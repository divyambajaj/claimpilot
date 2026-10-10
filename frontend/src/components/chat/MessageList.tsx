import type { ReactNode } from "react";
import type { AnswerIn, Question } from "../../types";
import { ProgressBubble, type DocProgress } from "./ProgressBubble";
import { QuestionForm } from "./QuestionForm";

export type Message =
  | { id: string; kind: "user"; text: string; files?: string[] }
  | { id: string; kind: "assistant"; text: ReactNode; tone?: "default" | "error" | "ok" }
  | { id: string; kind: "progress"; docs: DocProgress[] }
  | { id: string; kind: "questions"; questions: Question[]; answered: boolean };

interface Props {
  messages: Message[];
  onAnswer: (messageId: string, answers: AnswerIn[]) => Promise<void>;
  answerError: string | null;
  /** Questions still open on the claim; ones resolved elsewhere (Why drawer, field edit) drop out of the form. */
  openIds: Set<string>;
}

export function MessageList({ messages, onAnswer, answerError, openIds }: Props) {
  return (
    <ol className="space-y-5" aria-live="polite">
      {messages.map((m) => (
        <li key={m.id} className="animate-in">
          {m.kind === "user" && (
            <div className="flex justify-end">
              <div className="max-w-[85%] rounded-lg bg-sunken px-3.5 py-2.5 text-sm text-ink">
                <p>{m.text}</p>
                {m.files && m.files.length > 0 && (
                  <ul className="mt-1.5 flex flex-wrap gap-1">
                    {m.files.slice(0, 6).map((f) => (
                      <li key={f} className="mono rounded border border-line bg-surface px-1.5 py-0.5 text-2xs text-ink-2">{f}</li>
                    ))}
                    {m.files.length > 6 && <li className="px-1 text-2xs text-ink-3">+{m.files.length - 6} more</li>}
                  </ul>
                )}
              </div>
            </div>
          )}
          {m.kind === "assistant" && (
            <div className="max-w-[92%]">
              <div className="mb-1 text-2xs font-medium text-ink-3">ClaimPilot</div>
              <div className={`text-md leading-6 ${m.tone === "error" ? "text-bad" : "text-ink"}`}>{m.text}</div>
            </div>
          )}
          {m.kind === "progress" && <ProgressBubble docs={m.docs} />}
          {m.kind === "questions" &&
            (() => {
              const live = m.questions.filter((q) => openIds.has(q.id));
              return m.answered || !live.length ? (
                <div className="rounded-lg border border-line px-4 py-3 text-sm text-ink-3">
                  {m.answered ? (m.questions.length === 1 ? "1 question answered." : `${m.questions.length} questions answered.`) : "Resolved in the claim panel."}
                </div>
              ) : (
                <QuestionForm questions={live} onSubmit={(a) => onAnswer(m.id, a)} error={answerError} />
              );
            })()}
        </li>
      ))}
    </ol>
  );
}
