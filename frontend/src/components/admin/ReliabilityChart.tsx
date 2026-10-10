import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ReliabilityBin } from "../../types";
import { formatPct } from "../../lib/format";
import { C, ChartTooltip, LegendDot, axisProps } from "./chart";

export function ReliabilityChart({ bins }: { bins: ReliabilityBin[] }) {
  const data = bins.map((b) => ({ ...b, label: `${b.lo.toFixed(1)}`, perfect: (b.lo + b.hi) / 2, accuracy: b.count ? b.accuracy : null }));
  return (
    <div>
      <div className="mb-2 flex gap-4">
        <LegendDot color={C.s1} label="Observed accuracy" />
        <LegendDot color={C.axis} label="Perfect calibration" line />
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -16 }} barCategoryGap={2}>
          <CartesianGrid vertical={false} stroke={C.grid} />
          <XAxis dataKey="label" {...axisProps} />
          <YAxis {...axisProps} domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tickFormatter={(v: number) => formatPct(v)} />
          <Tooltip
            content={<ChartTooltip labelFormat={(l) => `Confidence ${l}–${(Number(l) + 0.1).toFixed(1)}`} format={(v) => formatPct(v, 1)} />}
            cursor={{ fill: "#F4F3EF" }}
          />
          <Bar isAnimationActive={false} dataKey="accuracy" name="Accuracy" fill={C.s1} radius={[3, 3, 0, 0]} />
          <Line isAnimationActive={false} dataKey="perfect" name="Perfect" stroke={C.axis} strokeDasharray="4 3" strokeWidth={1.5} dot={false} activeDot={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="mt-1 text-center text-2xs text-ink-3">Model confidence (bin lower bound)</p>
    </div>
  );
}
