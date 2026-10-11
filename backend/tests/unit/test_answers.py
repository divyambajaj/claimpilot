"""Answer validation: non-answers are rejected, personal purposes block, a bill is never replaced by text."""

import datetime as dt
import io
from pathlib import Path

import pytest
from PIL import Image

from app.api.sse import Broker
from app.config import Settings
from app.domain.enums import Category, LineStatus, Severity
from app.domain.models import FieldEdit
from app.finance_mock import MockFinance
from app.pipeline.answers import check_text, declares_personal
from app.pipeline.orchestrator import AnswerError, Orchestrator, Upload, reassess
from app.pipeline.planner import PlanContext
from tests.factories import NOW, TODAY, FakeProvider, extraction_payload, make_claim, make_line
from tests.unit.test_rules import POLICY_TEXT, RULESET

DINNER = "Client dinner approved in advance by the department head."
TRIP = "Drove to the Thane client site and back on 6 Oct for the workshop."
D = dt.date(2026, 10, 6)


@pytest.mark.parametrize(
    ("text", "rule", "action", "status"),
    [
        # the demo script's answers
        (DINNER, "MEALS_CAP_PER_PERSON", "cap", "ok"),
        (TRIP, "FUEL_TRIP_NOTE", "require_justification", "ok"),
        ("Client meeting approved in advance by the department head.", "FUEL_TRIP_NOTE", None, "ok"),
        ("No receipt was issued at the toll plaza, paid by FASTag on the client visit", None, None, "ok"),
        ("Late because the bill was with the travel desk", "SUBMISSION_WINDOW_30D", None, "ok"),
        ("Drove my personal car to the Pune plant audit", "FUEL_TRIP_NOTE", None, "ok"),
        ("Worked through the public holiday at the client office", None, None, "ok"),
        ("This was not a personal expense, it was the Vashi vendor audit", None, None, "ok"),
        ("Third party courier for the project samples", None, None, "ok"),
        # refusals and non-answers, whole or dominant
        ("", None, None, "rejected"),
        ("   ", None, None, "rejected"),
        ("-", None, None, "rejected"),
        (".", None, None, "rejected"),
        ("no", None, None, "rejected"),
        ("No.", None, None, "rejected"),
        ("nope", None, None, "rejected"),
        ("no i wont", None, None, "rejected"),
        ("No, I won't", None, None, "rejected"),
        ("I will not provide one", None, None, "rejected"),
        ("n/a", None, None, "rejected"),
        ("NA", None, None, "rejected"),
        ("nil", None, None, "rejected"),
        ("none", None, None, "rejected"),
        ("nothing to say here sorry", None, None, "rejected"),
        ("idk", None, None, "rejected"),
        ("I don't know, not sure", None, None, "rejected"),
        ("skip", None, None, "rejected"),
        ("ok", None, None, "rejected"),
        ("test", None, None, "rejected"),
        ("asdf", None, None, "rejected"),
        ("no bill", None, None, "rejected"),
        ("no bill available", None, None, "rejected"),
        ("not available", None, None, "rejected"),
        # gibberish, too short, not words
        ("aaaaaaaaaaaaaaaaaaaa", None, None, "rejected"),
        ("sdfgh jklqw rtzxc vbnmp", None, None, "rejected"),
        ("test test test test", None, None, "rejected"),
        ("1234 5678 9012 3456 !!!", None, None, "rejected"),
        ("client meeting", None, None, "rejected"),
        ("Met the client team", "MEALS_CAP_PER_PERSON", "cap", "rejected"),  # caps need 6 words
        ("Fuel for the car this week", "FUEL_TRIP_NOTE", None, "rejected"),  # no place, client or route
        ("Client visits in Thane", "FUEL_TRIP_NOTE", None, "rejected"),  # under 6 words
        # a declared personal purpose is accepted as stated, and blocks
        ("vacation", None, None, "personal"),
        ("Family holiday in Goa", "FUEL_TRIP_NOTE", None, "personal"),
        ("Dinner with friends for a birthday", "MEALS_CAP_PER_PERSON", "cap", "personal"),
        ("weekend trip", None, None, "personal"),
        ("Bought it for my own use", None, None, "personal"),
        ("shopping", None, None, "personal"),
    ],
)
def test_check_text(text: str, rule: str | None, action: str | None, status: str) -> None:
    check = check_text(text, rule, action)
    assert check.status == status, (text, check.message)
    assert bool(check.message) == (status != "ok")


def test_rejection_message_is_plain_and_specific() -> None:
    assert check_text("no i wont").message == (
        "“no i wont” doesn't explain the expense. Add the business reason — who, where or which project."
    )
    assert "at least 6 words" in check_text("Met the client team", action="cap").message
    assert "where the trip went" in check_text("Fuel for the car this week", "FUEL_TRIP_NOTE").message


@pytest.mark.parametrize(
    ("text", "personal"),
    [(None, False), ("personal vehicle for the client visit", False), ("a party of four clients", False)],
)
def test_declares_personal_edges(text: str | None, personal: bool) -> None:
    assert declares_personal(text) is personal


CTX = PlanContext(RULESET, TODAY, payer_names=("Kavya Mehta", "Jio Platforms Limited"))


def test_personal_purpose_blocks_with_eligibility_citation() -> None:
    line = make_line("O1", category="other", vendor_gstin=None, total_amount=900.0, date=D)
    claim = reassess(make_claim([line.model_copy(update={"business_purpose": "vacation"})]), CTX)
    out = claim.lines[0]
    block = next(f for f in out.findings if f.rule_id == "PERSONAL_PURPOSE_DECLARED")
    assert (
        block.severity == Severity.BLOCK and block.message == "Declared purpose is personal: not reimbursable"
    )
    assert block.citation and block.citation.section.startswith("2.1") and block.citation.citation_verified
    assert POLICY_TEXT[block.citation.char_start : block.citation.char_end] == block.citation.quote
    assert out.status == LineStatus.EXCLUDED and out.reimbursable_inr == 0


def test_category_change_is_traced_with_the_rules_it_avoided() -> None:
    line = make_line("F1", category="fuel", vendor_gstin=None, total_amount=1200.0, date=D)
    assert "FUEL_TRIP_NOTE" in {f.rule_id for f in reassess(make_claim([line]), CTX).lines[0].findings}
    f = line.extracted.category
    f.history.append(FieldEdit(at=NOW, old_value="fuel", new_value="travel_local"))
    f.value, f.origin = Category.TRAVEL_LOCAL, "user"
    claim = reassess(make_claim([line.model_copy(update={"category": Category.TRAVEL_LOCAL})]), CTX)
    out = claim.lines[0]
    change = next(x for x in out.findings if x.rule_id == "CATEGORY_CHANGED_BY_EMPLOYEE")
    assert change.message == "Category changed from Fuel to Local travel by employee"
    assert change.severity == Severity.WARN
    assert change.evidence["avoided_rules"] == ["FUEL_TRIP_NOTE"]
    assert "FUEL_TRIP_NOTE" not in {x.rule_id for x in out.findings}
    q = next(q for q in claim.open_questions if q.field == "CATEGORY_CHANGED_BY_EMPLOYEE")
    assert q.kind == "justify_flag" and out.status == LineStatus.FLAGGED


# --- regression: the live-test answers that used to complete UPI-only lines ---------------------------


def _png(shade: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (shade, shade, shade)).save(buf, format="PNG")
    return buf.getvalue()


def _upi(vendor: str, amount: float, category: str, payer: str = "K. Mehta") -> dict:
    return extraction_payload(
        doc_type="upi_screenshot",
        vendor_name=vendor,
        vendor_gstin=None,
        invoice_number=None,
        date=D,
        total_amount=amount,
        payment_method="upi",
        category=category,
        attendees_count=None,
        payee_type="merchant",
        payer_name=payer,
    )


async def _claim(tmp_path: Path, repo, tracer, make_client, payloads: list[dict]):
    settings = Settings(_env_file=None, DATA_DIR=tmp_path, EMPLOYEE_NAME="Kavya Mehta")
    repo.save_ruleset(RULESET, active=True)
    orch = Orchestrator(
        settings,
        repo,
        make_client(FakeProvider(payloads)),
        tracer,
        Broker(),
        MockFinance(repo, 0, 0),
        lambda: NOW,
    )
    claim = orch.create_claim("u1", "Answers")
    uploads = [Upload(f"doc{i}.png", _png(200 + i * 20)) for i in range(len(payloads))]
    await orch.add_documents(claim.id, uploads)
    await orch.wait_idle()
    return orch, repo.get_claim(claim.id)


@pytest.fixture
async def upi_claim(tmp_path: Path, repo, tracer, make_client):
    """Three UPI screenshots with no bill: a stationery shop, a prepaid recharge paid by someone else, CNG."""
    payloads = [
        _upi("Sai Stationers", 420.0, "other"),
        _upi("Prepaid Recharge", 299.0, "internet_phone", payer="R. Iyer"),
        _upi("Shree Ganesh Auto Care Centre", 687.08, "fuel"),
    ]
    return await _claim(tmp_path, repo, tracer, make_client, payloads)


def _questions(claim) -> dict[tuple[str, str], str]:
    vendors = {x.id: x.extracted.vendor_name.value for x in claim.lines}
    return {(vendors[q.line_id], q.field): q.id for q in [*claim.open_questions]}


async def test_text_never_replaces_a_bill_and_nothing_is_saved(upi_claim) -> None:
    orch, claim = upi_claim
    qs = _questions(claim)
    bill = qs[("Sai Stationers", "BILL_REQUIRED")]
    with pytest.raises(AnswerError) as err:
        await orch.answer(claim.id, [{"question_id": bill, "value": "no bill available"}])
    assert err.value.errors == {
        bill: "A note can't replace the bill. Attach the bill, or choose “I don't have the bill”."
    }
    after = orch.get_claim(claim.id)
    assert after.model_dump(exclude={"updated_at"}) == claim.model_dump(exclude={"updated_at"})
    assert all(f.resolution == "open" for x in after.lines for f in x.findings)


async def test_no_i_wont_is_rejected_per_question(upi_claim) -> None:
    orch, claim = upi_claim
    # the user's answers to the bill, mobile-bill-in-name and paid-by-someone-else questions
    for value in ("no i wont", "no bill available"):
        answers = [{"question_id": q.id, "value": value} for q in claim.open_questions]
        with pytest.raises(AnswerError) as err:
            await orch.answer(claim.id, answers)
        assert set(err.value.errors) == {q.id for q in claim.open_questions}
    assert not any(x.status == LineStatus.COMPLETE for x in orch.get_claim(claim.id).lines)


async def test_payer_and_mobile_bill_refusals_are_rejected(tmp_path: Path, repo, tracer, make_client) -> None:
    bills = [
        extraction_payload(
            category="meals", vendor_gstin=None, total_amount=600.0, date=D, payer_name="R. Iyer"
        ),
        extraction_payload(
            category="internet_phone", vendor_gstin=None, total_amount=499.0, date=D, payer_name="R. Iyer"
        ),
    ]
    orch, claim = await _claim(tmp_path, repo, tracer, make_client, bills)
    fields = {q.field: q for q in claim.open_questions}
    assert {"PAYER_NOT_EMPLOYEE", "MOBILE_BILL_IN_EMPLOYEE_NAME"} <= set(fields)
    with pytest.raises(AnswerError) as err:
        await orch.answer(claim.id, [{"question_id": q.id, "value": "no i wont"} for q in fields.values()])
    assert set(err.value.errors) == {q.id for q in fields.values()}


async def test_user_case_answers_no_longer_complete_lines(upi_claim) -> None:
    orch, claim = upi_claim
    # round by round, as the user would: bill -> "I don't have the bill", purpose -> "vacation"
    for _ in range(4):
        claim = orch.get_claim(claim.id)
        if not claim.open_questions:
            break
        answers = []
        for q in claim.open_questions:
            if q.kind == "attach_document":
                answers.append({"question_id": q.id, "value": "I don't have the bill"})
            elif q.field == "OTHER_NEEDS_BUSINESS_PURPOSE":
                answers.append({"question_id": q.id, "value": "vacation"})
            elif q.kind == "justify_flag":
                answers.append({"question_id": q.id, "value": TRIP})
            else:
                answers.append({"question_id": q.id, "value": "merchant"})
        claim = await orch.answer(claim.id, answers)
    by_vendor = {x.extracted.vendor_name.value: x for x in claim.lines}
    assert all(x.status == LineStatus.EXCLUDED for x in claim.lines)
    assert claim.reimbursable_inr == 0 and claim.status == "draft"
    for x in claim.lines:
        bill = next(f for f in x.findings if f.rule_id == "BILL_REQUIRED")
        assert bill.severity == Severity.BLOCK and bill.resolution == "open"
    assert not any(f.resolution == "justified" and not f.validated for x in claim.lines for f in x.findings)
    assert by_vendor["Sai Stationers"].missing_documents == ["bill"]


async def test_vacation_purpose_blocks_the_line(tmp_path: Path, repo, tracer, make_client) -> None:
    bill = extraction_payload(category="other", vendor_gstin=None, total_amount=900.0, date=D)
    orch, claim = await _claim(tmp_path, repo, tracer, make_client, [bill])
    q = next(q for q in claim.open_questions if q.field == "OTHER_NEEDS_BUSINESS_PURPOSE")
    claim = await orch.answer(claim.id, [{"question_id": q.id, "value": "vacation"}])
    line = next(x for x in claim.lines if x.id == q.line_id)
    block = next(f for f in line.findings if f.rule_id == "PERSONAL_PURPOSE_DECLARED")
    assert block.severity == Severity.BLOCK and line.status == LineStatus.EXCLUDED
    assert not any(f.resolution == "justified" for f in line.findings)
    assert not any(x.line_id == line.id for x in claim.open_questions)


async def test_business_purpose_edit_is_validated(upi_claim) -> None:
    orch, claim = upi_claim
    fuel = next(x for x in claim.lines if x.category == "fuel")
    with pytest.raises(AnswerError) as err:
        await orch.edit_line(claim.id, fuel.id, {"business_purpose": "nope"})
    assert set(err.value.errors) == {"business_purpose"}
    claim = await orch.edit_line(claim.id, fuel.id, {"business_purpose": TRIP})
    assert next(x for x in claim.lines if x.id == fuel.id).business_purpose == TRIP
