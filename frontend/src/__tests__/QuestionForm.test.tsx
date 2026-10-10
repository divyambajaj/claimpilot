import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QuestionForm, answerLabel } from "../components/chat/QuestionForm";
import type { Question } from "../types";

const q = (over: Partial<Question>): Question => ({ id: "q", line_id: "l", field: "x", prompt: "?", kind: "value", choices: null, voi_score: 0.5, reason: "r", ...over });

const QS: Question[] = [
  q({ id: "q1", field: "attendees_count", prompt: "How many people were at the dinner?", reason: "Affects reimbursable amount" }),
  q({ id: "q2", field: "date", prompt: "What date is on the fuel bill?", reason: "Required by policy 6.2" }),
  q({ id: "q3", field: "duplicate", kind: "confirm_duplicate", prompt: "Same ride?", choices: ["Same ride, drop it", "Different ride, keep both"], reason: "Would add ₹486" }),
];

describe("QuestionForm", () => {
  it("renders each question with its reason and a fitting input", () => {
    render(<QuestionForm questions={QS} onSubmit={() => {}} />);
    expect(screen.getByText("Affects reimbursable amount")).toBeInTheDocument();
    expect(screen.getByLabelText("How many people were at the dinner?")).toHaveAttribute("type", "number");
    expect(screen.getByLabelText("What date is on the fuel bill?")).toHaveAttribute("type", "date");
    expect(screen.getAllByRole("radio")).toHaveLength(2);
  });

  it("enables submit only when all are answered and sends typed values", async () => {
    const onSubmit = vi.fn();
    render(<QuestionForm questions={QS} onSubmit={onSubmit} />);
    const send = screen.getByRole("button", { name: "Send answers" });
    expect(send).toBeDisabled();
    await userEvent.type(screen.getByLabelText("How many people were at the dinner?"), "4");
    fireEvent.change(screen.getByLabelText("What date is on the fuel bill?"), { target: { value: "2026-10-04" } });
    expect(send).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: "Same ride, drop it" }));
    expect(screen.getByText("3 of 3 answered")).toBeInTheDocument();
    await userEvent.click(send);
    expect(onSubmit).toHaveBeenCalledWith([
      { question_id: "q1", value: 4 },
      { question_id: "q2", value: "2026-10-04" },
      { question_id: "q3", value: "confirm" },
    ]);
  });

  it("requires a real justification for flagged lines", async () => {
    render(<QuestionForm questions={[q({ id: "j", kind: "justify_flag", prompt: "Why late?" })]} onSubmit={() => {}} />);
    const box = screen.getByLabelText("Why late?");
    await userEvent.type(box, "ok");
    expect(screen.getByRole("button", { name: "Send answers" })).toBeDisabled();
    await userEvent.type(box, " — receipt was with the travel desk");
    expect(screen.getByRole("button", { name: "Send answers" })).toBeEnabled();
  });

  it("labels answers for the transcript", () => {
    expect(answerLabel(QS[2], "override")).toBe("Different ride, keep both");
    expect(answerLabel(QS[1], "2026-10-04")).toBe("4 Oct 2026");
  });
});
