"""Facts the rules engine reads: extracted values plus derived fields (gstin validity, per-person, age...)."""

import datetime as dt
from typing import Any

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


def line_facts(line: LineItem, today: dt.date) -> dict[str, Any]:
    r = line.extracted
    date = r.date.value
    attendees = r.attendees_count.value
    return {
        "amount_inr": line.amount_inr,
        "category": line.category.value,
        "date": date,
        "vendor_gstin": r.vendor_gstin.value,
        "vendor_gstin_valid": is_valid_gstin(r.vendor_gstin.value),
        "payment_method": r.payment_method.value.value if r.payment_method.value else None,
        "has_proof_of_payment": line.has_proof_of_payment,
        "attendees_count": attendees,
        "city": canonical_city(r.city.value),
        "doc_type": r.doc_type.value.value if r.doc_type.value else None,
        "days_since_expense": (today - date).days if date else None,
        "invoice_number": r.invoice_number.value,
        "is_weekend": date.weekday() >= 5 if date else None,
        "per_person_amount": round(line.amount_inr / max(attendees or 1, 1), 2),
        "distance_km": None,  # shortcut: not extracted yet; add to the extraction schema if a rule needs it
    }
