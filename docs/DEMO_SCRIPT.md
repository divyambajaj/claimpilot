# ClaimPilot demo script (~5 min)

## Setup (before recording)

```bash
rm -f data/app.db*
LLM_PROVIDER=replay SEED_DEMO=1 REPLAY_DELAY_S=1.5 make serve
```

- Open a fresh private/incognito window at http://localhost:8000 (a rehearsal in the same browser makes the receipts look like duplicates; clear site data or use a new private window).
- Browser at 1440px wide, zoom 100%, hide bookmarks bar. Record with QuickTime (⌘⇧5 → Record Selected Portion) and an external mic if possible.
- Do one full rehearsal, then reset with the two commands above.

## Shot list and narration

| Time | On screen | Say (roughly) |
|---|---|---|
| 0:00–0:25 | Title / chat home | "Employees lose 15–25 minutes per claim collecting bills, typing details and guessing policy. Finance then rejects claims for missing GST invoices or duplicates. ClaimPilot turns a pile of receipts into a submission-ready claim in about a minute." |
| 0:25–1:05 | Try sample receipts → select all 13 → Add to claim; per-document progress | "This is a two-day Mumbai client trip: rides, meals, a hotel folio with its UPI payment screenshot, a handwritten fuel bill, a stationery invoice, and a UPI transfer to a colleague for a shared cab. Each document is read by a vision model into structured fields with a confidence score and the exact text it read." |
| 1:05–1:35 | Click a field value (Total) → popover; point at grey "assumed" chips | "Every field carries provenance. Low-confidence fields only become questions if they would change the outcome; otherwise they're marked assumed. That's how we ask only necessary questions." |
| 1:35–2:20 | Claim panel: UPI proof row, GST block, Rohan Desai transfer ("Not reimbursable: ₹350 was sent to a person…", chip "Paid to: Person · Rohan Desai"), meal cap; click "Why?" on the transfer, then on the Chaiwala meal | "The LLM only perceives; deterministic code decides. The hotel's UPI screenshot is linked to its bill as proof of payment, not counted twice. A payment screenshot on its own is not a bill, and this one is a transfer to a person, so it is blocked under section 6.3; masked UPI IDs and phone numbers never get stored. The stationery invoice over ₹5,000 is blocked: its GSTIN fails the checksum. The meal is capped at ₹750 per person, and 'Why?' shows the rule and the exact policy sentence it came from." |
| 2:20–3:00 | Answer the 3 questions (fuel date 06-10-2026; "Same expense, drop it"; "Client dinner approved in advance by the department head.") → Send; then the 4th, the fuel trip note ("Drove to the Thane client site and back on 6 Oct for the workshop.") → Send | "Four questions for thirteen documents: the smudged date, a re-photographed ride receipt caught as a duplicate, a justification for the meal cap, and the trip note the policy needs for every fuel bill. Answers are re-checked instantly, with no extra AI call." |
| 3:00–3:15 | "₹16,204.00 reimbursable of ₹25,460.40" → Submit → finance reference → Approved | "Ready to submit. It goes to the finance system (mocked here behind the same interface a real ERP connector would use) with a full audit trail." |
| 3:15–3:45 | Admin → Overview | "For the finance and admin team: auto-completion rate, questions per claim, cost per claim in rupees, latency, duplicates prevented and hours saved, all computed from stored traces." |
| 3:45–4:05 | Traces → open a trace; Audit trail | "Every claim is traced step by step: ingest, extract, validate, dedupe, rules, plan, with model, prompt version, tokens and cost. The audit trail shows every flag with its rule and source text." |
| 4:05–4:35 | Evaluation → Smoke set → Run eval; comparison table, reliability chart | "We built a synthetic evaluation set of 68 Indian receipts with ground truth: blurred, rotated, handwritten, UPI screenshots, planted duplicates and decoys, plus payments with no bill, a person-to-person transfer, a salon bill, someone else's recharge and a split purchase. With prompt v3: field accuracy 100%, duplicate precision and recall 100%, policy accuracy 100%, calibration measured, and the v1 and v2 runs alongside for comparison. A regression gate runs in CI." |
| 4:35–4:55 | Policy → hover a rule → highlighted sentence | "The policy is written in plain English. The AI compiles it once into rules with verified citations, and a deterministic engine runs them. Change the policy, not the code." |
| 4:55–5:10 | Back to chat / GitHub repo | "Model-agnostic provider layer, record-and-replay for keyless deployment, 310 tests at 99% coverage. ClaimPilot: from a pile of receipts to ready-to-submit." |

## Expected numbers (replay, DEMO_TODAY 2026-10-10)

- After upload: 13 documents, 12 lines (the hotel UPI screenshot becomes the folio's proof row). Total ₹25,460.40, reimbursable ₹16,846.00 before answers.
- Blocked (₹0): Fort Stationery Mart ₹7,410.40 (GST_INVOICE_ABOVE_5000, GSTIN checksum fails) and the ₹350 transfer to Rohan Desai (P2P_TRANSFER_NOT_REIMBURSABLE; it also shows BILL_REQUIRED and OTHER_NEEDS_BUSINESS_PURPOSE).
- Round 1 questions: Om Sai fuel date, the airport ride duplicate, the Chaiwala meal cap (₹963.50/person, reimbursed ₹3,000 of ₹3,854). After answering: ₹16,204.00.
- Round 2 question: the Om Sai fuel trip note (FUEL_TRIP_NOTE). After answering: Ready to submit, ₹16,204.00 of ₹25,460.40.
- Seeded admin data: eval runs for prompts v1 and v2 (61-receipt snapshots) and v3 (68 receipts).

## Tips
- Pause a beat after each click so viewers can read.
- If anything looks off, stop, reset with the setup commands, and re-record that segment; cut segments together later.
- Upload the final video to YouTube as *Unlisted* and paste the link into the README.
