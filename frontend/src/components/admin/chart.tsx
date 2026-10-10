import type { ReactNode } from "react";

/** Validated with the dataviz palette checker (light surface): lightness, chroma, CVD and contrast all pass. */
export const C = {
  s1: "#00806A",
  s2: "#BF8233",
  grid: "#ECEAE5",
  axis: "#8C887E",
  ink: "#1A1A17",
  muted: "#D6D3CC",
};

export const axisProps = {
  tickLine: false,
  axisLine: false,
  tick: { fontSize: 11, fill: C.axis },
} as const;

export function ChartCard({ title, note, legend, children, className = "" }: { title: string; note?: ReactNode; legend?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card p-4 ${className}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-ink">{title}</h3>
          {note && <p className="mt-0.5 text-xs text-ink-3">{note}</p>}
        </div>
        {legend}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function LegendDot({ color, label, line }: { color: string; label: string; line?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-2xs text-ink-2">
      <span className={line ? "h-0.5 w-3 rounded" : "h-2 w-2 rounded-sm"} style={{ background: color }} aria-hidden />
      {label}
    </span>
  );
}

interface TipProps {
  active?: boolean;
  label?: string | number;
  payload?: { name?: string; value?: number | string; color?: string; dataKey?: string | number }[];
  format?: (v: number, key?: string) => string;
  labelFormat?: (l: string) => string;
}

export function ChartTooltip({ active, payload, label, format, labelFormat }: TipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-line bg-surface px-2.5 py-2 text-xs shadow-pop">
      {label !== undefined && <div className="mb-1 text-ink-3">{labelFormat ? labelFormat(String(label)) : label}</div>}
      {payload.map((p) => (
        <div key={String(p.dataKey)} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-sm" style={{ background: p.color }} aria-hidden />
          <span className="text-ink-2">{p.name}</span>
          <span className="mono ml-auto pl-3 text-ink">{format ? format(Number(p.value), String(p.dataKey)) : p.value}</span>
        </div>
      ))}
    </div>
  );
}
