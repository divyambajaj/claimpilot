"""Repository: ORM rows <-> Pydantic domain models. All persistence goes through here."""

import datetime as dt
from collections import defaultdict

from sqlalchemy import delete, select

from app.db import (
    ClaimRow,
    CorrectionLabelRow,
    Database,
    DocumentRow,
    EvalRunRow,
    LineItemRow,
    PolicyRow,
    RuleSetRow,
    SubmissionRow,
)
from app.domain.enums import Category, ClaimStatus, LineStatus
from app.domain.models import (
    Claim,
    CorrectionLabel,
    Document,
    EvalRun,
    FinanceSubmission,
    LineItem,
    PolicyDoc,
)
from app.rules.dsl import RuleSet

SETTLED_CLAIM_STATES = (ClaimStatus.SUBMITTED.value, ClaimStatus.APPROVED.value)


class NotFoundError(Exception):
    """Requested entity does not exist (mapped to HTTP 404)."""


class Repo:
    def __init__(self, db: Database) -> None:
        self.db = db

    # --- claims -----------------------------------------------------------------------------------
    def save_claim(self, claim: Claim) -> None:
        payload = claim.model_dump(mode="json", exclude={"lines", "documents"})
        with self.db.session() as s:
            row = s.get(ClaimRow, claim.id)
            if row is None:
                row = ClaimRow(id=claim.id, user_id=claim.user_id, created_at=claim.created_at)
                s.add(row)
            row.status = claim.status.value
            row.updated_at = claim.updated_at
            row.payload = payload
            keep = [line.id for line in claim.lines]
            s.execute(
                delete(LineItemRow).where(LineItemRow.claim_id == claim.id, LineItemRow.id.not_in(keep))
            )
            for pos, line in enumerate(claim.lines):
                lrow = s.get(LineItemRow, line.id) or LineItemRow(id=line.id, claim_id=claim.id)
                lrow.user_id = claim.user_id
                lrow.date = line.extracted.date.value
                lrow.status = line.status.value
                lrow.amount_inr = line.amount_inr
                lrow.position = pos
                lrow.payload = line.model_dump(mode="json")
                s.add(lrow)

    def get_claim(self, claim_id: str) -> Claim:
        with self.db.session() as s:
            row = s.get(ClaimRow, claim_id)
            if row is None:
                raise NotFoundError(f"claim {claim_id} not found")
            lines = s.scalars(
                select(LineItemRow).where(LineItemRow.claim_id == claim_id).order_by(LineItemRow.position)
            ).all()
            docs = s.scalars(select(DocumentRow).where(DocumentRow.claim_id == claim_id)).all()
            return Claim.model_validate(
                {**row.payload, "lines": [lr.payload for lr in lines], "documents": [d.payload for d in docs]}
            )

    def list_claims(self, user_id: str | None = None) -> list[Claim]:
        with self.db.session() as s:
            q = select(ClaimRow.id).order_by(ClaimRow.created_at.desc())
            if user_id is not None:
                q = q.where(ClaimRow.user_id == user_id)
            ids = list(s.scalars(q).all())
        return [self.get_claim(i) for i in ids]

    def user_lines_near(
        self, user_id: str, center: dt.date | None, days: int, exclude_claim_id: str
    ) -> list[LineItem]:
        """Prior lines of the user (other claims) within +/- `days` of `center`, excluding EXCLUDED lines."""
        with self.db.session() as s:
            q = select(LineItemRow).where(
                LineItemRow.user_id == user_id,
                LineItemRow.claim_id != exclude_claim_id,
                LineItemRow.status != LineStatus.EXCLUDED.value,
            )
            if center is not None:
                q = q.where(
                    LineItemRow.date.between(
                        center - dt.timedelta(days=days), center + dt.timedelta(days=days)
                    )
                )
            rows = s.scalars(q).all()
            return [LineItem.model_validate(r.payload) for r in rows]

    def prior_day_category_totals(
        self, user_id: str, exclude_claim_id: str
    ) -> dict[tuple[dt.date, Category], float]:
        """Reimbursable totals per (date, category) from the user's already-submitted claims."""
        totals: dict[tuple[dt.date, Category], float] = defaultdict(float)
        with self.db.session() as s:
            claim_ids = s.scalars(
                select(ClaimRow.id).where(
                    ClaimRow.user_id == user_id,
                    ClaimRow.id != exclude_claim_id,
                    ClaimRow.status.in_(SETTLED_CLAIM_STATES),
                )
            ).all()
            if not claim_ids:
                return {}
            rows = s.scalars(
                select(LineItemRow).where(
                    LineItemRow.claim_id.in_(claim_ids), LineItemRow.status == LineStatus.COMPLETE.value
                )
            ).all()
            for r in rows:
                line = LineItem.model_validate(r.payload)
                if r.date is not None:
                    totals[(r.date, line.category)] += line.reimbursable_inr
        return dict(totals)

    # --- documents --------------------------------------------------------------------------------
    def save_document(self, doc: Document) -> None:
        with self.db.session() as s:
            s.merge(
                DocumentRow(
                    id=doc.id,
                    claim_id=doc.claim_id,
                    sha256=doc.sha256,
                    dhash=doc.dhash,
                    payload=doc.model_dump(mode="json"),
                )
            )

    def get_document(self, doc_id: str) -> Document:
        with self.db.session() as s:
            row = s.get(DocumentRow, doc_id)
            if row is None:
                raise NotFoundError(f"document {doc_id} not found")
            return Document.model_validate(row.payload)

    def get_documents(self, doc_ids: list[str]) -> dict[str, Document]:
        with self.db.session() as s:
            rows = s.scalars(select(DocumentRow).where(DocumentRow.id.in_(doc_ids))).all()
            return {r.id: Document.model_validate(r.payload) for r in rows}

    # --- policies & rulesets ----------------------------------------------------------------------
    def save_policy(self, policy: PolicyDoc) -> None:
        with self.db.session() as s:
            s.merge(
                PolicyRow(
                    id=policy.id,
                    name=policy.name,
                    sha256=policy.sha256,
                    text=policy.text,
                    created_at=policy.created_at,
                )
            )

    def get_policy(self, policy_id: str) -> PolicyDoc:
        with self.db.session() as s:
            row = s.get(PolicyRow, policy_id)
            if row is None:
                raise NotFoundError(f"policy {policy_id} not found")
            return PolicyDoc(
                id=row.id, name=row.name, text=row.text, sha256=row.sha256, created_at=row.created_at
            )

    def list_policies(self) -> list[PolicyDoc]:
        with self.db.session() as s:
            ids = s.scalars(select(PolicyRow.id).order_by(PolicyRow.created_at)).all()
        return [self.get_policy(i) for i in ids]

    def next_ruleset_version(self) -> int:
        with self.db.session() as s:
            versions = s.scalars(select(RuleSetRow.version)).all()
            return max(versions, default=0) + 1

    def save_ruleset(self, ruleset: RuleSet, *, active: bool = False) -> None:
        with self.db.session() as s:
            if active:
                for row in s.scalars(select(RuleSetRow).where(RuleSetRow.active.is_(True))):
                    row.active = False
            s.merge(
                RuleSetRow(
                    version=ruleset.version,
                    policy_id=ruleset.policy_id,
                    active=active,
                    compiled_at=ruleset.compiled_at,
                    payload=ruleset.model_dump(mode="json", by_alias=True),
                )
            )

    def get_ruleset(self, version: int) -> RuleSet:
        with self.db.session() as s:
            row = s.get(RuleSetRow, version)
            if row is None:
                raise NotFoundError(f"ruleset v{version} not found")
            return RuleSet.model_validate(row.payload)

    def active_ruleset(self) -> RuleSet | None:
        with self.db.session() as s:
            row = s.scalars(select(RuleSetRow).where(RuleSetRow.active.is_(True))).first()
            return RuleSet.model_validate(row.payload) if row else None

    def list_rulesets(self) -> list[tuple[RuleSet, bool]]:
        with self.db.session() as s:
            rows = s.scalars(select(RuleSetRow).order_by(RuleSetRow.version)).all()
            return [(RuleSet.model_validate(r.payload), r.active) for r in rows]

    def activate_ruleset(self, version: int) -> RuleSet:
        ruleset = self.get_ruleset(version)
        self.save_ruleset(ruleset, active=True)
        return ruleset

    # --- labels, eval runs, submissions -----------------------------------------------------------
    def add_label(self, label: CorrectionLabel) -> None:
        with self.db.session() as s:
            s.add(
                CorrectionLabelRow(
                    id=label.id,
                    line_id=label.line_id,
                    field=label.field,
                    created_at=label.created_at,
                    payload=label.model_dump(mode="json"),
                )
            )

    def list_labels(self) -> list[CorrectionLabel]:
        with self.db.session() as s:
            rows = s.scalars(select(CorrectionLabelRow).order_by(CorrectionLabelRow.created_at.desc())).all()
            return [CorrectionLabel.model_validate(r.payload) for r in rows]

    def save_eval_run(self, run: EvalRun) -> None:
        with self.db.session() as s:
            s.merge(EvalRunRow(id=run.id, created_at=run.created_at, payload=run.model_dump(mode="json")))

    def list_eval_runs(self) -> list[EvalRun]:
        with self.db.session() as s:
            rows = s.scalars(select(EvalRunRow).order_by(EvalRunRow.created_at.desc())).all()
            return [EvalRun.model_validate(r.payload) for r in rows]

    def get_eval_run(self, run_id: str) -> EvalRun:
        with self.db.session() as s:
            row = s.get(EvalRunRow, run_id)
            if row is None:
                raise NotFoundError(f"eval run {run_id} not found")
            return EvalRun.model_validate(row.payload)

    def save_submission(self, sub: FinanceSubmission) -> None:
        with self.db.session() as s:
            s.merge(
                SubmissionRow(
                    reference=sub.reference,
                    claim_id=sub.claim_id,
                    status=sub.status,
                    created_at=sub.submitted_at,
                    payload=sub.model_dump(mode="json"),
                )
            )

    def get_submission(self, reference: str) -> FinanceSubmission:
        with self.db.session() as s:
            row = s.get(SubmissionRow, reference)
            if row is None:
                raise NotFoundError(f"submission {reference} not found")
            return FinanceSubmission.model_validate(row.payload)

    def list_submissions(self) -> list[FinanceSubmission]:
        with self.db.session() as s:
            rows = s.scalars(select(SubmissionRow).order_by(SubmissionRow.created_at)).all()
            return [FinanceSubmission.model_validate(r.payload) for r in rows]
