import { useState, type FormEvent } from "react";
import type { AnswerIn, Question } from "../../types";
import { Spinner } from "../ui";
import { formatDate } from "../../lib/format";

const NUMERIC = new Set(["attendees_count", "total_amount", "subtotal", "tax_amount", "amount_inr"]);

export function answerLabel(q: Question, value: unknown): string {
  if (q.kind === "confirm_duplicate")
    return value === "confirm" ? q.choices?.[0] ?? "Same expense, drop it" : q.choices?.[1] ?? "Different, keep both";
  if (q.field === "date") return formatDate(String(value));
  if (q.field === "attendees_count") return `${value} people`;
  return String(value);
}

interface Props {
  questions: Question[];
  onSubmit: (answers: AnswerIn[]) => Promise<void> | void;
  error?: string | null;
}

export function QuestionForm({ questions, onSubmit, error }: Props) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const set = (id: string, v: string) => setValues((s) => ({ ...s, [id]: v }));
  const valid = (q: Question) => {
    const v = (values[q.id] ?? "").trim();
    if (!v) return false;
    if (q.kind === "justify_flag") return v.length >= 5;
    if (q.kind === "value" && NUMERIC.has(q.field)) return Number(v) > 0;
    return true;
  };
  const allValid = questions.every(valid);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!allValid || busy) return;
    setBusy(true);
    try {
      await onSubmit(
        questions.map((q) => ({
          question_id: q.id,
          value: q.kind === "value" && NUMERIC.has(q.field) ? Number(values[q.id]) : values[q.id].trim(),
        })),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card overflow-hidden" aria-label="Questions">
      <ol className="divide-y divide-line">
        {questions.map((q, i) => (
          <li key={q.id} className="px-4 py-4">
            <div className="flex gap-3">
              <span className="mono mt-0.5 text-xs text-ink-3">{i + 1}</span>
              <div className="min-w-0 flex-1">
                <label htmlFor={`q-${q.id}`} className="block text-sm font-medium text-ink">
                  {q.prompt}
                </label>
                <p className="mt-0.5 text-xs text-ink-3">{q.reason}</p>
                <div className="mt-2.5">
                  <QuestionInput q={q} value={values[q.id] ?? ""} onChange={(v) => set(q.id, v)} />
                </div>
              </div>
            </div>
          </li>
        ))}
      </ol>
      <div className="flex items-center justify-between gap-3 border-t border-line bg-page/60 px-4 py-3">
        <span className={`text-xs ${error ? "text-bad" : "text-ink-3"}`} role={error ? "alert" : undefined}>
          {error ?? `${questions.filter(valid).length} of ${questions.length} answered`}
        </span>
        <button type="submit" className="btn-primary" disabled={!allValid || busy}>
          {busy && <Spinner size={12} />}
          Send answers
        </button>
      </div>
    </form>
  );
}

function QuestionInput({ q, value, onChange }: { q: Question; value: string; onChange: (v: string) => void }) {
  const id = `q-${q.id}`;
  if (q.kind === "justify_flag") {
    return (
      <textarea
        id={id}
        rows={3}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="One or two sentences for Finance"
        className="input h-auto resize-y py-2 leading-5"
      />
    );
  }
  if (q.kind === "confirm_duplicate" || q.kind === "choice") {
    const options =
      q.kind === "confirm_duplicate"
        ? [
            { value: "confirm", label: q.choices?.[0] ?? "Same expense, drop it" },
            { value: "override", label: q.choices?.[1] ?? "Different, keep both" },
          ]
        : (q.choices ?? []).map((c) => ({ value: c, label: c }));
    return (
      <div role="radiogroup" aria-labelledby={id} id={id} className="flex flex-wrap gap-2">
        {options.map((o) => {
          const on = value === o.value;
          return (
            <button
              key={o.value}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => onChange(o.value)}
              className={`h-8 rounded-md border px-3 text-sm transition-colors ${on ? "border-accent bg-accent-soft text-accent" : "border-line bg-surface text-ink hover:border-line-strong"}`}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    );
  }
  if (q.field === "date") {
    return <input id={id} type="date" value={value} onChange={(e) => onChange(e.target.value)} className="input w-44" max={new Date().toISOString().slice(0, 10)} />;
  }
  if (NUMERIC.has(q.field)) {
    return (
      <input
        id={id}
        type="number"
        inputMode="numeric"
        min={q.field === "attendees_count" ? 1 : 0}
        step={q.field === "attendees_count" ? 1 : 0.01}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="input mono w-32"
      />
    );
  }
  return <input id={id} type="text" value={value} onChange={(e) => onChange(e.target.value)} className="input" />;
}
