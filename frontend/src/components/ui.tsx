import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import type { LineStatus, Severity } from "../types";
import { STATUS_LABEL } from "../lib/format";

type Tone = "neutral" | "ok" | "warn" | "bad" | "accent" | "muted";

const TONE: Record<Tone, string> = {
  neutral: "bg-sunken text-ink-2 border-line",
  muted: "bg-transparent text-ink-3 border-line",
  ok: "bg-ok-soft text-ok border-ok/15",
  warn: "bg-warn-soft text-warn border-warn/20",
  bad: "bg-bad-soft text-bad border-bad/15",
  accent: "bg-accent-soft text-accent border-accent/15",
};

export function Pill({ tone = "neutral", children, dot }: { tone?: Tone; children: ReactNode; dot?: boolean }) {
  return (
    <span className={`inline-flex h-5 items-center gap-1.5 whitespace-nowrap rounded border px-1.5 text-2xs font-medium ${TONE[tone]}`}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current opacity-80" aria-hidden />}
      {children}
    </span>
  );
}

const STATUS_TONE: Record<LineStatus, Tone> = {
  processing: "neutral",
  missing_info: "warn",
  flagged: "warn",
  complete: "ok",
  excluded: "muted",
  error: "bad",
};

export function StatusPill({ status, blocked }: { status: LineStatus; blocked?: boolean }) {
  const tone = blocked && status === "flagged" ? "bad" : STATUS_TONE[status];
  return (
    <Pill tone={tone} dot>
      {blocked && status === "flagged" ? "Blocked" : STATUS_LABEL[status]}
    </Pill>
  );
}

export const SEVERITY_TONE: Record<Severity, Tone> = { info: "neutral", warn: "warn", block: "bad" };
export const SEVERITY_LABEL: Record<Severity, string> = { info: "Info", warn: "Warning", block: "Blocking" };

export function Drawer({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40">
      <div className="absolute inset-0 bg-ink/10" onClick={onClose} aria-hidden />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        className="animate-drawer absolute inset-y-0 right-0 flex w-full max-w-[440px] flex-col border-l border-line bg-surface shadow-pop outline-none"
      >
        <div className="flex h-14 shrink-0 items-center justify-between border-b border-line px-5">
          <div className="text-md font-medium">{title}</div>
          <button className="btn-ghost h-8 w-8 px-0" onClick={onClose} aria-label="Close">
            <X size={16} strokeWidth={1.5} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-5">{children}</div>
      </div>
    </div>
  );
}

export function Spinner({ size = 14 }: { size?: number }) {
  return (
    <span
      className="inline-block animate-spin rounded-full border-[1.5px] border-line-strong border-t-accent"
      style={{ width: size, height: size }}
      aria-hidden
    />
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="px-6 py-10 text-center">
      <div className="text-sm font-medium text-ink-2">{title}</div>
      {children && <div className="mt-1 text-sm text-ink-3">{children}</div>}
    </div>
  );
}
