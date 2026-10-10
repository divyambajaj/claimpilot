import { useEffect, useId, useRef, useState, type FormEvent } from "react";
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
  /** Save a corrected value (re-checks the line); omitted when the field is not editable. */
  onEdit?: (value: string) => Promise<void>;
  inputType?: "date" | "number" | "text";
}

export function FieldChip<T>({ label, field, format, mono, onEdit, inputType = "text" }: Props<T>) {
  const [open, setOpen] = useState(false);
  const [shift, setShift] = useState(0);
  const [draft, setDraft] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
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

  function toggle() {
    const el = ref.current;
    if (!open && el) {
      // slide the 288px popover left so the scrolling list it sits in does not clip it
      const list = el.closest("ul");
      const boxLeft = list?.getBoundingClientRect().left ?? 0;
      const boxRight = boxLeft + (list?.clientWidth ?? window.innerWidth); // clientWidth excludes the scrollbar
      const left = el.getBoundingClientRect().left;
      setShift(Math.max(boxLeft + 4 - left, Math.min(0, boxRight - 4 - (left + 288))));
    }
    setOpen((o) => !o);
    setDraft(null);
    setErr(null);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!onEdit || draft === null || !draft.trim()) return;
    try {
      await onEdit(draft.trim());
      setOpen(false);
    } catch (x) {
      setErr(x instanceof Error ? x.message : "Could not save");
    }
  }

  return (
    <div ref={ref} className="relative inline-flex min-w-0 flex-col">
      <span className="label !text-[10px] !tracking-[0.05em]">{label}</span>
      <button
        type="button"
        onClick={toggle}
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
        <div
          id={popId}
          role="dialog"
          aria-label={`${label} details`}
          style={{ left: shift }}
          className={`animate-in absolute top-full z-30 mt-1.5 block w-72 rounded-lg border border-line bg-surface p-3 text-left shadow-pop`}
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
          {onEdit &&
            (draft === null ? (
              <button type="button" className="link mt-2.5 text-xs" onClick={() => setDraft(missing ? "" : String(field.value))}>
                {missing ? "Add the value" : "Correct this value"}
              </button>
            ) : (
              <form className="mt-2.5 flex gap-2" onSubmit={save}>
                <input
                  autoFocus
                  type={inputType}
                  step={inputType === "number" ? "any" : undefined}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  className="input h-8 min-w-0 flex-1 text-xs"
                  aria-label={`Correct ${label}`}
                />
                <button type="submit" className="btn-primary h-8 shrink-0" disabled={!draft.trim()}>Save</button>
              </form>
            ))}
          {err && <span className="mt-1.5 block text-2xs text-bad" role="alert">{err}</span>}
        </div>
      )}
    </div>
  );
}
