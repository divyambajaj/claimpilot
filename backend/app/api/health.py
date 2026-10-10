"""Liveness and build info: provider, model, prompt versions, git sha, replay flag."""

from fastapi import APIRouter, Depends

from app.api.deps import Container, container
from app.api.schemas import Health

router = APIRouter(tags=["health"])


def _health(c: Container) -> Health:
    provider = c.llm.provider
    return Health(
        status="ok",
        provider=provider.name,
        model=provider.model,
        prompt_versions={n: c.llm.prompts.get(n).version for n in ("extract_receipt", "compile_policy")},
        git_sha=c.settings.GIT_SHA,
        replay_mode=provider.name == "replay",
    )


@router.get("/health", response_model=Health)
def health(c: Container = Depends(container)):
    return _health(c)


@router.get("/version", response_model=Health)
def version(c: Container = Depends(container)):
    return _health(c)
