"""Replay fingerprint (section 3.4): provider/model-independent so recordings replay anywhere."""

import hashlib
import json
from typing import Any


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def fingerprint(
    prompt_name: str, prompt_version: str, schema: dict[str, Any], text: str, image_ids: list[str]
) -> str:
    parts = [
        prompt_name,
        prompt_version,
        sha256_hex(json.dumps(schema, sort_keys=True, separators=(",", ":"))),
        sha256_hex(text),
        *image_ids,
    ]
    return sha256_hex("|".join(parts))
