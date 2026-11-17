"""
Build the PhytoLens corpus database from IMPPAT 2.0 bulk TSV dumps.

This is the W0 "data lock" step: turn the four published TSVs into one queryable
SQLite database with properties precomputed, so every later stage is a pure
function over local data.

Source:  IMPPAT 2.0  (https://cb.imsc.res.in/imppat/)
Licence: CC BY-NC-ND 4.0 -- academic/non-commercial, no derivatives.
         This database is for the hackathon demo only. Commercial use requires
         an IMPPAT licence or replacement of this source. See docs/BACKEND_SPEC.md.

Run:  python engine/build_corpus.py
Out:  engine/data/phytolens.db
"""
from __future__ import annotations

import csv
import os
import sqlite3
import sys
from collections import Counter, defaultdict

from rdkit import Chem, RDLogger
from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors

RDLogger.DisableLog("rdApp.*")

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, "data", "raw", "imppat")
DB = os.path.join(ROOT, "data", "phytolens.db")

# IMPPAT's 34 raw plant-part strings -> a canonical vocabulary we can filter on.
# "unspecified" is a real, reportable value: 22% of associations carry no part.
PART_CANON = {
    "leaf": "leaf",
    "flower": "flower",
    "fruit": "fruit",
    "seed": "seed",
    "root": "root",
    "rhizome": "rhizome",
    "stem": "stem",
    "bark": "bark",
    "wood": "wood",
    "whole plant": "whole_plant",
    "whole plant excluding woody parts": "whole_plant",
    "whole plant excluding root": "whole_plant",
    "whole plant excluding seeds": "whole_plant",
    "aerial part": "aerial_part",
    "shoot": "aerial_part",
    "seedling": "aerial_part",
    "plant exudate": "exudate",
    "latex": "exudate",
    "plant cells/culture": "culture",
    "underground part": "underground_part",
    "tuber": "underground_part",
    "bulb": "underground_part",
    "sucker": "underground_part",
    "reproductive organ": "reproductive_organ",
    "gnarl": "unspecified",
    "gall": "unspecified",
    "vegetable": "unspecified",
    "mixed": "unspecified",
    "plant fibers": "unspecified",
    "trichome": "unspecified",
    "epicuticular wax": "unspecified",
    "tendril": "unspecified",
    "cuticle": "unspecified",
}

SCHEMA = """
DROP TABLE IF EXISTS plants;
CREATE TABLE plants (
    id              TEXT PRIMARY KEY,
    canonical_name  TEXT NOT NULL,
    family          TEXT,
    common_name     TEXT,
    systems         TEXT
);

DROP TABLE IF EXISTS plant_aliases;
CREATE TABLE plant_aliases (
    plant_id  TEXT NOT NULL,
    alias     TEXT NOT NULL,
    alias_type TEXT NOT NULL,
    PRIMARY KEY (plant_id, alias, alias_type)
);

DROP TABLE IF EXISTS compounds;
CREATE TABLE compounds (
    id           TEXT PRIMARY KEY,
    name         TEXT,
    inchikey     TEXT,
    inchikey14   TEXT,
    smiles       TEXT,
    pubchem_cid  TEXT,
    chembl_id    TEXT,
    formula      TEXT,
    mw           REAL,
    logp         REAL,
    tpsa         REAL,
    hbd          INTEGER,
    hba          INTEGER,
    rotb         INTEGER,
    parse_ok     INTEGER NOT NULL DEFAULT 0
);

DROP TABLE IF EXISTS plant_compounds;
CREATE TABLE plant_compounds (
    plant_id     TEXT NOT NULL,
    part_raw     TEXT,
    part         TEXT NOT NULL,
    compound_id  TEXT NOT NULL,
    reference    TEXT,
    PRIMARY KEY (plant_id, part, compound_id)
);

DROP TABLE IF EXISTS compound_targets;
CREATE TABLE compound_targets (
    compound_id  TEXT NOT NULL,
    gene_symbol  TEXT NOT NULL,
    ensembl_id   TEXT,
    entrez_id    TEXT,
    source       TEXT,
    PRIMARY KEY (compound_id, gene_symbol)
);

CREATE INDEX idx_pc_plant   ON plant_compounds(plant_id, part);
CREATE INDEX idx_pc_comp    ON plant_compounds(compound_id);
CREATE INDEX idx_pc_part    ON plant_compounds(part);
CREATE INDEX idx_ct_comp    ON compound_targets(compound_id);
CREATE INDEX idx_ct_gene    ON compound_targets(gene_symbol);
CREATE INDEX idx_comp_inch  ON compounds(inchikey14);
CREATE INDEX idx_alias      ON plant_aliases(alias);
"""


def read_tsv(name: str):
    path = os.path.join(RAW, name)
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        yield from csv.DictReader(fh, delimiter="\t")


def compute_props(smiles: str) -> dict:
    """RDKit properties. Returns parse_ok=0 for anything RDKit rejects."""
    empty = dict(
        formula=None, mw=None, logp=None, tpsa=None,
        hbd=None, hba=None, rotb=None, inchikey14=None, parse_ok=0,
    )
    if not smiles or not smiles.strip():
        return empty
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return empty
    return dict(
        formula=rdMolDescriptors.CalcMolFormula(mol),
        mw=round(Descriptors.MolWt(mol), 2),
        logp=round(Crippen.MolLogP(mol), 3),
        tpsa=round(rdMolDescriptors.CalcTPSA(mol), 2),
        hbd=Lipinski.NumHDonors(mol),
        hba=Lipinski.NumHAcceptors(mol),
        rotb=Lipinski.NumRotatableBonds(mol),
        inchikey14=Chem.MolToInchiKey(mol)[:14] if Chem.MolToInchiKey(mol) else None,
        parse_ok=1,
    )


def build() -> None:
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)

    # ---- plants + aliases -------------------------------------------------
    plants, aliases = [], []
    for r in read_tsv("Plant_Information_IMPPAT.tsv"):
        pid = r["Plant_identifier"].strip()
        sci = (r["Indian_Medicinal_plant"] or "").strip()
        common = (r.get("Common_name") or "").strip()
        plants.append((pid, sci, (r.get("Family") or "").strip(), common,
                       (r.get("System_of_Medicine") or "").strip()))
        aliases.append((pid, sci, "scientific"))
        if common:
            aliases.append((pid, common, "common"))
        for syn in (r.get("Synonymous names") or "").split("|"):
            syn = syn.strip()
            if syn and syn.lower() != sci.lower():
                aliases.append((pid, syn, "synonym"))
    con.executemany("INSERT OR IGNORE INTO plants VALUES (?,?,?,?,?)", plants)
    con.executemany("INSERT OR IGNORE INTO plant_aliases VALUES (?,?,?)", aliases)

    # ---- compounds --------------------------------------------------------
    comps = []
    parse_fail = 0
    for r in read_tsv("Chemical_Information_IMPPAT_Phytochemicals.tsv"):
        cid = r["IMPPAT_Phytochemical_identifier"].strip()
        smiles = (r.get("Canonical_SMILES") or "").strip()
        props = compute_props(smiles)
        if smiles and not props["parse_ok"]:
            parse_fail += 1
        comps.append((
            cid,
            (r.get("Phytochemical name_standardised") or "").strip(),
            (r.get("InChIKey") or "").strip(),
            props["inchikey14"],
            smiles,
            (r.get("Pubchem_CID") or "").strip(),
            (r.get("ChEMBL") or "").strip(),
            props["formula"], props["mw"], props["logp"], props["tpsa"],
            props["hbd"], props["hba"], props["rotb"], props["parse_ok"],
        ))
    con.executemany("INSERT OR REPLACE INTO compounds VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", comps)

    # ---- plant <-> compound, with part ------------------------------------
    assoc, part_ct = [], Counter()
    for r in read_tsv("IMPPAT_Phytochemical_Plant_Association.tsv"):
        raw = (r["Plant_part"] or "").strip().lower()
        part = PART_CANON.get(raw, "unspecified")
        part_ct[part] += 1
        assoc.append((r["Plant_identifier"].strip(), raw, part,
                      r["IMPPAT_Phytochemical_identifier"].strip(),
                      (r.get("Reference_identifier") or "").strip()))
    con.executemany("INSERT OR IGNORE INTO plant_compounds VALUES (?,?,?,?,?)", assoc)

    # ---- compound -> target ----------------------------------------------
    targs = []
    for r in read_tsv("Target_IMPPAT_Phytochemicals.tsv"):
        targs.append((
            r["IMPPAT_Phytochemical_identifier"].strip(),
            r["HGNC_Symbol"].strip(),
            (r.get("Gene_identifier") or "").strip(),
            (r.get("Entrez gene identifier") or "").strip(),
            (r.get("Source") or "").strip(),
        ))
    con.executemany("INSERT OR IGNORE INTO compound_targets VALUES (?,?,?,?,?)", targs)

    con.commit()

    # ---- report -----------------------------------------------------------
    q = lambda s: con.execute(s).fetchone()[0]
    print("=" * 62)
    print("PhytoLens corpus built:", DB)
    print("=" * 62)
    print(f"plants                 {q('SELECT COUNT(*) FROM plants'):>8,}")
    print(f"plant aliases          {q('SELECT COUNT(*) FROM plant_aliases'):>8,}")
    print(f"compounds              {q('SELECT COUNT(*) FROM compounds'):>8,}")
    print(f"  RDKit parse failures {parse_fail:>8,}")
    print(f"  with InChIKey        {q('SELECT COUNT(*) FROM compounds WHERE inchikey14 IS NOT NULL'):>8,}")
    print(f"plant-compound rows    {q('SELECT COUNT(*) FROM plant_compounds'):>8,}")
    print(f"compound-target rows   {q('SELECT COUNT(*) FROM compound_targets'):>8,}")
    print(f"  compounds w/ targets {q('SELECT COUNT(DISTINCT compound_id) FROM compound_targets'):>8,}")
    print(f"  distinct genes       {q('SELECT COUNT(DISTINCT gene_symbol) FROM compound_targets'):>8,}")
    print()
    print("part coverage (canonical):")
    for part, n in part_ct.most_common():
        print(f"  {part:<18} {n:>7,}")
    con.close()


if __name__ == "__main__":
    build()
