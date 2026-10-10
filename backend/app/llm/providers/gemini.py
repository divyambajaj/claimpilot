"""Gemini `generateContent` over REST (httpx), JSON-schema constrained output."""

import base64
import json
import time

import httpx

from app.llm.base import LLMError, LLMRequest, LLMResponse, MalformedOutputError, TransportError, Usage
from app.observability.cost import estimate_cost_usd

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    name = "gemini"
    supports_vision = True

    def __init__(self, api_key: str, model: str, timeout_s: float = 120.0) -> None:
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    def build_body(self, req: LLMRequest) -> dict:
        parts: list[dict] = [
            {"inlineData": {"mimeType": i.mime, "data": base64.b64encode(i.data).decode()}}
            for i in req.images
        ]
        parts.append({"text": req.user_text})
        return {
            "systemInstruction": {"parts": [{"text": req.system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": req.json_schema,
                "temperature": req.temperature,
                "maxOutputTokens": req.max_tokens,
            },
        }

    async def complete_structured(self, req: LLMRequest) -> LLMResponse:
        url = f"{BASE_URL}/models/{self.model}:generateContent"
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                r = await client.post(
                    url, json=self.build_body(req), headers={"x-goog-api-key": self.api_key}
                )
        except httpx.HTTPError as exc:
            raise TransportError(f"gemini transport error: {exc}") from exc
        if r.status_code == 429 or r.status_code >= 500:
            retry_after = r.headers.get("retry-after")
            raise TransportError(f"gemini HTTP {r.status_code}", float(retry_after) if retry_after else None)
        if r.status_code >= 400:
            raise LLMError(f"gemini HTTP {r.status_code}: {r.text[:500]}")
        body = r.json()
        try:
            text = "".join(p.get("text", "") for p in body["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError) as exc:
            raise MalformedOutputError(
                "gemini response has no candidate text", json.dumps(body)[:2000]
            ) from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MalformedOutputError("gemini output is not JSON", text[:2000]) from exc
        meta = body.get("usageMetadata", {})
        tin, tout = meta.get("promptTokenCount"), meta.get("candidatesTokenCount")
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
