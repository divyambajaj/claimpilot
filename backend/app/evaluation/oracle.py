"""Perfect-perception provider: answers each fixture with its ground truth.

Running the eval with it isolates the deterministic half (dedupe, rules, planner): any duplicate or
violation miss under the oracle is a ground-truth or decision-code bug, not a perception error.
"""

import hashlib
from pathlib import Path
from typing import Any

from app.llm.base import LLMError, LLMRequest, LLMResponse, Usage
from app.pipeline.extract import FIELD_TYPES

ORACLE_CONFIDENCE = 0.95


def truth_payload(row: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name in FIELD_TYPES:
        value = row["fields"].get(name)
        value = value[0] if isinstance(value, list) else value
        data[name] = {
            "value": value,
            "confidence": ORACLE_CONFIDENCE if value is not None else 0.0,
            "source_snippet": None,
        }
    return data | {"items": row["items"], "raw_text": row["raw_text"], "quality": row["quality"]}


class OracleProvider:
    name = "oracle"
    model = "ground-truth"
    supports_vision = True

    def __init__(self, rows: list[dict[str, Any]], fixtures_dir: Path) -> None:
        self.by_sha = {hashlib.sha256((fixtures_dir / r["file"]).read_bytes()).hexdigest(): r for r in rows}

    async def complete_structured(self, req: LLMRequest) -> LLMResponse:
        sha = req.images[0].key.split(":")[0] if req.images and req.images[0].key else ""
        row = self.by_sha.get(sha)
        if row is None:
            raise LLMError("oracle: image is not an eval fixture")
        return LLMResponse(
            data=truth_payload(row),
            raw_text="",
            provider=self.name,
            model=self.model,
            latency_ms=0,
            usage=Usage(),
        )
