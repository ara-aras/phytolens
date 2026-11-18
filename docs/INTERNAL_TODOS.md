# Internal TODO — not part of the public README

Open items kept out of the pitch surface so the README does not ship with
placeholders. Nothing here blocks the hackathon demo.

## Data and licensing

- [ ] Decide the commercial path for the plant → compound layer: commercial
      IMPPAT licence, or rebuild on a permissive source (ChEMBL, CMAUP, FooDB).
- [x] Remove `engine/data/phytolens.db` from **git history** (`git filter-repo`)
      and `.gitignore` it while keeping the local database on disk for the demo.
- [ ] Before any commercial distribution, replace or commercially license the
      small IMPPAT-derived evaluation JSONs as well.
- [ ] Decide how to ship the 57 MB corpus for reviewers: current in-repo file,
      Git LFS, or a release asset with a checksum.
- [ ] Add a `DATA_LICENSE` link to every report PDF footer (currently the PDF
      cites the caveats, not the data terms).

## Science

- [ ] Add a fourth target (e.g. TNF or IL6) and re-run the panel + validation.
- [ ] Fix the COX-2 heme loss: prepare the receptor with a tool that preserves
      HETATM (Meeko/ADFR) and re-baseline §8 in `docs/DEMO_PLAN.md`.
- [ ] Confirm whether Fe²⁺ in 3V99 is typed correctly by Open Babel (present in
      the PDBQT, but not yet checked against a docking pose that uses it).
- [ ] Prospective or collaborator-run validation.
- [ ] ADMET / toxicity prediction.
- [ ] Literature-support tag on every compound-target link.

## Demo and ops

- [ ] Record a backup demo video and store it outside the repo.
- [ ] Decide whether to expose a public demo URL (ngrok/Cloudflare at pitch
      time, or a hosted deployment).
- [ ] If hosted: Upstash Redis (`rediss://`) + a persistent volume for SQLite.
- [x] Add screenshots to the README once the workbench is final (`docs/images/`).

## Repo hygiene

- [x] Remove the 0-byte `t1.pdbqt`, `t2.pdbqt`, `t3.pdbqt` receptor stubs.
- [ ] Decide whether the ~370 content-addressed cache files belong in git
      (currently committed: they make the panel and the warmed demo reproducible).
- [ ] Add a tag/release for the hackathon submission.
