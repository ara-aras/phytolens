"""
Regression pins for the extraction stage.

The first test in this file is the one that matters. It exists because an
earlier version of the pipeline used `-0.5 <= logP <= 5.0` for ethanol and
silently deleted every boswellic acid from Boswellia serrata -- the entire
anti-inflammatory fraction of the plant -- while keeping 36 volatile
monoterpenes. That is the failure this suite is here to prevent from coming
back.

Run: python -m pytest engine/tests -q
"""
from __future__ import annotations

import copy

import pytest

from engine.pipeline import extraction as ex

BOSWELLIC_ACIDS = [
    "beta-Boswellic acid",
    "alpha-Boswellic acid",
    "11-Keto-beta-boswellic acid",
    "3-Acetyl-beta-boswellic acid",
    "3-Acetyl-11-keto-beta-boswellic acid",
]


@pytest.fixture(scope="module")
def config():
    return ex.load_config()


@pytest.fixture(scope="module")
def boswellia(config):
    return ex.run("Boswellia serrata", "exudate", "ethanol")


@pytest.fixture(scope="module")
def curcuma(config):
    return ex.run("Curcuma longa", "rhizome", "ethanol")


def kept_names(result):
    return {v.compound.name for v in result.kept}


# --------------------------------------------------------------------------
# the pin
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", BOSWELLIC_ACIDS)
def test_boswellic_acids_survive_ethanol_extraction(boswellia, name):
    """All five boswellic acids must survive 70% ethanol. This is the pin."""
    assert name in kept_names(boswellia), (
        f"{name} was dropped: "
        f"{[v.reasons for v in boswellia.dropped if v.compound.name == name]}"
    )


def test_all_five_boswellic_acids_present_in_corpus(boswellia):
    """Guard against the pin passing because the compounds vanished upstream."""
    found = {v.compound.name for v in boswellia.verdicts if "oswellic" in v.compound.name}
    assert found == set(BOSWELLIC_ACIDS), f"corpus changed: {sorted(found)}"


def test_boswellic_acids_are_flagged_not_dropped(boswellia):
    """AKBA violates Lipinski twice. It must be flagged and still kept."""
    akba = next(v for v in boswellia.kept
                if v.compound.name == "3-Acetyl-11-keto-beta-boswellic acid")
    assert "lipinski_mw>500" in akba.flags
    assert "lipinski_logp>5" in akba.flags
    assert akba.kept is True


def test_old_narrow_window_would_have_lost_them(config):
    """Documents Finding 1 so the threshold cannot be quietly tightened back."""
    narrow = copy.deepcopy(config)
    narrow["extraction"]["solvents"]["ethanol"]["logp_min"] = -0.5
    narrow["extraction"]["solvents"]["ethanol"]["logp_max"] = 5.0

    con = ex.sqlite3.connect(ex.DB_PATH)
    try:
        pid, _ = ex.resolve_plant(con, "Boswellia serrata")
        compounds = ex.load_compounds(con, pid, "exudate")
    finally:
        con.close()

    verdicts = ex.evaluate_all(compounds, narrow, "ethanol")
    kept = {v.compound.name for v in verdicts if v.kept}
    for name in BOSWELLIC_ACIDS:
        assert name not in kept, f"{name} unexpectedly survived the narrow window"
    # ...and what survived instead is the volatile fraction.
    assert "Geraniol" in kept


# --------------------------------------------------------------------------
# solvent behaviour is real chemistry, not a free pass
# --------------------------------------------------------------------------
def test_water_correctly_excludes_boswellic_acids(boswellia):
    """Widening ethanol must not make the water window meaningless."""
    con = ex.sqlite3.connect(ex.DB_PATH)
    try:
        pid, _ = ex.resolve_plant(con, "Boswellia serrata")
        compounds = ex.load_compounds(con, pid, "exudate")
    finally:
        con.close()

    config = ex.load_config()
    verdicts = ex.evaluate_all(compounds, config, "water")
    kept = {v.compound.name for v in verdicts if v.kept}
    for name in BOSWELLIC_ACIDS:
        assert name not in kept


def test_unknown_solvent_is_an_error(config):
    with pytest.raises(KeyError):
        ex.solvent_spec(config, "dmso")


# --------------------------------------------------------------------------
# the demo plant
# --------------------------------------------------------------------------
def test_curcumin_survives_with_no_flags(curcuma):
    cur = next(v for v in curcuma.verdicts if v.compound.name == "Curcumin")
    assert cur.kept
    assert cur.flags == ()


def test_curcuma_rhizome_is_fully_solvent_compatible(curcuma):
    """168 in, 168 out. Turmeric in ethanol is not chemistry-limited.

    This is a finding, not a failure: the useful cut for this formulation has
    to come from biology (target overlap) and docking, not from logP.
    """
    assert len(curcuma.verdicts) == 168
    assert len(curcuma.kept) == 168


# --------------------------------------------------------------------------
# rule mechanics
# --------------------------------------------------------------------------
def test_mw_ceiling_is_enforced(config):
    heavy = ex.Compound(id="X", name="heavy", mw=900.0, logp=3.0)
    assert ex.evaluate(heavy, config, "ethanol").reasons == ("mw_above_700",)


def test_missing_properties_do_not_silently_pass(config):
    blank = ex.Compound(id="Y", name="blank")
    v = ex.evaluate(blank, config, "ethanol")
    assert v.kept is False
    assert "logp_missing" in v.reasons
    assert "mw_missing" in v.reasons


def test_funnel_is_monotonic(boswellia):
    prev = None
    for step in boswellia.funnel:
        assert step["output"] <= step["input"]
        if prev is not None:
            assert step["input"] == prev
        prev = step["output"]


def test_config_hash_is_stable_and_short():
    a, b = ex.config_hash(), ex.config_hash()
    assert a == b
    assert len(a) == 12


def test_summary_is_json_serialisable(boswellia):
    import json
    payload = json.dumps(boswellia.summary())
    assert '"config_hash"' in payload
