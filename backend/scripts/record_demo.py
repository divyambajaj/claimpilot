"""Run the demo gallery through the configured live provider and record replay files (`make record-demo`).

Uses the same ingest + LLMClient.extract path as the orchestrator, so the fingerprints match at replay time.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.llm.base import ImageInput
from app.llm.registry import build_client
from app.observability.tracing import Tracer
from app.pipeline.ingest import ingest_bytes


async def record(paths: list[Path]) -> None:
    settings = get_settings().model_copy(update={"LLM_RECORD": True})
    if settings.LLM_PROVIDER == "replay":
        raise SystemExit("set LLM_PROVIDER to a live provider (e.g. claude_code) to record")
    client = build_client(settings, Tracer(None))

    async def one(path: Path) -> None:
        _, pages = ingest_bytes(path.read_bytes())
        images = [ImageInput(data=p.png, key=p.replay_key, path=str(path.resolve())) for p in pages]
        receipt, resp = await client.extract(images)
        summary = {
            k: receipt.field(k).value
            for k in ("vendor_name", "vendor_gstin", "date", "total_amount", "payment_method", "category")
        }
        print(
            f"{path.name}: {resp.latency_ms} ms, ${resp.usage.cost_usd}, {json.dumps(summary, default=str)}"
        )

    results = await asyncio.gather(*(one(p) for p in paths), return_exceptions=True)
    for path, res in zip(paths, results, strict=True):
        if isinstance(res, Exception):
            print(f"{path.name}: FAILED {type(res).__name__}: {res}")


def main() -> None:
    settings = get_settings()
    targets = [Path(a) for a in sys.argv[1:]] or sorted(settings.demo_dir.glob("*.png"))
    asyncio.run(record(targets))


if __name__ == "__main__":
    main()
