import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MessageList, type Message } from "../components/chat/MessageList";
import { isSettled } from "../pages/ChatPage";
import type { Finding, Question } from "../types";
import { makeClaim, makeLine } from "./fixtures";

const q = (over: Partial<Question>): Question => ({ id: "q", line_id: "u", field: "x", prompt: "?", kind: "justify_flag", choices: null, voi_score: 0.6, reason: "r", ...over });
const BILL = q({ id: "q:u:BILL_REQUIRED", kind: "attach_document", field: "BILL_REQUIRED", prompt: "Attach the bill", choices: ["I don't have the bill"], finding_id: "u:BILL_REQUIRED" });
const NOTE = q({ id: "q:u:FUEL_TRIP_NOTE", field: "FUEL_TRIP_NOTE", prompt: "Trip note?", finding_id: "u:FUEL_TRIP_NOTE" });
const TRIP = "Drove to the Thane client site and back on 6 Oct for the workshop.";

/** Drafts live above the list, as in ChatPage. */
function Harness(props: { messages: Message[]; open: (q: Question) => boolean; attaching?: string | null; onAttach?: (q: Question) => void; onAnswer?: () => Promise<void> }) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  return (
    <MessageList
      messages={props.messages}
      onAnswer={props.onAnswer ?? (async () => {})}
      answerError={null}
      onAttach={props.onAttach}
      attaching={props.attaching}
      isOpen={props.open}
      drafts={drafts}
      onDraft={(id, v) => setDrafts((s) => ({ ...s, [id]: v }))}
    />
  );
}

describe("MessageList keeps typed answers", () => {
  const form: Message = { id: "m1", kind: "questions", questions: [BILL, NOTE], answered: false };

  it("through an attach upload and new events, and never submits on its own", async () => {
    const onAttach = vi.fn();
    const onAnswer = vi.fn(async () => {});
    const all = () => true;
    const { rerender } = render(<Harness messages={[form]} open={all} onAttach={onAttach} onAnswer={onAnswer} />);
    await userEvent.type(screen.getByLabelText("Trip note?"), TRIP);
    await userEvent.click(screen.getByRole("button", { name: "Attach bill" }));
    expect(onAttach).toHaveBeenCalledWith(BILL);

    rerender(<Harness messages={[form]} open={all} attaching={BILL.id} onAttach={onAttach} onAnswer={onAnswer} />);
    expect(screen.getByRole("button", { name: /Reading the bill/ })).toBeDisabled();
    expect(screen.getByLabelText("Trip note?")).toHaveValue(TRIP);

    // a claim_update re-plan hides the whole form for a moment, then a new round of questions arrives
    const next: Message[] = [form, { id: "m2", kind: "assistant", text: "1 document read." }, { id: "m3", kind: "questions", questions: [q({ id: "q:v:x", line_id: "v", prompt: "Other?" })], answered: false }];
    rerender(<Harness messages={next} open={() => false} onAttach={onAttach} onAnswer={onAnswer} />);
    expect(screen.queryByLabelText("Trip note?")).toBeNull();
    rerender(<Harness messages={next} open={(x) => x.id !== BILL.id} onAttach={onAttach} onAnswer={onAnswer} />);
    expect(screen.getByLabelText("Trip note?")).toHaveValue(TRIP);
    expect(onAnswer).not.toHaveBeenCalled();
  });
});

describe("isSettled", () => {
  const finding = (rule: string, resolution: Finding["resolution"] = "open"): Finding => ({ id: `u:${rule}`, kind: "policy", severity: "warn", rule_id: rule, message: "", citation: null, evidence: {}, resolution });

  it("keeps a question whose finding is still open, even when it is not among the shown three", () => {
    const line = makeLine({ id: "u", findings: [finding("BILL_REQUIRED"), finding("FUEL_TRIP_NOTE")] });
    expect(isSettled(NOTE, makeClaim({ lines: [line], open_questions: [] }))).toBe(false);
  });

  it("retires it once resolved, linked to a bill, or blocked", () => {
    const justified = makeLine({ id: "u", findings: [finding("FUEL_TRIP_NOTE", "justified")] });
    expect(isSettled(NOTE, makeClaim({ lines: [justified] }))).toBe(true);
    const linked = makeLine({ id: "u", linked_to_line_id: "bill", findings: [finding("FUEL_TRIP_NOTE")] });
    expect(isSettled(BILL, makeClaim({ lines: [linked] }))).toBe(true);
    const blocked = makeLine({ id: "u", findings: [finding("FUEL_TRIP_NOTE"), { ...finding("P2P"), severity: "block" }] });
    expect(isSettled(NOTE, makeClaim({ lines: [blocked] }))).toBe(true);
  });
});
