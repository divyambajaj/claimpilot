"""Regression gate against `data/eval/baseline.json` (section 12 tolerances), one baseline per subset."""

import json
from pathlib import Path
from typing import Any

from app.domain.models import EvalRun

# metric -> (direction, tolerance): "min" may not drop more than tol below baseline, "max" not rise above it
TOLERANCES: dict[str, tuple[str, float]] = {
    "field_accuracy": ("min", 0.02),
    "dup_recall": ("min", 0.05),
    "violation_accuracy": ("min", 0.02),
    "ece": ("max", 0.03),
    "questions_per_claim": ("max", 0.5),
}


def load_baseline(path: Path, subset: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text()).get(subset)


def check(metrics: dict[str, float], baseline: dict[str, Any] | None) -> tuple[bool, list[str]]:
    """(passed, messages). No baseline for the subset = pass with a warning."""
    if baseline is None:
        return True, ["no baseline for this subset; gate skipped (run `make eval-baseline`)"]
    failures = []
    for name, (direction, tol) in TOLERANCES.items():
        base, got = baseline["metrics"][name], metrics[name]
        if (direction == "min" and got < base - tol) or (direction == "max" and got > base + tol):
            failures.append(f"{name} {got:.4f} vs baseline {base:.4f} (tolerance {tol})")
    return not failures, failures


def write_baseline(path: Path, run: EvalRun) -> None:
    data = json.loads(path.read_text()) if path.exists() else {}
    data[run.subset or "full"] = {
        "run_id": run.id,
        "created_at": run.created_at.isoformat(),
        "provider": run.provider,
        "model": run.model,
        "prompt_version": run.prompt_version,
        "n_receipts": run.n_receipts,
        "metrics": run.metrics.model_dump(),
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
