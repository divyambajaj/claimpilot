import { useState } from "react";
import { Check } from "lucide-react";
import { ApiError } from "../../api/client";
import type { Claim, Finding, LineItem } from "../../types";
import { formatDateTime, formatINR, pluralize } from "../../lib/format";
import { Spinner } from "../ui";
import { LineItemCard } from "./LineItemCard";

interface Props {
  claim: Claim;
  onSubmit: () => void;
  submitting?: boolean;
  onWhy: (f: Finding, line: LineItem) => void;
  onEdit?: (line: LineItem, field: string, value: string) => Promise<void>;
  onExclude?: (line: LineItem, action: "exclude" | "restore") => void;
  onRaiseTicket?: (lineIds: string[], note: string) => Promise<void>;
}

export function claimHint(claim: Claim): string {
  const lines = claim.lines;
  if (lines.length === 0) return "Add receipts to start.";
  if (lines.some((l) => l.status === "processing")) return "Still reading receipts.";
  const q = claim.open_questions.length;
  if (q > 0) return `Answer ${pluralize(q, "question")} to continue.`;
  const blocked = lines.filter((l) => l.status === "flagged" || l.status === "error" || l.status === "missing_info").length;
  if (blocked > 0) return `${pluralize(blocked, "line")} still need attention.`;
  if (claim.status === "ready_to_submit") return "Ready to submit.";
  if (lines.every((l) => l.status === "excluded" || l.status === "error")) return "Every line is left out. Add other receipts, or tap Why? on a flag to keep a line.";
  return "Waiting for checks.";
}

const LEFT_OUT_REASON: Record<string, string> = {
  PERSONAL_EXPENSE_NOT_REIMBURSABLE: "personal expense",
  PERSONAL_PURPOSE_DECLARED: "personal purpose",
  P2P_TRANSFER_NOT_REIMBURSABLE: "payment to a person",
  BILL_REQUIRED: "no bill",
  DUPLICATE: "duplicate",
  GST_INVOICE_ABOVE_5000: "no valid GST invoice",
};

const lineName = (l: LineItem) => l.extracted.vendor_name.value ?? l.extracted.payee_name.value ?? "Unknown vendor";

const leftOutReasons = (l: LineItem) =>
  [...new Set(l.findings.filter((f) => f.severity === "block").map((f) => LEFT_OUT_REASON[f.rule_id ?? f.kind] ?? "blocked by policy"))];

const visibleLines = (claim: Claim) => {
  const proofIds = new Set(claim.lines.map((l) => l.linked_proof_line_id).filter(Boolean));
  return claim.lines.filter((l) => !proofIds.has(l.id));
};

/** Left-out lines that no open ticket covers yet. */
export function ticketable(claim: Claim): LineItem[] {
  const taken = new Set((claim.tickets ?? []).filter((t) => t.status !== "resolved").flatMap((t) => t.line_ids));
  return visibleLines(claim).filter((l) => l.status === "excluded" && !taken.has(l.id));
}

export const allLeftOut = (claim: Claim) => {
  const v = visibleLines(claim);
  return v.length > 0 && v.every((l) => l.status === "excluded");
};

/** "Raise a ticket with Finance": ask for a manual review of left-out lines. Renders nothing when there are none. */
export function TicketForm({ claim, onRaise }: { claim: Claim; onRaise: (lineIds: string[], note: string) => Promise<void> }) {
  const lines = ticketable(claim);
  const [open, setOpen] = useState(false);
  const [unchecked, setUnchecked] = useState<Set<string>>(new Set());
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  if (!lines.length) return null;
  if (!open)
    return (
      <button type="button" className="btn-secondary mt-3" onClick={() => setOpen(true)}>
        Raise a ticket with Finance
      </button>
    );
  const picked = lines.filter((l) => !unchecked.has(l.id)).map((l) => l.id);
  async function send() {
    setSending(true);
    setError(null);
    try {
      await onRaise(picked, note);
      setOpen(false);
      setNote("");
    } catch (err) {
      setError(err instanceof ApiError ? err.errors?.note ?? err.errors?.line_ids ?? err.message : "Could not raise the ticket.");
    } finally {
      setSending(false);
    }
  }
  return (
    <form className="mt-3 space-y-2.5 rounded-md border border-line bg-surface px-3 py-3" aria-label="Raise a ticket" onSubmit={(e) => (e.preventDefault(), void send())}>
      <fieldset className="space-y-1.5">
        <legend className="text-xs font-medium text-ink">Lines for Finance to review</legend>
        {lines.map((l) => (
          <label key={l.id} className="flex items-baseline gap-2 text-xs text-ink-2">
            <input
              type="checkbox"
              checked={!unchecked.has(l.id)}
              onChange={(e) => setUnchecked((s) => { const n = new Set(s); if (e.target.checked) n.delete(l.id); else n.add(l.id); return n; })}
            />
            <span className="min-w-0 flex-1 truncate">{lineName(l)} <span className="text-ink-3">· {leftOutReasons(l).join(", ") || "left out"}</span></span>
            <span className="mono shrink-0">{formatINR(l.amount_inr)}</span>
          </label>
        ))}
      </fieldset>
      <label className="block text-xs font-medium text-ink" htmlFor="ticket-note">Why should Finance review this?</label>
      <textarea id="ticket-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} className="input h-auto resize-y py-2 leading-5" />
      {error && <p className="text-xs text-bad" role="alert">{error}</p>}
      <div className="flex justify-end gap-2">
        <button type="button" className="btn-ghost" onClick={() => setOpen(false)}>Cancel</button>
        <button type="submit" className="btn-primary" disabled={sending || picked.length === 0}>
          {sending && <Spinner size={12} />}
          Submit ticket
        </button>
      </div>
    </form>
  );
}

/** Chat reply after answers when the claim is neither ready nor waiting on a question. */
export function afterAnswersText(claim: Claim): string {
  const proofIds = new Set(claim.lines.map((l) => l.linked_proof_line_id).filter(Boolean));
  const visible = claim.lines.filter((l) => !proofIds.has(l.id));
  const open = visible.filter((l) => l.status === "flagged" || l.status === "missing_info" || l.status === "error");
  if (open.length) {
    return `Still open: ${open.map(lineName).join(", ")}. Tap Why? on ${open.length === 1 ? "that line" : "those lines"} to fix it or leave it out.`;
  }
  if (visible.length && visible.every((l) => l.status === "excluded")) {
    const why = (l: LineItem) => `${lineName(l)} (${leftOutReasons(l).join(", ") || "left out"})`;
    const head = visible.length === 1 ? "The only line is left out" : `All ${visible.length} lines are left out`;
    return `Nothing in this claim is reimbursable. ${head}: ${visible.map(why).join("; ")}. Add other receipts or start a new claim.`;
  }
  return "Updated.";
}

export function ClaimCard({ claim, onSubmit, submitting, onWhy, onEdit, onExclude, onRaiseTicket }: Props) {
  const proofIds = new Set(claim.lines.map((l) => l.linked_proof_line_id).filter(Boolean));
  const byId = new Map(claim.lines.map((l) => [l.id, l]));
  const visible = claim.lines.filter((l) => !proofIds.has(l.id));
  const left = visible.filter((l) => l.status === "excluded").length;
  const attention = claim.lines.filter((l) => l.status === "missing_info" || l.status === "flagged").length;
  const submitted = claim.status === "submitted" || claim.status === "approved" || claim.status === "rejected";
  const ready = claim.status === "ready_to_submit";
  const ticketFor = (id: string) => (claim.tickets ?? []).filter((t) => t.line_ids.includes(id)).pop();

  return (
    <section className="card flex min-h-0 flex-col" aria-label="Claim">
      <header className="border-b border-line px-4 py-3.5">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="truncate text-md font-medium text-ink">{claim.title}</h2>
          <span className="mono shrink-0 text-2xs text-ink-3">{claim.id}</span>
        </div>
        <p className="mt-0.5 text-xs text-ink-3">
          {claim.lines.length === 0
            ? "No receipts yet"
            : `${pluralize(visible.length, "line")}${left ? ` · ${left} left out` : ""}${attention ? ` · ${attention} ${attention === 1 ? "needs" : "need"} attention` : ""} · Policy v${claim.ruleset_version}`}
        </p>
      </header>

      {claim.lines.length === 0 ? (
        <div className="px-4 py-10 text-center text-sm text-ink-3">Line items appear here as receipts are read.</div>
      ) : (
        <ul className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
          {visible.map((l, i) => (
            <LineItemCard key={l.id} line={l} index={i + 1} proof={l.linked_proof_line_id ? byId.get(l.linked_proof_line_id) : undefined} onWhy={onWhy} onEdit={submitted ? undefined : onEdit} onExclude={submitted ? undefined : onExclude} ticket={ticketFor(l.id)} />
          ))}
        </ul>
      )}

      <footer className="border-t border-line bg-page/60 px-4 py-3.5">
        <dl className="space-y-1 text-sm">
          <div className="flex justify-between">
            <dt className="text-ink-2">Total</dt>
            <dd className="mono text-ink-2" data-testid="claim-total">{formatINR(claim.total_inr)}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="font-medium text-ink">Reimbursable</dt>
            <dd className="mono font-medium text-ink" data-testid="claim-reimbursable">{formatINR(claim.reimbursable_inr)}</dd>
          </div>
        </dl>

        {submitted ? (
          <div className={`mt-3 rounded-md border px-3 py-2.5 ${claim.status === "rejected" ? "border-bad/20 bg-bad-soft" : "border-ok/20 bg-ok-soft"}`} role="status">
            <div className={`flex items-center gap-2 text-sm font-medium ${claim.status === "rejected" ? "text-bad" : "text-ok"}`}>
              <Check size={16} strokeWidth={1.75} /> {claim.status === "approved" ? "Approved by Finance" : claim.status === "rejected" ? "Rejected by Finance" : "Submitted to Finance"}
            </div>
            <div className="mt-1 text-xs text-ink-2">
              Reference <span className="mono text-ink">{claim.finance_reference}</span>
              {claim.submitted_at && <> · {formatDateTime(claim.submitted_at)}</>}
            </div>
          </div>
        ) : (
          <div className="mt-3 flex items-center justify-between gap-3">
            <p className="text-xs text-ink-3">{claimHint(claim)}</p>
            <button type="button" className="btn-primary shrink-0" disabled={!ready || submitting} onClick={onSubmit}>
              {submitting && <Spinner size={12} />}
              Submit claim
            </button>
          </div>
        )}
        {/* when every line is left out the chat offers the ticket under its summary instead */}
        {onRaiseTicket && !allLeftOut(claim) && <TicketForm claim={claim} onRaise={onRaiseTicket} />}
      </footer>
    </section>
  );
}
