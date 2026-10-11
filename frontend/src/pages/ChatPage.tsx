import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronUp } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { AnswerIn, Claim, ClaimEvent, DemoReceipt, Finding, LineItem, Question, RuleSet } from "../types";
import { formatINR, pluralize } from "../lib/format";
import { afterAnswersText, allLeftOut, ClaimCard, TicketForm } from "../components/chat/ClaimCard";
import { DemoGallery } from "../components/chat/DemoGallery";
import { ACCEPT, DropZone, MAX_BYTES } from "../components/chat/DropZone";
import { MessageList, type Message } from "../components/chat/MessageList";
import { answerLabel } from "../components/chat/QuestionForm";
import { WhyDrawer } from "../components/chat/WhyDrawer";
import { StatusPill } from "../components/ui";

const CLAIM_KEY = "claimpilot.claimId";
/** The open claim survives a page refresh; storage can be unavailable (private mode), which only loses that. */
const savedClaim = {
  get: () => {
    try {
      return localStorage.getItem(CLAIM_KEY);
    } catch {
      return null;
    }
  },
  set: (id: string | null) => {
    try {
      if (id) localStorage.setItem(CLAIM_KEY, id);
      else localStorage.removeItem(CLAIM_KEY);
    } catch {
      /* storage blocked */
    }
  },
};

let mid = 0;
const nextId = () => `m${++mid}-${Math.random().toString(36).slice(2, 7)}`; // random suffix keeps keys unique across HMR reloads

/** "7 documents read. 2 need a detail, 1 looks like a duplicate. …" */
export function summarize(claim: Claim, nDocs: number): string {
  const L = claim.lines;
  const missing = L.filter((l) => l.status === "missing_info").length;
  const isDup = (l: LineItem) => l.findings.some((f) => f.kind === "duplicate" && f.resolution === "open" && f.severity !== "info");
  const isBlocked = (l: LineItem) => l.findings.some((f) => f.severity === "block" && f.resolution === "open");
  const dups = L.filter(isDup).length;
  const blocked = L.filter((l) => isBlocked(l) && !isDup(l)).length;
  const other = L.filter((l) => l.status === "flagged" && !isDup(l) && !isBlocked(l)).length;
  const linked = L.filter((l) => l.linked_proof_line_id);
  const parts: string[] = [];
  if (missing) parts.push(`${missing} ${missing === 1 ? "needs a detail" : "need a detail"}`);
  if (dups) parts.push(`${dups} ${dups === 1 ? "looks like a duplicate" : "look like duplicates"}`);
  if (blocked) parts.push(`${blocked} ${blocked === 1 ? "is blocked by policy" : "are blocked by policy"}`);
  if (other > 0) parts.push(`${other} ${other === 1 ? "needs a justification" : "need a justification"}`);
  let s = `${pluralize(nDocs, "document")} read.`;
  s += parts.length ? ` ${parts.join(", ").replace(/^\w/, (c) => c.toUpperCase())}.` : " Everything checks out against the policy.";
  for (const inv of linked) {
    const upi = L.find((l) => l.id === inv.linked_proof_line_id);
    if (upi) s += ` The ${formatINR(upi.amount_inr, { decimals: false })} UPI payment is attached to the ${inv.extracted.vendor_name.value} invoice as proof, not counted twice.`;
  }
  return s;
}

/** Settled questions leave their form; one that a re-plan merely ranked lower stays, with what was typed. */
export function isSettled(q: Question, claim: Claim): boolean {
  const line = claim.lines.find((l) => l.id === q.line_id);
  if (!line || line.linked_to_line_id || line.user_excluded || line.status === "error") return true;
  if (line.findings.some((f) => f.severity === "block" && f.resolution === "open")) return true; // blocked lines get no questions
  if (q.finding_id) return !line.findings.some((f) => f.id === q.finding_id && f.resolution === "open");
  return (line.extracted as unknown as Record<string, { origin?: string } | undefined>)[q.field]?.origin === "user";
}

export function ChatPage() {
  const [claim, setClaim] = useState<Claim | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [receipts, setReceipts] = useState<DemoReceipt[] | null>(null);
  const [ruleset, setRuleset] = useState<RuleSet | null>(null);
  const [why, setWhy] = useState<{ f: Finding; line: LineItem } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [answerError, setAnswerError] = useState<string | null>(null);
  const [answerErrors, setAnswerErrors] = useState<Record<string, string>>({});
  const attachInput = useRef<HTMLInputElement>(null);
  const attachFor = useRef<Question | null>(null);
  const [attaching, setAttaching] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [sheet, setSheet] = useState(false);
  const submittingRef = useRef(false);

  const claimRef = useRef<Claim | null>(null);
  const progressId = useRef<string | null>(null);
  const asked = useRef(new Set<string>());
  const docCount = useRef(0);
  const unsub = useRef<(() => void) | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  const push = useCallback((...m: Message[]) => setMessages((s) => [...s, ...m]), []);
  const updateClaim = useCallback((c: Claim) => {
    claimRef.current = c;
    setClaim(c);
  }, []);
  const askNew = useCallback(
    (qs: Question[]) => {
      const fresh = qs.filter((q) => !asked.current.has(q.id));
      fresh.forEach((q) => asked.current.add(q.id));
      if (fresh.length) push({ id: nextId(), kind: "questions", questions: fresh, answered: false });
    },
    [push],
  );

  useEffect(() => {
    api.activeRuleset().then(setRuleset).catch(() => setRuleset(null));
    return () => unsub.current?.();
  }, []);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const onEvent = useCallback(
    (e: ClaimEvent) => {
      if (e.type === "stage") {
        const d = e.data;
        const pid = progressId.current; // read now: the updater runs later, after "done" may have cleared it
        setMessages((ms) =>
          ms.map((m) => {
            if (m.kind !== "progress" || m.id !== pid) return m;
            const exists = m.docs.some((x) => x.doc_id === d.doc_id);
            const doc = { doc_id: d.doc_id, filename: d.filename ?? d.doc_id, stage: d.stage, message: d.message };
            return { ...m, docs: exists ? m.docs.map((x) => (x.doc_id === d.doc_id ? { ...x, ...doc, filename: d.filename ?? x.filename } : x)) : [...m.docs, doc] };
          }),
        );
      } else if (e.type === "line_update") {
        const c = claimRef.current;
        if (!c) return;
        const lines = c.lines.some((l) => l.id === e.data.line.id) ? c.lines.map((l) => (l.id === e.data.line.id ? e.data.line : l)) : [...c.lines, e.data.line];
        updateClaim({ ...c, lines });
      } else if (e.type === "claim_update") {
        updateClaim(e.data.claim);
      } else if (e.type === "done") {
        updateClaim(e.data.claim);
        progressId.current = null;
        push({ id: nextId(), kind: "assistant", text: summarize(e.data.claim, docCount.current) });
        askNew(e.data.claim.open_questions);
      } else if (e.type === "question") {
        if (!progressId.current) askNew(e.data.questions);
      } else if (e.type === "error") {
        push({ id: nextId(), kind: "assistant", tone: "error", text: e.data.message });
      }
    },
    [askNew, push, updateClaim],
  );

  /** The stream opens with the current claim; resolves on it so no stage event of the next upload is missed. */
  function subscribe(claimId: string) {
    return new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, 3000);
      unsub.current = api.subscribeClaim(
        claimId,
        (e) => {
          if (e.type === "claim_update") {
            clearTimeout(timer);
            resolve();
          }
          onEvent(e);
        },
        () => push({ id: nextId(), kind: "assistant", tone: "error", text: "Lost the live connection. Refresh to see the latest state." }),
      );
    });
  }

  async function ensureClaim(): Promise<Claim> {
    if (claimRef.current) return claimRef.current;
    const c = await api.createClaim();
    updateClaim(c);
    savedClaim.set(c.id);
    await subscribe(c.id);
    return c;
  }

  function newClaim() {
    unsub.current?.();
    unsub.current = null;
    savedClaim.set(null);
    claimRef.current = null;
    progressId.current = null;
    asked.current.clear();
    setClaim(null);
    setMessages([]);
    setWhy(null);
    setAnswerError(null);
    setAnswerErrors({});
    setDrafts({});
  }

  // Resume the claim this browser was working on (refresh, reopened tab); finished ones start fresh.
  useEffect(() => {
    const id = savedClaim.get();
    if (!id) return;
    api
      .getClaim(id)
      .then((c) => {
        if (claimRef.current) return; // a second effect run (StrictMode) or an upload got there first
        if (c.status === "approved" || c.status === "rejected") return savedClaim.set(null);
        updateClaim(c);
        docCount.current = c.processing ?? 0;
        void subscribe(c.id);
        push({
          id: nextId(),
          kind: "assistant",
          text: (
            <>
                Picked up “{c.title}” where you left it.{" "}
                <button type="button" className="link" onClick={newClaim}>Start a new claim</button>
            </>
          ),
        });
        askNew(c.open_questions);
        if (c.status === "submitted") void awaitDecision(c.id);
      })
      .catch(() => savedClaim.set(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, on mount
  }, []);

  async function startBatch(label: string, names: string[], send: (claimId: string) => Promise<unknown>) {
    const pid = nextId();
    progressId.current = pid;
    docCount.current = names.length;
    push({ id: nextId(), kind: "user", text: label, files: names }, { id: pid, kind: "progress", docs: [] });
    try {
      const c = await ensureClaim();
      await send(c.id);
    } catch (err) {
      progressId.current = null;
      const notInDemo = err instanceof ApiError && err.status === 409;
      setMessages((ms) => ms.filter((m) => m.id !== pid));
      push({
        id: nextId(),
        kind: "assistant",
        tone: "error",
        text: notInDemo ? (
          <>
            This file is not in the recorded demo set, so it cannot be read in demo mode.{" "}
            <button className="link" onClick={() => setGalleryOpen(true)}>Use the sample receipts</button> instead.
          </>
        ) : (
          `Upload failed: ${err instanceof Error ? err.message : "unknown error"}.`
        ),
      });
    }
  }

  const onFiles = (files: File[], skipped: number) =>
    startBatch(`Added ${pluralize(files.length, "file")}${skipped ? ` · ${skipped} skipped (images or PDFs up to 10 MB, 10 at a time)` : ""}`, files.map((f) => f.name), (id) => api.uploadDocuments(id, files));

  const openGallery = () => setGalleryOpen(true);
  useEffect(() => {
    if (galleryOpen && !receipts) api.demoReceipts().then(setReceipts).catch(() => setReceipts([]));
  }, [galleryOpen, receipts]);

  const onSamples = (names: string[]) => {
    setGalleryOpen(false);
    startBatch(`Added ${pluralize(names.length, "sample receipt")}`, names, (id) => api.addDemoDocuments(id, names));
  };

  async function onAnswer(messageId: string, answers: AnswerIn[]) {
    const c = claimRef.current;
    if (!c) return;
    setAnswerError(null);
    setAnswerErrors({});
    const msg = messages.find((m) => m.id === messageId);
    try {
      const updated = await api.answer(c.id, answers);
      updateClaim(updated);
      setMessages((ms) => ms.map((m) => (m.id === messageId && m.kind === "questions" ? { ...m, answered: true } : m)));
      if (msg?.kind === "questions") {
        const text = answers.map((a) => answerLabel(msg.questions.find((q) => q.id === a.question_id)!, a.value)).join(" · ");
        push({ id: nextId(), kind: "user", text });
      }
      const pending = updated.open_questions.filter((q) => !asked.current.has(q.id));
      if (updated.status === "ready_to_submit") {
        push({
          id: nextId(),
          kind: "assistant",
          text: `All lines are complete. ${formatINR(updated.reimbursable_inr)} reimbursable of ${formatINR(updated.total_inr)} claimed. Review the claim and submit when ready.`,
        });
      } else if (pending.length) {
        push({ id: nextId(), kind: "assistant", text: `Thanks. ${pending.length === 1 ? "One more question" : `${pending.length} more questions`}, then the claim is ready.` });
      } else {
        push({ id: nextId(), kind: "assistant", text: afterAnswersText(updated) });
      }
      askNew(updated.open_questions);
    } catch (err) {
      setAnswerError(err instanceof Error ? err.message : "Could not save answers");
      setAnswerErrors(err instanceof ApiError ? err.errors ?? {} : {});
    }
  }

  function onAttach(q: Question) {
    attachFor.current = q;
    attachInput.current?.click();
  }

  /** The bill is read now and linked to this question's payment, or rejected with a reason shown under it. */
  async function attachBill(q: Question, file: File) {
    const c = claimRef.current;
    if (!c) return;
    const setError = (msg?: string) =>
      setAnswerErrors((s) => {
        const { [q.id]: _, ...rest } = s;
        return msg ? { ...rest, [q.id]: msg } : rest;
      });
    if (!(file.type.startsWith("image/") || file.type === "application/pdf") || file.size > MAX_BYTES) return setError("Attach an image or PDF up to 10 MB.");
    setError();
    setAttaching(q.id);
    try {
      await api.uploadDocuments(c.id, [file], q.line_id);
      updateClaim(await api.getClaim(c.id));
    } catch (err) {
      const notInDemo = err instanceof ApiError && err.status === 409;
      setError(notInDemo ? "This file is not in the recorded demo set, so it cannot be read in demo mode." : err instanceof Error ? err.message : "Could not attach the bill.");
    } finally {
      setAttaching(null);
    }
  }

  /** Finance decides asynchronously (mock: ~20 s); poll a few times so the decision lands in the chat. */
  async function awaitDecision(claimId: string) {
    for (let i = 0; i < 8; i++) {
      await new Promise((r) => setTimeout(r, 5000));
      const c = await api.getClaim(claimId).catch(() => null);
      if (claimRef.current?.id !== claimId) return;
      if (c && (c.status === "approved" || c.status === "rejected")) {
        updateClaim(c);
        push(
          c.status === "approved"
            ? { id: nextId(), kind: "assistant", tone: "ok", text: `Finance approved ${c.finance_reference} for ${formatINR(c.reimbursable_inr)}.` }
            : { id: nextId(), kind: "assistant", tone: "error", text: `Finance rejected ${c.finance_reference}.` },
        );
        return;
      }
    }
  }

  /** Raise errors to the form (422/409 shown under the note); success lands in the chat, status via polling. */
  async function onRaiseTicket(lineIds: string[], note: string) {
    const c = claimRef.current;
    if (!c) return;
    const ticket = await api.raiseTicket(c.id, lineIds, note);
    updateClaim(await api.getClaim(c.id).catch(() => ({ ...c, tickets: [...(c.tickets ?? []), ticket] })));
    push({ id: nextId(), kind: "assistant", tone: "ok", text: `Ticket ${ticket.id} raised for ${pluralize(ticket.line_ids.length, "line")}. Finance will review it — you'll see the status here.` });
    void awaitTicket(c.id, ticket.id);
  }

  async function awaitTicket(claimId: string, ticketId: string) {
    for (let i = 0; i < 8; i++) {
      await new Promise((r) => setTimeout(r, 5000));
      const fresh = await api.getClaim(claimId).catch(() => null);
      if (claimRef.current?.id !== claimId) return;
      if (fresh) updateClaim(fresh);
      if (fresh && fresh.tickets?.find((t) => t.id === ticketId)?.status !== "open") return;
    }
  }

  /** Apply a change made in the claim panel and surface what it unlocked. */
  async function change(fn: (claimId: string) => Promise<Claim>) {
    const c = claimRef.current;
    if (!c) return;
    const updated = await fn(c.id);
    updateClaim(updated);
    askNew(updated.open_questions);
    if (c.status !== "ready_to_submit" && updated.status === "ready_to_submit")
      push({ id: nextId(), kind: "assistant", text: `All lines are complete. ${formatINR(updated.reimbursable_inr)} reimbursable of ${formatINR(updated.total_inr)} claimed. Review the claim and submit when ready.` });
  }
  const failed = (err: unknown) =>
    push({ id: nextId(), kind: "assistant", tone: "error", text: `Could not update the line: ${err instanceof Error ? err.message : "unknown error"}.` });

  async function onLineAction(action: "override_duplicate" | "confirm_duplicate") {
    if (!why) return;
    try {
      await change((id) => api.lineAction(id, why.line.id, action));
      setWhy(null);
    } catch (err) {
      failed(err);
    }
  }

  const onExclude = (line: LineItem, action: "exclude" | "restore") => change((id) => api.lineAction(id, line.id, action)).catch(failed);
  const onEdit = (line: LineItem, field: string, value: string) => change((id) => api.editLine(id, line.id, { [field]: value })); // errors show in the field popover

  async function onSubmit() {
    const c = claimRef.current;
    if (!c || submittingRef.current) return; // a double click must not send twice
    submittingRef.current = true;
    setSubmitting(true);
    try {
      const { finance_reference } = await api.submit(c.id);
      const fresh = await api.getClaim(c.id).catch(() => ({ ...c, status: "submitted" as const, finance_reference, submitted_at: new Date().toISOString() }));
      updateClaim(fresh);
      push({ id: nextId(), kind: "assistant", tone: "ok", text: `Submitted to Finance. Reference ${finance_reference}. You will see the approval here once it is processed.` });
      void awaitDecision(c.id);
    } catch (err) {
      push({ id: nextId(), kind: "assistant", tone: "error", text: `Could not submit: ${err instanceof Error ? err.message : "unknown error"}.` });
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  }

  const rule = why?.f.rule_id ? ruleset?.rules.find((r) => r.id === why.f.rule_id) : undefined;
  const started = messages.length > 0;
  const processing = progressId.current !== null;
  const submitted = claim?.status === "submitted" || claim?.status === "approved" || claim?.status === "rejected";
  const panel = claim ? (
    <ClaimCard claim={claim} onSubmit={onSubmit} submitting={submitting} onWhy={(f, line) => setWhy({ f, line })} onEdit={onEdit} onExclude={onExclude} onRaiseTicket={onRaiseTicket} />
  ) : (
    <section className="card">
      <header className="border-b border-line px-4 py-3.5">
        <h2 className="text-md font-medium text-ink">Your claim</h2>
        <p className="mt-0.5 text-xs text-ink-3">No receipts yet</p>
      </header>
      <div className="px-4 py-10 text-center text-sm text-ink-3">Line items appear here as receipts are read.</div>
    </section>
  );

  return (
    <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1fr)_440px]">
      <div className="flex min-h-0 flex-col">
        <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[680px] px-4 pb-6 pt-8 sm:px-6 sm:pt-12">
            {!started ? (
              <div className="animate-in">
                <h1 className="text-2xl font-medium tracking-[-0.01em] text-ink">Turn a pile of receipts into a claim.</h1>
                <p className="mt-2 max-w-[520px] text-md text-ink-2">
                  Add photos, PDFs or UPI screenshots. ClaimPilot reads each one, checks it against the travel policy, and asks only what would change the outcome.
                </p>
                <div className="mt-8">
                  <DropZone onFiles={onFiles} onSamples={openGallery} />
                </div>
                <dl className="mt-8 grid gap-5 border-t border-line pt-6 text-sm sm:grid-cols-3">
                  {[
                    ["Every field has a source", "Tap any value to see the text it was read from and how sure the model was."],
                    ["Rules quote the policy", "Flags link to the exact policy sentence that produced them."],
                    ["No double claims", "Re-uploads and re-photographed bills are caught; UPI proofs attach to their invoice."],
                  ].map(([t, d]) => (
                    <div key={t}>
                      <dt className="font-medium text-ink">{t}</dt>
                      <dd className="mt-1 text-ink-3">{d}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ) : (
              <>
              <MessageList
                messages={messages}
                onAnswer={onAnswer}
                answerError={answerError}
                answerErrors={answerErrors}
                onAttach={onAttach}
                attaching={attaching}
                isOpen={(q) => !!claim && (claim.open_questions.some((o) => o.id === q.id) || !isSettled(q, claim))}
                drafts={drafts}
                onDraft={(id, v) => setDrafts((s) => ({ ...s, [id]: v }))}
              />
              {claim && !processing && allLeftOut(claim) && <TicketForm claim={claim} onRaise={onRaiseTicket} />}
              <input
                ref={attachInput}
                type="file"
                accept={ACCEPT}
                className="sr-only"
                tabIndex={-1}
                aria-hidden
                data-testid="attach-input"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file && attachFor.current) void attachBill(attachFor.current, file);
                  e.target.value = "";
                }}
              />
              </>
            )}
          </div>
        </div>
        {started && (
          <div className="border-t border-line bg-page px-4 py-3 sm:px-6">
            <div className="mx-auto max-w-[680px]">
              {submitted ? (
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm text-ink-3">{claim?.status === "submitted" ? "This claim is with Finance." : "Finance has decided this claim."}</span>
                  <button type="button" className="btn-secondary" onClick={newClaim}>Start a new claim</button>
                </div>
              ) : (
                <DropZone compact onFiles={onFiles} onSamples={openGallery} disabled={processing} />
              )}
            </div>
          </div>
        )}
        {claim && (
          <button
            type="button"
            onClick={() => setSheet(true)}
            className="flex items-center gap-3 border-t border-line bg-surface px-4 py-3 text-left lg:hidden"
            aria-label="Open claim"
          >
            <span className="min-w-0 flex-1">
              <span className="block text-xs text-ink-3">{pluralize(claim.lines.filter((l) => !l.linked_to_line_id).length, "line")} · Reimbursable</span>
              <span className="mono block text-md font-medium text-ink">{formatINR(claim.reimbursable_inr)}</span>
            </span>
            {claim.status === "ready_to_submit" ? <StatusPill status="complete" /> : claim.open_questions.length ? <StatusPill status="missing_info" /> : null}
            <span className="btn-secondary">
              View claim <ChevronUp size={14} strokeWidth={1.5} />
            </span>
          </button>
        )}
      </div>

      <aside className="hidden min-h-0 flex-col border-l border-line bg-page p-5 lg:flex">
        <div className="flex min-h-0 flex-col [&>section]:max-h-full">{panel}</div>
      </aside>

      {sheet && claim && (
        <div className="fixed inset-0 z-30 flex flex-col bg-page lg:hidden" role="dialog" aria-modal="true" aria-label="Claim">
          <div className="flex h-12 shrink-0 items-center justify-between border-b border-line px-4">
            <span className="text-sm font-medium">Claim</span>
            <button className="btn-ghost" onClick={() => setSheet(false)}>Done</button>
          </div>
          <div className="flex min-h-0 flex-1 flex-col p-3 [&>section]:max-h-full">{panel}</div>
        </div>
      )}

      <DemoGallery
        open={galleryOpen}
        receipts={receipts}
        onClose={() => setGalleryOpen(false)}
        onAdd={onSamples}
      />
      <WhyDrawer
        finding={why?.f ?? null}
        line={why?.line ?? null}
        lines={claim?.lines ?? []}
        rule={rule}
        onClose={() => setWhy(null)}
        onAction={submitted ? undefined : onLineAction}
      />
    </div>
  );
}
