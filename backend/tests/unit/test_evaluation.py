"""Evaluation harness: synthetic generator, metrics, calibration, gate."""

import json
from pathlib import Path

import pytest

from app.config import REPO_ROOT
from app.evaluation.synth.generator import amount_words, generate, words
from app.evaluation.synth.render import inr
from app.pipeline.validate.gstin import is_valid_gstin
from app.rules.dsl import RuleSet

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
        assert all((out / r["file"]).read_bytes() == (tmp_path / "again" / r["file"]).read_bytes() for r in rows)

    def test_committed_ground_truth_is_current(self, generated) -> None:
        out, _ = generated
        assert (out / "ground_truth.jsonl").read_text() == (COMMITTED / "ground_truth.jsonl").read_text()
        assert json.loads((out / "manifest.json").read_text()) == json.loads((COMMITTED / "manifest.json").read_text())

    def test_planted_scenarios(self, generated) -> None:
        out, rows = generated
        by_id = {r["id"]: r for r in rows}
        manifest = json.loads((out / "manifest.json").read_text())
        assert 55 <= len(rows) <= 65 and len(manifest["claims"]) == 12
        assert {k: manifest["counts"][k] for k in ("dup_exact", "dup_rephoto", "upi_pair", "decoy")} == {
            "dup_exact": 8,
            "dup_rephoto": 6,
            "upi_pair": 16,
            "decoy": 4,
        }
        for r in rows:
            if r["dup_kind"] == "exact":  # a re-upload of the very same file
                assert (out / r["file"]).read_bytes() == (out / by_id[r["dup_of"]]["file"]).read_bytes()
            if r["dup_kind"] == "rephoto":
                assert "perspective" in r["augment"] and r["fields"] == by_id[r["dup_of"]]["fields"]
            if r["template"] == "upi":
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
        ruleset = RuleSet.model_validate_json((REPO_ROOT / "data" / "rulesets" / "acme_v1.json").read_text())
        fired = {rule for r in generated[1] for rule in r["expected_rules"]}
        assert fired <= {r.id for r in ruleset.rules} and len(fired) >= 4

    def test_smoke_subset_has_a_duplicate_and_a_upi_pair(self, generated) -> None:
        out, rows = generated
        smoke = {f for c in json.loads((out / "manifest.json").read_text())["claims"] if c["smoke"] for f in c["fixtures"]}
        tags = {t for r in rows if r["id"] in smoke for t in r["scenario"]}
        assert {"dup_exact", "upi_pair", "meals_cap", "decoy"} <= tags

    def test_number_formatting(self) -> None:
        assert inr(123456.5) == "1,23,456.50"
        assert inr(999) == "999.00" and inr(-1200, 0) == "-1,200"
        assert words(0) == "zero" and words(115) == "one hundred fifteen"
        assert words(1234567) == "twelve lakh thirty-four thousand five hundred sixty-seven"
        assert amount_words(6608.5) == "Rupees Six Thousand Six Hundred Eight and Fifty Paise Only"
