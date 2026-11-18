"""Tests for RDKit ADMET, BOILED-Egg absorption, and PAINS/Brenk structural alerts."""
from __future__ import annotations

from engine.pipeline import admet as adm


def test_curcumin_triggers_michael_acceptor_brenk_alert():
    curcumin_smiles = "COc1cc(/C=C/C(=O)CC(=O)/C=C/c2ccc(O)c(OC)c2)ccc1O"
    prof = adm.evaluate_smiles(curcumin_smiles).as_dict()
    assert prof["qed"] is not None and 0.4 < prof["qed"] < 0.7
    assert prof["gi_absorption"] == "high"
    assert prof["bbb_permeant"] is False
    assert "Michael_acceptor_1" in prof["brenk_alerts"]
    assert prof["structural_alerts"] >= 1


def test_quercetin_triggers_catechol_pains_alert():
    quercetin_smiles = "O=c1c(O)c(-c2ccc(O)c(O)c2)oc2cc(O)cc(O)c12"
    prof = adm.evaluate_smiles(quercetin_smiles).as_dict()
    assert prof["assay_interference"] is True
    assert any("catechol" in a.lower() for a in prof["pains_alerts"])


def test_akba_has_low_gi_and_zero_structural_alerts():
    akba_smiles = (
        "CC(=O)O[C@H]1CC[C@]2(C)[C@H]3C(=O)C=C4[C@@H]([C@]5(C)CC[C@H](C)"
        "[C@@H](C)[C@@H]5CC[C@@]4(C)[C@@]3(C)CC[C@@H]2[C@]1(C)C(=O)O)C"
    )
    prof = adm.evaluate_smiles(akba_smiles).as_dict()
    assert prof["gi_absorption"] == "low"
    assert prof["bbb_permeant"] is False
    assert prof["pains_alerts"] == []
    assert prof["brenk_alerts"] == []


def test_empty_or_invalid_smiles_returns_unknown_without_raising():
    assert adm.evaluate_smiles(None).gi_absorption == "unknown"
    assert adm.evaluate_smiles("").gi_absorption == "unknown"
    assert adm.evaluate_smiles("not-a-valid-smiles").gi_absorption == "unknown"
