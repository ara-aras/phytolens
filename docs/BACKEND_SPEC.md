# PhytoLens — Backend Requirements & Scope Lock

Status: **draft for signoff**. Everything below is a decision, not an option, unless it appears in
§13 "Decisions needed from you".

Verified: 2026-11-17. Licence facts in §2 were checked against primary sources today, not recalled.

---

## 0. What actually exists

| Thing | State |
|---|---|
| Application code | **None.** No `app/`, `core/`, `requirements.txt`, `validation/`, `tests/` anywhere in the repo. |
| Pitch reel pipeline | Exists (`scripts/`, `projects/phytolens-pitch-reel/`, `vendor/hyperframes`, WhisperX venv). |
| Media assets | `phytolens_pitch_reel.mp4`, `reddit_video.mp4`, 5 WhatsApp clips. |
| Product spec | `README.md` (aspirational; quick start and project tree are placeholders). |

We are starting from zero on the backend. That is fine, but it means the README's build-status
checklist and Features table have to stop reading as present tense until it is real.

---

## 1. Scope lock

### In scope (v0.1 — backend only)

1. Formulation input: plant + plant part + solvent, optional condition.
2. Plant/part → phytochemical mapping, with plant-name alias resolution.
3. Extraction-aware polarity filter (documented heuristic, exact thresholds in config).
4. Drug-likeness filter (Lipinski + Veber, config-driven).
5. Target prediction via **local ChEMBL similarity kNN** (see §3 — this replaced the original plan).
6. Condition → disease-associated targets via **Open Targets**.
7. Compound-target-disease network with hub detection.
8. Structure selection: PDB-first, AlphaFold-second, with explicit **refuse-to-dock** path.
9. Docking via AutoDock Vina, as an **async job**, deterministic and seeded.
10. Deterministic, versioned prioritisation scoring.
11. Full provenance on every ranked row.
12. Retrospective validation harness with two published cases, reported untuned.
13. JSON API + PDF report generation.
14. Offline demo mode (no network, precomputed docking).

### Explicitly out of scope (v0.1)

- Auth, accounts, multi-tenancy, billing.
- A frontend beyond a thin Streamlit shell that consumes the API.
- Live docking of a novel formulation within a demo window (too slow; precompute).
- Any ADMET/toxicity prediction.
- Any claim of efficacy, safety, dosing, or diagnosis.
- Molecular dynamics, free-energy methods (MM/GBSA, FEP).
- Chinese/other traditional-medicine corpora.
- Custom LLM summarisation of results (adds unverifiable text; defer).

### Non-goals that are actually requirements

- **No number may appear in output without provenance.** If we cannot attach a source and method to
  a value, the value does not ship. This is the product's differentiator, not a nicety.
- **Refusal is a feature.** If pocket confidence is low or no reliable structure exists, the target is
  reported as `NOT_DOCKED` with the reason. Never dock into a floppy pocket to fill a table.

---

## 2. Licensing — the decisive constraint

This is the part that decides what is buildable. Verified today:

| Source | Licence (verified) | Commercial use | Verdict |
|---|---|---|---|
| **IMPPAT 2.0** | CC BY-NC; "academic use only, contact for commercial licensing"; **no adaptations** | ❌ | **Blocker.** Core dependency. Cannot ship commercially without a licence. |
| **SwissTargetPrediction** | ToS explicitly forbid "any form of web crawler or other data retrieval tool… in any automated manner" | ❌ | **Not usable as a backend.** No API. Removed from architecture. |
| **ChEMBL** | CC BY-SA 3.0 | ✅ with share-alike | Usable. Share-alike bites on *distribution* of derived databases, not on serving results. |
| **Open Targets Platform** | CC0 1.0 | ✅ | Free and clear. Replaces the vague "a public gene-disease database". |
| **STRING** | CC BY 4.0 | ✅ attribution | Optional PPI expansion only. |
| **AlphaFold DB** | CC BY 4.0, academic **and commercial** | ✅ attribution | Fine. (Distinct from AlphaFold *parameters*, which are CC BY-NC. We only use the DB.) |
| **RCSB PDB** | Public domain | ✅ | Fine; a few entries carry third-party terms. |
| **AutoDock Vina** | Apache 2.0 | ✅ | Fine. |
| **Uni-Dock** | Apache 2.0 (relicensed from LGPL-3 on 2025-03-10) | ✅ | GPU path only. Validated in WSL2, see `docs/GPU_DOCKING.md`. |
| **RDKit** | BSD-3 | ✅ | Fine. |
| **fpocket** | GPL | ⚠️ | GPL. Acceptable only as an external binary invoked by a service; not distributable in the app bundle. |
| **Meeko** | LGPL-2.1 (verified 2026-11-17 against PyPI metadata) | ⚠️ | **Was mislabelled "expected permissive".** It is weak copyleft. Installed in the env but *not imported* by `engine/` — ligand prep goes through RDKit plus the Open Babel binary. Keep it unused, or vendor a PDBQT writer. |
| **P2Rank** | *unverified* | ? | **Verify before shipping.** Fallback design avoids needing it (§6.3). |

### Consequences to accept now

1. **IMPPAT is non-commercial and forbids adaptations.** For the hackathon this is fine and must be
   documented as such. For the product it is a hard gate. Two escape routes, pick one before any
   commercial pilot:
   - **(A) License IMPPAT.** Cheapest technically, unknown cost, and the "no adaptations" clause still
     limits what we can do to it.
   - **(B) Build our own plant→part→compound table** from primary literature plus a permissively
     licensed natural-products set (COCONUT is CC BY 4.0 by its own paper, though its listing also
     says academic-only — **this conflict must be resolved in writing before we rely on it**).
2. **Ship the swap, not the promise.** The plant→compound layer must sit behind a
   `CompoundSource` interface with IMPPAT as one implementation and a licence field on every row.
   Swapping sources must not require touching the pipeline.
3. **ChEMBL share-alike.** Do not distribute a derived ChEMBL database as a downloadable artifact.
   Serve it. Keep ChEMBL IDs and release version on every derived row.

---

## 3. Architecture change: target prediction

The README says "SwissTargetPrediction". That cannot be a backend dependency — the ToS forbids
automated access and there is no API. Replace it with a **local, reproducible, licensable method that
does the same job**, and say so plainly in the pitch. This is a stronger story anyway: we can show
the evidence for each prediction instead of a black-box score.

### Locked method: similarity-based target fishing over ChEMBL

1. **Build the reference set** from ChEMBL activities, filtered to:
   - human, single-protein targets,
   - `assay_type = B` (binding) and `F` (functional),
   - `standard_type ∈ {IC50, Ki, Kd, EC50}`, `pChEMBL ≥ 6`,
   - ChEMBL target confidence score ≥ 8.
2. **Fingerprint** every reference molecule with Morgan2 / 2048 bits (RDKit).
3. **Query** each phytochemical: top-k (k=10) nearest reference molecules by Tanimoto, threshold 0.4.
4. **Score a target** `t` as the sum of similarities over neighbours known to be active on `t`,
   normalised by k. Keep the evidence: neighbour ChEMBL ID, similarity, target, assay.
5. **Report** top-N targets per compound with that evidence attached.

This is the same family of method SwissTargetPrediction uses (2D similarity over curated bioactivity),
implemented by us over a licence-clean source. It is citable, offline, and deterministic.

### Performance

No approximate-NN library needed. Bit-pack the reference fingerprints into a `uint8` matrix, chunk
the queries, and score with popcount matmul. ~500k reference molecules × 2048 bits ≈ 128 MB; ~18k
phytochemicals score in minutes on CPU. Run **once offline** and store the results — this is a data
build step, not a request-time step.

### Fallback if ChEMBL coverage is thin for a compound
Report `NO_TARGET_PREDICTION` with the reason. Do not substitute a guessed target. Coverage rate
across the demo formulation is itself a number we should publish.

---

## 4. Pipeline specification

Each stage is a **pure function** with an explicit input/output contract, a version, and unit tests.
No stage may reach the network at request time; all external data is snapshotted (§9).

### S1 — Ingest formulation
- Input: `[{plant_name, plant_part, solvent, ratio?}]`, optional `condition_name`.
- Resolve plant names through `plant_aliases` (scientific, common, Sanskrit, trade). Fuzzy match must
  return candidates with confidence, never silently pick one.
- Resolve condition to an EFO/MONDO id via Open Targets search.
- **Unresolved name = hard error with candidates.** Silent fuzzy matching is how you ship wrong science.

### S2 — Plant/part → compounds
- `CompoundSource.get(plant_id, part)` → `[(compound_id, name, smiles, source_ref)]`.
- Parts: whole, leaf, root, rhizome, bark, stem, seed, fruit, flower, gum-resin, latex.
- Deduplicate on InChIKey, keep all plant-of-origin links.

### S3 — Normalise compounds
- SMILES → canonical SMILES → InChIKey (RDKit). Salt/solvate stripping. Charge neutralisation.
- Compute: MW, Crippen logP, TPSA, HBD, HBA, rotatable bonds.
- Cross-map to PubChem CID and ChEMBL ID where possible (needed for S5).

### S4 — Extraction-aware filter
Polarity heuristic. **Exact rules go in `config/extraction.yaml`, not in code**, and the file is
versions and shipped with every report.

| Solvent | Class | Rule (documented as a simplification) |
|---|---|---|
| water | polar | logP ≤ 1.5 **or** (logP ≤ 3 and HBD ≥ 2) |
| hydroalcoholic | mid | 0 ≤ logP ≤ 4 |
| ethanol | mid | −0.5 ≤ logP ≤ 5 |
| methanol | mid-polar | −0.5 ≤ logP ≤ 4.5 |
| hexane, chloroform | non-polar | 2 ≤ logP ≤ 9 |

Rationale for the glycoside clause: sugars have low logP but high HBD; a pure logP cut would wrongly
exclude them from aqueous extracts. State the limitation: this is not an extraction model.

### S5 — Drug-likeness
Lipinski (MW ≤ 500, logP ≤ 5, HBD ≤ 5, HBA ≤ 10) and Veber (rotatable ≤ 10, TPSA ≤ 140).
Thresholds config-driven; a compound failing only one rule is flagged, not dropped.

### S6 — Target prediction
As §3. Output rows: `(compound, target, score, method, evidence[])`.

### S7 — Disease targets
Open Targets `associatedTargets` for the condition, `score ≥ 0.2` (config), cap 500, keep the score.
Store the Open Targets release id.

### S8 — Network + hubs
- Bipartite compound–target graph, restricted to targets that intersect the disease set.
- Hub metric: **degree centrality** (primary), betweenness (secondary, reported only).
- Optional STRING expansion is **off by default** — it adds a lot of noise and would let unrelated
  proteins become "hubs".
- Top 5 hubs by degree, ties broken by gene symbol for determinism.

### S9 — Structure selection
Ordered tiers, first match wins, tier recorded:

| Tier | Condition | Pocket definition |
|---|---|---|
| A | PDB entry for the UniProt with a co-crystal ligand | Box = ligand heavy-atom centroid, half-extent = max ligand extent + 8 Å |
| B | PDB apo, but a homologous holo entry exists | Superpose, transfer ligand box |
| C | AlphaFold only | Box transferred from homologous holo, **and** mean pLDDT over box residues ≥ 70 |
| D | No reliable pocket | **`NOT_DOCKED`** with reason |

Record for every structure: `source`, `pdb_id`/`af_id`, `resolution`, `mean_plddt_in_pocket`,
`ligand_used_for_box`, `tier`.

pLDDT ≥ 70 is the conventional "confident" cutoff; it is a parameter, not a magic number, and it
appears in `config/structures.yaml`.

### S10 — Docking
- Engine: Vina, `exhaustiveness = 8`, `num_modes = 9`, **`seed` fixed per (compound, structure)** so
  reruns are identical.
- Receptors: PDBQT **pre-prepared offline and shipped**. This removes the receptor-prep toolchain
  (and its GPL/licence questions) from the runtime entirely.
- Ligands: RDKit 3D embed (ETKDGv3, fixed seed) → Meeko PDBQT, **or** precomputed for the demo.
- Output: affinity (kcal/mol), RMSD l.b./u.b., pose file reference.
- Record `vina_version`, `seed`, `exhaustiveness`, `box_json` per row.

### S11 — Prioritisation
```
score = w_like  · druglike_pass            (0/1)
      + w_net   · hub_degree_norm          [0,1]
      + w_dock  · dock_norm                [0,1]
      + w_sim   · max_target_similarity    [0,1]
```
- **Absolute normalisation, not min-max within run.** Min-max makes every run look confident and
  makes scores incomparable across runs — which destroys the validation. Dock score maps linearly
  from [−12, −4] kcal/mol → [1, 0]; compounds with no dock score contribute 0 and the row is flagged.
- Weights and version in `config/scoring.yaml`. Every run stores `scoring_config_hash`.
- Ties broken deterministically (score desc, then InChIKey asc).

### S12 — Report
JSON first, PDF second. PDF must contain, on every report: scoring config hash, data snapshot ids,
the caveats page, the licence/attribution list, and the per-row provenance appendix.

---

## 5. Data model

SQLite for dev/demo, Postgres for deploy. SQLAlchemy 2.x, Alembic for migrations.

```
plants(id, canonical_name, family, licences_note)
plant_aliases(plant_id, alias, alias_type, source)
compounds(id, inchikey, smiles, name, formula, mw, logp, tpsa, hbd, hba, rotb,
          pubchem_cid, chembl_id, source, licence)
plant_compounds(plant_id, part, compound_id, source_ref)
solvents(id, name, polarity_class)
targets(id, uniprot, gene_symbol, name, organism)
compound_targets(compound_id, target_id, score, method, evidence_json, source_version)
conditions(id, efo_id, name, source_version)
disease_targets(efo_id, target_id, score, source_version)
structures(id, target_id, tier, source, pdb_id, af_id, resolution, mean_plddt, pocket_json)
docking_results(id, structure_id, compound_id, affinity, rmsd_lb, rmsd_ub,
                seed, exhaustiveness, vina_version, box_json, pose_path)
formulations(id, name, created_at)
formulation_items(formulation_id, plant_id, part, solvent_id, ratio)
runs(id, formulation_id, condition_id, status, config_hash, snapshot_ids_json, created_at, finished_at)
run_items(run_id, compound_id, target_id, rank, score, dock_status, provenance_json)
data_snapshots(id, source, version, sha256, retrieved_at, licence)
```

Indexes: `compounds.inchikey` unique, `compound_targets(compound_id)`, `disease_targets(efo_id)`,
`run_items(run_id, rank)`, `structures(target_id)`.

---

## 6. Provenance contract (the moat)

Every `run_items` row carries:

```json
{
  "compound":  {"source": "IMPPAT2", "version": "2022-06-17", "record": "IMPHY01234", "licence": "CC-BY-NC"},
  "target":    {"source": "ChEMBL", "version": "ChEMBL_37", "method": "similarity_knn",
                "k": 10, "similarity": 0.72, "nearest": "CHEMBL123456", "assay": "CHEMBL_ASSAY_99"},
  "structure": {"tier": "A", "source": "PDB", "id": "1CX2", "resolution": 2.1,
                "ligand": "SCN", "mean_plddt_in_pocket": null},
  "dock":      {"engine": "vina", "version": "1.2.5", "seed": 42, "exhaustiveness": 8,
                "box": [x, y, z, sx, sy, sz]},
  "config":    {"scoring": "0.1.0", "snapshots": {"imppat": "2022-06-17", "chembl": "ChEMBL_37"}}
}
```

Rule enforcement: a pytest guard walks every API schema field and fails if a numeric output field is
not accompanied by a provenance key. Sounds fussy; it is the only way this survives deadline pressure.

---

## 7. API surface

FastAPI. `/v1` prefix, no auth in v0.1.

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/formulations` | create; returns resolved plants or candidate lists |
| GET | `/v1/formulations/{id}` | current state |
| POST | `/v1/runs` | `{formulation_id, condition, params}` → 202 `{run_id}` |
| GET | `/v1/runs/{id}` | `{status, stage, progress, error}` |
| GET | `/v1/runs/{id}/shortlist` | ranked rows + provenance |
| GET | `/v1/runs/{id}/network` | `{nodes, edges, hubs}` |
| GET | `/v1/runs/{id}/report.pdf` | PDF |
| GET | `/v1/plants?q=` | alias resolution, returns candidates + confidence |
| GET | `/v1/conditions?q=` | EFO search |
| GET | `/v1/structures/{target_id}` | chosen structure + why |
| GET | `/v1/health`, `/v1/version` | ops |

Demo mode: `POST /v1/runs` with `demo_formulation_id` returns precomputed results in < 60 s.

---

## 8. Compute & jobs

Docking is minutes-to-hours, so runs cannot be synchronous.

- **Job runner**: ARQ over Redis. Interface `JobQueue.enqueue(run_id)`.
- **Local fallback**: `ThreadPoolExecutor` runner behind the same interface, so the hackathon laptop
  needs no Redis.
- **State machine**: `queued → resolving → filtering → predicting_targets → selecting_structures →
  docking → scoring → complete | failed`. Every transition persisted so a crash is diagnosable.
- **Idempotency**: rerunning a `run_id` with an identical `config_hash` and `snapshot_ids` returns the
  stored result rather than re-docking.
- **Caching**: every external HTTP call written to `cache/{sha256(url)}.json` with the response
  headers. Demo runs with the cache warm and network off.

---

## 9. Determinism & reproducibility requirements

These are testable and must be in CI, not aspiration:

1. Same inputs + same snapshots + same config ⇒ byte-identical `shortlist.json` (ignoring timestamps).
2. All random paths seeded: RDKit embed, Vina seed, any sampling.
3. Every run pins: `config_hash`, `snapshot_ids`, `vina_version`, `rdkit_version`, `python_version`.
4. No floating-point nondeterminism tolerated at the ranking level — ties broken by InChIKey.
5. A `phytolens reproduce <run_id>` command that rebuilds a run from its pinned inputs.

---

## 10. Validation harness — the thing the README is missing

Required in v0.1, not deferred. This is the answer to "how do you know the ranking is any good?"

### Cases

| Case | Formulation | Condition | Known actives | Why chosen |
|---|---|---|---|---|
| Primary | *Boswellia serrata*, gum-resin, ethanol | inflammation | AKBA, β-boswellic acid → ALOX5, PTGS2 | Clean literature, established targets, plant-part and solvent both matter |
| Secondary | *Curcuma longa*, rhizome, ethanol | inflammation | curcumin, demethoxycurcumin → RELA, PTGS2, AKT1 | Very well annotated; also a deliberate promiscuity stress test (curcumin is a known assay-interference compound) |

Case file format (`validation/cases/boswellia_serrata.yaml`):

```yaml
case: boswellia_serrata
formulation:
  - plant: Boswellia serrata
    part: gum_resin
    solvent: ethanol
condition: inflammation
known_actives:
  - name: AKBA
    inchikey: IUVGAPWWBFXCEO-UHFFFAOYSA-N
    targets: [ALOX5, PTGS2]
    reference: "doi:10.1016/..."
  - name: beta-boswellic acid
    inchikey: "..."
    targets: [ALOX5]
    reference: "doi:10.1016/..."
metrics: [recall_at_10, recall_at_25, mrr, mean_rank_of_known_actives]
```

### Protocol (fixes the circularity problem in the README)

1. **Run untuned.** Publish `recall@10`, `recall@25`, MRR from the default weights. **This is the
   headline number.**
2. **Only then** may weights be tuned, and only on a case held out from the headline.
3. Report every case attempted, including misses and cases where no active landed in the top 25.
4. Store results as `validation/results/{case}__{config_hash}.json`.

A modest honest number ("2 of 4 known actives in the top 25") is worth more than a tuned number a
cheminformatician can dismantle on stage.

---

## 11. Repo layout & dependencies

Proposed: build at `engine/` in this repo, so the reel pipeline and the product do not collide.
Split into its own repo before any external sharing.

```
engine/
  pyproject.toml
  src/phytolens/
    api/            routers, schemas, deps
    pipeline/       s01_ingest … s12_report, each pure + versioned
    sources/        CompoundSource protocol; imppat.py; coconut.py
    targets/        chembl_knn.py, open_targets.py
    structures/     pdb.py, alphafold.py, pocket.py
    docking/        vina.py, box.py
    scoring.py
    provenance.py
    config.py       pydantic-settings, yaml-backed
    cli.py
  config/           extraction.yaml, structures.yaml, scoring.yaml
  data/snapshots/   versioned, checksummed, gitignored
  data/precomputed/
  validation/
  tests/
```

Dependencies (licence-checked):

`fastapi`, `uvicorn`, `pydantic` v2, `pydantic-settings`, `sqlalchemy`, `alembic`, `httpx`,
`numpy`, `pandas`, `scipy`, `rdkit` (BSD-3), `networkx` (BSD-3), `pyyaml`, `weasyprint` (BSD) or
`reportlab` (BSD), `arq` (MIT), `pytest`, `pytest-cov`, `ruff`.

External binaries: `vina` (Apache 2.0). **Not** Open Babel (GPL) in the runtime path.
**Verify before ship**: `meeko`, `p2rank`. Ship pre-prepared receptor PDBQTs so neither is needed at
runtime.

---

## 12. Build order

| Wave | Deliverable | Exit criterion | Est. |
|---|---|---|---|
| W0 | Data lock: IMPPAT ingest, ChEMBL kNN reference build, Open Targets condition map, structure index, precomputed receptor PDBQTs, `docs/DATA.md` | Every snapshot hashed, licensed, and loadable | 1.5 d |
| W1 | Pipeline S1–S11 as pure functions + CLI + unit tests, no API | `phytolens run --case boswellia_serrata` produces a shortlist | 2.5 d |
| W2 | FastAPI + job queue + SQLite persistence + demo mode | `POST /v1/runs` → poll → shortlist over HTTP | 1.5 d |
| W3 | Validation harness + both cases run untuned + results committed | `validation/results/*.json` exist and are quoted in the README | 1 d |
| W4 | PDF report, provenance appendix, offline rehearsal, CI determinism test | Demo runs cold with network off, twice, identical output | 1 d |

W3 is the one that must not slip. If time runs out, cut the PDF (W4) and keep validation.

---

## 13. Decisions needed from you

1. **Demo-only or product-first?** Determines whether we skip auth and hosting entirely (recommended
   for the pitch) or build toward pilots.
2. **Where does `engine/` live** — this repo, or a fresh repo now? Mixing a judge-facing repo with
   media assets is how the current README/reality mismatch happened.
3. **IMPPAT**: do we pursue a commercial licence, or plan to rebuild the plant→compound layer? Affects
   whether the licence abstraction is a stub or a real second implementation.
4. **COCONUT**: its paper says CC BY 4.0, its listing says academic-only. Do you want me to resolve
   this in writing before we touch it, or avoid it entirely?
5. **Does the "application layer built during the event" code exist anywhere?** Nothing in this
   directory supports that README claim, and if it does exist I should read it before writing S1–S11.
