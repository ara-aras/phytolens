"""Ranking-stage tests: gate, terms, docking profile, determinism."""
from __future__ import annotations

import json

import pytest

from engine.pipeline import extraction as ex
from engine.pipeline import ranking as rk


@pytest.fixture(scope="module")
def ranking_config():
    import yaml
    return yaml.safe_load(rk.RANKING_CONFIG.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def condition():
    return rk.load_condition("colitis")


def compound(name="Test", mw=300.0, logp=2.0):
    return ex.Compound(id=name.upper(), name=name, mw=mw, logp=logp)


def targets(all_genes, measured_genes=None):
    measured = set(measured_genes if measured_genes is not None else all_genes)
    return rk.CompoundTargets(all_genes=set(all_genes),
                              measured_genes=set(measured))


# --------------------------------------------------------------------------
# gate
# --------------------------------------------------------------------------
def test_compound_without_condition_target_is_gated(ranking_config, condition):
    ct = targets({"NOT_IN_CONDITION_XYZ"})
    assert rk.score_compound(compound(), ct, condition, (), ranking_config) is None


def test_one_condition_target_is_enough(ranking_config, condition):
    gene = next(iter(condition.genes))
    scored = rk.score_compound(compound(), targets({gene}), condition, (), ranking_config)
    assert scored is not None
    assert scored.overlap_all == [gene]


# --------------------------------------------------------------------------
# docking profile
# --------------------------------------------------------------------------
def test_single_float_docking_is_accepted(ranking_config, condition):
    gene = next(iter(condition.genes))
    scored = rk.score_compound(compound(), targets({gene}), condition, (),
                               ranking_config, docking=-8.0)
    assert "docking" in scored.terms
    assert 0.0 < scored.terms["docking"] < 1.0


def test_per_target_docking_averages_normalised_scores(ranking_config, condition):
    gene = next(iter(condition.genes))
    strong = rk.score_compound(compound(), targets({gene}), condition, (),
                               ranking_config,
                               docking={"PTGS2": -9.0, "ALOX5": -5.0})
    weak = rk.score_compound(compound(), targets({gene}), condition, (),
                             ranking_config,
                             docking={"PTGS2": -6.0, "ALOX5": -6.0})
    assert strong.terms["docking"] == pytest.approx(0.5)
    assert weak.terms["docking"] == pytest.approx(0.25)
    assert strong.docking == {"ALOX5": -5.0, "PTGS2": -9.0}


def test_missing_docking_renormalises_weights(ranking_config, condition):
    gene = next(iter(condition.genes))
    scored = rk.score_compound(compound(), targets({gene}), condition, (),
                               ranking_config)
    assert "docking" not in scored.terms
    assert sum(scored.contributions.values()) == pytest.approx(scored.score)


def test_docking_stronger_than_window_clamps(ranking_config, condition):
    gene = next(iter(condition.genes))
    scored = rk.score_compound(compound(), targets({gene}), condition, (),
                               ranking_config, docking=-99.0)
    assert scored.terms["docking"] == 1.0


def test_predicted_only_links_reduce_evidence(ranking_config, condition):
    gene = next(iter(condition.genes))
    rk.PREDICTED.add("NPASS")
    measured = rk.score_compound(compound(), targets({gene}), condition, (),
                                 ranking_config)
    predicted = rk.score_compound(compound(), targets({gene}, set()), condition, (),
                                  ranking_config)
    assert measured.terms["evidence"] == 1.0
    assert predicted.terms["evidence"] == 0.0


# --------------------------------------------------------------------------
# stage
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def ranked():
    return rk.run("Curcuma longa", "rhizome", "ethanol", "colitis", top=10)


def test_ranked_is_descending_by_score(ranked):
    scores = [s.score for s in ranked.ranked]
    assert scores == sorted(scores, reverse=True)
    assert [s.rank for s in ranked.ranked] == list(range(1, len(ranked.ranked) + 1))


def test_summary_shape_and_provenance_keys(ranked):
    payload = ranked.summary()
    assert payload["funnel"]["in_part"] == 168
    assert payload["docking_pending"] is True
    for row in payload["ranked"]:
        assert {"id", "targets", "overlap", "terms", "docking"} <= set(row)
        for gene in row["overlap"]["genes"]:
            assert {"symbol", "condition_score", "measured", "evidence"} <= set(gene)


def test_summary_is_json_serialisable(ranked):
    assert '"ranking"' in json.dumps(ranked.summary(), allow_nan=False)


def test_top_limits_rows_but_keeps_candidate_count(ranked):
    full = rk.run("Curcuma longa", "rhizome", "ethanol", "colitis")
    assert len(full.ranked) > len(ranked.ranked)
    assert full.n_candidates == len(full.ranked)


def test_same_inputs_same_order():
    a = rk.run("Curcuma longa", "rhizome", "ethanol", "colitis", top=15)
    b = rk.run("Curcuma longa", "rhizome", "ethanol", "colitis", top=15)
    assert [s.compound.id for s in a.ranked] == [s.compound.id for s in b.ranked]
    assert [round(s.score, 12) for s in a.ranked] == [round(s.score, 12) for s in b.ranked]


def test_docking_coverage_distinguishes_partial_from_complete():
    base = rk.run("Curcuma longa", "rhizome", "ethanol", "colitis", top=5)
    first = base.ranked[0].compound.id
    partial = rk.run("Curcuma longa", "rhizome", "ethanol", "colitis", top=5,
                     docking_scores={first: {"PTGS2": -8.0}})
    info = partial.summary()["docking"]
    assert info["candidates"] == partial.n_candidates
    assert info["docked"] == 1
    assert info["partial"] is True

    none = base.summary()["docking"]
    assert none == {"candidates": base.n_candidates, "docked": 0, "partial": False}


def test_unknown_condition_lists_available():
    with pytest.raises(LookupError) as exc:
        rk.load_condition("no_such_condition")
    assert "colitis" in str(exc.value)
