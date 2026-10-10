"""Startup data: the shipped ruleset (always) and replayed sample history + eval runs (SEED_DEMO=1)."""

import datetime as dt
import hashlib
from pathlib import Path

from app.config import Settings
from app.domain.models import EXTRACTED_FIELD_NAMES, LineItem, PolicyDoc, Question
from app.domain.repo import Repo
from app.llm.base import ReplayMissError
from app.llm.prompts.registry import PromptRegistry
from app.llm.registry import build_client, build_provider
from app.observability.tracing import Tracer, utcnow
from app.pipeline.orchestrator import Orchestrator, Upload
from app.rules.dsl import RuleSet

RULESET_FILE = "acme_v1.json"
POLICY_FILE = "acme_india_travel_policy.md"
POLICY_NAME = "Acme India Travel & Expense Policy"
SAMPLE_JUSTIFICATION = "Client meeting approved in advance by the department head."
MAX_ROUNDS = 5
HISTORY_USER = "asha.rao"
HISTORY_DAYS = 14
GALLERY_TITLE = "Mumbai client visit (sample)"


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
    """Fill an empty database with real pipeline runs in replay mode (hosted demo, `SEED_DEMO=1`).

    - the eval claims as one employee's history over the last two weeks (backdated clock and spans),
      questions answered, most submitted, so the dashboard shows real violations, duplicates and cost;
    - the gallery as a recent sample claim under its own user, so a visitor adding the same gallery is not
      flagged as a duplicate of it;
    - one full eval run per recorded extraction prompt version.
    """
    from app.evaluation.runner import FIXTURES, load_fixtures, run_eval  # runner imports this module

    if orch.repo.list_claims():
        return
    settings = orch.settings.model_copy(update={"LLM_PROVIDER": "replay", "LLM_RECORD": False, "REPLAY_DELAY_S": 0.0})
    started, now = utcnow(), orch.clock()
    manifest, rows = load_fixtures()
    history = manifest["claims"]
    for i, c in enumerate(history):
        when = now - dt.timedelta(days=HISTORY_DAYS * (len(history) - i) / len(history), hours=3)
        files = [FIXTURES / rows[f]["file"] for f in c["fixtures"]]
        await _seed_claim(
            orch, settings, when, started, HISTORY_USER, c["title"], files, i < len(history) - 2
        )
    gallery = sorted(p for p in settings.demo_dir.iterdir() if p.suffix in (".png", ".jpg", ".pdf"))
    await _seed_claim(
        orch, settings, now - dt.timedelta(hours=2), started, user_id, GALLERY_TITLE, gallery, True
    )

    provider = build_provider(settings)
    for k, version in enumerate(PromptRegistry().versions("extract_receipt")):
        try:
            run = await run_eval(
                settings.model_copy(update={"PROMPT_VERSION_EXTRACT": version}),
                "full",
                provider,
                created_at=now - dt.timedelta(days=3 - k, hours=1),
            )
        except ReplayMissError:
            continue  # this prompt version was never recorded
        orch.repo.save_eval_run(run)


async def _seed_claim(
    orch: Orchestrator,
    settings: Settings,
    when: dt.datetime,
    started: dt.datetime,
    user: str,
    title: str,
    files: list[Path],
    submit: bool,
) -> None:
    def clock() -> dt.datetime:  # real elapsed time on top of the backdated start keeps durations honest
        return when + (utcnow() - started)

    tracer = Tracer(orch.tracer.db, clock)
    llm = build_client(settings, tracer)
    past = Orchestrator(settings, orch.repo, llm, tracer, orch.broker, orch.finance, clock, orch.detector)
    claim = past.create_claim(user, title)
    await past.add_documents(claim.id, [Upload(p.name, p.read_bytes()) for p in files])
    await past.wait_idle()
    for _ in range(MAX_ROUNDS):
        claim = past.repo.get_claim(claim.id)
        if not claim.open_questions:
            break
        lines = {x.id: x for x in claim.lines}
        answers = [
            {"question_id": q.id, "value": _sample_answer(q, lines[q.line_id], when)}
            for q in claim.open_questions
        ]
        claim = await past.answer(claim.id, answers)
    if submit and claim.status == "ready_to_submit":
        await past.submit(claim.id)


def _sample_answer(q: Question, line: LineItem, when: dt.datetime) -> object:
    """What a careful employee would answer: confirm duplicates, justify flags, confirm or fill values."""
    if q.kind == "confirm_duplicate":
        return "confirm"
    if q.kind == "justify_flag":
        return SAMPLE_JUSTIFICATION
    current = line.extracted.field(q.field).value if q.field in EXTRACTED_FIELD_NAMES else None
    if current is not None:
        return getattr(current, "value", current) if not isinstance(current, dt.date) else current.isoformat()
    defaults = {
        "date": (when - dt.timedelta(days=2)).date().isoformat(),
        "attendees_count": 2,
        "city": "Mumbai",
    }
    return defaults.get(q.field, q.choices[0] if q.choices else "")
