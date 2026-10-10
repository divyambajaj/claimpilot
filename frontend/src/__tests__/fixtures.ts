import type { Claim, LineItem } from "../types";
import { TEMPLATES } from "../api/mockReceipts";

export function makeLine(over: Partial<LineItem> = {}, tplName = "rydego-airport"): LineItem {
  const t = TEMPLATES.find((x) => x.demo.name === tplName)!;
  return {
    id: over.id ?? `line_${tplName}`,
    claim_id: "clm_1",
    document_ids: ["doc_1"],
    extracted: structuredClone(t.extracted),
    category: t.category,
    amount_inr: t.amount,
    reimbursable_inr: t.reimbursable,
    status: "complete",
    findings: [],
    linked_proof_line_id: null,
    trip_key: null,
    questions_asked: 0,
    ...over,
  };
}

export function makeClaim(over: Partial<Claim> = {}): Claim {
  return {
    id: "clm_1",
    user_id: "demo-user",
    title: "Mumbai client visit",
    status: "draft",
    lines: [],
    open_questions: [],
    total_inr: 0,
    reimbursable_inr: 0,
    ruleset_version: 1,
    finance_reference: null,
    created_at: "2026-10-10T10:00:00Z",
    updated_at: "2026-10-10T10:00:00Z",
    submitted_at: null,
    ...over,
  };
}
