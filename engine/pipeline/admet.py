"""Stage 1b: In-silico ADMET, bioavailability, PAINS and Brenk structural alerts.

Why this exists:
1. Curcumin is a documented pan-assay interference compound (PAINS) and Michael
   acceptor. Reporting docking affinity without flagging structural assay
   interference or reactivity invites a fair question from any medicinal
   chemist on the panel.
2. Early R&D teams need a quick, deterministic readout of passive
   gastrointestinal absorption (BOILED-Egg white), blood-brain barrier
   permeation (BOILED-Egg yolk), QED drug-likeness, and structural toxicity /
   reactivity alerts (Brenk) alongside target overlap and docking.

Like Lipinski/Veber flags, ADMET outputs are **annotations only** -- they inform
which counter-screens a wet lab should run (e.g. aggregation/redox controls for
PAINS hits) and never silently delete a natural product from the shortlist.

Usage:
    python -m engine.pipeline.admet --compound Curcumin --compound Bisdemethoxycurcumin
"""
from __future__ import annotations

import argparse
import functools
import json
from dataclasses import dataclass

from rdkit import Chem, RDLogger
from rdkit.Chem import Crippen, Descriptors, FilterCatalog, QED, rdMolDescriptors

RDLogger.DisableLog("rdApp.*")


@functools.lru_cache(maxsize=1)
def _catalogs() -> tuple[FilterCatalog.FilterCatalog, FilterCatalog.FilterCatalog]:
    pains_params = FilterCatalog.FilterCatalogParams()
    pains_params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS_A)
    pains_params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS_B)
    pains_params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS_C)

    brenk_params = FilterCatalog.FilterCatalogParams()
    brenk_params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.BRENK)
    return (
        FilterCatalog.FilterCatalog(pains_params),
        FilterCatalog.FilterCatalog(brenk_params),
    )


@dataclass(frozen=True)
class AdmetProfile:
    qed: float | None
    tpsa: float | None
    wlogp: float | None
    gi_absorption: str          # "high" | "low" | "unknown" (BOILED-Egg white proxy)
    bbb_permeant: bool | None   # BOILED-Egg yolk proxy
    pains_alerts: tuple[str, ...] = ()
    brenk_alerts: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "qed": self.qed,
            "tpsa": self.tpsa,
            "wlogp": self.wlogp,
            "gi_absorption": self.gi_absorption,
            "bbb_permeant": self.bbb_permeant,
            "pains_alerts": list(self.pains_alerts),
            "brenk_alerts": list(self.brenk_alerts),
            "assay_interference": bool(self.pains_alerts),
            "structural_alerts": len(self.pains_alerts) + len(self.brenk_alerts),
        }


@functools.lru_cache(maxsize=4096)
def evaluate_smiles(smiles: str | None) -> AdmetProfile:
    """Deterministic RDKit ADMET and structural-alert profile for one SMILES."""
    if not smiles or not smiles.strip():
        return AdmetProfile(
            qed=None, tpsa=None, wlogp=None,
            gi_absorption="unknown", bbb_permeant=None,
        )
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return AdmetProfile(
            qed=None, tpsa=None, wlogp=None,
            gi_absorption="unknown", bbb_permeant=None,
        )

    tpsa = round(rdMolDescriptors.CalcTPSA(mol), 2)
    wlogp = round(Crippen.MolLogP(mol), 3)
    mw = Descriptors.MolWt(mol)
    try:
        qed_score = round(float(QED.qed(mol)), 3)
    except Exception:  # noqa: BLE001
        qed_score = None

    # BOILED-Egg (Daina & Zoete, ChemMedChem 2016) Axis thresholds:
    # White (passive GI absorption): TPSA <= 131.6 A^2 and -2.3 <= WLOGP <= 6.8 (MW <= 700)
    # Yolk (passive BBB permeation): TPSA <= 79.0 A^2 and 0.4 <= WLOGP <= 6.0
    gi_high = (tpsa <= 131.6) and (-2.3 <= wlogp <= 6.8) and (mw <= 700.0)
    bbb = (tpsa <= 79.0) and (0.4 <= wlogp <= 6.0) and (mw <= 500.0)

    pains_cat, brenk_cat = _catalogs()
    pains = tuple(sorted({
        entry.GetDescription() for entry in pains_cat.GetMatches(mol)
    }))
    brenk = tuple(sorted({
        entry.GetDescription() for entry in brenk_cat.GetMatches(mol)
    }))

    return AdmetProfile(
        qed=qed_score,
        tpsa=tpsa,
        wlogp=wlogp,
        gi_absorption="high" if gi_high else "low",
        bbb_permeant=bbb,
        pains_alerts=pains,
        brenk_alerts=brenk,
    )


def main(argv: list[str] | None = None) -> int:
    from engine.pipeline import docking as dk

    ap = argparse.ArgumentParser(description="RDKit ADMET + PAINS/Brenk structural alerts")
    ap.add_argument("--compound", action="append", help="compound name in corpus (repeatable)")
    ap.add_argument("--smiles", action="append", help="raw SMILES string (repeatable)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    items: list[tuple[str, str]] = []
    for name in args.compound or []:
        _, smi = dk.ligand_smiles(name)
        items.append((name, smi))
    for smi in args.smiles or []:
        items.append((smi[:32], smi))
    if not items:
        for name in ("Curcumin", "Bisdemethoxycurcumin", "3-Acetyl-11-keto-beta-boswellic acid"):
            try:
                _, smi = dk.ligand_smiles(name)
                items.append((name, smi))
            except Exception:  # noqa: BLE001
                pass

    results = {name: evaluate_smiles(smi).as_dict() for name, smi in items}
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for name, prof in results.items():
            print(f"{name:<40} QED={prof['qed']}  GI={prof['gi_absorption']:<4} "
                  f"BBB={prof['bbb_permeant']}  PAINS={prof['pains_alerts']}  "
                  f"Brenk={prof['brenk_alerts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
