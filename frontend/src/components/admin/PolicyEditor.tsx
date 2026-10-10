import { Fragment, useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { Policy, Rule, RuleSet } from "../../types";
import { formatDateTime } from "../../lib/format";
import { Pill, Spinner } from "../ui";
import { RuleTable } from "./RuleTable";

interface Mark {
  start: number;
  end: number;
  ids: string[];
  verified: boolean;
}

/** Merge rule citation spans into non-overlapping marks. */
export function citationMarks(rules: Rule[]): Mark[] {
  const spans = rules
    .filter((r) => r.citation.char_end > r.citation.char_start)
    .map((r) => ({ start: r.citation.char_start, end: r.citation.char_end, ids: [r.id], verified: r.citation.citation_verified !== false }))
    .sort((a, b) => a.start - b.start);
  const out: Mark[] = [];
  for (const s of spans) {
    const last = out[out.length - 1];
    if (last && s.start < last.end) {
      last.end = Math.max(last.end, s.end);
      last.ids.push(...s.ids);
      last.verified &&= s.verified;
    } else out.push({ ...s, ids: [...s.ids] });
  }
  return out;
}

function sentenceCoverage(text: string, marks: Mark[]) {
  let total = 0;
  let covered = 0;
  const re = /[^.\n#][^.\n]*\./g;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    const lineStart = text.lastIndexOf("\n", m.index) + 1;
    if (text[lineStart] === "#") continue;
    total++;
    if (marks.some((k) => k.start < m!.index + m![0].length && k.end > m!.index)) covered++;
  }
  return { total, covered };
}

export function PolicyEditor() {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [ruleset, setRuleset] = useState<RuleSet | null>(null);
  const [text, setText] = useState("");
  const [mode, setMode] = useState<"coverage" | "edit">("coverage");
  const [hover, setHover] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  async function load(version?: number) {
    const [p] = await api.policies();
    setPolicy(p);
    setText((t) => t || p.text);
    setRuleset(await (version ? api.ruleset(version) : api.activeRuleset()));
  }
  useEffect(() => {
    load().catch((e: Error) => setMsg({ tone: "bad", text: e.message }));
  }, []);

  const marks = useMemo(() => citationMarks(ruleset?.rules ?? []), [ruleset]);
  const coverage = useMemo(() => sentenceCoverage(policy?.text ?? "", marks), [policy, marks]);

  async function compile() {
    if (!policy) return;
    setBusy(true);
    setMsg(null);
    const started = performance.now();
    try {
      const rs = await api.compilePolicy(policy.name, text);
      await load(rs.version);
      setMode("coverage");
      setMsg({ tone: "ok", text: `Compiled v${rs.version}: ${rs.rules.length} rules in ${((performance.now() - started) / 1000).toFixed(1)} s. Every citation checked against the text.` });
    } catch (e) {
      setMsg({ tone: "bad", text: e instanceof Error ? e.message : "Compile failed" });
    } finally {
      setBusy(false);
    }
  }

  async function activate(v: number) {
    await api.activateRuleset(v);
    await load(v);
  }

  if (!policy || !ruleset) return <div className="flex justify-center py-20"><Spinner /></div>;
  const dirty = text !== policy.text;

  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-ink">{policy.name}</div>
          <div className="mono text-2xs text-ink-3">sha {policy.sha256.slice(0, 12)} · compiled {formatDateTime(ruleset.compiled_at)} · {ruleset.provider}/{ruleset.model} · prompt {ruleset.compiler_prompt_version}</div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <label className="text-xs text-ink-3" htmlFor="rs-version">Ruleset</label>
          <select id="rs-version" className="input h-8 w-auto pr-7 text-xs" value={ruleset.version} onChange={(e) => load(Number(e.target.value))}>
            {policy.ruleset_versions.map((v) => (
              <option key={v} value={v}>v{v}{v === policy.active_ruleset_version ? " (active)" : ""}</option>
            ))}
          </select>
          {ruleset.version !== policy.active_ruleset_version ? (
            <button type="button" className="btn-secondary" onClick={() => activate(ruleset.version)}>Activate</button>
          ) : (
            <Pill tone="ok" dot>Active</Pill>
          )}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <section className="card flex min-h-0 flex-col">
          <header className="flex items-center justify-between border-b border-line px-4 py-2">
            <div className="inline-flex rounded-md border border-line p-0.5" role="tablist">
              {(["coverage", "edit"] as const).map((m) => (
                <button key={m} role="tab" aria-selected={mode === m} type="button" onClick={() => setMode(m)} className={`h-7 rounded px-2.5 text-xs ${mode === m ? "bg-sunken text-ink" : "text-ink-3 hover:text-ink"}`}>
                  {m === "coverage" ? "Coverage" : "Edit text"}
                </button>
              ))}
            </div>
            <button type="button" className="btn-primary" onClick={compile} disabled={busy}>
              {busy && <Spinner size={12} />} {busy ? "Compiling…" : "Compile"}
            </button>
          </header>
          {mode === "edit" ? (
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              spellCheck={false}
              className="mono h-[560px] w-full resize-none bg-surface px-4 py-3 text-xs leading-5 text-ink outline-none"
              aria-label="Policy text"
            />
          ) : (
            <div className="h-[560px] overflow-y-auto px-4 py-3">
              <PolicyText text={policy.text} marks={marks} hover={hover} onHover={setHover} />
            </div>
          )}
          <footer className="flex items-center justify-between gap-3 border-t border-line px-4 py-2 text-xs">
            {msg ? (
              <span className={msg.tone === "bad" ? "text-bad" : "text-ok"} role="status">{msg.text}</span>
            ) : mode === "edit" ? (
              <span className="text-ink-3">{dirty ? "Edited. Compile to produce a new ruleset version." : "Plain text or Markdown."}</span>
            ) : (
              <span className="text-ink-3">
                <span className="mono text-ink">{coverage.covered}</span> of {coverage.total} sentences produced a rule. Unhighlighted text has no rule.
              </span>
            )}
          </footer>
        </section>

        <div className="min-w-0 space-y-2">
          <div className="flex items-baseline justify-between">
            <h3 className="text-sm font-medium text-ink">{ruleset.rules.length} rules</h3>
            <span className="text-2xs text-ink-3">Hover a rule to find its sentence</span>
          </div>
          <RuleTable rules={ruleset.rules} active={hover} onHover={setHover} />
        </div>
      </div>
    </div>
  );
}

function PolicyText({ text, marks, hover, onHover }: { text: string; marks: Mark[]; hover: string | null; onHover: (id: string | null) => void }) {
  let offset = 0;
  return (
    <div className="space-y-1 text-sm leading-6 text-ink-2">
      {text.split("\n").map((line, i) => {
        const start = offset;
        offset += line.length + 1;
        if (!line.trim()) return null;
        const h = /^(#+)\s*/.exec(line);
        if (h) {
          const level = h[1].length;
          return (
            <div key={i} className={level === 1 ? "pb-1 text-md font-medium text-ink" : level === 2 ? "pt-3 text-sm font-medium text-ink" : "pt-1 text-xs font-medium text-ink-3"}>
              {line.slice(h[0].length)}
            </div>
          );
        }
        const end = start + line.length;
        const parts: { s: number; e: number; mark?: Mark }[] = [];
        let cur = start;
        for (const m of marks) {
          if (m.end <= start || m.start >= end) continue;
          const ms = Math.max(m.start, start);
          if (ms > cur) parts.push({ s: cur, e: ms });
          parts.push({ s: ms, e: Math.min(m.end, end), mark: m });
          cur = Math.min(m.end, end);
        }
        if (cur < end) parts.push({ s: cur, e: end });
        return (
          <p key={i}>
            {parts.map((p, j) =>
              p.mark ? (
                <mark
                  key={j}
                  onMouseEnter={() => onHover(p.mark!.ids[0])}
                  onMouseLeave={() => onHover(null)}
                  title={p.mark.ids.join(", ")}
                  className={`rounded-[2px] px-0.5 text-ink transition-colors ${p.mark.verified ? (hover && p.mark.ids.includes(hover) ? "bg-accent/20" : "bg-accent-soft") : "bg-warn-soft"} underline decoration-accent/40 underline-offset-4`}
                >
                  {text.slice(p.s, p.e)}
                </mark>
              ) : (
                <Fragment key={j}>{text.slice(p.s, p.e)}</Fragment>
              ),
            )}
          </p>
        );
      })}
    </div>
  );
}
