import { useState } from "react";
import { ChevronDown, CornerDownRight } from "lucide-react";
import type { Finding, LineItem } from "../../types";
import { CATEGORY_LABEL, DOC_TYPE_LABEL, PAYMENT_LABEL, formatDate, formatINR } from "../../lib/format";
import { Pill, SEVERITY_TONE, StatusPill } from "../ui";
import { FieldChip } from "./FieldChip";

interface Props {
  line: LineItem;
  index: number;
  proof?: LineItem;
  onWhy: (f: Finding, line: LineItem) => void;
}

export function LineItemCard({ line, index, proof, onWhy }: Props) {
  const [expanded, setExpanded] = useState(false);
  const x = line.extracted;
  const processing = line.status === "processing";
  const excluded = line.status === "excluded";
  const blocked = line.findings.some((f) => f.severity === "block" && f.resolution === "open");
  const findings = line.findings.filter((f) => !(f.evidence.linked_to && f.severity === "info"));
  const capped = !excluded && line.reimbursable_inr < line.amount_inr;

  if (processing) {
    return (
      <li className="px-4 py-3.5" aria-busy="true">
        <div className="flex items-center justify-between">
          <div className="h-3.5 w-36 rounded bg-sunken" />
          <div className="h-3.5 w-16 rounded bg-sunken" />
        </div>
        <div className="mt-2 h-3 w-24 rounded bg-sunken" />
      </li>
    );
  }

  return (
    <li className={`px-4 py-3.5 ${excluded ? "bg-page/60" : ""}`} data-testid="line-item">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="mono w-4 shrink-0 text-2xs text-ink-3">{index}</span>
            <span className={`truncate text-sm font-medium ${excluded ? "text-ink-3 line-through decoration-ink-3/60" : "text-ink"}`}>
              {x.vendor_name.value ?? "Unknown vendor"}
            </span>
          </div>
          <div className="mt-0.5 pl-6 text-xs text-ink-3">
            {CATEGORY_LABEL[line.category]} · {formatDate(x.date.value, { year: false })} · {DOC_TYPE_LABEL[x.doc_type.value ?? "unknown"]}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className={`mono text-sm ${excluded ? "text-ink-3 line-through decoration-ink-3/60" : "text-ink"}`}>{formatINR(line.amount_inr)}</div>
          <div className="mt-1 flex justify-end">
            <StatusPill status={line.status} blocked={blocked} />
          </div>
        </div>
      </div>

      {capped && (
        <div className="mt-2 pl-6 text-xs text-ink-2">
          Reimbursable <span className="mono text-ink">{formatINR(line.reimbursable_inr)}</span> of {formatINR(line.amount_inr)}
        </div>
      )}

      {!excluded && (
        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2.5 pl-6 sm:grid-cols-3">
          <FieldChip label="Date" field={x.date} format={(v) => formatDate(v)} />
          <FieldChip label="Total" field={x.total_amount} format={(v) => formatINR(v)} mono />
          {line.category === "meals" ? (
            <FieldChip label="Attendees" field={x.attendees_count} />
          ) : (
            <FieldChip label="Paid by" field={x.payment_method} format={(v) => PAYMENT_LABEL[v]} />
          )}
          {expanded && (
            <>
              <FieldChip label="GSTIN" field={x.vendor_gstin} mono />
              <FieldChip label="Invoice no." field={x.invoice_number} mono />
              <FieldChip label="Tax" field={x.tax_amount} format={(v) => formatINR(v)} mono />
              {line.category === "meals" && <FieldChip label="Paid by" field={x.payment_method} format={(v) => PAYMENT_LABEL[v]} />}
              <FieldChip label="City" field={x.city} />
              <FieldChip label="Category" field={x.category} format={(v) => CATEGORY_LABEL[v]} />
            </>
          )}
        </div>
      )}

      {findings.length > 0 && (
        <ul className="mt-3 space-y-1.5 pl-6">
          {findings.map((f) => (
            <li key={f.id} className="flex items-start gap-2 text-xs leading-5">
              <span className={`mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full ${f.resolution !== "open" ? "bg-line-strong" : f.severity === "block" ? "bg-bad" : f.severity === "warn" ? "bg-warn" : "bg-ink-3"}`} />
              <span className={f.resolution === "open" ? "text-ink-2" : "text-ink-3"}>
                {f.message}
                {f.resolution !== "open" && <span className="text-ink-3"> ({f.resolution})</span>}{" "}
                <button type="button" className="link whitespace-nowrap" onClick={() => onWhy(f, line)}>
                  Why?
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      {proof && (
        <div className="mt-3 ml-6 flex items-start gap-2 rounded-md border border-line bg-page px-2.5 py-2 text-xs" data-testid="proof-row">
          <CornerDownRight size={14} strokeWidth={1.5} className="mt-0.5 shrink-0 text-ink-3" />
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-2">
              <span className="whitespace-nowrap font-medium text-ink">Proof of payment</span>
              <span className="mono ml-auto shrink-0 text-ink-2">{formatINR(proof.amount_inr)}</span>
            </div>
            <div className="mt-0.5 flex items-baseline gap-2 text-ink-3">
              <span className="truncate">
                UPI{proof.extracted.upi_txn_id.value && <> · ref <span className="mono">{proof.extracted.upi_txn_id.value}</span></>} · {formatDate(proof.extracted.date.value, { year: false })}
              </span>
              {proof.findings[0] && (
                <button type="button" className="link ml-auto shrink-0" onClick={() => onWhy(proof.findings[0], proof)}>
                  Why?
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {!excluded && (
        <div className="mt-2 pl-6">
          <button type="button" onClick={() => setExpanded((e) => !e)} className="inline-flex items-center gap-1 text-2xs text-ink-3 hover:text-ink-2" aria-expanded={expanded}>
            {expanded ? "Fewer fields" : "All fields"}
            <ChevronDown size={12} strokeWidth={1.5} className={expanded ? "rotate-180" : ""} />
          </button>
          {line.status === "flagged" && blocked && <Pill tone={SEVERITY_TONE.block}>Fix or exclude to continue</Pill>}
        </div>
      )}
    </li>
  );
}
