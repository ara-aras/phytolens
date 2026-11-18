# Demo runbook

Everything needed to run PhytoLens on stage, in order, with the failure modes we
have actually hit. Verified on 2026-11-18 against the committed code.

> Research use only. Say this out loud at least once: the output is a hypothesis
> for laboratory validation, not evidence that anything works.

---

## 1. Start order

Redis first (so the API reports the real queue), then the worker, then the API,
then the web app. Each step has a check; do not skip to the next one if a check
fails.

```bash
# 1. queue (optional, but the header pill reads "queue redis" when it is up)
redis-server --port 6379 --save "" --appendonly no

# 2. worker (separate shell, from the repo root)
python -m engine.worker

# 3. API
uvicorn engine.api:app --host 127.0.0.1 --port 8000

# 4. web
cd web && npm run dev
```

Checks:

```bash
curl -s http://127.0.0.1:8000/v1/health
curl -s -o NUL -w "%{http_code}\n" http://127.0.0.1:3000/
```

`/v1/health` must say `"status": "ok"`, and `queue.backend` must be `redis` with
`worker_alive: true`. If it says `inline`, the demo still works — runs just
execute inside the API process. The header pill shows which one you are on.

Ports: engine **8000**, workbench **3000**. The browser only ever talks to 3000;
Next proxies `/v1` to `PHYTOLENS_API_ORIGIN` (default `http://127.0.0.1:8000`).

## 2. Warm the live-dock cache (do this before the pitch)

Live docking is a *real* Vina run. Cold, two compounds on one target takes about
20–50 s depending on ligand size; a second run on the same target returns from
the content-addressed cache in about half a second. Warm it first so the stage
click is instant, and keep the cold timing for the honest answer if asked.

```bash
# the demo shortlist, then the top two compounds against ALOX5
curl -s -X POST http://127.0.0.1:8000/v1/runs \
  -H "content-type: application/json" \
  -d '{"plant":"Curcuma longa","part":"rhizome","solvent":"ethanol","condition":"colitis","top":12}'

curl -s -X POST http://127.0.0.1:8000/v1/runs/<run_id>/dock \
  -H "content-type: application/json" \
  -d '{"targets":["ALOX5"],"candidates":2}'
```

The dock response reports `fresh` and `reused`. After warm-up a UI click should
show `0 fresh Vina runs … 2 cache hits`. That is the honest demo: it says which
it was.

## 3. The click-through (about 3 minutes)

1. **Open** `http://127.0.0.1:3000`. The header pill reads `engine 0.1.0 · queue redis`.
2. **Load the demo formulation** → *Curcuma longa*, rhizome, 70% ethanol, colitis.
   Watch the funnel: 168 in the part → 168 pass extraction → 24 reach a colitis
   target → 24/24 docked.
3. **Read the top four**: bisdemethoxycurcumin, curcumin, cholesterol,
   demethoxycurcumin. Say why cholesterol is there (real score, not a drug
   candidate, left in and disclosed).
4. **Click the top compound name** to expand its evidence row: the condition
   targets it reaches (filled chips = measured links), and the term-by-term score
   with the docking bar. This is the "explainable" claim, shown rather than
   asserted.
5. **Live-dock top 2 · ALOX5**. On a warm cache it returns at once and the notice
   names the fresh/reused split. Cold, the button counts seconds — leave it, the
   proxy timeout is 180 s and the engine is working.
6. **PDF report** opens the generated PDF in a tab. Page 2 is the limitations
   page and the provenance appendix; it is not optional output.
7. **Show validation results** → 10/10 actives, mean MRR 0.414 vs 0.197 without
   docking, corpus bias 24%, and the two cases whose p-values are not
   significant. Do not skip the misses; they are the reason to trust the rest.

## 4. The live-docking story (if asked "is this precomputed?")

The panel is precomputed for 51 compounds × 3 targets so the demo is fast. Live
docking is a separate, on-demand path: pick a formulation that was never scored,
then dock its top two.

*Azadirachta indica* leaf or *Zingiber officinale* rhizome
are good choices — partly covered by the panel, so the table visibly gains
scores and the "partial docking coverage" warning updates as runs land.

## 5. Tunnels

```bash
npx ngrok http 3000
# or
cloudflared tunnel --url http://localhost:3000
```

Tunnel the **web** port, never 8000: the page and its `/v1` calls then share one
origin, which is what avoids Chrome's Private Network Access block and a
per-restart CORS allowlist. `next.config.ts` already allows ngrok and
trycloudflare hostnames for dev assets.

## 6. Fallbacks

| Symptom | Cause | Do this |
|---|---|---|
| Header says `queue inline` | Redis or worker down | Keep going; runs execute in-process. Mention it if asked. |
| `Live-dock` fails fast with a 500 | Proxy gave up, or `vina`/`obabel` missing | Check `curl /v1/health` → `vina`. Skip the live dock and use the precomputed panel; the PDF and validation still carry the demo. |
| `Live-dock` sits at `Docking… 40s` | Cold cache, large ligand | Wait. The proxy allows 180 s. |
| Page renders blank behind a tunnel | Dev assets blocked | Confirm the tunnel host matches `allowedDevOrigins` in `web/next.config.ts`. |
| Everything is slow | 57 MB SQLite on a cold disk | Run the demo once before the pitch; the OS caches it. |
| Need the numbers with no UI | — | `curl -s http://127.0.0.1:8000/v1/demo` returns the full demo shortlist. |

## 7. Reset between runs

Runs are stateless for the demo: just reload the page and press
**Load the demo formulation** again. Runtime state lives in `engine/data/runs.db`
(git-ignored); deleting it while the API is stopped clears past runs without
touching the corpus or the docking cache.

## 8. If the network dies

The deck and the PDF are the fallback. Every claim in the pitch has a number in
`docs/STATUS.md`, and `docs/images/` has the three screenshots used in the README:
`shortlist.png`, `validation.png`, `report.png`.
