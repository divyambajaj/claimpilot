"""Keyless provider: serves responses recorded by `Recorder`, keyed by request fingerprint."""

import json
from pathlib import Path

from app.llm.base import LLMRequest, LLMResponse, ReplayMissError, Usage


class ReplayProvider:
    name = "replay"
    supports_vision = True

    def __init__(self, replay_dir: Path) -> None:
        self.replay_dir = replay_dir
        self.model = "recorded"

    async def complete_structured(self, req: LLMRequest) -> LLMResponse:
        fp = req.fingerprint()
        path = self.replay_dir / f"{fp}.json"
        if not path.exists():
            raise ReplayMissError(fp)
        rec = json.loads(path.read_text())
        return LLMResponse(
            data=rec["response"]["data"],
            raw_text=rec["response"].get("raw_text", ""),
            provider=self.name,
            model=rec.get("model", "recorded"),
            latency_ms=int(rec.get("latency_ms", 0)),
            usage=Usage.model_validate(rec.get("usage") or {}),
            replayed=True,
        )
