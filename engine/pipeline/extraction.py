"""
Stage 1 of the PhytoLens pipeline: extraction and drug-likeness.

Two rules decide what a preparation can actually contain:

  1. solvent window   -- does this compound partition into ethanol/water/hexane?
  2. molecular-weight ceiling -- is it inside the range our docking box and
     permeability assumptions cover?

Drug-likeness (Lipinski / Veber) runs *after* both and produces FLAGS ONLY.
It never removes a compound. That is a deliberate design decision, documented
in ``config/extraction.yaml`` and pinned by tests: on Boswellia serrata a hard
Lipinski cut removes exactly one compound -- AKBA, the most-studied active --
and does nothing useful to the other 46.

Run:
    python -m engine.pipeline.extraction --plant "Curcuma longa" --part rhizome --solvent ethanol
    python -m engine.pipeline.extraction --plant "Boswellia serrata" --part exudate --solvent ethanol --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ENGINE_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ENGINE_DIR / "config" / "extraction.yaml"
DB_PATH = ENGINE_DIR / "data" / "phytolens.db"


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Compound:
    id: str
    name: str
    smiles: str | None = None
    mw: float | None = None
    logp: float | None = None
    tpsa: float | None = None
    hbd: int | None = None
    hba: int | None = None
    rotb: int | None = None


@dataclass(frozen=True)
class Verdict:
    """Why one compound survived or did not. Everything is reportable."""

    compound: Compound
    kept: bool
    reasons: tuple[str, ...] = ()   # why it was dropped, empty when kept
    flags: tuple[str, ...] = ()     # drug-likeness flags, never fatal

    def as_dict(self) -> dict:
        return {
            "id": self.compound.id,
            "name": self.compound.name,
            "kept": self.kept,
            "reasons": list(self.reasons),
            "flags": list(self.flags),
            "mw": self.compound.mw,
            "logp": self.compound.logp,
        }


@dataclass
class ExtractionResult:
    solvent: str
    solvent_label: str
    plant_id: str
    plant_name: str
    part: str
    config_hash: str
    verdicts: list[Verdict] = field(default_factory=list)
    funnel: list[dict] = field(default_factory=list)

    @property
    def kept(self) -> list[Verdict]:
        return [v for v in self.verdicts if v.kept]

    @property
    def dropped(self) -> list[Verdict]:
        return [v for v in self.verdicts if not v.kept]

    def summary(self) -> dict:
        return {
            "plant": {"id": self.plant_id, "name": self.plant_name},
            "part": self.part,
            "solvent": self.solvent,
            "solvent_label": self.solvent_label,
            "config_hash": self.config_hash,
            "counts": {
                "in_part": len(self.verdicts),
                "kept": len(self.kept),
                "dropped": len(self.dropped),
                "flagged": sum(1 for v in self.verdicts if v.flags),
            },
            "funnel": self.funnel,
            "compounds": [v.as_dict() for v in self.verdicts],
        }


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------
def load_config(path: str | Path = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def config_hash(path: str | Path = CONFIG_PATH) -> str:
    """Short content hash so a report can name the exact thresholds used."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def solvent_spec(config: dict, solvent: str) -> dict:
    solvents = config["extraction"]["solvents"]
    key = solvent.strip().lower()
    if key not in solvents:
        raise KeyError(
            f"unknown solvent {solvent!r}; configured: {', '.join(sorted(solvents))}"
        )
    return solvents[key]


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------
def check_solvent(c: Compound, spec: dict) -> str | None:
    """None if the compound can partition into this solvent, else a reason."""
    if c.logp is None:
        return "logp_missing"
    if c.logp < spec["logp_min"]:
        return f"logp_below_{spec['logp_min']}"
    if c.logp > spec["logp_max"]:
        return f"logp_above_{spec['logp_max']}"
    return None


def check_mw(c: Compound, ceiling: float) -> str | None:
    if c.mw is None:
        return "mw_missing"
    if c.mw > ceiling:
        return f"mw_above_{ceiling:g}"
    return None


def druglikeness_flags(c: Compound, config: dict) -> tuple[str, ...]:
    """Lipinski + Veber as flags. Never changes survival."""
    lip = config["druglikeness"]["lipinski"]
    veb = config["druglikeness"]["veber"]
    flags: list[str] = []
    if c.mw is not None and c.mw > lip["mw_max"]:
        flags.append(f"lipinski_mw>{lip['mw_max']}")
    if c.logp is not None and c.logp > lip["logp_max"]:
        flags.append(f"lipinski_logp>{lip['logp_max']:g}")
    if c.hbd is not None and c.hbd > lip["hbd_max"]:
        flags.append(f"lipinski_hbd>{lip['hbd_max']}")
    if c.hba is not None and c.hba > lip["hba_max"]:
        flags.append(f"lipinski_hba>{lip['hba_max']}")
    if c.rotb is not None and c.rotb > veb["rotb_max"]:
        flags.append(f"veber_rotb>{veb['rotb_max']}")
    if c.tpsa is not None and c.tpsa > veb["tpsa_max"]:
        flags.append(f"veber_tpsa>{veb['tpsa_max']:g}")
    return tuple(flags)


def evaluate(c: Compound, config: dict, solvent: str) -> Verdict:
    spec = solvent_spec(config, solvent)
    reasons = [
        r
        for r in (
            check_solvent(c, spec),
            check_mw(c, config["extraction"]["mw_max"]),
        )
        if r
    ]
    return Verdict(
        compound=c,
        kept=not reasons,
        reasons=tuple(reasons),
        flags=druglikeness_flags(c, config),
    )


def evaluate_all(compounds, config: dict, solvent: str) -> list[Verdict]:
    return [evaluate(c, config, solvent) for c in compounds]


# --------------------------------------------------------------------------
# corpus access
# --------------------------------------------------------------------------
def resolve_plant(con: sqlite3.Connection, name: str) -> tuple[str, str]:
    """Plant id and canonical name from scientific name, common name or synonym."""
    con.row_factory = sqlite3.Row
    q = name.strip().lower()
    row = con.execute(
        """
        SELECT p.id, p.canonical_name
          FROM plant_aliases a JOIN plants p ON p.id = a.plant_id
         WHERE lower(a.alias) = ?
         ORDER BY CASE a.alias_type WHEN 'scientific' THEN 0
                                    WHEN 'synonym'    THEN 1
                                    ELSE 2 END
         LIMIT 1
        """,
        (q,),
    ).fetchone()
    if row is None:
        row = con.execute(
            "SELECT id, canonical_name FROM plants WHERE lower(canonical_name) LIKE ? LIMIT 1",
            (f"%{q}%",),
        ).fetchone()
    if row is None:
        raise LookupError(f"no plant matching {name!r}")
    return row["id"], row["canonical_name"]


def load_compounds(
    con: sqlite3.Connection,
    plant_id: str,
    part: str,
    *,
    allow_unspecified: bool = True,
) -> list[Compound]:
    """Compounds recorded for one plant part."""
    con.row_factory = sqlite3.Row
    part = part.strip().lower()
    if part == "unspecified" and not allow_unspecified:
        return []
    rows = con.execute(
        """
        SELECT c.id, c.name, c.smiles, c.mw, c.logp, c.tpsa, c.hbd, c.hba, c.rotb
          FROM plant_compounds pc JOIN compounds c ON c.id = pc.compound_id
         WHERE pc.plant_id = ? AND pc.part = ?
         ORDER BY c.name
        """,
        (plant_id, part),
    ).fetchall()
    return [
        Compound(
            id=r["id"], name=r["name"] or r["id"], smiles=r["smiles"],
            mw=r["mw"], logp=r["logp"], tpsa=r["tpsa"],
            hbd=r["hbd"], hba=r["hba"], rotb=r["rotb"],
        )
        for r in rows
    ]


def list_parts(con: sqlite3.Connection, plant_id: str) -> list[tuple[str, int]]:
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT part, COUNT(DISTINCT compound_id) n
          FROM plant_compounds WHERE plant_id = ?
         GROUP BY part ORDER BY n DESC
        """,
        (plant_id,),
    ).fetchall()
    return [(r["part"], r["n"]) for r in rows]


# --------------------------------------------------------------------------
# stage
# --------------------------------------------------------------------------
def run(
    plant: str,
    part: str,
    solvent: str,
    *,
    db: str | Path = DB_PATH,
    config_path: str | Path = CONFIG_PATH,
) -> ExtractionResult:
    config = load_config(config_path)
    con = sqlite3.connect(db)
    try:
        plant_id, plant_name = resolve_plant(con, plant)
        compounds = load_compounds(
            con, plant_id, part,
            allow_unspecified=config["parts"]["allow_unspecified"],
        )
    finally:
        con.close()

    spec = solvent_spec(config, solvent)
    ceiling = config["extraction"]["mw_max"]

    # Sequential funnel: each row is a rule and the count surviving it.
    # Order affects only presentation; the surviving set does not depend on it.
    funnel = [{"rule": "plant_part", "input": len(compounds), "output": len(compounds)}]
    survivors = compounds
    for rule, predicate in (
        (f"solvent:{solvent}", lambda c: check_solvent(c, spec) is None),
        ("mw_ceiling", lambda c: check_mw(c, ceiling) is None),
    ):
        nxt = [c for c in survivors if predicate(c)]
        funnel.append({"rule": rule, "input": len(survivors), "output": len(nxt)})
        survivors = nxt

    return ExtractionResult(
        solvent=solvent.strip().lower(),
        solvent_label=spec["label"],
        plant_id=plant_id,
        plant_name=plant_name,
        part=part.strip().lower(),
        config_hash=config_hash(config_path),
        verdicts=evaluate_all(compounds, config, solvent),
        funnel=funnel,
    )


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------
def _print(result: ExtractionResult) -> None:
    print()
    print(f"{result.plant_name}  [{result.part}]  {result.solvent_label}")
    print(f"config {result.config_hash}")
    print("-" * 68)
    prev = result.funnel[0]["input"]
    for step in result.funnel:
        label = step["rule"]
        n = step["output"]
        note = "" if step["rule"] == "plant_part" else f"  (-{prev - n})"
        print(f"  {label:<26} {n:>4}{note}")
        prev = n
    flagged = [v for v in result.kept if v.flags]
    print(f"  {'flagged (not dropped)':<26} {len(flagged):>4}")
    if flagged:
        for v in flagged[:6]:
            print(f"      {v.compound.name[:44]:<44} {', '.join(v.flags)}")
    print()
    print("kept compounds:")
    for v in sorted(result.kept, key=lambda v: (v.compound.mw or 0), reverse=True):
        fl = f"  [{', '.join(v.flags)}]" if v.flags else ""
        print(f"  {v.compound.name[:46]:<46} MW={v.compound.mw:>7} logP={v.compound.logp:>6}{fl}")
    if result.dropped:
        print()
        print(f"dropped ({len(result.dropped)}):")
        for v in result.dropped[:10]:
            print(f"  {v.compound.name[:46]:<46} {', '.join(v.reasons)}")
    print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extraction + drug-likeness stage")
    ap.add_argument("--plant", required=True)
    ap.add_argument("--part", required=True)
    ap.add_argument("--solvent", default="ethanol")
    ap.add_argument("--list-parts", action="store_true",
                    help="list parts available for the plant and exit")
    ap.add_argument("--json", action="store_true", help="emit the full result as JSON")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--config", default=str(CONFIG_PATH))
    args = ap.parse_args(argv)

    if args.list_parts:
        con = sqlite3.connect(args.db)
        try:
            pid, name = resolve_plant(con, args.plant)
            print(f"{name} ({pid})")
            for part, n in list_parts(con, pid):
                print(f"  {part:<20} {n:>4} compounds")
        finally:
            con.close()
        return 0

    try:
        result = run(args.plant, args.part, args.solvent,
                     db=args.db, config_path=args.config)
    except (LookupError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.summary(), indent=2, ensure_ascii=False))
    else:
        _print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
