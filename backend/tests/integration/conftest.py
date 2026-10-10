import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import Container
from app.config import REPO_ROOT, Settings
from app.main import build_container, create_app
from tests.factories import NOW

SHARED = ("replay", "rulesets", "policies")
# The API tests pin the original five-receipt gallery; the shipped gallery (data/demo_receipts) can evolve.
LEGACY_GALLERY = REPO_ROOT / "backend" / "tests" / "fixtures" / "demo_v1"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    data.mkdir()
    for name in SHARED:
        (data / name).symlink_to(REPO_ROOT / "data" / name)
    (data / "demo_receipts").symlink_to(LEGACY_GALLERY)
    return Settings(
        _env_file=None,
        LLM_PROVIDER="replay",
        DATA_DIR=data,
        DATABASE_URL=f"sqlite:///{tmp_path / 'app.db'}",
        FINANCE_DECISION_DELAY_S=60,
        PROMPT_VERSION_EXTRACT="v1",  # the pinned API tests assert v1's recorded readings
    )


@pytest.fixture
def container(settings: Settings) -> Container:
    return build_container(settings, clock=lambda: NOW)


@pytest.fixture
def client(container: Container) -> Iterator[TestClient]:
    with TestClient(create_app(container, dist=Path("/nonexistent"))) as c:
        yield c


def wait_processed(client: TestClient, claim_id: str, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        claim = client.get(f"/api/claims/{claim_id}").json()
        if claim["processing"] == 0:
            return claim
        time.sleep(0.05)
    raise AssertionError("claim did not finish processing")
