"""Locate a rule's quoted sentence in the policy: exact, whitespace-normalised, then fuzzy (unverified)."""

from rapidfuzz import fuzz

from app.domain.models import Citation

FUZZY_THRESHOLD = 92


def _normalized_with_map(text: str) -> tuple[str, list[int]]:
    """Collapse whitespace runs to one space; `index[i]` is the original offset of normalised char i."""
    chars: list[str] = []
    index: list[int] = []
    prev_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if prev_space:
                continue
            chars.append(" ")
            prev_space = True
        else:
            chars.append(ch)
            prev_space = False
        index.append(i)
    return "".join(chars), index


def locate(section: str, quote: str, policy_text: str) -> Citation | None:
    start = policy_text.find(quote)
    if start >= 0:
        return Citation(section=section, quote=quote, char_start=start, char_end=start + len(quote))

    norm_text, index = _normalized_with_map(policy_text)
    norm_quote = " ".join(quote.split())
    start = norm_text.find(norm_quote)
    if start >= 0 and norm_quote:
        s, e = index[start], index[start + len(norm_quote) - 1] + 1
        return Citation(section=section, quote=policy_text[s:e], char_start=s, char_end=e)

    match = fuzz.partial_ratio_alignment(norm_quote, norm_text)
    if match is None or match.score < FUZZY_THRESHOLD:
        return None
    s, e = index[match.dest_start], index[max(match.dest_end - 1, match.dest_start)] + 1
    return Citation(section=section, quote=quote, char_start=s, char_end=e, verified=False)
