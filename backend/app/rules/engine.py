"""Deterministic rules engine: executes a RuleSet against a claim's lines. Pure functions, no I/O."""

import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import Category, FindingKind, Severity
from app.domain.models import Finding, LineItem
from app.rules.derived import line_facts
from app.rules.dsl import Cond, Rule, RuleSet

DayKey = tuple[dt.date, Category]


@dataclass
class LineOutcome:
    category: Category
    reimbursable_inr: float
    findings: list[Finding] = field(default_factory=list)

    @property
    def fired(self) -> frozenset[str]:
        return frozenset(f.rule_id for f in self.findings if f.rule_id)


@dataclass
class Evaluation:
    lines: dict[str, LineOutcome]
    claim_findings: list[Finding]


def _coerce(actual: Any, expected: Any) -> Any:
    if isinstance(actual, dt.date) and isinstance(expected, str):
        return dt.date.fromisoformat(expected)
    if isinstance(actual, str) and isinstance(expected, str):
        return expected.casefold()
    return expected


def _norm(value: Any) -> Any:
    return value.casefold() if isinstance(value, str) else value


def eval_cond(cond: Cond, facts: dict[str, Any]) -> bool:
    if cond.all is not None:
        return all(eval_cond(c, facts) for c in cond.all)
    if cond.any is not None:
        return any(eval_cond(c, facts) for c in cond.any)
    if cond.not_ is not None:
        return not eval_cond(cond.not_, facts)
    actual = facts.get(cond.field or "")
    match cond.op:
        case "is_null":
            return actual is None
        case "not_null":
            return actual is not None
        case "eq":
            return _norm(actual) == _coerce(actual, cond.value)
        case "ne":
            return _norm(actual) != _coerce(actual, cond.value)
        case "in":
            return _norm(actual) in [_coerce(actual, v) for v in cond.value]
        case "not_in":
            return _norm(actual) not in [_coerce(actual, v) for v in cond.value]
        case "regex":
            return actual is not None and re.search(str(cond.value), str(actual)) is not None
    if actual is None:
        return False
    expected = _coerce(actual, cond.value)
    try:
        match cond.op:
            case "gt":
                return actual > expected
            case "gte":
                return actual >= expected
            case "lt":
                return actual < expected
            case "lte":
                return actual <= expected
    except TypeError:
        return False
    raise ValueError(f"unsupported op {cond.op}")


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_message(template: str, values: dict[str, Any]) -> str:
    return template.format_map(_SafeDict({k: _fmt(v) for k, v in values.items() if v is not None}))


def _finding(rule: Rule, owner: str, values: dict[str, Any], **evidence: Any) -> Finding:
    action = rule.action
    kind = FindingKind.MISSING if action.type == "require_field" else FindingKind.POLICY
    severity = Severity.BLOCK if action.type == "block" else rule.severity
    return Finding(
        id=f"{owner}:{rule.id}",
        kind=kind,
        severity=severity,
        rule_id=rule.id,
        message=render_message(rule.message_template, {**values, "cap_inr": action.cap_inr}),
        citation=rule.citation,
        evidence={"action": action.type, **evidence},
    )


def _applies(rule: Rule, category: Category) -> bool:
    return rule.category == "any" or rule.category == category


def _active(line: LineItem) -> bool:
    return not (line.user_excluded or line.linked_to_line_id or line.error)


def _cap(outcome: LineOutcome, allowed: float) -> float:
    allowed = max(0.0, round(allowed, 2))
    before = outcome.reimbursable_inr
    outcome.reimbursable_inr = min(before, allowed)
    return before - outcome.reimbursable_inr


def evaluate(
    lines: list[LineItem],
    ruleset: RuleSet,
    today: dt.date,
    prior_day_totals: dict[DayKey, float] | None = None,
    payer_names: tuple[str, ...] = (),
) -> Evaluation:
    """Evaluate every active line. `prior_day_totals` are reimbursed amounts from earlier submitted claims;
    `payer_names` are who may pay for a claimant's expenses (profile name, company)."""
    prior_day_totals = prior_day_totals or {}
    active = [line for line in lines if _active(line)]
    facts = {line.id: line_facts(line, today, payer_names) for line in active}
    outcomes = {line.id: LineOutcome(line.category, line.amount_inr) for line in active}

    for rule in (r for r in ruleset.rules if r.scope == "line" and r.action.type == "set_category"):
        for line in active:
            if _applies(rule, outcomes[line.id].category) and eval_cond(rule.when, facts[line.id]):
                outcomes[line.id].category = rule.action.category  # type: ignore[assignment]
                facts[line.id]["category"] = rule.action.category.value  # type: ignore[union-attr]

    for rule in ruleset.rules:
        if rule.scope == "line" and rule.action.type != "set_category":
            for line in active:
                _apply_line_rule(rule, line.id, facts[line.id], outcomes[line.id])
    # a blocked line is not reimbursed, so it must not count towards daily, vendor or claim totals
    payable = [x for x in active if not any(f.severity == Severity.BLOCK for f in outcomes[x.id].findings)]
    for rule in ruleset.rules:
        if rule.scope == "day_category":
            _apply_group_rule(rule, payable, facts, outcomes, prior_day_totals)
        elif rule.scope == "vendor_day":
            _apply_vendor_day_rule(rule, payable, facts, outcomes)

    claim_findings = [
        f for r in ruleset.rules if r.scope == "claim" for f in _apply_claim_rule(r, payable, outcomes)
    ]

    for outcome in outcomes.values():
        if any(f.severity == Severity.BLOCK for f in outcome.findings):
            outcome.reimbursable_inr = 0.0
    return Evaluation(outcomes, claim_findings)


def _apply_line_rule(rule: Rule, line_id: str, f: dict[str, Any], outcome: LineOutcome) -> None:
    if not _applies(rule, outcome.category) or not eval_cond(rule.when, f):
        return
    action = rule.action
    if action.type == "require_field":
        name = action.field or ""
        if f.get(name) is not None and f.get(f"{name}_valid") is not False:
            return
        outcome.findings.append(_finding(rule, line_id, f, field=name))
        return
    if action.type == "cap":
        attendees = max(f.get("attendees_count") or 1, 1)
        allowed = action.cap_inr * attendees if action.cap_basis == "per_person" else action.cap_inr  # type: ignore[operator]
        over = _cap(outcome, allowed)
        if over <= 0:
            return
        outcome.findings.append(
            _finding(
                rule, line_id, f, cap_basis=action.cap_basis, allowed_inr=allowed, over_by_inr=round(over, 2)
            )
        )
        return
    outcome.findings.append(
        _finding(rule, line_id, f, needs_justification=action.type == "require_justification")
    )


def _apply_group_rule(
    rule: Rule,
    active: list[LineItem],
    facts: dict[str, dict[str, Any]],
    outcomes: dict[str, LineOutcome],
    prior: dict[DayKey, float],
) -> None:
    groups: dict[DayKey, list[LineItem]] = defaultdict(list)
    for line in active:
        date, category = facts[line.id]["date"], outcomes[line.id].category
        if date is not None and _applies(rule, category):
            groups[(date, category)].append(line)
    for (date, category), members in sorted(groups.items()):
        already = prior.get((date, category), 0.0)
        total = already + sum(outcomes[m.id].reimbursable_inr for m in members)
        group_facts = {**facts[members[0].id], "amount_inr": total, "category": category.value}
        if not eval_cond(rule.when, group_facts):
            continue
        if rule.action.type == "cap":
            remaining = (rule.action.cap_inr or 0.0) - already
            for m in members:
                before = outcomes[m.id].reimbursable_inr
                over = _cap(outcomes[m.id], remaining)
                remaining -= outcomes[m.id].reimbursable_inr
                if over > 0:
                    outcomes[m.id].findings.append(
                        _finding(
                            rule,
                            m.id,
                            {**facts[m.id], "total_inr": total},
                            cap_basis=rule.action.cap_basis,
                            group_total_inr=round(total, 2),
                            over_by_inr=round(over, 2),
                            reimbursable_before_inr=before,
                        )
                    )
        else:
            for m in members:
                outcomes[m.id].findings.append(_finding(rule, m.id, {**facts[m.id], "total_inr": total}))


def _vendor_key(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").casefold())


def _apply_vendor_day_rule(
    rule: Rule, active: list[LineItem], facts: dict[str, dict[str, Any]], outcomes: dict[str, LineOutcome]
) -> None:
    """Split-bill check: several bills from one vendor on one day, judged on their combined amount."""
    groups: dict[tuple[dt.date, str], list[LineItem]] = defaultdict(list)
    for line in active:
        f = facts[line.id]
        vendor = _vendor_key(f["vendor_name"])
        if f["date"] is not None and vendor and _applies(rule, outcomes[line.id].category):
            groups[(f["date"], vendor)].append(line)
    for members in groups.values():
        amounts = [m.amount_inr for m in members]
        group = {
            **facts[members[0].id],
            "amount_inr": round(sum(amounts), 2),
            "total_inr": round(sum(amounts), 2),
            "line_count": len(members),
            "max_line_amount": max(amounts),
        }
        if not eval_cond(rule.when, group):
            continue
        ids = [m.id for m in members]
        for m in members:
            outcomes[m.id].findings.append(
                _finding(
                    rule,
                    m.id,
                    {**facts[m.id], **{k: group[k] for k in ("total_inr", "line_count")}},
                    group_line_ids=ids,
                    group_total_inr=group["total_inr"],
                )
            )


def _apply_claim_rule(rule: Rule, active: list[LineItem], outcomes: dict[str, LineOutcome]) -> list[Finding]:
    members = [line for line in active if _applies(rule, outcomes[line.id].category)]
    if not members:
        return []
    total = sum(outcomes[m.id].reimbursable_inr for m in members)
    claim_facts = {"amount_inr": total, "total_inr": total, "category": rule.category}
    if not eval_cond(rule.when, claim_facts):
        return []
    if rule.action.type != "cap":
        return [_finding(rule, "claim", claim_facts)]
    remaining = rule.action.cap_inr or 0.0
    for m in members:
        over = _cap(outcomes[m.id], remaining)
        remaining -= outcomes[m.id].reimbursable_inr
        if over > 0:
            outcomes[m.id].findings.append(
                _finding(rule, m.id, claim_facts, cap_basis=rule.action.cap_basis, over_by_inr=round(over, 2))
            )
    return []


def merge_resolutions(previous: list[Finding], fresh: list[Finding]) -> list[Finding]:
    """Keep the user's earlier resolution (justified, overridden...) for findings that fire again."""
    resolved = {f.id: f for f in previous if f.resolution != "open"}
    merged = []
    for f in fresh:
        old = resolved.get(f.id)
        merged.append(
            f.model_copy(update={"resolution": old.resolution, "justification": old.justification})
            if old
            else f
        )
    return merged
