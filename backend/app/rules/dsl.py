"""Policy-as-code rule DSL (section 6). Schema-validated; executed by `rules.engine`."""

import datetime as dt
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import Category, Severity
from app.domain.models import Citation

RuleField = Literal[
    "amount_inr",
    "category",
    "date",
    "vendor_gstin",
    "vendor_gstin_valid",
    "payment_method",
    "has_proof_of_payment",
    "attendees_count",
    "city",
    "doc_type",
    "days_since_expense",
    "invoice_number",
    "is_weekend",
    "per_person_amount",
    "distance_km",
]
Op = Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "is_null", "not_null", "regex"]
CategoryKey = Category | Literal["any"]


class Cond(BaseModel):
    """A leaf comparison (`field op value`) or a combinator (`all` / `any` / `not`)."""

    model_config = ConfigDict(populate_by_name=True)

    field: RuleField | None = None
    op: Op | None = None
    value: Any = None
    all: list["Cond"] | None = None
    any: list["Cond"] | None = None
    not_: "Cond | None" = Field(default=None, alias="not")

    @model_validator(mode="after")
    def _one_shape(self) -> Self:
        shapes = [self.op is not None, self.all is not None, self.any is not None, self.not_ is not None]
        if sum(shapes) != 1:
            raise ValueError("condition must be exactly one of: leaf (field+op), all, any, not")
        if self.op is not None and self.field is None:
            raise ValueError("leaf condition needs a field")
        if self.op in ("in", "not_in") and not isinstance(self.value, list):
            raise ValueError(f"op {self.op} needs a list value")
        return self


class Action(BaseModel):
    type: Literal["flag", "block", "cap", "require_field", "require_justification", "set_category"]
    field: RuleField | None = None
    cap_inr: float | None = None
    cap_basis: Literal["line", "per_person", "per_day_category", "per_claim_category"] | None = None
    category: Category | None = None

    @model_validator(mode="after")
    def _params(self) -> Self:
        if self.type == "cap" and (self.cap_inr is None or self.cap_inr < 0 or self.cap_basis is None):
            raise ValueError("cap action needs cap_inr >= 0 and cap_basis")
        if self.type == "require_field" and self.field is None:
            raise ValueError("require_field action needs a field")
        if self.type == "set_category" and self.category is None:
            raise ValueError("set_category action needs a category")
        return self


class CitationDraft(BaseModel):
    section: str
    quote: str


class _RuleBase(BaseModel):
    id: str = Field(pattern=r"^[A-Z0-9_]{3,64}$")
    title: str
    category: CategoryKey
    scope: Literal["line", "day_category", "claim"]
    when: Cond
    action: Action
    severity: Severity
    message_template: str
    confidence: float = Field(ge=0, le=1)


class Rule(_RuleBase):
    citation: Citation


class RuleDraft(_RuleBase):
    """What the compiler LLM emits: citations carry only section + verbatim quote."""

    citation: CitationDraft


class RuleSetDraft(BaseModel):
    required_fields: dict[CategoryKey, list[RuleField]]
    rules: list[RuleDraft]


class RuleSet(BaseModel):
    version: int
    policy_id: str
    policy_sha256: str
    compiled_at: dt.datetime
    compiler_prompt_version: str
    provider: str
    model: str
    required_fields: dict[CategoryKey, list[RuleField]]
    rules: list[Rule]
    defaults: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule ids must be unique")
        return self

    def rule(self, rule_id: str) -> Rule | None:
        return next((r for r in self.rules if r.id == rule_id), None)

    def required_for(self, category: Category) -> list[str]:
        fields = list(self.required_fields.get("any", []))
        fields += [f for f in self.required_fields.get(category, []) if f not in fields]
        return fields
