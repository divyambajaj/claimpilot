"""Keyless provider: serves responses recorded by `Recorder`, keyed by request fingerprint."""

import asyncio
import json
from pathlib import Path

from app.llm.base import LLMRequest, LLMResponse, ReplayMissError, Usage


class ReplayProvider:
    name = "replay"
    supports_vision = True

    def __init__(self, replay_dir: Path, delay_s: float = 0.0) -> None:
        self.replay_dir = replay_dir
        self.delay_s = delay_s  # paces a recorded demo so per-document progress is visible
        self.model = "recorded"

    def has(self, req: LLMRequest) -> bool:
        return (self.replay_dir / f"{req.fingerprint()}.json").exists()

    async def complete_structured(self, req: LLMRequest) -> LLMResponse:
        fp = req.fingerprint()
        path = self.replay_dir / f"{fp}.json"
        if not path.exists():
            raise ReplayMissError(fp)
        rec = json.loads(path.read_text())
        await asyncio.sleep(self.delay_s)
        return LLMResponse(
            data=rec["response"]["data"],
            raw_text=rec["response"].get("raw_text", ""),
            provider=self.name,
            model=rec.get("model", "recorded"),
            latency_ms=int(rec.get("latency_ms", 0)),
            usage=Usage.model_validate(rec.get("usage") or {}),
            replayed=True,
        )
