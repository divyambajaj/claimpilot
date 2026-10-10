"""Extraction schema (LLM structured-output contract) and deterministic post-processing of the raw output."""

import datetime as dt
import re
from typing import Any

from app.domain.enums import Category, DocType, PaymentMethod
from app.domain.models import EXTRACTED_FIELD_NAMES, ExtractedReceipt

_STR = {"type": ["string", "null"]}
_NUM = {"type": ["number", "null"]}
FIELD_TYPES: dict[str, dict[str, Any]] = {
    "doc_type": {"type": ["string", "null"], "enum": [*(d.value for d in DocType), None]},
    "vendor_name": _STR,
    "vendor_gstin": _STR,
    "invoice_number": _STR,
    "date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
    "currency": _STR,
    "subtotal": _NUM,
    "tax_amount": _NUM,
    "total_amount": _NUM,
    "payment_method": {"type": ["string", "null"], "enum": [*(p.value for p in PaymentMethod), None]},
    "upi_txn_id": _STR,
    "payee_name": _STR,
    "city": _STR,
    "category": {"type": ["string", "null"], "enum": [*(c.value for c in Category), None]},
    "attendees_count": {"type": ["integer", "null"]},
}
CORE_FIELDS = ("doc_type", "vendor_name", "date", "currency", "total_amount", "payment_method", "category")
QUALITIES = ["good", "blurry", "partial", "rotated", "handwritten"]

# shortcut: static FX table for the rare non-INR receipt; replace with a rates feed if foreign travel matters.
FX_TO_INR = {"INR": 1.0, "USD": 84.0, "EUR": 91.0, "GBP": 107.0, "AED": 22.9, "SGD": 63.0}
_CURRENCY_ALIASES = {
    "₹": "INR",
    "RS": "INR",
    "RS.": "INR",
    "RUPEES": "INR",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
}
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%d-%m-%y",
    "%d %b %Y",
    "%d %B %Y",
    "%d-%b-%Y",
    "%d %b %y",
    "%b %d, %Y",
    "%d %b, %Y",
)


def _field_schema(value_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"value": value_schema, "confidence": {"type": "number"}, "source_snippet": _STR},
        "required": ["value", "confidence", "source_snippet"],
        "additionalProperties": False,
    }


def extraction_schema(core: bool = False) -> dict[str, Any]:
    names = CORE_FIELDS if core else tuple(FIELD_TYPES)
    props: dict[str, Any] = {n: _field_schema(FIELD_TYPES[n]) for n in names}
    if not core:
        props["items"] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "quantity": _NUM,
                    "unit_price": _NUM,
                    "amount": _NUM,
                },
                "required": ["description", "quantity", "unit_price", "amount"],
                "additionalProperties": False,
            },
        }
    props["raw_text"] = {"type": "string"}
    props["quality"] = {"type": "string", "enum": QUALITIES}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def parse_date(value: Any) -> dt.date | None:
    if value is None:
        return None
    text = str(value).strip().replace("Sept", "Sep")
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    cleaned = re.sub(r"(?i)(inr|rs\.?|₹|/-|,|\s)", "", str(value))
    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_gstin(value: Any) -> str | None:
    if not value:
        return None
    return re.sub(r"[\s-]", "", str(value)).upper() or None


def _normalize_currency(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip().upper()
    return _CURRENCY_ALIASES.get(text, text)


def _normalize_enum(value: Any, allowed: set[str], fallback: str) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    text = str(value).strip().lower().replace(" ", "_")
    return (text, False) if text in allowed else (fallback, True)


def _clamp_conf(value: Any) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.0
    if c > 1:
        c /= 100
    return min(max(c, 0.0), 1.0)


_ENUMS = {
    "doc_type": ({d.value for d in DocType}, DocType.UNKNOWN.value),
    "payment_method": ({p.value for p in PaymentMethod}, PaymentMethod.UNKNOWN.value),
    "category": ({c.value for c in Category}, Category.OTHER.value),
}


def _normalize_field(name: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {"value": raw, "confidence": 0.5 if raw is not None else 0.0}
    value, conf = raw.get("value"), _clamp_conf(raw.get("confidence"))
    snippet = raw.get("source_snippet")
    out: dict[str, Any] = {"confidence": conf, "source_snippet": str(snippet) if snippet else None}
    if name == "date":
        parsed = parse_date(value)
        value, conf = (parsed.isoformat() if parsed else None), (conf if parsed else 0.0)
    elif name in ("subtotal", "tax_amount", "total_amount"):
        value = parse_amount(value)
    elif name == "attendees_count":
        amount = parse_amount(value)
        value = int(amount) if amount and amount >= 1 else None
    elif name == "vendor_gstin":
        value = normalize_gstin(value)
    elif name == "currency":
        value = _normalize_currency(value)
        if value is None:
            value, conf, out["origin"] = "INR", 0.6, "assumed"
    elif name in _ENUMS:
        allowed, fallback = _ENUMS[name]
        value, coerced = _normalize_enum(value, allowed, fallback)
        if coerced:
            conf = min(conf, 0.3)
    elif value is not None:
        value = str(value).strip() or None
    if value is None and name != "currency":
        conf = min(conf, 0.5) if conf else 0.0
    out.update(value=value, confidence=conf)
    return out


def normalize_extraction(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce provider output into the `ExtractedReceipt` shape; missing fields become null/0-confidence."""
    out: dict[str, Any] = {name: _normalize_field(name, raw.get(name)) for name in EXTRACTED_FIELD_NAMES}
    items = raw.get("items") or []
    out["items"] = [
        {
            "description": str(i.get("description")),
            "quantity": parse_amount(i.get("quantity")),
            "unit_price": parse_amount(i.get("unit_price")),
            "amount": parse_amount(i.get("amount")),
        }
        for i in items
        if isinstance(i, dict) and i.get("description")
    ]
    out["raw_text"] = str(raw.get("raw_text") or "")
    quality = raw.get("quality")
    out["quality"] = quality if quality in QUALITIES else "good"
    return out


def parse_extraction(raw: dict[str, Any]) -> ExtractedReceipt:
    if not isinstance(raw, dict) or "raw_text" not in raw:
        raise ValueError("extraction output must be an object with raw_text")
    return ExtractedReceipt.model_validate(normalize_extraction(raw))


def amount_in_inr(receipt: ExtractedReceipt) -> float:
    total = receipt.total_amount.value or 0.0
    return round(total * FX_TO_INR.get(receipt.currency.value or "INR", 1.0), 2)
