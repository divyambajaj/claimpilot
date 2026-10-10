"""Admin dashboard metrics, computed from stored claims, spans and eval runs (never estimated)."""

import datetime as dt
from collections import Counter, defaultdict
from statistics import quantiles
from typing import Any

from app.config import ImpactParams
from app.domain.enums import ClaimStatus, FindingKind, LineStatus, Severity
from app.domain.models import Claim, EvalRun, Span
from app.rules.dsl import RuleSet

LATENCY_BUCKET_MS = 2000
READY_OR_LATER = {
    ClaimStatus.READY_TO_SUBMIT,
    ClaimStatus.SUBMITTED,
    ClaimStatus.APPROVED,
    ClaimStatus.REJECTED,
}


def percentile(values: list[float], q: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    return float(quantiles(values, n=100, method="inclusive")[q - 1])


def rate(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def minutes_saved_per_claim(p: ImpactParams) -> float:
    return (p.manual_employee_min + p.manual_finance_min) - (p.agent_employee_min + p.agent_finance_min)


def _llm_latency(span: Span) -> float:
    recorded = span.attributes.get("latency_ms")
    return float(recorded) if recorded is not None else (span.end - span.start).total_seconds() * 1000


def overview(
    claims: list[Claim],
    spans: list[Span],
    eval_runs: list[EvalRun],
    ruleset: RuleSet | None,
    days: int,
    now: dt.datetime,
    impact: ImpactParams,
    fx_usd_inr: float,
) -> dict[str, Any]:
    since = now - dt.timedelta(days=days)
    claims = [c for c in claims if c.created_at >= since]
    lines = [x for c in claims for x in c.lines]
    llm = [s for s in spans if s.name == "llm"]
    ok_llm = [s for s in llm if s.status == "ok"]
    latencies = [_llm_latency(s) for s in ok_llm]
    total_cost_inr = sum(float(s.attributes.get("cost_usd") or 0) for s in ok_llm) * fx_usd_inr

    cost_by_day: dict[str, float] = defaultdict(float)
    for s in ok_llm:
        cost_by_day[s.start.date().isoformat()] += float(s.attributes.get("cost_usd") or 0) * fx_usd_inr
    claims_by_day = Counter(c.created_at.date().isoformat() for c in claims)

    titles = {r.id: r.title for r in ruleset.rules} if ruleset else {}
    violations = Counter(
        f.rule_id
        for x in lines
        for f in x.findings
        if f.kind in (FindingKind.POLICY, FindingKind.MISSING) and f.severity != Severity.INFO and f.rule_id
    )
    dup_layers: dict[str, list[float]] = {"perceptual": [], "fuzzy": [], "semantic": []}
    prevented = 0.0
    for x in lines:
        for f in x.findings:
            if f.kind != FindingKind.DUPLICATE:
                continue
            dup_layers.setdefault(str(f.evidence.get("layer")), []).append(x.amount_inr)
            if f.resolution == "confirmed" or (f.severity == Severity.BLOCK and f.resolution == "open"):
                prevented += x.amount_inr

    buckets = Counter(int(v // LATENCY_BUCKET_MS) * LATENCY_BUCKET_MS for v in latencies)
    start_day = since.date()
    return {
        "days": days,
        "kpis": {
            "claims_total": len(claims),
            "claims_today": sum(c.created_at.date() == now.date() for c in claims),
            "auto_completion_rate": rate(
                sum(x.status == LineStatus.COMPLETE and x.questions_asked == 0 for x in lines), len(lines)
            ),
            "first_pass_ready_rate": rate(
                sum(c.status in READY_OR_LATER and c.answers_received == 0 for c in claims), len(claims)
            ),
            "questions_per_claim": rate(sum(c.questions_asked for c in claims), len(claims)),
            "cost_per_claim_inr": round(total_cost_inr / len(claims), 2) if claims else 0.0,
            "p50_latency_ms": round(percentile(latencies, 50)),
            "p95_latency_ms": round(percentile(latencies, 95)),
            "error_rate": rate(sum(s.status == "error" for s in llm), len(llm)),
            "retry_rate": rate(sum(s.status == "retry" for s in llm), len(llm)),
            "time_saved_hours": round(len(claims) * minutes_saved_per_claim(impact) / 60, 1),
            "duplicate_inr_prevented": round(prevented, 2),
        },
        "claims_per_day": [
            {"date": d.isoformat(), "count": claims_by_day.get(d.isoformat(), 0)}
            for d in (start_day + dt.timedelta(days=i) for i in range(days + 1))
        ],
        "cost_trend": [
            {"date": day, "cost_per_claim_inr": round(cost / max(claims_by_day.get(day, 0), 1), 2)}
            for day, cost in sorted(cost_by_day.items())
        ],
        "latency_histogram": [{"bucket_ms": b, "count": n} for b, n in sorted(buckets.items())],
        "violations_by_rule": [
            {"rule_id": rid, "title": titles.get(rid, rid), "count": n} for rid, n in violations.most_common()
        ],
        "duplicates_by_layer": [
            {"layer": layer, "count": len(amounts), "amount_inr": round(sum(amounts), 2)}
            for layer, amounts in dup_layers.items()
            if layer in ("perceptual", "fuzzy", "semantic")
        ],
        "eval_trend": [
            {
                "run_id": r.id,
                "created_at": r.created_at.isoformat(),
                "field_accuracy": r.metrics.field_accuracy,
                "ece": r.metrics.ece,
            }
            for r in sorted(eval_runs, key=lambda r: r.created_at)
            if r.subset != "smoke"  # a smoke score is not comparable with the full-set trend
        ],
    }
