import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ClaimCard } from "../components/chat/ClaimCard";
import { makeClaim, makeLine } from "./fixtures";

const blocked = makeLine({ id: "x", status: "excluded", reimbursable_inr: 0 }, "paynow-6450");
const ok = makeLine({ id: "ok" });

describe("Raise a ticket", () => {
  it("is offered only for left-out lines", () => {
    render(<ClaimCard claim={makeClaim({ lines: [ok] })} onSubmit={() => {}} onWhy={() => {}} onRaiseTicket={async () => {}} />);
    expect(screen.queryByRole("button", { name: "Raise a ticket with Finance" })).toBeNull();
  });

  it("sends the checked left-out lines and the note, then shows the ticket on the line", async () => {
    const onRaise = vi.fn(async () => {});
    const claim = makeClaim({ lines: [ok, blocked] });
    const { rerender } = render(<ClaimCard claim={claim} onSubmit={() => {}} onWhy={() => {}} onRaiseTicket={onRaise} />);
    await userEvent.click(screen.getByRole("button", { name: "Raise a ticket with Finance" }));
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
    expect(screen.getByRole("checkbox")).toBeChecked();
    await userEvent.type(screen.getByLabelText("Why should Finance review this?"), "Shared cab to the client site.");
    await userEvent.click(screen.getByRole("button", { name: "Submit ticket" }));
    expect(onRaise).toHaveBeenCalledWith(["x"], "Shared cab to the client site.");
    const ticket = { id: "TKT-1042", claim_id: claim.id, line_ids: ["x"], reason: "r", status: "in_review" as const, created_at: "2026-10-10T10:00:00" };
    rerender(<ClaimCard claim={{ ...claim, tickets: [ticket] }} onSubmit={() => {}} onWhy={() => {}} onRaiseTicket={onRaise} />);
    expect(screen.getByTestId("ticket-pill")).toHaveTextContent("Ticket TKT-1042 · In review");
    expect(screen.queryByRole("button", { name: "Raise a ticket with Finance" })).toBeNull();
  });
});
