# Data licence and provenance

The **Apache License 2.0** in `LICENSE` covers the source code in this
repository. It does **not** grant rights to the bundled data.

## Bundled corpus: IMPPAT 2.0 — non-commercial, no derivatives

`engine/data/phytolens.db` and the JSON artefacts generated from it
(`curcuma_candidates.json`, `dock_scores*.json`, validation outputs) are derived
from **IMPPAT 2.0** (Indian Medicinal Plants, Phytochemistry And Therapeutics),
https://cb.imsc.res.in/imppat/.

IMPPAT 2.0 is distributed under **CC BY-NC-ND 4.0**:

- **NC** — non-commercial use only.
- **ND** — no derivatives. A rebuilt or reshaped database is a derivative.

We include the built corpus **only so the hackathon demo is reproducible**. We
do not grant permission to redistribute it, publish it, or use it commercially.
If you want to use PhytoLens for anything other than reviewing this hackathon
build, delete the bundled database and rebuild the corpus from a source you are
licensed to use:

```bash
rm engine/data/phytolens.db
# obtain IMPPAT under terms you accept, then:
python engine/build_corpus.py
```

Commercial use requires either a commercial IMPPAT licence or replacing the
plant -> plant-part -> compound layer with a permissively licensed source.

## Other sources used by the pipeline

| Source | Used for | Licence | Notes |
|---|---|---|---|
| IMPPAT 2.0 | Plant, plant-part, compound and curated compound-target links | CC BY-NC-ND 4.0 | Academic/non-commercial, no derivatives. See above. |
| Open Targets Platform | Condition target sets (colitis, IBD) | CC0 1.0 | Public domain dedication; safe to redistribute. |
| RCSB PDB | Experimental protein structures (3NT1, 3V99, 3D83) | Public domain (CC0) | Structures are freely usable. |
| AlphaFold DB | Not used in this build | CC BY 4.0 | The AlphaFold path is planned, not implemented. |

## Runtime tools (not vendored)

| Tool | Licence | How it is used |
|---|---|---|
| AutoDock Vina 1.2.7 | Apache-2.0 | Separate executable, invoked by subprocess. |
| Open Babel 3.1.1 | GPL-2.0 | Separate executable, invoked by subprocess for PDBQT conversion. Not distributed with this repo. |
| RDKit | BSD-3-Clause | Python dependency. |
| FastAPI / Uvicorn / Pydantic | MIT / BSD / MIT | Python dependencies. |
| ReportLab | BSD-3-Clause | PDF generation. |
| Redis | RSALv2 / SSPLv1 (server) | Optional queue and rate-limit backend; not distributed. |
| Next.js / React | MIT | Workbench. |
| Uni-Dock 1.2.0 | Apache-2.0 | Optional WSL2 GPU path, validated but not used in the served demo. |
| Meeko | LGPL-2.1 | Installed but **not imported**; ligand prep uses RDKit plus the Open Babel binary. |

## What this means for the public repo

This repository is public for the hackathon and academic review context. That
does **not** make the bundled IMPPAT-derived database open source. If the
repository is used beyond that context, remove the corpus first and rebuild it
from a licensed source.
