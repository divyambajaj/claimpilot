import type { Rule } from "../../types";
import { CATEGORY_LABEL, fieldLabel, formatINR } from "../../lib/format";
import { Pill, SEVERITY_LABEL, SEVERITY_TONE } from "../ui";

export function describeAction(r: Rule): string {
  const a = r.action;
  switch (a.type) {
    case "cap":
      return `Cap at ${formatINR(a.cap_inr ?? 0, { decimals: false })}${a.cap_basis === "per_person" ? " per person" : a.cap_basis === "line" ? " per line" : a.cap_basis ? ` (${a.cap_basis.replace(/_/g, " ")})` : ""}`;
    case "require_field":
      return `Require ${fieldLabel(a.field ?? "field")}`;
    case "require_justification":
      return "Require justification";
    case "block":
      return "Block";
    case "flag":
      return "Flag for review";
    case "set_category":
      return "Set category";
  }
}

interface Props {
  rules: Rule[];
  active: string | null;
  onHover: (id: string | null) => void;
}

export function RuleTable({ rules, active, onHover }: Props) {
  return (
    <div className="card overflow-x-auto">
      <table className="w-full min-w-[600px] text-xs">
        <thead className="border-b border-line bg-page text-ink-3">
          <tr>
            {["Rule", "Action", "Severity", "Citation", "Conf."].map((h, i) => (
              <th key={h} scope="col" className={`px-3 py-2 font-medium ${i === 4 ? "text-right" : "text-left"}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rules.map((r) => (
            <tr
              key={r.id}
              onMouseEnter={() => onHover(r.id)}
              onMouseLeave={() => onHover(null)}
              onFocus={() => onHover(r.id)}
              tabIndex={0}
              className={`align-top outline-none ${active === r.id ? "bg-accent-soft/60" : "hover:bg-page"}`}
            >
              <td className="px-3 py-2">
                <div className="text-ink">{r.title}</div>
                <div className="mono text-2xs text-ink-3">{r.id}</div>
                <div className="text-2xs text-ink-3">{r.category === "any" ? "Any category" : CATEGORY_LABEL[r.category]} · {r.scope.replace("_", " ")}</div>
              </td>
              <td className="px-3 py-2 text-ink">{describeAction(r)}</td>
              <td className="px-3 py-2"><Pill tone={SEVERITY_TONE[r.severity]}>{SEVERITY_LABEL[r.severity]}</Pill></td>
              <td className="max-w-[240px] px-3 py-2 text-ink-2">
                <span className="text-ink-3">§ {r.citation.section}</span>
                <div className="line-clamp-2">“{r.citation.quote}”</div>
                {r.citation.citation_verified === false && <div className="text-2xs text-warn">Approximate match</div>}
              </td>
              <td className={`mono px-3 py-2 text-right ${r.confidence < 0.8 ? "text-warn" : "text-ink"}`}>{Math.round(r.confidence * 100)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
