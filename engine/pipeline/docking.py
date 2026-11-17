"""
Docking stage: prepare, run Vina, cache.

Design notes that matter for the demo:

1. Vina is CPU-only. AutoDock Vina 1.2.7 has no GPU path. A GPU is only usable
   through a different program: Uni-Dock is now installed and validated in WSL2
   (see docs/GPU_DOCKING.md) and reproduces these scores to within 0.09 kcal/mol
   mean. This module still runs CPU Vina on purpose -- mixing backends inside one
   comparison table would make the ranking incomparable, and 24 ligands cost
   under two minutes. Using the GPU means re-docking and re-publishing every
   number in DEMO_PLAN.md section 8.

2. Everything is cached by content, not by name. The cache key is a hash of the
   ligand structure, the receptor file, the box, the Vina version, the seed and
   the exhaustiveness. Re-running an identical job returns the stored result
   instantly; changing any input produces a different key and a real run. That
   is what makes a second demo run faster rather than slower.

3. Determinism: `--seed` is fixed and passed explicitly. Same key -> same score.

Usage:
    python -m engine.pipeline.docking --receptor 3NT1 --ligands Curcumin,Eugenol
    python -m engine.pipeline.docking --list-cache
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from rdkit import Chem, RDLogger
from rdkit.Chem import AllChem

from engine.pipeline import extraction as ex

RDLogger.DisableLog("rdApp.*")

ENGINE_DIR = Path(__file__).resolve().parents[1]
WORK = ENGINE_DIR / "data" / "docking"
CACHE = WORK / "cache"
RECEPTORS = WORK / "receptors"
LIGANDS = WORK / "ligands"

VINA = os.environ.get("PHYTOLENS_VINA", r"C:\tools\vina.exe")
OBABEL = os.environ.get("PHYTOLENS_OBABEL",
                        r"C:\Program Files\OpenBabel-3.1.1\obabel.exe")

SEED = 42
EXHAUSTIVENESS = 8


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def vina_version() -> str:
    try:
        out = _run([VINA, "--version"], timeout=30)
        return (out.stdout + out.stderr).strip().splitlines()[0]
    except Exception as exc:  # pragma: no cover
        return f"unavailable ({exc})"


def gpu_available() -> dict:
    """Report honestly whether the GPU can be used. It cannot be, by Vina."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return {"gpu_present": False, "usable_by_vina": False}
    try:
        out = _run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader"], timeout=20)
        return {"gpu_present": bool(out.stdout.strip()),
                "gpu": out.stdout.strip(),
                "usable_by_vina": False,
                "usable_by_unidock": True,
                "reason": ("AutoDock Vina 1.2.x has no GPU support; this pipeline "
                           "runs Vina on CPU. Uni-Dock is installed in WSL2 and "
                           "validated, see docs/GPU_DOCKING.md.")}
    except Exception:
        return {"gpu_present": False, "usable_by_vina": False}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_key(ligand_smiles: str, receptor_sha: str, box: dict,
              exhaustiveness: int = EXHAUSTIVENESS, seed: int = SEED) -> str:
    payload = json.dumps({
        "ligand": ligand_smiles,
        "receptor": receptor_sha,
        "center": [round(box["center"][i], 3) for i in range(3)],
        "size": [round(box["size"][i], 3) for i in range(3)],
        "exhaustiveness": exhaustiveness,
        "seed": seed,
        "vina": vina_version(),
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# receptor
# --------------------------------------------------------------------------
@dataclass
class Receptor:
    pdb_id: str
    path: Path            # prepared .pdbqt
    box: dict             # center / size
    source_pdb: Path
    ligand_code: str
    resolution: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def sha(self) -> str:
        return sha256_file(self.path)


COX_ACTIVE_SITE = {"SER": [530], "ARG": [120], "TYR": [385]}


# --------------------------------------------------------------------------
# target panel
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TargetSpec:
    """A docking target, with the evidence for its box.

    `ligand_code` is always the co-crystallised inhibitor whose centroid defines
    the box. `keep_het` lists cofactors that must survive receptor preparation --
    for ALOX5 that is the catalytic non-heme iron, without which the site is not
    the real enzyme.
    """
    gene: str
    pdb_id: str
    ligand_code: str
    keep_het: tuple[str, ...]
    complex_with: str
    why: str


TARGETS: dict[str, TargetSpec] = {
    "PTGS2": TargetSpec(
        "PTGS2", "3NT1", "NPS", (),
        "naproxen",
        "COX-2. The established inflammatory target and the demo's original anchor.",
    ),
    "ALOX5": TargetSpec(
        "ALOX5", "3V99", "ACD", ("FE2",),
        "arachidonic acid",
        "5-lipoxygenase, 2.25 A, stable S663D construct. Arachidonic acid marks "
        "the substrate site; the catalytic Fe2+ is retained.",
    ),
    "MAPK14": TargetSpec(
        "MAPK14", "3D83", "GK6", (),
        "biphenyl amide inhibitor",
        "p38-alpha MAPK, 1.90 A. The best-resolution p38 structure with a "
        "drug-like inhibitor in the ATP pocket.",
    ),
}

DEFAULT_PANEL: tuple[str, ...] = ("PTGS2", "ALOX5", "MAPK14")


def receptor_for(target: str, *, size: float = 20.0, force: bool = False) -> Receptor:
    """Prepare the receptor named by a panel target (case-insensitive)."""
    spec = TARGETS.get(target.upper())
    if spec is None:
        raise KeyError(f"unknown target {target!r}; panel: {', '.join(sorted(TARGETS))}")
    return prepare_receptor(
        spec.pdb_id, spec.ligand_code, keep_het=spec.keep_het, size=size, force=force
    )


def ligand_efficiency(affinity: float | None, smiles: str) -> float | None:
    """Affinity per heavy atom (kcal/mol/HA). Vina favours large ligands."""
    if affinity is None:
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is None or mol.GetNumHeavyAtoms() == 0:
        return None
    return round(affinity / mol.GetNumHeavyAtoms(), 3)


def dock_panel(
    compounds: list[tuple[str, str, str]],
    targets: tuple[str, ...] = DEFAULT_PANEL,
    *,
    size: float = 20.0,
    force: bool = False,
    progress=None,
) -> dict:
    """Dock compounds against every panel target.

    `compounds` is a list of (compound_id, name, smiles). The return value is
    ready to be written as `engine/data/dock_scores_panel.json` and carries the
    receptor identity and box for each target, so a score can always be traced
    back to the structure that produced it.
    """
    receptors = {gene: receptor_for(gene, size=size, force=force) for gene in targets}
    scores: dict[str, dict] = {}
    for cid, name, smiles in compounds:
        row: dict = {"name": name, "targets": {}}
        for gene, rec in receptors.items():
            result = dock(name, smiles, rec, force=force)
            row["targets"][gene] = {
                "affinity": result.affinity,
                "ligand_efficiency": ligand_efficiency(result.affinity, smiles),
                "seconds": round(result.seconds, 2),
                "cached": result.cached,
                "key": result.key,
            }
            if progress:
                progress(cid, name, gene, result)
        scores[cid] = row

    return {
        "generated": __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        .isoformat(timespec="seconds"),
        "engine": "AutoDock Vina",
        "vina": vina_version(),
        "seed": SEED,
        "exhaustiveness": EXHAUSTIVENESS,
        "box_size": size,
        "targets": {
            gene: {
                "pdb_id": rec.pdb_id,
                "ligand_code": rec.ligand_code,
                "box": rec.box,
                "source": "RCSB PDB",
            }
            for gene, rec in receptors.items()
        },
        "scores": scores,
    }


def dock_live(
    compounds: list[tuple[str, str, str]],
    targets: tuple[str, ...] = DEFAULT_PANEL,
    *,
    size: float = 20.0,
    exhaustiveness: int = EXHAUSTIVENESS,
    force: bool = False,
) -> dict:
    """Dock a bounded set of compounds on demand, bypassing the precomputed panel.

    Identical machinery to `dock_panel` -- same receptors, same box, same seed,
    same content-addressed cache -- only invoked from a request instead of a
    build step. The response keeps `cached` on every score so a demo can be
    honest about which numbers are fresh Vina runs and which were already known.
    """
    receptors = {gene: receptor_for(gene, size=size) for gene in targets}
    scores: dict[str, dict] = {}
    for cid, name, smiles in compounds:
        row: dict = {"name": name, "targets": {}}
        for gene, rec in receptors.items():
            result = dock(name, smiles, rec, exhaustiveness=exhaustiveness,
                          force=force)
            row["targets"][gene] = {
                "affinity": result.affinity,
                "ligand_efficiency": ligand_efficiency(result.affinity, smiles),
                "seconds": round(result.seconds, 2),
                "cached": result.cached,
                "key": result.key,
            }
        scores[cid] = row

    payload = {
        "generated": __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        .isoformat(timespec="seconds"),
        "engine": "AutoDock Vina",
        "vina": vina_version(),
        "seed": SEED,
        "exhaustiveness": exhaustiveness,
        "box_size": size,
        "targets": {
            gene: {
                "pdb_id": rec.pdb_id,
                "ligand_code": rec.ligand_code,
                "box": rec.box,
                "source": "RCSB PDB",
            }
            for gene, rec in receptors.items()
        },
        "scores": scores,
    }
    payload["affinities"] = panel_affinities(payload)
    payload["fresh"] = sum(1 for row in scores.values()
                           for t in row["targets"].values() if not t["cached"])
    payload["reused"] = sum(1 for row in scores.values()
                            for t in row["targets"].values() if t["cached"])
    return payload


def load_panel(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def panel_affinities(panel: dict) -> dict[str, dict[str, float]]:
    """{compound_id: {gene: affinity}} from a panel payload."""
    out: dict[str, dict[str, float]] = {}
    for cid, row in panel.get("scores", {}).items():
        per = {g: v["affinity"] for g, v in row.get("targets", {}).items()
               if v.get("affinity") is not None}
        if per:
            out[cid] = per
    return out


def _resolution(path: Path) -> float | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("REMARK   2 RESOLUTION."):
                    return float(line[23:30])
                if line.startswith("ATOM"):
                    break
    except (OSError, ValueError):
        pass
    return None



def _pdb_atoms(path: Path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith(("ATOM", "HETATM")):
                yield line


def _coord(line: str) -> tuple[float, float, float]:
    return (float(line[30:38]), float(line[38:46]), float(line[46:54]))


def prepare_receptor(pdb_id: str, ligand_code: str, *,
                     keep_het: tuple[str, ...] = ("HEM",),
                     size: float = 20.0,
                     force: bool = False) -> Receptor:
    """Download a PDB, strip solvent/ligands, convert to PDBQT, define the box.

    The box is centred on the co-crystallised inhibitor (or, failing that, on
    the catalytic residues), and the coordinates are recorded in the result so
    the box is never a magic number in someone's slide.
    """
    RECEPTORS.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    src = RECEPTORS / f"{pdb_id}.pdb"
    clean = RECEPTORS / f"{pdb_id}_clean.pdb"
    out = RECEPTORS / f"{pdb_id}.pdbqt"

    if not src.exists() or force:
        import urllib.request
        url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
        urllib.request.urlretrieve(url, src)

    if out.exists() and not force:
        box_file = RECEPTORS / f"{pdb_id}_box.json"
        box = json.loads(box_file.read_text())
        return Receptor(pdb_id, out, box, src, ligand_code)

    # Box centre from the co-crystal ligand.
    coords = [c for line in _pdb_atoms(src)
              if line[17:20].strip() == ligand_code for c in [_coord(line)]]
    if not coords:
        raise RuntimeError(f"{pdb_id}: ligand {ligand_code} not found; "
                           f"cannot define a defensible box")
    cx = sum(c[0] for c in coords) / len(coords)
    cy = sum(c[1] for c in coords) / len(coords)
    cz = sum(c[2] for c in coords) / len(coords)
    box = {"center": [round(cx, 3), round(cy, 3), round(cz, 3)],
           "size": [size, size, size],
           "defined_by": f"centroid of {ligand_code} ({len(coords)} atoms)"}

    # Keep protein, drop solvent and the original inhibitor, optionally keep a
    # cofactor. `ligand_code` is dropped unconditionally: it defines the box, so
    # leaving it in the receptor would dock every ligand on top of an existing
    # molecule. Relying on a hardcoded list here is how a future receptor ends up
    # silently self-occupied.
    drop = {"HOH", "NPS", "ID8", "NAG", "BOG", "CL", "NH4", "EDO", "AKR",
            ligand_code}
    with open(clean, "w", encoding="utf-8") as fh:
        for line in _pdb_atoms(src):
            rec = line[17:20].strip()
            if line.startswith("ATOM"):
                fh.write(line)
            elif rec in keep_het and rec not in drop:
                fh.write(line)

    proc = _run([OBABEL, str(clean), "-O", str(out), "-xr", "-p", "7.4"])
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"receptor prep failed: {proc.stderr[-500:]}")

    (RECEPTORS / f"{pdb_id}_box.json").write_text(json.dumps(box, indent=2))
    return Receptor(pdb_id, out, box, src, ligand_code)


# --------------------------------------------------------------------------
# ligand
# --------------------------------------------------------------------------
def prepare_ligand(name: str, smiles: str) -> Path:
    LIGANDS.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:48]
    sdf = LIGANDS / f"{safe}.sdf"
    out = LIGANDS / f"{safe}.pdbqt"
    if out.exists() and out.stat().st_size > 0:
        return out

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"RDKit cannot parse SMILES for {name}")
    mol = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = SEED
    if AllChem.EmbedMolecule(mol, params) != 0:
        raise RuntimeError(f"3D embedding failed for {name}")
    AllChem.MMFFOptimizeMolecule(mol, maxIters=2000)
    sdf.write_text(Chem.MolToMolBlock(mol), encoding="utf-8")

    proc = _run([OBABEL, str(sdf), "-O", str(out), "--partialcharge", "gasteiger"])
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"ligand prep failed for {name}: {proc.stderr[-400:]}")
    return out


# --------------------------------------------------------------------------
# docking
# --------------------------------------------------------------------------
@dataclass
class DockResult:
    name: str
    affinity: float | None
    rmsd_lb: float | None
    modes: list[float]
    cached: bool
    seconds: float
    key: str
    best_pose: str | None = None

    def as_dict(self) -> dict:
        return {"name": self.name, "affinity": self.affinity,
                "rmsd_lb": self.rmsd_lb, "modes": self.modes,
                "cached": self.cached, "seconds": round(self.seconds, 2),
                "key": self.key, "best_pose": self.best_pose}


MODES_RE = re.compile(r"REMARK VINA RESULT:\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)")


def dock(name: str, smiles: str, rec: Receptor, *,
         exhaustiveness: int = EXHAUSTIVENESS, seed: int = SEED,
         force: bool = False) -> DockResult:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = cache_key(smiles, rec.sha, rec.box, exhaustiveness, seed)
    cache_file = CACHE / f"{key}.json"
    if cache_file.exists() and not force:
        payload = json.loads(cache_file.read_text())
        return DockResult(name=payload["name"], affinity=payload["affinity"],
                          rmsd_lb=payload["rmsd_lb"], modes=payload["modes"],
                          cached=True, seconds=0.0, key=key,
                          best_pose=payload.get("best_pose"))

    lig = prepare_ligand(name, smiles)
    out = CACHE / f"{key}.pdbqt"
    t0 = time.time()
    proc = _run([
        VINA,
        "--receptor", str(rec.path),
        "--ligand", str(lig),
        "--center_x", str(rec.box["center"][0]),
        "--center_y", str(rec.box["center"][1]),
        "--center_z", str(rec.box["center"][2]),
        "--size_x", str(rec.box["size"][0]),
        "--size_y", str(rec.box["size"][1]),
        "--size_z", str(rec.box["size"][2]),
        "--exhaustiveness", str(exhaustiveness),
        "--seed", str(seed),
        "--num_modes", "9",
        "--out", str(out),
    ], timeout=3600)
    elapsed = time.time() - t0

    text = (out.read_text(errors="replace") if out.exists() else "") + proc.stdout
    hits = MODES_RE.findall(text)
    if not hits:
        raise RuntimeError(f"Vina produced no result for {name}: "
                           f"{proc.stderr[-400:] or proc.stdout[-400:]}")

    modes = [float(a) for a, _ in hits]
    result = DockResult(
        name=name, affinity=modes[0], rmsd_lb=float(hits[0][1]),
        modes=modes, cached=False, seconds=elapsed, key=key,
        best_pose=str(out) if out.exists() else None,
    )
    cache_file.write_text(json.dumps({
        **result.as_dict(),
        "smiles": smiles,
        "receptor": rec.pdb_id,
        "box": rec.box,
        "exhaustiveness": exhaustiveness,
        "seed": seed,
        "vina": vina_version(),
    }, indent=2))
    return result


# --------------------------------------------------------------------------
# corpus lookup
# --------------------------------------------------------------------------
def compound_smiles(compound_ids: list[str], db: Path = ex.DB_PATH) -> dict[str, tuple[str, str]]:
    """{compound_id: (name, smiles)} for a set of ids, skipping any without SMILES."""
    import sqlite3
    out: dict[str, tuple[str, str]] = {}
    if not compound_ids:
        return out
    con = sqlite3.connect(db)
    try:
        for i in range(0, len(compound_ids), 400):
            part = compound_ids[i:i + 400]
            ph = ",".join("?" * len(part))
            for cid, name, smiles in con.execute(
                f"SELECT id, name, smiles FROM compounds WHERE id IN ({ph})", part
            ):
                if smiles:
                    out[cid] = (name or cid, smiles)
    finally:
        con.close()
    return out


def ligand_smiles(name: str, db: Path = ex.DB_PATH) -> tuple[str, str]:
    import sqlite3
    con = sqlite3.connect(db)
    try:
        row = con.execute(
            "SELECT id, name, smiles FROM compounds WHERE name=? COLLATE NOCASE LIMIT 1",
            (name,),
        ).fetchone()
    finally:
        con.close()
    if not row:
        raise LookupError(f"no compound named {name!r} in the corpus")
    if not row[2]:
        raise ValueError(f"{name} has no SMILES")
    return row[0], row[2]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dock ligands into a prepared receptor")
    ap.add_argument("--pdb", default="3NT1", help="PDB id (default 3NT1: COX-2 + naproxen)")
    ap.add_argument("--ligand-code", default="NPS", help="co-crystal ligand defining the box")
    ap.add_argument("--box", type=float, default=20.0)
    ap.add_argument("--ligands", help="comma-separated compound names")
    ap.add_argument("--force", action="store_true", help="ignore cache")
    ap.add_argument("--list-cache", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.list_cache:
        CACHE.mkdir(parents=True, exist_ok=True)
        files = sorted(CACHE.glob("*.json"))
        print(f"{len(files)} cached dockings in {CACHE}")
        for f in files:
            p = json.loads(f.read_text())
            print(f"  {p['key']}  {p['name'][:30]:<30} {p['affinity']:>7} kcal/mol")
        return 0

    names = [n.strip() for n in (args.ligands or "Curcumin").split(",") if n.strip()]
    rec = prepare_receptor(args.pdb, args.ligand_code, size=args.box, force=args.force)
    info = gpu_available()
    print(f"receptor   {rec.pdb_id}  box {rec.box['size']} Ã…  {rec.box['defined_by']}")
    print(f"vina       {vina_version()}")
    print(f"gpu        {info.get('gpu', 'none')} -> usable by Vina: {info['usable_by_vina']}")
    print("-" * 74)

    results = []
    for name in names:
        _, smiles = ligand_smiles(name)
        r = dock(name, smiles, rec, force=args.force)
        results.append(r)
        tag = "cached" if r.cached else f"{r.seconds:.0f}s"
        print(f"  {name[:32]:<32} {r.affinity:>7.2f} kcal/mol   {tag:<8} {r.key}")

    if args.json:
        print(json.dumps([r.as_dict() for r in results], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
