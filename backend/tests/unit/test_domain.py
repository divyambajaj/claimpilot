"""State derivation, repository round-trips, tracing and cost."""

import datetime as dt

import pytest

from app.domain.enums import ClaimStatus, FindingKind, LineStatus, Severity
from app.domain.models import CorrectionLabel, Document, Finding, PolicyDoc, Question
from app.domain.repo import NotFoundError, Repo
from app.domain.state import (
    IllegalTransitionError,
    derive_claim_status,
    derive_line_status,
    ensure_editable,
    ensure_submittable,
)
from app.observability.cost import estimate_cost_usd, price_for
from app.observability.tracing import Tracer
from tests.factories import NOW, make_claim, make_line


def _finding(severity: Severity, kind: FindingKind = FindingKind.POLICY, resolution: str = "open") -> Finding:
    return Finding(id="f", kind=kind, severity=severity, message="m", resolution=resolution)


def _q(kind: str, line_id: str = "L1") -> Question:
    return Question(id="q", line_id=line_id, field="date", prompt="?", kind=kind, voi_score=1, reason="r")


class TestLineStatus:
    def test_clean_line_is_complete(self) -> None:
        assert derive_line_status(make_line()) == LineStatus.COMPLETE

    def test_error(self) -> None:
        assert derive_line_status(make_line(error="boom")) == LineStatus.ERROR

    @pytest.mark.parametrize(
        "line_kwargs",
        [
            {"user_excluded": True},
            {"linked_to_line_id": "L9"},
            {"findings": [_finding(Severity.BLOCK)]},
            {"findings": [_finding(Severity.WARN, FindingKind.DUPLICATE, "confirmed")]},
        ],
    )
    def test_excluded(self, line_kwargs: dict) -> None:
        assert derive_line_status(make_line(**line_kwargs)) == LineStatus.EXCLUDED

    def test_missing_info_from_value_question(self) -> None:
        assert derive_line_status(make_line(), [_q("value")]) == LineStatus.MISSING_INFO
        assert derive_line_status(make_line(), [_q("value", line_id="other")]) == LineStatus.COMPLETE

    def test_flagged_then_resolved(self) -> None:
        assert derive_line_status(make_line(findings=[_finding(Severity.WARN)])) == LineStatus.FLAGGED
        dup = _finding(Severity.INFO, FindingKind.DUPLICATE)
        assert derive_line_status(make_line(findings=[dup])) == LineStatus.FLAGGED
        for resolution in ("acknowledged", "justified", "overridden"):
            resolved = _finding(Severity.WARN, resolution=resolution)
            assert derive_line_status(make_line(findings=[resolved])) == LineStatus.COMPLETE

    def test_info_does_not_flag(self) -> None:
        assert derive_line_status(make_line(findings=[_finding(Severity.INFO)])) == LineStatus.COMPLETE


class TestClaimStatus:
    def _line(self, status: LineStatus, line_id: str = "L1"):
        return make_line(line_id, status=status)

    def test_ready_when_settled(self) -> None:
        claim = make_claim([self._line(LineStatus.COMPLETE), self._line(LineStatus.EXCLUDED, "L2")])
        assert derive_claim_status(claim) == ClaimStatus.READY_TO_SUBMIT

    @pytest.mark.parametrize(
        "claim",
        [
            make_claim([]),
            make_claim([make_line(status=LineStatus.EXCLUDED)]),
            make_claim([make_line(status=LineStatus.FLAGGED)]),
            make_claim([make_line(status=LineStatus.COMPLETE)], processing=1),
            make_claim([make_line(status=LineStatus.COMPLETE)], open_questions=[_q("justify_flag")]),
            make_claim([make_line(status=LineStatus.COMPLETE)], findings=[_finding(Severity.BLOCK)]),
        ],
    )
    def test_draft(self, claim) -> None:
        assert derive_claim_status(claim) == ClaimStatus.DRAFT

    def test_terminal_states_stick(self) -> None:
        claim = make_claim([], status=ClaimStatus.SUBMITTED)
        assert derive_claim_status(claim) == ClaimStatus.SUBMITTED
        with pytest.raises(IllegalTransitionError):
            ensure_editable(claim)

    def test_submit_guard(self) -> None:
        with pytest.raises(IllegalTransitionError):
            ensure_submittable(make_claim([]))
        ensure_submittable(make_claim([], status=ClaimStatus.READY_TO_SUBMIT))


class TestRepo:
    def test_claim_round_trip_and_line_replacement(self, repo: Repo) -> None:
        claim = make_claim([make_line("L1"), make_line("L2", total_amount=250.0)])
        repo.save_claim(claim)
        loaded = repo.get_claim("C1")
        assert [line.id for line in loaded.lines] == ["L1", "L2"]
        assert loaded.lines[1].extracted.total_amount.value == 250.0
        repo.save_claim(claim.model_copy(update={"lines": [claim.lines[1]]}))
        assert [line.id for line in repo.get_claim("C1").lines] == ["L2"]
        assert [c.id for c in repo.list_claims("demo-user")] == ["C1"]
        assert repo.list_claims("someone-else") == []
        with pytest.raises(NotFoundError):
            repo.get_claim("nope")

    def test_user_lines_near_window(self, repo: Repo) -> None:
        old = make_claim(
            [make_line("A", status=LineStatus.COMPLETE, date=dt.date(2026, 9, 1))], claim_id="C0"
        )
        excluded = make_line("B", status=LineStatus.EXCLUDED, date=dt.date(2026, 10, 1))
        far = make_line("C", status=LineStatus.COMPLETE, date=dt.date(2025, 1, 1))
        repo.save_claim(old.model_copy(update={"lines": [*old.lines, excluded, far]}))
        repo.save_claim(make_claim([make_line("D")], claim_id="C1"))
        near = repo.user_lines_near("demo-user", dt.date(2026, 10, 3), 90, exclude_claim_id="C1")
        assert [line.id for line in near] == ["A"]

    def test_prior_day_category_totals(self, repo: Repo) -> None:
        line = make_line("A", status=LineStatus.COMPLETE, total_amount=900.0)
        repo.save_claim(make_claim([line], claim_id="C0", status=ClaimStatus.SUBMITTED))
        repo.save_claim(make_claim([make_line("B", status=LineStatus.COMPLETE)], claim_id="C2"))
        totals = repo.prior_day_category_totals("demo-user", exclude_claim_id="C1")
        assert totals == {(dt.date(2026, 10, 3), line.category): 900.0}
        assert repo.prior_day_category_totals("nobody", "C1") == {}

    def test_documents_policies_labels(self, repo: Repo) -> None:
        doc = Document(
            id="D1",
            claim_id="C1",
            filename="a.png",
            mime="image/png",
            sha256="s",
            dhash="0" * 16,
            dhash_rotations=["0" * 16] * 4,
            width=1,
            height=1,
            stored_path="/tmp/a.png",
        )
        repo.save_document(doc)
        assert repo.get_document("D1") == doc
        assert repo.get_documents(["D1", "zz"]) == {"D1": doc}
        policy = PolicyDoc(id="P1", name="n", text="t", sha256="h", created_at=NOW)
        repo.save_policy(policy)
        assert repo.get_policy("P1") == policy and repo.list_policies() == [policy]
        label = CorrectionLabel(
            id="X", line_id="L1", field="date", predicted="a", confidence=0.4, corrected="b", created_at=NOW
        )
        repo.add_label(label)
        assert repo.list_labels() == [label]
        for getter in (repo.get_document, repo.get_policy, repo.get_eval_run, repo.get_submission):
            with pytest.raises(NotFoundError):
                getter("missing")
        with pytest.raises(NotFoundError):
            repo.get_ruleset(99)


class TestTracing:
    def test_nested_spans_and_errors(self, tracer: Tracer) -> None:
        with tracer.trace("claim", "C1") as trace_id:
            with tracer.span("extract", doc="D1") as outer, tracer.span("llm") as inner:
                inner.set(tokens_in=5, obj=object())
            with pytest.raises(ValueError, match="bad rule"), tracer.span("rules"):
                raise ValueError("bad rule")
        trace = tracer.get_trace(trace_id)
        by_name = {s.name: s for s in trace.spans}
        assert by_name["llm"].parent_id == outer.id
        assert by_name["llm"].attributes["tokens_in"] == 5
        assert isinstance(by_name["llm"].attributes["obj"], str)
        assert by_name["rules"].status == "error" and "bad rule" in by_name["rules"].attributes["error"]
        assert [t.id for t in tracer.list_traces("C1")] == [trace_id]
        assert len(tracer.spans_since(NOW - dt.timedelta(days=3650))) == 3
        assert tracer.get_trace("nope") is None

    def test_span_without_trace_and_without_db(self) -> None:
        t = Tracer(None)
        with t.span("x") as span:
            span.set(a=1)
        assert t.get_trace("x") is None and t.list_traces() == [] and t.spans_since(NOW) == []


class TestCost:
    def test_prices(self) -> None:
        assert estimate_cost_usd("claude-sonnet-5-5", 1_000_000, 0) == 2.0
        assert price_for("gemini-2.5-flash-latest") == price_for("gemini-2.5-flash")
        assert price_for("unknown-model") == price_for("sonnet")
        assert estimate_cost_usd("sonnet", None, None) is None
