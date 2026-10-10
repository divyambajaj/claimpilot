"""Value-of-information question planner and the pure reassess step."""

import datetime as dt

from app.domain.enums import FindingKind, LineStatus, Severity
from app.domain.models import Finding
from app.pipeline.orchestrator import AnswerError, count_asked, reassess, set_field
from app.pipeline.planner import PlanContext, counterfactuals, plan, with_value
from tests.factories import NOW, TODAY, make_claim, make_line
from tests.unit.test_rules import RULESET

CTX = PlanContext(RULESET, TODAY)


def _dup(score: float = 0.9, severity: Severity = Severity.WARN) -> Finding:
    return Finding(
        id="L1:DUPLICATE",
        kind=FindingKind.DUPLICATE,
        severity=severity,
        rule_id="DUPLICATE",
        message="Looks like a duplicate.",
        evidence={"score": score, "layer": "fuzzy"},
    )


class TestCounterfactuals:
    def test_amount(self) -> None:
        assert counterfactuals("total_amount", 3780.0) == [7380.0, 3870.0, 3708.0, 37800.0, 378.0]
        assert 100.0 not in counterfactuals("total_amount", 100.0)

    def test_date(self) -> None:
        alts = counterfactuals("date", dt.date(2026, 10, 3))
        assert alts == [dt.date(2026, 3, 10), dt.date(2026, 9, 3), dt.date(2026, 11, 3)]
        assert counterfactuals("date", dt.date(2026, 1, 31))[1:] == [dt.date(2026, 2, 28)]
        assert counterfactuals("date", dt.date(2026, 12, 25)) == [dt.date(2026, 11, 25), dt.date(2027, 1, 25)]

    def test_others(self) -> None:
        assert counterfactuals("attendees_count", 1) == [2]
        assert counterfactuals("city", "Mumbai") == ["Nashik"]
        assert counterfactuals("vendor_gstin", "X") == [None]
        assert "meals" not in counterfactuals("category", "meals")
        assert counterfactuals("payment_method", "upi") == ["card", "cash"]
        assert counterfactuals("vendor_name", "x") == []

    def test_with_value_syncs(self) -> None:
        line = with_value(make_line(), "total_amount", 50.0)
        assert line.amount_inr == 50.0
        assert with_value(make_line(), "category", "lodging").category == "lodging"


class TestPlan:
    def test_required_null_is_asked(self) -> None:
        p = plan(make_claim([make_line(attendees_count=None)]), CTX)
        assert [(q.field, q.voi_score, q.kind) for q in p.asked] == [("attendees_count", 1.0, "value")]
        assert p.asked[0].reason == "Required by the expense policy."

    def test_low_confidence_irrelevant_is_assumed(self) -> None:
        p = plan(make_claim([make_line(conf={"city": 0.4, "payment_method": 0.5})]), CTX)
        assert p.asked == []
        assert set(p.assumed["L1"]) == {"city", "payment_method"}

    def test_low_confidence_relevant_is_asked_with_reason(self) -> None:
        line = make_line(total_amount=1400.0, attendees_count=2, conf={"attendees_count": 0.5})
        p = plan(make_claim([line]), CTX)
        q = p.asked[0]
        assert (q.field, q.kind) == ("attendees_count", "value")
        assert "reimbursable amount" in q.reason
        assert 0.25 < q.voi_score <= 0.5

    def test_choice_question_for_category(self) -> None:
        line = make_line(category="lodging", city="Pune", total_amount=5000.0, conf={"category": 0.3})
        q = plan(make_claim([line]), CTX).asked[0]
        assert (q.field, q.kind) == ("category", "choice")
        assert "lodging" in q.choices

    def test_findings_questions_and_ranking(self) -> None:
        dinner = make_line("L1", total_amount=3780.0, attendees_count=4, findings=[_dup(0.9)])
        late = make_line("L2", date=TODAY - dt.timedelta(days=40), total_amount=500.0, attendees_count=1)
        missing = make_line("L3", attendees_count=None, total_amount=200.0)
        hotel = make_line("L4", category="lodging", city="Pune", total_amount=9000.0)
        claim = reassess(make_claim([dinner, late, missing, hotel]), CTX)
        p = plan(claim, CTX)
        assert [(q.line_id, q.kind) for q in p.asked] == [
            ("L3", "value"),
            ("L1", "confirm_duplicate"),
            ("L4", "justify_flag"),
        ]
        assert [(q.line_id, q.field) for q in p.queued] == [
            ("L1", "MEALS_CAP_PER_PERSON"),
            ("L2", "SUBMISSION_WINDOW_30D"),
        ]
        assert p.asked[1].voi_score == 0.81

    def test_blocked_line_gets_no_finding_question(self) -> None:
        line = make_line(findings=[_dup(1.0, Severity.BLOCK)])
        assert plan(make_claim([line]), CTX).asked == []

    def test_user_fields_and_inactive_lines_skipped(self) -> None:
        line = make_line(conf={"attendees_count": 0.2})
        line.extracted.attendees_count.origin = "user"
        excluded = make_line("X", attendees_count=None, user_excluded=True)
        assert plan(make_claim([line, excluded]), CTX).asked == []


class TestReassess:
    def test_statuses_totals_and_assumed(self) -> None:
        dinner = make_line("L1", total_amount=3780.0, attendees_count=4, conf={"city": 0.5})
        ride = make_line(
            "L2", category="travel_local", total_amount=486.0, payment_method="upi", vendor_name="RydeGo"
        )
        missing = make_line("L3", attendees_count=None)
        claim = reassess(make_claim([dinner, ride, missing]), CTX)
        status = {x.id: x.status for x in claim.lines}
        assert status == {"L1": LineStatus.FLAGGED, "L2": LineStatus.COMPLETE, "L3": LineStatus.MISSING_INFO}
        assert claim.lines[0].assumed_fields == ["city"]
        assert claim.lines[0].extracted.city.origin == "assumed"
        assert claim.total_inr == 3780 + 486 + 1000
        assert claim.reimbursable_inr == 3000 + 486 + 750  # unknown attendees counts as one person
        assert claim.status == "draft"
        assert len(claim.open_questions) == 3  # L1 cap, L3 attendees, L3 cap

    def test_resolution_survives_reassess_and_claim_ready(self) -> None:
        claim = reassess(make_claim([make_line(total_amount=3780.0, attendees_count=4)]), CTX)
        finding = claim.lines[0].findings[0]
        resolved = finding.model_copy(update={"resolution": "justified", "justification": "client"})
        claim.lines[0].findings = [resolved]
        claim = reassess(claim, CTX)
        assert claim.lines[0].findings[0].resolution == "justified"
        assert claim.status == "ready_to_submit"
        assert claim.lines[0].reimbursable_inr == 3000.0

    def test_count_asked(self) -> None:
        claim = reassess(make_claim([make_line(attendees_count=None)]), CTX)  # missing value + meal cap
        counted = count_asked(claim, set())
        assert counted.questions_asked == 2
        assert counted.lines[0].questions_asked == 2
        assert count_asked(counted, {q.id for q in counted.open_questions}).questions_asked == 2


class TestSetField:
    def test_user_value_and_label(self) -> None:
        line, label = set_field(make_line(conf={"date": 0.4}), "date", "05/10/2026", NOW)
        f = line.extracted.date
        assert (f.value, f.confidence, f.origin) == (dt.date(2026, 10, 5), 1.0, "user")
        assert f.history[0].old_value == "2026-10-03"
        assert (label.predicted, label.corrected, label.confidence) == ("2026-10-03", "2026-10-05", 0.4)

    def test_amount_and_category_sync(self) -> None:
        line, _ = set_field(make_line(), "total_amount", "₹2,500", NOW)
        assert line.amount_inr == 2500.0
        line, _ = set_field(line, "category", "lodging", NOW)
        assert line.category == "lodging"
        _, label = set_field(line, "category", "lodging", NOW)
        assert label is None

    def test_invalid(self) -> None:
        for name, value in [("date", "someday"), ("category", "spaceship"), ("raw_text", "x"), ("nope", 1)]:
            try:
                set_field(make_line(), name, value, NOW)
            except AnswerError:
                continue
            raise AssertionError(f"{name}={value} accepted")
