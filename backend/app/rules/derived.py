"""Facts the rules engine reads: extracted values plus derived fields (gstin validity, per-person, age...)."""

import datetime as dt
import re
from typing import Any

from rapidfuzz import fuzz

from app.domain.enums import DocType
from app.domain.models import LineItem
from app.pipeline.validate.gstin import is_valid_gstin

# Rule-DSL fact -> ExtractedReceipt field (facts not listed here are derived, not asked about).
FACT_TO_FIELD = {
    "amount_inr": "total_amount",
    "category": "category",
    "date": "date",
    "vendor_gstin": "vendor_gstin",
    "payment_method": "payment_method",
    "attendees_count": "attendees_count",
    "city": "city",
    "doc_type": "doc_type",
    "invoice_number": "invoice_number",
    "vendor_name": "vendor_name",
    "payee_type": "payee_type",
    "payer_name": "payer_name",
}

_CITY_ALIASES = {
    "new delhi": "Delhi",
    "bangalore": "Bengaluru",
    "bombay": "Mumbai",
    "navi mumbai": "Mumbai",
    "madras": "Chennai",
    "calcutta": "Kolkata",
    "gurgaon": "Gurugram",
    "poona": "Pune",
    "secunderabad": "Hyderabad",
}


def canonical_city(city: str | None) -> str | None:
    if not city:
        return None
    key = city.strip().lower()
    return _CITY_ALIASES.get(key, city.strip().title())


# titles and company suffixes say nothing about who paid
_NOISE = re.compile(
    r"\b(?:mr|mrs|ms|miss|dr|shri|smt|kum|m/s|pvt|private|ltd|limited|llp)\b\.?", re.IGNORECASE
)


def _name_tokens(name: str) -> list[str]:
    name = _NOISE.sub(" ", re.sub(r"\(.*?\)", " ", name))  # drop "(xx1234)" and titles
    return re.findall(r"[a-z]+", name.casefold())


def name_matches(payer: str, name: str) -> bool:
    """'K. Mehta', 'Mehta', 'MEHTA KAVYA' match 'Kavya Mehta': every token equal or an initial of one."""
    a, b = _name_tokens(payer), _name_tokens(name)
    if not a or not b:
        return False
    if fuzz.token_sort_ratio(" ".join(a), " ".join(b)) >= 90:
        return True
    exact = [t for t in a if t in b]
    initials = all(t in b or (len(t) == 1 and any(x.startswith(t) for x in b)) for t in a)
    return initials and any(len(t) >= 3 for t in exact)


def payer_matches(payer: str | None, names: tuple[str, ...]) -> bool | None:
    """None when unknown (no payer printed or no profile configured)."""
    if not payer or not names:
        return None
    return any(name_matches(payer, n) for n in names)


def _plain(value: Any) -> Any:
    return getattr(value, "value", value)


def line_facts(line: LineItem, today: dt.date, payer_names: tuple[str, ...] = ()) -> dict[str, Any]:
    """`payer_names`: who may pay (the claimant's profile name, the company); empty = not checked."""
    r = line.extracted
    date = r.date.value
    attendees = r.attendees_count.value
    has_bill = r.doc_type.value != DocType.UPI_SCREENSHOT  # a linked screenshot is never evaluated alone
    return {
        "amount_inr": line.amount_inr,
        "category": line.category.value,
        "date": date,
        "vendor_gstin": r.vendor_gstin.value,
        "vendor_gstin_valid": is_valid_gstin(r.vendor_gstin.value),
        "payment_method": _plain(r.payment_method.value),
        "has_proof_of_payment": line.has_proof_of_payment,
        "attendees_count": attendees,
        "city": canonical_city(r.city.value),
        "doc_type": _plain(r.doc_type.value),
        "days_since_expense": (today - date).days if date else None,
        "invoice_number": r.invoice_number.value,
        "is_weekend": date.weekday() >= 5 if date else None,
        "per_person_amount": round(line.amount_inr / max(attendees or 1, 1), 2),
        "distance_km": None,  # shortcut: not extracted yet; add to the extraction schema if a rule needs it
        "vendor_name": r.vendor_name.value or r.payee_name.value,
        "has_bill": has_bill,
        "bill": _plain(r.doc_type.value) if has_bill else None,
        "payee_type": _plain(r.payee_type.value),
        "payer_name": r.payer_name.value,
        "payer_matches_employee": payer_matches(r.payer_name.value, payer_names),
        "business_purpose": line.business_purpose,
    }
