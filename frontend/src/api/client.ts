import type {
  AnswerIn,
  AuditRow,
  Claim,
  ClaimEvent,
  CorrectionLabel,
  DemoReceipt,
  EvalEvent,
  EvalRun,
  Health,
  LineActionName,
  MetricsOverview,
  Policy,
  RuleSet,
  Trace,
  TraceSummary,
} from "../types";
import { openSSE, parseJSONData } from "./sse";
import { createMockApi } from "./mock";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: unknown,
    /** 422 on answers: question id (or field) -> message to show under that question. */
    readonly errors?: Record<string, string>,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type Unsubscribe = () => void;

/** Everything the UI needs from the backend (docs/ARCHITECTURE.md section 10). */
export interface Api {
  health(): Promise<Health>;
  // claims
  createClaim(title?: string): Promise<Claim>;
  listClaims(): Promise<Claim[]>;
  getClaim(id: string): Promise<Claim>;
  /** `forLineId`: one bill for that payment, read and linked now (422 with the reason if it is not that bill). */
  uploadDocuments(claimId: string, files: File[], forLineId?: string): Promise<{ document_ids: string[] }>;
  addDemoDocuments(claimId: string, names: string[]): Promise<{ document_ids: string[] }>;
  subscribeClaim(claimId: string, onEvent: (e: ClaimEvent) => void, onError?: (e: unknown) => void): Unsubscribe;
  answer(claimId: string, answers: AnswerIn[]): Promise<Claim>;
  lineAction(claimId: string, lineId: string, action: LineActionName, justification?: string): Promise<Claim>;
  editLine(claimId: string, lineId: string, patch: Record<string, unknown>): Promise<Claim>;
  submit(claimId: string): Promise<{ finance_reference: string }>;
  demoReceipts(): Promise<DemoReceipt[]>;
  activeRuleset(): Promise<RuleSet>;
  // admin
  metricsOverview(days?: number): Promise<MetricsOverview>;
  traces(claimId?: string): Promise<TraceSummary[]>;
  trace(id: string): Promise<Trace>;
  audit(): Promise<AuditRow[]>;
  evalRuns(): Promise<EvalRun[]>;
  evalRun(id: string): Promise<EvalRun>;
  startEval(subset: "smoke" | "full"): Promise<{ run_id?: string }>;
  subscribeEval(onEvent: (e: EvalEvent) => void, onError?: (e: unknown) => void): Unsubscribe;
  labels(): Promise<CorrectionLabel[]>;
  policies(): Promise<Policy[]>;
  ruleset(version: number): Promise<RuleSet>;
  compilePolicy(name: string, text: string): Promise<RuleSet>;
  activateRuleset(version: number): Promise<RuleSet>;
}

const BASE = "/api";

/** Each browser is its own demo employee, so one visitor's claims never show up as another's duplicates. */
export const userId: string = (() => {
  try {
    const id = localStorage.getItem("claimpilot.userId") ?? `demo-${Math.random().toString(36).slice(2, 8)}`;
    localStorage.setItem("claimpilot.userId", id);
    return id;
  } catch {
    return "demo-user";
  }
})();

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("X-User-Id", userId);
  const token = readAdminToken();
  if (token && path.startsWith("/admin")) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  const text = await res.text();
  const body: unknown = text ? safeJSON(text) : undefined;
  if (!res.ok) {
    const detail = (body as { detail?: unknown } | undefined)?.detail ?? body;
    const msg = typeof detail === "string" ? detail : `${res.status} ${res.statusText}`;
    throw new ApiError(res.status, msg, detail, (body as { errors?: Record<string, string> } | undefined)?.errors);
  }
  return body as T;
}

function safeJSON(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function readAdminToken(): string | null {
  try {
    return localStorage.getItem("claimpilot.admin_token");
  } catch {
    return null;
  }
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

const CLAIM_EVENTS = new Set(["stage", "line_update", "question", "claim_update", "error", "done"]);
const EVAL_EVENTS = new Set(["progress", "done", "error"]);

export function createHttpApi(): Api {
  return {
    health: () => request("/health"),
    createClaim: (title) => request("/claims", json({ title })),
    listClaims: () => request("/claims"),
    getClaim: (id) => request(`/claims/${id}`),
    uploadDocuments: (claimId, files, forLineId) => {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f, f.name));
      const q = forLineId ? `?for_line_id=${encodeURIComponent(forLineId)}` : "";
      return request(`/claims/${claimId}/documents${q}`, { method: "POST", body: fd });
    },
    addDemoDocuments: (claimId, names) => request(`/claims/${claimId}/documents/from-demo`, json({ names })),
    subscribeClaim: (claimId, onEvent, onError) =>
      openSSE(
        `${BASE}/claims/${claimId}/events`,
        (msg) => {
          if (!CLAIM_EVENTS.has(msg.event)) return;
          const data = parseJSONData(msg);
          if (data !== undefined) onEvent({ type: msg.event, data } as ClaimEvent);
        },
        { onError },
      ),
    answer: (claimId, answers) => request(`/claims/${claimId}/answers`, json(answers)),
    lineAction: (claimId, lineId, action, justification) =>
      request(`/claims/${claimId}/lines/${lineId}/actions`, json({ action, justification })),
    editLine: (claimId, lineId, patch) =>
      request(`/claims/${claimId}/lines/${lineId}`, { method: "PATCH", body: JSON.stringify(patch) }),
    submit: (claimId) => request(`/claims/${claimId}/submit`, { method: "POST" }),
    demoReceipts: () => request("/demo/receipts"),
    activeRuleset: () => request("/policies/active"),
    metricsOverview: (days = 30) => request(`/admin/metrics/overview?days=${days}`),
    traces: (claimId) => request(`/admin/traces${claimId ? `?claim_id=${encodeURIComponent(claimId)}` : ""}`),
    trace: (id) => request(`/admin/traces/${id}`),
    audit: () => request("/admin/audit"),
    evalRuns: () => request("/admin/eval/runs"),
    evalRun: (id) => request(`/admin/eval/runs/${id}`),
    startEval: (subset) => request("/admin/eval/run", json({ subset })),
    subscribeEval: (onEvent, onError) => {
      const token = readAdminToken();
      return openSSE(
        `${BASE}/admin/eval/events`,
        (msg) => {
          if (!EVAL_EVENTS.has(msg.event)) return;
          const data = parseJSONData(msg);
          if (data !== undefined) onEvent({ type: msg.event, data } as EvalEvent);
        },
        { onError, headers: token ? { Authorization: `Bearer ${token}` } : undefined },
      );
    },
    labels: () => request("/admin/labels"),
    policies: () => request("/admin/policies"),
    ruleset: (v) => request(`/admin/rulesets/${v}`),
    compilePolicy: (name, text) => request("/admin/policies", json({ name, text })),
    activateRuleset: (v) => request(`/admin/rulesets/${v}/activate`, { method: "POST" }),
  };
}

export const isMock = import.meta.env.VITE_MOCK === "1";

export const api: Api = isMock ? createMockApi() : createHttpApi();
