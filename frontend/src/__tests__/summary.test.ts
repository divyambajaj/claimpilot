import { describe, expect, it } from "vitest";
import { summarize } from "../pages/ChatPage";
import { describeEvidence } from "../components/chat/WhyDrawer";
import type { Finding } from "../types";
import { makeClaim, makeLine } from "./fixtures";

const finding = (over: Partial<Finding>): Finding => ({ id: "f", kind: "policy", severity: "warn", rule_id: null, message: "", citation: null, evidence: {}, resolution: "open", ...over });

describe("summarize", () => {
  it("counts a blocked (excluded) line once and the flagged lines as justifications", () => {
    const blocked = makeLine({ id: "b", status: "excluded", findings: [finding({ severity: "block" })] });
    const flagA = makeLine({ id: "a", status: "flagged", findings: [finding({})] });
    const flagB = makeLine({ id: "c", status: "flagged", findings: [finding({})] });
    expect(summarize(makeClaim({ lines: [blocked, flagA, flagB] }), 3)).toBe("3 documents read. 1 is blocked by policy, 2 need a justification.");
  });
});

describe("describeEvidence", () => {
  it("names the earlier claim when the duplicate is not in this claim", () => {
    const f = finding({ kind: "duplicate", severity: "block", evidence: { matched_line_id: "x", matched_claim_id: "clm_1", matched_amount_inr: 486, score: 1, layer: "perceptual", layers: { perceptual: { signal: "sha256" } } } });
    expect(describeEvidence(f, [makeLine({ id: "l" })])).toEqual(["Matches a ₹486.00 receipt already in claim clm_1 (the identical file)."]);
  });
});
