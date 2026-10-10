"""Builds the configured provider and the LLMClient (`LLM_PROVIDER` env)."""

import asyncio

from app.config import Settings
from app.llm.base import LLMProvider
from app.llm.client import LLMClient
from app.llm.prompts.registry import PromptRegistry
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.claude_code import ClaudeCodeProvider
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.replay import ReplayProvider
from app.llm.recorder import Recorder
from app.observability.tracing import Tracer


def build_provider(settings: Settings) -> LLMProvider:
    match settings.LLM_PROVIDER:
        case "claude_code":
            return ClaudeCodeProvider(
                settings.CLAUDE_CODE_MODEL,
                settings.uploads_dir,
                settings.LLM_TIMEOUT_S,
                settings.CLAUDE_CODE_BIN,
            )
        case "gemini":
            return GeminiProvider(
                settings.GEMINI_API_KEY or "", settings.GEMINI_MODEL, settings.LLM_TIMEOUT_S
            )
        case "anthropic":
            return AnthropicProvider(
                settings.ANTHROPIC_API_KEY,
                settings.ANTHROPIC_MODEL,
                settings.ANTHROPIC_EFFORT,
                settings.LLM_TIMEOUT_S,
            )
        case _:
            return ReplayProvider(settings.replay_dir)


def build_prompts(settings: Settings) -> PromptRegistry:
    return PromptRegistry(
        pins={
            "extract_receipt": settings.PROMPT_VERSION_EXTRACT,
            "compile_policy": settings.PROMPT_VERSION_COMPILE,
        }
    )


def build_client(settings: Settings, tracer: Tracer, provider: LLMProvider | None = None) -> LLMClient:
    provider = provider or build_provider(settings)
    record = settings.LLM_RECORD and provider.name != "replay"
    return LLMClient(
        provider,
        Recorder(settings.replay_dir) if record else None,
        asyncio.Semaphore(settings.LLM_MAX_CONCURRENCY),
        tracer,
        build_prompts(settings),
    )
