# ClaimPilot evaluation

The eval harness pushes a synthetic receipt set with ground truth through the **real** orchestrator (ingest → extract → redact → validate → dedupe → rules → planner) and scores what comes out. It runs in CI on every push, in replay mode, with no keys.

Code: `backend/app/evaluation/` (`runner.py`, `metrics.py`, `calibration.py`, `gate.py`, `oracle.py`, `synth/`). Data: `data/eval/` (`fixtures/`, `baseline.json`, `history/`).

## 1. Dataset

68 synthetic documents in 14 claims (`data/eval/fixtures/manifest.json`, seed 20261008, eval date 2026-10-08, claimant "Kavya Mehta"). Every vendor, person, GSTIN and UPI ID is fictional; GSTINs are generated with valid (or deliberately broken) checksums. Images are committed and never regenerated in CI, because replay fingerprints depend on their bytes.

**Templates** (from `ground_truth.jsonl`): restaurant 18, ride 12, UPI screenshot 12, hotel folio 11, stationery invoice 8, handwritten bill 4, fuel slip 3. 34 PNG + 34 JPEG.

**Image degradations**: JPEG re-compression 18, crumple/shadow noise 14, blur 13, rotation 11, perspective warp 11, crop 6 (some receipts carry several).

**Planted scenarios** (`manifest.counts`, number of receipts tagged):

| Scenario | Receipts | What it tests |
|---|---|---|
| `upi_pair` | 16 (8 pairs) | UPI screenshot linked to its bill as proof of payment, not double-counted |
| `upi_txn_link` | 1 | Link via the UPI reference printed on the bill |
| `upi_no_bill` | 4 | A payment screenshot alone is not a bill (`BILL_REQUIRED`) |
| `dup_exact` | 8 | Same file re-uploaded (perceptual layer) |
| `dup_rephoto` | 6 | Same bill photographed again (fuzzy / semantic layers) |
| `decoy` | 4 | Near-misses that must **not** be flagged (e.g. two rides, same day, different amounts) |
| `meals_cap` | 3 | ₹750 per person cap |
| `lodging_cap` | 3 | Metro / non-metro hotel caps |
| `local_travel_cap` | 1 | Daily local conveyance cap across lines |
| `fuel_cap` | 1 | Fuel cap per claim |
| `fuel_no_trip_note` | 3 | Fuel needs a trip note (`FUEL_TRIP_NOTE`) |
| `gst_block` | 1 | ≥ ₹5,000 without a valid GST invoice is blocked |
| `invalid_gstin` | 3 | GSTIN fails the mod-36 checksum |
| `missing_gstin` / `missing_date` / `missing_covers` | 2 / 2 / 1 | Missing fields become questions |
| `smudged` | 1 | Low-confidence, decision-relevant field |
| `late` | 1 | Outside the 30-day submission window |
| `weekend` | 1 | Office supplies bought on a weekend |
| `cash` | 1 | Cash above ₹2,000 needs a justification |
| `p2p_transfer` | 1 | Person-to-person UPI transfer is blocked |
| `personal_expense` | 1 | Personal (salon) expense is blocked |
| `personal_recharge` | 1 | Recharge paid by someone else |
| `payer_mismatch` | 2 | Bill made out to / paid by someone other than the employee |
| `split_bill` | 2 | Same vendor, same day, together ≥ ₹5,000 |

Claims are processed in order, so later claims see earlier ones as the employee's history (cross-claim duplicates). The **smoke** subset is 3 claims / 13 receipts (claims marked `smoke: true`), used by the admin "Run eval" button.

## 2. Metrics

| Metric | Definition (`evaluation/metrics.py`, `calibration.py`) |
|---|---|
| Field accuracy (macro) | Per field, share of scored cells that match; mean over fields. A cell is scored when truth or prediction is non-null. Amounts match within ±₹0.5; GSTIN / invoice number / UPI ref compare alphanumerics case-insensitively; dates exact; strings case- and whitespace-normalised. A list in the truth means any listed value is correct (ambiguous fields such as a ride's subtotal are not scored). |
| Field accuracy (micro) | Same, over all cells pooled (778 cells in the v3 run). |
| Amount / date / GSTIN exact rate | Field accuracy restricted to those fields. |
| Duplicate precision / recall | Flagged pairs vs ground-truth pairs (same `dup_group`). Flagged decoys are false positives. Also reported per catching layer. |
| Violation accuracy | Per line, the set of WARN/BLOCK rule ids that fired equals the expected set exactly. Per-rule precision/recall is stored in `EvalRun.details`. |
| UPI link precision / recall | Links made by the pipeline vs planted screenshot ↔ bill pairs. |
| ECE | Expected calibration error over 10 equal-width bins of (post-validation confidence, correct) field cells. Brier score alongside. |
| Questions per claim | Questions shown to the user per claim (end of upload batch and after answers). |
| Auto-completion rate | Lines that ended COMPLETE without any question / all lines. |
| p50 / p95 latency, tokens, cost per receipt | From the `llm` spans; in replay these are the recorded values of the live run. |

The `--provider oracle` mode answers every extraction with the ground truth, which isolates the deterministic decision code: any error left is a rules, dedupe or planner bug, not a model error.

## 3. Results

Latest run (`make eval`, 11 Oct 2026, replay of the recorded live run, extraction prompt **v3**, 68 receipts): **gate PASS**.

| Metric | Value |
|---|---|
| Field accuracy (macro / micro) | 1.000 / 1.000 |
| Amount / date / GSTIN exact | 1.000 / 1.000 / 1.000 |
| Duplicates P / R | 1.000 / 1.000 (14 flagged / 14 true pairs: 8 perceptual, 6 fuzzy) |
| Violation accuracy | 1.000 (17 of the 20 rules have support; per-rule P/R all 1.000) |
| UPI links P / R | 1.000 / 1.000 (8 / 8) |
| ECE / Brier | 0.054 / 0.011 |
| Questions per claim | 2.29 |
| Auto-completion rate | 0.309 |
| Extract latency p50 / p95 | 12.6 s / 24.1 s |
| Mean tokens / cost per receipt | 53,351 / $0.063 |
| LLM calls / retries | 68 / 0 |

Per-field mean confidence ranges from 0.87 (category) and 0.88 (GSTIN) to 0.99 (total). With every cell correct, the ECE of 0.054 is entirely **under-confidence**.

### History (prompt progression)

| Run | Receipts | Field acc | Dup P / R | Violation acc | ECE | Q / claim | Auto-complete | $/receipt |
|---|---|---|---|---|---|---|---|---|
| extract v1 | 61 | 1.000 | 0.933 / 1.000 | 1.000 | 0.060 | 2.00 | 0.377 | 0.053 |
| extract v2 | 61 | 1.000 | 0.933 / 1.000 | 1.000 | 0.051 | 2.00 | 0.377 | 0.052 |
| extract v3 | 68 | 1.000 | 1.000 / 1.000 | 1.000 | 0.054 | 2.29 | 0.309 | 0.063 |

v1 and v2 ran on the earlier 61-receipt set; adding the eligibility scenarios and renaming the company and claimant changed most fixture bytes, so those runs are kept as snapshots in `data/eval/history/` (the seeded dashboard shows them). The rows are therefore comparable in trend, not cell by cell. The one v1/v2 duplicate false positive was a same-template, same-amount hotel pair caught by the semantic layer; it does not occur on the v3 set.

### What the eval caught (and the fixes)

| Found by | Problem | Fix |
|---|---|---|
| Oracle run | Distinct bills printed from one template sit within 6 bits of 64-bit dHash | A near (not byte-identical) image match now also needs the same amount and vendor |
| First live run | Dashed separator lines dominated the character n-gram vectors | Punctuation runs are dropped before embedding |
| First live run | A UPI screenshot read before its bill kept stale policy findings after linking | Linking drops them |
| v1 calibration | Under-confident on clearly printed values | v2 adds an explicit confidence scale and folio rules |
| Live testing with four UPI payment screenshots (not committed) | A salon payment, a prepaid recharge, a CNG payment and a "Money Sent" transfer to a person were all accepted | v3 prompt (`payee_type`, `payer_name`, `personal`), deterministic payee check, eligibility rules; synthetic look-alikes added to the set |

### Limits of these numbers

- The set is synthetic and was built alongside the prompt; 1.000 means "no regressions on known scenarios", not real-world accuracy.
- The semantic layer has no true positive of its own here (everything is caught earlier by the perceptual or fuzzy layer); it is unit-tested separately.
- Three rules (`EXPENSE_OLDER_THAN_90D`, `UPI_PROOF_FOR_CASHLESS`, `PHONE_INTERNET_MONTHLY_CAP`) have no planted case in the set; they are covered by unit and golden tests.
- Cost and latency are from one recorded live run; replays copy them.

## 4. How to run

```bash
make eval            # full set, replay provider, regression gate (what CI runs)
make eval-live       # full set through a live provider, recording replay files
                     #   LLM_PROVIDER=gemini make eval-live  (default claude_code)
make eval-baseline   # store the current replay run as the gate baseline (commit the result)

# runner options
PYTHONPATH=backend uv run python -m app.evaluation.runner \
  --subset smoke|full --provider replay|claude_code|gemini|anthropic|oracle \
  [--prompt-version v1] [--record] [--gate] [--write-baseline] [--no-save] [--compare]
```

From the UI: **Admin → Evaluation → Run eval** (smoke or full) streams progress over SSE and stores an `EvalRun`; the panel shows the per-field table, reliability diagram, deltas against the previous run of the same subset and the provider/prompt comparison table.

## 5. Regression gate

`make eval` exits 1 if the run regresses against `data/eval/baseline.json` (one baseline per subset; the current baseline is the v3 run above):

| Metric | Fails when |
|---|---|
| `field_accuracy` | drops more than 0.02 below baseline |
| `dup_recall` | drops more than 0.05 below baseline |
| `violation_accuracy` | drops more than 0.02 below baseline |
| `ece` | rises more than 0.03 above baseline |
| `questions_per_claim` | rises more than 0.5 above baseline |

A missing baseline passes with a warning. Changing the baseline is an explicit `make eval-baseline` commit, so a prompt or rule change that moves a metric shows up in review.
