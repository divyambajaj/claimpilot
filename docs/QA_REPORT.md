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
