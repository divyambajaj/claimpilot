"""Deterministic validators: adjust LLM confidence once after extraction; emit re-runnable findings."""

import datetime as dt

from app.domain.enums import DocType, FindingKind, PayeeType, Severity
from app.domain.models import EXTRACTED_FIELD_NAMES, ExtractedReceipt, Finding
from app.pipeline.validate.arithmetic import check_arithmetic
from app.pipeline.validate.dates import date_problem
from app.pipeline.validate.gstin import gstin_problem
from app.pipeline.validate.payee import payee_kind

QUALITY_PENALTY = {"blurry": 0.1, "partial": 0.1}
RECONCILE_BOOST = 0.15
MISMATCH_PENALTY = 0.2
CAP = 0.99
_PAYEE_WORD = {PayeeType.INDIVIDUAL: "person", PayeeType.MERCHANT: "business"}
PAYEE_DISAGREE_CONF = 0.5  # below TAU: the planner asks when business-vs-person changes the outcome


def payee_check(r: ExtractedReceipt) -> tuple[PayeeType | None, bool]:
    """Heuristic payee type for payment screenshots only (a bill's issuer is the merchant)."""
    if r.doc_type.value != DocType.UPI_SCREENSHOT:
        return None, False
    return payee_kind(r.payee_name.value or r.vendor_name.value, r.raw_text)


def adjust_confidence(receipt: ExtractedReceipt, today: dt.date) -> ExtractedReceipt:
    """Return a copy with validator-adjusted confidences. Call once per extraction (not idempotent)."""
    r = receipt.model_copy(deep=True)
    penalty = QUALITY_PENALTY.get(r.quality, 0.0)
    if penalty:
        for name in EXTRACTED_FIELD_NAMES:
            f = r.field(name)
            if f.value is not None:
                f.confidence = max(0.0, f.confidence - penalty)

    if r.vendor_gstin.value is not None:
        if gstin_problem(r.vendor_gstin.value):
            r.vendor_gstin.confidence, r.vendor_gstin.origin = 0.0, "validator"
        else:
            r.vendor_gstin.confidence = min(CAP, r.vendor_gstin.confidence + RECONCILE_BOOST)

    check = check_arithmetic(r)
    if r.total_amount.value is not None:
        if check.totals_reconcile or check.items_reconcile:
            r.total_amount.confidence = min(CAP, r.total_amount.confidence + RECONCILE_BOOST)
        elif check.totals_reconcile is False or check.items_reconcile is False:
            r.total_amount.confidence = max(0.0, r.total_amount.confidence - MISMATCH_PENALTY)

    if date_problem(r.date.value, today):
        r.date.confidence = min(r.date.confidence, 0.3)

    kind, strong = payee_check(r)
    f = r.payee_type
    if kind is not None:
        if f.value in (None, PayeeType.UNKNOWN):
            f.value, f.confidence, f.origin = kind, (0.8 if strong else 0.6), "validator"
        elif f.value == kind:
            f.confidence = min(CAP, f.confidence + RECONCILE_BOOST)
        else:
            f.confidence = min(f.confidence, PAYEE_DISAGREE_CONF)
    return r


def validation_findings(r: ExtractedReceipt, line_id: str, today: dt.date) -> list[Finding]:
    """INFO evidence for the UI; decisions stay in the rules engine. Deterministic ids so re-runs replace."""
    findings: list[Finding] = []

    def add(code: str, message: str, **evidence: object) -> None:
        findings.append(
            Finding(
                id=f"{line_id}:{code}",
                kind=FindingKind.VALIDATION,
                severity=Severity.INFO,
                rule_id=code,
                message=message,
                evidence=dict(evidence),
            )
        )

    if r.vendor_gstin.value is not None and (problem := gstin_problem(r.vendor_gstin.value)):
        add(
            "VAL_GSTIN_INVALID",
            f"GSTIN {r.vendor_gstin.value} is invalid: {problem}.",
            gstin=r.vendor_gstin.value,
        )
    check = check_arithmetic(r)
    if check.totals_reconcile is False:
        add(
            "VAL_TOTAL_MISMATCH",
            "Subtotal plus tax does not add up to the total.",
            subtotal=r.subtotal.value,
            tax=r.tax_amount.value,
            total=r.total_amount.value,
        )
    if check.items_reconcile is False:
        add(
            "VAL_ITEMS_MISMATCH",
            "Line items do not add up to the bill total.",
            items_sum=round(sum(i.amount or 0 for i in r.items), 2),
            total=r.total_amount.value,
        )
    kind, _ = payee_check(r)
    if kind is not None and r.payee_type.value not in (None, PayeeType.UNKNOWN, kind):
        add(
            "VAL_PAYEE_MISMATCH",
            f"The payee check reads this as a payment to a {_PAYEE_WORD[kind]}; the model read"
            f" {_PAYEE_WORD.get(r.payee_type.value, r.payee_type.value)}.",
            heuristic=kind.value,
            model=str(r.payee_type.value),
        )
    if problem := date_problem(r.date.value, today):
        add(
            "VAL_DATE_IMPLAUSIBLE",
            f"Expense date {r.date.value} looks wrong: {problem}.",
            date=str(r.date.value),
        )
    return findings
