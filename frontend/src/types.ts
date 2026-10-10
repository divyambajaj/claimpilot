/**
 * TypeScript mirror of the backend Pydantic models (docs/ARCHITECTURE.md section 4 and 6).
 * JSON conventions: `date` -> "YYYY-MM-DD", `datetime` -> ISO-8601 string, enums -> lowercase string values.
 * Types marked "UI contract" are not spelled out in the architecture doc; they are the shapes the
 * frontend expects from the corresponding endpoints (section 10).
 */

// ---------- enums (domain/enums.py) ----------
export type DocType =
  | "invoice"
  | "receipt"
  | "upi_screenshot"
  | "hotel_folio"
  | "ride_receipt"
  | "fuel"
  | "handwritten"
  | "unknown";

export type Category =
  | "meals"
  | "travel_local"
  | "travel_intercity"
  | "lodging"
  | "fuel"
  | "office"
  | "internet_phone"
  | "personal"
  | "other";

/** Who received a payment (prompt v3+): a business, or a private person (not reimbursable). */
export type PayeeType = "merchant" | "individual" | "unknown";

export type LineStatus = "processing" | "missing_info" | "flagged" | "complete" | "excluded" | "error";
export type ClaimStatus = "draft" | "ready_to_submit" | "submitted" | "approved" | "rejected";
export type Severity = "info" | "warn" | "block";
export type FindingKind = "policy" | "duplicate" | "validation" | "missing";
export type PaymentMethod = "upi" | "card" | "cash" | "unknown";
export type FieldOrigin = "llm" | "validator" | "user" | "assumed";
export type Resolution = "open" | "acknowledged" | "justified" | "overridden" | "confirmed";

// ---------- domain/models.py ----------
export interface FieldEdit {
  at: string;
  old_value: unknown;
  new_value: unknown;
  by?: string;
}

export interface ExtractedField<T> {
  value: T | null;
  confidence: number; // 0..1
  source_snippet?: string | null;
  origin: FieldOrigin;
  history?: FieldEdit[];
}

export interface ReceiptItem {
  description: string;
  quantity: number | null;
  unit_price: number | null;
  amount: number | null;
}

export type ReceiptQuality = "good" | "blurry" | "partial" | "rotated" | "handwritten";

export interface ExtractedReceipt {
  doc_type: ExtractedField<DocType>;
  vendor_name: ExtractedField<string>;
  vendor_gstin: ExtractedField<string>;
  invoice_number: ExtractedField<string>;
  date: ExtractedField<string>;
  currency: ExtractedField<string>;
  subtotal: ExtractedField<number>;
  tax_amount: ExtractedField<number>;
  total_amount: ExtractedField<number>;
  payment_method: ExtractedField<PaymentMethod>;
  upi_txn_id: ExtractedField<string>;
  payee_name: ExtractedField<string>;
  city: ExtractedField<string>;
  category: ExtractedField<Category>;
  attendees_count: ExtractedField<number>;
  /** Prompt v3+: absent on documents read by older prompt versions. */
  payee_type?: ExtractedField<PayeeType>;
  payer_name?: ExtractedField<string>;
  items: ReceiptItem[];
  raw_text: string;
  quality: ReceiptQuality;
}

export type ExtractedFieldKey = Exclude<keyof ExtractedReceipt, "items" | "raw_text" | "quality">;

export interface Document {
  id: string;
  claim_id: string;
  filename: string;
  mime: string;
  sha256: string;
  dhash: string;
  dhash_rotations: string[];
  width: number;
  height: number;
  page: number;
  stored_path: string;
}

export interface Citation {
  section: string;
  quote: string;
  char_start: number;
  char_end: number;
  /** Set by the compiler when the quote could only be located fuzzily (section 6). */
  citation_verified?: boolean;
}

export interface Finding {
  id: string;
  kind: FindingKind;
  severity: Severity;
  rule_id: string | null;
  message: string;
  citation: Citation | null;
  /** e.g. {matched_line_id, score, layer} for duplicates; {linked_to} for UPI proof. */
  evidence: Record<string, unknown>;
  resolution: Resolution;
  justification?: string | null;
}

export interface LineItem {
  id: string;
  claim_id: string;
  document_ids: string[];
  extracted: ExtractedReceipt;
  category: Category;
  amount_inr: number;
  reimbursable_inr: number;
  status: LineStatus;
  findings: Finding[];
  linked_proof_line_id: string | null;
  /** Set on a UPI screenshot attached to its invoice. */
  linked_to_line_id?: string | null;
  /** The user left this line out of the claim (restore brings it back). */
  user_excluded?: boolean;
  trip_key: string | null;
  questions_asked: number;
  /** The user's trip note / business purpose (answers OTHER_NEEDS_BUSINESS_PURPOSE, FUEL_TRIP_NOTE). */
  business_purpose?: string | null;
}

export type QuestionKind = "value" | "choice" | "confirm_duplicate" | "justify_flag";

export interface Question {
  id: string;
  line_id: string;
  field: string;
  prompt: string;
  kind: QuestionKind;
  choices: string[] | null;
  voi_score: number;
  reason: string;
}

export interface Claim {
  id: string;
  user_id: string;
  title: string;
  status: ClaimStatus;
  lines: LineItem[];
  open_questions: Question[];
  total_inr: number;
  reimbursable_inr: number;
  ruleset_version: number;
  finance_reference: string | null;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  /** Documents still being read. */
  processing?: number;
  /** UI contract: documents attached to the claim (filename lookup for progress rows). Optional. */
  documents?: Document[];
}

// ---------- rules (section 6) ----------
export type RuleField =
  | "amount_inr"
  | "category"
  | "date"
  | "vendor_gstin"
  | "vendor_gstin_valid"
  | "payment_method"
  | "has_proof_of_payment"
  | "attendees_count"
  | "city"
  | "doc_type"
  | "days_since_expense"
  | "invoice_number"
  | "is_weekend"
  | "per_person_amount"
  | "distance_km"
  | "vendor_name"
  | "has_bill"
  | "bill"
  | "payee_type"
  | "payer_name"
  | "payer_matches_employee"
  | "business_purpose"
  | "line_count"
  | "max_line_amount";

export type Op = "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "in" | "not_in" | "is_null" | "not_null" | "regex";

export interface Cond {
  field?: RuleField | null;
  op?: Op | null;
  value?: unknown;
  all?: Cond[] | null;
  any?: Cond[] | null;
  not?: Cond | null;
}

export interface Action {
  type: "flag" | "block" | "cap" | "require_field" | "require_justification" | "set_category";
  field?: RuleField | null;
  cap_inr?: number | null;
  cap_basis?: "line" | "per_person" | "per_day_category" | "per_claim_category" | null;
}

export interface Rule {
  id: string;
  title: string;
  category: Category | "any";
  scope: "line" | "day_category" | "vendor_day" | "claim";
  when: Cond;
  action: Action;
  severity: Severity;
  message_template: string;
  citation: Citation;
  confidence: number;
}

export interface RuleSet {
  version: number;
  policy_id: string;
  policy_sha256: string;
  compiled_at: string;
  compiler_prompt_version: string;
  provider: string;
  model: string;
  required_fields: Record<string, RuleField[]>;
  rules: Rule[];
  defaults: Record<string, unknown>;
  /** UI contract: whether this version is the active one (list endpoints). */
  active?: boolean;
}

/** UI contract for GET /admin/policies. */
export interface Policy {
  id: string;
  name: string;
  text: string;
  sha256: string;
  created_at: string;
  ruleset_versions: number[];
  active_ruleset_version: number | null;
}

// ---------- observability ----------
export type SpanName = "ingest" | "extract" | "validate" | "dedupe" | "rules" | "plan" | "submit" | "compile" | string;

export interface Span {
  id: string;
  trace_id: string;
  parent_id: string | null;
  name: SpanName;
  start: string;
  end: string;
  status: "ok" | "error" | "retry";
  attributes: Record<string, unknown>;
}

export interface Trace {
  id: string;
  claim_id: string;
  kind: "claim" | "policy" | "eval";
  spans: Span[];
}

/** UI contract for GET /admin/traces (list rows). */
export interface TraceSummary {
  id: string;
  claim_id: string;
  kind: Trace["kind"];
  title: string;
  started_at: string;
  duration_ms: number;
  span_count: number;
  status: "ok" | "error" | "retry";
  cost_usd: number;
}

// ---------- evaluation ----------
export interface EvalMetrics {
  field_accuracy: number;
  amount_exact_rate: number;
  date_exact_rate: number;
  gstin_exact_rate: number;
  dup_precision: number;
  dup_recall: number;
  violation_accuracy: number;
  ece: number;
  questions_per_claim: number;
  auto_completion_rate: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  mean_tokens: number;
  cost_usd_per_receipt: number;
}

export interface FieldMetric {
  accuracy: number;
  n: number;
  mean_confidence: number;
}

export interface ReliabilityBin {
  lo: number;
  hi: number;
  count: number;
  mean_confidence: number;
  accuracy: number;
}

export interface EvalRun {
  id: string;
  created_at: string;
  provider: string;
  model: string;
  prompt_version: string;
  n_receipts: number;
  metrics: EvalMetrics;
  per_field: Record<string, FieldMetric>;
  reliability_bins: ReliabilityBin[];
  passed_gate: boolean;
  git_sha: string | null;
  /** UI contract: "smoke" | "full" if the backend records it. */
  subset?: string;
  /** Micro accuracy, Brier, per-rule P/R, duplicate misses by layer, UPI-link P/R, gate messages. */
  details?: Record<string, unknown>;
}

export interface CorrectionLabel {
  id: string;
  line_id: string;
  field: string;
  predicted: unknown;
  confidence: number;
  corrected: unknown;
  created_at: string;
}

// ---------- API payloads (UI contract) ----------
export interface Health {
  status: string;
  provider: string;
  model: string;
  prompt_versions?: Record<string, string>;
  git_sha?: string | null;
  /** true when LLM_PROVIDER=replay (keyless demo). */
  replay_mode: boolean;
}

export interface DemoReceipt {
  name: string; // stable id passed to /documents/from-demo
  title: string; // "Dinner, Saffron Table"
  doc_type: DocType;
  description: string; // "GST invoice, 2 pages"
  thumbnail_url?: string | null;
  amount_inr?: number | null;
}

export interface AnswerIn {
  question_id: string;
  value: unknown;
}

export type LineActionName = "exclude" | "restore" | "override_duplicate" | "confirm_duplicate" | "justify";

export interface MetricsOverview {
  days: number;
  kpis: {
    claims_total: number;
    claims_today: number;
    auto_completion_rate: number;
    first_pass_ready_rate: number;
    questions_per_claim: number;
    cost_per_claim_inr: number;
    p50_latency_ms: number;
    p95_latency_ms: number;
    error_rate: number;
    retry_rate: number;
    time_saved_hours: number;
    duplicate_inr_prevented: number;
  };
  claims_per_day: { date: string; count: number }[];
  cost_trend: { date: string; cost_per_claim_inr: number }[];
  latency_histogram: { bucket_ms: number; count: number }[];
  violations_by_rule: { rule_id: string; title: string; count: number }[];
  duplicates_by_layer: { layer: "perceptual" | "fuzzy" | "semantic"; count: number; amount_inr: number }[];
  eval_trend: { run_id: string; created_at: string; field_accuracy: number; ece: number }[];
  /** Synthetic impact assumptions behind time_saved_hours (backend config.ImpactParams). */
  assumptions?: { manual_employee_min: number; manual_finance_min: number; agent_employee_min: number; agent_finance_min: number };
}

/** UI contract for GET /admin/audit (cross-claim findings table). */
export interface AuditRow {
  finding_id: string;
  claim_id: string;
  claim_title: string;
  line_id: string;
  vendor: string | null;
  amount_inr: number;
  kind: FindingKind;
  rule_id: string | null;
  rule_title: string | null;
  severity: Severity;
  message: string;
  policy_quote: string | null;
  policy_section: string | null;
  source_snippet: string | null;
  resolution: Resolution;
  justification: string | null;
  created_at: string;
}

// ---------- SSE events (UI contract for GET /claims/{id}/events) ----------
export type DocStage = "ingest" | "extract" | "validate" | "dedupe" | "rules" | "done" | "error";

export interface StageEvent {
  doc_id: string;
  filename?: string;
  stage: DocStage;
  message?: string;
}

export type ClaimEvent =
  | { type: "stage"; data: StageEvent }
  | { type: "line_update"; data: { line: LineItem } }
  | { type: "question"; data: { questions: Question[] } }
  | { type: "claim_update"; data: { claim: Claim } }
  | { type: "error"; data: { message: string; doc_id?: string; code?: string } }
  | { type: "done"; data: { claim: Claim } };

export type EvalEvent =
  | { type: "progress"; data: { done: number; total: number; fixture_id?: string } }
  | { type: "done"; data: { run: EvalRun } }
  | { type: "error"; data: { message: string } };
