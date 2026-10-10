"""Deterministic payee check for payment screenshots: was the money paid to a business or to a person?

Works on the transcription after PII redaction too: merchant collection VPAs are never masked (they name a
business, not a person), and person-like VPAs are classified on their masked shape, so a live run and its
replay always agree.
"""

import re

from app.domain.enums import PayeeType

# Google Pay personal handles; merchants collect on PSP/bank QR handles instead.
PERSONAL_HANDLES = frozenset({"okhdfcbank", "okaxis", "okicici", "oksbi"})
_MERCHANT_LOCAL = re.compile(
    r"^(?:paytmqr|paytm\.|ombk\.|bharatpe|mab\.|gpay-|q\d{6,}$|(?=(?:\D*\d){6})[a-z0-9]{14,}$)", re.IGNORECASE
)
VPA = re.compile(r"(?<![\w.*-])([A-Za-z0-9*][\w.*-]*)@([A-Za-z][A-Za-z0-9]+)\b(?!\.[A-Za-z])")
_SEPARATORS = ".-_"
_PHONE_SHAPE = re.compile(r"^[6-9][\d*]{8}\d$")
_NAME_SHAPE = re.compile(r"^[a-z*]{2,}[._][a-z*]{2,}(?:-?[\d*]{1,3})?$", re.IGNORECASE)
_BUSINESS = re.compile(
    r"\b(?:stores?|cent(?:re|er)|salon|spa|traders?|enterprises?|services?|pvt|private|ltd|limited|llp|"
    r"mart|restaurant|hotel|cafe|foods?|motors?|auto|petroleum|fuels?|filling|station|agenc(?:y|ies)|"
    r"telecom|airtel|mobile|recharge|broadband|medical|pharmacy|chemists?|clinic|hospital|bakery|sweets|"
    r"kirana|general|company|co|industries|solutions|technologies|residency|suites|kitchen|house|point|"
    r"care|luxury|unisex|boutique|garments|fashion|electronics|bazaa?r|shop|parlou?r|studio|gym|"
    r"dhaba|bhojanalaya|tiffins?|caterers?|travels?|tours|cabs?|mobility)\b",
    re.IGNORECASE,
)
_PERSON_NAME = re.compile(r"^(?:[A-Z][a-z]+|[A-Z]\.?)(?:\s+(?:[A-Z][a-z]+|[A-Z]\.?)){1,2}$")
_SENT = re.compile(r"\b(?:money sent|sent to|transferred to|sent successfully)\b", re.IGNORECASE)


def is_merchant_vpa(local: str) -> bool:
    return bool(_MERCHANT_LOCAL.match(local))


def mask_local(local: str) -> str:
    """Keep the first and last character and the separators; idempotent."""
    if len(local) <= 2:
        return local
    middle = "".join(ch if ch in _SEPARATORS else "*" for ch in local[1:-1])
    return local[0] + middle + local[-1]


def vpa_kind(local: str, handle: str) -> PayeeType | None:
    if is_merchant_vpa(local):
        return PayeeType.MERCHANT
    shape = mask_local(local)
    if handle.lower() in PERSONAL_HANDLES or _PHONE_SHAPE.match(shape) or _NAME_SHAPE.match(shape):
        return PayeeType.INDIVIDUAL
    return None


def _payee_vpa(payee: str | None, text: str) -> tuple[str, str] | None:
    """The VPA printed after the payee's name (the 'Paid to' block), else the first one on the screen."""
    start = text.find(payee) if payee else -1
    m = VPA.search(text, max(start, 0)) or VPA.search(text)
    return (m.group(1), m.group(2)) if m else None


def payee_kind(payee: str | None, text: str) -> tuple[PayeeType | None, bool]:
    """(heuristic payee type, strong?) from the payee's VPA, name and the screen wording."""
    vpa = _payee_vpa(payee, text)
    kind = vpa_kind(*vpa) if vpa else None
    if kind is not None:
        return kind, True
    name = (payee or "").strip()
    if name and _BUSINESS.search(name):
        return PayeeType.MERCHANT, False
    if name and _PERSON_NAME.match(name):
        return PayeeType.INDIVIDUAL, bool(_SENT.search(text))
    return None, False
