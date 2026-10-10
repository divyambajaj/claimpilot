"""Provider adapters, fully offline: subprocess, httpx (respx) and the Anthropic SDK are all mocked."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest
import respx

from app.config import Settings
from app.llm.base import ImageInput, LLMError, LLMRequest, MalformedOutputError, TransportError
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.claude_code import ClaudeCodeProvider
from app.llm.providers.gemini import BASE_URL, GeminiProvider
from app.llm.providers.replay import ReplayProvider
from app.llm.registry import build_client, build_provider
from app.observability.tracing import Tracer

SCHEMA = {
    "type": "object",
    "properties": {"a": {"type": "integer"}},
    "required": ["a"],
    "additionalProperties": False,
}


def _req(images: list[ImageInput] | None = None) -> LLMRequest:
    return LLMRequest(
        prompt_name="p",
        prompt_version="v1",
        system="sys",
        user_text="do it",
        images=images or [],
        json_schema=SCHEMA,
    )


# --- claude_code -------------------------------------------------------------------------------------
class _Proc:
    def __init__(self, stdout: bytes, returncode: int = 0, hang: bool = False) -> None:
        self._stdout, self.returncode, self._hang = stdout, returncode, hang
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.sleep(10)
        return self._stdout, b"boom"

    def kill(self) -> None:
        self.killed = True


def _patch_exec(monkeypatch: pytest.MonkeyPatch, proc: _Proc) -> list[tuple]:
    calls: list[tuple] = []

    async def fake_exec(*args: Any, **kwargs: Any) -> _Proc:
        calls.append(args)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls


class TestClaudeCode:
    async def test_success_parses_structured_output(self, monkeypatch, tmp_path: Path) -> None:
        envelope = {
            "structured_output": {"a": 1},
            "total_cost_usd": 0.04,
            "duration_ms": 9000,
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 20},
            "is_error": False,
        }
        calls = _patch_exec(monkeypatch, _Proc(json.dumps(envelope).encode()))
        provider = ClaudeCodeProvider("sonnet", tmp_path)
        resp = await provider.complete_structured(_req([ImageInput(data=b"png-bytes")]))
        assert resp.data == {"a": 1}
        assert resp.usage.cost_usd == 0.04
        assert resp.usage.input_tokens == 100
        assert resp.latency_ms == 9000
        cmd = calls[0]
        assert cmd[0] == "claude" and "--json-schema" in cmd and cmd[cmd.index("--model") + 1] == "sonnet"
        assert "Read the image file(s) " + str(tmp_path) in cmd[2]

    async def test_uses_existing_absolute_path(self, monkeypatch, tmp_path: Path) -> None:
        img = tmp_path / "r.png"
        img.write_bytes(b"x")
        calls = _patch_exec(monkeypatch, _Proc(json.dumps({"structured_output": {"a": 1}}).encode()))
        await ClaudeCodeProvider("sonnet", tmp_path).complete_structured(
            _req([ImageInput(data=b"x", path=str(img))])
        )
        assert str(img) in calls[0][2]

    async def test_falls_back_to_result_text(self, monkeypatch, tmp_path: Path) -> None:
        _patch_exec(
            monkeypatch, _Proc(json.dumps({"result": '{"a": 2}', "usage": {"output_tokens": 5}}).encode())
        )
        resp = await ClaudeCodeProvider("sonnet", tmp_path).complete_structured(_req())
        assert resp.data == {"a": 2}
        assert resp.usage.cost_usd is not None  # estimated from the price table

    @pytest.mark.parametrize(
        ("stdout", "exc"),
        [
            (b"not json", MalformedOutputError),
            (json.dumps({"result": "sorry, no"}).encode(), MalformedOutputError),
            (json.dumps({"structured_output": [1]}).encode(), MalformedOutputError),
            (json.dumps({"is_error": True, "result": "limit"}).encode(), LLMError),
        ],
    )
    async def test_bad_output(self, monkeypatch, tmp_path: Path, stdout: bytes, exc: type) -> None:
        _patch_exec(monkeypatch, _Proc(stdout))
        with pytest.raises(exc):
            await ClaudeCodeProvider("sonnet", tmp_path).complete_structured(_req())

    async def test_nonzero_exit_is_transport_error(self, monkeypatch, tmp_path: Path) -> None:
        _patch_exec(monkeypatch, _Proc(b"", returncode=1))
        with pytest.raises(TransportError, match="exited 1"):
            await ClaudeCodeProvider("sonnet", tmp_path).complete_structured(_req())

    async def test_timeout_kills_process(self, monkeypatch, tmp_path: Path) -> None:
        proc = _Proc(b"", hang=True)
        _patch_exec(monkeypatch, proc)
        with pytest.raises(TransportError, match="timed out"):
            await ClaudeCodeProvider("sonnet", tmp_path, timeout_s=0.01).complete_structured(_req())
        assert proc.killed


# --- gemini ------------------------------------------------------------------------------------------
URL = f"{BASE_URL}/models/gemini-2.5-flash:generateContent"


def _gemini_ok(text: str) -> httpx.Response:
    body = {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 200},
    }
    return httpx.Response(200, json=body)


class TestGemini:
    @respx.mock
    async def test_success(self) -> None:
        route = respx.post(URL).mock(return_value=_gemini_ok('{"a": 3}'))
        resp = await GeminiProvider("k", "gemini-2.5-flash").complete_structured(
            _req([ImageInput(data=b"img")])
        )
        assert resp.data == {"a": 3}
        assert resp.usage.input_tokens == 1000 and resp.usage.cost_usd > 0
        sent = json.loads(route.calls[0].request.content)
        assert sent["generationConfig"]["responseJsonSchema"] == SCHEMA
        assert sent["contents"][0]["parts"][0]["inlineData"]["mimeType"] == "image/png"
        assert route.calls[0].request.headers["x-goog-api-key"] == "k"

    @respx.mock
    async def test_429_is_retryable_with_retry_after(self) -> None:
        respx.post(URL).mock(return_value=httpx.Response(429, headers={"retry-after": "7"}))
        with pytest.raises(TransportError) as info:
            await GeminiProvider("k", "gemini-2.5-flash").complete_structured(_req())
        assert info.value.retry_after == 7.0

    @respx.mock
    async def test_400_is_fatal(self) -> None:
        respx.post(URL).mock(return_value=httpx.Response(400, text="bad"))
        with pytest.raises(LLMError):
            await GeminiProvider("k", "gemini-2.5-flash").complete_structured(_req())

    @respx.mock
    async def test_network_error(self) -> None:
        respx.post(URL).mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(TransportError):
            await GeminiProvider("k", "gemini-2.5-flash").complete_structured(_req())

    @respx.mock
    @pytest.mark.parametrize(
        "response", [_gemini_ok("not json"), httpx.Response(200, json={"candidates": []})]
    )
    async def test_malformed(self, response: httpx.Response) -> None:
        respx.post(URL).mock(return_value=response)
        with pytest.raises(MalformedOutputError):
            await GeminiProvider("k", "gemini-2.5-flash").complete_structured(_req())

    def test_requires_key(self) -> None:
        with pytest.raises(LLMError):
            GeminiProvider("", "m")


# --- anthropic ---------------------------------------------------------------------------------------
class _Messages:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _message(text: str, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=1200, output_tokens=300),
    )


def _status_error(cls: type, status: int, headers: dict | None = None) -> Exception:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status, headers=headers or {}, request=request)
    return cls("err", response=response, body=None)


def _anthropic(result: Any) -> tuple[AnthropicProvider, _Messages]:
    messages = _Messages(result)
    return AnthropicProvider(None, "claude-sonnet-5-5", client=SimpleNamespace(messages=messages)), messages


class TestAnthropic:
    async def test_success_uses_structured_outputs(self) -> None:
        provider, messages = _anthropic(_message('{"a": 4}'))
        resp = await provider.complete_structured(_req([ImageInput(data=b"img", mime="image/jpeg")]))
        assert resp.data == {"a": 4}
        assert resp.usage.cost_usd == pytest.approx((1200 * 2 + 300 * 10) / 1e6)
        kw = messages.kwargs
        assert kw["output_config"]["format"]["type"] == "json_schema"
        assert "tool_choice" not in kw and "tools" not in kw and "temperature" not in kw
        image = kw["messages"][0]["content"][0]
        assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg"

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (_status_error(anthropic.RateLimitError, 429, {"retry-after": "3"}), TransportError),
            (_status_error(anthropic.InternalServerError, 529), TransportError),
            (_status_error(anthropic.BadRequestError, 400), LLMError),
            (anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")), TransportError),
        ],
    )
    async def test_error_mapping(self, error: Exception, expected: type) -> None:
        provider, _ = _anthropic(error)
        with pytest.raises(expected) as info:
            await provider.complete_structured(_req())
        if isinstance(error, anthropic.RateLimitError):
            assert info.value.retry_after == 3.0

    @pytest.mark.parametrize("msg", [_message("nope"), _message('{"a": 1}', stop_reason="refusal")])
    async def test_malformed(self, msg: SimpleNamespace) -> None:
        provider, _ = _anthropic(msg)
        with pytest.raises(MalformedOutputError):
            await provider.complete_structured(_req())

    def test_requires_key(self) -> None:
        with pytest.raises(LLMError):
            AnthropicProvider(None, "m")


# --- registry ----------------------------------------------------------------------------------------
class TestRegistry:
    def test_builds_each_provider(self, tmp_path: Path) -> None:
        base = Settings(DATA_DIR=tmp_path, GEMINI_API_KEY="g", ANTHROPIC_API_KEY="a", _env_file=None)
        for name, cls in [
            ("replay", ReplayProvider),
            ("claude_code", ClaudeCodeProvider),
            ("gemini", GeminiProvider),
            ("anthropic", AnthropicProvider),
        ]:
            assert isinstance(build_provider(base.model_copy(update={"LLM_PROVIDER": name})), cls)

    def test_recorder_only_for_live_providers(self, tmp_path: Path) -> None:
        settings = Settings(DATA_DIR=tmp_path, LLM_RECORD=True, _env_file=None)
        assert build_client(settings, Tracer(None)).recorder is None
        live = settings.model_copy(update={"LLM_PROVIDER": "claude_code"})
        assert build_client(live, Tracer(None)).recorder is not None
