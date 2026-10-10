"""Records live LLM responses to `data/replay/{fingerprint}.json` (metadata only, never image bytes)."""

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from app.llm.base import LLMRequest, LLMResponse
from app.llm.fingerprint import sha256_hex

_SECRET = re.compile(r"(sk-ant-[\w-]+|AIza[\w-]{20,})")


def scrub(value: Any) -> Any:
    """Defensively redact anything that looks like an API key."""
    if isinstance(value, str):
        return _SECRET.sub("[redacted]", value)
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


class Recorder:
    def __init__(self, replay_dir: Path) -> None:
        self.replay_dir = replay_dir

    def path_for(self, fp: str) -> Path:
        return self.replay_dir / f"{fp}.json"

    def save(self, req: LLMRequest, resp: LLMResponse) -> Path:
        fp = req.fingerprint()
        record = {
            "fingerprint": fp,
            "recorded_at": dt.datetime.now(dt.UTC).isoformat(),
            "request_meta": {
                "prompt_name": req.prompt_name,
                "prompt_version": req.prompt_version,
                "schema_sha256": sha256_hex(
                    json.dumps(req.json_schema, sort_keys=True, separators=(",", ":"))
                ),
                "text_sha256": sha256_hex(req.system + "\n" + req.user_text),
                "images": [{"id": i.identity(), "bytes": len(i.data), "mime": i.mime} for i in req.images],
            },
            "provider": resp.provider,
            "model": resp.model,
            "latency_ms": resp.latency_ms,
            "usage": resp.usage.model_dump(),
            "response": {"data": resp.data, "raw_text": resp.raw_text},
        }
        self.replay_dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(fp)
        path.write_text(json.dumps(scrub(record), indent=2, ensure_ascii=False) + "\n")
        return path
