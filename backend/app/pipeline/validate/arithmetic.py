"""Arithmetic cross-checks: subtotal + tax = total, items sum, and GST slab detection."""

from dataclasses import dataclass

from app.domain.models import ExtractedReceipt

GST_SLABS = (0.05, 0.12, 0.18, 0.28)


def tolerance(amount: float) -> float:
    return max(1.0, 0.005 * abs(amount))


def close(a: float, b: float) -> bool:
    return abs(a - b) <= tolerance(max(abs(a), abs(b)))


@dataclass(frozen=True)
class ArithmeticCheck:
    totals_reconcile: bool | None  # None = not enough fields to check
    items_reconcile: bool | None
    gst_rate: float | None


def check_arithmetic(r: ExtractedReceipt) -> ArithmeticCheck:
    sub, tax, total = r.subtotal.value, r.tax_amount.value, r.total_amount.value
    totals = close(sub + tax, total) if None not in (sub, tax, total) else None  # type: ignore[operator]
    item_amounts = [i.amount for i in r.items if i.amount is not None]
    items = None
    if item_amounts and total is not None:
        s = sum(item_amounts)
        items = close(s, total) or (sub is not None and close(s, sub))
    rate = None
    if sub and tax:
        rate = next((slab for slab in GST_SLABS if abs(tax / sub - slab) <= 0.005), None)
    return ArithmeticCheck(totals, items, rate)
