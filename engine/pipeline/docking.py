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
        "PTGS2", "3NT1", "NPS", ("HEM",),
        "naproxen",
        "COX-2. The established inflammatory target and the demo's original anchor. "
        "Peroxidase heme (HEM A/B 619) is retained 32.5 A from the cyclooxygenase pocket.",
    ),
    "ALOX5": TargetSpec(
        "ALOX5", "3V99", "ACD", ("FE2",),
        "arachidonic acid",
        "5-lipoxygenase, 2.25 A, stable S663D construct. Arachidonic acid marks "
        "the substrate site; the catalytic Fe2+ (FE2 A 701, 7.5 A from box centre) is retained.",
    ),
    "MAPK14": TargetSpec(
        "MAPK14", "3D83", "GK6", (),
        "biphenyl amide inhibitor",
        "p38-alpha MAPK, 1.90 A. The best-resolution p38 structure with a "
        "drug-like inhibitor in the ATP pocket.",
    ),
    "TNF": TargetSpec(
        "TNF", "2AZ5", "307", (),
        "small-molecule dimer-interface inhibitor 307",
        "TNF-alpha, 2.10 A. Co-crystallised small-molecule inhibitor at the "
        "homodimer interface; available for on-demand live docking.",
    ),
    "ACHE": TargetSpec(
        "ACHE", "4EY7", "E20", (),
        "donepezil (E20)",
        "Human acetylcholinesterase, 2.35 A, in complex with Donepezil (Aricept). "
        "Primary symptomatic target in Alzheimer's disease.",
    ),
    "PPARG": TargetSpec(
        "PPARG", "2PRG", "BRL", (),
        "rosiglitazone (BRL)",
        "Human PPAR-gamma ligand-binding domain, 2.30 A, in complex with "
        "Rosiglitazone. Master regulator in Type 2 diabetes and mucosal inflammation.",
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


# --------------------------------------------------------------------------
# 2D structure + 3D pose inspection for the workbench
# --------------------------------------------------------------------------
_AD_TO_ELEM = {
    "A": "C", "C": "C", "NA": "N", "N": "N", "OA": "O", "O": "O",
    "SA": "S", "S": "S", "HD": "H", "H": "H", "HS": "H",
    "P": "P", "F": "F", "Cl": "Cl", "CL": "Cl", "Br": "Br", "BR": "Br",
    "I": "I", "Fe": "Fe", "FE": "Fe", "Zn": "Zn", "Mg": "Mg",
}


def render_2d_svg(smiles: str | None, width: int = 340, height: int = 210) -> str | None:
    """Render a transparent 2D chemical depiction SVG via RDKit."""
    if not smiles or not smiles.strip():
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    try:
        from rdkit.Chem import rdDepictor
        from rdkit.Chem.Draw import rdMolDraw2D

        rdDepictor.Compute2DCoords(mol)
        drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
        opts = drawer.drawOptions()
        opts.clearBackground = True
        opts.bondLineWidth = 1.8
        opts.padding = 0.08
        drawer.DrawMolecule(mol)
        drawer.FinishDrawing()
        return drawer.GetDrawingText()
    except Exception:  # noqa: BLE001
        return None


def _pdbqt_line_to_pdb(line: str, serial: int) -> str:
    """Convert one PDBQT ATOM/HETATM line to a standard 80-col PDB HETATM record."""
    ad_type = line[76:].strip() or line.split()[-1]
    raw_name = line[12:16].strip()
    elem = _AD_TO_ELEM.get(ad_type)
    if not elem:
        letters = "".join(c for c in raw_name if c.isalpha())
        elem = (letters[:2].capitalize() if letters[:2].upper() in {"CL", "BR", "FE", "ZN", "MG"}
                else (letters[:1].upper() or "C"))
    atom_name = f" {raw_name:<3}" if len(raw_name) < 4 else raw_name[:4]
    coords = line[30:54]
    return f"HETATM{serial:>5} {atom_name} LIG L   1    {coords}  1.00  0.00          {elem:>2}"


def parse_pdbqt_modes(pdbqt_path: Path) -> list[dict]:
    """Extract all Vina binding modes (affinity, RMSD, energies, clean PDB block)."""
    if not pdbqt_path.exists():
        return []
    modes: list[dict] = []
    cur_mode = 0
    affinity: float | None = None
    rmsd_lb: float | None = None
    rmsd_ub: float | None = None
    inter_e: float | None = None
    intra_e: float | None = None
    pdb_lines: list[str] = []
    coords: list[tuple[float, float, float]] = []
    serial = 0

    for line in pdbqt_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("MODEL"):
            parts = line.split()
            cur_mode = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else len(modes) + 1
            affinity = rmsd_lb = rmsd_ub = inter_e = intra_e = None
            pdb_lines = []
            coords = []
            serial = 0
        elif line.startswith("REMARK VINA RESULT:"):
            nums = line.replace("REMARK VINA RESULT:", "").split()
            if len(nums) >= 3:
                affinity = float(nums[0])
                rmsd_lb = float(nums[1])
                rmsd_ub = float(nums[2])
        elif line.startswith("REMARK INTER:"):
            try:
                inter_e = float(line.split(":")[1].strip())
            except (IndexError, ValueError):
                pass
        elif line.startswith("REMARK INTRA:"):
            try:
                intra_e = float(line.split(":")[1].strip())
            except (IndexError, ValueError):
                pass
        elif line.startswith(("ATOM", "HETATM")):
            serial += 1
            pdb_lines.append(_pdbqt_line_to_pdb(line, serial))
            try:
                coords.append(_coord(line))
            except ValueError:
                pass
        elif line.startswith("ENDMDL"):
            if pdb_lines:
                pdb_lines.append("END")
                modes.append({
                    "mode": cur_mode or (len(modes) + 1),
                    "affinity": affinity,
                    "rmsd_lb": rmsd_lb,
                    "rmsd_ub": rmsd_ub,
                    "inter_energy": inter_e,
                    "intra_energy": intra_e,
                    "atoms": serial,
                    "pdb_block": "\n".join(pdb_lines),
                    "_coords": coords,
                })
    return modes


def pocket_contacts(
    receptor_pdb: Path,
    ligand_coords: list[tuple[float, float, float]],
    *,
    cutoff: float = 4.5,
    limit: int = 12,
) -> list[dict]:
    """Closest receptor residues and cofactors within `cutoff` A of the ligand pose."""
    import math

    if not receptor_pdb.exists() or not ligand_coords:
        return []
    best_by_res: dict[tuple[str, str, int], tuple[float, bool]] = {}
    for line in _pdb_atoms(receptor_pdb):
        rec_type = line[:6].strip()
        atom_name = line[12:16].strip()
        if atom_name.startswith("H"):
            continue
        resname = line[17:20].strip()
        chain = line[21:22].strip() or "A"
        try:
            resid = int(line[22:26].strip())
            rc = _coord(line)
        except ValueError:
            continue
        d = min(math.dist(rc, lc) for lc in ligand_coords)
        if d <= cutoff:
            key = (chain, resname, resid)
            is_cof = rec_type == "HETATM" or resname in {"FE2", "FE", "HEM", "ZN", "MG"}
            prev = best_by_res.get(key)
            if prev is None or d < prev[0]:
                best_by_res[key] = (d, is_cof)

    ranked = sorted(best_by_res.items(), key=lambda item: item[1][0])[:limit]
    return [
        {
            "chain": chain,
            "resname": resname,
            "resid": resid,
            "label": f"{resname} {resid}" + (f" ({chain})" if chain != "A" else ""),
            "distance": round(dist, 2),
            "is_cofactor": is_cof,
        }
        for (chain, resname, resid), (dist, is_cof) in ranked
    ]


def _conformer_pdb_in_box(
    smiles: str,
    center: list[float] | tuple[float, float, float],
) -> tuple[str, list[tuple[float, float, float]], int] | None:
    """Embed a 3D RDKit conformer and translate its centroid to `center`."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    try:
        mol = Chem.AddHs(mol)
        params = AllChem.ETKDGv3()
        params.randomSeed = SEED
        if AllChem.EmbedMolecule(mol, params) != 0:
            AllChem.EmbedMolecule(mol, useRandomCoords=True, randomSeed=SEED)
        try:
            AllChem.MMFFOptimizeMolecule(mol, maxIters=500)
        except Exception:  # noqa: BLE001
            pass
        conf = mol.GetConformer()
        n = mol.GetNumAtoms()
        if n == 0:
            return None
        pts = [conf.GetAtomPosition(i) for i in range(n)]
        mx = sum(p.x for p in pts) / n
        my = sum(p.y for p in pts) / n
        mz = sum(p.z for p in pts) / n
        dx, dy, dz = center[0] - mx, center[1] - my, center[2] - mz
        coords: list[tuple[float, float, float]] = []
        for i, p in enumerate(pts):
            nx, ny, nz = p.x + dx, p.y + dy, p.z + dz
            conf.SetAtomPosition(i, (nx, ny, nz))
            coords.append((nx, ny, nz))
        pdb_block = Chem.MolToPDBBlock(mol)
        return pdb_block, coords, n
    except Exception:  # noqa: BLE001
        return None


def resolve_pose(
    compound_id: str,
    target: str,
    *,
    panel_path: Path,
    db: Path = ex.DB_PATH,
) -> dict | None:
    """Resolve the cached 3D Vina pose, 9 modes, pocket contacts, and 2D SVG.

    If a compound is in the corpus but has not been docked against `target` yet,
    returns its 2D RDKit depiction plus a 3D conformer positioned in the target
    pocket (`docked: False`) so the 3D viewer is never blank and can offer
    one-click live Vina docking.
    """
    spec = TARGETS.get(target.upper())
    if spec is None:
        return None

    # 1. Look up compound name + SMILES (corpus first, then panel/cache fallback)
    name: str | None = None
    smiles: str | None = None
    if db.exists() and db.stat().st_size > 0:
        found = compound_smiles([compound_id], db=db)
        if compound_id in found:
            name, smiles = found[compound_id]

    key: str | None = None
    cached_meta: dict | None = None
    if panel_path.exists():
        panel = load_panel(panel_path)
        row = panel.get("scores", {}).get(compound_id)
        if row:
            name = name or row.get("name")
            t_info = row.get("targets", {}).get(spec.gene)
            if t_info and t_info.get("key"):
                key = t_info["key"]

    if key and (CACHE / f"{key}.json").exists():
        cached_meta = json.loads((CACHE / f"{key}.json").read_text(encoding="utf-8-sig"))
        smiles = smiles or cached_meta.get("smiles")
        name = name or cached_meta.get("name")
    else:
        # Scan cache for a matching (receptor == spec.pdb_id) and (smiles or name)
        for jf in sorted(CACHE.glob("*.json")):
            try:
                meta = json.loads(jf.read_text(encoding="utf-8-sig"))
            except Exception:  # noqa: BLE001
                continue
            if meta.get("receptor") != spec.pdb_id:
                continue
            if (smiles and meta.get("smiles") == smiles) or (
                name and (meta.get("name") or "").lower() == name.lower()
            ):
                key = meta.get("key") or jf.stem
                cached_meta = meta
                smiles = smiles or meta.get("smiles")
                name = name or meta.get("name")
                break

    box_file = RECEPTORS / f"{spec.pdb_id}_box.json"
    box = (
        (cached_meta or {}).get("box")
        or (json.loads(box_file.read_text()) if box_file.exists() else None)
    )
    clean_pdb = RECEPTORS / f"{spec.pdb_id}_clean.pdb"
    if not clean_pdb.exists():
        clean_pdb = RECEPTORS / f"{spec.pdb_id}.pdb"

    raw_modes = parse_pdbqt_modes(CACHE / f"{key}.pdbqt") if key else []
    is_docked = bool(raw_modes)

    if not raw_modes:
        if not smiles:
            return None
        center = box["center"] if box and "center" in box else [0.0, 0.0, 0.0]
        embedded = _conformer_pdb_in_box(smiles, center)
        if embedded is None:
            return None
        pdb_block, coords, n_atoms = embedded
        raw_modes = [
            {
                "mode": 1,
                "affinity": None,
                "rmsd_lb": 0.0,
                "rmsd_ub": 0.0,
                "inter_energy": None,
                "intra_energy": None,
                "atoms": n_atoms,
                "pdb_block": pdb_block,
                "_coords": coords,
            }
        ]

    mode1_coords = raw_modes[0].get("_coords", [])
    contacts = pocket_contacts(clean_pdb, mode1_coords)
    for m in raw_modes:
        m.pop("_coords", None)

    best_aff = raw_modes[0]["affinity"]
    return {
        "compound_id": compound_id,
        "compound_name": name or compound_id,
        "smiles": smiles,
        "target": spec.gene,
        "pdb_id": spec.pdb_id,
        "complex_with": spec.complex_with,
        "ligand_code": spec.ligand_code,
        "why": spec.why,
        "docked": is_docked,
        "key": key or "conformer_preview",
        "seed": (cached_meta or {}).get("seed", SEED),
        "exhaustiveness": (cached_meta or {}).get("exhaustiveness", EXHAUSTIVENESS),
        "vina": (cached_meta or {}).get("vina", "AutoDock Vina v1.2.7"),
        "box": box,
        "affinity": best_aff,
        "ligand_efficiency": (
            ligand_efficiency(best_aff, smiles) if (smiles and best_aff is not None) else None
        ),
        "modes": raw_modes,
        "contacts": contacts,
        "svg_2d": render_2d_svg(smiles),
    }


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
