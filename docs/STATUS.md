# PhytoLens — project status

*Last updated: 2026-11-17. Every number below was produced by the code in this repo; commands to
reproduce are in the last section.*

## What this is

PhytoLens is an evidence engine for herbal and AYUSH formulations. You give it a plant, the plant
part a preparation uses, the extraction solvent and a condition; it returns a ranked, explainable
shortlist of compounds to test first, with docking scores and the evidence behind every
compound–target link.

It is an **in-silico research tool**. Outputs are hypotheses for laboratory validation — not
evidence that a product works, not a diagnosis, not a health claim.

## Where the project stands

| Area | State |
|---|---|
| Corpus | 4,154 plants · 18,314 compounds · 195,862 plant-part links · 38,842 compound-target links (IMPPAT 2.0) |
| Extraction + drug-likeness | Config-driven, Boswellia regression pinned by tests |
| Condition target sets | Open Targets: colitis (66 targets), IBD (82) |
| Ranking | Gate on condition overlap, capped overlap term, evidence quality, specificity, promiscuity penalty, docking as the primary term |
| Docking | AutoDock Vina 1.2.7, three experimental co-crystal targets: COX-2 (3NT1), 5-LOX (3V99), p38-α (3D83), content-addressed cache |
| Docking panel | 51 compounds × 3 targets — every candidate of every validation case |
| API | FastAPI, 15 `/v1` endpoints, async runs, PDF reports, network graph, live docking |
| Queue | Redis (`BRPOPLPUSH`, crash recovery), in-process fallback, standalone worker |
| Frontend | Next.js 15 workbench (replaced the planned Streamlit shell) |
| Rate limits | Per-endpoint, Redis-shared, `Retry-After` + `X-RateLimit-*` |
| Auth | Optional bearer API keys (client identity for quotas/audit, not user accounts) |
| Validation | 4 cases, untuned, with ablation, permutation null and bias-residue controls |
| Tests | 100 passing (`python -m pytest -q`) |
| CI | GitHub Actions: tests, validation run, queue smoke test, Next.js build — no Docker |

## Headline results

### Demo shortlist — *Curcuma longa* rhizome, 70% ethanol → colitis

Funnel: 168 compounds in the part → 168 pass the solvent window → 24 reach a colitis target →
24/24 docked against three targets.

Ranking: **bisdemethoxycurcumin #1, curcumin #2, cholesterol #3, demethoxycurcumin #4**, eugenol
#11. The three curcuminoids are exactly what the clinical literature identifies as turmeric's
anti-inflammatory actives — an external check, not our own intuition. Cholesterol is a membrane
sterol and is deliberately **left in and disclosed** rather than quietly filtered.

### Retrospective validation (untuned defaults, all cases reported)

| Case | Actives found | MRR | MRR without docking | Δ | Random-order MRR | p |
|---|---|---|---|---|---|---|
| *Boswellia serrata* exudate → IBD | 4 / 4 | 0.473 | 0.265 | +0.208 | 0.221 | 0.008 |
| *Curcuma longa* rhizome → colitis | 3 / 3 | 0.583 | 0.236 | +0.347 | 0.155 | 0.001 |
| *Piper nigrum* fruit → IBD | 1 / 1 | 0.333 | 0.077 | +0.256 | 0.196 | 0.173 |
| *Withania somnifera* root → IBD | 2 / 2 | 0.267 | 0.208 | +0.058 | 0.402 | 0.738 |
| **Aggregate** | **10 / 10** | **0.414** | **0.197** | **+0.217** | — | — |

What this says, without spin: docking improves the ordering in three of four cases and hurts in
none, but only the two well-covered cases separate from chance. Piper has one active among 19
candidates and Withania two among six, where random orderings score well by construction.
Withania is included as a control and it does not flatter the pipeline — nicotine still outranks
the withanolides before docking.

### The corpus-bias result that motivates the product

Annotation-based ranking (counting targets) is a measure of how much a compound has been studied.
Measured across the corpus: **2,034 of 8,510 plant-part groups with ≥3 candidates (23.9%) are
topped by one of six ubiquitous compounds** — eugenol, geraniol, cinnamaldehyde, quercetin,
eucalyptol, safrole. That is why target count is a gate, never a score, and why docking carries
the ranking.

An earlier draft claimed 44% (1,647 / 3,710). That figure could not be reproduced under any
stated definition and has been withdrawn; the docs say so explicitly.

### Live docking (real Vina, on demand)

`POST /v1/runs/{id}/dock` docks up to six compounds against two targets with the same receptors,
box and seed as the panel, then merges and re-ranks. Recorded sample
(`engine/data/live_dock_sample.json`, Zingiber officinale rhizome → COX-2, exhaustiveness 4):

- Shogaol −6.34 kcal/mol in 5.1 s, Gingerol −6.45 kcal/mol in 6.6 s (both fresh cache entries)
- Coverage 12/21 → 14/21 candidates
- Neither compound displaced the annotation leaders — the expected outcome for two mid-size
  ligands on one target, and the reason the precomputed panel exists

## What was built in this session

1. **Audited what an "opencode" agent had left behind** (its session ended on a usage-limit
   error): docs plus extraction/ranking/docking stages, no API, no UI, no PDF, no queue.
2. **Finished the backend**: three-target docking panel, validation harness, PDF report, FastAPI
   with asynchronous runs and SQLite state.
3. **Replaced Streamlit with Next.js** (`web/`): formulation builder, funnel, shortlist with
   per-target affinities, expandable evidence drawer, hub targets, caveats, PDF link, live-dock
   button, validation panel.
4. **Redis job queue** with a durable handoff, crash recovery, a standalone worker and a
   no-Redis fallback. Local Redis today; `PHYTOLENS_REDIS_URL=rediss://…` for Upstash later.
5. **Rate limits and optional API keys** — quota identity for a metered API, not user accounts.
6. **Live docking** endpoint and CLI, with the sample artefact above.
7. **Validation work**: two more cases, ablation (with/without docking), permutation null with
   p-values, bias-residue control, and a panel rebuilt so no case is scored on uncovered
   candidates.
8. **CI** without Docker: real Redis from apt, tests, validation run, queue smoke test, web build.

## Architecture

```
Next.js workbench (:3000)
        │  REST + CORS
        ▼
FastAPI (:8000) ── rate limits (Redis) ── optional bearer auth
        │
        ├── SQLite: runs, formulations, run owner
        └── Redis queue ──► engine.worker ──► ranking pipeline ──► shortlist / PDF
                                  │
                                  └── Vina (panel or live) + content-addressed cache
```

Docking needs `vina` (and `obabel` to prepare ligands/receptors). Everything else runs from
Python plus the corpus database.

## API surface

`GET /v1/health`, `GET /v1/version`, `GET /v1/plants?q=`, `GET /v1/plants/{id}/parts`,
`GET /v1/conditions`, `POST /v1/formulations`, `GET /v1/formulations/{id}`, `POST /v1/runs`,
`GET /v1/runs/{id}`, `GET /v1/runs/{id}/shortlist`, `GET /v1/runs/{id}/network`,
`GET /v1/runs/{id}/report.pdf`, `POST /v1/runs/{id}/dock`, `GET /v1/validation`,
`GET /v1/structures/{target}`, `GET /v1/demo`.

## How to run

```bash
python -m pip install -r requirements.txt

# optional but recommended: real queue + shared rate limits
redis-server --port 6379 --save "" --appendonly no
python -m engine.worker            # second shell

uvicorn engine.api:app --host 127.0.0.1 --port 8000
cd web && npm install && npm run dev     # http://127.0.0.1:3000
```

Without Redis — or with Redis up but no worker — the API runs jobs in a thread pool and says so
(`queue: "inline"`), so a demo never hangs on a missing worker.

**Sharing through a tunnel (ngrok/Cloudflare).** Open the tunnel URL, not the API URL: the
browser calls `/v1` on its own origin and Next proxies it to `http://127.0.0.1:8000`. Calling the
API directly from a tunneled page is blocked by Chrome's Private Network Access check. Also note
tunnel hostnames change per restart; CORS and `allowedDevOrigins` already cover the common
providers. A free ngrok tunnel shows a one-time "Visit Site" interstitial.

**Port in use / stale frontend.** `netstat -ano | grep ":3000 .*LISTEN"` then
`taskkill //PID <pid> //T //F`, and start `npm run dev` again — Next only picks up
`next.config.ts` changes (proxy, allowed origins) on a restart.

```bash
python -m pytest -q                                  # 100 tests
python -m engine.validation --all                    # untuned validation, writes results
python -m engine.live_dock --plant "Zingiber officinale" --part rhizome \
  --condition colitis --targets PTGS2 --compound Gingerol --compound Shogaol
```

## Checks and what they cover

- `python -m pytest -q` → **100 passed**: extraction regressions, ranking, docking cache/targets,
  validation metrics and controls, PDF, API lifecycle, Redis queue handoff/recovery/fallback,
  rate-limit 429 path, API-key 401/403, live-dock merge.
- `npm run build` in `web/` → compiled, types valid.
- End-to-end over HTTP: run created → Redis → worker → `complete`; live dock returned 2 fresh
  Vina scores and re-ranked the stored run.
- Browser: demo formulation rendered the full shortlist; validation panel rendered all four cases.

## Limitations we state out loud

- **No prospective validation.** Agreement with known actives tests the ranking; it does not show
  a compound works.
- **Three targets, not the proteome.** A compound binding none of them may act elsewhere.
- **Heme is missing from the COX-2 receptor** (Open Babel drops HETATM when writing PDBQT). At the
  shipped 20 Å box this no longer lets large lipophilic ligands win; larger ligands may still be
  favoured, which is why ligand efficiency sits beside every affinity.
- **Cholesterol ranks #3 on the demo panel.** Real score, not a drug candidate, disclosed.
- **Annotation bias is reduced, not eliminated.** Geraniol still appears in the Boswellia top 10.
- **Small validation cases are underpowered.** p-values are reported, including the two that are
  not significant.
- **Licensing.** The corpus derives from IMPPAT 2.0 (CC BY-NC-ND 4.0, academic/non-commercial, no
  derivatives). Public sharing of this repo is for the hackathon/academic context; commercial use
  needs a licence or a rebuilt plant→compound layer.
- **Not built**: user accounts, multi-tenancy, ADMET/toxicity prediction, GPU docking in the
  served path (Uni-Dock is installed and validated for later).
