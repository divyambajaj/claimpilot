import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMockApi } from "../api/mock";
import type { ClaimEvent } from "../types";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

async function settle<T>(p: Promise<T>): Promise<T> {
  let done = false;
  const tracked = p.finally(() => (done = true));
  tracked.catch(() => {});
  while (!done) await vi.advanceTimersByTimeAsync(100);
  return tracked;
}

describe("mock API happy path", () => {
  it("streams progress, asks <=3 questions, applies answers, then submits", async () => {
    const api = createMockApi();
    const claim = await settle(api.createClaim());
    const events: ClaimEvent[] = [];
    api.subscribeClaim(claim.id, (e) => events.push(e));
    const names = ["saffron-table-dinner", "rydego-airport", "paperleaf-invoice", "paynow-6450", "highway-fuels-handwritten", "rydego-airport-photo"];
    await settle(api.addDemoDocuments(claim.id, names));
    while (!events.some((e) => e.type === "done")) await vi.advanceTimersByTimeAsync(200);

    const stages = events.filter((e) => e.type === "stage").map((e) => (e.type === "stage" ? e.data.stage : ""));
    expect(stages.filter((s) => s === "done")).toHaveLength(names.length);
    const done = events.find((e) => e.type === "done")!;
    if (done.type !== "done") throw new Error();
    const c = done.data.claim;
    expect(c.open_questions).toHaveLength(3);
    expect(c.lines.find((l) => l.extracted.doc_type.value === "upi_screenshot")?.status).toBe("excluded");
    expect(c.lines.some((l) => l.linked_proof_line_id)).toBe(true);
    expect(c.status).toBe("draft");

    const answers = c.open_questions.map((q) => ({ question_id: q.id, value: q.field === "attendees_count" ? 4 : q.field === "date" ? "2026-10-04" : "confirm" }));
    const after = await settle(api.answer(c.id, answers));
    expect(after.status).toBe("ready_to_submit");
    const meal = after.lines.find((l) => l.category === "meals")!;
    expect(meal.reimbursable_inr).toBe(3000);
    expect(after.lines.filter((l) => l.status === "excluded")).toHaveLength(2);

    const { finance_reference } = await settle(api.submit(c.id));
    expect(finance_reference).toMatch(/^FIN-\d{4}-\d{5}$/);
  });

  it("rejects submit on a draft claim with 409", async () => {
    const api = createMockApi();
    const claim = await settle(api.createClaim());
    await expect(settle(api.submit(claim.id))).rejects.toMatchObject({ status: 409 });
  });
});
