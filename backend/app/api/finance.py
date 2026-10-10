"""Mock finance/ERP adapter endpoints (same interface a real connector would implement)."""

from fastapi import APIRouter, Depends

from app.api.deps import Container, container
from app.domain.models import FinanceSubmission, SubmissionPayload

router = APIRouter(prefix="/finance", tags=["finance"])


@router.post("/submissions", response_model=FinanceSubmission, status_code=201)
def create_submission(payload: SubmissionPayload, c: Container = Depends(container)):
    return c.finance.submit(payload, c.orchestrator.clock())


@router.get("/submissions/{reference}", response_model=FinanceSubmission)
def get_submission(reference: str, c: Container = Depends(container)):
    return c.finance.poll(reference, c.orchestrator.clock())
