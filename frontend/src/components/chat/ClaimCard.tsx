import { Check } from "lucide-react";
import type { Claim, Finding, LineItem } from "../../types";
import { formatDateTime, formatINR, pluralize } from "../../lib/format";
import { Spinner } from "../ui";
import { LineItemCard } from "./LineItemCard";

interface Props {
  claim: Claim;
  onSubmit: () => void;
  submitting?: boolean;
  onWhy: (f: Finding, line: LineItem) => void;
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
  return "Waiting for checks.";
}

export function ClaimCard({ claim, onSubmit, submitting, onWhy }: Props) {
  const proofIds = new Set(claim.lines.map((l) => l.linked_proof_line_id).filter(Boolean));
  const byId = new Map(claim.lines.map((l) => [l.id, l]));
  const visible = claim.lines.map((l, i) => ({ l, i })).filter(({ l }) => !proofIds.has(l.id));
  const counted = claim.lines.filter((l) => l.status !== "excluded" && l.status !== "processing");
  const attention = claim.lines.filter((l) => l.status === "missing_info" || l.status === "flagged").length;
  const submitted = claim.status === "submitted" || claim.status === "approved" || claim.status === "rejected";
  const ready = claim.status === "ready_to_submit";

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
            : `${pluralize(counted.length, "line")}${attention ? ` · ${attention} ${attention === 1 ? "needs" : "need"} attention` : ""} · Policy v${claim.ruleset_version}`}
        </p>
      </header>

      {claim.lines.length === 0 ? (
        <div className="px-4 py-10 text-center text-sm text-ink-3">Line items appear here as receipts are read.</div>
      ) : (
        <ul className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
          {visible.map(({ l, i }) => (
            <LineItemCard key={l.id} line={l} index={i + 1} proof={l.linked_proof_line_id ? byId.get(l.linked_proof_line_id) : undefined} onWhy={onWhy} />
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
          <div className="mt-3 rounded-md border border-ok/20 bg-ok-soft px-3 py-2.5" role="status">
            <div className="flex items-center gap-2 text-sm font-medium text-ok">
              <Check size={16} strokeWidth={1.75} /> Submitted to Finance
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
      </footer>
    </section>
  );
}
