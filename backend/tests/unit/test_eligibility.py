"""Eligibility: payment screenshots without a bill, person-to-person transfers, personal spend, payer checks."""

import datetime as dt
import io
from pathlib import Path

import pytest
from PIL import Image

from app.api.sse import Broker
from app.config import Settings
from app.domain.enums import LineStatus, PayeeType
from app.finance_mock import MockFinance
from app.pipeline.orchestrator import Orchestrator, Upload, reassess
from app.pipeline.planner import PlanContext
from app.pipeline.validate.confidence import adjust_confidence, validation_findings
from app.pipeline.validate.payee import mask_local, payee_kind, vpa_kind
from app.rules.derived import name_matches, payer_matches
from app.rules.engine import evaluate
from tests.factories import NOW, TODAY, FakeProvider, extraction_payload, make_claim, make_line, make_receipt
from tests.unit.test_rules import RULESET

NAMES = ("Kavya Mehta", "Jio Platforms Limited")
CTX = PlanContext(RULESET, TODAY, payer_names=NAMES)
D = dt.date(2026, 10, 6)


def upi(line_id: str = "U1", **values) -> object:
    base = {
        "doc_type": "upi_screenshot",
        "payment_method": "upi",
        "vendor_gstin": None,
        "invoice_number": None,
        "date": D,
        "attendees_count": None,
        "payer_name": "K. Mehta",
        "payee_type": "merchant",
        "category": "other",
    }
    return make_line(line_id, **(base | values))


def fired(*lines) -> dict[str, set[str]]:
    result = evaluate(list(lines), RULESET, TODAY, payer_names=NAMES)
    return {k: set(v.fired) for k, v in result.lines.items()}


class TestNames:
    @pytest.mark.parametrize(
        ("payer", "ok"),
        [
            ("Kavya Mehta", True),
            ("K. Mehta", True),
            ("MEHTA KAVYA", True),
            ("Mr. Kavya Mehta (xx4821)", True),
            ("Mehta", True),
            ("Kavya Mehtaa", True),
            ("R. Iyer", False),
            ("K. Iyer", False),
            ("Kavya", True),
            ("Rohan Mehta", False),
        ],
    )
    def test_name_matches(self, payer: str, ok: bool) -> None:
        assert name_matches(payer, "Kavya Mehta") is ok

    def test_payer_matches(self) -> None:
        assert payer_matches(None, NAMES) is None
        assert payer_matches("R. Iyer", ()) is None
        assert payer_matches("JIO PLATFORMS LIMITED", NAMES) is True
        assert payer_matches("Acorn Traders", NAMES) is False
        assert name_matches("(xx12)", "Kavya Mehta") is False


class TestPayeeHeuristic:
    @pytest.mark.parametrize(
        ("local", "handle", "kind"),
        [
            ("paytmqr2810050501011abcd", "paytm", PayeeType.MERCHANT),
            ("Q123456789", "ybl", PayeeType.MERCHANT),
            ("ombk.aabc1234", "mbk", PayeeType.MERCHANT),
            ("shreeomsai1234567890", "ybl", PayeeType.MERCHANT),
            ("rohan.desai-1", "okhdfcbank", PayeeType.INDIVIDUAL),
            ("rohan.desai-1", "paynow", PayeeType.INDIVIDUAL),
            ("rohandesai", "okaxis", PayeeType.INDIVIDUAL),
            ("9876543210", "paynow", PayeeType.INDIVIDUAL),
            ("harbourviewres", "paynow", None),
        ],
    )
    def test_vpa_kind_is_stable_under_masking(self, local: str, handle: str, kind) -> None:
        assert vpa_kind(local, handle) == kind
        if kind != PayeeType.MERCHANT:  # merchant collection ids are never masked
            assert vpa_kind(mask_local(local), handle) == kind

    def test_mask_local(self) -> None:
        assert mask_local("rohan.desai-1") == "r****.*****-1"
        assert mask_local(mask_local("rohan.desai-1")) == "r****.*****-1"
        assert mask_local("ab") == "ab"

    def test_payee_kind(self) -> None:
        text = "Paid to\nRohan Desai\nrohan.desai-2@okpaynow\nFrom\nK. Mehta"
        assert payee_kind("Rohan Desai", text) == (PayeeType.INDIVIDUAL, True)
        assert payee_kind("Lakeview Unisex Salon", "Paid to Lakeview Unisex Salon") == (
            PayeeType.MERCHANT,
            False,
        )
        assert payee_kind("Rohan Desai", "Money Sent\nRohan Desai") == (PayeeType.INDIVIDUAL, True)
        assert payee_kind("Rohan Desai", "Paid to Rohan Desai") == (PayeeType.INDIVIDUAL, False)
        assert payee_kind(None, "nothing") == (None, False)

    def test_adjust_confidence(self) -> None:
        text = "Money Sent\nRohan Desai\nrohan.desai-2@okpaynow"
        llm_null = make_receipt(doc_type="upi_screenshot", payee_name="Rohan Desai", raw_text=text)
        filled = adjust_confidence(llm_null, TODAY).payee_type
        assert (filled.value, filled.confidence, filled.origin) == (PayeeType.INDIVIDUAL, 0.8, "validator")
        wrong = make_receipt(
            doc_type="upi_screenshot", payee_name="Rohan Desai", payee_type="merchant", raw_text=text
        )
        assert adjust_confidence(wrong, TODAY).payee_type.confidence == 0.5
        assert [f.rule_id for f in validation_findings(wrong, "L1", TODAY)] == ["VAL_PAYEE_MISMATCH"]
        agree = make_receipt(
            doc_type="upi_screenshot", payee_name="Rohan Desai", payee_type="individual", raw_text=text
        )
        assert adjust_confidence(agree, TODAY).payee_type.confidence == 0.99
        bill = make_receipt(payee_name="Rohan Desai", raw_text=text)  # an invoice: not checked
        assert adjust_confidence(bill, TODAY).payee_type.value is None


class TestRules:
    def test_cng_screenshot_needs_bill_and_trip_note(self) -> None:
        line = upi(vendor_name="Shree Ganesh Auto Care Centre", category="fuel", total_amount=687.08)
        assert fired(line) == {"U1": {"BILL_REQUIRED", "FUEL_TRIP_NOTE"}}

    def test_salon_is_blocked(self) -> None:
        line = upi(vendor_name="Lakeview Unisex Salon", category="personal", total_amount=300.0)
        result = evaluate([line], RULESET, TODAY, payer_names=NAMES).lines["U1"]
        assert "PERSONAL_EXPENSE_NOT_REIMBURSABLE" in result.fired
        assert result.reimbursable_inr == 0.0

    def test_recharge_not_in_employee_name(self) -> None:
        line = upi(
            vendor_name="Recharge of Mobile 98xxxxxx12",
            category="internet_phone",
            total_amount=490.8,
            payer_name="R. Iyer",
        )
        assert fired(line) == {"U1": {"BILL_REQUIRED", "MOBILE_BILL_IN_EMPLOYEE_NAME"}}
        own = line.model_copy(deep=True)
        own.extracted.payer_name.value = "Kavya Mehta"
        assert fired(own) == {"U1": {"BILL_REQUIRED"}}

    def test_p2p_transfer_is_blocked(self) -> None:
        line = upi(vendor_name=None, payee_name="Rohan Desai", payee_type="individual", total_amount=2800.0)
        assert "P2P_TRANSFER_NOT_REIMBURSABLE" in fired(line)["U1"]
        claim = reassess(make_claim([line]), CTX)
        assert claim.lines[0].status == LineStatus.EXCLUDED
        assert claim.open_questions == []  # blocked: no questions, the card says why

    def test_other_needs_purpose_and_payer_check(self) -> None:
        line = make_line(category="other", vendor_name="Acorn Traders", payer_name="R. Iyer")
        assert fired(line) == {"L1": {"OTHER_NEEDS_BUSINESS_PURPOSE", "PAYER_NOT_EMPLOYEE"}}
        noted = line.model_copy(update={"business_purpose": "Projector cable for the client demo"})
        assert fired(noted) == {"L1": {"PAYER_NOT_EMPLOYEE"}}

    def test_split_bills_same_vendor_day(self) -> None:
        a = make_line("A", category="office", total_amount=3000.0, vendor_name="Fort Stationery Mart", date=D)
        b = make_line("B", category="office", total_amount=2800.0, vendor_name="FORT STATIONERY MART", date=D)
        c = make_line("C", category="office", total_amount=900.0, vendor_name="Other Shop", date=D)
        out = evaluate([a, b, c], RULESET, TODAY)
        assert out.lines["A"].fired == {"SPLIT_BILL_SAME_VENDOR_DAY"} == out.lines["B"].fired
        assert out.lines["C"].fired == frozenset()
        evidence = out.lines["A"].findings[0].evidence
        assert evidence["group_total_inr"] == 5800.0 and evidence["group_line_ids"] == ["A", "B"]
        assert "2 bills" in out.lines["A"].findings[0].message
        big = make_line(
            "B", category="office", total_amount=5200.0, vendor_name="Fort Stationery Mart", date=D
        )
        assert "SPLIT_BILL_SAME_VENDOR_DAY" not in evaluate([a, big], RULESET, TODAY).lines["A"].fired

    def test_payee_question_when_heuristic_disagrees(self) -> None:
        line = upi(vendor_name=None, payee_name="Rohan Desai", total_amount=2800.0, conf={"payee_type": 0.5})
        claim = reassess(make_claim([line]), CTX)
        q = next(q for q in claim.open_questions if q.field == "payee_type")
        assert q.choices == ["merchant", "individual"] and "business or to a person" in q.prompt

    def test_vendor_name_required(self) -> None:
        claim = reassess(make_claim([make_line(vendor_name=None)]), CTX)
        assert [q.field for q in claim.open_questions if q.kind == "value"] == ["vendor_name"]


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (250, 250, 250)).save(buf, format="PNG")
    return buf.getvalue()


async def test_bill_and_trip_note_answers(tmp_path: Path, repo, tracer, make_client) -> None:
    """The CNG screenshot asks for its bill and a trip note; answers re-check without an LLM call."""
    settings = Settings(_env_file=None, DATA_DIR=tmp_path, EMPLOYEE_NAME="Kavya Mehta")
    payload = extraction_payload(
        doc_type="upi_screenshot",
        vendor_name="Shree Ganesh Auto Care Centre",
        vendor_gstin=None,
        invoice_number=None,
        date=D,
        total_amount=687.08,
        payment_method="upi",
        category="fuel",
        attendees_count=None,
        payee_type="merchant",
        payer_name="K. Mehta",
    )
    repo.save_ruleset(RULESET, active=True)
    orch = Orchestrator(
        settings,
        repo,
        make_client(FakeProvider([payload])),
        tracer,
        Broker(),
        MockFinance(repo, 0, 0),
        lambda: NOW,
    )
    claim = orch.create_claim("u1", "CNG")
    await orch.add_documents(claim.id, [Upload("cng.png", _png())])
    await orch.wait_idle()
    claim = repo.get_claim(claim.id)
    questions = {q.field: q for q in claim.open_questions}
    assert set(questions) == {"BILL_REQUIRED", "FUEL_TRIP_NOTE"}
    assert questions["BILL_REQUIRED"].prompt.startswith(
        "Attach the bill for this ₹687.08 payment to Shree Ganesh Auto Care Centre"
    )
    claim = await orch.answer(
        claim.id,
        [
            {"question_id": questions["FUEL_TRIP_NOTE"].id, "value": "Client visits in Thane, 6 Oct"},
            {"question_id": questions["BILL_REQUIRED"].id, "value": "Station gave no printed bill"},
        ],
    )
    line = claim.lines[0]
    assert line.business_purpose == "Client visits in Thane, 6 Oct"
    assert {f.rule_id: f.resolution for f in line.findings if f.rule_id} == {"BILL_REQUIRED": "justified"}
    assert line.status == LineStatus.COMPLETE and claim.status == "ready_to_submit"
    claim = await orch.edit_line(claim.id, line.id, {"business_purpose": ""})
    assert claim.lines[0].business_purpose is None
    assert any(q.field == "FUEL_TRIP_NOTE" for q in claim.open_questions)
