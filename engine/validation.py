"""Retrospective validation harness.

The question this answers is the one a pharmacology judge asks first: *how do
you know the ranking is any good?* Protocol (docs/BACKEND_SPEC.md section 10):

1. Run the pipeline **untuned** and publish recall@10, recall@25, MRR and the
   mean rank of the known actives.
2. Report every case attempted, including misses.
3. Write the result to ``engine/validation/results/{case}__{config_hash}.json``.

Three controls make the numbers mean something:

* **ablation** -- the same case ranked with and without docking. The difference
  is the docking term's contribution, not a tuned improvement.
* **null baseline** -- the same actives against random orderings of the same
  candidate list, with a one-sided permutation p-value. This is what stops a
  small case from looking impressive by chance.
* **residual bias** -- how many of the case's top 10 are the six ubiquitous
  compounds from the corpus-bias finding, so a case cannot quietly succeed on
  the very bias the design exists to shrink.

Weights are not tuned here. Anything tuned later must be reported separately
against a held-out case, never mixed into these numbers.

Run:
    python -m engine.validation --all
    python -m engine.validation --case curcuma_longa --json
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from engine.pipeline import extraction as ex
from engine.pipeline import ranking as rk

ENGINE_DIR = Path(__file__).resolve().parent
CASES_PATH = ENGINE_DIR / "validation" / "cases.yaml"
RESULTS_DIR = ENGINE_DIR / "validation" / "results"
PANEL_PATH = ENGINE_DIR / "data" / "dock_scores_panel.json"

SIX_COMPOUNDS = ("Eugenol", "Geraniol", "Cinnamaldehyde", "Quercetin",
                 "Eucalyptol", "Safrole")


@dataclass(frozen=True)
class Case:
    name: str
    label: str
    plant: str
    part: str
    solvent: str
    condition: str
    known_actives: tuple[dict, ...]
    rationale: str = ""

    @property
    def active_names(self) -> list[str]:
        return [a["name"] for a in self.known_actives]

    @property
    def active_groups(self) -> list[list[str]]:
        return [[a["name"], *(a.get("aliases") or [])]
                for a in self.known_actives]


def load_cases(path: Path = CASES_PATH) -> list[Case]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cases = []
    for raw in payload["cases"]:
        cases.append(Case(
            name=raw["name"],
            label=raw.get("label", raw["name"]),
            plant=raw["plant"],
            part=raw["part"],
            solvent=raw.get("solvent", "ethanol"),
            condition=raw["condition"],
            known_actives=tuple(raw["known_actives"]),
            rationale=raw.get("rationale", ""),
        ))
    return cases


def get_case(name: str, path: Path = CASES_PATH) -> Case:
    for case in load_cases(path):
        if case.name == name:
            return case
    raise LookupError(f"no validation case {name!r}")


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
def active_ranks(ranked_names: list[str], active_names: list[str]) -> dict[str, int]:
    """Rank of each known active that appears in the ranking (1-based)."""
    lookup = {n.strip().lower(): i + 1 for i, n in enumerate(ranked_names)}
    ranks: dict[str, int] = {}
    for name in active_names:
        rank = lookup.get(name.strip().lower())
        if rank is not None and name not in ranks:
            ranks[name] = rank
    return ranks


def recall_at(ranks: dict[str, int], n_actives: int, k: int) -> float:
    if n_actives <= 0:
        return 0.0
    return sum(1 for r in ranks.values() if r <= k) / n_actives


def _unique(names: list[str]) -> list[str]:
    """Deduplicate case-insensitively, keeping the first spelling."""
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        key = name.strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(name)
    return out


def metrics_for_groups(ranked_names: list[str], groups: list[list[str]],
                       ks: tuple[int, ...] = (10, 25)) -> dict:
    """Metrics where each group is one known active plus its synonyms.

    Counting an alias as a second active would inflate both the denominator
    and the recall. An active is found if any of its names is ranked; its rank
    is the best rank among those names.
    """
    lookup = {n.strip().lower(): i + 1 for i, n in enumerate(ranked_names)}
    ranks: dict[str, int] = {}
    for group in groups:
        found = [lookup[n.strip().lower()] for n in group
                 if n and n.strip().lower() in lookup]
        if found:
            ranks[group[0]] = min(found)
    n = len(groups)
    return {
        "n_known_actives": n,
        "n_found": len(ranks),
        "ranks": ranks,
        "unranked": [g[0] for g in groups if g[0] not in ranks],
        "mrr": round(sum(1.0 / r for r in ranks.values()) / n, 4) if n else 0.0,
        "mean_rank": round(sum(ranks.values()) / len(ranks), 2) if ranks else None,
        "best_rank": min(ranks.values()) if ranks else None,
        **{f"recall_at_{k}": round(recall_at(ranks, n, k), 4) for k in ks},
    }


def metrics(ranked_names: list[str], active_names: list[str],
            ks: tuple[int, ...] = (10, 25)) -> dict:
    names = _unique(active_names)
    return metrics_for_groups(ranked_names, [[n] for n in names], ks=ks)


# --------------------------------------------------------------------------
# controls: null baseline, bias residue
# --------------------------------------------------------------------------
def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return round(ordered[idx], 4)


def null_baseline(ranked_names: list[str], groups: list[list[str]], *,
                  permutations: int = 1000, ks: tuple[int, ...] = (10, 25),
                  seed: int = 7) -> dict:
    """Same actives, randomly ordered candidates.

    Answers "could this ranking have happened by luck?" for a case whose
    candidate list is small. The analytic expectation of 1/rank for a uniform
    ordering is H_N / N, which is reported alongside the empirical draw so the
    simulation can be checked rather than trusted.
    """
    n = len(ranked_names)
    if n == 0 or not groups:
        return {"permutations": 0, "note": "empty candidate list"}

    observed = metrics_for_groups(ranked_names, groups, ks=ks)
    rng = random.Random(seed)
    pool = list(ranked_names)
    mrrs: list[float] = []
    r10: list[float] = []
    r25: list[float] = []
    for _ in range(permutations):
        rng.shuffle(pool)
        m = metrics_for_groups(pool, groups, ks=ks)
        mrrs.append(m["mrr"])
        r10.append(m["recall_at_10"])
        r25.append(m["recall_at_25"])

    def p_value(draws: list[float], stat: float) -> float:
        # One-sided: share of random orderings at least as good as observed.
        return round(sum(1 for d in draws if d >= stat) / len(draws), 4)

    harmonic = sum(1.0 / k for k in range(1, n + 1))
    found_share = observed["n_found"] / max(1, observed["n_known_actives"])
    return {
        "permutations": permutations,
        "seed": seed,
        "n_candidates": n,
        "analytic_expected_mrr": round(found_share * harmonic / n, 4),
        "random_mrr_mean": round(statistics.fmean(mrrs), 4),
        "random_mrr_p95": _percentile(mrrs, 0.95),
        "observed_mrr": observed["mrr"],
        "mrr_percentile": round(
            sum(1 for d in mrrs if d <= observed["mrr"]) / len(mrrs), 4),
        "p_value_mrr": p_value(mrrs, observed["mrr"]),
        "p_value_recall_at_10": p_value(r10, observed["recall_at_10"]),
        "p_value_recall_at_25": p_value(r25, observed["recall_at_25"]),
    }


def bias_residue(ranked_names: list[str], k: int = 10) -> dict:
    """How much of this case's top k is the ubiquitous six-compound cohort."""
    top = [n.strip().lower() for n in ranked_names[:k]]
    six = {c.lower() for c in SIX_COMPOUNDS}
    hits = sorted({n for n in top if n in six})
    return {
        "k": k,
        "six_in_top": hits,
        "count": sum(1 for n in top if n in six),
        "fraction": round(sum(1 for n in top if n in six) / max(1, len(top)), 4),
    }


# --------------------------------------------------------------------------
# corpus-wide bias (the 44% figure, recomputed rather than quoted)
# --------------------------------------------------------------------------
def corpus_bias(db: Path = ex.DB_PATH, min_candidates: int = 3) -> dict:
    """Share of plant-part groups whose annotation-ranked top compound is one
    of the six ubiquitous phytochemicals.

    Groups are (plant_id, part). A compound's score is its number of annotated
    targets, which is exactly the quantity the pipeline refuses to rank on.
    """
    con = sqlite3.connect(db)
    try:
        names = {cid: name for cid, name in
                 con.execute("SELECT id, name FROM compounds")}
        rows = con.execute(
            """
            SELECT pc.plant_id, pc.part, pc.compound_id,
                   COUNT(DISTINCT ct.gene_symbol) AS n_targets
              FROM plant_compounds pc
              LEFT JOIN compound_targets ct ON ct.compound_id = pc.compound_id
             GROUP BY pc.plant_id, pc.part, pc.compound_id
            """
        ).fetchall()
    finally:
        con.close()

    groups: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for plant_id, part, cid, n in rows:
        groups.setdefault((plant_id, part), []).append((cid, n))

    eligible = 0
    topped = 0
    examples: list[dict] = []
    for (plant_id, part), members in groups.items():
        if len(members) < min_candidates:
            continue
        eligible += 1
        # Highest annotated-target count; ties broken by compound id for
        # determinism (never by name).
        best = sorted(members, key=lambda m: (-m[1], m[0]))[0]
        name = names.get(best[0], best[0])
        if name in SIX_COMPOUNDS:
            topped += 1
            if len(examples) < 5:
                examples.append({"plant_id": plant_id, "part": part,
                                 "top": name, "targets": best[1]})

    return {
        "plant_part_groups": len(groups),
        "groups_with_at_least": min_candidates,
        "eligible_groups": eligible,
        "topped_by_six": topped,
        "fraction": round(topped / eligible, 4) if eligible else 0.0,
        "six_compounds": list(SIX_COMPOUNDS),
        "examples": examples,
    }


# --------------------------------------------------------------------------
# cases
# --------------------------------------------------------------------------
def load_docking(path: Path = PANEL_PATH) -> dict[str, dict[str, float]] | None:
    if not Path(path).exists():
        return None
    from engine.pipeline import docking as dk
    return dk.panel_affinities(dk.load_panel(path))


def run_case(case: Case, *, docking_scores=None, db: Path = ex.DB_PATH,
             write: bool = False) -> dict:
    result = rk.run(case.plant, case.part, case.solvent, case.condition,
                    docking_scores=docking_scores, db=db)
    ranked_names = [s.compound.name for s in result.ranked]
    summary = result.summary()
    metrics_docking = metrics_for_groups(ranked_names, case.active_groups)

    # Ablation: identical pipeline with the docking term removed. The weights
    # renormalise themselves, so this is the annotation-only arm, not a
    # hand-tuned comparison.
    plain = rk.run(case.plant, case.part, case.solvent, case.condition,
                   docking_scores=None, db=db)
    plain_names = [s.compound.name for s in plain.ranked]
    metrics_plain = metrics_for_groups(plain_names, case.active_groups)

    payload = {
        "case": case.name,
        "label": case.label,
        "rationale": case.rationale,
        "protocol": ("untuned defaults; report every case, misses included; "
                     "weights must only be tuned on a held-out case"),
        "run": {
            "plant": case.plant,
            "part": case.part,
            "solvent": case.solvent,
            "condition": case.condition,
            "config_hashes": summary["config_hashes"],
            "docking_pending": summary["docking_pending"],
            "docking": summary["docking"],
            "funnel": summary["funnel"],
        },
        "metrics": metrics_docking,
        "ablation": {
            "with_docking": metrics_docking,
            "annotation_only": metrics_plain,
            "delta_mrr": round(metrics_docking["mrr"] - metrics_plain["mrr"], 4),
            "delta_best_rank": (
                None if metrics_plain["best_rank"] is None
                or metrics_docking["best_rank"] is None
                else metrics_plain["best_rank"] - metrics_docking["best_rank"]),
            "annotation_only_top_10": [
                {"rank": s.rank, "name": s.compound.name}
                for s in plain.ranked[:10]
            ],
        },
        "null_baseline": null_baseline(ranked_names, case.active_groups),
        "bias_residue": bias_residue(ranked_names),
        "top_10": [
            {"rank": s.rank, "name": s.compound.name, "score": round(s.score, 4),
             "docking": s.docking}
            for s in result.ranked[:10]
        ],
        "generated": date.today().isoformat(),
    }

    if write:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in case.name)
        path = RESULTS_DIR / f"{safe}__{summary['config_hashes']['ranking']}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        payload["result_file"] = str(path.relative_to(ENGINE_DIR.parent))
    return payload


def run_all(*, write: bool = True, db: Path = ex.DB_PATH) -> dict:
    docking = load_docking()
    cases = [run_case(c, docking_scores=docking, db=db, write=write)
             for c in load_cases()]
    with_dock = [c["metrics"]["mrr"] for c in cases]
    without = [c["ablation"]["annotation_only"]["mrr"] for c in cases]
    return {
        "generated": date.today().isoformat(),
        "docking_used": docking is not None,
        "corpus_bias": corpus_bias(db),
        "aggregate": {
            "n_cases": len(cases),
            "mean_mrr": round(statistics.fmean(with_dock), 4) if with_dock else 0.0,
            "mean_mrr_annotation_only": round(statistics.fmean(without), 4) if without else 0.0,
            "delta_mrr": round(statistics.fmean(with_dock) - statistics.fmean(without), 4)
            if with_dock and without else 0.0,
            "n_actives_found": sum(c["metrics"]["n_found"] for c in cases),
            "n_actives": sum(c["metrics"]["n_known_actives"] for c in cases),
        },
        "cases": cases,
    }


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------
def _print(payload: dict) -> None:
    bias = payload.get("corpus_bias")
    if bias:
        print(f"corpus bias: {bias['topped_by_six']:,} of {bias['eligible_groups']:,} "
              f"plant-part groups ({bias['fraction']:.1%}) are topped by one of six "
              f"compounds")
        print()
    for case in payload["cases"]:
        m = case["metrics"]
        run = case["run"]
        print(f"{case['label']}  ({run['plant']} / {run['part']} / {run['solvent']}"
              f" -> {run['condition']})")
        print(f"  docking used       : {'yes' if not run['docking_pending'] else 'no'}")
        print(f"  known actives found: {m['n_found']}/{m['n_known_actives']}")
        print(f"  recall@10 / @25    : {m['recall_at_10']:.2f} / {m['recall_at_25']:.2f}")
        print(f"  MRR                : {m['mrr']:.3f}")
        print(f"  best / mean rank   : {m['best_rank']} / {m['mean_rank']}")
        print(f"  ranks              : {m['ranks']}")
        ablation = case.get("ablation") or {}
        if ablation:
            plain = ablation["annotation_only"]
            print(f"  annotation-only MRR: {plain['mrr']:.3f} "
                  f"(delta {ablation['delta_mrr']:+.3f})")
        null = case.get("null_baseline") or {}
        if null.get("permutations"):
            print(f"  random MRR mean    : {null['random_mrr_mean']:.3f} "
                  f"(observed p={null['p_value_mrr']:.3f}, "
                  f"percentile {null['mrr_percentile']:.2f})")
        bias = case.get("bias_residue") or {}
        if bias:
            print(f"  six-compound residue in top 10: {bias['count']} "
                  f"{bias['six_in_top'] or ''}")
        if case.get("result_file"):
            print(f"  written            : {case['result_file']}")
        print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Retrospective validation harness")
    ap.add_argument("--all", action="store_true", help="run every case")
    ap.add_argument("--case", help="run one case by name")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    if args.case:
        docking = load_docking()
        payload = {"cases": [run_case(get_case(args.case), docking_scores=docking,
                                      write=not args.no_write)],
                   "corpus_bias": corpus_bias()}
    elif args.all:
        payload = run_all(write=not args.no_write)
    else:
        ap.error("pass --all or --case NAME")

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        _print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
