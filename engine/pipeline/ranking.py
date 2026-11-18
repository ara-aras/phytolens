"""
Stage 2: rank the surviving compounds for a specific condition.

The design constraint comes from `docs/DEMO_PLAN.md` Finding 2. Ranking on the
number of annotated targets promotes annotation volume over pharmacology: for
Boswellia serrata it puts geraniol (99 links, 89 measured) first and buries the
boswellic acids (1 measured link each). So target count is used as a gate and
as a capped overlap term, never as the score.

Terms, all reported individually so the ordering can be argued with:

    overlap       condition targets reached, capped
    evidence      share of those resting on measured (non-NPASS) links
    specificity   overlap / everything the compound is known to hit
    promiscuity   penalty for a very large measured target set
    docking       Vina affinity, when available

Docking is the only term that does not depend on how much a compound has been
studied. Until it runs, its weight is redistributed and every result is marked
`docking_pending: true` so a pre-docking ordering is never shown as final.

Usage:
    python -m engine.pipeline.ranking --plant "Curcuma longa" --part rhizome \
        --solvent ethanol --condition colitis --top 12
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from engine.pipeline import admet as adm
from engine.pipeline import extraction as ex

ENGINE_DIR = Path(__file__).resolve().parents[1]
RANKING_CONFIG = ENGINE_DIR / "config" / "ranking.yaml"
TARGETS_DIR = ENGINE_DIR / "data" / "targets"


# --------------------------------------------------------------------------
# condition target set
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Condition:
    id: str
    name: str
    scores: dict[str, float]           # gene symbol -> Open Targets score
    evidence: dict[str, dict]          # gene symbol -> evidence-type -> score
    source: str
    retrieved: str
    min_score: float

    @property
    def genes(self) -> set[str]:
        return set(self.scores)


def load_condition(name: str, dir_path: Path = TARGETS_DIR) -> Condition:
    path = dir_path / f"{name}.json"
    if not path.exists():
        available = sorted(p.stem for p in dir_path.glob("*.json"))
        raise LookupError(
            f"no cached condition {name!r}; available: {', '.join(available) or 'none'}. "
            f"Fetch one with: python -m engine.fetch_targets --disease MONDO_... --name {name}"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    cond = payload["condition"]
    targets = payload["targets"]
    return Condition(
        id=cond["id"],
        name=cond["name"],
        scores={t["symbol"]: t["score"] for t in targets},
        evidence={t["symbol"]: t.get("evidence", {}) for t in targets},
        source=cond.get("source", "Open Targets"),
        retrieved=cond.get("retrieved", ""),
        min_score=cond.get("min_score", 0.0),
    )


# --------------------------------------------------------------------------
# compounds
# --------------------------------------------------------------------------
PREDICTED = set()


def _is_measured(source: str) -> bool:
    """A link is measured if ANY listed source is a measured database.

    IMPPAT unions its sources with "|", so a link can read
    "BindingDB | ChEMBL | NPASS". Checking `"NPASS" not in source` would call
    that predicted, which is wrong and understates every well-studied compound
    -- curcumin's PTGS2 and ALOX5 links are exactly this case.
    """
    parts = {p.strip() for p in (source or "").split("|") if p.strip()}
    return bool(parts - PREDICTED)


@dataclass
class CompoundTargets:
    all_genes: set[str] = field(default_factory=set)
    measured_genes: set[str] = field(default_factory=set)
    gene_sources: dict[str, list[str]] = field(default_factory=dict)

    @property
    def n_all(self) -> int:
        return len(self.all_genes)

    @property
    def n_measured(self) -> int:
        return len(self.measured_genes)


def load_targets(con: sqlite3.Connection, compound_ids: list[str]) -> dict[str, CompoundTargets]:
    out: dict[str, CompoundTargets] = {}
    if not compound_ids:
        return out
    chunk = 400
    for i in range(0, len(compound_ids), chunk):
        part = compound_ids[i:i + chunk]
        ph = ",".join("?" * len(part))
        rows = con.execute(
            f"SELECT compound_id, gene_symbol, source FROM compound_targets "
            f"WHERE compound_id IN ({ph})",
            part,
        ).fetchall()
        for cid, gene, source in rows:
            rec = out.setdefault(cid, CompoundTargets())
            rec.all_genes.add(gene)
            if _is_measured(source):
                rec.measured_genes.add(gene)
            srcs = {p.strip() for p in (source or "").split("|") if p.strip()}
            if srcs:
                rec.gene_sources[gene] = sorted(set(rec.gene_sources.get(gene, ())) | srcs)
    return out


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------
@dataclass
class Scored:
    compound: ex.Compound
    flags: tuple[str, ...]
    n_all: int
    n_measured: int
    overlap_all: list[str]
    overlap_measured: list[str]
    overlap_sources: dict[str, list[str]] = field(default_factory=dict)
    terms: dict[str, float] = field(default_factory=dict)
    contributions: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    rank: int = 0
    docking: dict[str, float] = field(default_factory=dict)
    admet: dict = field(default_factory=dict)

    def as_dict(self, cond: Condition) -> dict:
        return {
            "rank": self.rank,
            "id": self.compound.id,
            "name": self.compound.name,
            "score": round(self.score, 4),
            "mw": self.compound.mw,
            "logp": self.compound.logp,
            "flags": list(self.flags),
            "admet": self.admet or adm.evaluate_smiles(self.compound.smiles).as_dict(),
            "targets": {"annotated": self.n_all, "measured": self.n_measured},
            "overlap": {
                "count": len(self.overlap_all),
                "measured": len(self.overlap_measured),
                "genes": [
                    {
                        "symbol": g,
                        "condition_score": cond.scores.get(g),
                        "measured": g in self.overlap_measured,
                        "support": "measured" if g in self.overlap_measured else "predicted",
                        "sources": self.overlap_sources.get(g, []),
                        "evidence": cond.evidence.get(g, {}),
                    }
                    for g in sorted(self.overlap_all,
                                    key=lambda g: -(cond.scores.get(g) or 0))
                ],
            },
            "terms": {k: round(v, 4) for k, v in self.terms.items()},
            "contributions": {k: round(v, 4) for k, v in self.contributions.items()},
            "docking": dict(sorted(self.docking.items())),
            "docking_missing": not self.docking,
        }


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _docking_norm(affinity: float | None, cfg: dict) -> float | None:
    if affinity is None:
        return None
    strong, weak = cfg["strong"], cfg["weak"]
    return _clamp((weak - affinity) / (weak - strong))


def _dock_profile(docking) -> dict[str, float]:
    """Normalise a docking input to {target: affinity}.

    Accepts a bare affinity (single target, the pre-panel format) or a mapping.
    """
    if docking is None:
        return {}
    if isinstance(docking, dict):
        return {str(k): float(v) for k, v in docking.items() if v is not None}
    return {"docking": float(docking)}


def score_compound(
    c: ex.Compound,
    ct: CompoundTargets,
    cond: Condition,
    flags: tuple[str, ...],
    rc: dict,
    docking=None,
) -> Scored | None:
    o_all = sorted(ct.all_genes & cond.genes)
    o_meas = sorted(ct.measured_genes & cond.genes)
    if len(o_all) < rc["gate"]["min_condition_targets"]:
        return None

    w = dict(rc["weights"])
    cap = rc["overlap"]["cap"]

    terms = {
        "overlap": min(len(o_all), cap) / cap,
        "evidence": (len(o_meas) / len(o_all)) if o_all else 0.0,
        "specificity": (len(o_all) / ct.n_all) if ct.n_all else 0.0,
        "promiscuity": _clamp(
            (ct.n_measured - rc["promiscuity"]["starts_at"])
            / max(1, rc["promiscuity"]["saturates_at"] - rc["promiscuity"]["starts_at"])
        ),
    }

    profile = _dock_profile(docking)
    normed = [n for n in (_docking_norm(a, rc["docking"]) for a in profile.values())
              if n is not None]
    dock_norm = sum(normed) / len(normed) if normed else None
    if dock_norm is None:
        w.pop("docking")
        total = sum(w.values())
        w = {k: v / total for k, v in w.items()}
        dock_norm = 0.0
    else:
        terms["docking"] = dock_norm

    contributions = {k: w[k] * terms[k] for k in w}
    contributions["promiscuity"] = -w["promiscuity"] * terms["promiscuity"]
    score = sum(contributions.values())

    return Scored(
        compound=c, flags=flags,
        n_all=ct.n_all, n_measured=ct.n_measured,
        overlap_all=o_all, overlap_measured=o_meas,
        overlap_sources={g: ct.gene_sources.get(g, ["ChEMBL" if g in o_meas else "NPASS"])
                         for g in o_all},
        terms=terms, contributions=contributions, score=score,
        docking=dict(sorted(profile.items())),
        admet=adm.evaluate_smiles(c.smiles).as_dict(),
    )


# --------------------------------------------------------------------------
# stage
# --------------------------------------------------------------------------
@dataclass
class RankingResult:
    extraction: ex.ExtractionResult
    condition: Condition
    ranked: list[Scored]
    excluded_no_condition_target: int
    docking_pending: bool
    config_hash: str
    n_candidates: int = 0
    n_docked: int = 0

    def summary(self) -> dict:
        ranked = self.ranked
        return {
            "condition": {
                "id": self.condition.id,
                "name": self.condition.name,
                "targets": len(self.condition.genes),
                "source": self.condition.source,
                "retrieved": self.condition.retrieved,
                "min_score": self.condition.min_score,
            },
            "formulation": {
                "plant": self.extraction.plant_name,
                "plant_id": self.extraction.plant_id,
                "part": self.extraction.part,
                "solvent": self.extraction.solvent,
                "solvent_label": self.extraction.solvent_label,
            },
            "config_hashes": {
                "extraction": self.extraction.config_hash,
                "ranking": self.config_hash,
            },
            "docking_pending": self.docking_pending,
            "docking": {
                "candidates": self.n_candidates,
                "docked": self.n_docked,
                "partial": 0 < self.n_docked < self.n_candidates,
            },
            "funnel": {
                "in_part": len(self.extraction.verdicts),
                "pass_extraction": len(self.extraction.kept),
                "flagged_druglikeness": sum(1 for v in self.extraction.kept if v.flags),
                "with_condition_target": self.n_candidates,
                "excluded_no_condition_target": self.excluded_no_condition_target,
            },
            "ranked": [s.as_dict(self.condition) for s in ranked],
        }


def run(
    plant: str,
    part: str,
    solvent: str,
    condition: str,
    *,
    top: int | None = None,
    docking_scores: dict[str, float | dict[str, float]] | None = None,
    db: str | Path = ex.DB_PATH,
    extraction_config: str | Path = ex.CONFIG_PATH,
    ranking_config: str | Path = RANKING_CONFIG,
    targets_dir: Path = TARGETS_DIR,
) -> RankingResult:
    rc = yaml.safe_load(Path(ranking_config).read_text(encoding="utf-8"))
    PREDICTED.update(rc.get("evidence", {}).get("predicted_sources", ["NPASS"]))

    cond = load_condition(condition, targets_dir)
    ext = ex.run(plant, part, solvent, db=db, config_path=extraction_config)

    kept = ext.kept
    ids = [v.compound.id for v in kept]
    con = sqlite3.connect(db)
    try:
        targets = load_targets(con, ids)
    finally:
        con.close()

    scored: list[Scored] = []
    excluded = 0
    for v in kept:
        ct = targets.get(v.compound.id, CompoundTargets())
        s = score_compound(
            v.compound, ct, cond, v.flags, rc,
            docking=(docking_scores or {}).get(v.compound.id),
        )
        if s is None:
            excluded += 1
        else:
            scored.append(s)

    scored.sort(key=lambda s: (-s.score, -len(s.overlap_measured), -len(s.overlap_all),
                               s.compound.name or ""))
    for i, s in enumerate(scored, 1):
        s.rank = i

    has_docking = bool(docking_scores)
    n_candidates = len(scored)
    n_docked = sum(1 for s in scored if s.docking)
    if top:
        scored = scored[:top]

    return RankingResult(
        extraction=ext, condition=cond, ranked=scored,
        excluded_no_condition_target=excluded,
        docking_pending=not has_docking,
        config_hash=ex.config_hash(ranking_config),
        n_candidates=n_candidates,
        n_docked=n_docked,
    )


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------
def _print(res: RankingResult) -> None:
    e = res.extraction
    c = res.condition
    f = res.summary()["funnel"]
    print()
    print(f"{e.plant_name}  [{e.part}]  {e.solvent_label}   ->  {c.name}")
    print(f"condition set: {len(c.genes)} targets from {c.source} "
          f"(score >= {c.min_score}, {c.retrieved})")
    print(f"config: extraction {e.config_hash} | ranking {res.config_hash}")
    print("-" * 96)
    print(f"  {'compounds in part':<34} {f['in_part']:>5}")
    print(f"  {'pass extraction':<34} {f['pass_extraction']:>5}")
    print(f"  {'flagged drug-likeness (kept)':<34} {f['flagged_druglikeness']:>5}")
    print(f"  {'reach >=1 condition target':<34} {f['with_condition_target']:>5}")
    print(f"  {'no condition target (gated)':<34} {f['excluded_no_condition_target']:>5}")
    if res.docking_pending:
        print("  NOTE: docking has not run -- weights renormalised, order is preliminary")
    print()
    header = (f"{'#':>3} {'compound':<38} {'score':>6} {'ovl':>4} {'meas':>5} "
              f"{'tgts':>5} {'spec':>5} {'evid':>5} {'prom':>5}  genes")
    print(header)
    print("-" * 96)
    for s in res.ranked:
        t = s.terms
        genes = ",".join(s.overlap_all[:4]) + ("..." if len(s.overlap_all) > 4 else "")
        print(f"{s.rank:>3} {s.compound.name[:38]:<38} {s.score:>6.3f} "
              f"{len(s.overlap_all):>4} {len(s.overlap_measured):>5} "
              f"{s.n_all:>5} {t['specificity']:>5.2f} {t['evidence']:>5.2f} "
              f"{t['promiscuity']:>5.2f}  {genes}")
    print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rank compounds for a condition")
    ap.add_argument("--plant", required=True)
    ap.add_argument("--part", required=True)
    ap.add_argument("--solvent", default="ethanol")
    ap.add_argument("--condition", required=True, help="cached target set name, e.g. colitis")
    ap.add_argument("--top", type=int, default=None)
    ap.add_argument("--dock", help="JSON file of {compound_id: vina_affinity}")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--db", default=str(ex.DB_PATH))
    args = ap.parse_args(argv)

    docking = None
    if args.dock:
        docking = json.loads(Path(args.dock).read_text(encoding="utf-8"))

    try:
        res = run(args.plant, args.part, args.solvent, args.condition,
                  top=args.top, docking_scores=docking, db=args.db)
    except LookupError as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 2

    if args.json:
        print(json.dumps(res.summary(), indent=2, ensure_ascii=False))
    else:
        _print(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
