# ClaimPilot demo script (~5 min)

## Setup (before recording)

```bash
rm -f data/app.db*
LLM_PROVIDER=replay SEED_DEMO=1 REPLAY_DELAY_S=1.5 make serve
```

- If port 8000 is taken, add `DATABASE_URL=sqlite:////tmp/claimpilot_demo.db` and run `uv run uvicorn app.main:app --app-dir backend --port 8020` with the same env vars after `npm --prefix frontend run build`.
- Open a fresh private/incognito window at http://localhost:8000 (a rehearsal in the same browser makes the receipts look like duplicates; clear site data or use a new private window).
- Browser at 1440px wide, zoom 100%, hide bookmarks bar. Record with QuickTime (⌘⇧5 → Record Selected Portion) and an external mic if possible.
- Do one full rehearsal, then reset with the two commands above.

## Shot list and narration

| Time | On screen | Say (roughly) |
|---|---|---|
| 0:00–0:25 | Title / chat home | "Employees lose 15–25 minutes per claim collecting bills, typing details and guessing policy. Finance then rejects claims for missing GST invoices or duplicates. ClaimPilot turns a pile of receipts into a submission-ready claim in about a minute." |
| 0:25–1:05 | Try sample receipts → all 13 are pre-selected → Add 13 to claim; per-document progress ("Reading 13 documents", about 20 s) | "This is a two-day Mumbai client trip: rides, meals, a hotel folio with its UPI payment screenshot, a handwritten fuel bill, a stationery invoice, and a UPI transfer to a colleague for a shared cab. Each document is read by a vision model into structured fields with a confidence score and the exact text it read." |
| 1:05–1:35 | Click Total on the Chaiwala meal → popover ("GRAND TOTAL Rs. 3,854.00", confidence bar); point at the fuel line's "Date: Not found" | "Every field carries provenance: the exact text it was read from and how sure the model was. A low-confidence field only becomes a question if a plausible misreading would change the outcome (otherwise it is marked assumed, shown in grey); here only the smudged fuel date matters. That's how we ask only necessary questions." |
| 1:35–2:20 | Claim panel: UPI proof row under Harbourview (#5), GST block on Fort Stationery (#10), Rohan Desai transfer (#11: one red line "Not reimbursable: ₹350 was sent to a person…", chip "Paid to: Person · Rohan Desai"; tap the chip to show the masked UPI ID), meal cap on Chaiwala (#4); click "Why?" at the end of the transfer's red line (§6.3 quote, "Also noted" lists the bill and purpose checks it no longer needs), then "Why?" on the Chaiwala meal (§4.2 quote, "Reimbursed up to the limit: ₹3,000.00, ₹854.00 over.") | "The LLM only perceives; deterministic code decides. The hotel's UPI screenshot is linked to its bill as proof of payment, not counted twice. A payment screenshot on its own is not a bill, and this one is a transfer to a person, so it is blocked under section 6.3, and a blocked line asks nothing more of you. Personal spend such as a salon bill is blocked the same way. UPI IDs and phone numbers are masked before anything is stored. The stationery invoice over ₹5,000 is blocked: its GSTIN fails the checksum. The meal is capped at ₹750 per person, and 'Why?' shows the rule and the exact policy sentence it came from." |
| 2:20–3:00 | Round 1, three questions: fuel date 06/10/2026 in the date picker; "Same expense, drop it"; type "Client dinner approved in advance by the department head." → Send answers (reimbursable becomes ₹16,204.00). Round 2, "Thanks. One more question…": the fuel trip note, type "Drove to the Thane client site and back on 6 Oct for the workshop." → Send answers | "Four questions for thirteen documents: the smudged date, a re-photographed ride receipt caught as a duplicate, a justification for the meal cap, and the trip note the policy needs for every fuel bill. Answers are re-checked instantly, with no extra AI call." |
| 3:00–3:15 | "All lines are complete. ₹16,204.00 reimbursable of ₹25,460.40 claimed." → Submit claim → "Submitted to Finance. Reference FIN-xxxx" → about 20 s later "Finance approved FIN-xxxx for ₹16,204.00." | "Ready to submit. It goes to the finance system (mocked here behind the same interface a real ERP connector would use) with a full audit trail." |
| optional, +0:15 | Claim panel footer → Raise a ticket with Finance → uncheck Fort Stationery, keep the Rohan Desai transfer; note "Shared cab with a colleague to the client site; I paid him back by UPI." → Submit ticket → "Ticket TKT-xxxx raised for 1 line…"; the transfer's card shows "Ticket TKT-xxxx · Open", then "In review" about 20 s later (also listed under Admin → Audit trail → Tickets) | "A blocked line is not a dead end. If the employee thinks the rule got it wrong, one click sends it to Finance for a manual review, with their note. The totals do not change: the rules decide, people review." |
| 3:15–3:45 | Admin → Overview | "For the finance and admin team: auto-completion rate, questions per claim, cost per claim in rupees, latency, duplicates prevented and hours saved, all computed from stored traces." |
| 3:45–4:05 | Traces → open a trace; Audit trail | "Every claim is traced step by step: ingest, extract, validate, dedupe, rules, plan, with model, prompt version, tokens and cost. The audit trail shows every flag with its rule and source text." |
| 4:05–4:35 | Evaluation → Smoke set → Run eval (13 receipts, about 20 s, "Gate passed"); pick the full v3 run in the Run menu; comparison table, reliability chart | "We built a synthetic evaluation set of 68 Indian receipts with ground truth: blurred, rotated, handwritten, UPI screenshots, planted duplicates and decoys, plus payments with no bill, a person-to-person transfer, a salon bill, someone else's recharge and a split purchase. With prompt v3 on 68 receipts: field accuracy 100%, duplicate precision and recall 100%, policy accuracy 100%, calibration measured, and the v1 and v2 runs on the earlier 61-receipt set alongside (the table shows each run's receipt count). A regression gate runs in CI." |
| 4:35–4:55 | Policy → hover a rule → highlighted sentence | "The policy is written in plain English. The AI compiles it once into rules with verified citations, and a deterministic engine runs them. Change the policy, not the code." |
| 4:55–5:10 | Back to chat / GitHub repo | "Model-agnostic provider layer, record-and-replay for keyless deployment, 374 backend tests at 99% coverage plus 36 UI tests. ClaimPilot: from a pile of receipts to ready-to-submit." |

## Expected numbers (replay, DEMO_TODAY 2026-10-10)

- After upload: 13 documents, 12 lines (the hotel UPI screenshot becomes the folio's proof row). Header "12 lines · 2 left out · 3 need attention". Chat: "13 documents read. 1 needs a detail, 1 looks like a duplicate, 2 are blocked by policy, 1 needs a justification. The ₹5,824 UPI payment is attached to the Harbourview Residency invoice as proof, not counted twice." Total ₹25,460.40, reimbursable ₹16,846.00 before answers.
- Blocked (₹0): Fort Stationery Mart ₹7,410.40 (GST_INVOICE_ABOVE_5000, with the VAL_GSTIN_INVALID note under it) and the ₹350 transfer to Rohan Desai (P2P_TRANSFER_NOT_REIMBURSABLE only on the card; BILL_REQUIRED and OTHER_NEEDS_BUSINESS_PURPOSE appear under "Also noted" in its Why drawer and in the audit trail). Blocked lines ask no questions; "Leave out of claim" is the only action.
- Round 1 questions: Om Sai fuel date, the airport ride duplicate, the Chaiwala meal cap (₹963.50/person, reimbursed ₹3,000 of ₹3,854). After answering: ₹16,204.00, header "12 lines · 3 left out · 1 needs attention".
- Round 2 question: the Om Sai fuel trip note (FUEL_TRIP_NOTE). After answering: Ready to submit, ₹16,204.00 of ₹25,460.40.
- Seeded admin data: eval runs for prompts v1 and v2 (61-receipt snapshots) and v3 (68 receipts).

## Tips
- Pause a beat after each click so viewers can read.
- If anything looks off, stop, reset with the setup commands, and re-record that segment; cut segments together later.
- Upload the final video to YouTube as *Unlisted* and paste the link into the README.
