"""Startup data: the shipped ruleset (always) and a sample submitted claim (SEED_DEMO=1, hosted demo)."""

import hashlib

from app.config import Settings
from app.domain.models import PolicyDoc
from app.domain.repo import Repo
from app.pipeline.orchestrator import Orchestrator, Upload
from app.rules.dsl import RuleSet

RULESET_FILE = "acme_v1.json"
POLICY_FILE = "acme_india_travel_policy.md"
POLICY_NAME = "Acme India Travel & Expense Policy"
SAMPLE_JUSTIFICATION = "Client meeting approved in advance by the department head."
MAX_ROUNDS = 5


def ensure_ruleset(repo: Repo, settings: Settings) -> RuleSet:
    active = repo.active_ruleset()
    if active is not None:
        return active
    ruleset = RuleSet.model_validate_json((settings.rulesets_dir / RULESET_FILE).read_text())
    text = (settings.policies_dir / POLICY_FILE).read_text()
    if hashlib.sha256(text.encode()).hexdigest() != ruleset.policy_sha256:
        raise RuntimeError(f"{POLICY_FILE} changed since {RULESET_FILE} was built; rebuild the ruleset")
    repo.save_policy(
        PolicyDoc(
            id=ruleset.policy_id,
            name=POLICY_NAME,
            text=text,
            sha256=ruleset.policy_sha256,
            created_at=ruleset.compiled_at,
        )
    )
    repo.save_ruleset(ruleset, active=True)
    return ruleset


async def seed_demo(orch: Orchestrator, user_id: str = "sample-team") -> None:
    """Run the demo gallery through the real pipeline once, answer its questions and submit.

    Seeded under its own user so a visitor adding the same gallery is not flagged as a duplicate of it.
    """
    if orch.repo.list_claims():
        return
    claim = orch.create_claim(user_id, "Bengaluru client visit (sample)")
    files = sorted(p for p in orch.settings.demo_dir.iterdir() if p.suffix in (".png", ".jpg", ".pdf"))
    await orch.add_documents(claim.id, [Upload(p.name, p.read_bytes()) for p in files])
    await orch.wait_idle()
    for _ in range(MAX_ROUNDS):
        claim = orch.repo.get_claim(claim.id)
        if not claim.open_questions:
            break
        answers = [
            {"question_id": q.id, "value": _sample_answer(q.kind, q.field)} for q in claim.open_questions
        ]
        claim = await orch.answer(claim.id, answers)
    if claim.status == "ready_to_submit":
        await orch.submit(claim.id)


def _sample_answer(kind: str, field: str) -> object:
    if kind == "confirm_duplicate":
        return "confirm"
    if kind == "justify_flag":
        return SAMPLE_JUSTIFICATION
    return {"attendees_count": 2, "city": "Bengaluru", "category": "other", "payment_method": "card"}.get(
        field, ""
    )
