import type { ReactNode } from "react";

export function KpiTile({ label, value, note, tone }: { label: string; value: ReactNode; note?: ReactNode; tone?: "ok" | "bad" }) {
  return (
    <div className="bg-surface px-4 py-3.5">
      <div className="text-xs text-ink-3">{label}</div>
      <div className={`mono mt-1.5 text-xl font-medium tracking-[-0.02em] ${tone === "bad" ? "text-bad" : tone === "ok" ? "text-ok" : "text-ink"}`}>{value}</div>
      {note && <div className="mt-0.5 text-2xs text-ink-3">{note}</div>}
    </div>
  );
}

/** Tiles share hairline dividers instead of separate boxed cards. */
export function KpiGrid({ children, cols = "grid-cols-2 sm:grid-cols-3 xl:grid-cols-5" }: { children: ReactNode; cols?: string }) {
  return <div className={`grid gap-px overflow-hidden rounded-lg border border-line bg-line ${cols}`}>{children}</div>;
}
