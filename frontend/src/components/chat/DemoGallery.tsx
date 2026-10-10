import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import type { DemoReceipt } from "../../types";
import { DOC_TYPE_LABEL, formatINR } from "../../lib/format";
import { Drawer, Spinner } from "../ui";

interface Props {
  open: boolean;
  receipts: DemoReceipt[] | null;
  onClose: () => void;
  onAdd: (names: string[]) => void;
}

/** Small drawn stand-in for a receipt image when the backend provides no thumbnail. */
function Thumb({ r }: { r: DemoReceipt }) {
  if (r.thumbnail_url) return <img src={r.thumbnail_url} alt="" className="h-14 w-11 rounded-sm border border-line object-cover" />;
  const upi = r.doc_type === "upi_screenshot";
  return (
    <div className={`flex h-14 w-11 shrink-0 flex-col gap-[3px] rounded-sm border border-line px-1.5 py-2 ${upi ? "bg-accent-soft" : "bg-page"}`} aria-hidden>
      {upi ? (
        <>
          <div className="mx-auto mt-1 h-3 w-3 rounded-full border border-accent/50" />
          <div className="mx-auto mt-1 h-[3px] w-5 rounded bg-accent/40" />
          <div className="mx-auto h-[2px] w-6 rounded bg-ink-3/30" />
        </>
      ) : (
        <>
          <div className="h-[3px] w-6 rounded bg-ink-3/50" />
          <div className="h-[2px] w-7 rounded bg-ink-3/25" />
          <div className="h-[2px] w-5 rounded bg-ink-3/25" />
          <div className="h-[2px] w-7 rounded bg-ink-3/25" />
          <div className="mt-auto h-[3px] w-4 self-end rounded bg-ink-3/50" />
        </>
      )}
    </div>
  );
}

export function DemoGallery({ open, receipts, onClose, onAdd }: Props) {
  const [sel, setSel] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (open) setSel(new Set((receipts ?? []).map((r) => r.name)));
  }, [open, receipts]);
  const toggle = (n: string) =>
    setSel((s) => {
      const next = new Set(s); // copy first: StrictMode runs updaters twice, so never mutate `s`
      if (!next.delete(n)) next.add(n);
      return next;
    });

  return (
    <Drawer open={open} onClose={onClose} title="Sample receipts">
      <p className="text-sm text-ink-2">
        Synthetic receipts, all fictional. They include a UPI screenshot that pays the hotel folio, an invoice with a mistyped GSTIN and a UPI transfer to a colleague.
      </p>
      {!receipts ? (
        <div className="flex justify-center py-10"><Spinner /></div>
      ) : (
        <ul className="mt-4 divide-y divide-line rounded-lg border border-line">
          {receipts.map((r) => {
            const on = sel.has(r.name);
            return (
              <li key={r.name}>
                <label className="flex cursor-pointer items-center gap-3 px-3 py-2.5 hover:bg-page">
                  <input type="checkbox" className="sr-only" checked={on} onChange={() => toggle(r.name)} />
                  <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-[4px] border ${on ? "border-accent bg-accent text-white" : "border-line-strong bg-surface"}`} aria-hidden>
                    {on && <Check size={12} strokeWidth={2.25} />}
                  </span>
                  <Thumb r={r} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-ink">{r.title}</span>
                    <span className="block truncate text-xs text-ink-3">{r.description || DOC_TYPE_LABEL[r.doc_type]}</span>
                  </span>
                  {r.amount_inr != null && <span className="mono text-xs text-ink-2">{formatINR(r.amount_inr)}</span>}
                </label>
              </li>
            );
          })}
        </ul>
      )}
      <div className="sticky -bottom-5 -mx-5 -mb-5 mt-5 flex items-center justify-between border-t border-line bg-surface px-5 py-4">
        <span className="text-xs text-ink-3">{sel.size} selected</span>
        <button type="button" className="btn-primary" disabled={sel.size === 0} onClick={() => onAdd((receipts ?? []).filter((r) => sel.has(r.name)).map((r) => r.name))}>
          Add {sel.size || ""} to claim
        </button>
      </div>
    </Drawer>
  );
}
