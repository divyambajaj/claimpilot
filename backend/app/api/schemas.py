"""Request/response shapes that are not domain models (mirrored in frontend/src/types.ts)."""

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel

from app.domain.enums import DocType, FindingKind, Severity
from app.domain.models import Resolution, Span
from app.rules.dsl import RuleSet


class ClaimCreate(BaseModel):
    title: str | None = None


class AnswerIn(BaseModel):
    question_id: str | None = None
    line_id: str | None = None
    field: str | None = None
    value: Any = None


class LineActionIn(BaseModel):
    action: Literal["exclude", "restore", "override_duplicate", "confirm_duplicate", "justify"]
    justification: str | None = None


class DocumentIds(BaseModel):
    document_ids: list[str]


class DemoSelection(BaseModel):
    names: list[str]


class FinanceReference(BaseModel):
    finance_reference: str


class AuditRow(BaseModel):
    finding_id: str
    claim_id: str
    claim_title: str
    line_id: str
    vendor: str | None
    amount_inr: float
    kind: FindingKind
    rule_id: str | None
    rule_title: str | None
    severity: Severity
    message: str
    policy_quote: str | None
    policy_section: str | None
    source_snippet: str | None
    resolution: Resolution
    justification: str | None
    created_at: dt.datetime


class ClaimAudit(BaseModel):
    claim_id: str
    findings: list[AuditRow]
    spans: list[Span]


class DemoReceipt(BaseModel):
    name: str
    title: str
    doc_type: DocType
    description: str
    thumbnail_url: str | None = None
    amount_inr: float | None = None


class Health(BaseModel):
    status: str
    provider: str
    model: str
    prompt_versions: dict[str, str]
    git_sha: str | None
    replay_mode: bool


class RuleSetOut(RuleSet):
    active: bool = False


class PolicyOut(BaseModel):
    id: str
    name: str
    text: str
    sha256: str
    created_at: dt.datetime
    ruleset_versions: list[int]
    active_ruleset_version: int | None


class PolicyIn(BaseModel):
    name: str
    text: str


class TraceSummary(BaseModel):
    id: str
    claim_id: str | None
    kind: str
    title: str
    started_at: dt.datetime
    duration_ms: int
    span_count: int
    status: Literal["ok", "error", "retry"]
    cost_usd: float


class EvalRunIn(BaseModel):
    subset: Literal["smoke", "full"] = "smoke"
