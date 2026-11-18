# Hackathon plan — data-driven corrections (v2)

**v1 of this document claimed curcumin ranked #1 on inflammatory overlap. That claim is
withdrawn.** It was measured against a 20-gene inflammation list I wrote by hand — which is
circular: I chose the genes, then declared the result a validation. Re-measured against a
citable Open Targets target set, curcumin ranks 5th–8th before docking. See Finding 3.

Everything below is measured against `engine/data/phytolens.db` (18,314 compounds, 195,862
plant-part links, 38,842 compound-target links) and Open Targets disease target sets cached in
`engine/data/targets/`. Nothing here is estimated.

---

## 1. What the data says

### Finding 1 — The extraction filter as specified deletes the active ingredients

Boswellia serrata gum-resin exudate, ethanol extraction:

| Compound | MW | logP | survives `−0.5..5.0`? |
|---|---|---|---|
| β-boswellic acid | 456.7 | 7.09 | ✗ |
| 11-keto-β-boswellic acid | 470.7 | 6.27 | ✗ |
| 3-acetyl-11-keto-β-boswellic acid | 512.7 | 6.84 | ✗ |

All five boswellic acids fall outside the planned ethanol window. The filter keeps 36 of 47
compounds and every survivor is a volatile monoterpene. Triterpenoid acids really are that
hydrophobic, and ethanolic Soxhlet of the gum resin is how they are obtained in practice. The
heuristic was wrong about the chemistry.

**Corrected and shipped** in `engine/config/extraction.yaml`:
- ethanol window widened to `−1.0 ≤ logP ≤ 8.5`, with the triterpenoid reasoning recorded inline
- MW ceiling 700 (3,281 corpus compounds exceed 500; 1,242 exceed 700)
- drug-likeness is **flags only, never a drop**

Pinned by `engine/tests/test_extraction.py`: all five boswellic acids must survive, and a test
asserts the old narrow window *would* have deleted them, so it cannot be quietly restored.

### Finding 2 — Target-count ranking measures how much a compound has been studied

Boswellia exudate, ranked by number of annotated targets (measured = backed by ChEMBL or
BindingDB, whatever else is listed):

| Rank | Compound | Targets | Measured | logP |
|---|---|---|---|---|
| 1 | **Geraniol** | 99 | 95 | 2.67 |
| 2 | Estragole | 11 | 1 | 2.42 |
| 3 | β-boswellic acid | 11 | 8 | 7.09 |
| 4 | 11-keto-β-boswellic acid | 10 | 10 | 6.27 |

Geraniol wins by a factor of nine. It is a monoterpene alcohol, not the anti-inflammatory
principle of frankincense. Estragole is second on eleven links, one of which is measured.
Filtering predicted links out does not rescue this — geraniol's links are measured.

### Finding 3 — The bias is not plant-specific. It is the whole corpus.

The old claim that curcumin wins was an artefact of a hand-picked gene list. Against Open
Targets **inflammatory bowel disease** (82 targets at score ≥ 0.5, CC0), the top of *Curcuma
longa* rhizome is:

| Rank | Compound | Measured IBD targets | Measured targets overall |
|---|---|---|---|
| 1 | Eugenol | 7 | 88 |
| 2 | Geraniol | 6 | 89 |
| 3 | Eucalyptol | 6 | 88 |
| 4 | Safrole | 6 | 88 |
| 5 | **Curcumin** | 5 | 84 |

Eugenol beats curcumin at **every** threshold tested, on both colitis and IBD target sets.
So does the same volatile cohort in other plants:

| Plant / part | Annotation-ranked #1 | The plant's actual active |
|---|---|---|
| *Withania somnifera* root | **Nicotine** (6) | withaferin A (1) |
| *Piper nigrum* fruit | Eugenol (7) | piperine (9) |
| *Zingiber officinale* rhizome | Eugenol (7) | 6-gingerol (7) |
| *Azadirachta indica* leaf | Quercetin (12) | azadirachtin (absent) |

Corpus-wide, measured by `python -m engine.validation --all`: **2,034 of 8,510 plant-part
groups with ≥3 candidates (23.9%) are topped by one of six compounds** — eugenol, geraniol,
cinnamaldehyde, quercetin, eucalyptol, safrole. Groups are plant × part; the top compound is
the one with the most annotated targets. The ranking is largely telling you which compound
has the largest literature footprint.

**Correction:** an earlier draft of this document quoted 1,647 of 3,710 groups (44%). That
figure could not be reproduced from this corpus under any stated definition (all-candidates,
annotated-only, extraction-filtered and plant-level groupings give 21–32%), so it is
withdrawn. Use 23.9% with the definition above. The argument does not depend on the exact
share: one in four medicinal-plant preparations is topped by the same volatile cohort.

**Consequence for the design:** target annotation is a **gate**, not a ranking. It answers
"could this compound plausibly act on this condition?" and never "which compound should we
test first?". Docking is the only term in the pipeline that is independent of how much a
compound has been studied — which makes it the product, not a feature.

---

## 2. Demo lock

| Field | Value |
|---|---|
| Formulation | *Curcuma longa* rhizome, 70% ethanol |
| Condition | colitis (MONDO_0005292, Open Targets, 66 targets at score ≥ 0.4) |
| Chosen because | curcumin already has human trial data in ulcerative colitis, so the output can be checked against clinical literature instead of against our own intuition |
| Funnel (real) | 168 in part → 168 pass extraction → 14 flagged → 24 reach a colitis target |
| Pre-docking ordering | eugenol, bisdemethoxycurcumin, thymol, … curcumin #8 — **shown deliberately** |
| Post-docking ordering (three-target panel) | bisdemethoxycurcumin #1, curcumin #2, cholesterol #3, demethoxycurcumin #4, eugenol #11 of 24 |
| Honesty case | Boswellia serrata exudate: β-boswellic acid #1, α-boswellic acid #2, 11-keto-β #4, AKBA #7, geraniol #8 — four of four known actives in the top 10; annotation bias shrunk, not eliminated |

**The demo does not claim curcumin is #1 pre-docking, because it isn't.** The arc is:

1. Naive annotation ranking returns eugenol, geraniol, eucalyptol — the same six compounds
   that top 24% of the corpus. Show that number.
2. Explain: this is literature density, not pharmacology.
3. Rank by docking instead. Report whatever comes out, including if curcumin still loses.

If curcumin does not win on docking, that is the result and it goes on the slide. A pipeline
that reports its own negative result is the pitch.

---

## 3. Ranking design (shipped in `engine/config/ranking.yaml`)

```
gate:   survives extraction  AND  has >=1 target in the condition set
score:  w_dock   · docking_normalised     [-9..-5 kcal/mol -> 1..0]   (primary)
      + w_ovl    · overlap / 8 (capped)   condition targets reached
      + w_evid   · measured / overlap     evidence quality, not volume
      + w_spec   · overlap / all targets  precision against the whole target set
      - w_prom   · promiscuity             log-scaled measured-target count
never:  raw target count as a term
```

- Overlap is **capped at 8**. Past that, more overlap just finds the biggest literature
  footprint — the exact bias in Finding 3.
- While docking is absent the docking weight is redistributed and the result is stamped
  `docking_pending: true`. A pre-docking ordering is never presented as final.
- Every term is emitted per compound, so a judge can disagree with the weights and still read
  the evidence.

---

## 4. The pitch beat (60–90 seconds, screens not slides)

1. **The bottleneck.** 168 compounds in a turmeric rhizome. Which do you test first?
2. **The trap.** Run the standard network-pharmacology ranking. It returns eugenol. Then show
   that the same method returns the same six compounds for 24% of the corpus — and nicotine
   for ashwagandha. That is the method failing, in public.
3. **The correction.** Re-rank the 24 candidates by docking against the condition's targets.
4. **The provenance.** Click any compound → IMPPAT record, ChEMBL-measured links, PDB entry,
   Vina score, config hash. Every number carries its source.
5. **The honesty slide.** Frankincense: geraniol still ranks first. The correction lifts the
   boswellic acids from buried to #2 and #4–6, but it does not eliminate the bias — it shrinks
   it. We show both the improvement and the residue.
6. **The ask.** Licence or per-report; pilot with one export-oriented manufacturer.

Step 2 is the strongest asset. It is a measured, reproducible criticism of the incumbent
method — and it is the reason the product exists.

---

## 5. Build order

| # | Task | Status |
|---|---|---|
| 1 | Corpus (`phytolens.db`) with parts, properties, targets, provenance | ✅ done |
| 2 | Extraction + drug-likeness, config-driven, Boswellia regression pinned | ✅ done — 17 tests pass |
| 3 | Condition target sets from Open Targets, cached with per-target evidence | ✅ done — colitis 66, IBD 82 |
| 4 | Ranking v0 with all terms exposed, pre-docking | ✅ done — `python -m engine.pipeline.ranking` |
| 5 | Structure selection for hub targets: PTGS2 3NT1, ALOX5 3V99, MAPK14 3D83 | ✅ done — experimental co-crystals |
| 6 | Precompute docking, validation candidates × 3 targets | ✅ done — 35 compounds, `dock_scores_panel.json` |
| 7 | FastAPI: `/v1/demo`, `/v1/runs`, `/v1/structures`, `/v1/health`, network, PDF | ✅ done — `engine/api.py` |
| 8 | Next.js workbench: formulation builder, shortlist, evidence drawer, validation panel | ✅ done — `web/` |
| 9 | Validation numbers: recall@10/@25, MRR, corpus-bias figure | ✅ done — four cases in `engine/validation/results/` |
| 10 | PDF with caveats + provenance appendix | ✅ done — `engine/report.py` |
| 11 | Redis job queue with in-process fallback + worker process | ✅ done — `engine/jobs.py`, `engine/worker.py` |
| 12 | Rate limits and optional API-key auth | ✅ done — `engine/ratelimit.py`, `engine/auth.py` |
| 13 | Bounded live docking endpoint and a recorded sample | ✅ done — `POST /v1/runs/{id}/dock`, `engine/data/live_dock_sample.json` |
| 14 | CI: tests, validation run, queue smoke test, Next.js build | ✅ done — `.github/workflows/ci.yml` (no Docker) |
| 15 | Validation controls: ablation, permutation null, bias residue | ✅ done — §9 |

Steps 1–4 are done. Step 6 gates the entire demo: without docking there is no product claim,
only a criticism.

---

## 6. Deliberately not doing

- Bespoke target prediction (ChEMBL kNN). IMPPAT already ships curated links; a second
  predictor costs a day and buys nothing on stage.
- AlphaFold. Every demo target has a co-crystal PDB.
- Postgres and a migration framework. SQLite is the store; the one schema change since
  v0.1 (a run owner column) is applied in place.
- Managed Redis. Local Redis carries the queue now; the same `REDIS_URL` points at
  Upstash (`rediss://…`) later with no code change.
- User accounts, login sessions, billing. API keys exist to identify a client for quotas
  and audit, not to model people.
- Docker. Redis comes from the distribution in CI, the app runs from the source tree.
- Streamlit. It was replaced by the Next.js workbench in `web/`, because a shortlist that
  has to carry provenance and caveats needs real layout control.

---

## 7. Open items needing a human decision

1. **Docking budget.** No longer a constraint. The full panel (35 compounds × 3 targets)
   runs on CPU in minutes with the content-addressed cache. Uni-Dock is installed and
   validated in WSL2 (`docs/GPU_DOCKING.md`) and reproduces Vina to 0.09 kcal/mol mean, but
   the shipped numbers stay on CPU Vina so the table is one backend.
2. **IMPPAT licence.** CC BY-NC-ND 4.0 — non-commercial, no derivatives. Fine for the
   hackathon and disclosed on stage; commercial use needs a licence or a rebuild.
3. **Curcumin PAINS caveat.** Curcumin is a documented assay-interference compound. Pre-empt
   it: report docking and potency separately, and carry a promiscuity flag on every report.
4. **Cholesterol ranks #3 on the three-target panel.** It is a membrane sterol, not a
   therapeutic candidate. The score is real: it docks strongly into all three sites. It is
   left in the shortlist and disclosed rather than filtered, because a quiet sterol filter is
   the kind of hidden thumb-on-the-scale this tool exists to avoid. Decide whether the demo
   slide annotates it as a non-candidate or whether a documented sterol exclusion is added.

---

## 8. Docking results (panel: COX-2 3NT1, 5-LOX 3V99, p38-α 3D83)

Receptor: 3NT1, naproxen (NPS) stripped, waters and cryoprotectant removed, protonated at
pH 7.4. Box: 20 Å cube centred on the naproxen centroid (the coordinates are written to
`engine/data/docking/receptors/3NT1_box.json`). Vina 1.2.7, exhaustiveness 8, seed 42.

Twenty-four candidates, all cached in `engine/data/docking/cache/`, results in
`engine/data/dock_scores.json`.

| Vina rank | Compound | Affinity | Ligand efficiency | Annotation rank |
|---|---|---|---|---|
| 1 | Bisdemethoxycurcumin | −8.08 | −0.351 | 2 |
| 2 | Demethoxycurcumin | −8.08 | −0.323 | 12 |
| 3 | Cholesterol | −8.00 | −0.286 | 18 |
| 4 | Curcumin | −7.96 | −0.295 | 8 |
| 5 | Piperine | −7.88 | −0.375 | 17 |
| … | Eugenol | −5.51 | −0.460 | **1** |
| … | Geraniol | −5.55 | −0.505 | 7 |

With the three-target panel (`dock_scores_panel.json`, now 51 compounds: every candidate of
every validation case), the composite is **bisdemethoxycurcumin #1, curcumin #2, cholesterol
#3, demethoxycurcumin #4**, with eugenol at #11 and geraniol at #13 of 24. Cholesterol's
placement is driven by p38-α (−10.20 kcal/mol) and is disclosed, not hidden: it is a sterol,
not a drug candidate.

The panel was rebuilt from all four validation cases after the initial two-case export. Before
that, the Piper and Withania cases were partially or entirely undocked, which made their
docking ablation meaningless. No case is now scored on a candidate list the panel does not
cover.

### Live docking

`POST /v1/runs/{id}/dock` runs Vina on demand for up to six compounds and two targets
(exhaustiveness default 4 rather than the panel's 8, because a live run has a clock), then
merges the fresh scores and re-ranks the stored run. Every score reports `cached: true/false`,
so a live demo can say which numbers are new.

A recorded sample (`engine/data/live_dock_sample.json`, Zingiber officinale rhizome, 2
candidates × COX-2): Shogaol −6.34 kcal/mol (5.1 s), Gingerol −6.45 kcal/mol (6.6 s), both
fresh cache entries, coverage 12/21 → 14/21 candidates. Neither compound displaced the
annotation leaders, which is the expected result for two mid-sized ligands on one target and
is why the panel exists.

The Cox-2-only composite from the first pass was bisdemethoxycurcumin, curcumin,
demethoxycurcumin in the top three. Both are recorded here because the target panel changed
the ordering, and a judge may ask which one is on the slide.

The three curcuminoids are exactly what the clinical literature identifies as the
anti-inflammatory actives of turmeric. That is a check against external evidence, not
against our own intuition — which is what the earlier withdrawn claim failed to do.

### Limitations to state out loud

- **Four targets, not the whole proteome.** COX-2, 5-LOX and p38-α in the precomputed
  panel, plus on-demand TNF-α (`2AZ5`). All are experimental structures with co-crystal box
  definitions. A compound that binds none of them may still act elsewhere.
- **COX-2 heme is only partly retained.** Open Babel drops the porphyrin ring when writing
  PDBQT and leaves the heme iron atoms; the heme is ~32.5 Å from the docked cyclooxygenase
  box, so the scored site is unaffected. At a 26 Å box this inflated scores for large
  lipophilic ligands (cholesterol ranked #1); at 20 Å it does not. Larger ligands may still
  be favoured.
- **Vina's scoring function has a size bias.** Ligand efficiency is reported next to every
  affinity for that reason. Neither number alone is a rank.
- **Cholesterol ranks 3rd composite on the three-target panel.** It is a membrane sterol
  with no business being on a therapeutic shortlist. It is left in the table rather than
  filtered out, because quietly removing inconvenient hits is how these tools lose
  credibility. The slide should say so before a judge does.

---

## 9. Validation results (untuned, shipped defaults)

Generated by `python -m engine.validation --all`, written to
`engine/validation/results/{case}__{ranking_hash}.json`. Weights were not tuned on these
cases. Every case is reported, including where it would be convenient not to.

| Case | Actives found | recall@10 / @25 | MRR | Best / mean rank | MRR without docking | Δ | Random-order MRR | p |
|---|---|---|---|---|---|---|---|---|
| *Boswellia serrata* exudate → IBD | 4 / 4 | 1.00 / 1.00 | 0.473 | 1 / 3.5 | 0.265 | +0.208 | 0.221 | 0.008 |
| *Curcuma longa* rhizome → colitis | 3 / 3 | 1.00 / 1.00 | 0.583 | 1 / 2.33 | 0.236 | +0.347 | 0.155 | 0.001 |
| *Piper nigrum* fruit → IBD | 1 / 1 | 1.00 / 1.00 | 0.333 | 3 / 3.0 | 0.077 | +0.256 | 0.196 | 0.173 |
| *Withania somnifera* root → IBD | 2 / 2 | 1.00 / 1.00 | 0.267 | 3 / 4.0 | 0.208 | +0.058 | 0.402 | 0.738 |
| **Aggregate** | **10 / 10** | — | **0.414** | — | **0.197** | **+0.217** | — | — |

Columns after MRR are controls, not tuning:

- **Without docking** is the identical pipeline with the docking term removed and its weight
  renormalised. Δ is what docking contributed to MRR.
- **Random-order MRR** is the mean over 1,000 permutations of the same candidate list, and
  **p** is the one-sided share of random orderings at least as good as the observed one.
  The analytic expectation (H_N / N, scaled by actives found) is stored beside the simulation
  so the draw can be checked.

Boswellia ranks β-boswellic acid #1, α #2, 11-keto #4 and AKBA #7, with geraniol at #8.
Turmeric ranks bisdemethoxycurcumin #1, curcumin #2 and demethoxycurcumin #4. Piperine is #3
of 19, up from #13 without docking. Withania: withanolide D #3 and withaferin A #5, with
nicotine still above them in the annotation-only arm.

**Read the p-values honestly.** Docking helps in three of four cases and hurts in none, but
only the two well-covered cases are statistically separated from chance. Piper has one active
among 19 candidates and Withania two among six; random orderings score well on such small
lists by construction (Withania's random MRR, 0.402, is higher than the observed 0.267). The
honest claim is "docking improves the ordering in the cases where it has enough candidates to
act", not "the ranking is validated".

Withania is included as a control and it does not flatter the pipeline: the root extract has
six candidates, annotation puts nicotine first, and the known actives sit at 3 and 5. A case
set that only contains wins is a brochure.

The corpus-bias figure in Finding 3 is recomputed in the same run (23.9%, definition stated
there). No metric here is tuned against its own case.

What this does **not** show: these are known-actives *ranked*, not compounds shown to work.
Agreement with the literature is a check on the ranking, not a prospective validation.

---

## 10. Running the stack

```bash
# Python side
python -m pip install -r requirements.txt

# Redis (queue + rate limits). Optional: without it the API falls back to threads.
redis-server --port 6379 --save "" --appendonly no

# HTTP API (docs at http://127.0.0.1:8000/docs)
uvicorn engine.api:app --host 127.0.0.1 --port 8000

# consume the Redis queue (skip if running inline)
python -m engine.worker

# Next.js workbench (http://127.0.0.1:3000)
cd web && npm install && npm run dev
```

The browser calls `/v1` on its own origin; `web/next.config.ts` proxies it to
`PHYTOLENS_API_ORIGIN` (default `http://127.0.0.1:8000`). That is deliberate: when the demo is
opened through a tunnel (ngrok, Cloudflare), Chrome blocks a public HTTPS page from calling
`http://127.0.0.1` under Private Network Access, and CORS would have to agree with a tunnel
hostname that changes on every restart. The proxy keeps the browser same-origin and the engine
on loopback.

Direct API clients still get CORS: `PHYTOLENS_CORS_ORIGINS` (exact origins) and
`PHYTOLENS_CORS_ORIGIN_REGEX` (defaults to loopback on any port plus ngrok/trycloudflare hosts).
Next's dev server also needs `allowedDevOrigins` for a tunnel host, or it serves the HTML and
blocks every `/_next/*` asset.

```bash
# demo shortlist in one request
curl http://127.0.0.1:8000/v1/demo

# retrospective validation (untuned, with ablation + permutation null)
python -m engine.validation --all

# live docking sample (real Vina, ~10 s per ligand)
python -m engine.live_dock --plant "Zingiber officinale" --part rhizome \
  --condition colitis --targets PTGS2 --compound Gingerol --compound Shogaol

# PDF for a formulation
python -m engine.report --plant "Curcuma longa" --part rhizome \
  --condition colitis --dock engine/data/dock_scores_panel.json --out out.pdf

# tests
python -m pytest -q
```

Endpoints: `GET /v1/health`, `GET /v1/version`, `GET /v1/plants?q=`,
`GET /v1/plants/{id}/parts`, `GET /v1/conditions`, `POST /v1/formulations`,
`GET /v1/formulations/{id}`, `POST /v1/runs`, `GET /v1/runs/{id}`,
`GET /v1/runs/{id}/shortlist`, `GET /v1/runs/{id}/network`, `GET /v1/runs/{id}/report.pdf`,
`POST /v1/runs/{id}/dock`, `GET /v1/validation`, `GET /v1/structures/{target}`,
`GET /v1/demo`. Runs are asynchronous (202 + poll).

## 11. Ops: queue, limits, auth, CI

**Queue.** `POST /v1/runs` writes the run row, then pushes the job to Redis
(`phytolens:runs`). The worker moves it to `phytolens:runs:processing` with `BRPOPLPUSH`, so a
worker killed mid-job is recovered by `requeue_inflight()` on its next start. SQLite stays the
source of truth. The worker publishes a heartbeat; if Redis is down **or no worker is alive**,
the API runs the job in a local thread pool and says so (`queue: "inline"`), because a job that
sits queued forever while the UI polls is worse than a slower start. `PHYTOLENS_REDIS_URL`
accepts `rediss://`, which is all Upstash needs.

**Rate limits.** Fixed-window counters in Redis, per endpoint class: live docking 4/min, run
creation 12/min, formulations 30/min, `/v1/demo` 60/min, other reads 240/min. Counters are
shared across workers, which is the reason they live in Redis rather than in process memory.
Responses carry `X-RateLimit-Limit/Remaining/Reset/Backend`; a 429 carries `Retry-After`.
`PHYTOLENS_RATE_LIMIT_SCALE` multiplies the limits (the tests use it to prove the 429 path
without waiting a minute).

**Auth — what it is and is not.** PhytoLens has no human accounts: there is no sign-up, no
session, no per-user data, so "auth" cannot mean login. What it means here is *client
identity for a metered API*:

1. the rate limiter needs a subject that is not a shared office IP, so a customer cannot
   exhaust the quota for everyone behind the same NAT;
2. live docking spends CPU on this machine, so anonymous callers must not be able to queue it;
3. every run stores `owner` (`key_…`), which is the audit trail a report can be traced to.

It is a bearer API key (`Authorization: Bearer …`), off unless `PHYTOLENS_API_KEY` is set
(comma-separated for rotation). When set, POST endpoints return 401 without it and 403 with a
wrong key; GETs stay public so a shared report link opens. Keys are compared in constant time
and never logged — the stored owner is a hash prefix. Real user accounts would only be needed
if reports become per-customer private, and that is a hosting decision, not a pipeline one.

**CI.** `.github/workflows/ci.yml` runs on GitHub-hosted Ubuntu with no containers:
`redis-server` from apt, `pytest`, a `python -m engine.validation --all --no-write` run, a
worker smoke test, and `npm ci && npm run build` for the web app. Docker is deliberately not
used — the SQLite corpus and runs database are build inputs, not something to bake into an
image.

