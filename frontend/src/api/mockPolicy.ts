import type { Citation, Rule, RuleSet } from "../types";

/** Fictional policy used by the mock layer (all names synthetic). */
export const POLICY_TEXT = `# Acme India Travel and Expense Policy

## 1. Purpose
This policy explains which business expenses Acme India reimburses and what evidence each claim needs. It applies to all full-time employees and contractors on assignment.

## 2. Submission
### 2.1 Who may claim
Employees may claim expenses they paid personally while on approved company business.
### 2.2 How to claim
Submit one claim per trip or per calendar month for recurring local expenses.
### 2.3 Timelines
Claims must be submitted within 30 days of the expense date. Late claims need a written justification and may be returned by Finance.

## 3. Documentation
### 3.1 Documentation
Every expense needs an itemised receipt or invoice. Any single expense of INR 5,000 or more must be supported by a GST tax invoice bearing the vendor's GSTIN.
### 3.2 Proof of payment
For digital payments above INR 2,000, attach the payment confirmation. A screenshot from any UPI app showing the reference number is acceptable.

## 4. Meals
### 4.1 What is covered
Business meals with clients or colleagues while travelling are covered. Alcohol is not reimbursable.
### 4.2 Meals
Meals are reimbursed up to INR 750 per person per meal. Team meal claims must state the number of attendees.

## 5. Lodging
### 5.1 Lodging
Hotel stays are capped at INR 6,000 per night in metro cities and INR 4,000 elsewhere. Metro cities are Mumbai, Delhi, Bengaluru, Hyderabad, Chennai, Kolkata and Pune.

## 6. Local travel and fuel
### 6.1 Cabs
App-based cabs and auto-rickshaws are reimbursed at actuals for business travel.
### 6.2 Fuel
Fuel for a personal vehicle used on company business is reimbursed only against a fuel bill that shows the date and amount.

## 7. Duplicates and misuse
The same expense must never be claimed twice. Finance may audit any claim within 12 months of payment.
`;

function cite(text: string, section: string, quote: string): Citation {
  const start = text.indexOf(quote);
  return {
    section,
    quote,
    char_start: Math.max(start, 0),
    char_end: start >= 0 ? start + quote.length : 0,
    citation_verified: start >= 0,
  };
}

export function buildRules(text: string): Rule[] {
  const rules: Rule[] = [
    {
      id: "SUBMISSION_WINDOW_30D",
      title: "Submit within 30 days",
      category: "any",
      scope: "line",
      when: { field: "days_since_expense", op: "gt", value: 30 },
      action: { type: "require_justification" },
      severity: "warn",
      message_template: "Expense is {days_since_expense} days old; policy window is 30 days. Add a justification.",
      citation: cite(text, "2.3 Timelines", "Claims must be submitted within 30 days of the expense date."),
      confidence: 0.99,
    },
    {
      id: "GST_INVOICE_ABOVE_5000",
      title: "GST invoice for ₹5,000 and above",
      category: "any",
      scope: "line",
      when: {
        all: [
          { field: "amount_inr", op: "gte", value: 5000 },
          { field: "vendor_gstin_valid", op: "ne", value: true },
        ],
      },
      action: { type: "require_field", field: "vendor_gstin" },
      severity: "block",
      message_template: "Expenses of ₹5,000 or more need a valid GST invoice (GSTIN missing or fails checksum).",
      citation: cite(
        text,
        "3.1 Documentation",
        "Any single expense of INR 5,000 or more must be supported by a GST tax invoice bearing the vendor's GSTIN.",
      ),
      confidence: 0.98,
    },
    {
      id: "UPI_PROOF_FOR_CASHLESS",
      title: "Payment proof above ₹2,000",
      category: "any",
      scope: "line",
      when: {
        all: [
          { field: "payment_method", op: "eq", value: "upi" },
          { field: "has_proof_of_payment", op: "eq", value: false },
          { field: "amount_inr", op: "gt", value: 2000 },
        ],
      },
      action: { type: "flag" },
      severity: "warn",
      message_template: "UPI payment above ₹2,000 without a matching payment confirmation screenshot.",
      citation: cite(text, "3.2 Proof of payment", "For digital payments above INR 2,000, attach the payment confirmation."),
      confidence: 0.9,
    },
    {
      id: "MEALS_NO_ALCOHOL",
      title: "Alcohol not reimbursable",
      category: "meals",
      scope: "line",
      when: { field: "category", op: "eq", value: "meals" },
      action: { type: "flag" },
      severity: "warn",
      message_template: "Bill includes alcohol, which is not reimbursable.",
      citation: cite(text, "4.1 What is covered", "Alcohol is not reimbursable."),
      confidence: 0.74,
    },
    {
      id: "MEALS_CAP_PER_PERSON",
      title: "Meal limit per person",
      category: "meals",
      scope: "line",
      when: {
        all: [
          { field: "category", op: "eq", value: "meals" },
          { field: "per_person_amount", op: "gt", value: 750 },
        ],
      },
      action: { type: "cap", cap_inr: 750, cap_basis: "per_person" },
      severity: "warn",
      message_template: "Meal works out to ₹{per_person_amount}/person, above the ₹750 limit; reimbursed at cap.",
      citation: cite(text, "4.2 Meals", "Meals are reimbursed up to INR 750 per person per meal."),
      confidence: 0.96,
    },
    {
      id: "MEALS_ATTENDEES_REQUIRED",
      title: "Attendee count on meals",
      category: "meals",
      scope: "line",
      when: { field: "category", op: "eq", value: "meals" },
      action: { type: "require_field", field: "attendees_count" },
      severity: "info",
      message_template: "Meal claims need the number of attendees.",
      citation: cite(text, "4.2 Meals", "Team meal claims must state the number of attendees."),
      confidence: 0.88,
    },
    {
      id: "LODGING_CAP_METRO",
      title: "Hotel cap, metro",
      category: "lodging",
      scope: "line",
      when: {
        all: [
          { field: "city", op: "in", value: ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Kolkata", "Pune"] },
          { field: "amount_inr", op: "gt", value: 6000 },
        ],
      },
      action: { type: "cap", cap_inr: 6000, cap_basis: "line" },
      severity: "warn",
      message_template: "Hotel in {city} above the metro cap of ₹6,000/night.",
      citation: cite(
        text,
        "5.1 Lodging",
        "Hotel stays are capped at INR 6,000 per night in metro cities and INR 4,000 elsewhere.",
      ),
      confidence: 0.95,
    },
    {
      id: "LODGING_CAP_NON_METRO",
      title: "Hotel cap, other cities",
      category: "lodging",
      scope: "line",
      when: {
        all: [
          { field: "city", op: "not_in", value: ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Kolkata", "Pune"] },
          { field: "amount_inr", op: "gt", value: 4000 },
        ],
      },
      action: { type: "cap", cap_inr: 4000, cap_basis: "line" },
      severity: "warn",
      message_template: "Hotel in {city} above the ₹4,000/night cap for non-metro cities.",
      citation: cite(
        text,
        "5.1 Lodging",
        "Hotel stays are capped at INR 6,000 per night in metro cities and INR 4,000 elsewhere.",
      ),
      confidence: 0.93,
    },
    {
      id: "FUEL_BILL_DATE",
      title: "Fuel bill shows date",
      category: "fuel",
      scope: "line",
      when: { field: "category", op: "eq", value: "fuel" },
      action: { type: "require_field", field: "date" },
      severity: "info",
      message_template: "Fuel bills must show the date.",
      citation: cite(
        text,
        "6.2 Fuel",
        "Fuel for a personal vehicle used on company business is reimbursed only against a fuel bill that shows the date and amount.",
      ),
      confidence: 0.86,
    },
  ];
  return rules;
}

export function buildRuleset(text: string, version: number, compiledAt: string): RuleSet {
  // In the mock compiler, rules whose quote no longer appears in the text are dropped.
  const rules = buildRules(text).filter((r) => r.citation.citation_verified);
  return {
    version,
    policy_id: "pol_acme_india",
    policy_sha256: fakeSha(text),
    compiled_at: compiledAt,
    compiler_prompt_version: "v1",
    provider: "replay",
    model: "recorded",
    required_fields: {
      any: ["amount_inr", "date"],
      meals: ["attendees_count"],
      fuel: ["date"],
    },
    rules,
    defaults: { currency: "INR", submission_window_days: 30 },
    active: true,
  };
}

/** Deterministic non-crypto hash rendered as 64 hex chars (display only). */
export function fakeSha(s: string): string {
  let h1 = 0x811c9dc5;
  let out = "";
  for (let round = 0; round < 8; round++) {
    for (let i = 0; i < s.length; i++) {
      h1 ^= s.charCodeAt(i) + round;
      h1 = Math.imul(h1, 0x01000193) >>> 0;
    }
    out += h1.toString(16).padStart(8, "0");
  }
  return out;
}
