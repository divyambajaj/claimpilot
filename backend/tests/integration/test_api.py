"""HTTP API: claims edits/actions, uploads, demo gallery, admin, health, SSE, finance, seed, SPA."""

import asyncio
import datetime as dt
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.deps import Container
from app.api.sse import Broker, format_sse
from app.config import REPO_ROOT, Settings
from app.llm.base import LLMError
from app.main import build_container, create_app
from tests.factories import NOW, FakeProvider, extraction_payload
from tests.integration.conftest import wait_processed
from tests.unit.test_rules import POLICY_TEXT, _draft

DINNER = "restaurant_chaiwala_mumbai"


def _png(color: str = "white") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (80, 120), color).save(buf, format="PNG")
    return buf.getvalue()


def _dinner_claim(client: TestClient) -> dict:
    claim = client.post("/api/claims", json={"title": "Dinner"}).json()
    client.post(f"/api/claims/{claim['id']}/documents/from-demo", json={"names": [DINNER]})
    return wait_processed(client, claim["id"])


class TestClaimsApi:
    def test_list_get_404(self, client: TestClient) -> None:
        claim = client.post("/api/claims").json()
        assert claim["title"].startswith("Expenses ")
        assert [c["id"] for c in client.get("/api/claims").json()] == [claim["id"]]
        assert client.get("/api/claims", headers={"X-User-Id": "someone"}).json() == []
        r = client.get("/api/claims/nope")
        assert r.status_code == 404
        assert r.json()["code"] == "NotFoundError"

    def test_edit_line_writes_label_and_reevaluates(self, client: TestClient) -> None:
        claim = _dinner_claim(client)
        line = claim["lines"][0]
        assert line["reimbursable_inr"] == 3000.0
        claim = client.patch(
            f"/api/claims/{claim['id']}/lines/{line['id']}", json={"attendees_count": 6}
        ).json()
        line = claim["lines"][0]
        assert line["reimbursable_inr"] == 3780.0
        assert line["extracted"]["attendees_count"]["origin"] == "user"
        assert line["extracted"]["attendees_count"]["history"][0]["new_value"] == 6
        assert claim["status"] == "ready_to_submit"
        labels = client.get("/api/admin/labels").json()
        assert [(lb["field"], lb["predicted"], lb["corrected"]) for lb in labels] == [
            ("attendees_count", 4, 6)
        ]
        bad = client.patch(f"/api/claims/{claim['id']}/lines/{line['id']}", json={"date": "someday"})
        assert bad.status_code == 422

    def test_line_actions(self, client: TestClient) -> None:
        claim = _dinner_claim(client)
        cid, lid = claim["id"], claim["lines"][0]["id"]
        url = f"/api/claims/{cid}/lines/{lid}/actions"
        assert client.post(url, json={"action": "justify"}).status_code == 422
        claim = client.post(url, json={"action": "justify", "justification": "Client dinner"}).json()
        assert claim["lines"][0]["findings"][0]["resolution"] == "justified"
        assert claim["status"] == "ready_to_submit"
        claim = client.post(url, json={"action": "exclude"}).json()
        assert claim["lines"][0]["status"] == "excluded"
        assert claim["status"] == "draft"
        claim = client.post(url, json={"action": "restore"}).json()
        assert claim["lines"][0]["status"] == "complete"
        assert client.post(url, json={"action": "explode"}).status_code == 422
        assert (
            client.post(f"/api/claims/{cid}/lines/nope/actions", json={"action": "exclude"}).status_code
            == 422
        )

    def test_answers_validation(self, client: TestClient) -> None:
        claim = _dinner_claim(client)
        url = f"/api/claims/{claim['id']}/answers"
        q = claim["open_questions"][0]
        assert client.post(url, json=[{"question_id": "q:none"}]).status_code == 422
        assert client.post(url, json=[{"value": 1}]).status_code == 422
        assert client.post(url, json=[{"question_id": q["id"], "value": "  "}]).status_code == 422
        by_field = client.post(
            url, json=[{"line_id": claim["lines"][0]["id"], "field": "city", "value": "Pune"}]
        )
        assert by_field.json()["lines"][0]["extracted"]["city"]["value"] == "Pune"

    def test_duplicate_question_answers(self, client: TestClient, container: Container) -> None:
        first = _dinner_claim(client)
        dup_line = first["lines"][0]
        # A different file with the same bill content: fuzzy duplicate -> WARN + confirm question.
        second = client.post("/api/claims").json()
        line = dup_line.copy()
        claim = container.repo.get_claim(second["id"])
        from app.domain.models import LineItem
        from app.pipeline.dedupe.detector import DuplicateDetector, duplicate_finding

        copy = LineItem.model_validate(
            {**line, "id": "ln_copy", "claim_id": second["id"], "document_ids": []}
        )
        match = DuplicateDetector().find_duplicate(copy, [LineItem.model_validate(dup_line)], {})
        copy = copy.model_copy(update={"findings": [duplicate_finding(copy, match)]})
        container.repo.save_claim(claim.model_copy(update={"lines": [copy]}))
        claim = client.patch(f"/api/claims/{second['id']}/lines/ln_copy", json={}).json()
        q = next(q for q in claim["open_questions"] if q["kind"] == "confirm_duplicate")
        url = f"/api/claims/{second['id']}/answers"
        assert client.post(url, json=[{"question_id": q["id"], "value": "maybe"}]).status_code == 422
        claim = client.post(url, json=[{"question_id": q["id"], "value": "confirm"}]).json()
        assert claim["lines"][0]["status"] == "excluded"


class TestUploads:
    def test_limits_and_bad_files(self, client: TestClient, settings: Settings) -> None:
        cid = client.post("/api/claims").json()["id"]
        url = f"/api/claims/{cid}/documents"
        too_many = [
            ("files", (f"{i}.png", b"x", "image/png")) for i in range(settings.MAX_FILES_PER_REQUEST + 1)
        ]
        assert client.post(url, files=too_many).status_code == 400
        r = client.post(url, files=[("files", ("a.gif", b"GIF89a", "image/gif"))])
        assert r.status_code == 400
        assert r.json()["code"] == "IngestError"
        assert client.post(f"/api/claims/{cid}/documents/from-demo", json={"names": []}).status_code == 400
        assert (
            client.post(f"/api/claims/{cid}/documents/from-demo", json={"names": ["../secret"]}).status_code
            == 404
        )

    def test_too_large(self, client: TestClient, container: Container) -> None:
        container.settings.MAX_UPLOAD_MB = 0
        cid = client.post("/api/claims").json()["id"]
        r = client.post(f"/api/claims/{cid}/documents", files=[("files", ("a.png", _png(), "image/png"))])
        assert r.status_code == 413


class TestLiveProviderPath:
    @pytest.fixture
    def fake_client(self, settings: Settings):
        def build(responses):
            c = build_container(settings, provider=FakeProvider(responses), clock=lambda: NOW)
            return TestClient(create_app(c, dist=Path("/nonexistent"))), c

        return build

    def test_extraction_error_becomes_error_line(self, fake_client) -> None:
        client, _ = fake_client([LLMError("provider down")])
        with client:
            cid = client.post("/api/claims").json()["id"]
            r = client.post(f"/api/claims/{cid}/documents", files=[("files", ("a.png", _png(), "image/png"))])
            assert r.status_code == 202
            claim = wait_processed(client, cid)
            line = claim["lines"][0]
            assert line["status"] == "error"
            assert "provider down" in line["error"]
            assert claim["total_inr"] == 0

    def test_arbitrary_upload_with_live_provider(self, fake_client) -> None:
        client, _ = fake_client([extraction_payload(total_amount=600.0, attendees_count=2)])
        with client:
            cid = client.post("/api/claims").json()["id"]
            client.post(
                f"/api/claims/{cid}/documents", files=[("files", ("a.png", _png("gray"), "image/png"))]
            )
            claim = wait_processed(client, cid)
            assert claim["status"] == "ready_to_submit"
            assert Path(claim["documents"][0]["stored_path"]).exists()

    def test_compile_policy_endpoint(self, fake_client) -> None:
        client, _ = fake_client([_draft()])
        with client:
            r = client.post("/api/admin/policies", json={"name": "Acme v2", "text": POLICY_TEXT})
            assert r.status_code == 200
            body = r.json()
            assert (body["version"], body["active"], [x["id"] for x in body["rules"]]) == (
                2,
                True,
                ["MEAL_CAP"],
            )
            policies = client.get("/api/admin/policies").json()
            assert [(p["ruleset_versions"], p["active_ruleset_version"]) for p in policies] == [([1, 2], 2)]
            assert client.post("/api/admin/rulesets/1/activate").json()["active"] is True
            assert client.get("/api/admin/rulesets/2").json()["active"] is False
            assert client.get("/api/policies/active").json()["version"] == 1
            traces = client.get("/api/admin/traces").json()
            assert traces[0]["kind"] == "policy"
            assert traces[0]["title"] == "Policy compile"

    def test_compile_failure_is_422(self, fake_client) -> None:
        client, _ = fake_client([{"x": 1}] * 3)
        with client:
            assert client.post("/api/admin/policies", json={"name": "x", "text": "y"}).status_code == 422


class TestAdminAndPublic:
    def test_health_version_openapi(self, client: TestClient) -> None:
        h = client.get("/api/health").json()
        assert h["replay_mode"] is True
        assert h["provider"] == "replay"
        assert h["prompt_versions"] == {"extract_receipt": "v1", "compile_policy": "v1"}
        assert client.get("/api/version").json() == h
        assert "/api/claims/{claim_id}/answers" in client.get("/api/openapi.json").json()["paths"]

    def test_demo_gallery(self, client: TestClient) -> None:
        receipts = client.get("/api/demo/receipts").json()
        assert len(receipts) == 5
        dinner = next(r for r in receipts if r["name"] == DINNER)
        assert dinner["doc_type"] == "invoice"
        img = client.get(dinner["thumbnail_url"])
        assert img.status_code == 200
        assert img.headers["content-type"] == "image/png"

    def test_admin_views_after_a_claim(self, client: TestClient) -> None:
        claim = _dinner_claim(client)
        overview = client.get("/api/admin/metrics/overview").json()
        assert overview["kpis"]["claims_total"] == 1
        assert overview["violations_by_rule"][0]["rule_id"] == "MEALS_CAP_PER_PERSON"
        assert overview["kpis"]["p50_latency_ms"] > 0
        assert overview["assumptions"]["manual_employee_min"] > 0
        traces = client.get(f"/api/admin/traces?claim_id={claim['id']}").json()
        assert traces[0]["title"] == "Dinner · upload"
        assert traces[0]["cost_usd"] > 0
        detail = client.get(f"/api/admin/traces/{traces[0]['id']}").json()
        assert {s["name"] for s in detail["spans"]} >= {"ingest", "extract", "llm"}
        assert client.get("/api/admin/traces/nope").status_code == 404
        audit = client.get("/api/admin/audit").json()
        row = next(r for r in audit if r["rule_id"] == "MEALS_CAP_PER_PERSON")
        assert row["policy_quote"].startswith("Meals are reimbursed")
        assert row["source_snippet"]
        assert row["rule_title"] == "Meal limit per person"
        assert client.get("/api/admin/eval/runs").json() == []
        assert client.get("/api/admin/eval/runs/nope").status_code == 404

    def test_admin_token(self, client: TestClient, container: Container) -> None:
        container.settings.ADMIN_TOKEN = "s3cret"
        assert client.get("/api/admin/labels").status_code == 401
        assert client.get("/api/admin/labels", headers={"Authorization": "Bearer s3cret"}).status_code == 200
        assert client.get("/api/health").status_code == 200

    def test_finance_endpoints_and_decision(self, client: TestClient, container: Container) -> None:
        claim = _dinner_claim(client)
        client.post(
            f"/api/claims/{claim['id']}/lines/{claim['lines'][0]['id']}/actions",
            json={"action": "justify", "justification": "ok"},
        )
        ref = client.post(f"/api/claims/{claim['id']}/submit").json()["finance_reference"]
        assert client.get(f"/api/finance/submissions/{ref}").json()["status"] == "submitted"
        container.orchestrator.clock = lambda: NOW + dt.timedelta(minutes=5)
        decided = client.get(f"/api/claims/{claim['id']}").json()
        assert decided["status"] in ("approved", "rejected")
        payload = client.get(f"/api/finance/submissions/{ref}").json()["payload"]
        direct = client.post("/api/finance/submissions", json={**payload, "claim_id": "other"})
        assert direct.status_code == 201
        assert direct.json()["reference"].startswith("FIN-")


class TestSse:
    async def test_stream_frames_and_cleanup(self) -> None:
        broker = Broker()
        calls = {"n": 0}

        async def disconnected() -> bool:
            calls["n"] += 1
            return calls["n"] > 2

        gen = broker.stream(
            "c1", disconnected, first=("claim_update", {"claim": {"id": "c1"}}), keepalive_s=0.01
        )
        assert await anext(gen) == format_sse("claim_update", {"claim": {"id": "c1"}})
        broker.publish("c1", "stage", {"stage": "extract"})
        assert await anext(gen) == 'event: stage\ndata: {"stage": "extract"}\n\n'
        assert await anext(gen) == ": keepalive\n\n"
        with pytest.raises(StopAsyncIteration):
            await anext(gen)
        assert broker._subs == {}
        broker.publish("c1", "stage", {})  # no subscribers: no error

    async def test_pipeline_event_order(self, container: Container) -> None:
        orch = container.orchestrator
        claim = orch.create_claim("demo-user", "SSE")
        frames: list[str] = []
        done = asyncio.Event()

        async def disconnected() -> bool:
            return done.is_set()

        async def consume() -> None:
            async for frame in container.broker.stream(claim.id, disconnected, keepalive_s=0.05):
                frames.append(frame.split("\n", 1)[0])
                if frame.startswith("event: done"):
                    done.set()

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0)
        demo = container.settings.demo_dir / f"{DINNER}.png"
        from app.pipeline.orchestrator import Upload

        await orch.add_documents(claim.id, [Upload(demo.name, demo.read_bytes())])
        await asyncio.wait_for(done.wait(), 10)
        await asyncio.wait_for(consumer, 1)
        events = [f.removeprefix("event: ") for f in frames]
        stages = [e for e in events if e == "stage"]
        assert len(stages) == 6  # ingest, extract, validate, dedupe, rules, done
        assert events[0] == "stage"
        assert events[-5:] == ["line_update", "claim_update", "stage", "question", "done"]

    async def test_events_route_404(self, client: TestClient) -> None:
        assert client.get("/api/claims/nope/events").status_code == 404


class TestSeedAndSpa:
    def test_seed_rejects_mismatched_policy(self, settings: Settings, tmp_path: Path) -> None:
        policies = tmp_path / "pol"
        policies.mkdir()
        (policies / "acme_india_travel_policy.md").write_text("edited")
        data = settings.DATA_DIR
        (data / "policies").unlink()
        (data / "policies").symlink_to(policies)
        with pytest.raises(RuntimeError, match="rebuild"):
            build_container(settings)

    def test_spa_fallback(self, container: Container, tmp_path: Path) -> None:
        dist = tmp_path / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<html>app</html>")
        (dist / "assets" / "app.js").write_text("console.log(1)")
        with TestClient(create_app(container, dist=dist)) as client:
            assert client.get("/").text == "<html>app</html>"
            assert client.get("/admin/overview").text == "<html>app</html>"
            assert client.get("/assets/app.js").text == "console.log(1)"
            assert client.get("/api/unknown").status_code == 404
            assert client.get("/api/health").json()["status"] == "ok"

    def test_default_app_builds_from_settings(self, settings: Settings, monkeypatch) -> None:
        import app.main as main

        monkeypatch.setattr(main, "get_settings", lambda: settings.model_copy(update={"SEED_DEMO": True}))
        with TestClient(main.create_app(dist=REPO_ROOT / "nonexistent")) as client:
            assert client.get("/api/health").status_code == 200


class TestDemoToday:
    def test_replay_pins_the_calendar_and_keeps_time_running(self, settings: Settings) -> None:
        pinned = dt.date(2026, 10, 10)
        c = build_container(settings.model_copy(update={"DEMO_TODAY": pinned}))
        first = c.orchestrator.clock()
        assert first.date() == pinned
        assert c.tracer.clock is c.orchestrator.clock  # spans and claims share one calendar
        assert c.orchestrator.clock() >= first

    def test_unset_demo_today_uses_the_real_date(self, settings: Settings) -> None:
        c = build_container(settings.model_copy(update={"DEMO_TODAY": None}))
        assert c.orchestrator.clock().date() == dt.datetime.now(dt.UTC).date()
