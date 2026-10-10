"""GSTIN structure + mod-36 checksum validation (GSTN check-digit algorithm)."""

import re

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_PATTERN = re.compile(r"^(\d{2})([A-Z]{5}\d{4}[A-Z])([1-9A-Z])Z([0-9A-Z])$")
VALID_STATE_CODES = {f"{n:02d}" for n in range(1, 39)} | {"97", "99"}


def checksum_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = ALPHABET.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return ALPHABET[(36 - total % 36) % 36]


def normalize(gstin: str) -> str:
    return re.sub(r"[\s-]", "", gstin).upper()


def gstin_problem(gstin: str | None) -> str | None:
    """None if valid, else a short human reason."""
    if not gstin:
        return "missing"
    g = normalize(gstin)
    m = _PATTERN.match(g)
    if not m:
        return "not a 15-character GSTIN (state code + PAN + entity + Z + check digit)"
    if m.group(1) not in VALID_STATE_CODES:
        return f"unknown state code {m.group(1)}"
    if checksum_char(g[:14]) != g[14]:
        return "check digit does not match (likely misread or fabricated)"
    return None


def is_valid_gstin(gstin: str | None) -> bool:
    return gstin_problem(gstin) is None


def make_gstin(state_code: str, pan: str, entity: str = "1") -> str:
    """Build a checksum-valid GSTIN (used for synthetic data)."""
    first14 = f"{state_code}{pan}{entity}Z"
    return first14 + checksum_char(first14)
