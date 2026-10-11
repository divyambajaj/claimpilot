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
| 0:00–0:25 | Title / chat home | "Filing an expense claim takes fifteen to twenty-five minutes. Then Finance sends it back for a missing GST bill or a duplicate. ClaimPilot does this work for you in about a minute." |
| 0:25–1:05 | Try sample receipts → all 13 are pre-selected → Add 13 to claim; per-document progress ("Reading 13 documents", about 20 s) | "Here is a two-day client trip to Mumbai: cab rides, meals, a hotel bill with its UPI payment, a handwritten fuel bill, an office supplies bill, and money sent to a colleague. The AI reads every bill and fills in the details by itself." |
| 1:05–1:35 | Click Total on the Chaiwala meal → popover ("GRAND TOTAL Rs. 3,854.00", confidence bar); point at the fuel line's "Date: Not found" | "For every value, you can see exactly where on the bill it was read from, and how sure the AI is. It only asks about something unclear if the answer would change the money. Here, only the smudged fuel date matters." |
| 1:35–2:20 | Claim panel: UPI proof row under Harbourview (#5), GST block on Fort Stationery (#10), Rohan Desai transfer (#11: one red line "Not reimbursable: ₹350 was sent to a person…", chip "Paid to: Person · Rohan Desai"; tap the chip to show the masked UPI ID), meal cap on Chaiwala (#4); click "Why?" at the end of the transfer's red line (§6.3 quote, "Also noted" lists the bill and purpose checks it no longer needs), then "Why?" on the Chaiwala meal (§4.2 quote, "Reimbursed up to the limit: ₹3,000.00, ₹854.00 over.") | "The AI only reads the bills. Fixed company rules make every decision. The hotel's UPI payment is matched to its bill, so it isn't counted twice. Money sent to a person is not allowed, and a stopped bill asks nothing more. Phone numbers and UPI IDs are hidden before anything is saved. The office supplies bill is stopped because its GST number is not valid. The meal is over the ₹750 per person limit, and 'Why?' shows the exact line from the policy." |
| 2:20–3:00 | Round 1, three questions: fuel date 06/10/2026 in the date picker; "Same expense, drop it"; type "Client dinner approved in advance by the department head." → Send answers (reimbursable becomes ₹16,204.00). Round 2, "Thanks. One more question…": the fuel trip note, type "Drove to the Thane client site and back on 6 Oct for the workshop." → Send answers | "Thirteen bills, and only four questions: a date that can't be read, a cab bill uploaded twice, a reason for the costly meal, and a note for the fuel trip. Answers are checked straight away. A reply like 'no' is not accepted." |
| 3:00–3:15 | "All lines are complete. ₹16,204.00 reimbursable of ₹25,460.40 claimed." → Submit claim → "Submitted to Finance. Reference FIN-xxxx" → about 20 s later "Finance approved FIN-xxxx for ₹16,204.00." | "The claim is ready. It goes to Finance with a reference number and a full record of every decision." |
| optional, +0:15 | Claim panel footer → Raise a ticket with Finance → uncheck Fort Stationery, keep the Rohan Desai transfer; note "Shared cab with a colleague to the client site; I paid him back by UPI." → Submit ticket → "Ticket TKT-xxxx raised for 1 line…"; the transfer's card shows "Ticket TKT-xxxx · Open", then "In review" about 20 s later (also listed under Admin → Audit trail → Tickets) | "A stopped bill is not a dead end. If the employee thinks it is wrong, one click sends it to a person in Finance with their note. The rules decide; people review." |
| 3:15–3:45 | Admin → Overview | "The Finance team gets a live dashboard: claims that needed no questions, cost per claim in rupees, time saved, and money saved by catching duplicates. All measured from every claim it processes." |
| 3:45–4:05 | Traces → open a trace; Audit trail | "Every claim keeps a step-by-step record: what was read, which checks ran, and why each bill was flagged." |
| 4:05–4:35 | Evaluation → Smoke set → Run eval (13 receipts, about 20 s, "Gate passed"); pick the full v3 run in the Run menu; comparison table, reliability chart | "We tested it on sixty-eight sample Indian bills we made for testing: blurry, tilted, handwritten, uploaded twice, a payment with no bill, money sent to a person, a salon bill. It got every detail, every duplicate and every policy check right. Every change is re-tested automatically." |
| 4:35–4:55 | Policy → hover a rule → highlighted sentence | "The policy is written in plain English. It is turned into rules once, each linked to the exact policy line. To change a rule, you change the policy, not the code." |
| 4:55–5:10 | Back to chat / GitHub repo | "It is not tied to any one AI company, the online demo needs no paid keys, and it is backed by 374 automated tests. ClaimPilot: from a pile of bills to a claim that is ready to submit." |

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
