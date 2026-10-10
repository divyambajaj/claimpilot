"""Build data/rulesets/jio_v1.json from hand-authored rules; citation offsets are located in code.

Run: `uv run python backend/scripts/build_jio_ruleset.py`. Fails if any quote is not verbatim in the policy.
"""

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import REPO_ROOT
from app.domain.models import PolicyDoc
from app.rules.compiler import build_ruleset, smoke_test
from app.rules.dsl import RuleSetDraft

POLICY = REPO_ROOT / "data" / "policies" / "jio_travel_expense_policy.md"
OUT = REPO_ROOT / "data" / "rulesets" / "jio_v1.json"
METROS = ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Kolkata", "Pune"]


def rule(rid, title, category, when, action, severity, message, section, quote, confidence, scope="line"):
    return {
        "id": rid,
        "title": title,
        "category": category,
        "scope": scope,
        "when": when,
        "action": action,
        "severity": severity,
        "message_template": message,
        "citation": {"section": section, "quote": quote},
        "confidence": confidence,
    }


RULES = [
    rule(
        "MEALS_CAP_PER_PERSON",
        "Meal limit per person",
        "meals",
        {
            "all": [
                {"field": "category", "op": "eq", "value": "meals"},
                {"field": "per_person_amount", "op": "gt", "value": 750},
            ]
        },
        {"type": "cap", "cap_inr": 750, "cap_basis": "per_person"},
        "warn",
        "Meal works out to ₹{per_person_amount}/person, above the ₹750 limit; reimbursed at cap.",
        "4.2 Meals",
        "Meals are reimbursed up to INR 750 per person per meal.",
        0.96,
    ),
    rule(
        "GST_INVOICE_ABOVE_5000",
        "GST invoice for expenses of ₹5,000+",
        "any",
        {
            "all": [
                {"field": "amount_inr", "op": "gte", "value": 5000},
                {"field": "doc_type", "op": "ne", "value": "upi_screenshot"},
                {"field": "vendor_gstin_valid", "op": "ne", "value": True},
            ]
        },
        {"type": "require_field", "field": "vendor_gstin"},
        "block",
        "Expenses of ₹5,000 or more need a valid GST invoice (GSTIN missing or fails checksum).",
        "3.1 Documentation",
        "Any single expense of INR 5,000 or more must be supported by a GST tax invoice bearing the vendor's GSTIN.",
        0.98,
    ),
    rule(
        "SUBMISSION_WINDOW_30D",
        "Submit within 30 days",
        "any",
        {"field": "days_since_expense", "op": "gt", "value": 30},
        {"type": "require_justification"},
        "warn",
        "Expense is {days_since_expense} days old; policy window is 30 days. Add a justification.",
        "2.3 Timelines",
        "Claims must be submitted within 30 days of the expense date.",
        0.99,
    ),
    rule(
        "EXPENSE_OLDER_THAN_90D",
        "No reimbursement after 90 days",
        "any",
        {"field": "days_since_expense", "op": "gt", "value": 90},
        {"type": "block"},
        "block",
        "Expense is {days_since_expense} days old; expenses older than 90 days are not reimbursed.",
        "2.3 Timelines",
        "Expenses older than 90 days will not be reimbursed.",
        0.97,
    ),
    rule(
        "UPI_PROOF_FOR_CASHLESS",
        "Payment proof for digital payments above ₹2,000",
        "any",
        {
            "all": [
                {"field": "payment_method", "op": "eq", "value": "upi"},
                {"field": "has_proof_of_payment", "op": "eq", "value": False},
                {"field": "doc_type", "op": "ne", "value": "upi_screenshot"},
                {"field": "amount_inr", "op": "gt", "value": 2000},
            ]
        },
        {"type": "flag"},
        "warn",
        "UPI payment above ₹2,000 without a matching payment confirmation screenshot.",
        "3.2 Proof of payment",
        "For digital payments above INR 2,000, attach the payment confirmation.",
        0.9,
    ),
    rule(
        "CASH_ABOVE_2000_JUSTIFY",
        "Justify cash payments above ₹2,000",
        "any",
        {
            "all": [
                {"field": "payment_method", "op": "eq", "value": "cash"},
                {"field": "amount_inr", "op": "gt", "value": 2000},
            ]
        },
        {"type": "require_justification"},
        "warn",
        "Cash payment of ₹{amount_inr} needs a written justification.",
        "3.2 Proof of payment",
        "Cash payments above INR 2,000 require a written justification, since they cannot be independently verified.",
        0.93,
    ),
    rule(
        "LODGING_CAP_METRO",
        "Hotel cap, metro cities",
        "lodging",
        {
            "all": [
                {"field": "city", "op": "in", "value": METROS},
                {"field": "amount_inr", "op": "gt", "value": 6000},
            ]
        },
        {"type": "cap", "cap_inr": 6000, "cap_basis": "line"},
        "warn",
        "Hotel in {city} above the metro cap of ₹6,000/night.",
        "5.1 Lodging",
        "Hotel stays are capped at INR 6,000 per night in metro cities and INR 4,000 elsewhere.",
        0.95,
    ),
    rule(
        "LODGING_CAP_NON_METRO",
        "Hotel cap, other cities",
        "lodging",
        {
            "all": [
                {"field": "city", "op": "not_null"},
                {"field": "city", "op": "not_in", "value": METROS},
                {"field": "amount_inr", "op": "gt", "value": 4000},
            ]
        },
        {"type": "cap", "cap_inr": 4000, "cap_basis": "line"},
        "warn",
        "Hotel in {city} above the non-metro cap of ₹4,000/night.",
        "5.1 Lodging",
        "Hotel stays are capped at INR 6,000 per night in metro cities and INR 4,000 elsewhere.",
        0.93,
    ),
    rule(
        "LOCAL_TRAVEL_DAILY_CAP",
        "Local conveyance per day",
        "travel_local",
        {"field": "amount_inr", "op": "gt", "value": 1500},
        {"type": "cap", "cap_inr": 1500, "cap_basis": "per_day_category"},
        "warn",
        "Local travel on this day totals ₹{total_inr}, above the ₹1,500 daily limit.",
        "4.1 Local conveyance",
        "Local conveyance (cabs, auto-rickshaws and metro) is reimbursed up to INR 1,500 per day.",
        0.94,
        scope="day_category",
    ),
    rule(
        "FUEL_CAP_PER_CLAIM",
        "Fuel per claim",
        "fuel",
        {"field": "amount_inr", "op": "gt", "value": 5000},
        {"type": "cap", "cap_inr": 5000, "cap_basis": "per_claim_category"},
        "warn",
        "Fuel in this claim totals ₹{total_inr}, above the ₹5,000 per-claim limit.",
        "4.4 Fuel",
        "Fuel for personal vehicles used on company business is reimbursed up to INR 5,000 per claim.",
        0.92,
        scope="claim",
    ),
    rule(
        "PHONE_INTERNET_MONTHLY_CAP",
        "Mobile and internet per month",
        "internet_phone",
        {"field": "amount_inr", "op": "gt", "value": 1000},
        {"type": "cap", "cap_inr": 1000, "cap_basis": "line"},
        "warn",
        "Bill of ₹{amount_inr} is above the ₹1,000 monthly limit; reimbursed at cap.",
        "6.2 Mobile and internet",
        "Mobile and internet bills are reimbursed up to INR 1,000 per month.",
        0.88,
    ),
    rule(
        "OFFICE_SUPPLIES_WEEKEND",
        "Office supplies bought on a weekend",
        "office",
        {"field": "is_weekend", "op": "eq", "value": True},
        {"type": "require_justification"},
        "warn",
        "Office supplies bought on a weekend need a note explaining why they could not wait.",
        "6.1 Office supplies",
        "Office supplies bought on a weekend need a note from the manager explaining why they could not wait "
        "until a working day.",
        0.85,
    ),
]

DRAFT = {
    "required_fields": {
        "any": ["date", "amount_inr"],
        "meals": ["attendees_count"],
        "lodging": ["city"],
    },
    "rules": RULES,
}


def main() -> None:
    text = POLICY.read_text()
    sha = hashlib.sha256(text.encode()).hexdigest()
    policy = PolicyDoc(
        id=f"pol_{sha[:12]}",
        name="Jio Platforms Travel & Expense Policy",
        text=text,
        sha256=sha,
        created_at=dt.datetime(2026, 10, 1),
    )
    ruleset, dropped = build_ruleset(
        RuleSetDraft.model_validate(DRAFT),
        policy,
        1,
        "hand-authored",
        "hand-authored",
        "n/a",
        policy.created_at,
    )
    if dropped or not all(r.citation.citation_verified for r in ruleset.rules):
        raise SystemExit(f"citations not verbatim: {dropped}")
    smoke_test(ruleset)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(ruleset.model_dump(mode="json", by_alias=True), indent=2, ensure_ascii=False) + "\n"
    )
    print(f"wrote {len(ruleset.rules)} rules to {OUT}")


if __name__ == "__main__":
    main()
