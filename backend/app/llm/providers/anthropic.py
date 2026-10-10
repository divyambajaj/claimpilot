"""Anthropic Messages API via the official SDK, using structured outputs (`output_config.format`)."""

import base64
import json
import time
from typing import Any

import anthropic

from app.llm.base import LLMError, LLMRequest, LLMResponse, MalformedOutputError, TransportError, Usage
from app.observability.cost import estimate_cost_usd


class AnthropicProvider:
    name = "anthropic"
    supports_vision = True

    def __init__(
        self,
        api_key: str | None,
        model: str,
        effort: str = "medium",
        timeout_s: float = 120.0,
        client: Any = None,
    ) -> None:
        if client is None and not api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        # Retries are owned by LLMClient so every attempt is traced.
        self.client = client or anthropic.AsyncAnthropic(api_key=api_key, max_retries=0, timeout=timeout_s)
        self.model = model
        self.effort = effort

    def build_params(self, req: LLMRequest) -> dict[str, Any]:
        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": i.mime,
                    "data": base64.standard_b64encode(i.data).decode(),
                },
            }
            for i in req.images
        ]
        content.append({"type": "text", "text": req.user_text})
        # No temperature: current models reject non-default sampling params.
        return {
            "model": self.model,
            "max_tokens": req.max_tokens,
            "system": req.system,
            "messages": [{"role": "user", "content": content}],
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": anthropic.transform_schema(req.json_schema)},
            },
        }

    async def complete_structured(self, req: LLMRequest) -> LLMResponse:
        started = time.monotonic()
        try:
            msg = await self.client.messages.create(**self.build_params(req))
        except anthropic.RateLimitError as exc:
            retry_after = exc.response.headers.get("retry-after")
            raise TransportError(
                "anthropic rate limited", float(retry_after) if retry_after else None
            ) from exc
        except anthropic.InternalServerError as exc:
            raise TransportError(f"anthropic server error {exc.status_code}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"anthropic HTTP {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:  # includes APITimeoutError
            raise TransportError(f"anthropic connection error: {exc}") from exc

        text = "".join(b.text for b in msg.content if b.type == "text")
        if msg.stop_reason in ("refusal", "max_tokens"):
            raise MalformedOutputError(f"anthropic stopped with {msg.stop_reason}", text[:2000])
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MalformedOutputError("anthropic output is not JSON", text[:2000]) from exc
        tin, tout = msg.usage.input_tokens, msg.usage.output_tokens
        return LLMResponse(
            data=data,
            raw_text=text,
            provider=self.name,
            model=self.model,
            latency_ms=int((time.monotonic() - started) * 1000),
            usage=Usage(
                input_tokens=tin, output_tokens=tout, cost_usd=estimate_cost_usd(self.model, tin, tout)
            ),
        )
