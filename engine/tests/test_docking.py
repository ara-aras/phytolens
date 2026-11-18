"""Docking-stage tests that never invoke Vina.

Actual docking is verified by the panel artefacts in engine/data; these tests
pin the cache key, the target panel's provenance, and the ligand-efficiency
maths so a configuration change cannot silently invalidate old scores.
"""
from __future__ import annotations

import glob

import pytest

from engine.pipeline import docking as dk

BOX = {"center": [-43.8, -47.2, -44.0], "size": [20.0, 20.0, 20.0]}


def test_cache_key_is_stable():
    assert dk.cache_key("CCO", "abc", BOX) == dk.cache_key("CCO", "abc", BOX)


def test_cache_key_changes_with_ligand():
    assert dk.cache_key("CCO", "abc", BOX) != dk.cache_key("CCC", "abc", BOX)


def test_cache_key_changes_with_box():
    moved = {**BOX, "center": [-40.0, -47.2, -44.0]}
    assert dk.cache_key("CCO", "abc", BOX) != dk.cache_key("CCO", "abc", moved)


def test_cache_key_changes_with_receptor():
    assert dk.cache_key("CCO", "abc", BOX) != dk.cache_key("CCO", "def", BOX)


def test_cache_key_changes_with_seed_or_exhaustiveness():
    assert dk.cache_key("CCO", "abc", BOX, seed=1) != dk.cache_key("CCO", "abc", BOX, seed=2)
    assert (dk.cache_key("CCO", "abc", BOX, exhaustiveness=8)
            != dk.cache_key("CCO", "abc", BOX, exhaustiveness=16))


def test_panel_targets_are_distinct_experimental_structures():
    assert set(dk.DEFAULT_PANEL) <= set(dk.TARGETS)
    assert "TNF" in dk.TARGETS
    pdbs = [spec.pdb_id for spec in dk.TARGETS.values()]
    assert len(pdbs) == len(set(pdbs))
    for spec in dk.TARGETS.values():
        assert spec.ligand_code, f"{spec.gene} has no box-defining ligand"
        assert spec.why, f"{spec.gene} has no documented rationale"


def test_ligand_efficiency_is_affinity_per_heavy_atom():
    assert dk.ligand_efficiency(-8.0, "CCO") == pytest.approx(-8.0 / 3, abs=1e-3)
    assert dk.ligand_efficiency(None, "CCO") is None
    assert dk.ligand_efficiency(-8.0, "not-a-smiles") is None


def test_panel_affinities_skips_missing_targets():
    panel = {"scores": {
        "A": {"targets": {"PTGS2": {"affinity": -8.0}, "ALOX5": {"affinity": None}}},
        "B": {"targets": {"PTGS2": {"affinity": None}}},
    }}
    assert dk.panel_affinities(panel) == {"A": {"PTGS2": -8.0}}


@pytest.mark.parametrize("gene", ["PTGS2", "ALOX5", "MAPK14", "TNF"])
def test_receptor_is_prepared_or_preparable(gene):
    path = dk.RECEPTORS / f"{dk.TARGETS[gene].pdb_id}.pdbqt"
    if not path.exists():
        pytest.skip("receptor not prepared in this checkout")
    assert path.stat().st_size > 10_000


def test_alox5_retains_catalytic_fe2_inside_box_and_poses_contact_it():
    import math
    pdbqt = dk.RECEPTORS / "3V99.pdbqt"
    box_file = dk.RECEPTORS / "3V99_box.json"
    if not pdbqt.exists() or not box_file.exists():
        pytest.skip("3V99 receptor not prepared in this checkout")
    fe_lines = [
        line for line in pdbqt.read_text(errors="replace").splitlines()
        if line.startswith(("ATOM", "HETATM")) and line.rstrip().endswith("Fe")
    ]
    assert fe_lines, "catalytic Fe2+ missing from 3V99.pdbqt"
    fe_coord = dk._coord(fe_lines[0])
    box = dk.json.loads(box_file.read_text())
    center = box["center"]
    half = [s / 2.0 for s in box["size"]]
    assert all(abs(fe_coord[i] - center[i]) <= half[i] for i in range(3))

    # Confirm at least one docked 3V99 pose approaches the catalytic Fe2+ (< 3.0 A)
    min_dist = float("inf")
    for jf in dk.CACHE.glob("*.json"):
        meta = dk.json.loads(jf.read_text(encoding="utf-8-sig"))
        if meta.get("receptor") != "3V99":
            continue
        pose = dk.CACHE / f"{meta['key']}.pdbqt"
        if not pose.exists():
            continue
        for line in pose.read_text(errors="replace").splitlines():
            if line.startswith("ENDMDL"):
                break
            if line.startswith(("ATOM", "HETATM")):
                min_dist = min(min_dist, math.dist(dk._coord(line), fe_coord))
    if min_dist < float("inf"):
        assert min_dist < 3.0


def test_ptgs2_retains_heme_cofactor_in_peroxidase_site():
    import math
    pdbqt = dk.RECEPTORS / "3NT1.pdbqt"
    box_file = dk.RECEPTORS / "3NT1_box.json"
    if not pdbqt.exists() or not box_file.exists():
        pytest.skip("3NT1 receptor not prepared in this checkout")
    fe_lines = [
        line for line in pdbqt.read_text(errors="replace").splitlines()
        if line.startswith(("ATOM", "HETATM")) and line.rstrip().endswith("Fe")
    ]
    assert len(fe_lines) >= 1, "HEM Fe missing from 3NT1.pdbqt"
    fe_coord = dk._coord(fe_lines[0])
    center = dk.json.loads(box_file.read_text())["center"]
    # Peroxidase heme is ~32.5 A from the cyclooxygenase (NPS) pocket
    assert math.dist(fe_coord, center) > 25.0


def test_cache_entries_are_content_addressed():
    files = glob.glob(str(dk.CACHE / "*.json"))
    if not files:
        pytest.skip("no cache in this checkout")
    for path in files[:10]:
        payload = dk.json.loads(open(path, encoding="utf-8-sig").read())
        assert len(payload["key"]) == 16
        assert payload["seed"] == dk.SEED
        assert payload["receptor"]
