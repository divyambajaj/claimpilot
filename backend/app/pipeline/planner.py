"""Question planner: ask only about missing fields, or uncertain AND decision-relevant ones (section 7)."""

import calendar
import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import Category, FindingKind, LineStatus, PayeeType, PaymentMethod, Severity
from app.domain.models import Claim, Finding, LineItem, Question
from app.domain.state import derive_line_status
from app.pipeline.extract import FX_TO_INR
from app.rules.derived import FACT_TO_FIELD, line_facts
from app.rules.dsl import RuleSet
from app.rules.engine import DayKey, evaluate, merge_resolutions

# Fields the planner may ask about, in a stable order.
ASKABLE = (
    "total_amount",
    "date",
    "category",
    "attendees_count",
    "city",
    "payment_method",
    "vendor_gstin",
    "payee_type",
)
CHOICES = {
    "category": [c.value for c in Category],
    "payment_method": [p.value for p in PaymentMethod if p != PaymentMethod.UNKNOWN],
    "payee_type": [p.value for p in PayeeType if p != PayeeType.UNKNOWN],
}
DUPLICATE_CHOICES = ["Same expense, drop it", "Different, keep both"]
# shortcut: one representative metro and non-metro city; derive from ruleset city lists if rules diversify.
CITY_ALTERNATIVES = ("Mumbai", "Nashik")


@dataclass(frozen=True)
class PlanContext:
    ruleset: RuleSet
    today: dt.date
    prior_day_totals: dict[DayKey, float] = field(default_factory=dict)
    tau: float = 0.75
    max_questions: int = 3
    payer_names: tuple[str, ...] = ()  # the claimant's profile name and the company (payer check)


@dataclass(frozen=True)
class Outcome:
    status: LineStatus
    reimbursable: int
    fired: frozenset[str]


@dataclass
class Plan:
    asked: list[Question]
    queued: list[Question]
    assumed: dict[str, list[str]]  # line_id -> fields judged not decision-relevant

    @property
    def all(self) -> list[Question]:
        return self.asked + self.queued


def sticky(findings: list[Finding]) -> list[Finding]:
    """Findings produced at ingest time (duplicates, UPI links) survive re-evaluation."""
    return [f for f in findings if f.kind == FindingKind.DUPLICATE or f.rule_id == "UPI_LINK"]


def active(line: LineItem) -> bool:
    return not (line.user_excluded or line.linked_to_line_id or line.error)


def outcome(line: LineItem, others: list[LineItem], ctx: PlanContext) -> Outcome:
    result = evaluate(
        [*others, line], ctx.ruleset, ctx.today, ctx.prior_day_totals, ctx.payer_names
    ).lines.get(line.id)
    if result is None:
        return Outcome(LineStatus.EXCLUDED, 0, frozenset())
    findings = sticky(line.findings) + merge_resolutions(line.findings, result.findings)
    status = derive_line_status(line.model_copy(update={"findings": findings}))
    reimbursable = 0 if status == LineStatus.EXCLUDED else round(result.reimbursable_inr)
    return Outcome(status, reimbursable, result.fired)


def with_value(line: LineItem, name: str, value: Any) -> LineItem:
    """A copy of the line with one extracted field replaced (keeps amount/category in sync)."""
    extracted = line.extracted.model_copy(deep=True)
    extracted.field(name).value = value
    update: dict[str, Any] = {"extracted": extracted}
    if name == "total_amount":
        update["amount_inr"] = round(
            (value or 0.0) * FX_TO_INR.get(extracted.currency.value or "INR", 1.0), 2
        )
    if name == "category" and value is not None:
        update["category"] = Category(value)
    return line.model_copy(update=update)


def _shift_month(d: dt.date, months: int) -> dt.date:
    month = d.month - 1 + months
    year, month = d.year + month // 12, month % 12 + 1
    return d.replace(year=year, month=month, day=min(d.day, calendar.monthrange(year, month)[1]))


def counterfactuals(name: str, value: Any) -> list[Any]:
    """Plausible misreadings of `value` (section 7)."""
    alts: list[Any] = []
    if name == "total_amount":
        digits = f"{int(value)}"
        for i in range(len(digits) - 1):
            swapped = digits[:i] + digits[i + 1] + digits[i] + digits[i + 2 :]
            if swapped != digits and not swapped.startswith("0"):
                alts.append(float(swapped) + (value - int(value)))
        alts += [value * 10, value / 10]
    elif name == "date":
        if value.day <= 12 and value.day != value.month:
            alts.append(value.replace(day=value.month, month=value.day))
        alts += [_shift_month(value, -1), _shift_month(value, 1)]
    elif name == "attendees_count":
        alts = [n for n in (value - 1, value + 1, 1) if n >= 1 and n != value]
    elif name == "city":
        alts = [c for c in CITY_ALTERNATIVES if c.casefold() != str(value).casefold()]
    elif name == "vendor_gstin":
        alts = [None]
    elif name in CHOICES:
        current = value.value if hasattr(value, "value") else value
        alts = [c for c in CHOICES[name] if c != current]
    return list(dict.fromkeys(alts))


def _impact(base: Outcome, alt: Outcome, amount: float) -> float:
    status_change = 1.0 if base.status != alt.status else 0.0
    return abs(base.reimbursable - alt.reimbursable) / max(amount, 1.0) + status_change


def _reason(base: Outcome, alts: list[Outcome]) -> str:
    if any(a.reimbursable != base.reimbursable for a in alts):
        return "A different value would change the reimbursable amount."
    if any(a.status != base.status for a in alts):
        return "A different value would change whether this line can be submitted."
    rules = sorted({r for a in alts for r in a.fired.symmetric_difference(base.fired)})
    return f"A different value would change which policy rules apply ({', '.join(rules)})."


def _vendor(line: LineItem) -> str:
    return line.extracted.vendor_name.value or "this"


def _value_prompt(line: LineItem, name: str) -> str:
    vendor, current = _vendor(line), line.extracted.field(name).value
    seen = f" I read {current}." if current is not None else ""
    prompts = {
        "total_amount": f"What is the total on the {vendor} bill?{seen}",
        "date": f"What date is on the {vendor} bill?{seen}",
        "attendees_count": f"How many people were at the {vendor} meal?",
        "city": f"Which city was the {vendor} expense in?",
        "category": f"What kind of expense is the {vendor} bill?",
        "payment_method": f"How was the {vendor} bill paid?",
        "vendor_gstin": f"What GSTIN is printed on the {vendor} invoice?",
        "vendor_name": "Who was this paid to? Enter the business name on the bill.",
        "payee_type": f"Was the {vendor} payment made to a business or to a person?",
    }
    return prompts.get(name, f"What is the {name.replace('_', ' ')} on the {vendor} bill?")


def _question(line: LineItem, name: str, voi: float, reason: str) -> Question:
    return Question(
        id=f"q:{line.id}:{name}",
        line_id=line.id,
        field=name,
        prompt=_value_prompt(line, name),
        kind="choice" if name in CHOICES else "value",
        choices=CHOICES.get(name),
        voi_score=round(voi, 4),
        reason=reason,
    )


def _finding_question(line: LineItem, f: Finding) -> Question | None:
    if f.resolution != "open":
        return None
    if f.kind == FindingKind.DUPLICATE:
        return Question(
            id=f"q:{line.id}:duplicate",
            line_id=line.id,
            field="duplicate",
            prompt=f"{f.message} Is it the same expense?",
            kind="confirm_duplicate",
            choices=DUPLICATE_CHOICES,
            voi_score=round(0.9 * float(f.evidence.get("score", 1.0)), 4),
            reason="Duplicates are not reimbursed twice.",
            finding_id=f.id,
        )
    if f.kind == FindingKind.MISSING and f.severity == Severity.WARN:  # e.g. a payment with no bill
        return Question(
            id=f"q:{line.id}:{f.rule_id}",
            line_id=line.id,
            field=f.rule_id or "justification",
            prompt=f"{f.message} Add it to this claim and it is linked automatically, or explain why there is"
            " none.",
            kind="justify_flag",
            voi_score=0.7,
            reason=f"Policy {f.citation.section if f.citation else ''}".strip() + " needs a bill.",
            finding_id=f.id,
        )
    if f.kind == FindingKind.POLICY and f.severity == Severity.WARN:
        ask = "" if f.message.endswith("?") else " Add a short justification for Finance."
        return Question(
            id=f"q:{line.id}:{f.rule_id}",
            line_id=line.id,
            field=f.rule_id or "justification",
            prompt=f"{f.message}{ask}",
            kind="justify_flag",
            voi_score=0.6 if f.evidence.get("action") in ("cap", "require_justification") else 0.5,
            reason=f"Policy {f.citation.section if f.citation else ''}".strip()
            + " asks for a justification.",
            finding_id=f.id,
        )
    return None


def plan(claim: Claim, ctx: PlanContext) -> Plan:
    candidates: list[Question] = []
    assumed: dict[str, list[str]] = {}
    lines = [line for line in claim.lines if active(line)]
    for line in lines:
        others = [o for o in lines if o.id != line.id]
        asked_fields: set[str] = set()
        blocked = any(f.severity == Severity.BLOCK and f.resolution == "open" for f in line.findings)
        facts = line_facts(line, ctx.today, ctx.payer_names)

        # A. required by policy and missing -> always ask (not on a blocked line: it is not reimbursed anyway)
        for fact in [] if blocked else ctx.ruleset.required_for(line.category):
            name = FACT_TO_FIELD.get(fact)
            if not name or name in asked_fields:
                continue
            # a payment screenshot's payee stands in for the vendor name
            value = facts.get(fact) if fact == "vendor_name" else line.extracted.field(name).value
            if value is None:
                candidates.append(_question(line, name, 1.0, "Required by the expense policy."))
                asked_fields.add(name)

        # B. low confidence -> ask only if a plausible misreading changes the decision
        base = outcome(line, others, ctx)
        for name in ASKABLE:
            f = line.extracted.field(name)
            if name in asked_fields or f.value is None or f.origin == "user" or f.confidence >= ctx.tau:
                continue
            alt_outcomes = [
                outcome(with_value(line, name, alt), others, ctx) for alt in counterfactuals(name, f.value)
            ]
            if all(a == base for a in alt_outcomes):
                assumed.setdefault(line.id, []).append(name)
                continue
            impact = max(_impact(base, a, line.amount_inr) for a in alt_outcomes)
            voi = (1 - f.confidence) * (0.5 + 0.5 * min(impact, 1.0))
            candidates.append(_question(line, name, voi, _reason(base, alt_outcomes)))

        # C. open findings the user can resolve (a blocked line is excluded; its card shows the fix path)
        if not blocked:
            candidates += [q for f in line.findings if (q := _finding_question(line, f))]

    amounts = {line.id: line.amount_inr for line in claim.lines}
    unique: dict[tuple[str, str], Question] = {}
    for q in candidates:
        unique.setdefault((q.line_id, q.field), q)
    ranked = sorted(unique.values(), key=lambda q: (-q.voi_score, -amounts.get(q.line_id, 0.0), q.id))
    return Plan(ranked[: ctx.max_questions], ranked[ctx.max_questions :], assumed)
