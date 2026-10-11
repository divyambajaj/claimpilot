/**
 * In-browser mock of the backend (VITE_MOCK=1). Returns synthetic data shaped exactly like
 * src/types.ts and simulates SSE progress, so the UI is demoable without the API.
 * shortcut: scenario logic is scripted per demo receipt, not a real rules engine; delete once the backend serves replay data.
 */
import { ApiError, type Api } from "./client";
import type {
  AnswerIn,
  AuditRow,
  Claim,
  ClaimEvent,
  CorrectionLabel,
  DocStage,
  EvalEvent,
  EvalRun,
  Finding,
  LineItem,
  MetricsOverview,
  Policy,
  Question,
  RuleSet,
  Span,
  Trace,
  TraceSummary,
} from "../types";
import { POLICY_TEXT, buildRules, buildRuleset } from "./mockPolicy";
import { TEMPLATES, type MockTemplate } from "./mockReceipts";

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const clone = <T>(x: T): T => structuredClone(x);
let seq = 0;
const uid = (p: string) => `${p}_${(++seq).toString(36).padStart(4, "0")}${Math.random().toString(36).slice(2, 6)}`;

function rng(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------------------------------------------------------------- claim state
interface MockLine {
  line: LineItem;
  tpl: MockTemplate;
  pending: (Question & { _key: string })[];
}
interface MockClaim {
  claim: Claim;
  lines: MockLine[];
  listeners: Set<(e: ClaimEvent) => void>;
}
const claims = new Map<string, MockClaim>();
let rulesets: RuleSet[] = [buildRuleset(POLICY_TEXT, 1, "2026-10-01T09:30:00Z")];
let policyText = POLICY_TEXT;

const ruleById = (id: string | null) => rulesets.find((r) => r.active)?.rules.find((r) => r.id === id);

function emit(mc: MockClaim, e: ClaimEvent) {
  mc.listeners.forEach((l) => l(clone(e)));
}

function recompute(mc: MockClaim) {
  const c = mc.claim;
  c.lines = mc.lines.map((m) => m.line);
  const all = mc.lines.flatMap((m) => m.pending).sort((a, b) => b.voi_score - a.voi_score);
  c.open_questions = all.slice(0, 3).map(({ _key: _k, ...q }) => q);
  const live = c.lines.filter((l) => l.status !== "excluded");
  c.total_inr = round2(live.reduce((s, l) => s + l.amount_inr, 0));
  c.reimbursable_inr = round2(live.reduce((s, l) => s + l.reimbursable_inr, 0));
  const settled = c.lines.length > 0 && c.lines.every((l) => l.status === "complete" || l.status === "excluded");
  if (c.status === "draft" || c.status === "ready_to_submit") {
    c.status = settled && live.length > 0 && all.length === 0 ? "ready_to_submit" : "draft";
  }
  c.updated_at = new Date().toISOString();
}

const round2 = (n: number) => Math.round(n * 100) / 100;

function lineStatus(m: MockLine): LineItem["status"] {
  if (m.line.status === "excluded" && m.pending.length === 0) return "excluded";
  if (m.pending.some((q) => q.kind === "value" || q.kind === "choice")) return "missing_info";
  if (m.pending.length > 0) return "flagged";
  if (m.line.findings.some((f) => f.severity === "block" && f.resolution === "open")) return "flagged";
  return m.line.status === "excluded" ? "excluded" : m.tpl.settledStatus;
}

function withCitation(f: Omit<Finding, "id">): Finding {
  const rule = ruleById(f.rule_id);
  return { id: uid("fnd"), ...clone(f), citation: rule ? clone(rule.citation) : f.citation };
}

function makeLine(claimId: string, docId: string, tpl: MockTemplate): MockLine {
  const lineId = uid("line");
  const line: LineItem = {
    id: lineId,
    claim_id: claimId,
    document_ids: [docId],
    extracted: clone(tpl.extracted),
    category: tpl.category,
    amount_inr: tpl.amount,
    reimbursable_inr: tpl.reimbursable,
    status: "processing",
    findings: tpl.findings.map(withCitation),
    linked_proof_line_id: null,
    trip_key: tpl.extracted.date.value && tpl.extracted.city.value ? `${tpl.extracted.date.value}:${tpl.extracted.city.value}` : null,
    questions_asked: 0,
  };
  const pending = tpl.questions.map((q) => ({
    _key: q.key,
    id: uid("q"),
    line_id: lineId,
    field: q.field,
    prompt: q.prompt,
    kind: q.kind,
    choices: q.choices ?? null,
    voi_score: q.voi,
    reason: q.reason,
  }));
  return { line, tpl, pending };
}

/** Cross-line logic that the backend's dedupe layer would do: UPI linking and duplicates. */
function linkLines(mc: MockClaim) {
  for (const m of mc.lines) {
    const role = m.tpl.role;
    if (role?.upiFor && !m.line.findings.some((f) => f.evidence.linked_to)) {
      const inv = mc.lines.find((x) => x.tpl.demo.name === role.upiFor);
      if (inv) {
        m.line.status = "excluded";
        m.line.reimbursable_inr = 0;
        m.line.findings.push({
          id: uid("fnd"),
          kind: "duplicate",
          severity: "info",
          rule_id: null,
          message: `Linked as proof of payment for the ${inv.line.extracted.vendor_name.value} invoice.`,
          citation: ruleById("UPI_PROOF_FOR_CASHLESS")?.citation ?? null,
          evidence: { linked_to: inv.line.id, layer: "upi_link", score: 0.98, matched_on: ["amount", "date", "payee"] },
          resolution: "acknowledged",
        });
        inv.line.linked_proof_line_id = m.line.id;
        inv.line.document_ids = [...inv.line.document_ids, ...m.line.document_ids];
      } else {
        m.line.status = "flagged";
        m.line.findings.push({
          id: uid("fnd"),
          kind: "validation",
          severity: "warn",
          rule_id: null,
          message: "UPI payment with no matching invoice in this claim. Add the invoice or exclude this line.",
          citation: null,
          evidence: {},
          resolution: "open",
        });
      }
    }
    if (role?.duplicateOf && !m.pending.some((q) => q.kind === "confirm_duplicate")) {
      const orig = mc.lines.find((x) => x.tpl.demo.name === role.duplicateOf);
      if (orig) {
        m.line.findings.push({
          id: uid("fnd"),
          kind: "duplicate",
          severity: "warn",
          rule_id: null,
          message: `Looks like the same ride as receipt #${mc.lines.indexOf(orig) + 1}: same vendor, amount and date.`,
          citation: { section: "7. Duplicates and misuse", quote: "The same expense must never be claimed twice.", char_start: policyText.indexOf("The same expense must never"), char_end: policyText.indexOf("The same expense must never") + 46 },
          evidence: { matched_line_id: orig.line.id, matched_index: mc.lines.indexOf(orig) + 1, score: 0.93, layer: "fuzzy", vendor_sim: 0.96, amount_match: true, date_delta_days: 0 },
          resolution: "open",
        });
        m.pending.push({
          _key: "dup",
          id: uid("q"),
          line_id: m.line.id,
          field: "duplicate",
          prompt: `Is the photographed RydeGo receipt the same ride as receipt #${mc.lines.indexOf(orig) + 1} (₹486, 5 Oct)?`,
          kind: "confirm_duplicate",
          choices: ["Same ride, drop it", "Different ride, keep both"],
          voi_score: 0.84,
          reason: "Claiming it twice would add ₹486 to the reimbursable amount.",
        });
      }
    }
  }
}

function applyAnswer(mc: MockClaim, a: AnswerIn) {
  const m = mc.lines.find((x) => x.pending.some((q) => q.id === a.question_id));
  if (!m) throw new MockHttpError(404, "Question not found or already answered");
  const q = m.pending.find((x) => x.id === a.question_id)!;
  const L = m.line;
  m.pending = m.pending.filter((x) => x.id !== q.id);
  L.questions_asked += 1;
  const now = new Date().toISOString();
  if (q.kind === "value" && q.field === "attendees_count") {
    const n = Math.max(1, Math.round(Number(a.value)));
    if (!Number.isFinite(n)) throw new MockHttpError(422, "Attendees must be a number");
    labels.unshift({ id: uid("lbl"), line_id: L.id, field: q.field, predicted: L.extracted.attendees_count.value, confidence: L.extracted.attendees_count.confidence, corrected: n, created_at: now });
    L.extracted.attendees_count = { ...L.extracted.attendees_count, value: n, confidence: 1, origin: "user" };
    const cap = 750 * n;
    L.reimbursable_inr = Math.min(L.amount_inr, cap);
    const f = L.findings.find((x) => x.rule_id === "MEALS_CAP_PER_PERSON");
    if (f) {
      if (L.amount_inr > cap) {
        f.message = `Meal works out to ₹${Math.round(L.amount_inr / n).toLocaleString("en-IN")}/person, above the ₹750 limit; reimbursed at cap.`;
        f.evidence = { ...f.evidence, per_person_amount: round2(L.amount_inr / n), attendees_count: n };
        f.resolution = "acknowledged";
      } else L.findings = L.findings.filter((x) => x !== f);
    }
  } else if (q.kind === "value" && q.field === "date") {
    const v = String(a.value ?? "");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) throw new MockHttpError(422, "Date must be YYYY-MM-DD");
    L.extracted.date = { ...L.extracted.date, value: v, confidence: 1, origin: "user" };
    L.findings = L.findings.filter((x) => x.kind !== "missing");
  } else if (q.kind === "confirm_duplicate") {
    const confirm = a.value === "confirm" || a.value === true || a.value === q.choices?.[0];
    const f = L.findings.find((x) => x.kind === "duplicate" && x.resolution === "open");
    if (f) f.resolution = confirm ? "confirmed" : "overridden";
    L.status = confirm ? "excluded" : "complete";
    if (confirm) L.reimbursable_inr = 0;
  } else if (q.kind === "justify_flag") {
    const text = String(a.value ?? "").trim();
    if (text.length < 5) throw new MockHttpError(422, "Please add a short justification");
    const f = L.findings.find((x) => x.resolution === "open");
    if (f) {
      f.resolution = "justified";
      f.justification = text;
    }
  }
  L.status = lineStatus(m);
}

class MockHttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function processDocs(mc: MockClaim, tpls: { tpl: MockTemplate; filename: string }[]) {
  const claimId = mc.claim.id;
  const docs = tpls.map(({ tpl, filename }) => {
    const docId = uid("doc");
    mc.claim.documents?.push({
      id: docId, claim_id: claimId, filename, mime: "image/png", sha256: "", dhash: "", dhash_rotations: [],
      width: 1200, height: 1600, page: 0, stored_path: "",
    });
    return { docId, tpl, filename };
  });
  mc.claim.status = "draft";
  const stage = (doc_id: string, filename: string, s: DocStage, message?: string) =>
    emit(mc, { type: "stage", data: { doc_id, filename, stage: s, message } });
  docs.forEach((d) => stage(d.docId, d.filename, "ingest"));

  const queue = [...docs];
  const worker = async () => {
    for (let d = queue.shift(); d; d = queue.shift()) {
      await wait(350);
      stage(d.docId, d.filename, "extract");
      await wait(d.tpl.readMs * 0.7);
      const m = makeLine(claimId, d.docId, d.tpl);
      mc.lines.push(m);
      // keep upload order so "receipt #n" matches what the user added
      mc.lines.sort((a, b) => (mc.claim.documents ?? []).findIndex((x) => x.id === a.line.document_ids[0]) - (mc.claim.documents ?? []).findIndex((x) => x.id === b.line.document_ids[0]));
      recompute(mc);
      emit(mc, { type: "line_update", data: { line: m.line } });
      stage(d.docId, d.filename, "validate");
      await wait(d.tpl.readMs * 0.2);
      stage(d.docId, d.filename, "dedupe");
      await wait(d.tpl.readMs * 0.1 + 150);
      m.line.status = lineStatus(m);
      stage(d.docId, d.filename, "done", summarizeLine(m.line));
    }
  };
  await Promise.all([worker(), worker(), worker()]); // backend semaphore is 3
  linkLines(mc);
  mc.lines.forEach((m) => (m.line.status = lineStatus(m)));
  recompute(mc);
  mc.lines.forEach((m) => emit(mc, { type: "line_update", data: { line: m.line } }));
  emit(mc, { type: "question", data: { questions: mc.claim.open_questions } });
  emit(mc, { type: "done", data: { claim: mc.claim } });
}

function summarizeLine(l: LineItem): string {
  if (l.extracted.date.value === null) return "Date not readable";
  if (l.status === "missing_info") return "Needs one detail";
  return "Read";
}

// ---------------------------------------------------------------- admin data
const R = rng(42);
const today = new Date("2026-10-10T12:00:00Z");
const isoDay = (offset: number) => new Date(today.getTime() - offset * 86400000).toISOString().slice(0, 10);

const labels: CorrectionLabel[] = Array.from({ length: 14 }, (_, i) => {
  const fields = ["date", "attendees_count", "total_amount", "vendor_name", "date", "category", "vendor_gstin"];
  const f = fields[i % fields.length];
  return {
    id: `lbl_seed_${i}`,
    line_id: `line_seed_${i}`,
    field: f,
    predicted: f === "total_amount" ? 1840 : f === "date" ? "2026-10-01" : "—",
    confidence: 0.4 + R() * 0.3,
    corrected: f === "total_amount" ? 1480 : f === "date" ? "2026-01-10" : "—",
    created_at: new Date(today.getTime() - i * 7.3 * 3600000).toISOString(),
  };
});

const overview: MetricsOverview = (() => {
  const claims_per_day = Array.from({ length: 30 }, (_, i) => {
    const d = 29 - i;
    const dow = new Date(isoDay(d)).getUTCDay();
    const base = dow === 0 || dow === 6 ? 2 : 9;
    return { date: isoDay(d), count: Math.round(base + R() * 6 + i * 0.15) };
  });
  const cost_trend = claims_per_day.map((c, i) => ({ date: c.date, cost_per_claim_inr: round2(3.6 - i * 0.04 + (R() - 0.5) * 0.5) }));
  const total = claims_per_day.reduce((s, c) => s + c.count, 0);
  return {
    days: 30,
    kpis: {
      claims_total: total,
      claims_today: claims_per_day[29].count,
      auto_completion_rate: 0.71,
      first_pass_ready_rate: 0.46,
      questions_per_claim: 1.4,
      cost_per_claim_inr: 2.84,
      p50_latency_ms: 6400,
      p95_latency_ms: 14800,
      error_rate: 0.012,
      retry_rate: 0.034,
      time_saved_hours: round2((total * 14) / 60),
      duplicate_inr_prevented: 48230,
    },
    claims_per_day,
    cost_trend,
    latency_histogram: [2, 4, 6, 8, 10, 12, 14, 16, 18, 20].map((b, i) => ({ bucket_ms: b * 1000, count: Math.round(60 * Math.exp(-((i - 2.5) ** 2) / 4) + R() * 6) })),
    violations_by_rule: [
      { rule_id: "MEALS_CAP_PER_PERSON", title: "Meal limit per person", count: 38 },
      { rule_id: "UPI_PROOF_FOR_CASHLESS", title: "Payment proof above ₹2,000", count: 24 },
      { rule_id: "SUBMISSION_WINDOW_30D", title: "Submit within 30 days", count: 17 },
      { rule_id: "GST_INVOICE_ABOVE_5000", title: "GST invoice for ₹5,000+", count: 11 },
      { rule_id: "LODGING_CAP_METRO", title: "Hotel cap, metro", count: 9 },
      { rule_id: "MEALS_NO_ALCOHOL", title: "Alcohol not reimbursable", count: 4 },
    ],
    duplicates_by_layer: [
      { layer: "perceptual", count: 14, amount_inr: 21480 },
      { layer: "fuzzy", count: 11, amount_inr: 17920 },
      { layer: "semantic", count: 6, amount_inr: 8830 },
    ],
    eval_trend: [],
    assumptions: { manual_employee_min: 12, manual_finance_min: 6, agent_employee_min: 2.5, agent_finance_min: 1.5 },
  };
})();

function makeEvalRun(i: number, provider: string, model: string, prompt: string, n: number, quality: number): EvalRun {
  const r = rng(100 + i);
  const fa = Math.min(0.99, quality + (r() - 0.5) * 0.02);
  const fields = ["vendor_name", "vendor_gstin", "invoice_number", "date", "total_amount", "tax_amount", "payment_method", "city", "category", "attendees_count", "upi_txn_id"];
  const per_field = Object.fromEntries(
    fields.map((f) => {
      const acc = Math.min(0.995, fa + (r() - 0.55) * 0.14 - (f === "attendees_count" ? 0.12 : 0));
      return [f, { accuracy: round2(acc * 1000) / 1000, n: Math.round(n * (f === "upi_txn_id" ? 0.2 : f === "attendees_count" ? 0.3 : 0.95)), mean_confidence: Math.min(0.99, acc + (r() - 0.4) * 0.08) }];
    }),
  );
  const bins = Array.from({ length: 10 }, (_, b) => {
    const mid = b / 10 + 0.05;
    const count = b < 3 ? Math.round(4 + r() * 10) : Math.round(10 + b * b * 3 * r() + b * 10);
    return { lo: b / 10, hi: (b + 1) / 10, count, mean_confidence: mid, accuracy: Math.max(0, Math.min(1, mid + (r() - 0.55) * (0.22 - quality * 0.15))) };
  });
  const ece = round2(0.018 + (1 - quality) * 0.3 + r() * 0.01);
  return {
    id: `run_${String(i).padStart(3, "0")}`,
    created_at: new Date(today.getTime() - (12 - i) * 1.6 * 86400000).toISOString(),
    provider, model, prompt_version: prompt, n_receipts: n,
    metrics: {
      field_accuracy: fa,
      amount_exact_rate: Math.min(0.995, fa + 0.03),
      date_exact_rate: fa - 0.02,
      gstin_exact_rate: fa - 0.04,
      dup_precision: 0.9 + r() * 0.06,
      dup_recall: 0.86 + r() * 0.08,
      violation_accuracy: 0.9 + r() * 0.06,
      ece,
      questions_per_claim: round2(1.2 + r() * 0.6),
      auto_completion_rate: 0.66 + r() * 0.1,
      p50_latency_ms: 5200 + r() * 2400,
      p95_latency_ms: 12000 + r() * 5000,
      mean_tokens: 1850 + r() * 400,
      cost_usd_per_receipt: 0.006 + r() * 0.004,
    },
    per_field,
    reliability_bins: bins,
    passed_gate: fa >= 0.88 && ece <= 0.06,
    git_sha: Math.floor(r() * 0xfffffff).toString(16).padStart(7, "0"),
    subset: n > 20 ? "full" : "smoke",
  };
}

let evalRuns: EvalRun[] = [
  makeEvalRun(1, "claude_code", "sonnet", "v1", 60, 0.87),
  makeEvalRun(2, "claude_code", "sonnet", "v1", 60, 0.88),
  makeEvalRun(3, "gemini", "gemini-2.5-flash", "v1", 60, 0.84),
  makeEvalRun(4, "claude_code", "sonnet", "v2", 60, 0.91),
  makeEvalRun(5, "anthropic", "claude-sonnet-4-5", "v2", 60, 0.92),
  makeEvalRun(6, "gemini", "gemini-2.5-flash", "v2", 60, 0.86),
  makeEvalRun(7, "claude_code", "sonnet", "v3", 60, 0.93),
  makeEvalRun(8, "replay", "recorded", "v3", 60, 0.93),
].reverse();
overview.eval_trend = [...evalRuns].reverse().map((r) => ({ run_id: r.id, created_at: r.created_at, field_accuracy: r.metrics.field_accuracy, ece: r.metrics.ece }));

const VENDORS = ["Saffron Table Kitchen", "RydeGo", "Harbour View Residency", "Paperleaf Stationers", "Bloom Café", "Chaiwala Corner", "Shree Highway Fuels", "Metro Lodge Pune", "Kona Bistro", "SkyNet Broadband"];
const PEOPLE = ["Ananya R.", "Kabir S.", "Meera T.", "Rohan D.", "Ishaan P.", "Nisha K."];

const traceList: TraceSummary[] = Array.from({ length: 14 }, (_, i) => {
  const r = rng(500 + i);
  const docs = 2 + Math.floor(r() * 6);
  return {
    id: `trc_${(9381 - i).toString(16)}`,
    claim_id: `clm_${(4120 - i).toString(16)}`,
    kind: i === 3 ? "policy" : "claim",
    title: i === 3 ? "Policy compile v1" : `${PEOPLE[i % PEOPLE.length]} · ${["Mumbai trip", "Client visit", "September local", "Pune offsite", "Team offsite"][i % 5]}`,
    started_at: new Date(today.getTime() - i * 5.1 * 3600000).toISOString(),
    duration_ms: i === 3 ? 14200 : 3000 + docs * 1700 + r() * 3000,
    span_count: i === 3 ? 3 : docs * 4 + 2,
    status: i === 5 ? "error" : i === 2 || i === 8 ? "retry" : "ok",
    cost_usd: i === 3 ? 0.041 : docs * (0.006 + r() * 0.003),
  };
});

function makeTrace(id: string): Trace {
  const s = traceList.find((t) => t.id === id) ?? traceList[0];
  const r = rng(id.length * 31 + s.span_count);
  const t0 = new Date(s.started_at).getTime();
  const spans: Span[] = [];
  const mk = (name: string, start: number, dur: number, parent: string | null, status: Span["status"] = "ok", attributes: Record<string, unknown> = {}) => {
    const sp: Span = { id: `sp_${spans.length}`, trace_id: s.id, parent_id: parent, name, start: new Date(t0 + start).toISOString(), end: new Date(t0 + start + dur).toISOString(), status, attributes };
    spans.push(sp);
    return sp;
  };
  if (s.kind === "policy") {
    const root = mk("compile", 0, s.duration_ms, null, "ok", { policy_id: "pol_jio_platforms", ruleset_version: 1 });
    mk("llm.compile_policy", 40, 12100, root.id, "ok", { provider: "replay", model: "recorded", prompt_name: "compile_policy", prompt_version: "v1", tokens_in: 3120, tokens_out: 2480, cost_usd: 0.041, replayed: true, attempt: 1 });
    mk("verify_citations", 12160, 1400, root.id, "ok", { rules: 9, verified: 9 });
    return { id: s.id, claim_id: s.claim_id, kind: s.kind, spans };
  }
  const docs = (s.span_count - 2) / 4;
  const root = mk("process_documents", 0, s.duration_ms, null, s.status === "error" ? "error" : "ok", { claim_id: s.claim_id, documents: docs, ruleset_version: 1 });
  const lanes = [0, 0, 0];
  let lastEnd = 0;
  for (let d = 0; d < docs; d++) {
    const lane = lanes.indexOf(Math.min(...lanes));
    let t = lanes[lane];
    const ing = 120 + r() * 200;
    mk("ingest", t, ing, root.id, "ok", { doc_id: `doc_${d}`, mime: "image/jpeg", width: 1200, height: 1600, dhash: Math.floor(r() * 2 ** 48).toString(16) });
    t += ing;
    const retry = (s.status === "retry" && d === 1) || (s.status === "error" && d === docs - 1);
    const ext = 2400 + r() * 2600;
    const tokens_in = Math.round(1500 + r() * 400), tokens_out = Math.round(380 + r() * 200);
    const llm = { provider: "replay", model: "recorded", prompt_name: "extract_receipt", prompt_version: "v3", tokens_in, tokens_out, cost_usd: round2((tokens_in * 3 + tokens_out * 15) / 1e4) / 100, replayed: true, doc_id: `doc_${d}` };
    if (retry) {
      mk("extract", t, ext * 0.6, root.id, "retry", { ...llm, attempt: 1, error: "ValidationError: total_amount: Input should be a valid number" });
      t += ext * 0.6;
    }
    const failed = s.status === "error" && d === docs - 1;
    mk("extract", t, ext, root.id, failed ? "error" : "ok", { ...llm, attempt: retry ? 2 : 1, ...(failed ? { error: "ReplayMissError: fingerprint not in demo set" } : { raw_response: `{"doc_type":{"value":"receipt","confidence":0.96},"vendor_name":{"value":"${VENDORS[d % VENDORS.length]}","confidence":0.94}, …}` }) });
    t += ext;
    if (!failed) {
      const v = 30 + r() * 40;
      mk("validate", t, v, root.id, "ok", { gstin_valid: r() > 0.2, arithmetic: "reconciled", confidence_adjustments: 2 });
      t += v;
      const dd = 40 + r() * 80;
      mk("dedupe", t, dd, root.id, "ok", { candidates: Math.floor(r() * 40), best_score: round2(r() * 0.7), layer: "none" });
      t += dd;
    }
    lanes[lane] = t + 20;
    lastEnd = Math.max(lastEnd, t);
  }
  mk("rules", lastEnd + 10, 6, root.id, "ok", { rules_evaluated: 9, findings: Math.floor(r() * 4) });
  mk("plan", lastEnd + 18, 9, root.id, "ok", { candidates: 5, asked: Math.floor(r() * 3) + 1, assumed: 2 });
  root.end = new Date(t0 + lastEnd + 40).toISOString();
  return { id: s.id, claim_id: s.claim_id, kind: s.kind, spans };
}

const audit: AuditRow[] = (() => {
  const r = rng(77);
  const rules = buildRules(POLICY_TEXT);
  const res: AuditRow["resolution"][] = ["open", "acknowledged", "justified", "overridden", "confirmed"];
  return Array.from({ length: 46 }, (_, i) => {
    const dup = i % 6 === 2;
    const rule = rules[Math.floor(r() * rules.length)];
    const amount = Math.round(300 + r() * 9000);
    const resolution = res[Math.floor(r() * res.length)];
    return {
      finding_id: `fnd_seed_${i}`,
      claim_id: `clm_${(4120 - Math.floor(i / 3)).toString(16)}`,
      claim_title: `${PEOPLE[Math.floor(i / 3) % PEOPLE.length]} · ${["Mumbai trip", "Client visit", "September local", "Pune offsite"][Math.floor(i / 3) % 4]}`,
      line_id: `line_seed_${i}`,
      vendor: VENDORS[Math.floor(r() * VENDORS.length)],
      amount_inr: amount,
      kind: dup ? "duplicate" : "policy",
      rule_id: dup ? null : rule.id,
      rule_title: dup ? "Duplicate receipt" : rule.title,
      severity: dup ? "warn" : rule.severity,
      message: dup ? `Matches an earlier line: same vendor, amount and date (score ${(0.82 + r() * 0.17).toFixed(2)}, ${["perceptual", "fuzzy", "semantic"][i % 3]} layer).` : rule.message_template.replace(/\{(\w+)\}/g, (_m, k: string) => (k === "city" ? "Mumbai" : k === "days_since_expense" ? "41" : String(Math.round(amount / 2)))),
      policy_quote: dup ? "The same expense must never be claimed twice." : rule.citation.quote,
      policy_section: dup ? "7. Duplicates and misuse" : rule.citation.section,
      source_snippet: dup ? "Total ₹" + amount.toLocaleString("en-IN") : ["GRAND TOTAL ₹ 3,860.00", "Date: 28/08/2026", "Mode: UPI", "GSTIN: —"][i % 4],
      resolution,
      justification: resolution === "justified" ? ["Client dinner extended past schedule.", "Receipt was with the travel desk until last week.", "Approved by cost-centre head on email."][i % 3] : null,
      created_at: new Date(today.getTime() - i * 9.7 * 3600000).toISOString(),
    };
  });
})();

// ---------------------------------------------------------------- API
async function guard<T>(fn: () => T | Promise<T>, latency = 180): Promise<T> {
  await wait(latency);
  try {
    return clone(await fn());
  } catch (e) {
    if (e instanceof MockHttpError) throw new ApiError(e.status, e.message);
    throw e;
  }
}

function getMc(id: string): MockClaim {
  const mc = claims.get(id);
  if (!mc) throw new MockHttpError(404, "Claim not found");
  return mc;
}

const evalListeners = new Set<(e: EvalEvent) => void>();

export function createMockApi(): Api {
  return {
    health: () => guard(() => ({ status: "ok", provider: "replay", model: "recorded", prompt_versions: { extract_receipt: "v3", compile_policy: "v1" }, git_sha: "4f2a9c1", replay_mode: true })),
    createClaim: (title) =>
      guard(() => {
        const now = new Date().toISOString();
        const claim: Claim = {
          id: uid("clm"), user_id: "demo-user", title: title || "Mumbai client visit, Oct 2026", status: "draft",
          lines: [], open_questions: [], total_inr: 0, reimbursable_inr: 0, ruleset_version: 1, finance_reference: null,
          created_at: now, updated_at: now, submitted_at: null, documents: [],
        };
        claims.set(claim.id, { claim, lines: [], listeners: new Set() });
        return claim;
      }),
    listClaims: () => guard(() => [...claims.values()].map((m) => m.claim)),
    getClaim: (id) => guard(() => getMc(id).claim),
    uploadDocuments: (claimId, files, forLineId) =>
      guard(() => {
        const mc = getMc(claimId);
        if (forLineId) throw new MockHttpError(422, "Attaching a bill to a payment needs the real backend.");
        if (files.length > 10) throw new MockHttpError(413, "Up to 10 files per upload");
        // shortcut: uploaded files are mapped onto demo templates by order; the real backend reads them.
        const offset = mc.lines.length;
        const items = files.map((f, i) => ({ tpl: TEMPLATES[(offset + i) % TEMPLATES.length], filename: f.name }));
        void processDocs(mc, items);
        return { document_ids: items.map(() => uid("doc")) };
      }),
    addDemoDocuments: (claimId, names) =>
      guard(() => {
        const mc = getMc(claimId);
        const items = names.map((n) => {
          const tpl = TEMPLATES.find((t) => t.demo.name === n);
          if (!tpl) throw new MockHttpError(409, `“${n}” is not in the demo set`);
          return { tpl, filename: `${n}.jpg` };
        });
        void processDocs(mc, items);
        return { document_ids: items.map(() => uid("doc")) };
      }),
    subscribeClaim: (claimId, onEvent) => {
      const mc = claims.get(claimId);
      mc?.listeners.add(onEvent);
      return () => mc?.listeners.delete(onEvent);
    },
    answer: (claimId, answers) =>
      guard(() => {
        const mc = getMc(claimId);
        answers.forEach((a) => applyAnswer(mc, a));
        recompute(mc);
        emit(mc, { type: "claim_update", data: { claim: mc.claim } });
        return mc.claim;
      }, 420),
    lineAction: (claimId, lineId, action, justification) =>
      guard(() => {
        const mc = getMc(claimId);
        const m = mc.lines.find((x) => x.line.id === lineId);
        if (!m) throw new MockHttpError(404, "Line not found");
        if (action === "exclude") {
          m.line.status = "excluded";
          m.pending = [];
        } else if (action === "restore") {
          m.line.status = m.tpl.settledStatus === "excluded" ? "excluded" : "complete";
          m.line.status = lineStatus(m);
        } else {
          const q = m.pending.find((x) => (action === "justify" ? x.kind === "justify_flag" : x.kind === "confirm_duplicate"));
          if (q) applyAnswer(mc, { question_id: q.id, value: action === "justify" ? justification : action === "confirm_duplicate" ? "confirm" : "override" });
        }
        recompute(mc);
        return mc.claim;
      }),
    editLine: (claimId, lineId, patch) =>
      guard(() => {
        const mc = getMc(claimId);
        const m = mc.lines.find((x) => x.line.id === lineId);
        if (!m) throw new MockHttpError(404, "Line not found");
        for (const [k, v] of Object.entries(patch)) {
          const key = k as keyof typeof m.line.extracted;
          const f = m.line.extracted[key];
          if (f && typeof f === "object" && "confidence" in f) Object.assign(f, { value: v, confidence: 1, origin: "user" });
        }
        recompute(mc);
        return mc.claim;
      }),
    submit: (claimId) =>
      guard(() => {
        const mc = getMc(claimId);
        if (mc.claim.status !== "ready_to_submit") throw new MockHttpError(409, "Claim is not ready to submit");
        const ref = `FIN-${new Date().getFullYear()}-${String(Math.floor(10000 + Math.random() * 89999))}`;
        mc.claim.status = "submitted";
        mc.claim.finance_reference = ref;
        mc.claim.submitted_at = new Date().toISOString();
        emit(mc, { type: "claim_update", data: { claim: mc.claim } });
        return { finance_reference: ref };
      }, 900),
    demoReceipts: () => guard(() => TEMPLATES.map((t) => t.demo)),
    activeRuleset: () => guard(() => rulesets.find((r) => r.active)!),

    metricsOverview: () => guard(() => overview, 300),
    traces: (claimId) => guard(() => traceList.filter((t) => !claimId || t.claim_id === claimId)),
    trace: (id) => guard(() => makeTrace(id)),
    audit: () => guard(() => audit),
    evalRuns: () => guard(() => evalRuns),
    evalRun: (id) =>
      guard(() => {
        const run = evalRuns.find((r) => r.id === id);
        if (!run) throw new MockHttpError(404, "Run not found");
        return run;
      }),
    startEval: (subset) =>
      guard(() => {
        const total = subset === "smoke" ? 6 : 60;
        const runId = `run_${String(evalRuns.length + 1).padStart(3, "0")}`;
        void (async () => {
          for (let done = 1; done <= total; done++) {
            await wait(subset === "smoke" ? 450 : 90);
            evalListeners.forEach((l) => l({ type: "progress", data: { done, total, fixture_id: `fx_${String(done).padStart(3, "0")}` } }));
          }
          const run = { ...makeEvalRun(evalRuns.length + 1, "replay", "recorded", "v3", total, 0.93), id: runId, created_at: new Date().toISOString(), subset };
          evalRuns = [run, ...evalRuns];
          overview.eval_trend = [...overview.eval_trend, { run_id: run.id, created_at: run.created_at, field_accuracy: run.metrics.field_accuracy, ece: run.metrics.ece }];
          evalListeners.forEach((l) => l({ type: "done", data: { run: clone(run) } }));
        })();
        return { run_id: runId };
      }),
    subscribeEval: (onEvent) => {
      evalListeners.add(onEvent);
      return () => evalListeners.delete(onEvent);
    },
    labels: () => guard(() => labels),
    policies: () =>
      guard((): Policy[] => [
        { id: "pol_jio_platforms", name: "Jio Platforms Travel and Expense Policy", text: policyText, sha256: rulesets[0].policy_sha256, created_at: "2026-10-01T09:30:00Z", ruleset_versions: rulesets.map((r) => r.version), active_ruleset_version: rulesets.find((r) => r.active)?.version ?? null },
      ]),
    ruleset: (v) =>
      guard(() => {
        const rs = rulesets.find((r) => r.version === v);
        if (!rs) throw new MockHttpError(404, "Ruleset not found");
        return rs;
      }),
    compilePolicy: (_name, text) =>
      guard(() => {
        if (text.trim().length < 40) throw new MockHttpError(422, "Policy text is too short to compile");
        policyText = text;
        const version = Math.max(...rulesets.map((r) => r.version)) + 1;
        const rs = buildRuleset(text, version, new Date().toISOString());
        rulesets = [rs, ...rulesets.map((r) => ({ ...r, active: false }))];
        return rs;
      }, 2600),
    activateRuleset: (v) =>
      guard(() => {
        if (!rulesets.some((r) => r.version === v)) throw new MockHttpError(404, "Ruleset not found");
        rulesets = rulesets.map((r) => ({ ...r, active: r.version === v }));
        return rulesets.find((r) => r.version === v)!;
      }),
  };
}
