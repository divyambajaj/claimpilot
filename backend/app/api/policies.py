"""Public policy endpoint: the active ruleset (chat "Why?" drawer and policy page)."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import Container, container
from app.api.schemas import RuleSetOut

router = APIRouter(tags=["policies"])


@router.get("/policies/active", response_model=RuleSetOut)
def active_ruleset(c: Container = Depends(container)):
    ruleset = c.repo.active_ruleset()
    if ruleset is None:
        raise HTTPException(404, "no active ruleset")
    return RuleSetOut(**ruleset.model_dump(by_alias=True), active=True)
