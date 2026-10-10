import { Check, X } from "lucide-react";
import type { DocStage } from "../../types";
import { pluralize } from "../../lib/format";

export interface DocProgress {
  doc_id: string;
  filename: string;
  stage: DocStage;
  message?: string;
}

const STEPS = ["Uploaded", "Reading", "Checking", "Done"] as const;

/** ingest -> uploaded, extract -> reading, validate/dedupe/rules -> checking, done. */
export function stepIndex(stage: DocStage): number {
  switch (stage) {
    case "ingest":
      return 0;
    case "extract":
      return 1;
    case "validate":
    case "dedupe":
    case "rules":
      return 2;
    default:
      return 3;
  }
}

export function ProgressBubble({ docs }: { docs: DocProgress[] }) {
  const done = docs.filter((d) => d.stage === "done").length;
  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <span className="text-sm text-ink">{done === docs.length ? "Read" : "Reading"} {pluralize(docs.length, "document")}</span>
        <span className="mono text-xs text-ink-3">{done}/{docs.length}</span>
      </div>
      <ul className="divide-y divide-line">
        {docs.map((d) => {
          const idx = stepIndex(d.stage);
          const err = d.stage === "error";
          const finished = d.stage === "done";
          return (
            <li key={d.doc_id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 px-4 py-2.5" data-stage={d.stage}>
              <span className="mono truncate text-xs text-ink-2">{d.filename}</span>
              <span className={`flex items-center gap-1.5 text-xs ${err ? "text-bad" : finished ? "text-ink-2" : "text-ink"}`}>
                {finished && <Check size={14} strokeWidth={1.75} className="text-ok" />}
                {err && <X size={14} strokeWidth={1.75} />}
                {err ? d.message ?? "Could not read" : finished ? d.message ?? "Read" : `${STEPS[idx]}…`}
              </span>
              <div className="col-span-2 mt-2 grid grid-cols-4 gap-1" aria-hidden>
                {STEPS.map((s, i) => (
                  <span key={s} className="relative h-[3px] overflow-hidden rounded-full bg-sunken">
                    {(i < idx || finished) && <span className={`absolute inset-0 ${err ? "bg-bad/60" : "bg-accent"}`} />}
                    {i === idx && !finished && !err && <span className="bar-indeterminate absolute inset-y-0 w-2/5 bg-accent/70" />}
                  </span>
                ))}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
