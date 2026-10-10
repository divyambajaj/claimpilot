"""Policy compiler: LLM drafts DSL rules; code validates them, verifies citations, smoke-tests the engine."""

import datetime as dt
import hashlib

from app.domain.enums import Category, LineStatus
from app.domain.models import EXTRACTED_FIELD_NAMES, ExtractedReceipt, LineItem, PolicyDoc
from app.domain.repo import Repo
from app.llm.client import LLMClient, StructuredOutputError
from app.rules.citations import locate
from app.rules.dsl import Rule, RuleSet, RuleSetDraft
from app.rules.engine import evaluate

DEFAULTS = {"currency": "INR", "submission_window_days": 30}


class CompileError(Exception):
    """The policy could not be compiled into a usable ruleset."""


def _smoke_line(line_id: str, category: Category, amount: float, **values: object) -> LineItem:
    fields = {"total_amount": amount, "category": category.value, "date": "2026-01-15", **values}
    data = {
        n: {"value": fields.get(n), "confidence": 1.0 if n in fields else 0.0} for n in EXTRACTED_FIELD_NAMES
    }
    receipt = ExtractedReceipt.model_validate({**data, "raw_text": "smoke"})
    return LineItem(
        id=line_id,
        claim_id="smoke",
        document_ids=[],
        extracted=receipt,
        category=category,
        amount_inr=amount,
        reimbursable_inr=amount,
        status=LineStatus.PROCESSING,
    )


SMOKE_LINES = [
    _smoke_line("meal", Category.MEALS, 4200.0, attendees_count=3, city="Mumbai", payment_method="card"),
    _smoke_line("hotel", Category.LODGING, 9000.0, city="Pune", payment_method="upi"),
    _smoke_line("cab", Category.TRAVEL_LOCAL, 650.0, city="Delhi", payment_method="cash"),
]


def build_ruleset(
    draft: RuleSetDraft,
    policy: PolicyDoc,
    version: int,
    prompt_version: str,
    provider: str,
    model: str,
    compiled_at: dt.datetime,
) -> tuple[RuleSet, list[str]]:
    """Attach located citations; rules whose quote cannot be found in the policy are dropped (returned)."""
    rules, dropped = [], []
    for r in draft.rules:
        citation = locate(r.citation.section, r.citation.quote, policy.text)
        if citation is None:
            dropped.append(r.id)
            continue
        rules.append(Rule.model_validate({**r.model_dump(by_alias=True), "citation": citation.model_dump()}))
    ruleset = RuleSet(
        version=version,
        policy_id=policy.id,
        policy_sha256=policy.sha256,
        compiled_at=compiled_at,
        compiler_prompt_version=prompt_version,
        provider=provider,
        model=model,
        required_fields=draft.required_fields,
        rules=rules,
        defaults=DEFAULTS,
    )
    return ruleset, dropped


def smoke_test(ruleset: RuleSet) -> None:
    try:
        result = evaluate(SMOKE_LINES, ruleset, dt.date(2026, 1, 20))
    except Exception as exc:
        raise CompileError(f"ruleset crashed the engine on smoke claims: {exc}") from exc
    for outcome in result.lines.values():
        if outcome.reimbursable_inr < 0:
            raise CompileError("ruleset produced a negative reimbursable amount")


async def compile_policy(
    client: LLMClient, repo: Repo, name: str, text: str, now: dt.datetime, activate: bool = True
) -> tuple[RuleSet, list[str]]:
    sha = hashlib.sha256(text.encode()).hexdigest()
    policy = PolicyDoc(id=f"pol_{sha[:12]}", name=name, text=text, sha256=sha, created_at=now)
    try:
        draft, resp = await client.compile_policy(text)
    except StructuredOutputError as exc:
        raise CompileError(f"compiler output never matched the rule schema: {exc}") from exc
    prompt_version = client.prompts.get("compile_policy").version
    ruleset, dropped = build_ruleset(
        draft, policy, repo.next_ruleset_version(), prompt_version, resp.provider, resp.model, now
    )
    if not ruleset.rules:
        raise CompileError("no rule could be tied to a verbatim policy sentence")
    smoke_test(ruleset)
    repo.save_policy(policy)
    repo.save_ruleset(ruleset, active=activate)
    return ruleset, dropped
