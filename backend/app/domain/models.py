"""Pydantic v2 domain models: the source of truth for every object the API returns."""

import datetime as dt
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from app.domain.enums import (
    Category,
    ClaimStatus,
    DocType,
    FindingKind,
    LineStatus,
    PaymentMethod,
    Severity,
)

T = TypeVar("T")

FieldOrigin = Literal["llm", "validator", "user", "assumed"]
Resolution = Literal["open", "acknowledged", "justified", "overridden", "confirmed"]
Quality = Literal["good", "blurry", "partial", "rotated", "handwritten"]


class FieldEdit(BaseModel):
    at: dt.datetime
    old: Any = None
    new: Any = None
    by: Literal["user", "validator"] = "user"


class ExtractedField(BaseModel, Generic[T]):
    value: T | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    source_snippet: str | None = None
    origin: FieldOrigin = "llm"
    history: list[FieldEdit] = Field(default_factory=list)


class ReceiptItem(BaseModel):
    description: str
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None


class ExtractedReceipt(BaseModel):
    doc_type: ExtractedField[DocType]
    vendor_name: ExtractedField[str]
    vendor_gstin: ExtractedField[str]
    invoice_number: ExtractedField[str]
    date: ExtractedField[dt.date]
    currency: ExtractedField[str]
    subtotal: ExtractedField[float]
    tax_amount: ExtractedField[float]
    total_amount: ExtractedField[float]
    payment_method: ExtractedField[PaymentMethod]
    upi_txn_id: ExtractedField[str]
    payee_name: ExtractedField[str]
    city: ExtractedField[str]
    category: ExtractedField[Category]
    attendees_count: ExtractedField[int]
    items: list[ReceiptItem] = Field(default_factory=list)
    raw_text: str = ""
    quality: Quality = "good"

    def field(self, name: str) -> ExtractedField[Any]:
        return getattr(self, name)


EXTRACTED_FIELD_NAMES: tuple[str, ...] = tuple(
    name
    for name, info in ExtractedReceipt.model_fields.items()
    if name not in {"items", "raw_text", "quality"}
)


class Document(BaseModel):
    id: str
    claim_id: str
    filename: str
    mime: str
    sha256: str
    dhash: str
    dhash_rotations: list[str]
    width: int
    height: int
    page: int = 0
    stored_path: str


class Citation(BaseModel):
    section: str
    quote: str
    char_start: int
    char_end: int
    verified: bool = True


class Finding(BaseModel):
    id: str
    kind: FindingKind
    severity: Severity
    rule_id: str | None = None
    message: str
    citation: Citation | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    resolution: Resolution = "open"
    justification: str | None = None


class LineItem(BaseModel):
    id: str
    claim_id: str
    document_ids: list[str]
    extracted: ExtractedReceipt
    category: Category
    amount_inr: float
    reimbursable_inr: float
    status: LineStatus
    findings: list[Finding] = Field(default_factory=list)
    linked_proof_line_id: str | None = None
    trip_key: str | None = None
    questions_asked: int = 0
    # Implementation additions (see ARCHITECTURE.md "Implementation notes").
    linked_to_line_id: str | None = None
    has_proof_of_payment: bool = False
    user_excluded: bool = False
    assumed_fields: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: dt.datetime | None = None


class Question(BaseModel):
    id: str
    line_id: str
    field: str
    prompt: str
    kind: Literal["value", "choice", "confirm_duplicate", "justify_flag"]
    choices: list[str] | None = None
    voi_score: float
    reason: str
    finding_id: str | None = None


class Claim(BaseModel):
    id: str
    user_id: str
    title: str
    status: ClaimStatus
    lines: list[LineItem] = Field(default_factory=list)
    open_questions: list[Question] = Field(default_factory=list)
    total_inr: float = 0.0
    reimbursable_inr: float = 0.0
    ruleset_version: int
    finance_reference: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    submitted_at: dt.datetime | None = None
    # Implementation additions.
    findings: list[Finding] = Field(default_factory=list)
    questions_asked: int = 0
    answers_received: int = 0
    processing: int = 0


class Span(BaseModel):
    id: str
    trace_id: str
    parent_id: str | None = None
    name: str
    start: dt.datetime
    end: dt.datetime
    status: Literal["ok", "error", "retry"]
    attributes: dict[str, Any] = Field(default_factory=dict)


class Trace(BaseModel):
    id: str
    claim_id: str | None
    kind: Literal["claim", "policy", "eval"]
    spans: list[Span] = Field(default_factory=list)


class FieldMetric(BaseModel):
    accuracy: float
    n: int


class ReliabilityBin(BaseModel):
    lower: float
    upper: float
    count: int
    mean_confidence: float
    accuracy: float


class EvalMetrics(BaseModel):
    field_accuracy: float
    amount_exact_rate: float
    date_exact_rate: float
    gstin_exact_rate: float
    dup_precision: float
    dup_recall: float
    violation_accuracy: float
    ece: float
    questions_per_claim: float
    auto_completion_rate: float
    p50_latency_ms: float
    p95_latency_ms: float
    mean_tokens: float
    cost_usd_per_receipt: float


class EvalRun(BaseModel):
    id: str
    created_at: dt.datetime
    provider: str
    model: str
    prompt_version: str
    n_receipts: int
    metrics: EvalMetrics
    per_field: dict[str, FieldMetric]
    reliability_bins: list[ReliabilityBin]
    passed_gate: bool
    git_sha: str | None = None


class CorrectionLabel(BaseModel):
    id: str
    line_id: str
    field: str
    predicted: Any = None
    confidence: float
    corrected: Any = None
    created_at: dt.datetime


class SubmissionLine(BaseModel):
    line_id: str
    date: dt.date | None
    category: Category
    vendor_name: str | None
    vendor_gstin: str | None
    invoice_number: str | None
    amount_inr: float
    reimbursable_inr: float
    justification: str | None = None


class SubmissionPayload(BaseModel):
    claim_id: str
    user_id: str
    title: str
    ruleset_version: int
    lines: list[SubmissionLine]
    total_reimbursable_inr: float


class FinanceSubmission(BaseModel):
    reference: str
    claim_id: str
    status: Literal["submitted", "approved", "rejected"]
    submitted_at: dt.datetime
    decide_at: dt.datetime
    decided_at: dt.datetime | None = None
    note: str | None = None
    payload: SubmissionPayload


class PolicyDoc(BaseModel):
    id: str
    name: str
    text: str
    sha256: str
    created_at: dt.datetime


def line_date(line: LineItem) -> dt.date | None:
    return line.extracted.date.value
