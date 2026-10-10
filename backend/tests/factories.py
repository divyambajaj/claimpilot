"""Test helpers: receipt/line/claim factories and a scripted FakeProvider."""

import datetime as dt
from typing import Any

from app.domain.enums import Category, ClaimStatus, LineStatus
from app.domain.models import Claim, ExtractedReceipt, LineItem
from app.llm.base import LLMRequest, LLMResponse, Usage
from app.pipeline.validate.gstin import make_gstin

VALID_GSTIN = make_gstin("27", "AAKCC4821M")
NOW = dt.datetime(2026, 10, 10, 12, 0, 0)
TODAY = NOW.date()

_DEFAULTS: dict[str, Any] = {
    "doc_type": "invoice",
    "vendor_name": "Chaiwala Corner Pvt Ltd",
    "vendor_gstin": VALID_GSTIN,
    "invoice_number": "CC/2026/1",
    "date": dt.date(2026, 10, 3),
    "currency": "INR",
    "subtotal": None,
    "tax_amount": None,
    "total_amount": 1000.0,
    "payment_method": "card",
    "upi_txn_id": None,
    "payee_name": None,
    "city": "Mumbai",
    "category": "meals",
    "attendees_count": 2,
    "payee_type": None,
    "payer_name": None,
}


def make_receipt(conf: dict[str, float] | None = None, raw_text: str = "", **values: Any) -> ExtractedReceipt:
    conf = conf or {}
    data: dict[str, Any] = {}
    for name, default in _DEFAULTS.items():
        value = values.pop(name, default)
        data[name] = {"value": value, "confidence": conf.get(name, 0.95 if value is not None else 0.0)}
    data["items"] = values.pop("items", [])
    data["quality"] = values.pop("quality", "good")
    data["raw_text"] = raw_text or f"{data['vendor_name']['value']} total {data['total_amount']['value']}"
    assert not values, f"unknown receipt fields {values}"
    return ExtractedReceipt.model_validate(data)


def make_line(
    line_id: str = "L1", claim_id: str = "C1", conf: dict[str, float] | None = None, **values: Any
) -> LineItem:
    extra = {k: values.pop(k) for k in list(values) if k in LineItem.model_fields and k != "category"}
    receipt = make_receipt(conf=conf, **values)
    amount = receipt.total_amount.value or 0.0
    line = LineItem(
        id=line_id,
        claim_id=claim_id,
        document_ids=[f"D-{line_id}"],
        extracted=receipt,
        category=receipt.category.value or Category.OTHER,
        amount_inr=amount,
        reimbursable_inr=amount,
        status=LineStatus.PROCESSING,
        created_at=NOW,
    )
    return line.model_copy(update=extra)


def make_claim(lines: list[LineItem] | None = None, claim_id: str = "C1", **extra: Any) -> Claim:
    return Claim(
        id=claim_id,
        user_id=extra.pop("user_id", "demo-user"),
        title="Test claim",
        status=extra.pop("status", ClaimStatus.DRAFT),
        lines=lines or [],
        ruleset_version=1,
        created_at=NOW,
        updated_at=NOW,
        **extra,
    )


class FakeProvider:
    """Returns scripted responses (dicts) or raises scripted exceptions, in order."""

    name = "fake"
    model = "fake-model"
    supports_vision = True

    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[LLMRequest] = []

    async def complete_structured(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResponse(
            data=item,
            raw_text=str(item),
            provider=self.name,
            model=self.model,
            latency_ms=5,
            usage=Usage(input_tokens=100, output_tokens=50, cost_usd=0.001),
        )


def extraction_payload(**overrides: Any) -> dict[str, Any]:
    """A raw provider payload shaped like the extraction schema."""
    receipt = make_receipt(**overrides)
    data = receipt.model_dump(mode="json", exclude={"items"})
    for name in list(data):
        if isinstance(data[name], dict):
            data[name] = {k: data[name][k] for k in ("value", "confidence", "source_snippet")}
    data["items"] = []
    return data
