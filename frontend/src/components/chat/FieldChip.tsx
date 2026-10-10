import { useEffect, useId, useRef, useState } from "react";
import type { ExtractedField } from "../../types";

export type ConfidenceBand = "high" | "medium" | "low";

/** TAU = 0.75 matches the planner threshold (architecture section 7). */
export function confidenceBand(c: number): ConfidenceBand {
  return c >= 0.9 ? "high" : c >= 0.75 ? "medium" : "low";
}

const UNDERLINE: Record<ConfidenceBand, string> = {
  high: "decoration-line-strong decoration-solid",
  medium: "decoration-ink-3 decoration-dotted",
  low: "decoration-warn decoration-dashed",
};

const ORIGIN_NOTE = {
  llm: "Read by the model",
  validator: "Set by a validator",
  user: "Provided by you",
  assumed: "Assumed: low confidence, but it would not change the outcome, so we did not ask",
} as const;

interface Props<T> {
  label: string;
  field: ExtractedField<T>;
  format?: (v: T) => string;
  mono?: boolean;
}

export function FieldChip<T>({ label, field, format, mono }: Props<T>) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const popId = useId();
  const band = confidenceBand(field.confidence);
  const assumed = field.origin === "assumed";
  const user = field.origin === "user";
  const missing = field.value === null || field.value === undefined;
  const text = missing ? "Not found" : format ? format(field.value as T) : String(field.value);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const pct = Math.round(field.confidence * 100);

  return (
    <span ref={ref} className="relative inline-flex min-w-0 flex-col">
      <span className="label !text-[10px] !tracking-[0.05em]">{label}</span>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={`${label}: ${text}${assumed ? " (assumed)" : band === "low" && !user && !missing ? " (low confidence)" : ""}`}
        aria-controls={popId}
        data-confidence={band}
        data-origin={field.origin}
        className={[
          "group inline-flex max-w-full items-center gap-1 truncate text-left text-sm underline decoration-1 underline-offset-[5px]",
          mono ? "mono text-[13px]" : "",
          missing ? "text-ink-3 italic decoration-transparent" : assumed ? "text-ink-3 decoration-line-strong decoration-dotted" : user ? "text-ink decoration-accent/50 decoration-solid" : `text-ink ${UNDERLINE[band]}`,
          "hover:decoration-ink-2 rounded-sm",
        ].join(" ")}
      >
        <span className="truncate">{text}</span>
        {band === "low" && !assumed && !user && !missing && (
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-warn" aria-label="low confidence" />
        )}
        {assumed && <span className="text-[10px] uppercase tracking-wide text-ink-3 no-underline">assumed</span>}
      </button>
      {open && (
        <span
          id={popId}
          role="dialog"
          aria-label={`${label} details`}
          className="animate-in absolute left-0 top-full z-30 mt-1.5 block w-72 rounded-lg border border-line bg-surface p-3 text-left shadow-pop"
        >
          <span className="flex items-baseline justify-between">
            <span className="text-xs font-medium text-ink">{label}</span>
            <span className="mono text-xs text-ink-2">{user ? "100%" : `${pct}%`} confidence</span>
          </span>
          <span className="mt-2 block h-1 overflow-hidden rounded-full bg-sunken">
            <span
              className={`block h-full ${band === "low" && !user ? "bg-warn" : "bg-accent"}`}
              style={{ width: `${user ? 100 : pct}%` }}
            />
          </span>
          <span className="mt-3 block text-2xs text-ink-3">{field.source_snippet ? "Read from the document" : "No source text"}</span>
          {field.source_snippet && (
            <span className="mono mt-1 block rounded border border-line bg-sunken px-2 py-1.5 text-xs leading-5 text-ink">
              {field.source_snippet}
            </span>
          )}
          <span className="mt-2.5 block text-2xs leading-4 text-ink-2">{ORIGIN_NOTE[field.origin]}</span>
        </span>
      )}
    </span>
  );
}
