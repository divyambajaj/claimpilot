"""Shared dependencies: the per-app service container, user identity and the admin guard."""

from dataclasses import dataclass

from fastapi import Header, HTTPException, Request

from app.api.sse import Broker
from app.config import Settings
from app.db import Database
from app.domain.repo import Repo
from app.finance_mock import MockFinance
from app.llm.client import LLMClient
from app.observability.tracing import Tracer
from app.pipeline.orchestrator import Orchestrator

DEFAULT_USER = "demo-user"


@dataclass
class Container:
    settings: Settings
    db: Database
    repo: Repo
    tracer: Tracer
    broker: Broker
    llm: LLMClient
    finance: MockFinance
    orchestrator: Orchestrator


def container(request: Request) -> Container:
    return request.app.state.container


def user_id(x_user_id: str | None = Header(default=None)) -> str:
    return x_user_id or DEFAULT_USER


def require_admin(request: Request, authorization: str | None = Header(default=None)) -> None:
    token = request.app.state.container.settings.ADMIN_TOKEN
    if token and authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="admin token required")
