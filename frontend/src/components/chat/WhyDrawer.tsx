import type { Finding, LineItem, Rule } from "../../types";
import { fieldLabel, formatINR } from "../../lib/format";
import { Drawer, Pill, SEVERITY_LABEL, SEVERITY_TONE } from "../ui";

/** Plain-language evidence line, e.g. "Matches receipt #2 — same vendor, amount, date (score 0.93, fuzzy layer)". */
export function describeEvidence(f: Finding, lines: LineItem[]): string[] {
  const e = f.evidence as Record<string, unknown>;
  const idx = (id: unknown) => lines.findIndex((l) => l.id === id) + 1;
  const out: string[] = [];
  if (e.matched_line_id && !idx(e.matched_line_id) && e.matched_claim_id) {
    const layers = e.layers as { perceptual?: { signal?: string } } | undefined;
    const how = layers?.perceptual?.signal === "sha256" ? "the identical file" : `score ${Number(e.score).toFixed(2)}, ${e.layer} layer`;
    out.push(`Matches a ${e.matched_amount_inr != null ? `${formatINR(Number(e.matched_amount_inr))} ` : ""}receipt already in claim ${String(e.matched_claim_id)} (${how}).`);
  } else if (e.matched_line_id) {
    const n = idx(e.matched_line_id) || Number(e.matched_index) || "?";
    const same = [e.vendor_sim !== undefined && Number(e.vendor_sim) > 0.8 && "vendor", e.amount_match && "amount", e.date_delta_days === 0 && "date"].filter(Boolean);
    out.push(`Matches receipt #${n}${same.length ? ` — same ${same.join(", ")}` : ""} (score ${Number(e.score).toFixed(2)}, ${e.layer} layer)`);
  }
  if (e.linked_to) {
    const n = idx(e.linked_to);
    out.push(`Linked to receipt #${n || "?"} on ${(e.matched_on as string[] | undefined)?.join(", ") ?? "amount and date"} (score ${Number(e.score ?? 1).toFixed(2)}). Counted once, as proof of payment.`);
  }
  if (e.per_person_amount !== undefined) out.push(`${formatINR(Number(e.per_person_amount))} per person across ${e.attendees_count} attendees; limit ${formatINR(Number(e.cap_inr ?? 750))}.`);
  if (e.allowed_inr !== undefined && e.over_by_inr !== undefined) out.push(`Reimbursed up to the limit: ${formatINR(Number(e.allowed_inr))}, ${formatINR(Number(e.over_by_inr))} over.`);
  if (e.days_since_expense !== undefined) out.push(`Expense date is ${e.days_since_expense} days before today.`);
  if (e.field) out.push(e.action === "require_field" ? `The policy needs a valid ${fieldLabel(String(e.field))} on this receipt. Correct it on the line to re-check.` : `Field “${fieldLabel(String(e.field))}” could not be read with enough confidence.`);
  return out;
}

interface Props {
  finding: Finding | null;
  line: LineItem | null;
  lines: LineItem[];
  rule?: Rule;
  onClose: () => void;
  /** Resolve an open duplicate finding; omitted when the claim can no longer be edited. */
  onAction?: (action: "override_duplicate" | "confirm_duplicate") => void;
}

export function WhyDrawer({ finding, line, lines, rule, onClose, onAction }: Props) {
  const f = finding;
  const citation = f?.citation ?? rule?.citation ?? null;
  const title = rule?.title ?? (f?.kind === "duplicate" ? (f.evidence.linked_to ? "Proof of payment" : "Possible duplicate") : "Check");
  return (
    <Drawer open={!!f} onClose={onClose} title="Why this was flagged">
      {f && (
        <div className="space-y-6">
          <div>
            <div className="flex items-center gap-2">
              <Pill tone={SEVERITY_TONE[f.severity]}>{SEVERITY_LABEL[f.severity]}</Pill>
              {f.rule_id && <span className="mono text-2xs text-ink-3">{f.rule_id}</span>}
            </div>
            <h3 className="mt-2 text-lg font-medium text-ink">{title}</h3>
            <p className="mt-1 text-sm text-ink-2">{f.message}</p>
          </div>

          {citation && (
            <section>
              <div className="label">Policy</div>
              <blockquote className="mt-2 border-l-2 border-accent/60 pl-3 text-sm leading-6 text-ink">
                “{citation.quote}”
                <footer className="mt-1 text-xs text-ink-3">Section {citation.section}</footer>
              </blockquote>
              {citation.citation_verified === false && (
                <p className="mt-2 text-xs text-warn">Quote matched approximately, not verbatim.</p>
              )}
            </section>
          )}

          <section>
            <div className="label">Evidence</div>
            <ul className="mt-2 space-y-2 text-sm text-ink">
              {describeEvidence(f, lines).map((s) => (
                <li key={s} className="leading-6">{s}</li>
              ))}
            </ul>
            {line && (
              <dl className="mt-3 grid grid-cols-[96px_1fr] gap-y-1.5 rounded-md border border-line bg-page p-3 text-xs">
                <dt className="text-ink-3">Receipt</dt>
                <dd className="text-ink">#{lines.findIndex((l) => l.id === line.id) + 1} · {line.extracted.vendor_name.value}</dd>
                <dt className="text-ink-3">Amount</dt>
                <dd className="mono text-ink">{formatINR(line.amount_inr)}</dd>
                {line.extracted.total_amount.source_snippet && (
                  <>
                    <dt className="text-ink-3">Read as</dt>
                    <dd className="mono text-ink">{line.extracted.total_amount.source_snippet}</dd>
                  </>
                )}
              </dl>
            )}
          </section>

          {onAction && f.kind === "duplicate" && !f.evidence.linked_to && f.resolution === "open" && (
            <section className="flex flex-wrap gap-2">
              <button type="button" className="btn-secondary" onClick={() => onAction("override_duplicate")}>Not a duplicate, keep it</button>
              <button type="button" className="btn-ghost" onClick={() => onAction("confirm_duplicate")}>Yes, leave it out</button>
            </section>
          )}

          {f.resolution !== "open" && (
            <section>
              <div className="label">Resolution</div>
              <p className="mt-2 text-sm capitalize text-ink">{f.resolution}</p>
              {f.justification && <p className="mt-1 text-sm text-ink-2">“{f.justification}”</p>}
            </section>
          )}

          <p className="border-t border-line pt-4 text-xs leading-5 text-ink-3">
            Decisions come from deterministic rules compiled from the policy. The model only reads the documents.
          </p>
        </div>
      )}
    </Drawer>
  );
}
