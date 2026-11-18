# engine/data

Everything here is either generated or derived. Nothing in this directory is
covered by the Apache-2.0 code licence.

- `phytolens.db` — local SQLite corpus built from IMPPAT 2.0 by
  `engine/build_corpus.py` (git-ignored, not distributed in the repo).
  **IMPPAT is CC BY-NC-ND 4.0**: academic/non-commercial, no derivatives.
  See `../../DATA_LICENSE.md`.
- `curcuma_candidates.json`, `dock_scores.json`, `dock_scores_panel.json`,
  `live_dock_sample.json` — derived results. Same data terms as the corpus.
- `targets/` — Open Targets extracts (CC0).
- `docking/receptors/` — RCSB PDB structures (public domain) and prepared PDBQT files.
- `docking/cache/` — content-addressed Vina results for this corpus.
- `runs.db` — local runtime state, git-ignored.
- `raw/` — downloaded source TSVs, git-ignored.

To rebuild from scratch you need IMPPAT 2.0 under terms you accept:

```bash
python engine/build_corpus.py
python engine/fetch_targets.py --all
```
