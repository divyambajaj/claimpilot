"""Claims: create/list/read, answers, line actions and edits, submit, per-claim audit trail."""

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import Container, container, user_id
from app.api.schemas import AnswerIn, AuditRow, ClaimAudit, ClaimCreate, FinanceReference, LineActionIn
from app.domain.models import Claim
from app.domain.repo import NotFoundError
from app.rules.dsl import RuleSet

router = APIRouter(tags=["claims"])

_SNIPPET_FIELD = {"vendor_gstin": "vendor_gstin", "attendees_count": "attendees_count", "city": "city"}


def audit_rows(claim: Claim, ruleset: RuleSet | None) -> list[AuditRow]:
    rows = []
    for line in claim.lines:
        for f in line.findings:
            rule = ruleset.rule(f.rule_id) if (ruleset and f.rule_id) else None
            field = (rule.action.field if rule and rule.action.field else None) or "total_amount"
            snippet = line.extracted.field(_SNIPPET_FIELD.get(field, "total_amount")).source_snippet
            rows.append(
                AuditRow(
                    finding_id=f.id,
                    claim_id=claim.id,
                    claim_title=claim.title,
                    line_id=line.id,
                    vendor=line.extracted.vendor_name.value,
                    amount_inr=line.amount_inr,
                    kind=f.kind,
                    rule_id=f.rule_id,
                    rule_title=rule.title if rule else None,
                    severity=f.severity,
                    message=f.message,
                    policy_quote=f.citation.quote if f.citation else None,
                    policy_section=f.citation.section if f.citation else None,
                    source_snippet=snippet,
                    resolution=f.resolution,
                    justification=f.justification,
                    created_at=line.created_at or claim.created_at,
                )
            )
    return rows


@router.post("/claims", response_model=Claim)
def create_claim(
    body: ClaimCreate | None = None, c: Container = Depends(container), user: str = Depends(user_id)
):
    return c.orchestrator.create_claim(user, body.title if body else None)


@router.get("/claims", response_model=list[Claim])
def list_claims(c: Container = Depends(container), user: str = Depends(user_id)):
    return c.repo.list_claims(user)


@router.get("/claims/{claim_id}", response_model=Claim)
def get_claim(claim_id: str, c: Container = Depends(container)):
    return c.orchestrator.get_claim(claim_id)


@router.post("/claims/{claim_id}/answers", response_model=Claim)
async def answer(claim_id: str, answers: list[AnswerIn], c: Container = Depends(container)):
    return await c.orchestrator.answer(claim_id, [a.model_dump() for a in answers])


@router.post("/claims/{claim_id}/lines/{line_id}/actions", response_model=Claim)
async def line_action(claim_id: str, line_id: str, body: LineActionIn, c: Container = Depends(container)):
    return await c.orchestrator.line_action(claim_id, line_id, body.action, body.justification)


@router.patch("/claims/{claim_id}/lines/{line_id}", response_model=Claim)
async def edit_line(claim_id: str, line_id: str, patch: dict[str, Any], c: Container = Depends(container)):
    return await c.orchestrator.edit_line(claim_id, line_id, patch)


@router.post("/claims/{claim_id}/submit", response_model=FinanceReference)
async def submit(claim_id: str, c: Container = Depends(container)):
    claim = await c.orchestrator.submit(claim_id)
    return FinanceReference(finance_reference=claim.finance_reference or "")


@router.get("/claims/{claim_id}/audit", response_model=ClaimAudit)
def claim_audit(claim_id: str, c: Container = Depends(container)):
    claim = c.repo.get_claim(claim_id)
    ruleset = _ruleset_for(c, claim)
    spans = [s for t in c.tracer.list_traces(claim_id) for s in t.spans]
    return ClaimAudit(
        claim_id=claim_id, findings=audit_rows(claim, ruleset), spans=sorted(spans, key=lambda s: s.start)
    )


def _ruleset_for(c: Container, claim: Claim) -> RuleSet | None:
    try:
        return c.repo.get_ruleset(claim.ruleset_version)
    except NotFoundError:
        return c.repo.active_ruleset()
