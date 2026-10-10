"""PII redaction for everything we persist from a document read (extraction fields, raw_text, snippets,
replay files): mobile numbers, UPI VPAs, card numbers, emails and account numbers. Names and amounts stay.

Pure and idempotent, so a replayed (already masked) recording passes through unchanged.
"""

import re
from typing import Any

from app.pipeline.validate.payee import VPA, is_merchant_vpa, mask_local

_EMAIL = re.compile(r"(?<![\w.+-])([\w.%+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b")
_CARD_FULL = re.compile(r"(?<!\d)(?:\d{4}[ -]){3}\d{4}(?!\d)|(?<!\d)\d{16}(?!\d)")
_CARD_LAST4 = re.compile(r"(?<![\w*])([xX*]{2,4}[ -]?)(\d{4})\b")
_ACCOUNT = re.compile(
    r"(?i)\b(a/c|acct\.?|account)(\s*(?:no\.?|number)?\s*[:#.-]?\s*)([X*\d][X*\d -]{4,20}\d)(?!\d)"
)
_MOBILE = re.compile(r"(?<![\w*])((?:\+91[\s-]?)?)([6-9]\d{4}[\s-]?\d{5})(?!\d)")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def _keep_last(text: str, n: int) -> str:
    """Mask every digit except the last `n` with X, keeping spacing."""
    idx = [i for i, ch in enumerate(text) if ch.isdigit()]
    hide = set(idx[:-n] if n else idx)
    return "".join("X" if i in hide else ch for i, ch in enumerate(text))


def _vpa(m: re.Match[str]) -> str:
    local, handle = m.group(1), m.group(2)
    # merchant collection ids name a business, not a person, and the payee check needs them
    return m.group(0) if is_merchant_vpa(local) else f"{mask_local(local)}@{handle}"


def _card(m: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", m.group(0))
    return re.sub(r"\d", "•", m.group(0)) if _luhn(digits) else m.group(0)


def redact_text(text: str) -> str:
    text = _EMAIL.sub(lambda m: f"{mask_local(m.group(1))}@{m.group(2)}", text)
    text = VPA.sub(_vpa, text)
    text = _CARD_FULL.sub(_card, text)
    text = _CARD_LAST4.sub(lambda m: m.group(1) + "••••", text)
    text = _ACCOUNT.sub(lambda m: m.group(1) + m.group(2) + _keep_last(m.group(3), 4), text)
    return _MOBILE.sub(lambda m: m.group(1) + _keep_last(m.group(2), 2), text)


def redact(value: Any) -> Any:
    """Redact every string inside a JSON-like value."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value
