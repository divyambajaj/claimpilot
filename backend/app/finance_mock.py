"""In-process stand-in for a finance/ERP system: accepts a submission, decides after a delay."""

import datetime as dt
import random

from app.domain.models import FinanceSubmission, SubmissionPayload, Ticket
from app.domain.repo import Repo

APPROVAL_RATE = 0.9


class MockFinance:
    def __init__(self, repo: Repo, delay_s: float, seed: int) -> None:
        self.repo = repo
        self.delay = dt.timedelta(seconds=delay_s)
        self.seed = seed

    def submit(self, payload: SubmissionPayload, now: dt.datetime) -> FinanceSubmission:
        reference = f"FIN-{random.Random(f'{self.seed}:{payload.claim_id}').randint(1000, 9999)}"
        sub = FinanceSubmission(
            reference=reference,
            claim_id=payload.claim_id,
            status="submitted",
            submitted_at=now,
            decide_at=now + self.delay,
            payload=payload,
        )
        self.repo.save_submission(sub)
        return sub

    def poll(self, reference: str, now: dt.datetime) -> FinanceSubmission:
        """Seeded decision once the review delay has passed (stands in for an ERP callback)."""
        sub = self.repo.get_submission(reference)
        if sub.status != "submitted" or now < sub.decide_at:
            return sub
        approved = random.Random(f"{self.seed}:{reference}").random() < APPROVAL_RATE
        sub = sub.model_copy(
            update={
                "status": "approved" if approved else "rejected",
                "decided_at": now,
                "note": "Approved for payment in the next run."
                if approved
                else "Returned: attach the original bills.",
            }
        )
        self.repo.save_submission(sub)
        return sub

    def raise_ticket(
        self, claim_id: str, line_ids: list[str], reason: str, now: dt.datetime, n: int
    ) -> Ticket:
        """`n` = tickets the claim already has, so each ticket of a claim gets its own seeded id."""
        number = random.Random(f"{self.seed}:{claim_id}:ticket:{n}").randint(1000, 9999)
        return Ticket(id=f"TKT-{number}", claim_id=claim_id, line_ids=line_ids, reason=reason, created_at=now)

    def poll_ticket(self, ticket: Ticket, now: dt.datetime) -> Ticket:
        """A reviewer picks the ticket up once the review delay has passed."""
        if ticket.status != "open" or now < ticket.created_at + self.delay:
            return ticket
        return ticket.model_copy(update={"status": "in_review"})
