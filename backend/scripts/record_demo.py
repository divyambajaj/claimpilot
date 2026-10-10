"""Record replay files for the demo gallery and the eval fixtures through the live provider (`make record-demo`).

Uses the same ingest + LLMClient.extract path as the orchestrator, so the fingerprints match at replay time.

    python backend/scripts/record_demo.py                 # gallery + eval fixtures, skip ones already recorded
    python backend/scripts/record_demo.py --only gallery  # or: eval
    python backend/scripts/record_demo.py --prompt-version v1 --force
    python backend/scripts/record_demo.py path/to/a.png   # explicit files
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.evaluation.runner import FIXTURES
from app.llm.base import ImageInput
from app.llm.registry import build_client
from app.observability.tracing import Tracer
from app.pipeline.ingest import ingest_bytes

SUFFIXES = (".png", ".jpg", ".jpeg", ".pdf")


def targets(only: str | None) -> list[Path]:
    settings = get_settings()
    gallery = sorted(p for p in settings.demo_dir.iterdir() if p.suffix in SUFFIXES)
    fixtures = sorted(p for p in FIXTURES.iterdir() if p.suffix in SUFFIXES)
    return {"gallery": gallery, "eval": fixtures}.get(only or "", gallery + fixtures)


async def record(paths: list[Path], prompt_version: str | None, force: bool) -> None:
    settings = get_settings().model_copy(update={"LLM_RECORD": True})
    if settings.LLM_PROVIDER == "replay":
        raise SystemExit("set LLM_PROVIDER to a live provider (e.g. claude_code) to record")
    client = build_client(settings, Tracer(None))
    seen: set[str] = set()

    async def one(path: Path) -> str:
        _, pages = ingest_bytes(path.read_bytes())
        images = [ImageInput(data=p.png, key=p.replay_key, path=str(path.resolve())) for p in pages]
        fp = client.extract_request(images, prompt_version).fingerprint()
        if fp in seen or (not force and (settings.replay_dir / f"{fp}.json").exists()):
            return "already recorded"  # byte-identical duplicates share one recording
        seen.add(fp)
        receipt, resp = await client.extract(images, prompt_version)
        summary = {k: receipt.field(k).value for k in ("vendor_name", "date", "total_amount", "category")}
        return f"{resp.latency_ms} ms, ${resp.usage.cost_usd}, {json.dumps(summary, default=str)}"

    results = await asyncio.gather(*(one(p) for p in paths), return_exceptions=True)
    for path, res in zip(paths, results, strict=True):
        print(f"{path.name}: {f'FAILED {type(res).__name__}: {res}' if isinstance(res, Exception) else res}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("files", nargs="*", type=Path)
    p.add_argument("--only", choices=["gallery", "eval"])
    p.add_argument("--prompt-version")
    p.add_argument("--force", action="store_true", help="re-record even if a replay file exists")
    args = p.parse_args()
    asyncio.run(record(args.files or targets(args.only), args.prompt_version, args.force))


if __name__ == "__main__":
    main()
