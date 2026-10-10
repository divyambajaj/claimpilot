import { useEffect, useState } from "react";
import { Activity, FileText, FlaskConical, LayoutGrid, ListChecks } from "lucide-react";
import { Overview } from "../components/admin/Overview";
import { TraceViewer } from "../components/admin/TraceViewer";
import { AuditTrail } from "../components/admin/AuditTrail";
import { EvalPanel } from "../components/admin/EvalPanel";
import { PolicyEditor } from "../components/admin/PolicyEditor";

const TABS = [
  { id: "overview", label: "Overview", icon: LayoutGrid, blurb: "Volume, cost, latency and impact over the last 30 days." },
  { id: "traces", label: "Traces", icon: Activity, blurb: "Every pipeline step recorded as a span, with tokens and cost." },
  { id: "audit", label: "Audit trail", icon: ListChecks, blurb: "Every finding with the rule, the policy sentence and how it was resolved." },
  { id: "eval", label: "Evaluation", icon: FlaskConical, blurb: "Accuracy and calibration on synthetic receipts with ground truth." },
  { id: "policy", label: "Policy", icon: FileText, blurb: "Policy text compiled into deterministic rules, each citing its source sentence." },
] as const;
type TabId = (typeof TABS)[number]["id"];

const tabOf = (): TabId => {
  const t = window.location.hash.split("/")[2];
  return TABS.some((x) => x.id === t) ? (t as TabId) : "overview";
};

export function AdminPage() {
  const [tab, setTab] = useState<TabId>(tabOf);
  useEffect(() => {
    const on = () => setTab(tabOf());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const current = TABS.find((t) => t.id === tab)!;

  return (
    <div className="flex min-h-0 flex-1 flex-col md:flex-row">
      <nav aria-label="Admin" className="shrink-0 border-b border-line bg-surface md:w-52 md:border-b-0 md:border-r">
        <ul className="no-scrollbar flex gap-1 overflow-x-auto px-3 py-2 md:flex-col md:px-3 md:py-4">
          {TABS.map(({ id, label, icon: Icon }) => (
            <li key={id}>
              <a
                href={`#/admin/${id}`}
                aria-current={tab === id ? "page" : undefined}
                className={`flex h-8 items-center gap-2 whitespace-nowrap rounded-md px-2.5 text-sm ${tab === id ? "bg-sunken text-ink" : "text-ink-2 hover:bg-page hover:text-ink"}`}
              >
                <Icon size={16} strokeWidth={1.5} className={tab === id ? "text-ink" : "text-ink-3"} />
                {label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[1280px] px-4 py-6 sm:px-8 sm:py-8">
          <header className="mb-6">
            <h1 className="text-xl font-medium tracking-[-0.01em] text-ink">{current.label}</h1>
            <p className="mt-1 text-sm text-ink-3">{current.blurb}</p>
          </header>
          {tab === "overview" && <Overview />}
          {tab === "traces" && <TraceViewer />}
          {tab === "audit" && <AuditTrail />}
          {tab === "eval" && <EvalPanel />}
          {tab === "policy" && <PolicyEditor />}
        </div>
      </div>
    </div>
  );
}
