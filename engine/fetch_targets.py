"""
Fetch a condition's target set from Open Targets and cache it locally.

Why Open Targets: it is CC0, machine-readable, and every association carries the
evidence types behind it (genetic, literature, expression, pathways). That lets
the report state *why* a gene belongs to the condition, instead of asserting it.

The condition target set is what turns "this compound hits 194 proteins" into a
question that matters: "how many of them are proteins implicated in THIS
condition, and how good is the evidence for each?".

Usage:
    python -m engine.fetch_targets --disease MONDO_0005292 --name colitis --min-score 0.4
    python -m engine.fetch_targets --list "inflammat"

Output: engine/data/targets/<name>.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
OUT_DIR = ENGINE_DIR / "data" / "targets"
API = "https://api.platform.opentargets.org/api/v4/graphql"
PAGE = 500


def gql(query: str) -> dict:
    body = json.dumps({"query": query}).encode()
    req = urllib.request.Request(
        API, data=body,
        headers={"Content-Type": "application/json",
                 "User-Agent": "phytolens-hackathon"},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        payload = json.loads(r.read().decode())
    if "errors" in payload:
        raise RuntimeError(payload["errors"][0].get("message", payload["errors"]))
    return payload["data"]


def search(term: str) -> list[dict]:
    q = '{ search(queryString:%s, entityNames:["disease"]) { hits { id name } } }' % json.dumps(term)
    return gql(q)["search"]["hits"]


def disease_targets(disease_id: str, min_score: float) -> dict:
    """All associations above `min_score`, with their evidence breakdown."""
    rows: list[dict] = []
    index = 0
    meta = None
    while True:
        q = (
            '{ disease(efoId:%s) { id name '
            '  associatedTargets(page:{index:%d,size:%d}) { count rows { '
            '    score target { approvedSymbol } '
            '    datasourceScores { id score } } } } }'
            % (json.dumps(disease_id), index, PAGE)
        )
        d = gql(q)["disease"]
        if d is None:
            raise RuntimeError(f"Open Targets has no disease {disease_id!r}")
        meta = {"id": d["id"], "name": d["name"]}
        page = d["associatedTargets"]["rows"]
        rows.extend(page)
        total = d["associatedTargets"]["count"]
        index += 1
        # Stop once the page has fallen below the threshold or we have them all.
        if not page or page[-1]["score"] < min_score or len(rows) >= total:
            break

    kept = [r for r in rows if r["score"] >= min_score]
    kept.sort(key=lambda r: -r["score"])
    return {
        "condition": {
            **meta,
            "min_score": min_score,
            "source": "Open Targets Platform, GraphQL v4",
            "endpoint": API,
            "licence": "CC0 1.0",
            "retrieved": dt.date.today().isoformat(),
            "total_associations": total,
            "targets_kept": len(kept),
        },
        "targets": [
            {
                "symbol": r["target"]["approvedSymbol"],
                "score": round(r["score"], 4),
                "evidence": {s["id"]: round(s["score"], 4)
                             for s in r["datasourceScores"] if s["score"] > 0},
            }
            for r in kept
        ],
    }


def write(payload: dict, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cache an Open Targets disease target set")
    ap.add_argument("--disease", help="Open Targets / MONDO id, e.g. MONDO_0005292")
    ap.add_argument("--name", help="cache slug, e.g. colitis")
    ap.add_argument("--min-score", type=float, default=0.4,
                    help="association threshold (default 0.4)")
    ap.add_argument("--list", metavar="TERM", help="search disease names and exit")
    args = ap.parse_args(argv)

    if args.list:
        hits = search(args.list)
        for h in hits[:20]:
            print(f"  {h['id']:<22} {h['name']}")
        return 0

    if not args.disease or not args.name:
        ap.error("--disease and --name are required unless --list is used")

    payload = disease_targets(args.disease, args.min_score)
    path = write(payload, args.name)
    c = payload["condition"]
    print(f"{c['name']} ({c['id']})")
    print(f"  associations total : {c['total_associations']:,}")
    print(f"  kept at score >= {args.min_score}: {c['targets_kept']:,}")
    print(f"  written            : {path.relative_to(ENGINE_DIR.parent)}")
    print("  top 12: " + ", ".join(f"{t['symbol']}({t['score']:.2f})"
                                   for t in payload["targets"][:12]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
