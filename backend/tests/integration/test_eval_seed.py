"""Eval endpoints (smoke subset in replay) and the SEED_DEMO startup history, all offline."""

import asyncio
import datetime as dt
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import admin
from app.api.deps import Container
from app.config import REPO_ROOT, Settings
from app.evaluation.runner import run_eval
from app.main import build_container
from app.seed import HISTORY_USER, seed_demo
from tests.factories import NOW


def _wait_runs(client: TestClient, n: int, timeout: float = 60.0) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runs = client.get("/api/admin/eval/runs").json()
        if len(runs) >= n:
            return runs
        time.sleep(0.1)
    raise AssertionError("eval run did not finish")


class TestEvalApi:
    def test_smoke_run_over_http(self, client: TestClient) -> None:
        r = client.post("/api/admin/eval/run", json={"subset": "smoke"})
        assert r.status_code == 202 and r.json() == {"subset": "smoke", "status": "started"}
        run = _wait_runs(client, 1)[0]
        assert run["subset"] == "smoke" and run["provider"] == "replay" and run["n_receipts"] == 9
        assert run["metrics"]["p50_latency_ms"] > 0 and run["metrics"]["cost_usd_per_receipt"] > 0
        assert client.get(f"/api/admin/eval/runs/{run['id']}").json()["id"] == run["id"]

    async def test_progress_and_done_events(self, container: Container) -> None:
        frames: list[str] = []
        stop = asyncio.Event()

        async def listen() -> None:
            async for frame in container.broker.stream(admin.EVAL_TOPIC, _until(stop), keepalive_s=0.05):
                frames.append(frame)
                if frame.startswith("event: done"):
                    stop.set()

        listener = asyncio.create_task(listen())
        await asyncio.sleep(0)
        await admin._run_eval(container, "smoke")
        await asyncio.wait_for(listener, 30)
        frames = [f for f in frames if f.startswith("event:")]
        events = [f.split("\n")[0].removeprefix("event: ") for f in frames]
        assert events[0] == "progress" and events[-1] == "done" and events.count("progress") == 10
        assert '"done": 0, "total": 9}' in frames[0] and '"fixture_id": "fx_' in frames[1]
        assert len(container.repo.list_eval_runs()) == 1

    async def test_failure_is_an_error_event(self, container: Container, monkeypatch) -> None:
        async def boom(*_a, **_k):
            raise RuntimeError("no fixtures")

        monkeypatch.setattr(admin, "run_eval", boom)
        seen = []
        monkeypatch.setattr(
            container.broker, "publish", lambda topic, event, data: seen.append((event, data))
        )
        await admin._run_eval(container, "full")
        assert seen == [("error", {"message": "Evaluation failed: no fixtures"})]

    async def test_one_run_at_a_time_and_events_route(self, client: TestClient, container: Container) -> None:
        pending = asyncio.get_running_loop().create_future()
        admin._eval_tasks[id(container)] = pending  # type: ignore[assignment]
        try:
            assert client.post("/api/admin/eval/run", json={}).status_code == 409
        finally:
            pending.cancel()
            admin._eval_tasks.pop(id(container))

        class _Req:
            async def is_disconnected(self) -> bool:
                return True

        resp = await admin.eval_events(_Req(), container)  # type: ignore[arg-type]
        assert resp.media_type == "text/event-stream"


def _until(stop: asyncio.Event):
    async def disconnected() -> bool:
        return stop.is_set()

    return disconnected


@pytest.fixture
def gallery_settings(settings: Settings) -> Settings:
    demo = settings.DATA_DIR / "demo_receipts"
    demo.unlink()
    demo.symlink_to(REPO_ROOT / "data" / "demo_receipts")
    return settings


class TestSeed:
    async def test_seed_builds_history_gallery_and_eval_runs(self, gallery_settings: Settings) -> None:
        container = build_container(gallery_settings, clock=lambda: NOW)
        await seed_demo(container.orchestrator)
        claims = container.repo.list_claims()
        history = [c for c in claims if c.user_id == HISTORY_USER]
        sample = next(c for c in claims if c.user_id == "sample-team")
        assert len(history) == 12 and len({c.created_at.date() for c in history}) >= 8
        assert sum(c.status == "submitted" for c in history) >= 8
        assert sample.status == "submitted" and len(sample.lines) == 12
        runs = container.repo.list_eval_runs()
        assert runs and all(r.provider == "replay" and r.subset == "full" for r in runs)
        lines = [x for c in claims for x in c.lines]
        assert any(f.kind == "duplicate" for x in lines for f in x.findings)
        spans = container.tracer.spans_since(NOW - dt.timedelta(days=30))
        assert len({s.start.date() for s in spans}) >= 8  # spans are backdated with their claims
        await seed_demo(container.orchestrator)  # idempotent
        assert len(container.repo.list_claims()) == len(claims)


def test_replay_miss_names_the_fixture(settings: Settings, tmp_path: Path) -> None:
    empty = tmp_path / "replay"
    empty.mkdir()
    (settings.DATA_DIR / "replay").unlink()
    (settings.DATA_DIR / "replay").symlink_to(empty)
    with pytest.raises(Exception, match="no recorded response"):
        asyncio.run(run_eval(settings, "smoke"))
