"""FastAPI app: routers under /api, error mapping, lifespan wiring, and the built SPA (if present)."""

import asyncio
import datetime as dt
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from app.api import admin, claims, demo, documents, events, finance, health, policies
from app.api.deps import Container
from app.api.sse import Broker
from app.config import REPO_ROOT, Settings, get_settings
from app.db import Database
from app.domain.repo import NotFoundError, Repo
from app.domain.state import IllegalTransitionError
from app.finance_mock import MockFinance
from app.llm.base import LLMProvider, ReplayMissError
from app.llm.registry import build_client
from app.observability.tracing import Tracer, utcnow
from app.pipeline.ingest import IngestError, warm_ingest
from app.pipeline.orchestrator import AnswerError, Orchestrator
from app.rules.compiler import CompileError
from app.seed import ensure_ruleset, seed_demo

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
ERROR_STATUS: dict[type[Exception], int] = {
    NotFoundError: 404,
    IllegalTransitionError: 409,
    ReplayMissError: 409,
    IngestError: 400,
    AnswerError: 422,
    CompileError: 422,
}
REPLAY_MISS_DETAIL = "This file is not in the recorded demo set. Use the sample receipts gallery instead."


def build_container(
    settings: Settings, provider: LLMProvider | None = None, clock: Callable[[], dt.datetime] = utcnow
) -> Container:
    db = Database(settings.DATABASE_URL)
    db.create_all()
    if clock is utcnow and settings.LLM_PROVIDER == "replay" and settings.DEMO_TODAY:
        clock = demo_clock(settings.DEMO_TODAY)
    repo, tracer, broker = Repo(db), Tracer(db, clock), Broker()
    llm = build_client(settings, tracer, provider)
    finance = MockFinance(repo, settings.FINANCE_DECISION_DELAY_S, settings.FINANCE_SEED)
    orch = Orchestrator(settings, repo, llm, tracer, broker, finance, clock)
    ensure_ruleset(repo, settings)
    return Container(settings, db, repo, tracer, broker, llm, finance, orch)


def demo_clock(today: dt.date) -> Callable[[], dt.datetime]:
    """Real time of day on a pinned calendar day: durations and the finance delay stay real."""
    shift = dt.datetime.combine(today, dt.time()) - dt.datetime.combine(utcnow().date(), dt.time())
    return lambda: utcnow() + shift


def create_app(container: Container | None = None, dist: Path = FRONTEND_DIST) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if getattr(app.state, "container", None) is None:
            app.state.container = build_container(get_settings())
        c: Container = app.state.container
        if c.settings.SEED_DEMO:
            asyncio.create_task(seed_demo(c.orchestrator))  # noqa: RUF006 - fire and forget at boot
            # decode the sample receipts once at boot so "Add to claim" in the gallery answers instantly
            asyncio.create_task(asyncio.to_thread(warm_ingest, c.settings.demo_dir))  # noqa: RUF006
        yield
        await c.orchestrator.wait_idle()

    app = FastAPI(
        title="ClaimPilot",
        version="0.1.0",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        lifespan=lifespan,
    )
    app.state.container = container
    for module in (health, claims, documents, events, demo, policies, finance, admin):
        app.include_router(module.router, prefix="/api")

    for exc_type, status in ERROR_STATUS.items():
        app.add_exception_handler(exc_type, _handler(status))

    if dist.is_dir():
        _mount_spa(app, dist)
    return app


def _handler(status: int):
    async def handle(_: Request, exc: Exception) -> JSONResponse:
        detail = REPLAY_MISS_DETAIL if isinstance(exc, ReplayMissError) else str(exc)
        body = {"detail": detail, "code": type(exc).__name__}
        if getattr(exc, "errors", None):  # per-question messages for an invalid answer
            body["errors"] = exc.errors  # type: ignore[attr-defined]
        return JSONResponse(body, status_code=status)

    return handle


def _mount_spa(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
