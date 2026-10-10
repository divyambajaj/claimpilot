"""Local provider that shells out to the `claude` CLI (headless, Read tool only, JSON-schema output)."""

import asyncio
import json
import tempfile
import time
from pathlib import Path

from app.llm.base import LLMError, LLMRequest, LLMResponse, MalformedOutputError, TransportError, Usage
from app.observability.cost import estimate_cost_usd

_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


class ClaudeCodeProvider:
    name = "claude_code"
    supports_vision = True

    def __init__(self, model: str, work_dir: Path, timeout_s: float = 120.0, binary: str = "claude") -> None:
        self.model = model
        self.work_dir = work_dir
        self.timeout_s = timeout_s
        self.binary = binary

    def _image_paths(self, req: LLMRequest) -> list[str]:
        paths = []
        for img in req.images:
            if img.path and Path(img.path).is_absolute() and Path(img.path).exists():
                paths.append(img.path)
                continue
            self.work_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=self.work_dir, suffix=_EXT.get(img.mime, ".png"), delete=False
            ) as fh:
                fh.write(img.data)
                paths.append(fh.name)
        return paths

    def build_command(self, req: LLMRequest) -> list[str]:
        paths = self._image_paths(req)
        prompt = req.system.strip() + "\n\n"
        if paths:
            prompt += "Read the image file(s) " + ", ".join(paths) + " then do the task below.\n\n"
        prompt += req.user_text
        return [
            self.binary,
            "-p",
            prompt,
            "--tools",
            "Read",
            "--allowedTools",
            "Read",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(req.json_schema),
            "--model",
            self.model,
        ]

    async def complete_structured(self, req: LLMRequest) -> LLMResponse:
        cmd = self.build_command(req)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=self.work_dir, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_s)
        except TimeoutError as exc:
            proc.kill()
            raise TransportError(f"claude CLI timed out after {self.timeout_s:.0f}s") from exc
        if proc.returncode != 0:
            raise TransportError(f"claude CLI exited {proc.returncode}: {stderr.decode()[-500:]}")
        return self._parse(stdout.decode(), int((time.monotonic() - started) * 1000))

    def _parse(self, stdout: str, wall_ms: int) -> LLMResponse:
        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise MalformedOutputError("claude CLI stdout is not JSON", stdout[-2000:]) from exc
        if envelope.get("is_error"):
            raise LLMError(f"claude CLI reported an error: {str(envelope.get('result'))[:500]}")
        data = envelope.get("structured_output")
        raw = envelope.get("result") or ""
        if data is None:
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError) as exc:
                raise MalformedOutputError("no structured_output in CLI response", str(raw)[:2000]) from exc
        if not isinstance(data, dict):
            raise MalformedOutputError("structured output is not an object", str(raw)[:2000])
        usage = envelope.get("usage") or {}
        tokens_in = sum(
            int(usage.get(k) or 0)
            for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        )
        tokens_out = usage.get("output_tokens")
        cost = envelope.get("total_cost_usd")
        if cost is None:
            cost = estimate_cost_usd(self.model, tokens_in, tokens_out)
        return LLMResponse(
            data=data,
            raw_text=json.dumps(data),
            provider=self.name,
            model=self.model,
            latency_ms=int(envelope.get("duration_ms") or wall_ms),
            usage=Usage(input_tokens=tokens_in or None, output_tokens=tokens_out, cost_usd=cost),
        )
