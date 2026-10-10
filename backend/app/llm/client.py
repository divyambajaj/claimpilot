"""LLMClient: the only LLM surface the pipeline sees. Owns retries, schema validation, recording and spans."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import ValidationError

from app.domain.models import ExtractedReceipt
from app.llm.base import (
    ImageInput,
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    MalformedOutputError,
    TransportError,
)
from app.llm.prompts.registry import PromptRegistry
from app.llm.recorder import Recorder
from app.observability.tracing import Tracer
from app.pipeline.extract import extraction_schema, parse_extraction
from app.rules.dsl import RuleSetDraft

M = TypeVar("M")
BACKOFF_S = (1.0, 3.0)
TRANSPORT_ATTEMPTS = 3


class StructuredOutputError(LLMError):
    """All validation attempts failed; `raw_text` keeps the last output for debugging."""

    def __init__(self, message: str, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text


class _Invalid(Exception):
    def __init__(self, error: str, raw_text: str) -> None:
        self.error, self.raw_text = error, raw_text


def _repair(req: LLMRequest, error: str) -> LLMRequest:
    note = (
        "\n\nYour previous answer failed validation with these errors:\n"
        f"{error}\nReturn a corrected JSON object that satisfies the schema."
    )
    return req.model_copy(update={"user_text": req.user_text + note})


class LLMClient:
    def __init__(
        self,
        provider: LLMProvider,
        recorder: Recorder | None,
        limiter: asyncio.Semaphore,
        tracer: Tracer,
        prompts: PromptRegistry,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.provider = provider
        self.recorder = recorder
        self.limiter = limiter
        self.tracer = tracer
        self.prompts = prompts
        self.sleep = sleep

    def extract_request(self, images: list[ImageInput], prompt_version: str | None = None) -> LLMRequest:
        prompt = self.prompts.get("extract_receipt", prompt_version)
        return LLMRequest(
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            system=prompt.system,
            user_text=prompt.render_user(),
            images=images,
            json_schema=extraction_schema(schema=int(prompt.meta.get("schema", 1))),
        )

    def can_serve(self, images: list[ImageInput]) -> bool:
        """False only when a replay provider has no recording for these images."""
        has = getattr(self.provider, "has", None)
        return has is None or has(self.extract_request(images))

    async def extract(
        self, images: list[ImageInput], prompt_version: str | None = None
    ) -> tuple[ExtractedReceipt, LLMResponse]:
        req = self.extract_request(images, prompt_version)
        schema = int(self.prompts.get("extract_receipt", prompt_version).meta.get("schema", 1))
        core = req.model_copy(update={"json_schema": extraction_schema(core=True, schema=schema)})
        return await self._call(req, parse_extraction, fallback=core)

    async def compile_policy(
        self, policy_text: str, prompt_version: str | None = None
    ) -> tuple[RuleSetDraft, LLMResponse]:
        prompt = self.prompts.get("compile_policy", prompt_version)
        req = LLMRequest(
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            system=prompt.system,
            user_text=prompt.render_user(policy_text=policy_text),
            json_schema=RuleSetDraft.model_json_schema(by_alias=True),
            max_tokens=16000,
        )
        return await self._call(req, RuleSetDraft.model_validate)

    async def _call(
        self, req: LLMRequest, parse: Callable[[dict], M], fallback: LLMRequest | None = None
    ) -> tuple[M, LLMResponse]:
        """Attempt 1: as asked; 2: repair with the validation errors; 3: core-fields schema (or repair)."""
        current, raw = req, ""
        for attempt in (1, 2, 3):
            try:
                return await self._attempt(current, parse, attempt)
            except _Invalid as bad:
                raw = bad.raw_text
                current = fallback if (attempt == 2 and fallback is not None) else _repair(req, bad.error)
        raise StructuredOutputError(f"{req.prompt_name}: output failed validation 3 times", raw)

    async def _attempt(
        self, req: LLMRequest, parse: Callable[[dict], M], attempt: int
    ) -> tuple[M, LLMResponse]:
        for transport_try in range(TRANSPORT_ATTEMPTS):
            with self.tracer.span(
                "llm",
                provider=self.provider.name,
                model=self.provider.model,
                prompt_name=req.prompt_name,
                prompt_version=req.prompt_version,
                attempt=attempt,
                transport_try=transport_try + 1,
                fingerprint=req.fingerprint(),
            ) as span:
                try:
                    async with self.limiter:
                        resp = await self.provider.complete_structured(req)
                except TransportError as exc:
                    if transport_try == TRANSPORT_ATTEMPTS - 1:
                        raise
                    span.status = "retry"
                    span.set(error=str(exc)[:500])
                    delay = exc.retry_after or BACKOFF_S[transport_try]
                except MalformedOutputError as exc:
                    span.status = "retry"
                    span.set(error=str(exc)[:500])
                    raise _Invalid(str(exc), exc.raw_text) from exc
                else:
                    resp = resp.model_copy(update={"attempt": attempt})
                    span.set(
                        model=resp.model,
                        tokens_in=resp.usage.input_tokens,
                        tokens_out=resp.usage.output_tokens,
                        cost_usd=resp.usage.cost_usd,
                        latency_ms=resp.latency_ms,
                        replayed=resp.replayed,
                    )
                    try:
                        parsed = parse(resp.data)
                    except (ValidationError, ValueError) as exc:
                        span.status = "retry"
                        span.set(error=str(exc)[:500])
                        raise _Invalid(str(exc)[:2000], resp.raw_text) from exc
                    if self.recorder is not None and not resp.replayed:
                        self.recorder.save(req, resp)
                    return parsed, resp
            await self.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover
