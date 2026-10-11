"""Deterministic checks on the employee's free-text answers, and the findings their declarations produce.

A justification, business purpose or trip note is data the employee typed; it resolves a flag only if it reads
as a real business reason. A declared personal purpose is not an error: it is accepted and blocks the line.
"""

import re
from dataclasses import dataclass
from typing import Literal

from app.domain.enums import FindingKind, Severity
from app.domain.models import Citation, Finding, LineItem
from app.rules.dsl import RuleSet

# require_field facts that are documents: text can never stand in for them
DOCUMENT_FIELDS = frozenset({"bill"})
CATEGORY_LABEL = {
    "meals": "Meals",
    "travel_local": "Local travel",
    "travel_intercity": "Intercity travel",
    "lodging": "Lodging",
    "fuel": "Fuel",
    "office": "Office supplies",
    "internet_phone": "Internet & phone",
    "personal": "Personal",
    "other": "Other",
}
ELIGIBILITY_QUOTE = (
    "An expense is reimbursable only if it was incurred wholly and necessarily for Company business"
)
PERSONAL_RULE = "PERSONAL_PURPOSE_DECLARED"
CATEGORY_RULE = "CATEGORY_CHANGED_BY_EMPLOYEE"
PERSONAL_MESSAGE = "Declared purpose is personal: not reimbursable"
ASK = "Add the business reason — who, where or which project."

# words that carry no business content: an answer made only of these is a refusal or a non-answer
_EMPTY_WORDS = frozenset(
    re.findall(
        r"\S+",
        "no nope nah not wont will wouldnt cant cannot dont do does didnt i im me my we it its a an the to "
        "of for and or is was be there this that any have has had provide give one want going sorry just "
        "yes yeah ok okay fine na n/a nil none nothing idk know sure skip test testing asdf bill bills "
        "receipt receipts available here now later why because reason answer please thanks say",
    )
)
_PERSONAL = re.compile(
    r"\b(vacations?|holidays?|leisure|personal|family|friends?|birthday|party|wedding|anniversary|shopping|"
    r"outing|picnic|honeymoon|weekend (?:trip|getaway)|own use|sightseeing)\b"
)
_VEHICLE_ETC = "vehicle car bike scooter card account phone number mobile funds"
_NOT_PERSONAL_NEXT = {"personal": frozenset(re.findall(r"\S+", _VEHICLE_ETC)), "party": {"of"}}
_NOT_PERSONAL_PREV = {"party": {"third", "client", "customer", "vendor"}, "holiday": {"public", "bank"}}
_NEGATION = {"not", "no", "non", "isnt", "wasnt", "never"}
_PLACE_WORDS = frozenset(
    re.findall(
        r"\S+",
        "client customer site office visit visited visiting meeting workshop project plant branch warehouse "
        "airport station route trip km factory depot vendor supplier store hq headquarters campus",
    )
)
_PLACE_NAME = re.compile(r"\b(?:to|from|via|at|in|near)\s+(?:the\s+)?[A-Z][a-z]+")


@dataclass(frozen=True)
class Check:
    status: Literal["ok", "rejected", "personal"]
    message: str = ""


OK = Check("ok")


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9/]+", text.casefold().replace("'", "").replace("’", ""))


def declares_personal(text: str | None) -> bool:
    """True when the answer states a personal purpose ('vacation', 'friends'), not 'personal vehicle'."""
    if not text:
        return False
    low = text.casefold().replace("'", "").replace("’", "")
    for m in _PERSONAL.finditer(low):
        word = m.group(1).split()[0].rstrip("s")
        before = _words(low[: m.start()])[-3:]
        after = _words(low[m.end() :])[:1]
        if _NEGATION & set(before):
            continue
        if after and after[0] in _NOT_PERSONAL_NEXT.get(word, ()):
            continue
        if before and before[-1] in _NOT_PERSONAL_PREV.get(word, ()):
            continue
        return True
    return False


def _gibberish(text: str, words: list[str]) -> bool:
    if re.search(r"([a-z])\1{3,}", text.casefold()):  # "aaaa", "nooooo"
        return True
    vowelless = [w for w in words if len(w) >= 4 and w.isalpha() and not re.search(r"[aeiouy]", w)]
    return (len(words) >= 4 and len(set(words)) <= len(words) // 2) or len(vowelless) * 2 > len(words)


def check_text(text: str | None, rule_id: str | None = None, action: str | None = None) -> Check:
    """Is this a usable justification / purpose / trip note for `rule_id` (a rule with `action`)?"""
    raw = (text or "").strip()
    words = _words(raw)
    if not words:
        return Check("rejected", f"Add a short note for Finance. {ASK}")
    if declares_personal(raw):
        return Check("personal", PERSONAL_MESSAGE)
    if all(w in _EMPTY_WORDS for w in words):
        return Check("rejected", f"“{raw}” doesn't explain the expense. {ASK}")
    visible = re.sub(r"\s", "", raw)
    letters = sum(c.isalpha() for c in visible)
    if letters < 0.6 * len(visible) or _gibberish(raw, words):
        return Check("rejected", f"That doesn't read as a sentence. {ASK}")
    fuel = rule_id == "FUEL_TRIP_NOTE"
    need = 6 if fuel or action == "cap" else 4
    if len(words) < need or letters < 15:
        return Check("rejected", f"Add a little more detail (at least {need} words). {ASK}")
    if fuel and not (_PLACE_WORDS & set(words) or _PLACE_NAME.search(raw)):
        return Check("rejected", "Say where the trip went: the client, site or route, and why.")
    return OK


def no_document_choice(field: str) -> str:
    return f"I don't have the {field}"


def eligibility_citation(ruleset: RuleSet) -> Citation | None:
    """The verified section 2.1 eligibility sentence, reused from the ruleset rule that cites it."""
    # shortcut: needs a rule citing 2.1 (PAYER_NOT_EMPLOYEE); locate() it in the policy text if none does
    return next((r.citation for r in ruleset.rules if r.citation.quote.startswith(ELIGIBILITY_QUOTE)), None)


def personal_purpose_finding(line: LineItem, ruleset: RuleSet) -> Finding | None:
    if not declares_personal(line.business_purpose):
        return None
    return Finding(
        id=f"{line.id}:{PERSONAL_RULE}",
        kind=FindingKind.POLICY,
        severity=Severity.BLOCK,
        rule_id=PERSONAL_RULE,
        message=PERSONAL_MESSAGE,
        citation=eligibility_citation(ruleset),
        evidence={"action": "block", "declared_purpose": line.business_purpose},
    )


def original_category(line: LineItem) -> str | None:
    """The model's category when the employee has since changed it, else None."""
    f = line.extracted.category
    if f.origin != "user" or not f.history or f.history[0].old_value is None:
        return None
    first = str(f.history[0].old_value)
    return first if first != str(getattr(f.value, "value", f.value)) else None


def category_change_finding(line: LineItem, original: str, avoided: list[str]) -> Finding:
    new = str(getattr(line.extracted.category.value, "value", line.extracted.category.value))
    return Finding(
        id=f"{line.id}:{CATEGORY_RULE}",
        kind=FindingKind.POLICY,
        severity=Severity.WARN,
        rule_id=CATEGORY_RULE,
        message=f"Category changed from {CATEGORY_LABEL.get(original, original)} to "
        f"{CATEGORY_LABEL.get(new, new)} by employee",
        evidence={"action": "require_justification", "from": original, "to": new, "avoided_rules": avoided},
    )


def no_document_finding(f: Finding) -> Finding:
    """The employee said the document does not exist: the payment alone is not reimbursable."""
    return f.model_copy(
        update={
            "severity": Severity.BLOCK,
            "message": "No bill — policy 3.1 requires a bill; payment confirmation alone isn't enough",
            "evidence": {**f.evidence, "declared_missing": True},
        }
    )
