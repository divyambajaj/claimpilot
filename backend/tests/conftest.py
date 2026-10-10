import asyncio
from pathlib import Path

import pytest

from app.db import Database
from app.domain.repo import Repo
from app.llm.client import LLMClient
from app.llm.prompts.registry import PromptRegistry
from app.llm.recorder import Recorder
from app.observability.tracing import Tracer
from tests.factories import FakeProvider


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_all()
    return database


@pytest.fixture
def repo(db: Database) -> Repo:
    return Repo(db)


@pytest.fixture
def tracer(db: Database) -> Tracer:
    return Tracer(db)


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
def make_client(tracer: Tracer):
    def build(provider: FakeProvider, recorder: Recorder | None = None) -> LLMClient:
        return LLMClient(provider, recorder, asyncio.Semaphore(3), tracer, PromptRegistry(), sleep=_no_sleep)

    return build
