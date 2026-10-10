"""Evaluation harness: synthetic generator, metrics, calibration, gate."""

import asyncio
import datetime as dt
import json
from pathlib import Path

import pytest

from app.config import REPO_ROOT, Settings
from app.domain.enums import DocType, FindingKind, Severity
from app.domain.models import EvalRun, Finding, Span
from app.evaluation import gate, runner
from app.evaluation.calibration import brier, ece, reliability
from app.evaluation.metrics import (
    Observed,
    duplicate_scores,
    field_match,
    fired_rules,
    run_stats,
    score_fields,
    upi_link_scores,
    violation_scores,
)
from app.evaluation.oracle import OracleProvider
from app.evaluation.runner import FIXTURES, comparison, load_fixtures, run_eval
from app.evaluation.synth.generator import amount_words, generate, words
from app.evaluation.synth.render import inr
from app.pipeline.validate.gstin import is_valid_gstin
from app.rules.dsl import RuleSet
from tests.factories import make_claim, make_line

COMMITTED = REPO_ROOT / "data" / "eval" / "fixtures"


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[dict]]:
    out = tmp_path_factory.mktemp("synth")
    return out, generate(out)


class TestGenerator:
    def test_seeded_and_reproducible(self, generated, tmp_path: Path) -> None:
        out, rows = generated
        again = generate(tmp_path / "again")
        assert again == rows
        assert all(
            (out / r["file"]).read_bytes() == (tmp_path / "again" / r["file"]).read_bytes() for r in rows
        )

    def test_committed_ground_truth_is_current(self, generated) -> None:
        out, _ = generated
        assert (out / "ground_truth.jsonl").read_text() == (COMMITTED / "ground_truth.jsonl").read_text()
        assert json.loads((out / "manifest.json").read_text()) == json.loads(
            (COMMITTED / "manifest.json").read_text()
        )

    def test_planted_scenarios(self, generated) -> None:
        out, rows = generated
        by_id = {r["id"]: r for r in rows}
        manifest = json.loads((out / "manifest.json").read_text())
        assert 65 <= len(rows) <= 75 and len(manifest["claims"]) == 14
        planted = ("dup_exact", "dup_rephoto", "upi_pair", "decoy", "upi_no_bill", "p2p_transfer")
        planted += (
            "personal_expense",
            "personal_recharge",
            "split_bill",
            "payer_mismatch",
            "fuel_no_trip_note",
        )
        assert {k: manifest["counts"][k] for k in planted} == {
            "dup_exact": 8,
            "dup_rephoto": 6,
            "upi_pair": 16,
            "decoy": 4,
            "upi_no_bill": 4,
            "p2p_transfer": 1,
            "personal_expense": 1,
            "personal_recharge": 1,
            "split_bill": 2,
            "payer_mismatch": 2,
            "fuel_no_trip_note": 3,
        }
        assert manifest["employee_name"] == "Kavya Mehta"
        for r in rows:
            if r["dup_kind"] == "exact":  # a re-upload of the very same file
                assert (out / r["file"]).read_bytes() == (out / by_id[r["dup_of"]]["file"]).read_bytes()
            if r["dup_kind"] == "rephoto":
                assert "perspective" in r["augment"] and r["fields"] == by_id[r["dup_of"]]["fields"]
            if r["upi_pair"] and r["template"] == "upi":
                inv = by_id[r["upi_pair"]]
                assert (r["fields"]["total_amount"], r["fields"]["date"]) == (
                    inv["fields"]["total_amount"],
                    inv["fields"]["date"],
                )
                assert inv["claim_id"] == r["claim_id"]
            gstin = r["fields"].get("vendor_gstin")
            if gstin:
                src = by_id[r["dup_of"]] if r["dup_of"] else r
                assert is_valid_gstin(gstin) == ("invalid_gstin" not in src["scenario"]), r["id"]
        assert sum("missing_date" in r["scenario"] or "missing_gstin" in r["scenario"] for r in rows) >= 4

    def test_expected_rules_exist_in_ruleset(self, generated) -> None:
        ruleset = RuleSet.model_validate_json((REPO_ROOT / "data" / "rulesets" / "jio_v1.json").read_text())
        fired = {rule for r in generated[1] for rule in r["expected_rules"]}
        assert fired <= {r.id for r in ruleset.rules} and len(fired) >= 4

    def test_smoke_subset_has_a_duplicate_and_a_upi_pair(self, generated) -> None:
        out, rows = generated
        smoke = {
            f
            for c in json.loads((out / "manifest.json").read_text())["claims"]
            if c["smoke"]
            for f in c["fixtures"]
        }
        tags = {t for r in rows if r["id"] in smoke for t in r["scenario"]}
        assert {"dup_exact", "upi_pair", "meals_cap", "decoy"} <= tags

    def test_number_formatting(self) -> None:
        assert inr(123456.5) == "1,23,456.50"
        assert inr(999) == "999.00" and inr(-1200, 0) == "-1,200"
        assert words(0) == "zero" and words(115) == "one hundred fifteen"
        assert words(1234567) == "twelve lakh thirty-four thousand five hundred sixty-seven"
        assert amount_words(6608.5) == "Rupees Six Thousand Six Hundred Eight and Fifty Paise Only"


# --- calibration -------------------------------------------------------------------------------------------
class TestCalibration:
    def test_perfectly_calibrated_is_zero(self) -> None:
        pairs = [(0.75, True)] * 3 + [(0.75, False)] + [(1.0, True)] * 4
        assert ece(pairs) == 0.0
        assert brier([(1.0, True), (0.0, False)]) == 0.0

    def test_hand_computed_bins(self) -> None:
        pairs = [(0.95, True), (0.95, False), (0.15, False), (0.15, False)]
        # bin 9: acc 0.5 conf 0.95 -> 0.45; bin 1: acc 0 conf 0.15 -> 0.15; ECE = 0.5*0.45 + 0.5*0.15
        assert ece(pairs) == 0.3
        bins = reliability(pairs)
        assert len(bins) == 10 and bins[9].count == 2 and bins[9].accuracy == 0.5 and bins[0].count == 0
        assert (bins[1].lo, bins[1].hi, bins[1].mean_confidence) == (0.1, 0.2, 0.15)
        assert brier(pairs) == round((0.05**2 + 0.95**2 + 2 * 0.15**2) / 4, 4)

    def test_empty(self) -> None:
        assert ece([]) == 0.0 and brier([]) == 0.0 and all(b.count == 0 for b in reliability([]))


# --- metrics -----------------------------------------------------------------------------------------------
def _truth(fid: str, **kw) -> dict:
    base = {
        "id": fid,
        "template": "restaurant",
        "fields": {},
        "expected_rules": [],
        "dup_group": None,
        "upi_pair": None,
    }
    return base | kw


class TestMetrics:
    def test_field_match_normalisation(self) -> None:
        assert field_match("total_amount", 486.0, 486.4) and not field_match("total_amount", 486.0, 487.0)
        assert field_match("vendor_name", ["RydeGo", "RydeGo Mobility Pvt Ltd"], "RYDEGO MOBILITY PVT. LTD.")
        assert field_match("date", "2026-09-15", dt.date(2026, 9, 15))
        assert field_match("vendor_gstin", "27AAKCC4821M1ZC", "27 AAKCC 4821M1ZC")
        assert field_match("doc_type", ["invoice", "receipt"], DocType.RECEIPT)
        assert field_match("attendees_count", 2, 2.0) and field_match("city", None, None)
        assert not field_match("city", None, "Mumbai") and not field_match("city", "Mumbai", None)

    def test_score_fields_skips_empty_cells(self) -> None:
        truth = _truth(
            "fx_1", fields={"total_amount": 100.0, "city": None, "upi_txn_id": None, "date": "2026-10-01"}
        )
        line = make_line(
            "L1",
            total_amount=100.0,
            city="Pune",
            upi_txn_id=None,
            date=dt.date(2026, 10, 2),
            conf={"city": 0.4},
        )
        per_field, macro, micro, pairs = score_fields([Observed(truth, line)])
        assert set(per_field) == {"total_amount", "city", "date"}  # both-empty upi_txn_id is not scored
        assert per_field["city"].accuracy == 0.0 and per_field["city"].mean_confidence == 0.4
        assert (macro, micro) == (round(1 / 3, 4), round(1 / 3, 4)) and len(pairs) == 3

    def test_duplicates_violations_and_upi(self) -> None:
        a, b, c = make_line("A"), make_line("B"), make_line("C")
        dup = Finding(
            id="f",
            kind=FindingKind.DUPLICATE,
            severity=Severity.WARN,
            rule_id="DUPLICATE",
            message="dup",
            evidence={"matched_line_id": "A", "layer": "fuzzy"},
        )
        cap = Finding(
            id="g",
            kind=FindingKind.POLICY,
            severity=Severity.WARN,
            rule_id="MEALS_CAP_PER_PERSON",
            message="x",
        )
        info = Finding(
            id="h", kind=FindingKind.VALIDATION, severity=Severity.INFO, rule_id="VAL_X", message="x"
        )
        b.findings = [dup, cap]
        c.findings = [
            dup.model_copy(update={"evidence": {"matched_line_id": "B", "layer": "semantic"}}),
            info,
        ]
        observed = [
            Observed(_truth("fx_1", dup_group="g1", expected_rules=["MEALS_CAP_PER_PERSON"]), a),
            Observed(_truth("fx_2", dup_group="g1", expected_rules=["MEALS_CAP_PER_PERSON"]), b),
            Observed(_truth("fx_3"), c),
        ]
        fixture_of = {"A": "fx_1", "B": "fx_2", "C": "fx_3"}
        dups = duplicate_scores(observed, fixture_of)
        assert (dups["precision"], dups["recall"], dups["caught_by_layer"]) == (0.5, 1.0, {"fuzzy": 1})
        assert dups["false_positives"] == [{"pair": ["fx_2", "fx_3"], "layer": "semantic"}]
        v = violation_scores(observed)
        assert v["accuracy"] == round(2 / 3, 4)
        assert v["per_rule"]["MEALS_CAP_PER_PERSON"] == {"precision": 1.0, "recall": 0.5, "support": 2}
        assert fired_rules(c) == set()
        upi = make_line("U", doc_type="upi_screenshot", linked_to_line_id="A")
        links = upi_link_scores([Observed(_truth("fx_9", template="upi", upi_pair="fx_1"), upi)], fixture_of)
        assert links == {"precision": 1.0, "recall": 1.0, "expected": 1, "linked": 1}
        assert duplicate_scores([], {})["precision"] == 1.0

    def test_run_stats(self) -> None:
        now = dt.datetime(2026, 10, 8, 12)

        def span(status: str, **attrs) -> Span:
            return Span(id="s", trace_id="t", name="llm", start=now, end=now, status=status, attributes=attrs)

        spans = [
            span("ok", latency_ms=1000, tokens_in=900, tokens_out=100, cost_usd=0.02),
            span("ok", latency_ms=3000, tokens_in=1900, tokens_out=100, cost_usd=0.04),
            span("retry", latency_ms=50),
        ]
        stats = run_stats([make_claim(lines=[make_line("L1")], questions_asked=2)], spans, 2)
        assert stats["p50_latency_ms"] == 2000 and stats["mean_tokens"] == 1500
        assert stats["cost_usd_per_receipt"] == 0.03 and stats["llm_retries"] == 1
        assert stats["questions_per_claim"] == 2.0


# --- gate --------------------------------------------------------------------------------------------------
class TestGate:
    base = {
        "field_accuracy": 0.9,
        "dup_recall": 0.9,
        "violation_accuracy": 0.9,
        "ece": 0.05,
        "questions_per_claim": 2.0,
    }

    def test_within_and_beyond_tolerance(self) -> None:
        ok, msgs = gate.check(self.base | {"field_accuracy": 0.885, "ece": 0.07}, {"metrics": self.base})
        assert ok and msgs == []
        ok, msgs = gate.check(
            self.base | {"field_accuracy": 0.85, "questions_per_claim": 2.6}, {"metrics": self.base}
        )
        assert not ok and len(msgs) == 2 and msgs[0].startswith("field_accuracy")

    def test_missing_baseline_warns(self, tmp_path: Path) -> None:
        assert gate.load_baseline(tmp_path / "none.json", "full") is None
        ok, msgs = gate.check(self.base, None)
        assert ok and "no baseline" in msgs[0]

    def test_write_and_load_per_subset(self, tmp_path: Path, oracle_run: EvalRun) -> None:
        path = tmp_path / "baseline.json"
        gate.write_baseline(path, oracle_run)
        assert (
            gate.load_baseline(path, "full")["metrics"]["field_accuracy"] == oracle_run.metrics.field_accuracy
        )
        assert gate.load_baseline(path, "smoke") is None


# --- runner (offline: the oracle provider answers with ground truth) ----------------------------------------
@pytest.fixture(scope="module")
def oracle_run(tmp_path_factory: pytest.TempPathFactory) -> EvalRun:
    _, rows = load_fixtures()
    tmp = tmp_path_factory.mktemp("oracle")
    settings = Settings(
        _env_file=None, DATA_DIR=_shared_data(tmp), DATABASE_URL=f"sqlite:///{tmp / 'app.db'}"
    )
    seen: list[tuple[int, int, str | None]] = []
    run = asyncio.run(
        run_eval(
            settings,
            "full",
            OracleProvider(list(rows.values()), FIXTURES),
            lambda d, t, f: seen.append((d, t, f)),
            baseline_path=tmp / "none.json",
        )
    )
    assert seen[0] == (0, 68, None) and seen[-1][0] == 68 and len(seen) == 69
    assert not list((tmp / "data" / "uploads").glob("*")), "eval uploads are scratch copies and get removed"
    return run


def _shared_data(tmp: Path) -> Path:
    data = tmp / "data"
    data.mkdir()
    for name in ("replay", "rulesets", "policies"):
        (data / name).symlink_to(REPO_ROOT / "data" / name)
    return data


class TestRunner:
    def test_oracle_scores_the_decision_code(self, oracle_run: EvalRun) -> None:
        """With perfect perception every planted violation, UPI link and duplicate is found."""
        m, d = oracle_run.metrics, oracle_run.details
        assert m.field_accuracy == 1.0 and m.violation_accuracy == 1.0 and m.dup_recall == 1.0
        assert d["upi_links"]["recall"] == 1.0 and d["violations"]["mismatches"] == []
        assert m.dup_precision >= 0.9  # one same-template, same-amount hotel pair stays a hard decoy
        assert oracle_run.provider == "oracle" and oracle_run.n_receipts == 68 and oracle_run.subset == "full"
        assert oracle_run.passed_gate and "no baseline" in d["gate"][0]
        assert sum(b.count for b in oracle_run.reliability_bins) == d["scored_cells"]

    def test_comparison_keeps_latest_per_key(self, oracle_run: EvalRun) -> None:
        older = oracle_run.model_copy(
            update={"id": "old", "created_at": oracle_run.created_at - dt.timedelta(days=1)}
        )
        other = oracle_run.model_copy(update={"id": "v0", "prompt_version": "v0"})
        assert [r.id for r in comparison([older, oracle_run, other])] == [oracle_run.id, "v0"]

    def test_cli_gate_baseline_and_compare(self, tmp_path: Path, monkeypatch, capsys) -> None:
        settings = Settings(
            _env_file=None, DATA_DIR=_shared_data(tmp_path), DATABASE_URL=f"sqlite:///{tmp_path / 'a.db'}"
        )
        monkeypatch.setattr(runner, "get_settings", lambda: settings)
        monkeypatch.setattr(runner, "BASELINE", tmp_path / "baseline.json")
        assert runner.main(["--subset", "smoke", "--provider", "oracle", "--write-baseline"]) == 0
        assert "baseline for 'smoke' written" in capsys.readouterr().out
        assert runner.main(["--subset", "smoke", "--provider", "oracle", "--gate"]) == 0
        out = capsys.readouterr().out
        assert "gate: PASS" in out and "field accuracy  macro 1.000" in out
        baseline = json.loads((tmp_path / "baseline.json").read_text())
        baseline["smoke"]["metrics"]["field_accuracy"] = 1.5  # an impossible baseline must fail the gate
        (tmp_path / "baseline.json").write_text(json.dumps(baseline))
        assert runner.main(["--subset", "smoke", "--provider", "oracle", "--gate", "--no-save"]) == 1
        assert "gate: FAIL" in capsys.readouterr().out
        assert runner.main(["--compare"]) == 0
        assert capsys.readouterr().out.count("oracle/ground-truth") == 1  # latest stored run per key
