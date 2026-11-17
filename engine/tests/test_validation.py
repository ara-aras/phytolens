"""Validation harness: metric maths, case files, corpus bias, one live case."""
from __future__ import annotations

import pytest

from engine import validation as v


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
def test_metrics_counts_ranks_and_misses():
    names = ["A", "B", "C", "D", "E"]
    m = v.metrics(names, ["B", "D", "Z"], ks=(1, 3))
    assert m["n_known_actives"] == 3
    assert m["n_found"] == 2
    assert m["ranks"] == {"B": 2, "D": 4}
    assert m["recall_at_1"] == 0.0
    assert m["recall_at_3"] == pytest.approx(1 / 3, abs=1e-3)
    assert m["mrr"] == pytest.approx((1 / 2 + 1 / 4) / 3, abs=1e-3)
    assert m["unranked"] == ["Z"]


def test_metrics_are_case_insensitive_and_ignore_duplicates():
    m = v.metrics(["curcumin", "Eugenol"], ["Curcumin", "curcumin"])
    assert m["n_known_actives"] == 1
    assert list(m["ranks"].values()) == [1]


def test_alias_does_not_inflate_the_active_count():
    m = v.metrics_for_groups(
        ["AKBA", "Filler"],
        [["3-Acetyl-11-keto-beta-boswellic acid", "AKBA"]],
    )
    assert m["n_known_actives"] == 1
    assert m["ranks"] == {"3-Acetyl-11-keto-beta-boswellic acid": 1}


def test_metrics_empty_ranking_is_not_an_error():
    m = v.metrics([], ["A"])
    assert m["recall_at_10"] == 0.0
    assert m["mrr"] == 0.0
    assert m["best_rank"] is None


# --------------------------------------------------------------------------
# cases
# --------------------------------------------------------------------------
def test_case_files_load_and_cover_the_case_set():
    cases = {c.name: c for c in v.load_cases()}
    assert set(cases) == {"boswellia_serrata", "curcuma_longa",
                          "piper_nigrum", "withania_somnifera"}
    for case in cases.values():
        assert case.known_actives
        assert case.condition in {"colitis", "ibd"}
        assert case.solvent == "ethanol"
        assert case.rationale, f"{case.name} has no stated rationale"


def test_known_actives_exist_in_the_corpus():
    import sqlite3
    from engine.pipeline import extraction as ex

    con = sqlite3.connect(ex.DB_PATH)
    try:
        corpus = {n.lower() for (n,) in con.execute("SELECT name FROM compounds")}
        for case in v.load_cases():
            for active in case.known_actives:
                assert active["name"].lower() in corpus, (
                    f"{case.name}: {active['name']} is not in the corpus, "
                    "so the case cannot be scored"
                )
    finally:
        con.close()


# --------------------------------------------------------------------------
# bias
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def bias():
    return v.corpus_bias()


def test_corpus_bias_is_measured_not_hardcoded(bias):
    assert bias["eligible_groups"] > 1000
    assert 0.0 < bias["fraction"] < 1.0
    assert bias["topped_by_six"] <= bias["eligible_groups"]
    assert len(bias["six_compounds"]) == 6


# --------------------------------------------------------------------------
# controls
# --------------------------------------------------------------------------
def test_null_baseline_detects_a_perfect_ranking():
    names = [f"C{i}" for i in range(20)]
    result = v.null_baseline(names, [["C0"], ["C1"]], permutations=300)
    assert result["observed_mrr"] == pytest.approx((1.0 + 0.5) / 2)
    assert result["p_value_mrr"] < 0.05
    assert result["mrr_percentile"] > 0.95
    assert result["analytic_expected_mrr"] == pytest.approx(
        sum(1 / k for k in range(1, 21)) / 20, abs=1e-3)


def test_null_baseline_is_deterministic_for_a_seed():
    names = [f"C{i}" for i in range(12)]
    a = v.null_baseline(names, [["C3"]], permutations=100, seed=11)
    b = v.null_baseline(names, [["C3"]], permutations=100, seed=11)
    assert a == b


def test_bias_residue_counts_the_ubiquitous_six():
    top = ["Eugenol", "Curcumin", "Geraniol", "Filler"]
    payload = v.bias_residue(top, k=4)
    assert payload["count"] == 2
    assert payload["six_in_top"] == ["eugenol", "geraniol"]
    assert payload["fraction"] == pytest.approx(0.5)


# --------------------------------------------------------------------------
# live case
# --------------------------------------------------------------------------
@pytest.mark.slow
def test_curcuma_case_runs_and_reports_metrics():
    case = v.get_case("curcuma_longa")
    payload = v.run_case(case, docking_scores=None, write=False)
    m = payload["metrics"]
    assert payload["run"]["docking_pending"] is True
    assert 0 <= m["recall_at_10"] <= 1
    assert 0 <= m["recall_at_25"] <= 1
    assert 0 <= m["mrr"] <= 1
    assert payload["top_10"][0]["rank"] == 1


@pytest.mark.slow
def test_case_payload_carries_ablation_and_null_baseline():
    case = v.get_case("curcuma_longa")
    payload = v.run_case(case, docking_scores=v.load_docking(), write=False)
    assert payload["run"]["docking_pending"] is False
    assert payload["ablation"]["with_docking"]["mrr"] == payload["metrics"]["mrr"]
    assert payload["ablation"]["annotation_only"]["n_found"] >= 1
    assert payload["null_baseline"]["permutations"] == 1000
    assert 0.0 <= payload["null_baseline"]["p_value_mrr"] <= 1.0
    assert payload["bias_residue"]["k"] == 10
    # Docking is the term under test; the ablation must actually differ.
    assert payload["ablation"]["delta_mrr"] > 0
