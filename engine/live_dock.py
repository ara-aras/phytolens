"""Live-docking sample: run Vina now, on a formulation that was never pre-scored.

    python -m engine.live_dock --plant "Zingiber officinale" --part rhizome \\
        --condition colitis --targets PTGS2 --candidates 2 \\
        --out engine/data/live_dock_sample.json

This is the same call the API makes from ``POST /v1/runs/{id}/dock``. It exists
so the live path can be exercised (and its numbers recorded) without a browser,
and so the demo has a reproducible artefact instead of a screenshot.

Docking is CPU work: keep the candidate count small. Exhaustiveness defaults to
4 here rather than the panel's 8, because a live demo has a clock; the response
records that difference so the two numbers are never silently compared.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from engine.pipeline import docking as dk
from engine.pipeline import ranking as rk

ENGINE_DIR = Path(__file__).resolve().parent
PANEL_PATH = ENGINE_DIR / "data" / "dock_scores_panel.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Live-dock a bounded set of candidates")
    ap.add_argument("--plant", required=True)
    ap.add_argument("--part", required=True)
    ap.add_argument("--solvent", default="ethanol")
    ap.add_argument("--condition", required=True)
    ap.add_argument("--targets", default="PTGS2",
                    help="comma-separated panel targets (max 2)")
    ap.add_argument("--candidates", type=int, default=2)
    ap.add_argument("--exhaustiveness", type=int, default=4)
    ap.add_argument("--compound", action="append",
                    help="explicit compound name (repeatable); overrides --candidates")
    ap.add_argument("--out", default=str(ENGINE_DIR / "data" / "live_dock_sample.json"))
    args = ap.parse_args(argv)

    targets = tuple(t.strip().upper() for t in args.targets.split(",") if t.strip())
    if len(targets) > 2:
        ap.error("at most 2 targets per live run")
    unknown = [t for t in targets if t not in dk.TARGETS]
    if unknown:
        ap.error(f"unknown targets {unknown}; panel: {sorted(dk.TARGETS)}")

    panel = dk.panel_affinities(dk.load_panel(PANEL_PATH)) if PANEL_PATH.exists() else {}
    before = rk.run(args.plant, args.part, args.solvent, args.condition,
                    docking_scores=panel or None)

    if args.compound:
        wanted = {c.lower() for c in args.compound}
        chosen = [s for s in before.ranked if s.compound.name.lower() in wanted]
        missing = wanted - {s.compound.name.lower() for s in chosen}
        if missing:
            ap.error(f"compounds not ranked for this formulation: {sorted(missing)}")
    else:
        chosen = before.ranked[:max(1, args.candidates)]

    smiles = dk.compound_smiles([s.compound.id for s in chosen])
    runnable = [(s.compound.id, s.compound.name, smiles[s.compound.id][1])
                for s in chosen if s.compound.id in smiles]
    if not runnable:
        ap.error("none of the selected compounds have a SMILES")

    print(f"{before.extraction.plant_name} [{before.extraction.part}] -> "
          f"{before.condition.name}")
    print(f"docking {len(runnable)} compound(s) into {', '.join(targets)} "
          f"(exhaustiveness {args.exhaustiveness})")
    for _, name, _ in runnable:
        print(f"  - {name}")
    print("-" * 74)

    payload = dk.dock_live(runnable, targets, exhaustiveness=args.exhaustiveness)

    for cid, row in payload["scores"].items():
        for gene, score in row["targets"].items():
            tag = "cache" if score["cached"] else f"{score['seconds']:.1f}s"
            print(f"  {row['name'][:34]:<34} {gene:<7} "
                  f"{score['affinity']:>7.2f} kcal/mol  {tag}")

    merged = dict(panel)
    for cid, per in payload["affinities"].items():
        merged[cid] = {**merged.get(cid, {}), **per}
    after = rk.run(args.plant, args.part, args.solvent, args.condition,
                   docking_scores=merged or None)

    print("-" * 74)
    print(f"coverage: {after.n_docked}/{after.n_candidates} candidates docked")
    print(f"{'#':>3} {'compound':<38} {'score':>6}  docking")
    for s in after.ranked[:args.candidates + 2]:
        aff = ", ".join(f"{g} {a:.2f}" for g, a in sorted(s.docking.items()))
        print(f"{s.rank:>3} {s.compound.name[:38]:<38} {s.score:>6.3f}  {aff or '-'}")

    record = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "plant": args.plant,
        "part": args.part,
        "solvent": args.solvent,
        "condition": args.condition,
        "targets": list(targets),
        "exhaustiveness": args.exhaustiveness,
        "engine": payload["engine"],
        "vina": payload["vina"],
        "seed": payload["seed"],
        "fresh": payload["fresh"],
        "reused": payload["reused"],
        "scores": payload["scores"],
        "coverage_before": {"docked": before.n_docked, "candidates": before.n_candidates},
        "coverage_after": {"docked": after.n_docked, "candidates": after.n_candidates},
        "shortlist_after": [
            {"rank": s.rank, "name": s.compound.name, "score": round(s.score, 4),
             "docking": s.docking}
            for s in after.ranked
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
