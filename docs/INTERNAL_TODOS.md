# Internal TODO — Completed Resolution Log

Every open item tracked during development has been resolved and verified.

## Data and licensing

- [x] **Decide the commercial path for the plant → compound layer:** Locked to
      rebuild on permissive sources (`LOTUS` CC0 + `ChEMBL` CC BY-SA 3.0) behind
      `engine/build_corpus.py` before any commercial pilot (`DATA_LICENSE.md`).
- [x] **Remove `engine/data/phytolens.db` from git history (`git filter-repo`):**
      Purged from all commits and added to `.gitignore` while keeping the local
      54.5 MB database on disk for the demo.
- [x] **Commercial boundary for derived evaluation JSONs:** Documented in
      `DATA_LICENSE.md` (`curcuma_candidates.json`, `dock_scores*.json`,
      `validation/results/*.json` are retained only for academic/hackathon
      review and regenerated via `engine/scripts/run_panel.py` +
      `python -m engine.validation --all` once a permissive corpus is loaded).
- [x] **Decide how to verify/ship the corpus for reviewers:** `phytolens.db` is
      rebuilt locally via `python engine/build_corpus.py` and verified with
      `python engine/build_corpus.py --verify` (`sha256:
      4f7dd8e74f011c0c762aad92ea4c2082b85afe8ac97b42ad640b56032d51f40e`).
- [x] **Add a `DATA_LICENSE` reference to every report PDF footer:** Added to
      both the per-page footer (`Data terms: DATA_LICENSE.md`) and the
      Provenance Appendix in `engine/report.py`, pinned by
      `engine/tests/test_report.py`.

## Science

- [x] **Add a fourth target (`TNF`, PDB `2AZ5`):** Prepared experimental
      co-crystal structure `2AZ5` (human TNF-α dimer with small-molecule
      inhibitor `307`, `2.10 Å`, `20 Å` centroid box) in
      `engine/data/docking/receptors/2AZ5*`, registered in `dk.TARGETS["TNF"]`,
      cached Vina runs for *Curcuma* top actives, and pinned by
      `engine/tests/test_docking.py`.
- [x] **Audit COX-2 (`3NT1`) heme retention:** Verified that `3NT1_clean.pdb`
      (`86` `HETATM ... HEM` records) and `3NT1.pdbqt` (`143` `UNL` cofactor
      atoms including `Fe`) retain the peroxidase heme at `(-26.335, -39.314,
      -17.704)` — `32.53 Å` away from the cyclooxygenase (`NPS`) binding pocket,
      outside the `20 Å` box. Set `keep_het=("HEM",)` on `PTGS2` and pinned with
      `test_ptgs2_retains_heme_cofactor_in_peroxidase_site`.
- [x] **Confirm `Fe²⁺` in `3V99` (`ALOX5`) is typed and contacted by poses:**
      Verified that `FE2 A 701` at `(12.218, -79.285, -29.738)` is typed `Fe` in
      `3V99.pdbqt` (`7.47 Å` from the `3V99` box centre, well inside the `20 Å`
      box) and that cached `3V99` poses coordinate directly to it
      (`beta-Boswellic acid` at `1.99 Å`, `AKBA` at `2.35 Å`). Pinned by
      `test_alox5_retains_catalytic_fe2_inside_box_and_poses_contact_it`.
- [x] **Prospective / collaborator validation protocol:** Authored the
      pre-registered 8-point IC50 biochemical assay + Triton X-100 / GSH
      counter-screen hand-off protocol in
      `engine/validation/wetlab_protocol.md`.
- [x] **ADMET / toxicity & structural alert prediction:** Implemented
      deterministic RDKit ADMET (`QED`, `BOILED-Egg` GI absorption & BBB
      permeation, `PAINS` A/B/C, and `Brenk` structural toxicity/reactivity
      alerts) in `engine/pipeline/admet.py`, surfaced on every ranked compound
      in the API and Next.js workbench, and pinned by
      `engine/tests/test_admet.py`.
- [x] **Literature-support tag on every compound-target link:** Every gene in
      `overlap.genes` and `/v1/runs/{id}/network` now carries `support:
      "measured" | "predicted"` and `sources: ["BindingDB", "ChEMBL", ...]`,
      rendered on the workbench gene chips and pinned by
      `engine/tests/test_ranking.py`.

## Demo and ops

- [x] **Backup demo video and report stored outside the repo:** Copied
      `phytolens_pitch_reel.mp4`, `demo_shortlist.pdf`, `phytolens.db`, and
      `phytolens-all.bundle` to `C:\Projects\photolens_pre-rewrite_2026-11-18\`.
- [x] **Public demo URL strategy:** Locked to tunnelling port `3000` (`ngrok` or
      `cloudflared`) at pitch time via the Next.js same-origin `/v1` proxy
      (`docs/DEMO_RUNBOOK.md`).
- [x] **Redis / SQLite deployment config:** `PHYTOLENS_REDIS_URL` (`rediss://`
      for Upstash) and `PHYTOLENS_RUNS_DB` environment variables wired and
      tested (`engine/jobs.py`, `engine/api.py`).
- [x] **Add screenshots to the README (`docs/images/`):** `shortlist.png`,
      `validation.png`, and `report.png` embedded in `README.md`.

## Repo hygiene

- [x] **Remove the 0-byte `t1.pdbqt`, `t2.pdbqt`, `t3.pdbqt` receptor stubs.**
- [x] **Content-addressed cache policy:** Kept the ~375 `.json`/`.pdbqt` cache
      files in `engine/data/docking/cache/` (~3 MiB packed) so the 51×3 panel,
      `TNF` (`2AZ5`), and the warm `ALOX5` stage demo are 100% reproducible.
- [x] **Add a tag/release for the hackathon submission:** Tagged
      `v0.1.0-hackathon` and pushed to `origin`.
