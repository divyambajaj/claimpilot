"""Eval metrics (section 13): field accuracy, duplicate P/R, violation accuracy, UPI links, cost/latency.

Inputs are ground-truth rows (`ground_truth.jsonl`) paired with the `LineItem` the real pipeline produced.
A field cell is scored when the truth or the prediction is non-null (both empty = nothing to score); a list
in the truth means any of those values is correct.
"""

import itertools
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from app.domain.enums import FindingKind, LineStatus, Severity
from app.domain.models import Claim, FieldMetric, LineItem, Span
from app.evaluation.calibration import Pair
from app.observability.metrics import _llm_latency, percentile, rate

AMOUNT_FIELDS = {"subtotal", "tax_amount", "total_amount"}
AMOUNT_TOL = 0.5
SCORED_SEVERITIES = {Severity.WARN, Severity.BLOCK}


@dataclass
class Observed:
    truth: dict[str, Any]
    line: LineItem


def _plain(v: Any) -> Any:
    return getattr(v, "value", v)


def _text(v: Any) -> str:
    return re.sub(r"[^\w]+", " ", str(v).casefold()).strip()


def field_match(name: str, truth: Any, pred: Any) -> bool:
    if isinstance(truth, list):
        return any(field_match(name, t, pred) for t in truth)
    pred = _plain(pred)
    if truth is None or pred is None:
        return truth is None and pred is None
    if name in AMOUNT_FIELDS:
        return abs(float(pred) - float(truth)) <= AMOUNT_TOL
    if name == "attendees_count":
        return int(pred) == int(truth)
    if name in ("vendor_gstin", "invoice_number", "upi_txn_id"):
        return re.sub(r"[^0-9A-Z]", "", str(pred).upper()) == re.sub(r"[^0-9A-Z]", "", str(truth).upper())
    return _text(pred) == _text(truth)  # dates are ISO strings on both sides after str()


def score_fields(observed: list[Observed]) -> tuple[dict[str, FieldMetric], float, float, list[Pair]]:
    """Per-field accuracy, macro (mean over fields), micro (over all cells), and calibration pairs."""
    cells: dict[str, list[Pair]] = defaultdict(list)
    for obs in observed:
        for name, truth in obs.truth["fields"].items():
            got = obs.line.extracted.field(name)
            if truth is None and got.value is None:
                continue
            cells[name].append((got.confidence, field_match(name, truth, got.value)))
    per_field = {
        name: FieldMetric(
            accuracy=round(sum(ok for _, ok in pairs) / len(pairs), 4),
            n=len(pairs),
            mean_confidence=round(sum(c for c, _ in pairs) / len(pairs), 4),
        )
        for name, pairs in sorted(cells.items())
    }
    all_pairs = [p for pairs in cells.values() for p in pairs]
    macro = round(sum(m.accuracy for m in per_field.values()) / len(per_field), 4) if per_field else 0.0
    micro = round(sum(ok for _, ok in all_pairs) / len(all_pairs), 4) if all_pairs else 0.0
    return per_field, macro, micro, all_pairs


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def duplicate_scores(observed: list[Observed], fixture_of: dict[str, str]) -> dict[str, Any]:
    """Flagged pairs vs ground-truth pairs (same dup_group); flagged decoys are false positives."""
    groups: dict[str, list[str]] = defaultdict(list)
    for obs in observed:
        if obs.truth.get("dup_group"):
            groups[obs.truth["dup_group"]].append(obs.truth["id"])
    truth = {_pair(a, b) for ids in groups.values() for a, b in itertools.combinations(sorted(ids), 2)}
    flagged: dict[tuple[str, str], str] = {}
    for obs in observed:
        for f in obs.line.findings:
            other = fixture_of.get(str(f.evidence.get("matched_line_id")))
            if f.kind == FindingKind.DUPLICATE and other:
                flagged[_pair(obs.truth["id"], other)] = str(f.evidence.get("layer"))
    tp = [p for p in flagged if p in truth]
    by_layer: dict[str, int] = defaultdict(int)
    for p in tp:
        by_layer[flagged[p]] += 1
    return {
        "precision": round(len(tp) / len(flagged), 4) if flagged else 1.0,
        "recall": round(len(tp) / len(truth), 4) if truth else 1.0,
        "true_pairs": len(truth),
        "flagged_pairs": len(flagged),
        "caught_by_layer": dict(sorted(by_layer.items())),
        "false_positives": [
            {"pair": list(p), "layer": flagged[p]} for p in sorted(flagged) if p not in truth
        ],
        "missed": [list(p) for p in sorted(truth - set(flagged))],
    }


def fired_rules(line: LineItem) -> set[str]:
    return {
        f.rule_id
        for f in line.findings
        if f.rule_id
        and f.kind in (FindingKind.POLICY, FindingKind.MISSING)
        and f.severity in SCORED_SEVERITIES
    }


def violation_scores(observed: list[Observed]) -> dict[str, Any]:
    """Per line: set-equality of fired WARN/BLOCK rule ids vs expected; plus per-rule precision/recall."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    exact, mismatches = 0, []
    for obs in observed:
        expected, fired = set(obs.truth["expected_rules"]), fired_rules(obs.line)
        exact += expected == fired
        if expected != fired:
            mismatches.append(
                {"fixture": obs.truth["id"], "expected": sorted(expected), "fired": sorted(fired)}
            )
        for rule in expected | fired:
            key = "tp" if rule in expected and rule in fired else "fn" if rule in expected else "fp"
            counts[rule][key] += 1
    per_rule = {
        rule: {
            "precision": round(c["tp"] / (c["tp"] + c["fp"]), 4) if c["tp"] + c["fp"] else 1.0,
            "recall": round(c["tp"] / (c["tp"] + c["fn"]), 4) if c["tp"] + c["fn"] else 1.0,
            "support": c["tp"] + c["fn"],
        }
        for rule, c in sorted(counts.items())
    }
    return {"accuracy": rate(exact, len(observed)), "per_rule": per_rule, "mismatches": mismatches}


def upi_link_scores(observed: list[Observed], fixture_of: dict[str, str]) -> dict[str, Any]:
    """UPI screenshot -> invoice links made by the pipeline vs planted pairs."""
    expected = {
        (o.truth["id"], o.truth["upi_pair"])
        for o in observed
        if o.truth["template"] == "upi" and o.truth.get("upi_pair")
    }
    made = {
        (o.truth["id"], fixture_of.get(o.line.linked_to_line_id, "?"))
        for o in observed
        if o.line.linked_to_line_id
    }
    hit = len(expected & made)
    return {
        "precision": round(hit / len(made), 4) if made else 1.0,
        "recall": round(hit / len(expected), 4) if expected else 1.0,
        "expected": len(expected),
        "linked": len(made),
    }


def run_stats(claims: list[Claim], spans: list[Span], n_receipts: int) -> dict[str, float]:
    """Questions per claim, auto-completion and LLM latency/tokens/cost (recorded values when replayed)."""
    lines = [x for c in claims for x in c.lines]
    ok = [s for s in spans if s.name == "llm" and s.status == "ok"]
    latencies = [_llm_latency(s) for s in ok]
    tokens = sum(
        int(s.attributes.get("tokens_in") or 0) + int(s.attributes.get("tokens_out") or 0) for s in ok
    )
    cost = sum(float(s.attributes.get("cost_usd") or 0) for s in ok)
    n = max(n_receipts, 1)
    return {
        "questions_per_claim": rate(sum(c.questions_asked for c in claims), len(claims)),
        "auto_completion_rate": rate(
            sum(x.status == LineStatus.COMPLETE and x.questions_asked == 0 for x in lines), len(lines)
        ),
        "p50_latency_ms": round(percentile(latencies, 50), 1),
        "p95_latency_ms": round(percentile(latencies, 95), 1),
        "mean_tokens": round(tokens / n, 1),
        "cost_usd_per_receipt": round(cost / n, 6),
        "llm_calls": len(ok),
        "llm_retries": sum(s.name == "llm" and s.status == "retry" for s in spans),
    }
