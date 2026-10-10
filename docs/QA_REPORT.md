# QA report: pre-recording pass

Date: 10 Oct 2026. Build: `main` after `b5941e9`. Run: `LLM_PROVIDER=replay SEED_DEMO=1` on a fresh SQLite DB, single port :8000, driven in a real browser at 1440x900 and 375x812. Code-level checks (coverage, lint, types) were out of scope; `uv run pytest -q` and `npm run build` were kept green.

Status: PASS = worked as expected first time; FIXED = failed, fixed and re-verified; NOTE = works, with a caveat.

**Totals: 56 cases. 31 PASS, 24 FIXED (failed, then fixed and re-verified), 1 NOTE, 0 open failures.**

## A. Demo story (12-receipt Mumbai gallery)

| Area | Case | Expected | Actual | Status | Fix commit |
|---|---|---|---|---|---|
| Chat | Gallery: select all, add | 12 receipts added to a new claim | 12 added; claim "Expenses 10 Oct 2026" | PASS | |
| Chat | Per-document progress | Each file moves Reading -> Read | In replay, all 12 finished in under 1 s, so progress was never visible | FIXED | 03022f1 (`REPLAY_DELAY_S`) |
| Chat | Summary message | Counts and UPI note | "12 documents read. 1 needs a detail, 1 looks like a duplicate, 1 is blocked by policy, 1 needs a justification. The ₹5,824 UPI payment is attached ..." | PASS | |
| Claim | Total | Sum of 11 non-proof lines | ₹25,110.40 (642+642+1,166+3,854+5,824+318+872+2,132+1,545+7,410.40+705) | PASS | |
| Claim | Reimbursable before answers | Total minus GST block, minus meal over-cap | ₹16,846.00 | PASS | |
| Claim | Meal cap ₹750/person | Chaiwala 4 covers: ₹3,854 -> ₹3,000 (₹963.50/person) | "Reimbursable ₹3,000.00 of ₹3,854.00", flagged | PASS | |
| Claim | Meals under cap | Konkan 2 covers, Malabar 3, Bandra Bean 3: complete | All complete | PASS | |
| Claim | Hotel metro cap ₹6,000 | Harbourview ₹5,824 for 1 night: complete | Complete | PASS | |
| Claim | UPI proof row | UPI screenshot attached to the folio, not counted | Proof row "₹5,824.00 · UPI · ref 643616165652 · 6 Oct"; UPI line excluded | PASS | |
| Claim | GST block | Stationery ₹7,410.40, invalid GSTIN: excluded | Excluded with VAL_GSTIN_INVALID + GST_INVOICE_ABOVE_5000 | PASS | |
| Claim | Duplicate ride | Re-photographed ₹642 ride flagged | Flagged; message showed ISO date "2026-10-05" | FIXED | 11e694c ("5 Oct 2026") |
| Claim | Header line count | Counts match the cards shown | "10 lines" over 11 cards | FIXED | 109a8f4 ("11 lines · 1 left out · 3 need attention") |
| Questions | Smudged date, duplicate, meal justification | Three questions, answerable | Answered; claim READY, ₹16,204.00 of ₹25,110.40 | PASS | |
| Submit | Finance reference, then Approved | FIN-xxxx, approval lands in chat | "Finance approved FIN-3567 for ₹16,204.00." | PASS | |
| Format | INR | Indian grouping, ₹ prefix, 2 decimals | Correct everywhere checked | PASS | |
| Format | Times | Local time | Naive UTC shown as local (5.5 h off in IST) | FIXED | 109a8f4 |

## B. Features in isolation

| Area | Case | Expected | Actual | Status | Fix commit |
|---|---|---|---|---|---|
| Popover | Source snippet + confidence | Snippet, % and origin | Shown | PASS | |
| Popover | Near the right edge of the panel | Fully visible | Clipped by the scrolling list | FIXED | 109a8f4, 6cdf567 |
| Popover | Assumed / validator origin | Origin note | "Set by a validator" on the invalid GSTIN (0%) | PASS | |
| Why drawer | Rule, quote, section, evidence | All four | Meal cap: rule, quote, §4.2, but no evidence line | FIXED | 109a8f4 ("Reimbursed up to the limit: ₹3,000.00, ₹854.00 over.") |
| Why drawer | GST block evidence | Plain explanation | Said the GSTIN "could not be read with enough confidence" | FIXED | 109a8f4 |
| Duplicates | Keep / drop from the drawer | Line updates, question disappears | Line updated, but the open form still held the question and "Send answers" failed: "question ... is not open" (user stuck) | FIXED | 109a8f4 |
| Lines | Exclude / restore | Available in the panel | No UI for it (API only) | FIXED | 109a8f4 ("Leave out of claim" / "Restore line", totals verified) |
| Fields | Direct edit + re-check | Correct a value, rules re-run | No UI (API only); blocked lines hid their fields | FIXED | 109a8f4 (GSTIN corrected -> stationery Complete, +₹7,410.40) |
| Fields | Invalid edit | Rejected or re-flagged | Bad GSTIN saved and re-flagged invalid; validation errors show in the popover | PASS | |
| Upload | Non-recorded file | 409 message pointing to the gallery | "This file is not in the recorded demo set ... Use the sample receipts instead." | PASS | |
| Upload | Wrong type / over 10 MB | Rejected with a reason | Rejected, but the reason was lost once the chat started | FIXED | 109a8f4 ("Added 1 file · 2 skipped (...)") |
| Upload | PDF | Read if recorded | No PDF is recorded in the demo set; a PDF gets the 409 above | NOTE | |
| Empty | Empty chat / claim / admin states | Plain empty copy | Shown | PASS | |
| Gallery | Footer | Pinned at the bottom | Rows showed through below the footer | FIXED | 109a8f4 |

## C. Admin

| Area | Case | Expected | Actual | Status | Fix commit |
|---|---|---|---|---|---|
| Overview | KPIs match the API | Same numbers | 14 claims; time saved 14 x 14 min = 3.3 h; duplicates ₹11,618 + ₹19,023 + ₹10,752 = ₹41,393 | PASS | |
| Overview | Violations by rule | Every rule labelled | Every second label missing | FIXED | 5b1d0d4 |
| Overview | Eval trend | Comparable runs | Smoke runs would mix with full runs | FIXED | 11e694c |
| Traces | Waterfall + span attributes | Click a span, see attributes | Attributes were below an 84-row list | FIXED | 5b1d0d4 (list scrolls) |
| Audit | Search / severity filter / sort | Work | "hotel" -> 7 of 55; amount sort ascending | PASS | |
| Audit | Rows without a rule | Readable | Rule "—"; info rows read "Open" in warning colour | FIXED | 5b1d0d4 |
| Eval | Run smoke, progress, gate | Runs, badge | Ran; "Gate passed" | PASS | |
| Eval | Second run while running | 409 | Button disabled while running; API returns 409 "An evaluation is already running." | PASS | |
| Eval | Deltas / comparison | Same subset | Smoke run compared against the full run | FIXED | 5b1d0d4 |
| Eval | Reliability chart, per-field table | Rendered | Rendered | PASS | |
| Policy | Text, rules with citations, hover highlight, coverage | Rendered | 12 rules, citations, "11 of 76 sentences produced a rule" | PASS | |
| Policy | Compile in replay mode | Sensible message | Showed the receipt-gallery message | FIXED | 5b1d0d4 |

## D. Robustness

| Area | Case | Expected | Actual | Status | Fix commit |
|---|---|---|---|---|---|
| Refresh | Mid-claim | Same claim | Started a new chat | FIXED | 109a8f4 (resumes; "Start a new claim" link) |
| Navigation | Back / forward between tabs | Correct tab | Correct | PASS | |
| Submit | Double click | One submission | One submission, no error | PASS (guard added in 109a8f4) | |
| Upload | Repeated uploads while reading | No double batch | Drop zone disabled while reading | PASS | |
| Server | Restart mid-claim | Claim continues | Answers and submit worked after restart | PASS | |
| Users | Second visitor runs the gallery | Same story | All 11 lines flagged as duplicates of the first visitor's claim (shared `demo-user`) | FIXED | 109a8f4 (per-browser `X-User-Id`) |

## E. Visual (1440 and 375)

| Area | Case | Expected | Actual | Status | Fix commit |
|---|---|---|---|---|---|
| Layout | No horizontal page scroll at 375 | None | scrollWidth 375 on all six pages | PASS | |
| Layout | Eval run picker at 375 | Inside its card | Overflowed | FIXED | 5b1d0d4 |
| Style | No purple, gradients, emoji icons | None | None found | PASS | |
| Keyboard | Question form | Tab through, Enter submits, focus ring | Works; visible focus ring | PASS | |
| Text | Long vendor names | Truncate, no overlap | Truncate with ellipsis | PASS | |

## F. Date robustness

| Area | Case | Expected | Actual | Status | Fix commit |
|---|---|---|---|---|---|
| Clock | Opened weeks after recording | Same findings | Late-submission findings would appear after 4 Nov | FIXED | 03022f1 (`DEMO_TODAY`, tests in `test_api.py::TestDemoToday`) |

## G. Leftovers

| Area | Case | Expected | Actual | Status | Fix commit |
|---|---|---|---|---|---|
| Lint | Secret check | Passes | False positive at `test_llm_core.py:89` | FIXED | cefdb6b |
| Types | `EvalRun.details` | Mirrored | Added (with `LineItem.user_excluded`, `linked_to_line_id`, `Claim.processing`) | FIXED | 109a8f4 |

## Not changed

- Replay runs are fast even with `REPLAY_DELAY_S`; the waterfall shows replay timings, with the recorded latency in each llm span (already labelled on the page).
- Overview has no latency histogram chart although the API returns one (spec item, not a regression).
- A failed (409) upload leaves an empty claim behind; harmless.

# Pass 2: eligibility rules and the 13-receipt story

Date: 11 Oct 2026. Build: `main` after `5719c29` (Jio Platforms rename, prompt v3, eligibility rules, PII masking, 13-receipt gallery). Run: `LLM_PROVIDER=replay SEED_DEMO=1 REPLAY_DELAY_S=1.5` on a fresh SQLite DB (port 8020 with a scratch `DATABASE_URL`, because :8000 was in use), driven in the built-in browser at 1440x900 and 375x812 with site data cleared before each run. `uv run pytest -q` (310 tests, 98.9% coverage), `make lint`, `npm run build` and the 27 frontend tests stay green.

**Totals: 37 cases. 28 PASS, 7 FIXED, 2 NOTE, 0 open failures.**

| Area | Case | Expected | Actual | Status | Fix commit |
|---|---|---|---|---|---|
| Chat | Gallery | 13 receipts, all pre-selected | "Add 13 to claim"; intro copy did not mention the transfer | FIXED | 78aac46 |
| Chat | Progress | Visible per document | "Reading 13 documents", about 20 s; a single file read "Read 1 documents" | FIXED | 78aac46 ("Read 1 document") |
| Chat | Summary | Counts and UPI note | "13 documents read. 1 needs a detail, 1 looks like a duplicate, 2 are blocked by policy, 1 needs a justification. The ₹5,824 UPI payment is attached …" | PASS | |
| Claim | Totals before answers | ₹25,460.40 / ₹16,846.00 | Same; header "12 lines · 2 left out · 3 need attention" | PASS | |
| Claim | UPI proof row | Under Harbourview, not counted | "Proof of payment ₹5,824.00 · UPI · ref 643616165652 · 6 Oct" | PASS | |
| Claim | Stationery GST block | Excluded, invalid GSTIN | "Not reimbursable: … GSTIN missing or fails checksum" plus the VAL_GSTIN_INVALID note | PASS | |
| Claim | Rohan Desai transfer | One clear reason | Red "Not reimbursable" line plus three bullet findings (P2P repeated, "Attach the bill", "business purpose") | FIXED | 39a4de9 (card shows one reason with Why?; the other checks sit under "Also noted" in the drawer) |
| Claim | Blocked line actions | Optional remove only | No "Leave out of claim" on blocked lines | FIXED | 39a4de9 |
| Claim | Duplicate ride | Flagged, question | Flagged with "5 Oct 2026" | PASS | |
| Why | Meal cap | Rule, Jio §4.2 quote, evidence | "Meals are reimbursed up to INR 750 per person per meal." §4.2; "Reimbursed up to the limit: ₹3,000.00, ₹854.00 over." | PASS | |
| Why | Receipt number | Same as the card | Drawer counted the nested UPI proof: transfer showed "#12", card "11" | FIXED | 39a4de9 |
| Questions | Round 1 | Date, duplicate, meal justification | Answered (06/10/2026, "Same expense, drop it", justification): ₹16,204.00, "3 left out · 1 needs attention" | PASS | |
| Questions | Round 2 | Fuel trip note, then ready | "Thanks. One more question…"; answer stored as "Purpose:" on the card; "All lines are complete. ₹16,204.00 reimbursable of ₹25,460.40 claimed." | PASS | |
| Submit | Finance | Reference, then approved | "Submitted to Finance. Reference FIN-3672 …", ~20 s later "Finance approved FIN-3672 for ₹16,204.00." | PASS | |
| Rules | Blocked line asks nothing | No questions on a blocked line | Planner still ran low-confidence (VOI) questions on blocked lines, e.g. category or payee on a salon payment | FIXED | 1908804 (+ test in `test_eligibility.py`) |
| Rules | Standalone UPI screenshot | "Attach the bill …", linked when the bill arrives | Hotel UPI alone: "Attach the bill for this ₹5,824 payment to Harbourview Residency …" (plus city, category); adding the folio linked it, questions closed, "Ready to submit" | PASS | |
| Rules | Trip note re-check | Fuel line completes | Completes after the answer, no model call | PASS | |
| Rules | Business-purpose note | Re-check clears OTHER_NEEDS_BUSINESS_PURPOSE | No unblocked "other" line in the gallery; covered by `test_eligibility.py::test_bill_and_trip_note_answers` and `test_other_needs_purpose_and_payer_check` | NOTE | |
| Rules | Not-reimbursable copy | Clear and calm | "₹350 was sent to a person (Rohan Desai), not paid to a business; person-to-person transfers are not reimbursed." | PASS | |
| PII | Payee / payer display | Masked | "Paid to: Person · Rohan Desai"; popover snippet `r****.*****-2@okpaynow`; payer "K. Mehta (xx••••)" | PASS | |
| Copy | "Acme" leftovers | None | None in UI, docs, seed data, policy or gallery images | PASS | |
| Admin | Overview | Renders with new rules | 16 claims, 16 rules in "Violations by rule" incl. BILL_REQUIRED, P2P, PERSONAL, SPLIT | PASS | |
| Admin | Answered justifications in stats/audit | Trip note visible as resolved | FUEL_TRIP_NOTE / OTHER_NEEDS_BUSINESS_PURPOSE stop firing once `business_purpose` is set, so they vanish from Overview counts and the audit trail (the purpose stays on the line) | NOTE | |
| Admin | Traces | Waterfall, span attributes | Upload trace 91 spans, attributes below | PASS | |
| Admin | Audit | New rules with citations | 71 findings; §3.1, §6.3, §2.1 quotes | PASS | |
| Admin | Eval history | v1/v2/v3 sensible | v3 (68 receipts) showed "+0.003 vs previous" against v2 on the 61-receipt snapshot | FIXED | 78aac46 (deltas only within one fixture set; "Receipts" column in the comparison table) |
| Admin | Smoke run | Runs, gate | 13 receipts, ~20 s, "Gate passed" | PASS | |
| Admin | Policy | Jio policy, disclaimer, new rules verified | First line is the disclaimer; 20 rules, every `citation_verified` true; "19 of 83 sentences produced a rule"; hover highlights the sentence | PASS | |
| Regression | Refresh mid-claim | Resumes | "Picked up 'Expenses 10 Oct 2026' where you left it." | PASS | |
| Regression | Second visitor | No cross-visitor duplicates | Fresh browser id; hotel folio and UPI not flagged | PASS | |
| Regression | Non-recorded upload | 409 message | "This file is not in the recorded demo set …" | PASS | |
| Regression | Wrong type / over 10 MB | Reason shown | "Added 1 file · 2 skipped (images or PDFs up to 10 MB, 10 at a time)" | PASS | |
| Regression | Field popover | Snippet, confidence | Shown, inside the mobile sheet too | PASS | |
| Regression | Mobile bar and sheet | Totals, sheet opens | "12 lines · Reimbursable ₹16,846.00 · Needs info · View claim"; sheet scrolls | PASS | |
| Regression | 375 px layout | No horizontal scroll | scrollWidth 375 | PASS | |
| Regression | Drawer close | Escape closes | Works | PASS | |
| Regression | Keyboard in justification box | Enter | Enter adds a newline in the textarea (Send answers button submits) | PASS | |

## Not changed (pass 2)

- The run picker, comparison table and llm span attributes show the recorded model name; CLAUDE.md keeps docs provider-neutral, the UI was left as is.
- Times use the UTC calendar day pinned to `DEMO_TODAY`; after 18:30 UTC (midnight IST) the claim is titled "10 Oct" while times read "11 Oct". Record in the IST daytime.
- Answered trip notes and business purposes are not kept as resolved findings (see the NOTE above); changing that means changing the rule conditions and the eval ground truth.
