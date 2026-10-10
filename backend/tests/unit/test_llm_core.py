"""Fingerprint, recorder/replay, prompt registry and LLMClient retry/repair behaviour."""

import json
from pathlib import Path

import pytest

from app.llm.base import (
    ImageInput,
    LLMError,
    LLMRequest,
    LLMResponse,
    MalformedOutputError,
    ReplayMissError,
    TransportError,
    Usage,
)
from app.llm.client import StructuredOutputError
from app.llm.prompts.registry import PromptRegistry
from app.llm.providers.replay import ReplayProvider
from app.llm.recorder import Recorder, scrub
from app.observability.tracing import Tracer
from app.pipeline.extract import extraction_schema
from tests.factories import FakeProvider, extraction_payload


def _req(**kw) -> LLMRequest:
    base = {
        "prompt_name": "extract_receipt",
        "prompt_version": "v1",
        "system": "sys",
        "user_text": "user",
        "images": [ImageInput(data=b"img-bytes")],
        "json_schema": {"type": "object"},
    }
    return LLMRequest(**{**base, **kw})


class TestFingerprint:
    def test_stable_and_independent_of_paths(self) -> None:
        a = _req()
        b = _req(images=[ImageInput(data=b"img-bytes", path="/somewhere/else.png")])
        assert a.fingerprint() == b.fingerprint()

    @pytest.mark.parametrize(
        "change",
        [
            {"prompt_version": "v2"},
            {"json_schema": {"type": "array"}},
            {"user_text": "other"},
            {"images": [ImageInput(data=b"different")]},
        ],
    )
    def test_changes_with_inputs(self, change: dict) -> None:
        assert _req().fingerprint() != _req(**change).fingerprint()

    def test_image_key_overrides_bytes(self) -> None:
        a = _req(images=[ImageInput(data=b"x", key="sha:0")])
        b = _req(images=[ImageInput(data=b"y", key="sha:0")])
        assert a.fingerprint() == b.fingerprint()


class TestRecorderReplay:
    async def test_record_then_replay(self, tmp_path: Path) -> None:
        req = _req()
        resp = LLMResponse(
            data={"a": 1},
            raw_text="{}",
            provider="live",
            model="m1",
            latency_ms=42,
            usage=Usage(input_tokens=10, output_tokens=5, cost_usd=0.01),
        )
        path = Recorder(tmp_path).save(req, resp)
        stored = json.loads(path.read_text())
        assert "img-bytes" not in path.read_text()
        assert stored["request_meta"]["images"][0]["bytes"] == len(b"img-bytes")

        replayed = await ReplayProvider(tmp_path).complete_structured(req)
        assert replayed.data == {"a": 1}
        assert replayed.replayed is True
        assert replayed.usage.cost_usd == 0.01
        assert replayed.model == "m1"

    async def test_miss_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ReplayMissError):
            await ReplayProvider(tmp_path).complete_structured(_req())

    def test_scrub_redacts_keys(self) -> None:
        out = scrub(
            {"x": ["key " + "sk-ant-" + "abc123-def", "AIza" + "b" * 30]}
        )  # split so make lint sees no key
        assert out == {"x": ["key [redacted]", "[redacted]"]}


class TestPromptRegistry:
    def test_latest_and_pinned(self, tmp_path: Path) -> None:
        d = tmp_path / "demo"
        d.mkdir()
        for v in (1, 2, 10):
            (d / f"v{v}.md").write_text(
                f"---\nversion: v{v}\n---\n# System\nsys {v}\n# User\nhello {{{{name}}}}\n"
            )
        reg = PromptRegistry(tmp_path)
        assert reg.versions("demo") == ["v1", "v2", "v10"]
        assert reg.get("demo").version == "v10"
        assert reg.get("demo", "v2").system == "sys 2"
        assert PromptRegistry(tmp_path, pins={"demo": "v1"}).get("demo").version == "v1"
        assert reg.get("demo").render_user(name="Asha") == "hello Asha"

    def test_missing(self, tmp_path: Path) -> None:
        with pytest.raises(KeyError):
            PromptRegistry(tmp_path).get("nope")
        (tmp_path / "bad").mkdir()
        (tmp_path / "bad" / "v1.md").write_text("no front matter")
        with pytest.raises(ValueError, match="front matter"):
            PromptRegistry(tmp_path).get("bad")

    def test_shipped_prompts_load(self) -> None:
        reg = PromptRegistry()
        assert "verbatim" in reg.get("compile_policy").system
        assert reg.get("extract_receipt").version == "v3"
        assert reg.versions("extract_receipt") == ["v1", "v2", "v3"]

    def test_schema_versions(self) -> None:
        v1, v2 = extraction_schema(schema=1), extraction_schema(schema=2)
        assert "payee_type" not in v1["properties"] and "payer_name" in v2["properties"]
        assert "personal" not in v1["properties"]["category"]["properties"]["value"]["enum"]
        assert (
            "personal"
            in extraction_schema(core=True, schema=2)["properties"]["category"]["properties"]["value"]["enum"]
        )


class TestClient:
    async def test_extract_success_records_and_traces(
        self, make_client, tmp_path: Path, tracer: Tracer
    ) -> None:
        provider = FakeProvider([extraction_payload(total_amount=500.0)])
        client = make_client(provider, Recorder(tmp_path))
        with tracer.trace("claim", "C1") as trace_id:
            receipt, resp = await client.extract([ImageInput(data=b"png")])
        assert receipt.total_amount.value == 500.0
        assert resp.attempt == 1
        assert len(list(tmp_path.glob("*.json"))) == 1
        spans = tracer.get_trace(trace_id).spans
        assert [s.name for s in spans] == ["llm"]
        assert spans[0].attributes["tokens_in"] == 100
        assert spans[0].attributes["prompt_version"] == "v3"

    async def test_repair_then_core_fallback(self, make_client) -> None:
        provider = FakeProvider([{"bogus": 1}, MalformedOutputError("not json", "xx"), extraction_payload()])
        receipt, resp = await make_client(provider).extract([ImageInput(data=b"png")])
        assert resp.attempt == 3
        assert "failed validation" in provider.requests[1].user_text
        core_props = provider.requests[2].json_schema["properties"]
        assert "items" not in core_props and "vendor_gstin" not in core_props
        assert receipt.vendor_name.value == "Chaiwala Corner Pvt Ltd"

    async def test_gives_up_after_three_invalid(self, make_client) -> None:
        provider = FakeProvider([{"bogus": 1}] * 3)
        with pytest.raises(StructuredOutputError):
            await make_client(provider).extract([ImageInput(data=b"png")])

    async def test_transport_retry_with_backoff(self, make_client, tracer: Tracer) -> None:
        provider = FakeProvider(
            [TransportError("429", retry_after=2.0), TransportError("503"), extraction_payload()]
        )
        client = make_client(provider)
        delays: list[float] = []

        async def fake_sleep(d: float) -> None:
            delays.append(d)

        client.sleep = fake_sleep
        with tracer.trace("claim") as trace_id:
            await client.extract([ImageInput(data=b"png")])
        assert delays == [2.0, 3.0]
        assert [s.status for s in tracer.get_trace(trace_id).spans] == ["retry", "retry", "ok"]

    async def test_transport_exhausted_raises(self, make_client) -> None:
        provider = FakeProvider([TransportError("x")] * 3)
        with pytest.raises(TransportError):
            await make_client(provider).extract([ImageInput(data=b"png")])

    async def test_non_retryable_propagates(self, make_client) -> None:
        with pytest.raises(LLMError):
            await make_client(FakeProvider([LLMError("401")])).extract([])

    async def test_compile_policy_parses_draft(self, make_client) -> None:
        draft = {
            "required_fields": {"any": ["date", "amount_inr"]},
            "rules": [
                {
                    "id": "LATE_CLAIM",
                    "title": "Late claim",
                    "category": "any",
                    "scope": "line",
                    "when": {"field": "days_since_expense", "op": "gt", "value": 30},
                    "action": {"type": "require_justification"},
                    "severity": "warn",
                    "message_template": "late",
                    "citation": {"section": "2.3", "quote": "Claims must be submitted within 30 days."},
                    "confidence": 0.9,
                }
            ],
        }
        parsed, _ = await make_client(FakeProvider([draft])).compile_policy("policy text")
        assert parsed.rules[0].id == "LATE_CLAIM"
