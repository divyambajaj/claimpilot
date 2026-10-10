"""Eval runner: pushes the synthetic claims through the real orchestrator and scores them (section 12-13).

    python -m app.evaluation.runner --subset full --provider replay --gate

Each run uses a throwaway database (the eval user's history never touches real claims) and a fixed clock at
the manifest's eval date, so "days since expense" and duplicate windows are reproducible. The resulting
`EvalRun` is saved to the app database unless `--no-save`.
"""

import argparse
import asyncio
import datetime as dt
import json
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.api.sse import Broker
from app.config import REPO_ROOT, Settings, get_settings
from app.db import Database
from app.domain.models import EvalMetrics, EvalRun
from app.domain.repo import Repo
from app.evaluation import gate
from app.evaluation.calibration import brier, ece, reliability
from app.evaluation.metrics import (
    Observed,
    duplicate_scores,
    run_stats,
    score_fields,
    upi_link_scores,
    violation_scores,
)
from app.evaluation.oracle import OracleProvider
from app.finance_mock import MockFinance
from app.llm.base import LLMProvider
from app.llm.registry import build_client
from app.observability.tracing import Tracer, new_id, utcnow
from app.pipeline.orchestrator import Orchestrator, Upload
from app.seed import ensure_ruleset

EVAL_DIR = REPO_ROOT / "data" / "eval"
FIXTURES = EVAL_DIR / "fixtures"
BASELINE = EVAL_DIR / "baseline.json"
Progress = Callable[[int, int, str | None], None]


def load_fixtures(fixtures_dir: Path = FIXTURES) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest = json.loads((fixtures_dir / "manifest.json").read_text())
    rows = [
        json.loads(line) for line in (fixtures_dir / "ground_truth.jsonl").read_text().splitlines() if line
    ]
    return manifest, {r["id"]: r for r in rows}


def git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT
        )
    except OSError:
        return None
    return out.stdout.strip() or None


class _ProgressBroker(Broker):
    """Counts finished documents from the orchestrator's own stage events."""

    def __init__(self, on_finished: Callable[[str], None]) -> None:
        super().__init__()
        self.on_finished = on_finished

    def publish(self, topic: str, event: str, data: Any) -> None:
        super().publish(topic, event, data)
        if event == "stage" and data.get("stage") in ("done", "error"):
            self.on_finished(data["filename"])


def _remove_uploads(repo: Repo, claim_ids: list[str]) -> None:
    """The orchestrator's stored uploads are scratch copies of committed fixtures."""
    for cid in claim_ids:
        for doc in repo.get_claim(cid).documents:
            Path(doc.stored_path).unlink(missing_ok=True)


async def run_eval(
    settings: Settings,
    subset: str = "full",
    provider: LLMProvider | None = None,
    on_progress: Progress | None = None,
    fixtures_dir: Path = FIXTURES,
    baseline_path: Path = BASELINE,
    created_at: dt.datetime | None = None,
) -> EvalRun:
    manifest, rows = load_fixtures(fixtures_dir)
    if manifest.get("employee_name"):  # the receipts are printed for this claimant, whatever .env says
        settings = settings.model_copy(update={"EMPLOYEE_NAME": manifest["employee_name"]})
    claims = [c for c in manifest["claims"] if subset == "full" or c["smoke"]]
    total = sum(len(c["fixtures"]) for c in claims)
    now = dt.datetime.combine(dt.date.fromisoformat(manifest["eval_date"]), dt.time(12))
    by_file = {r["file"]: r for r in rows.values()}
    done = 0

    def finished(filename: str) -> None:
        nonlocal done
        done += 1
        if on_progress:
            on_progress(done, total, by_file[filename]["id"])

    with tempfile.TemporaryDirectory(prefix="claimpilot-eval-") as tmp:
        db = Database(f"sqlite:///{Path(tmp) / 'eval.db'}")
        db.create_all()
        repo, tracer = Repo(db), Tracer(db)
        ensure_ruleset(repo, settings)
        llm = build_client(settings, tracer, provider)
        orch = Orchestrator(
            settings, repo, llm, tracer, _ProgressBroker(finished), MockFinance(repo, 0, 0), lambda: now
        )
        if on_progress:
            on_progress(0, total, None)
        claim_ids: list[str] = []
        try:
            for c in claims:
                claim = orch.create_claim(manifest["user_id"], c["title"])
                claim_ids.append(claim.id)
                uploads = [
                    Upload(rows[f]["file"], (fixtures_dir / rows[f]["file"]).read_bytes())
                    for f in c["fixtures"]
                ]
                await orch.add_documents(claim.id, uploads)
                await orch.wait_idle()  # claims run in order so later ones see earlier ones as history
            results = [repo.get_claim(cid) for cid in claim_ids]
            docs = repo.get_documents([d for cl in results for x in cl.lines for d in x.document_ids])
        finally:
            await orch.wait_idle()
            _remove_uploads(repo, claim_ids)
        spans = tracer.spans_since(dt.datetime(2000, 1, 1))

    fixture_of = {x.id: by_file[docs[x.document_ids[0]].filename]["id"] for cl in results for x in cl.lines}
    observed = sorted(
        (Observed(rows[fixture_of[x.id]], x) for cl in results for x in cl.lines), key=lambda o: o.truth["id"]
    )
    per_field, macro, micro, pairs = score_fields(observed)
    dups = duplicate_scores(observed, fixture_of)
    violations = violation_scores(observed)
    stats = run_stats(results, spans, len(observed))
    metrics = EvalMetrics(
        field_accuracy=macro,
        amount_exact_rate=per_field["total_amount"].accuracy if "total_amount" in per_field else 0.0,
        date_exact_rate=per_field["date"].accuracy if "date" in per_field else 0.0,
        gstin_exact_rate=per_field["vendor_gstin"].accuracy if "vendor_gstin" in per_field else 0.0,
        dup_precision=dups["precision"],
        dup_recall=dups["recall"],
        violation_accuracy=violations["accuracy"],
        ece=ece(pairs),
        **{
            k: stats[k]
            for k in (
                "questions_per_claim",
                "auto_completion_rate",
                "p50_latency_ms",
                "p95_latency_ms",
                "mean_tokens",
                "cost_usd_per_receipt",
            )
        },
    )
    passed, gate_messages = gate.check(metrics.model_dump(), gate.load_baseline(baseline_path, subset))
    models = Counter(str(s.attributes.get("model")) for s in spans if s.name == "llm" and s.status == "ok")
    return EvalRun(
        id=new_id("run"),
        created_at=created_at or utcnow(),
        provider=llm.provider.name,
        model=models.most_common(1)[0][0] if models else llm.provider.model,
        prompt_version=llm.extract_request([]).prompt_version,
        n_receipts=len(observed),
        metrics=metrics,
        per_field=per_field,
        reliability_bins=reliability(pairs),
        passed_gate=passed,
        git_sha=settings.GIT_SHA or git_sha(),
        subset=subset,
        details={
            "field_accuracy_micro": micro,
            "brier": brier(pairs),
            "scored_cells": len(pairs),
            "duplicates": dups,
            "violations": violations,
            "upi_links": upi_link_scores(observed, fixture_of),
            "llm_calls": stats["llm_calls"],
            "llm_retries": stats["llm_retries"],
            "eval_date": manifest["eval_date"],
            "gate": gate_messages,
        },
    )


def comparison(runs: list[EvalRun]) -> list[EvalRun]:
    """Latest run per (provider, model, prompt_version, subset)."""
    latest: dict[tuple, EvalRun] = {}
    for run in sorted(runs, key=lambda r: r.created_at):
        latest[(run.provider, run.model, run.prompt_version, run.subset)] = run
    return sorted(latest.values(), key=lambda r: -r.metrics.field_accuracy)


def _print_run(run: EvalRun) -> None:
    m, d = run.metrics, run.details
    print(
        f"\n{run.id}  {run.provider}/{run.model}  prompt {run.prompt_version}"
        f"  {run.subset}  n={run.n_receipts}"
    )
    print(f"  field accuracy  macro {m.field_accuracy:.3f}  micro {d['field_accuracy_micro']:.3f}")
    print(f"  amount {m.amount_exact_rate:.3f}  date {m.date_exact_rate:.3f}  gstin {m.gstin_exact_rate:.3f}")
    print(
        f"  duplicates      P {m.dup_precision:.3f}  R {m.dup_recall:.3f}"
        f"  ({d['duplicates']['flagged_pairs']} flagged / {d['duplicates']['true_pairs']} true)"
    )
    print(f"  violations      {m.violation_accuracy:.3f}   UPI links R {d['upi_links']['recall']:.3f}")
    print(f"  calibration     ECE {m.ece:.4f}  Brier {d['brier']:.4f}")
    print(f"  questions/claim {m.questions_per_claim:.2f}  auto-complete {m.auto_completion_rate:.3f}")
    print(
        f"  latency p50/p95 {m.p50_latency_ms:.0f}/{m.p95_latency_ms:.0f} ms"
        f"  tokens {m.mean_tokens:.0f}  ${m.cost_usd_per_receipt:.4f}/receipt"
    )
    for name, fm in run.per_field.items():
        print(f"    {name:<16} {fm.accuracy:.3f}  n={fm.n:<3} conf {fm.mean_confidence:.2f}")
    for fp in d["duplicates"]["false_positives"]:
        print(f"  dup false positive {fp}")
    for miss in d["duplicates"]["missed"]:
        print(f"  dup missed {miss}")
    for mm in d["violations"]["mismatches"]:
        print(f"  violation mismatch {mm}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ClaimPilot evaluation harness")
    p.add_argument("--subset", choices=["smoke", "full"], default="full")
    p.add_argument("--provider", choices=["replay", "claude_code", "gemini", "anthropic", "oracle"])
    p.add_argument("--prompt-version", help="pin the extraction prompt (e.g. v1)")
    p.add_argument("--record", action="store_true", help="record live responses to data/replay")
    p.add_argument("--gate", action="store_true", help="exit 1 if the run regresses against the baseline")
    p.add_argument("--write-baseline", action="store_true", help="store this run as the subset's baseline")
    p.add_argument("--no-save", action="store_true", help="do not store the EvalRun in the app database")
    p.add_argument(
        "--compare", action="store_true", help="print the latest stored run per provider/model/prompt"
    )
    args = p.parse_args(argv)

    updates: dict[str, Any] = {"LLM_RECORD": args.record}
    if args.provider and args.provider != "oracle":
        updates["LLM_PROVIDER"] = args.provider
    if args.prompt_version:
        updates["PROMPT_VERSION_EXTRACT"] = args.prompt_version
    settings = get_settings().model_copy(update=updates)
    repo = Repo(Database(settings.DATABASE_URL))
    repo.db.create_all()
    if args.compare:
        for run in comparison(repo.list_eval_runs()):
            _print_run(run)
        return 0

    provider = None
    if args.provider == "oracle":
        provider = OracleProvider(list(load_fixtures()[1].values()), FIXTURES)

    def progress(done: int, total: int, fixture: str | None) -> None:
        print(f"\r  {done}/{total} {fixture or ''}   ", end="", file=sys.stderr, flush=True)

    run = asyncio.run(run_eval(settings, args.subset, provider, progress, baseline_path=BASELINE))
    print(file=sys.stderr)
    _print_run(run)
    if not args.no_save:
        repo.save_eval_run(run)
    if args.write_baseline:
        gate.write_baseline(BASELINE, run)
        print(f"baseline for '{args.subset}' written to {BASELINE}")
    for msg in run.details["gate"]:
        print(f"gate: {msg}")
    print(f"gate: {'PASS' if run.passed_gate else 'FAIL'}")
    return 1 if args.gate and not run.passed_gate else 0


if __name__ == "__main__":
    raise SystemExit(main())
