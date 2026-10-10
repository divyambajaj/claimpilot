import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, LabelList, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../../api/client";
import type { MetricsOverview } from "../../types";
import { formatDate, formatINR, formatMs, formatNumber, formatPct } from "../../lib/format";
import { Spinner } from "../ui";
import { C, ChartCard, ChartTooltip, axisProps } from "./chart";
import { KpiGrid, KpiTile } from "./KpiTile";

const shortDate = (d: string) => formatDate(d, { year: false });

export function Overview() {
  const [m, setM] = useState<MetricsOverview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.metricsOverview(30).then(setM).catch((e: Error) => setErr(e.message));
  }, []);
  if (err) return <p className="text-sm text-bad">Could not load metrics: {err}</p>;
  if (!m) return <div className="flex justify-center py-20"><Spinner /></div>;
  const k = m.kpis;
  const a = m.assumptions;
  const saved = a ? a.manual_employee_min + a.manual_finance_min - a.agent_employee_min - a.agent_finance_min : 0;
  const evalTrend = m.eval_trend.map((r) => ({ ...r, label: shortDate(r.created_at.slice(0, 10)) }));

  return (
    <div className="space-y-6">
      <KpiGrid>
        <KpiTile label="Claims, 30 days" value={formatNumber(k.claims_total)} note={`${k.claims_today} today`} />
        <KpiTile label="Auto-completed lines" value={formatPct(k.auto_completion_rate)} note="Complete with zero questions" />
        <KpiTile label="Questions per claim" value={k.questions_per_claim.toFixed(1)} note="Asked only when they change the outcome" />
        <KpiTile label="Cost per claim" value={formatINR(k.cost_per_claim_inr)} note="From traced token usage" />
        <KpiTile label="Extract latency, p50" value={formatMs(k.p50_latency_ms)} note="Per document" />
        <KpiTile label="Extract latency, p95" value={formatMs(k.p95_latency_ms)} note="Per document" />
        <KpiTile label="Error rate" value={formatPct(k.error_rate, 1)} note={`Retries ${formatPct(k.retry_rate, 1)}`} />
        <KpiTile label="Time saved" value={`${formatNumber(k.time_saved_hours, k.time_saved_hours < 10 ? 1 : 0)} h`} note={a ? `Assumes ${formatNumber(saved)} min saved per claim` : "Synthetic assumption"} />
        <KpiTile label="Duplicates prevented" value={formatINR(k.duplicate_inr_prevented, { decimals: false })} note="Confirmed duplicate lines" />
        <KpiTile label="Ready on first pass" value={formatPct(k.first_pass_ready_rate)} note="Claims needing no answers" />
      </KpiGrid>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Claims per day" note="Last 30 days">
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={m.claims_per_day} margin={{ top: 4, right: 4, bottom: 0, left: -24 }} barCategoryGap={2}>
              <CartesianGrid vertical={false} stroke={C.grid} />
              <XAxis dataKey="date" {...axisProps} tickFormatter={shortDate} interval={6} />
              <YAxis {...axisProps} allowDecimals={false} />
              <Tooltip content={<ChartTooltip labelFormat={shortDate} />} cursor={{ fill: "#F4F3EF" }} />
              <Bar isAnimationActive={false} dataKey="count" name="Claims" fill={C.s1} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Cost per claim" note="₹, from span cost × FX" empty={m.cost_trend.length === 0 && "No traced LLM calls in this period."}>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={m.cost_trend} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
              <CartesianGrid vertical={false} stroke={C.grid} />
              <XAxis dataKey="date" {...axisProps} tickFormatter={shortDate} interval={6} />
              <YAxis {...axisProps} domain={[0, "auto"]} allowDecimals={false} tickFormatter={(v: number) => `₹${v}`} />
              <Tooltip content={<ChartTooltip labelFormat={shortDate} format={(v) => formatINR(v)} />} cursor={{ stroke: C.muted }} />
              <Line isAnimationActive={false} dataKey="cost_per_claim_inr" name="Cost / claim" stroke={C.s1} strokeWidth={2} dot={m.cost_trend.length < 8 ? { r: 3, fill: C.s1, strokeWidth: 0 } : false} activeDot={{ r: 4, strokeWidth: 2, stroke: "#fff" }} />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Violations by rule" note="Findings raised, last 30 days" empty={m.violations_by_rule.length === 0 && "No policy findings yet. They appear as claims are checked."}>
          <ResponsiveContainer width="100%" height={Math.max(220, m.violations_by_rule.length * 30)}>
            <BarChart data={m.violations_by_rule} layout="vertical" margin={{ top: 0, right: 28, bottom: 0, left: 0 }} barCategoryGap={6}>
              <XAxis type="number" hide />
              <YAxis type="category" dataKey="title" {...axisProps} width={200} interval={0} tick={{ fontSize: 12, fill: "#5C5950" }} />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: "#F4F3EF" }} />
              <Bar isAnimationActive={false} barSize={12} dataKey="count" name="Findings" fill={C.s1} radius={[0, 3, 3, 0]}>
                <LabelList dataKey="count" position="right" className="num" style={{ fontSize: 11, fill: "#5C5950" }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Duplicate catches by layer" note="Confirmed duplicates and the amount kept out of claims" empty={!m.duplicates_by_layer.some((d) => d.count > 0) && "No duplicates confirmed yet. Re-uploading a receipt from an earlier claim shows up here."}>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={m.duplicates_by_layer.map((d) => ({ ...d, label: d.layer[0].toUpperCase() + d.layer.slice(1), caption: `${d.count} · ${formatINR(d.amount_inr, { decimals: false })}` }))} layout="vertical" margin={{ top: 0, right: 110, bottom: 0, left: 0 }} barCategoryGap={18}>
              <XAxis type="number" hide />
              <YAxis type="category" dataKey="label" {...axisProps} width={90} tick={{ fontSize: 12, fill: "#5C5950" }} />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: "#F4F3EF" }} />
              <Bar isAnimationActive={false} barSize={12} dataKey="count" name="Duplicates" fill={C.s1} radius={[0, 3, 3, 0]}>
                <LabelList dataKey="caption" position="right" style={{ fontSize: 11, fill: "#5C5950" }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Eval field accuracy" note="Per eval run" empty={evalTrend.length === 0 && "No evaluation runs yet. Start one from the Evaluation tab."}>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={evalTrend} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid vertical={false} stroke={C.grid} />
              <XAxis dataKey="label" {...axisProps} />
              <YAxis {...axisProps} domain={[0.8, 1]} tickFormatter={(v: number) => formatPct(v)} />
              <Tooltip content={<ChartTooltip format={(v) => formatPct(v, 1)} />} cursor={{ stroke: C.muted }} />
              <Line isAnimationActive={false} dataKey="field_accuracy" name="Field accuracy" stroke={C.s1} strokeWidth={2} dot={{ r: 3, fill: C.s1, strokeWidth: 0 }} />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Eval calibration error (ECE)" note="Lower is better" empty={evalTrend.length === 0 && "Calibration is measured by each evaluation run."}>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={evalTrend} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid vertical={false} stroke={C.grid} />
              <XAxis dataKey="label" {...axisProps} />
              <YAxis {...axisProps} domain={[0, "auto"]} tickFormatter={(v: number) => v.toFixed(2)} />
              <Tooltip content={<ChartTooltip format={(v) => v.toFixed(3)} />} cursor={{ stroke: C.muted }} />
              <Line isAnimationActive={false} dataKey="ece" name="ECE" stroke={C.s2} strokeWidth={2} dot={{ r: 3, fill: C.s2, strokeWidth: 0 }} />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
      {a && (
        <p className="text-xs text-ink-3">
          Impact figures use synthetic assumptions: {formatNumber(a.manual_employee_min + a.manual_finance_min)} min manual handling per claim versus{" "}
          {formatNumber(a.agent_employee_min + a.agent_finance_min)} min with the agent.
        </p>
      )}
    </div>
  );
}
