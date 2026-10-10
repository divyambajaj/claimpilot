"""Pure status derivation for lines and claims (section 5). Recomputed after every change."""

from collections.abc import Sequence

from app.domain.enums import ClaimStatus, FindingKind, LineStatus, Severity
from app.domain.models import Claim, LineItem, Question

TERMINAL_CLAIM_STATES = frozenset({ClaimStatus.SUBMITTED, ClaimStatus.APPROVED, ClaimStatus.REJECTED})
VALUE_QUESTION_KINDS = frozenset({"value", "choice"})


class IllegalTransitionError(Exception):
    """Raised for API actions that the current status does not allow (mapped to HTTP 409)."""


def derive_line_status(line: LineItem, questions: Sequence[Question] = ()) -> LineStatus:
    if line.error:
        return LineStatus.ERROR
    if line.user_excluded or line.linked_to_line_id:
        return LineStatus.EXCLUDED
    open_findings = [f for f in line.findings if f.resolution == "open"]
    if any(f.severity == Severity.BLOCK for f in open_findings):
        return LineStatus.EXCLUDED
    if any(f.kind == FindingKind.DUPLICATE and f.resolution == "confirmed" for f in line.findings):
        return LineStatus.EXCLUDED
    if any(q.line_id == line.id and q.kind in VALUE_QUESTION_KINDS for q in questions):
        return LineStatus.MISSING_INFO
    if any(f.severity == Severity.WARN or f.kind == FindingKind.DUPLICATE for f in open_findings):
        return LineStatus.FLAGGED
    return LineStatus.COMPLETE


def derive_claim_status(claim: Claim) -> ClaimStatus:
    if claim.status in TERMINAL_CLAIM_STATES:
        return claim.status
    if claim.processing > 0 or not claim.lines:
        return ClaimStatus.DRAFT
    statuses = [line.status for line in claim.lines]
    all_settled = all(s in (LineStatus.COMPLETE, LineStatus.EXCLUDED) for s in statuses)
    claim_block = any(f.severity == Severity.BLOCK and f.resolution == "open" for f in claim.findings)
    if all_settled and LineStatus.COMPLETE in statuses and not claim_block and not claim.open_questions:
        return ClaimStatus.READY_TO_SUBMIT
    return ClaimStatus.DRAFT


def ensure_submittable(claim: Claim) -> None:
    if claim.status != ClaimStatus.READY_TO_SUBMIT:
        raise IllegalTransitionError(
            f"claim is {claim.status.value}; only ready_to_submit claims can be submitted"
        )


def ensure_editable(claim: Claim) -> None:
    if claim.status in TERMINAL_CLAIM_STATES:
        raise IllegalTransitionError(f"claim is {claim.status.value} and can no longer be changed")
