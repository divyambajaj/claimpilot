import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { Span, Trace, TraceSummary } from "../../types";
import { formatDateTime, formatMs } from "../../lib/format";
import { Empty, Pill, Spinner } from "../ui";

const ms = (iso: string) => new Date(iso).getTime();
const isLLM = (s: Span) => s.name === "llm" || s.name.startsWith("llm.");

const BAR: Record<string, string> = { ok: "bg-[#00806A]", retry: "bg-[#BF8233]", error: "bg-bad" };

export function TraceViewer() {
  const [list, setList] = useState<TraceSummary[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [span, setSpan] = useState<Span | null>(null);

  useEffect(() => {
    api.traces().then((t) => {
      setList(t);
      // open the richest trace first (an upload batch), not a one-span submit
      setSel(t.reduce<TraceSummary | null>((best, x) => (!best || x.span_count > best.span_count ? x : best), null)?.id ?? null);
    });
  }, []);
  useEffect(() => {
    if (!sel) return;
    setTrace(null);
    api.trace(sel).then((t) => {
      setTrace(t);
      setSpan(t.spans.find(isLLM) ?? t.spans[0] ?? null);
    });
  }, [sel]);

  if (!list) return <div className="flex justify-center py-20"><Spinner /></div>;
  if (!list.length) return <Empty title="No traces yet">Process a claim to record spans.</Empty>;

  return (
    <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
      <ul className="card max-h-[280px] xl:max-h-[640px] divide-y divide-line overflow-y-auto">
        {list.map((t) => (
          <li key={t.id}>
            <button
              type="button"
              onClick={() => setSel(t.id)}
              className={`block w-full px-3.5 py-2.5 text-left hover:bg-page ${sel === t.id ? "bg-accent-soft/60 shadow-[inset_2px_0_0_rgb(var(--accent))]" : ""}`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm text-ink">{t.title}</span>
                {t.status !== "ok" && <Pill tone={t.status === "error" ? "bad" : "warn"}>{t.status}</Pill>}
              </div>
              <div className="mono mt-0.5 flex justify-between text-2xs text-ink-3">
                <span>{formatDateTime(t.started_at)}</span>
                <span>{formatMs(t.duration_ms)} · {t.span_count} spans</span>
              </div>
            </button>
          </li>
        ))}
      </ul>
      <div className="min-w-0 space-y-4">
        {!trace ? <div className="card flex justify-center py-20"><Spinner /></div> : <Waterfall trace={trace} selected={span} onSelect={setSpan} />}
        {span && <SpanAttributes span={span} />}
      </div>
    </div>
  );
}

function Waterfall({ trace, selected, onSelect }: { trace: Trace; selected: Span | null; onSelect: (s: Span) => void }) {
  const { t0, total, rows } = useMemo(() => {
    const t0 = Math.min(...trace.spans.map((s) => ms(s.start)));
    const t1 = Math.max(...trace.spans.map((s) => ms(s.end)));
    const depth = (s: Span): number => (s.parent_id ? 1 + depth(trace.spans.find((p) => p.id === s.parent_id) ?? { ...s, parent_id: null }) : 0);
    const rows = [...trace.spans].sort((a, b) => ms(a.start) - ms(b.start) || (a.parent_id ? 1 : -1)).map((s) => ({ s, d: depth(s) }));
    return { t0, total: Math.max(t1 - t0, 1), rows };
  }, [trace]);
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const replayed = trace.spans.some((s) => s.attributes.replayed === true);
  const cost = trace.spans.reduce((a, s) => a + Number(s.attributes.cost_usd ?? 0), 0);

  return (
    <section className="card overflow-hidden">
      <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-4 py-3">
        <div>
          <h3 className="text-sm font-medium text-ink">Span waterfall</h3>
          <p className="mono text-2xs text-ink-3">{trace.id} · claim {trace.claim_id}</p>
        </div>
        <p className="mono text-xs text-ink-2">{formatMs(total)} · ${cost.toFixed(4)}</p>
        {replayed && <p className="w-full text-2xs text-ink-3">LLM responses replayed from a recording; the original call latency is in each llm span's latency_ms.</p>}
      </header>
      <div className="overflow-x-auto">
        <div className="min-w-[560px]">
          <div className="grid grid-cols-[180px_1fr] border-b border-line px-4 py-1.5">
            <span className="label">Span</span>
            <div className="relative h-4">
              {ticks.map((t) => (
                <span key={t} className="mono absolute top-0 -translate-x-1/2 whitespace-nowrap text-2xs text-ink-3 first:translate-x-0 last:-translate-x-full" style={{ left: `${t * 100}%` }}>
                  {formatMs(total * t)}
                </span>
              ))}
            </div>
          </div>
          <ul className="max-h-[440px] overflow-y-auto py-1">
            {rows.map(({ s, d }) => {
              const left = ((ms(s.start) - t0) / total) * 100;
              const width = Math.max(((ms(s.end) - ms(s.start)) / total) * 100, 0.4);
              const on = selected?.id === s.id;
              const quiet = !isLLM(s) && s.status === "ok";
              return (
                <li key={s.id}>
                  <button type="button" onClick={() => onSelect(s)} className={`grid w-full grid-cols-[180px_1fr] items-center px-4 py-[5px] text-left ${on ? "bg-accent-soft/60" : "hover:bg-page"}`}>
                    <span className="flex min-w-0 items-center gap-2 text-xs text-ink" style={{ paddingLeft: d * 12 }}>
                      <span className="truncate">{s.name}</span>
                      {s.attributes.doc_id != null && <span className="mono truncate text-2xs text-ink-3">{String(s.attributes.doc_id)}</span>}
                    </span>
                    <span className="relative h-3">
                      {ticks.slice(1, -1).map((t) => (
                        <span key={t} className="absolute inset-y-[-5px] w-px bg-line/70" style={{ left: `${t * 100}%` }} aria-hidden />
                      ))}
                      <span
                        className={`absolute inset-y-0 rounded-[2px] ${quiet ? "bg-line-strong" : BAR[s.status]} ${on ? "ring-2 ring-accent/30" : ""}`}
                        style={{ left: `${left}%`, width: `${width}%` }}
                        title={`${s.name} · ${formatMs(ms(s.end) - ms(s.start))}`}
                      />
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
      <footer className="flex flex-wrap gap-4 border-t border-line px-4 py-2 text-2xs text-ink-2">
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-3 rounded-[2px] bg-[#00806A]" />LLM call</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-3 rounded-[2px] bg-line-strong" />Deterministic step</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-3 rounded-[2px] bg-[#BF8233]" />Retry</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-3 rounded-[2px] bg-bad" />Error</span>
      </footer>
    </section>
  );
}

function SpanAttributes({ span }: { span: Span }) {
  const entries = Object.entries(span.attributes);
  return (
    <section className="card">
      <header className="flex items-center justify-between border-b border-line px-4 py-3">
        <h3 className="text-sm font-medium text-ink">
          {span.name} <span className="mono ml-1 text-xs font-normal text-ink-3">{formatMs(ms(span.end) - ms(span.start))}</span>
        </h3>
        <Pill tone={span.status === "ok" ? "ok" : span.status === "retry" ? "warn" : "bad"}>{span.status}</Pill>
      </header>
      <dl className="grid grid-cols-[140px_minmax(0,1fr)] gap-x-4 gap-y-1.5 px-4 py-3 text-xs">
        {entries.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-ink-3">{k}</dt>
            <dd className={`mono break-words ${k === "error" ? "text-bad" : "text-ink"}`}>
              {typeof v === "object" ? JSON.stringify(v) : String(v)}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
