import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FieldChip, confidenceBand } from "../components/chat/FieldChip";
import { fld } from "../api/mockReceipts";
import { formatINR } from "../lib/format";

describe("FieldChip", () => {
  it("bands confidence at 0.9 and the 0.75 planner threshold", () => {
    expect(confidenceBand(0.95)).toBe("high");
    expect(confidenceBand(0.8)).toBe("medium");
    expect(confidenceBand(0.74)).toBe("low");
  });

  it("formats the value and opens a popover with snippet and confidence", async () => {
    render(<FieldChip label="Total" field={fld(3860, 0.96, "GRAND TOTAL ₹ 3,860.00")} format={(v) => formatINR(v)} mono />);
    const btn = screen.getByRole("button", { name: /3,860\.00/ });
    expect(btn).toHaveAttribute("data-confidence", "high");
    await userEvent.click(btn);
    expect(screen.getByRole("dialog", { name: "Total details" })).toBeInTheDocument();
    expect(screen.getByText("96% confidence")).toBeInTheDocument();
    expect(screen.getByText("GRAND TOTAL ₹ 3,860.00")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("marks low-confidence values and shows assumed fields in grey", () => {
    const { rerender } = render(<FieldChip label="Attendees" field={fld(2, 0.46, "Cvr: 2?")} />);
    expect(screen.getByLabelText("low confidence")).toBeInTheDocument();
    rerender(<FieldChip label="City" field={fld("Lonavala", 0.58, null, "assumed")} />);
    const btn = screen.getByRole("button", { name: /Lonavala/ });
    expect(btn).toHaveAttribute("data-origin", "assumed");
    expect(btn).toHaveTextContent("assumed");
    expect(screen.queryByLabelText("low confidence")).not.toBeInTheDocument();
  });

  it("shows missing values as Not found", () => {
    render(<FieldChip label="Date" field={fld<string>(null, 0)} />);
    expect(screen.getByRole("button", { name: /Not found/ })).toBeInTheDocument();
  });
});
