import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Search } from "lucide-react";
import { api } from "../../api/client";
import type { AuditRow, Severity, Ticket } from "../../types";
import { formatDateTime, formatINR } from "../../lib/format";
import { Pill, SEVERITY_LABEL, SEVERITY_TONE, Spinner } from "../ui";

type Key = "created_at" | "claim_title" | "vendor" | "amount_inr" | "rule_title" | "severity" | "resolution";
const SEV_RANK: Record<Severity, number> = { info: 0, warn: 1, block: 2 };

export function AuditTrail() {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [q, setQ] = useState("");
  const [sev, setSev] = useState<Severity | "all">("all");
  const [sort, setSort] = useState<{ key: Key; dir: 1 | -1 }>({ key: "created_at", dir: -1 });

  useEffect(() => {
    api.audit().then(setRows);
    api.tickets().then(setTickets).catch(() => setTickets([]));
  }, []);

  const view = useMemo(() => {
    if (!rows) return [];
    const needle = q.trim().toLowerCase();
    return rows
      .filter((r) => (sev === "all" || r.severity === sev) && (!needle || [r.claim_title, r.vendor, r.rule_id, r.rule_title, r.message, r.policy_quote, r.justification].some((v) => v?.toLowerCase().includes(needle))))
      .sort((a, b) => {
        const k = sort.key;
        const av = k === "severity" ? SEV_RANK[a.severity] : a[k] ?? "";
        const bv = k === "severity" ? SEV_RANK[b.severity] : b[k] ?? "";
        return (av < bv ? -1 : av > bv ? 1 : 0) * sort.dir;
      });
  }, [rows, q, sev, sort]);

  if (!rows) return <div className="flex justify-center py-20"><Spinner /></div>;

  const th = (key: Key, label: string, right = false) => (
    <th scope="col" className={`whitespace-nowrap px-3 py-2 font-medium ${right ? "text-right" : "text-left"}`} aria-sort={sort.key === key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      <button type="button" className="inline-flex items-center gap-1 hover:text-ink" onClick={() => setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : 1 }))}>
        {label}
        {sort.key === key && (sort.dir === 1 ? <ArrowUp size={12} strokeWidth={1.5} /> : <ArrowDown size={12} strokeWidth={1.5} />)}
      </button>
    </th>
  );

  return (
    <div className="space-y-3">
      {tickets.length > 0 && <TicketTable tickets={tickets} />}
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative w-full max-w-xs">
          <Search size={14} strokeWidth={1.5} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3" />
          <input className="input pl-8" placeholder="Search claim, vendor, rule, quote" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search findings" />
        </label>
        <div className="inline-flex rounded-md border border-line bg-surface p-0.5" role="group" aria-label="Severity">
          {(["all", "block", "warn", "info"] as const).map((s) => (
            <button key={s} type="button" onClick={() => setSev(s)} className={`h-7 rounded px-2.5 text-xs ${sev === s ? "bg-sunken text-ink" : "text-ink-3 hover:text-ink"}`} aria-pressed={sev === s}>
              {s === "all" ? "All" : SEVERITY_LABEL[s]}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-ink-3">{view.length} of {rows.length} findings</span>
      </div>
      <div className="card overflow-x-auto">
        <table className="w-full min-w-[1100px] text-xs">
          <thead className="border-b border-line bg-page text-ink-3">
            <tr>
              {th("created_at", "When")}
              {th("claim_title", "Claim")}
              {th("vendor", "Line")}
              {th("amount_inr", "Amount", true)}
              {th("rule_title", "Rule")}
              {th("severity", "Severity")}
              <th scope="col" className="px-3 py-2 text-left font-medium">Policy</th>
              <th scope="col" className="px-3 py-2 text-left font-medium">Source</th>
              {th("resolution", "Resolution")}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {view.map((r) => (
              <tr key={r.finding_id} className="align-top hover:bg-page/70">
                <td className="mono whitespace-nowrap px-3 py-2 text-ink-3">{formatDateTime(r.created_at)}</td>
                <td className="max-w-[160px] px-3 py-2 text-ink"><div className="truncate">{r.claim_title}</div><div className="mono text-2xs text-ink-3">{r.claim_id}</div></td>
                <td className="max-w-[130px] truncate px-3 py-2 text-ink-2">{r.vendor ?? "—"}</td>
                <td className="mono whitespace-nowrap px-3 py-2 text-right text-ink">{formatINR(r.amount_inr)}</td>
                <td className="max-w-[180px] px-3 py-2">
                  <div className={r.rule_title ? "text-ink" : "line-clamp-2 text-ink-2"}>{r.rule_title ?? r.message}</div>
                  {r.rule_id && <div className="mono text-2xs text-ink-3">{r.rule_id}</div>}
                </td>
                <td className="px-3 py-2"><Pill tone={SEVERITY_TONE[r.severity]}>{SEVERITY_LABEL[r.severity]}</Pill></td>
                <td className="min-w-[240px] max-w-[300px] px-3 py-2 text-ink-2">
                  {r.policy_quote ? <span className="line-clamp-2" title={r.policy_quote}>“{r.policy_quote}”</span> : "—"}
                  {r.policy_section && <div className="text-2xs text-ink-3">§ {r.policy_section}</div>}
                </td>
                <td className="mono max-w-[160px] truncate px-3 py-2 text-ink-2" title={r.source_snippet ?? ""}>{r.source_snippet ?? "—"}</td>
                <td className="max-w-[200px] px-3 py-2">
                  <span className={`capitalize ${r.resolution !== "open" ? "text-ink" : r.severity === "info" ? "text-ink-3" : "text-warn"}`}>{r.severity === "info" && r.resolution === "open" ? "Noted" : r.resolution}</span>
                  {r.justification && <div className="line-clamp-2 text-2xs text-ink-3" title={r.justification}>{r.justification}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const TICKET_STATUS: Record<Ticket["status"], string> = { open: "Open", in_review: "In review", resolved: "Resolved" };

/** Employees' requests for a manual review of left-out lines. */
function TicketTable({ tickets }: { tickets: Ticket[] }) {
  return (
    <div className="card overflow-x-auto">
      <h3 className="border-b border-line px-3 py-2 text-xs font-medium text-ink">Tickets</h3>
      <table className="w-full min-w-[800px] text-xs">
        <thead className="border-b border-line bg-page text-ink-3">
          <tr>
            {["Ref", "Claim", "Lines", "Note", "Status", "Created"].map((h) => (
              <th key={h} scope="col" className="whitespace-nowrap px-3 py-2 text-left font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {tickets.map((t) => (
            <tr key={t.id} className="align-top">
              <td className="mono whitespace-nowrap px-3 py-2 text-ink">{t.id}</td>
              <td className="mono whitespace-nowrap px-3 py-2 text-ink-2">{t.claim_id}</td>
              <td className="px-3 py-2 text-ink-2">{t.line_ids.length}</td>
              <td className="max-w-[360px] px-3 py-2 text-ink-2"><span className="line-clamp-2" title={t.reason}>{t.reason}</span></td>
              <td className="px-3 py-2"><Pill tone={t.status === "open" ? "warn" : "neutral"}>{TICKET_STATUS[t.status]}</Pill></td>
              <td className="mono whitespace-nowrap px-3 py-2 text-ink-3">{formatDateTime(t.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
