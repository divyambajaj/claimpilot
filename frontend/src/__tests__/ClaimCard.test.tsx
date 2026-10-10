import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ClaimCard } from "../components/chat/ClaimCard";
import { formatINR } from "../lib/format";
import { makeClaim, makeLine } from "./fixtures";

describe("ClaimCard", () => {
  it("lists lines with status pills and disables submit while questions are open", () => {
    const meal = makeLine({ id: "l1", status: "missing_info" }, "saffron-table-dinner");
    const ride = makeLine({ id: "l2" });
    const claim = makeClaim({ lines: [meal, ride], total_inr: 4346, reimbursable_inr: 1986, open_questions: [{ id: "q", line_id: "l1", field: "attendees_count", prompt: "", kind: "value", choices: null, voi_score: 1, reason: "" }] });
    render(<ClaimCard claim={claim} onSubmit={() => {}} onWhy={() => {}} />);
    expect(screen.getAllByTestId("line-item")).toHaveLength(2);
    expect(screen.getByText("Needs info")).toBeInTheDocument();
    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.getByTestId("claim-reimbursable")).toHaveTextContent("₹1,986.00");
    expect(screen.getByText("Answer 1 question to continue.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit claim" })).toBeDisabled();
    // capped meal shows reimbursable vs total
    expect(screen.getByText(/Reimbursable/, { selector: "div" })).toHaveTextContent(`${formatINR(1500)} of ${formatINR(3860)}`);
  });

  it("renders a linked UPI screenshot as a proof-of-payment sub-row, not its own line", () => {
    const upi = makeLine({ id: "u", status: "excluded", reimbursable_inr: 0, findings: [{ id: "f", kind: "duplicate", severity: "info", rule_id: null, message: "Linked", citation: null, evidence: { linked_to: "inv" }, resolution: "acknowledged" }] }, "paynow-6450");
    const inv = makeLine({ id: "inv", linked_proof_line_id: "u" }, "paperleaf-invoice");
    render(<ClaimCard claim={makeClaim({ lines: [inv, upi] })} onSubmit={() => {}} onWhy={() => {}} />);
    expect(screen.getAllByTestId("line-item")).toHaveLength(1);
    const proof = screen.getByTestId("proof-row");
    expect(within(proof).getByText("Proof of payment")).toBeInTheDocument();
    expect(within(proof).getByText(/428913765012/)).toBeInTheDocument();
  });

  it("says why a blocked person-to-person transfer is not reimbursed", () => {
    const base = makeLine({}, "paynow-6450");
    const extracted = {
      ...base.extracted,
      vendor_name: { ...base.extracted.vendor_name, value: null },
      payee_name: { ...base.extracted.payee_name, value: "Rohan Desai" },
      payee_type: { value: "individual" as const, confidence: 0.95, origin: "llm" as const },
    };
    const msg = "₹2,800 was sent to a person (Rohan Desai), not paid to a business; person-to-person transfers are not reimbursed.";
    const p2p = makeLine({ id: "p", status: "excluded", reimbursable_inr: 0, extracted, findings: [{ id: "p:P2P", kind: "policy", severity: "block", rule_id: "P2P_TRANSFER_NOT_REIMBURSABLE", message: msg, citation: null, evidence: {}, resolution: "open" }, { id: "p:BILL", kind: "missing", severity: "warn", rule_id: "BILL_REQUIRED", message: "Attach the bill", citation: null, evidence: {}, resolution: "open" }] });
    render(<ClaimCard claim={makeClaim({ lines: [p2p] })} onSubmit={() => {}} onWhy={() => {}} />);
    expect(screen.getByTestId("block-reason")).toHaveTextContent(`Not reimbursable: ${msg}`);
    expect(screen.queryByText(/Attach the bill/)).not.toBeInTheDocument(); // one reason on a blocked card
    expect(screen.getAllByText(/person-to-person/)).toHaveLength(1);
    expect(screen.getByText("Rohan Desai")).toBeInTheDocument();
    expect(screen.getByText("Person · Rohan Desai")).toBeInTheDocument();
  });

  it("enables submit when ready and shows the finance reference after submission", async () => {
    const onSubmit = vi.fn();
    const ready = makeClaim({ status: "ready_to_submit", lines: [makeLine()], total_inr: 486, reimbursable_inr: 486 });
    const { rerender } = render(<ClaimCard claim={ready} onSubmit={onSubmit} onWhy={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Submit claim" }));
    expect(onSubmit).toHaveBeenCalled();
    rerender(<ClaimCard claim={{ ...ready, status: "submitted", finance_reference: "FIN-2026-48213", submitted_at: "2026-10-10T11:00:00Z" }} onSubmit={onSubmit} onWhy={() => {}} />);
    expect(screen.getByRole("status")).toHaveTextContent("FIN-2026-48213");
    expect(screen.queryByRole("button", { name: "Submit claim" })).not.toBeInTheDocument();
  });

  it("opens Why? for a finding", async () => {
    const onWhy = vi.fn();
    const f = { id: "f1", kind: "duplicate" as const, severity: "warn" as const, rule_id: null, message: "Looks like the same ride as receipt #1", citation: null, evidence: { matched_line_id: "l2", score: 0.93, layer: "fuzzy" }, resolution: "open" as const };
    render(<ClaimCard claim={makeClaim({ lines: [makeLine({ id: "l1", status: "flagged", findings: [f] }, "rydego-airport-photo")] })} onSubmit={() => {}} onWhy={onWhy} />);
    expect(screen.getByText("Flagged")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Why?" }));
    expect(onWhy).toHaveBeenCalledWith(f, expect.objectContaining({ id: "l1" }));
  });
});
