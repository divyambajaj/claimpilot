"""Rule DSL, derived facts, engine semantics (incl. golden files), citations and the compiler."""

import datetime as dt
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import REPO_ROOT
from app.domain.enums import Category, FindingKind, Severity
from app.domain.models import Finding
from app.domain.repo import Repo
from app.rules.citations import locate
from app.rules.compiler import CompileError, compile_policy, smoke_test
from app.rules.derived import canonical_city, line_facts
from app.rules.dsl import Action, Cond, RuleSet
from app.rules.engine import eval_cond, evaluate, merge_resolutions, render_message
from tests.factories import NOW, TODAY, VALID_GSTIN, FakeProvider, make_line

RULESET = RuleSet.model_validate_json((REPO_ROOT / "data" / "rulesets" / "acme_v1.json").read_text())
POLICY_TEXT = (REPO_ROOT / "data" / "policies" / "acme_india_travel_policy.md").read_text()
GOLDEN = Path(__file__).parents[1] / "golden" / "rules_findings"
BAD_GSTIN = VALID_GSTIN[:14] + ("A" if VALID_GSTIN[14] != "A" else "B")


def fired(lines, **kw) -> dict[str, set[str]]:
    result = evaluate(lines, RULESET, TODAY, **kw)
    return {lid: set(o.fired) for lid, o in result.lines.items()}


class TestDsl:
    def test_valid_and_alias(self) -> None:
        c = Cond.model_validate({"not": {"field": "city", "op": "is_null"}})
        assert c.not_ is not None
        assert "not" in c.model_dump(by_alias=True, exclude_none=True)

    @pytest.mark.parametrize(
        "bad",
        [
            {"field": "salary", "op": "eq", "value": 1},
            {"field": "city", "op": "approx", "value": 1},
            {"op": "eq", "value": 1},
            {"field": "city", "op": "in", "value": "Pune"},
            {},
            {"all": [], "any": []},
        ],
    )
    def test_rejects_invalid_conditions(self, bad: dict) -> None:
        with pytest.raises(ValidationError):
            Cond.model_validate(bad)

    @pytest.mark.parametrize(
        "bad",
        [
            {"type": "cap", "cap_inr": -1, "cap_basis": "line"},
            {"type": "cap"},
            {"type": "require_field"},
            {"type": "set_category"},
        ],
    )
    def test_rejects_invalid_actions(self, bad: dict) -> None:
        with pytest.raises(ValidationError):
            Action.model_validate(bad)

    def test_ruleset_unique_ids_and_helpers(self) -> None:
        data = RULESET.model_dump(by_alias=True)
        data["rules"].append(data["rules"][0])
        with pytest.raises(ValidationError, match="unique"):
            RuleSet.model_validate(data)
        assert RULESET.rule("MEALS_CAP_PER_PERSON") is not None
        assert RULESET.rule("NOPE") is None
        assert RULESET.required_for(Category.MEALS) == ["date", "amount_inr", "attendees_count"]

    FACTS = {"amount_inr": 900.0, "city": "Pune", "date": dt.date(2026, 10, 3), "flag": True, "gstin": None}

    @pytest.mark.parametrize(
        ("cond", "expected"),
        [
            ({"field": "amount_inr", "op": "gt", "value": 800}, True),
            ({"field": "amount_inr", "op": "lte", "value": 800}, False),
            ({"field": "amount_inr", "op": "gte", "value": 900}, True),
            ({"field": "amount_inr", "op": "lt", "value": 901}, True),
            ({"field": "city", "op": "eq", "value": "PUNE"}, True),
            ({"field": "city", "op": "ne", "value": "Pune"}, False),
            ({"field": "city", "op": "in", "value": ["Mumbai", "pune"]}, True),
            ({"field": "city", "op": "not_in", "value": ["Mumbai"]}, True),
            ({"field": "city", "op": "regex", "value": "^Pu"}, True),
            ({"field": "date", "op": "gte", "value": "2026-10-01"}, True),
            ({"field": "vendor_gstin", "op": "is_null"}, True),
            ({"field": "vendor_gstin", "op": "not_null"}, False),
            ({"field": "vendor_gstin", "op": "gt", "value": 1}, False),
            ({"field": "city", "op": "gt", "value": 5}, False),
            (
                {
                    "all": [
                        {"field": "amount_inr", "op": "gt", "value": 1},
                        {"field": "city", "op": "eq", "value": "x"},
                    ]
                },
                False,
            ),
            (
                {
                    "any": [
                        {"field": "amount_inr", "op": "gt", "value": 1},
                        {"field": "city", "op": "eq", "value": "x"},
                    ]
                },
                True,
            ),
            ({"not": {"field": "city", "op": "eq", "value": "x"}}, True),
        ],
    )
    def test_evaluation_table(self, cond: dict, expected: bool) -> None:
        assert eval_cond(Cond.model_validate(cond), self.FACTS) is expected


class TestDerived:
    def test_facts(self) -> None:
        facts = line_facts(
            make_line(total_amount=3000.0, attendees_count=4, date=dt.date(2026, 10, 3)), TODAY
        )
        assert facts["per_person_amount"] == 750.0
        assert facts["days_since_expense"] == 7
        assert facts["is_weekend"] is True  # 3 Oct 2026 is a Saturday
        assert facts["vendor_gstin_valid"] is True
        assert facts["payment_method"] == "card"

    def test_missing_values(self) -> None:
        facts = line_facts(
            make_line(
                date=None, attendees_count=None, vendor_gstin=BAD_GSTIN, payment_method=None, doc_type=None
            ),
            TODAY,
        )
        assert facts["days_since_expense"] is None and facts["is_weekend"] is None
        assert facts["per_person_amount"] == 1000.0
        assert facts["vendor_gstin_valid"] is False
        assert facts["payment_method"] is None and facts["doc_type"] is None

    def test_city_aliases(self) -> None:
        assert canonical_city(" new delhi ") == "Delhi"
        assert canonical_city("BANGALORE") == "Bengaluru"
        assert canonical_city("nashik") == "Nashik"
        assert canonical_city(None) is None


class TestEnginePerRule:
    def test_meal_cap_per_person(self) -> None:
        line = make_line(total_amount=3780.0, attendees_count=4)
        out = evaluate([line], RULESET, TODAY).lines["L1"]
        assert out.fired == {"MEALS_CAP_PER_PERSON"}
        assert out.reimbursable_inr == 3000.0
        f = out.findings[0]
        assert f.severity == Severity.WARN
        assert f.citation.section == "4.2 Meals"
        assert "945" in f.message
        assert fired([make_line(total_amount=1400.0, attendees_count=2)]) == {"L1": set()}

    def test_gst_invoice_block(self) -> None:
        big = {"total_amount": 6490.0, "category": "office", "date": dt.date(2026, 10, 2)}
        assert fired([make_line(vendor_gstin=BAD_GSTIN, **big)]) == {"L1": {"GST_INVOICE_ABOVE_5000"}}
        assert fired([make_line(vendor_gstin=None, **big)]) == {"L1": {"GST_INVOICE_ABOVE_5000"}}
        assert fired([make_line(**big)]) == {"L1": set()}
        blocked = evaluate([make_line(vendor_gstin=None, **big)], RULESET, TODAY).lines["L1"]
        assert blocked.reimbursable_inr == 0.0
        assert blocked.findings[0].kind == FindingKind.MISSING
        assert blocked.findings[0].severity == Severity.BLOCK

    def test_submission_window_and_ninety_day_block(self) -> None:
        assert fired([make_line(date=TODAY - dt.timedelta(days=45))]) == {"L1": {"SUBMISSION_WINDOW_30D"}}
        old = fired([make_line(date=TODAY - dt.timedelta(days=120))])
        assert old == {"L1": {"SUBMISSION_WINDOW_30D", "EXPENSE_OLDER_THAN_90D"}}

    def test_upi_proof(self) -> None:
        hotel = {"category": "lodging", "city": "Nashik", "total_amount": 3500.0, "payment_method": "upi"}
        assert fired([make_line(**hotel)]) == {"L1": {"UPI_PROOF_FOR_CASHLESS"}}
        assert fired([make_line(has_proof_of_payment=True, **hotel)]) == {"L1": set()}

    def test_cash_justification(self) -> None:
        assert fired([make_line(payment_method="cash", total_amount=2500.0, attendees_count=4)]) == {
            "L1": {"CASH_ABOVE_2000_JUSTIFY"}
        }

    def test_lodging_caps(self) -> None:
        metro = evaluate(
            [make_line(category="lodging", city="Bangalore", total_amount=8064.0)], RULESET, TODAY
        )
        assert metro.lines["L1"].fired == {"LODGING_CAP_METRO"}
        assert metro.lines["L1"].reimbursable_inr == 6000.0
        other = evaluate([make_line(category="lodging", city="Nashik", total_amount=4500.0)], RULESET, TODAY)
        assert other.lines["L1"].fired == {"LODGING_CAP_NON_METRO"}
        assert other.lines["L1"].reimbursable_inr == 4000.0
        assert fired([make_line(category="lodging", city=None, total_amount=4500.0)]) == {"L1": set()}

    def test_local_travel_day_aggregation_across_claims(self) -> None:
        rides = [
            make_line("R1", category="travel_local", total_amount=700.0, payment_method="upi"),
            make_line("R2", category="travel_local", total_amount=600.0, payment_method="upi"),
        ]
        assert fired(rides) == {"R1": set(), "R2": set()}
        prior = {(dt.date(2026, 10, 3), Category.TRAVEL_LOCAL): 500.0}
        result = evaluate(rides, RULESET, TODAY, prior)
        assert result.lines["R1"].reimbursable_inr == 700.0
        assert result.lines["R2"].reimbursable_inr == 300.0
        assert result.lines["R2"].fired == {"LOCAL_TRAVEL_DAILY_CAP"}
        assert result.lines["R1"].fired == frozenset()

    def test_fuel_claim_cap(self) -> None:
        fuel = [
            make_line(f"F{i}", category="fuel", total_amount=2000.0, payment_method="card") for i in range(3)
        ]
        result = evaluate(fuel, RULESET, TODAY)
        assert [result.lines[f"F{i}"].reimbursable_inr for i in range(3)] == [2000.0, 2000.0, 1000.0]
        assert result.lines["F2"].fired == {"FUEL_CAP_PER_CLAIM"}
        assert result.claim_findings == []

    def test_phone_and_weekend_office(self) -> None:
        assert fired([make_line(category="internet_phone", total_amount=1299.0)]) == {
            "L1": {"PHONE_INTERNET_MONTHLY_CAP"}
        }
        assert fired([make_line(category="office", total_amount=300.0, date=dt.date(2026, 10, 4))]) == {
            "L1": {"OFFICE_SUPPLIES_WEEKEND"}
        }

    def test_inactive_lines_skipped(self) -> None:
        lines = [
            make_line("A", user_excluded=True),
            make_line("B", linked_to_line_id="X"),
            make_line("C", error="x"),
        ]
        assert evaluate(lines, RULESET, TODAY).lines == {}


class TestEngineMisc:
    def _custom(self, rules: list[dict]) -> RuleSet:
        data = RULESET.model_dump(by_alias=True)
        cite = data["rules"][0]["citation"]
        base = {
            "title": "t",
            "category": "any",
            "scope": "line",
            "severity": "warn",
            "message_template": "m",
            "citation": cite,
            "confidence": 1,
        }
        data["rules"] = [{**base, **r} for r in rules]
        return RuleSet.model_validate(data)

    def test_set_category_and_claim_flag(self) -> None:
        rs = self._custom(
            [
                {
                    "id": "RECAT",
                    "when": {"field": "vendor_gstin", "op": "regex", "value": "^27"},
                    "action": {"type": "set_category", "category": "office"},
                },
                {
                    "id": "BIG_CLAIM",
                    "scope": "claim",
                    "when": {"field": "amount_inr", "op": "gt", "value": 1500},
                    "action": {"type": "flag"},
                    "message_template": "Claim total {total_inr}",
                },
                {
                    "id": "DAY_FLAG",
                    "scope": "day_category",
                    "category": "office",
                    "when": {"field": "amount_inr", "op": "gt", "value": 1500},
                    "action": {"type": "flag"},
                },
            ]
        )
        result = evaluate([make_line("A"), make_line("B")], rs, TODAY)
        assert result.lines["A"].category == Category.OFFICE
        assert [f.id for f in result.claim_findings] == ["claim:BIG_CLAIM"]
        assert result.claim_findings[0].message == "Claim total 2,000"
        assert result.lines["A"].fired == {"DAY_FLAG"}

    def test_render_message(self) -> None:
        assert (
            render_message("{a} {b} {c} {missing}", {"a": 1234.5, "b": 7, "c": "x"})
            == "1,234.50 7 x {missing}"
        )

    def test_determinism(self) -> None:
        lines = [
            make_line(total_amount=3780.0, attendees_count=4),
            make_line("L2", category="lodging", city="Pune", total_amount=9000.0),
        ]

        def dump():
            return [
                o.model_dump(mode="json")
                for r in evaluate(lines, RULESET, TODAY).lines.values()
                for o in r.findings
            ]

        assert json.dumps(dump()) == json.dumps(dump())

    def test_merge_resolutions(self) -> None:
        old = [
            Finding(
                id="x",
                kind=FindingKind.POLICY,
                severity=Severity.WARN,
                message="m",
                resolution="justified",
                justification="client dinner",
            )
        ]
        fresh = [
            Finding(id="x", kind=FindingKind.POLICY, severity=Severity.WARN, message="m2"),
            Finding(id="y", kind=FindingKind.POLICY, severity=Severity.WARN, message="m3"),
        ]
        merged = merge_resolutions(old, fresh)
        assert (merged[0].resolution, merged[0].justification, merged[0].message) == (
            "justified",
            "client dinner",
            "m2",
        )
        assert merged[1].resolution == "open"


GOLDEN_CASES = {
    "team_dinner_over_cap": [make_line(total_amount=3780.0, attendees_count=4)],
    "hotel_metro_with_upi_proof": [
        make_line(
            category="lodging",
            city="Bengaluru",
            total_amount=8064.0,
            payment_method="upi",
            has_proof_of_payment=True,
        )
    ],
    "office_invalid_gstin_cash": [
        make_line(
            category="office",
            vendor_gstin=BAD_GSTIN,
            total_amount=6490.0,
            payment_method="cash",
            date=dt.date(2026, 10, 2),
        )
    ],
    "rides_over_daily_cap": [
        make_line(f"R{i}", category="travel_local", total_amount=650.0, payment_method="upi")
        for i in range(3)
    ],
    "late_and_stale": [make_line("A", date=dt.date(2026, 8, 20)), make_line("B", date=dt.date(2026, 6, 1))],
}


@pytest.mark.parametrize("case", sorted(GOLDEN_CASES))
def test_golden_findings(case: str) -> None:
    result = evaluate(GOLDEN_CASES[case], RULESET, TODAY)
    actual = {
        lid: {
            "reimbursable_inr": o.reimbursable_inr,
            "findings": [f.model_dump(mode="json") for f in o.findings],
        }
        for lid, o in sorted(result.lines.items())
    }
    path = GOLDEN / f"{case}.json"
    if os.environ.get("UPDATE_GOLDEN") or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(actual, indent=2, ensure_ascii=False) + "\n")
    assert actual == json.loads(path.read_text())


class TestCitations:
    QUOTE = "Meals are reimbursed up to INR 750 per person per meal."

    def test_exact(self) -> None:
        c = locate("4.2 Meals", self.QUOTE, POLICY_TEXT)
        assert POLICY_TEXT[c.char_start : c.char_end] == self.QUOTE
        assert c.verified

    def test_whitespace_normalised(self) -> None:
        text = POLICY_TEXT.replace(self.QUOTE, "Meals are reimbursed\n  up to INR 750 per person per meal.")
        c = locate("4.2", self.QUOTE, text)
        assert c.verified
        assert " ".join(text[c.char_start : c.char_end].split()) == self.QUOTE

    def test_fuzzy_unverified_and_miss(self) -> None:
        c = locate(
            "4.2", "Meals are reimbursed up to INR 750 per person per meal", POLICY_TEXT.replace("750", "75O")
        )
        assert c is not None
        assert c.verified is False
        assert locate("x", "Employees receive a free unicorn every Friday.", POLICY_TEXT) is None


def _draft(quote: str = TestCitations.QUOTE) -> dict:
    return {
        "required_fields": {"any": ["date"]},
        "rules": [
            {
                "id": "MEAL_CAP",
                "title": "Meal cap",
                "category": "meals",
                "scope": "line",
                "when": {"field": "per_person_amount", "op": "gt", "value": 750},
                "action": {"type": "cap", "cap_inr": 750, "cap_basis": "per_person"},
                "severity": "warn",
                "message_template": "over",
                "citation": {"section": "4.2 Meals", "quote": quote},
                "confidence": 0.9,
            },
            {
                "id": "MADE_UP",
                "title": "x",
                "category": "any",
                "scope": "line",
                "when": {"field": "amount_inr", "op": "gt", "value": 1},
                "action": {"type": "flag"},
                "severity": "info",
                "message_template": "x",
                "citation": {"section": "9", "quote": "Employees receive a free unicorn every Friday."},
                "confidence": 0.2,
            },
        ],
    }


class TestCompiler:
    async def test_compiles_verifies_and_stores(self, make_client, repo: Repo) -> None:
        ruleset, dropped = await compile_policy(
            make_client(FakeProvider([_draft()])), repo, "Acme", POLICY_TEXT, NOW
        )
        assert dropped == ["MADE_UP"]
        assert [r.id for r in ruleset.rules] == ["MEAL_CAP"]
        assert ruleset.version == 1
        assert ruleset.policy_sha256 == repo.get_policy(ruleset.policy_id).sha256
        assert ruleset.compiler_prompt_version == "v1"
        assert repo.active_ruleset() == ruleset

    async def test_repair_path(self, make_client, repo: Repo) -> None:
        provider = FakeProvider([{"rules": "nope"}, _draft()])
        ruleset, _ = await compile_policy(make_client(provider), repo, "Acme", POLICY_TEXT, NOW)
        assert len(provider.requests) == 2
        assert ruleset.rules

    async def test_invalid_thrice(self, make_client, repo: Repo) -> None:
        with pytest.raises(CompileError):
            await compile_policy(make_client(FakeProvider([{"x": 1}] * 3)), repo, "Acme", POLICY_TEXT, NOW)

    async def test_no_verifiable_rules(self, make_client, repo: Repo) -> None:
        draft = _draft("Totally invented sentence about llamas and budgets.")
        with pytest.raises(CompileError, match="verbatim"):
            await compile_policy(make_client(FakeProvider([draft])), repo, "Acme", POLICY_TEXT, NOW)

    def test_smoke_test_passes_shipped_ruleset(self) -> None:
        smoke_test(RULESET)

    def test_versions_and_activation(self, repo: Repo) -> None:
        repo.save_ruleset(RULESET, active=True)
        v2 = RULESET.model_copy(update={"version": 2})
        repo.save_ruleset(v2, active=True)
        assert repo.active_ruleset().version == 2
        repo.activate_ruleset(1)
        assert repo.active_ruleset().version == 1
        assert [(rs.version, active) for rs, active in repo.list_rulesets()] == [(1, True), (2, False)]
        assert repo.next_ruleset_version() == 3
