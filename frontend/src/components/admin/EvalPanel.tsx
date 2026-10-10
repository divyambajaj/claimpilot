import { useEffect, useMemo, useState } from "react";
import { Play } from "lucide-react";
import { api, ApiError } from "../../api/client";
import type { CorrectionLabel, EvalRun } from "../../types";
import { fieldLabel, formatDateTime, formatMs, formatPct } from "../../lib/format";
import { Pill, Spinner } from "../ui";
import { ChartCard } from "./chart";
import { KpiGrid, KpiTile } from "./KpiTile";
import { ReliabilityChart } from "./ReliabilityChart";

export function EvalPanel() {
  const [runs, setRuns] = useState<EvalRun[] | null>(null);
  const [selId, setSelId] = useState<string | null>(null);
  const [subset, setSubset] = useState<"smoke" | "full">("smoke");
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [labels, setLabels] = useState<CorrectionLabel[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .evalRuns()
      .then((r) => {
        setRuns(r);
        setSelId(r[0]?.id ?? null);
      })
      .catch(() => setRuns([]));
    api.labels().then(setLabels).catch(() => setLabels([]));
    return api.subscribeEval((e) => {
      if (e.type === "progress") setProgress({ done: e.data.done, total: e.data.total });
      else if (e.type === "done") {
        setProgress(null);
        setRuns((rs) => [e.data.run, ...(rs ?? []).filter((r) => r.id !== e.data.run.id)]);
        setSelId(e.data.run.id);
      } else if (e.type === "error") {
        setProgress(null);
        setErr(e.data.message);
      }
    });
  }, []);

  const run = runs?.find((r) => r.id === selId) ?? null;
  const prev = runs && run ? runs[runs.indexOf(run) + 1] : undefined;
  const comparison = useMemo(() => {
    const seen = new Map<string, EvalRun>();
    for (const r of runs ?? []) {
      const key = `${r.provider}|${r.model}|${r.prompt_version}`;
      if (!seen.has(key)) seen.set(key, r);
    }
    return [...seen.values()].sort((a, b) => b.metrics.field_accuracy - a.metrics.field_accuracy);
  }, [runs]);
  const topCorrected = useMemo(() => {
    const c = new Map<string, number>();
    labels.forEach((l) => c.set(l.field, (c.get(l.field) ?? 0) + 1));
    return [...c.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4);
  }, [labels]);

  async function start() {
    setErr(null);
    setProgress({ done: 0, total: 0 }); // the real total arrives with the first progress event
    try {
      await api.startEval(subset);
    } catch (e) {
      setProgress(null);
      setErr(e instanceof ApiError && e.status === 501 ? "The evaluation runner is not available on this server yet." : e instanceof Error ? e.message : "Could not start eval");
    }
  }

  if (!runs) return <div className="flex justify-center py-20"><Spinner /></div>;
  const m = run?.metrics;
  const delta = (k: keyof EvalRun["metrics"], pct = true, lowerBetter = false) => {
    if (!m || !prev) return undefined;
    const d = m[k] - prev.metrics[k];
    if (Math.abs(d) < 1e-4) return "No change vs previous";
    const good = lowerBetter ? d < 0 : d > 0;
    return <span className={good ? "text-ok" : "text-bad"}>{d > 0 ? "+" : "−"}{pct ? `${Math.abs(d * 100).toFixed(1)} pts` : Math.abs(d).toFixed(3)} vs previous</span>;
  };

  return (
    <div className="space-y-6">
      <div className="card flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-md border border-line p-0.5" role="group" aria-label="Fixture subset">
            {(["smoke", "full"] as const).map((s) => (
              <button key={s} type="button" onClick={() => setSubset(s)} aria-pressed={subset === s} className={`h-7 rounded px-2.5 text-xs ${subset === s ? "bg-sunken text-ink" : "text-ink-3 hover:text-ink"}`}>
                {s === "smoke" ? "Smoke set" : "Full set"}
              </button>
            ))}
          </div>
          <button type="button" className="btn-primary" onClick={start} disabled={!!progress}>
            {progress ? <Spinner size={12} /> : <Play size={14} strokeWidth={1.5} />} Run eval
          </button>
        </div>
        {progress ? (
          <div className="min-w-[200px] flex-1">
            <div className="flex justify-between text-xs text-ink-2">
              <span>Running {subset} set in replay mode</span>
              <span className="mono">{progress.total ? `${progress.done}/${progress.total}` : "starting"}</span>
            </div>
            <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-sunken">
              <div className="h-full bg-accent transition-[width] duration-200" style={{ width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%` }} />
            </div>
          </div>
        ) : runs.length === 0 ? (
          <span className="text-xs text-ink-3">No runs yet. A smoke run scores a handful of synthetic receipts against ground truth.</span>
        ) : (
          <label className="flex items-center gap-2 text-xs text-ink-3">
            Run
            <select className="input h-7 w-auto py-0 pr-7 text-xs" value={selId ?? ""} onChange={(e) => setSelId(e.target.value)}>
              {runs.map((r) => (
                <option key={r.id} value={r.id}>{r.id} · {r.provider}/{r.model} · {r.prompt_version} · {formatDateTime(r.created_at)}</option>
              ))}
            </select>
          </label>
        )}
        {err && <span className="text-xs text-bad">{err}</span>}
        {run && (
          <div className="ml-auto flex items-center gap-3">
            <span className="mono hidden text-2xs text-ink-3 md:inline">{run.n_receipts} receipts · {run.git_sha ?? "no sha"}</span>
            <Pill tone={run.passed_gate ? "ok" : "bad"} dot>{run.passed_gate ? "Gate passed" : "Gate failed"}</Pill>
          </div>
        )}
      </div>

      {run && m && (
        <>
          <KpiGrid>
            <KpiTile label="Field accuracy" value={formatPct(m.field_accuracy, 1)} note={delta("field_accuracy")} />
            <KpiTile label="Amount exact" value={formatPct(m.amount_exact_rate, 1)} />
            <KpiTile label="Date exact" value={formatPct(m.date_exact_rate, 1)} />
            <KpiTile label="GSTIN exact" value={formatPct(m.gstin_exact_rate, 1)} />
            <KpiTile label="Calibration (ECE)" value={m.ece.toFixed(3)} note={delta("ece", false, true)} />
            <KpiTile label="Duplicate precision" value={formatPct(m.dup_precision, 1)} />
            <KpiTile label="Duplicate recall" value={formatPct(m.dup_recall, 1)} />
            <KpiTile label="Violation accuracy" value={formatPct(m.violation_accuracy, 1)} />
            <KpiTile label="Questions per claim" value={m.questions_per_claim.toFixed(2)} />
            <KpiTile label="Latency p50 / p95" value={formatMs(m.p50_latency_ms)} note={`p95 ${formatMs(m.p95_latency_ms)} · $${m.cost_usd_per_receipt.toFixed(4)}/receipt`} />
          </KpiGrid>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard title="Per-field accuracy" note="Exact match after normalisation">
              <table className="w-full text-xs">
                <thead className="text-ink-3">
                  <tr className="border-b border-line">
                    <th className="py-1.5 text-left font-medium">Field</th>
                    <th className="py-1.5 text-right font-medium">n</th>
                    <th className="w-[38%] py-1.5 pl-4 text-left font-medium">Accuracy</th>
                    <th className="py-1.5 text-right font-medium">Mean conf.</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {Object.entries(run.per_field).sort((a, b) => a[1].accuracy - b[1].accuracy).map(([f, v]) => (
                    <tr key={f}>
                      <td className="py-1.5 text-ink">{fieldLabel(f)}</td>
                      <td className="mono py-1.5 text-right text-ink-3">{v.n}</td>
                      <td className="py-1.5 pl-4">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 flex-1 rounded-full bg-sunken">
                            <div className={`h-full rounded-full ${v.accuracy < 0.85 ? "bg-[#BF8233]" : "bg-[#00806A]"}`} style={{ width: `${v.accuracy * 100}%` }} />
                          </div>
                          <span className="mono w-12 text-right text-ink">{formatPct(v.accuracy, 1)}</span>
                        </div>
                      </td>
                      <td className="mono py-1.5 text-right text-ink-2">{v.mean_confidence.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ChartCard>
            <ChartCard title="Reliability diagram" note={`ECE ${m.ece.toFixed(3)} over 10 bins of field-level confidence`}>
              <ReliabilityChart bins={run.reliability_bins} />
            </ChartCard>
          </div>
        </>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <ChartCard title="Provider comparison" note="Latest run per provider, model and prompt version">
          <div className="-mx-4 overflow-x-auto">
            <table className="w-full min-w-[560px] text-xs">
              <thead className="text-ink-3">
                <tr className="border-b border-line">
                  {["Provider", "Prompt", "Field acc.", "ECE", "Dup recall", "p50", "$/receipt", "Gate"].map((h, i) => (
                    <th key={h} className={`px-4 py-1.5 font-medium ${i > 1 ? "text-right" : "text-left"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {comparison.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-ink-3">Each run adds a row here, so providers and prompt versions can be compared side by side.</td>
                  </tr>
                )}
                {comparison.map((r, i) => (
                  <tr key={r.id} className={r.id === selId ? "bg-accent-soft/50" : ""}>
                    <td className="px-4 py-2 text-ink">{r.provider} <span className="text-ink-3">/ {r.model}</span>{i === 0 && <span className="ml-2 text-2xs text-accent">best</span>}</td>
                    <td className="mono px-4 py-2 text-ink-2">{r.prompt_version}</td>
                    <td className="mono px-4 py-2 text-right text-ink">{formatPct(r.metrics.field_accuracy, 1)}</td>
                    <td className="mono px-4 py-2 text-right text-ink-2">{r.metrics.ece.toFixed(3)}</td>
                    <td className="mono px-4 py-2 text-right text-ink-2">{formatPct(r.metrics.dup_recall, 0)}</td>
                    <td className="mono px-4 py-2 text-right text-ink-2">{formatMs(r.metrics.p50_latency_ms)}</td>
                    <td className="mono px-4 py-2 text-right text-ink-2">{r.metrics.cost_usd_per_receipt.toFixed(4)}</td>
                    <td className="px-4 py-2 text-right"><Pill tone={r.passed_gate ? "ok" : "bad"}>{r.passed_gate ? "Pass" : "Fail"}</Pill></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ChartCard>
        <ChartCard title="Online labels" note="Corrections users made in chat">
          <div className="mono text-2xl font-medium text-ink">{labels.length}</div>
          <div className="mt-0.5 text-xs text-ink-3">fields corrected</div>
          <ul className="mt-4 space-y-1.5 text-xs">
            {topCorrected.map(([f, n]) => (
              <li key={f} className="flex justify-between border-b border-line pb-1.5 last:border-0">
                <span className="text-ink">{fieldLabel(f)}</span>
                <span className="mono text-ink-2">{n}</span>
              </li>
            ))}
          </ul>
        </ChartCard>
      </div>
    </div>
  );
}
