import { describe, expect, it } from "vitest";
import { formatINR, formatDate } from "../lib/format";
import { describeEvidence } from "../components/chat/WhyDrawer";
import { makeLine } from "./fixtures";

describe("formatting", () => {
  it("uses Indian digit grouping for rupees", () => {
    expect(formatINR(123456)).toBe("₹1,23,456.00");
    expect(formatINR(1234567.5, { decimals: false })).toBe("₹12,34,568");
    expect(formatINR(null)).toBe("—");
  });
  it("formats plain dates without timezone shifts", () => {
    expect(formatDate("2026-10-03")).toBe("3 Oct 2026");
  });
  it("explains duplicate evidence in plain words", () => {
    const lines = [makeLine({ id: "a" }), makeLine({ id: "b" })];
    const [s] = describeEvidence({ id: "f", kind: "duplicate", severity: "warn", rule_id: null, message: "", citation: null, evidence: { matched_line_id: "b", score: 0.93, layer: "fuzzy", vendor_sim: 0.96, amount_match: true, date_delta_days: 0 }, resolution: "open" }, lines);
    expect(s).toBe("Matches receipt #2 — same vendor, amount, date (score 0.93, fuzzy layer)");
  });
});
