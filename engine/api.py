"""FastAPI service for PhytoLens v0.1.

The API is a thin layer over the engine: it resolves a formulation, queues a
run, persists run state in SQLite, and serves the shortlist and PDF. Runs go to
Redis when it is reachable and to a local thread pool otherwise, so the demo
works on a laptop with no services (``engine/jobs.py``).

Docking is precomputed for the demo panel. ``POST /v1/runs/{id}/dock`` is the
exception: it runs Vina on demand for a bounded number of candidates and merges
the fresh scores into the shortlist. That endpoint is CPU time, so it carries
the tightest rate limit and requires an API key when auth is configured.

Run:
    uvicorn engine.api:app --reload --port 8000
    python -m engine.api            # same, via this module's __main__
    python -m engine.worker         # if using Redis
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from engine import auth, jobs, ratelimit
from engine.pipeline import docking as dk
from engine.pipeline import extraction as ex
from engine.pipeline import ranking as rk
from engine.report import build_report

ENGINE_DIR = Path(__file__).resolve().parent
DATA_DIR = ENGINE_DIR / "data"
PANEL_PATH = DATA_DIR / "dock_scores_panel.json"
REPORTS_DIR = DATA_DIR / "reports"
VERSION = "0.1.0"

DEMO = {"plant": "Curcuma longa", "part": "rhizome", "solvent": "ethanol",
        "condition": "colitis"}

STAGES = ("queued", "resolving", "filtering", "scoring", "complete", "failed")

_VALIDATION_CACHE: dict = {}


# --------------------------------------------------------------------------
# run persistence
# --------------------------------------------------------------------------
def runs_db() -> Path:
    return Path(os.environ.get("PHYTOLENS_RUNS_DB", DATA_DIR / "runs.db"))
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    path = runs_db()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS formulations (
            id      TEXT PRIMARY KEY,
            created TEXT NOT NULL,
            request TEXT NOT NULL,
            resolved TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id         TEXT PRIMARY KEY,
            status     TEXT NOT NULL,
            stage      TEXT NOT NULL,
            created    TEXT NOT NULL,
            updated    TEXT NOT NULL,
            request    TEXT NOT NULL,
            result     TEXT,
            error      TEXT,
            owner      TEXT
        )
        """
    )
    # Older databases predate the owner column; add it instead of requiring a
    # migration tool for a single-column change.
    columns = {row[1] for row in con.execute("PRAGMA table_info(runs)")}
    if "owner" not in columns:
        con.execute("ALTER TABLE runs ADD COLUMN owner TEXT")
    con.commit()
    return con


def _save(run_id: str, *, status: str, stage: str, request: dict | None = None,
          result: dict | None = None, error: str | None = None,
          owner: str | None = None) -> None:
    con = _connect()
    try:
        row = con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            con.execute(
                "INSERT INTO runs (id,status,stage,created,updated,request,result,error,owner)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (run_id, status, stage, _now(), _now(),
                 json.dumps(request or {}), json.dumps(result) if result else None,
                 error, owner),
            )
        else:
            con.execute(
                "UPDATE runs SET status=?, stage=?, updated=?, result=?, error=? WHERE id=?",
                (status, stage, _now(),
                 json.dumps(result) if result else row["result"], error, run_id),
            )
        con.commit()
    finally:
        con.close()


def _save_formulation(formulation_id: str, request: dict, resolved: dict) -> None:
    con = _connect()
    try:
        con.execute(
            "INSERT INTO formulations (id,created,request,resolved) VALUES (?,?,?,?)",
            (formulation_id, _now(), json.dumps(request), json.dumps(resolved)),
        )
        con.commit()
    finally:
        con.close()


def _load_formulation(formulation_id: str) -> dict | None:
    con = _connect()
    try:
        row = con.execute("SELECT * FROM formulations WHERE id=?",
                          (formulation_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    return {"formulation_id": row["id"], "created": row["created"],
            **json.loads(row["resolved"])}


def _load(run_id: str) -> dict | None:
    con = _connect()
    try:
        row = con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    return {
        "id": row["id"],
        "status": row["status"],
        "stage": row["stage"],
        "created": row["created"],
        "updated": row["updated"],
        "request": json.loads(row["request"]),
        "result": json.loads(row["result"]) if row["result"] else None,
        "error": row["error"],
        "owner": row["owner"],
    }


# --------------------------------------------------------------------------
# data helpers
# --------------------------------------------------------------------------
def docking_index() -> dict[str, dict[str, float]]:
    if not PANEL_PATH.exists():
        return {}
    return dk.panel_affinities(dk.load_panel(PANEL_PATH))


def panel_meta() -> dict:
    if not PANEL_PATH.exists():
        return {}
    return dk.load_panel(PANEL_PATH).get("targets", {})


def corpus_counts() -> dict:
    con = sqlite3.connect(ex.DB_PATH)
    try:
        q = lambda s: con.execute(s).fetchone()[0]
        return {
            "plants": q("SELECT COUNT(*) FROM plants"),
            "compounds": q("SELECT COUNT(*) FROM compounds"),
            "plant_compounds": q("SELECT COUNT(*) FROM plant_compounds"),
            "compound_targets": q("SELECT COUNT(*) FROM compound_targets"),
        }
    finally:
        con.close()


def cached_conditions() -> list[dict]:
    out = []
    for path in sorted(rk.TARGETS_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        c = payload["condition"]
        out.append({
            "name": path.stem,
            "id": c.get("id"),
            "label": c.get("name"),
            "targets": c.get("targets_kept", len(payload.get("targets", []))),
            "min_score": c.get("min_score"),
            "retrieved": c.get("retrieved"),
            "source": c.get("source"),
            "licence": c.get("licence"),
        })
    return out


def resolve_formulation(plant: str, part: str, solvent: str) -> dict:
    con = sqlite3.connect(ex.DB_PATH)
    try:
        try:
            plant_id, plant_name = ex.resolve_plant(con, plant)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        parts = [{"part": p, "compounds": n} for p, n in ex.list_parts(con, plant_id)]
    finally:
        con.close()

    config = ex.load_config()
    try:
        spec = ex.solvent_spec(config, solvent)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if part.strip().lower() not in {p["part"] for p in parts}:
        raise HTTPException(
            status_code=400,
            detail={"message": f"no part {part!r} for {plant_name}",
                    "available_parts": parts},
        )
    compounds = sum(1 for p in parts if p["part"] == part.strip().lower()
                    for _ in range(p["compounds"]))
    return {
        "plant_id": plant_id,
        "plant": plant_name,
        "part": part.strip().lower(),
        "solvent": solvent.strip().lower(),
        "solvent_label": spec["label"],
        "compounds_in_part": compounds,
        "available_parts": parts,
    }


# --------------------------------------------------------------------------
# pipeline execution
# --------------------------------------------------------------------------
def _execute(run_id: str, request: dict) -> None:
    try:
        _save(run_id, status="running", stage="resolving")
        resolve_formulation(request["plant"], request["part"], request["solvent"])

        _save(run_id, status="running", stage="filtering")
        scores = docking_index()
        result = rk.run(
            request["plant"], request["part"], request["solvent"],
            request["condition"], top=request.get("top"),
            docking_scores=scores or None,
        )
        _save(run_id, status="running", stage="scoring")
        summary = result.summary()
        summary["run_id"] = run_id
        summary["docking_targets"] = sorted(panel_meta())
        _save(run_id, status="complete", stage="complete", result=summary)
    except Exception as exc:  # noqa: BLE001 - persisted for diagnosis
        _save(run_id, status="failed", stage="failed", error=f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------
# schemas
# --------------------------------------------------------------------------
class FormulationRequest(BaseModel):
    plant: str = Field(min_length=1)
    part: str = Field(min_length=1)
    solvent: str = "ethanol"
    condition: str | None = None


class RunRequest(BaseModel):
    plant: str = Field(min_length=1)
    part: str = Field(min_length=1)
    solvent: str = "ethanol"
    condition: str = Field(default="colitis", min_length=1)
    top: int | None = Field(default=12, ge=1, le=200)


class LiveDockRequest(BaseModel):
    """Bounded on-demand docking. This runs real Vina, so the caps are hard."""
    targets: list[str] = Field(default_factory=lambda: ["PTGS2"], min_length=1,
                               max_length=2)
    candidates: int = Field(default=2, ge=1, le=6)
    compound_ids: list[str] | None = Field(default=None, max_length=6)
    exhaustiveness: int = Field(default=4, ge=1, le=16)


# --------------------------------------------------------------------------
# app
# --------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_app: FastAPI):
    _connect().close()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    jobs.reset()
    yield


app = FastAPI(title="PhytoLens API", version=VERSION,
              description="In-silico prioritisation. Hypotheses for lab validation only.",
              lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get(
        "PHYTOLENS_CORS_ORIGINS",
        "http://127.0.0.1:3000,http://localhost:3000").split(",") if o.strip()],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining",
                    "X-RateLimit-Reset", "Retry-After"],
    max_age=600,
)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    verdict = ratelimit.evaluate(
        request.method, request.url.path,
        request.headers.get("authorization"),
        request.client.host if request.client else None,
    )
    if not verdict["allowed"]:
        retry = max(1, verdict["reset"] - int(time.time()))
        return JSONResponse(
            status_code=429,
            content={
                "detail": "rate limit exceeded",
                "bucket": verdict["bucket"],
                "limit": verdict["limit"],
                "retry_after": retry,
            },
            headers={
                "Retry-After": str(retry),
                "X-RateLimit-Limit": str(verdict["limit"]),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(verdict["reset"]),
                "X-RateLimit-Backend": verdict["backend"],
            },
        )
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(verdict["limit"])
    response.headers["X-RateLimit-Remaining"] = str(verdict["remaining"])
    response.headers["X-RateLimit-Reset"] = str(verdict["reset"])
    response.headers["X-RateLimit-Backend"] = verdict["backend"]
    return response


@app.get("/v1/health")
def health() -> dict:
    try:
        counts = corpus_counts()
        status = "ok"
    except Exception as exc:  # noqa: BLE001
        counts = {}
        status = f"degraded: {exc}"
    return {
        "status": status,
        "version": VERSION,
        "corpus": counts,
        "conditions": [c["name"] for c in cached_conditions()],
        "docking_panel": str(PANEL_PATH.name) if PANEL_PATH.exists() else None,
        "vina": dk.vina_version(),
        "gpu": dk.gpu_available(),
        "runs_db": str(runs_db()),
        "queue": jobs.status(),
        "auth": {"enabled": auth.enabled(), "scheme": "bearer api key"},
    }


@app.get("/v1/version")
def version() -> dict:
    import platform
    return {"version": VERSION, "python": platform.python_version(),
            "engine": "phytolens-v0.1"}


@app.get("/v1/plants")
def plants(q: str = Query(min_length=1), limit: int = Query(default=8, ge=1, le=50)) -> dict:
    con = sqlite3.connect(ex.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        # One row per plant: a query like "turmeric" matches several aliases of
        # the same plant, and returning each alias produced duplicate rows (and
        # duplicate React keys in the UI). Keep the shortest matching alias.
        rows = con.execute(
            """
            SELECT id, canonical_name, common_name, alias FROM (
                SELECT p.id, p.canonical_name, p.common_name, a.alias,
                       ROW_NUMBER() OVER (
                           PARTITION BY p.id
                           ORDER BY length(a.alias), a.alias
                       ) AS rn
                  FROM plant_aliases a JOIN plants p ON p.id = a.plant_id
                 WHERE lower(a.alias) LIKE ?
            ) WHERE rn = 1
            ORDER BY length(alias), canonical_name
            LIMIT ?
            """,
            (f"%{q.strip().lower()}%", limit),
        ).fetchall()
    finally:
        con.close()
    return {"query": q, "results": [
        {"id": r["id"], "plant": r["canonical_name"],
         "common_name": r["common_name"], "matched": r["alias"]}
        for r in rows
    ]}


@app.get("/v1/plants/{plant_id}/parts")
def plant_parts(plant_id: str) -> dict:
    """Parts and compound counts for one plant, without creating a formulation."""
    con = sqlite3.connect(ex.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute("SELECT canonical_name FROM plants WHERE id=?",
                          (plant_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown plant {plant_id!r}")
        parts = [{"part": p, "compounds": n} for p, n in ex.list_parts(con, plant_id)]
    finally:
        con.close()
    return {"plant_id": plant_id, "plant": row["canonical_name"], "parts": parts}


@app.get("/v1/conditions")
def conditions(q: str | None = None) -> dict:
    items = cached_conditions()
    if q:
        needle = q.strip().lower()
        items = [c for c in items
                 if needle in (c["name"] or "").lower()
                 or needle in (c["label"] or "").lower()]
    return {"conditions": items}


@app.post("/v1/formulations", status_code=201)
def create_formulation(body: FormulationRequest,
                       _owner: str | None = Depends(auth.require_write)) -> dict:
    resolved = resolve_formulation(body.plant, body.part, body.solvent)
    formulation_id = "frm_" + uuid.uuid4().hex[:12]
    _save_formulation(formulation_id, body.model_dump(), resolved)
    return {"formulation_id": formulation_id, "created": _now(), **resolved}


@app.get("/v1/formulations/{formulation_id}")
def get_formulation(formulation_id: str) -> dict:
    stored = _load_formulation(formulation_id)
    if stored is None:
        raise HTTPException(status_code=404,
                            detail=f"unknown formulation {formulation_id!r}")
    return stored


@app.post("/v1/runs", status_code=202)
def create_run(body: RunRequest,
               owner: str | None = Depends(auth.require_write)) -> JSONResponse:
    resolve_formulation(body.plant, body.part, body.solvent)
    if body.condition not in {c["name"] for c in cached_conditions()}:
        raise HTTPException(status_code=400,
                            detail=f"condition {body.condition!r} is not cached")
    run_id = "run_" + uuid.uuid4().hex[:12]
    request = body.model_dump()
    _save(run_id, status="queued", stage="queued", request=request, owner=owner)
    receipt = jobs.enqueue(run_id, lambda: _execute(run_id, request))
    return JSONResponse(status_code=202, content={
        "run_id": run_id, "status": "queued", "stage": "queued",
        "poll": f"/v1/runs/{run_id}", "queue": receipt["backend"],
    })


@app.get("/v1/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = _load(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    progress = {"queued": 0.0, "resolving": 0.2, "filtering": 0.5,
                "scoring": 0.8, "complete": 1.0, "failed": 1.0}.get(run["stage"], 0.0)
    return {
        "run_id": run["id"],
        "status": run["status"],
        "stage": run["stage"],
        "progress": progress,
        "request": run["request"],
        "error": run["error"],
        "owner": run["owner"],
        "created": run["created"],
        "updated": run["updated"],
    }


@app.get("/v1/runs/{run_id}/shortlist")
def get_shortlist(run_id: str) -> dict:
    run = _load(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    if run["status"] != "complete":
        raise HTTPException(status_code=409,
                            detail=f"run is {run['status']} ({run['stage']})")
    return run["result"]


@app.get("/v1/runs/{run_id}/network")
def get_network(run_id: str) -> dict:
    """Compound-target-condition graph for the shortlist.

    Nodes carry provenance-free identifiers only; edges state whether the link
    is measured (ChEMBL/BindingDB) or predicted (NPASS-only).
    """
    run = _load(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    if run["status"] != "complete":
        raise HTTPException(status_code=409,
                            detail=f"run is {run['status']} ({run['stage']})")
    summary = run["result"]
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    condition = summary["condition"]
    nodes[f"condition:{condition['id']}"] = {
        "id": f"condition:{condition['id']}", "label": condition["name"],
        "type": "condition"}
    for row in summary["ranked"]:
        cid = f"compound:{row['id']}"
        nodes[cid] = {"id": cid, "label": row["name"], "type": "compound",
                      "rank": row["rank"]}
        for gene in row["overlap"]["genes"]:
            gid = f"target:{gene['symbol']}"
            nodes.setdefault(gid, {"id": gid, "label": gene["symbol"], "type": "target"})
            edges.append({"source": cid, "target": gid,
                          "measured": gene["measured"]})
            edges.append({"source": gid, "target": f"condition:{condition['id']}",
                          "measured": gene["measured"]})
    degree: dict[str, int] = {}
    for edge in edges:
        degree[edge["source"]] = degree.get(edge["source"], 0) + 1
        degree[edge["target"]] = degree.get(edge["target"], 0) + 1
    hubs = sorted((n for n in nodes if n.startswith("target:")),
                  key=lambda n: (-degree.get(n, 0), n))[:10]
    return {"nodes": list(nodes.values()), "edges": edges,
            "hubs": [{"id": h, "label": nodes[h]["label"], "degree": degree.get(h, 0)}
                     for h in hubs]}


@app.get("/v1/runs/{run_id}/report.pdf")
def get_report(run_id: str) -> Response:
    run = _load(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    if run["status"] != "complete":
        raise HTTPException(status_code=409,
                            detail=f"run is {run['status']} ({run['stage']})")
    request = run["request"]
    scores = docking_index()
    result = rk.run(request["plant"], request["part"], request["solvent"],
                    request["condition"], top=request.get("top"),
                    docking_scores=scores or None)
    path = REPORTS_DIR / f"{run_id}.pdf"
    build_report(result, path, docking_meta=panel_meta(), top=request.get("top"))
    return Response(content=path.read_bytes(), media_type="application/pdf",
                    headers={"Content-Disposition":
                             f'inline; filename="{run_id}.pdf"'})


@app.get("/v1/validation")
def validation_report() -> dict:
    """Retrospective validation, untuned, cached for five minutes.

    Read-only on purpose: results on disk are written by
    `python -m engine.validation --all`, never by a GET. Running every case
    twice (with and without docking) reads the whole corpus, so the payload is
    cached rather than recomputed per page load.
    """
    from engine import validation as val

    cached = _VALIDATION_CACHE.get("payload")
    if (cached is not None
            and time.time() - _VALIDATION_CACHE.get("at", 0.0) < 300):
        return cached
    payload = val.run_all(write=False)
    _VALIDATION_CACHE.update(at=time.time(), payload=payload)
    return payload


@app.post("/v1/runs/{run_id}/dock")
def live_dock(run_id: str, body: LiveDockRequest,
              _owner: str | None = Depends(auth.require_write)) -> dict:
    """Dock a bounded set of this run's candidates on demand.

    Example: the top two compounds of a formulation that was never
    pre-scored, into COX-2. Every score records whether it was a fresh Vina
    run or a cache hit, because a live demo must be able to say which.
    """
    run = _load(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
    if run["status"] != "complete":
        raise HTTPException(status_code=409,
                            detail=f"run is {run['status']} ({run['stage']})")

    summary = run["result"]
    ranked = summary["ranked"]
    if body.compound_ids:
        wanted = set(body.compound_ids)
        chosen = [row for row in ranked if row["id"] in wanted]
        missing = sorted(wanted - {row["id"] for row in chosen})
        if missing:
            raise HTTPException(status_code=400,
                                detail=f"compounds not in this run: {missing}")
    else:
        chosen = ranked[:body.candidates]

    targets = tuple(t.upper() for t in body.targets)
    unknown = [t for t in targets if t not in dk.TARGETS]
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"unknown targets {unknown}; panel: "
                                   f"{sorted(dk.TARGETS)}")

    smiles = dk.compound_smiles([row["id"] for row in chosen])
    runnable = [(row["id"], row["name"], smiles[row["id"]][1])
                for row in chosen if row["id"] in smiles]
    skipped = [row["name"] for row in chosen if row["id"] not in smiles]
    if not runnable:
        raise HTTPException(status_code=422,
                            detail="none of the selected compounds have a SMILES")

    payload = dk.dock_live(runnable, targets, exhaustiveness=body.exhaustiveness)

    # Merge the fresh scores over the precomputed panel and re-rank, so the
    # demo shows the effect of the live run rather than a disconnected table.
    merged = docking_index()
    for cid, per in payload["affinities"].items():
        merged[cid] = {**merged.get(cid, {}), **per}
    request = run["request"]
    result = rk.run(request["plant"], request["part"], request["solvent"],
                    request["condition"], top=request.get("top"),
                    docking_scores=merged or None)
    updated = result.summary()
    updated["run_id"] = run_id
    updated["docking_targets"] = sorted(panel_meta())
    _save(run_id, status="complete", stage="complete", result=updated)

    return {
        "run_id": run_id,
        "docked": payload["scores"],
        "affinities": payload["affinities"],
        "fresh": payload["fresh"],
        "reused": payload["reused"],
        "skipped_no_smiles": skipped,
        "engine": payload["engine"],
        "vina": payload["vina"],
        "seed": payload["seed"],
        "exhaustiveness": payload["exhaustiveness"],
        "targets": payload["targets"],
        "shortlist": updated["ranked"],
        "docking": updated["docking"],
    }


@app.get("/v1/structures/{target}")
def get_structure(target: str) -> dict:
    spec = dk.TARGETS.get(target.upper())
    if spec is None:
        raise HTTPException(status_code=404,
                            detail=f"unknown target {target!r}; "
                                   f"panel: {sorted(dk.TARGETS)}")
    meta = panel_meta().get(spec.gene, {})
    pdb_path = dk.RECEPTORS / f"{spec.pdb_id}.pdb"
    resolution = dk._resolution(pdb_path) if pdb_path.exists() else None
    return {
        "target": spec.gene,
        "tier": "A",
        "tier_reason": "experimental co-crystal structure with a defined pocket",
        "source": "RCSB PDB",
        "pdb_id": spec.pdb_id,
        "resolution": resolution,
        "ligand_code": spec.ligand_code,
        "complex_with": spec.complex_with,
        "keep_het": list(spec.keep_het),
        "why": spec.why,
        "box": meta.get("box"),
        "docked": bool(meta),
    }


@app.get("/v1/demo")
def demo() -> dict:
    """Precomputed demo formulation, synchronously, in one request."""
    scores = docking_index()
    result = rk.run(DEMO["plant"], DEMO["part"], DEMO["solvent"],
                    DEMO["condition"], top=12, docking_scores=scores or None)
    summary = result.summary()
    summary["demo"] = True
    summary["docking_targets"] = sorted(panel_meta())
    return summary


def main() -> None:
    import uvicorn
    uvicorn.run("engine.api:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
