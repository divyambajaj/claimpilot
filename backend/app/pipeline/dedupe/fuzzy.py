"""Layer 2: fuzzy match on (vendor, amount, date) with an invoice-number shortcut."""

import re

from rapidfuzz import fuzz

from app.domain.models import LineItem

FIRE_AT = 0.80
_LEGAL_SUFFIX = re.compile(r"\b(pvt|private|ltd|limited|llp|inc|co|company|india)\b")


def norm_vendor(name: str | None) -> str:
    if not name:
        return ""
    text = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    return " ".join(_LEGAL_SUFFIX.sub(" ", text).split())


def norm_invoice(number: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (number or "").upper())


def amount_match(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(1.0, 0.005 * abs(a))


def vendor_similarity(a: str | None, b: str | None) -> float:
    na, nb = norm_vendor(a), norm_vendor(b)
    return fuzz.token_set_ratio(na, nb) / 100 if na and nb else 0.0


def fuzzy_score(a: LineItem, b: LineItem) -> tuple[float, dict]:
    ra, rb = a.extracted, b.extracted
    amounts = amount_match(a.amount_inr, b.amount_inr)
    inv_a, inv_b = norm_invoice(ra.invoice_number.value), norm_invoice(rb.invoice_number.value)
    if inv_a and inv_a == inv_b and amounts:
        return 0.98, {"signal": "invoice_number", "invoice_number": inv_a}
    vendor_sim = vendor_similarity(ra.vendor_name.value, rb.vendor_name.value)
    da, db = ra.date.value, rb.date.value
    date_delta = abs((da - db).days) if da and db else None
    date_term = max(0.0, 1 - date_delta / 3) if date_delta is not None else 0.0
    score = 0.5 * vendor_sim + 0.35 * amounts + 0.15 * date_term
    return round(score, 4), {
        "vendor_similarity": round(vendor_sim, 3),
        "amount_match": amounts,
        "date_delta_days": date_delta,
    }
