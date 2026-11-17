# PhytoLens (working name)

**An evidence engine for herbal and AYUSH formulations.**
Enter a formulation and a condition. Get the likely targets, the key compounds, a docking-based ranking, and a shortlist of what to test in the lab first.

> Status: hackathon prototype (The Founder's Arena, PACE Mangaluru). Domain: Healthcare & Medical Solutions (Diagnose, Heal, Treat). This is an **in-silico research tool**. Outputs are hypotheses for laboratory validation, not evidence that any product works. Not a medical device. Not for clinical decisions or health claims.

**Intended use:** PhytoLens helps researchers and R&D teams prioritise which compounds and targets to test first. It does not diagnose, treat, or recommend therapy, and it does not substantiate health claims.

**One line:** it tells a lab where to look first, so fewer experiments are wasted.

---

## The problem

Traditional and herbal formulations can contain dozens of plants and hundreds of compounds. Companies that want to understand *why* a formulation might work, or need mechanistic support for R&D, export dossiers or patent filings, face a slow and expensive path:

- Wet-lab screening of every compound is costly and slow.
- Commercial docking and network-analysis software is expensive and needs trained computational staff.
- Most small and mid-size AYUSH manufacturers have neither, so promising formulations stay unexplored.

## The solution

PhytoLens turns a formulation into a ranked, explainable research shortlist:

1. **Compounds:** maps each plant (and plant part) to its reported phytochemicals.
2. **Extraction-aware filter:** adjusts the compound list by plant part and by extraction solvent type, using a simple polarity heuristic.
3. **Drug-likeness filter:** screens compounds on basic properties so the list is workable.
4. **Targets:** predicts likely protein targets for each compound.
5. **Network pharmacology:** overlaps compound targets with disease-related targets, builds a compound-target-disease network, and finds hub targets.
6. **Structures:** for each hub target, picks the best available protein structure (experimental if one exists, otherwise a predicted AlphaFold model) and records which was used.
7. **Docking:** ranks the top compounds against the hub targets with AutoDock Vina; results on predicted structures are flagged as lower confidence.
8. **Report:** a one-click PDF with the network, the docking ranking, the caveats, and a suggested first set of lab tests.

## Domain fit: Diagnose, Heal, Treat

- **Heal and Treat (research stage):** helps find which compounds and targets may explain a formulation's reported effect, as a route to better candidates and better-designed experiments.
- **Diagnose:** not a diagnostic tool. We do not claim to diagnose.

## Who it is for

- **Primary buyer:** R&D or regulatory-affairs lead at an export-oriented AYUSH or nutraceutical brand, or at a contract manufacturer, who needs mechanistic support for a formulation (R&D direction, export dossiers, patent filings).
- **Secondary:** research groups in pharmacy, biotech and ayurveda colleges. Useful as early users and for validation, but slow to buy.
- **Not our customer (yet):** large pharma with in-house discovery platforms.

*Context (sourced):* India's AYUSH and herbal exports were US$688.89 million in 2024-25, up 6.11% from the previous year (Ministry of Commerce, January 2026). This shows the size of the sector, not demand for our product, which is untested.

## Features

| Feature | What it does |
|---|---|
| Formulation input | List of plants (with plant part and extraction solvent type) and optionally a condition |
| Compound lookup | Plant and plant-part to phytochemical mapping from public databases |
| Extraction-aware filter | Heuristic filter using compound polarity (logP) against the chosen solvent type; labelled as a simplification |
| Drug-likeness filter | Property-based filtering with RDKit |
| Target prediction | Likely targets per compound |
| Network view | Compound-target-disease network with hub-target highlighting |
| Structure selection | Uses an experimental structure when one exists, otherwise an AlphaFold model with its confidence shown; the structure source appears on every result |
| Docking ranking | AutoDock Vina scores for top compounds vs hub targets, shown as a ranked table |
| Lab-test shortlist | Top candidates with the reasoning, and the checks that would confirm or reject them |
| PDF report | Shareable summary with a "limitations and caveats" page on every report |

**Demo mode:** docking is **pre-computed** for the demo formulation and loaded from saved results. We do not dock live on stage.

## How it works

```
Formulation (plants + part + solvent) + condition
        |
        v
  Plant / plant-part -> compound lookup
        |
        v
  Extraction-aware filter (polarity heuristic)
        |
        v
  Drug-likeness filter (RDKit)
        |
        v
  Target prediction  ----+
                         |
  Disease-related targets +--> Overlap --> Network + hub targets
                                                |
                                                v
                                  Structure selection
                                  (experimental, else AlphaFold)
                                                |
                                                v
                                  Docking (AutoDock Vina)
                                  top compounds vs hub targets
                                                |
                                                v
                              Ranked shortlist + PDF report
```

### Methods

- **Extraction-aware filter:** whether a compound ends up in an extract depends on the plant part and the solvent. We approximate this with compound polarity (logP) against a polar / mid-polar / non-polar solvent choice. This is a heuristic, not an extraction model.
- **Drug-likeness:** property-based screen (molecular weight, logP, H-bond donors and acceptors) as a first filter. It narrows the list and does not predict activity.
- **Network pharmacology:** targets shared by a compound set and a condition are treated as candidates; hub targets are identified by network centrality (for example, degree).
- **Structure selection:** where an experimental structure exists (RCSB PDB), we prefer it, ideally one with a bound ligand that defines the binding site. Where none exists, we use the AlphaFold database model for the target's UniProt entry, check the per-residue confidence (pLDDT) in the binding region, and define the pocket from known annotations or a pocket-detection tool. Targets whose pocket confidence is low are not docked. In the demo, models are downloaded in advance; we do not run AlphaFold ourselves.
- **Docking:** AutoDock Vina binding scores are used to **rank** candidates. A good score is a reason to test a compound, not evidence that it works. Results depend on the protein structure and the preparation steps used.
- **Prioritisation:** candidates are ordered by combined evidence (drug-likeness, network position, docking rank). Weights are defaults and are tuned only against the validation case below.

## Retrospective validation (complete before the pitch)

The question every scientist will ask is "how do you know the ranking is any good?" We answer it with a retrospective test, and we report the result whatever it is.

- **Formulation or plant:** `[TODO: choose one or two well-studied cases whose active compounds and targets are already published]`
- **Known actives (from the literature):** `[TODO: list, with references]`
- **Protocol:** choose the case(s) and write them down before running; do not tune weights on them; report every case we run, including misses.
- **Method:** run the pipeline blind to the known answer; record where the known actives land in our ranking.
- **Result:** `[TODO: e.g. "X of Y known actives ranked in the top N" , reported honestly, including misses]`
- **What this does and does not show:** agreement with published findings supports the usefulness of the ranking. It is not a prospective validation and does not prove a compound works.

## Data sources and licensing

`[TODO: confirm each source's current terms before the demo]`

| Source (examples) | Used for | Licence note |
|---|---|---|
| IMPPAT (Indian medicinal plants, phytochemistry, therapeutics) | Plant, plant-part and compound mapping | Distributed under non-commercial terms as far as we can tell; **confirm on the source site** |
| PubChem | Compound structures | `[TODO: check]` |
| SwissTargetPrediction | Target prediction | Academic-oriented terms; `[TODO: check commercial use]` |
| STRING | Protein-protein interactions | `[TODO: check]` |
| RCSB PDB | Experimental protein structures | `[TODO: check]` |
| AlphaFold Protein Structure Database | Predicted structures where no experimental one exists | CC BY 4.0, which permits commercial use with attribution. We use the database only; AlphaFold 3 outputs are non-commercial |
| A public gene-disease database | Disease-related targets | `[TODO: check licence]` |

**Hackathon demo:** runs on data used under academic terms. **Before any commercial use:** we will license the restricted datasets or replace them with commercially permitted sources (for example, ChEMBL, BindingDB, Open Targets), and this is part of our funding plan.

## Quick start

```bash
git clone <repo-url> phytolens && cd phytolens
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# engine (docs at http://127.0.0.1:8000/docs)
uvicorn engine.api:app --host 127.0.0.1 --port 8000

# workbench (http://127.0.0.1:3000), in a second shell
cd web && npm install && npm run dev
```

Redis is optional: with it running, runs are queued and `python -m engine.worker` consumes them;
without it the API falls back to an in-process thread pool. Full docking (live, or rebuilding the
panel) needs the system binaries `vina` and `obabel`.

## Project structure (planned)

```
phytolens/
|-- engine/api.py                FastAPI service (/v1)
|-- engine/jobs.py               Redis run queue, in-process fallback
|-- engine/worker.py             out-of-process run worker
|-- engine/ratelimit.py          per-endpoint limits
|-- engine/auth.py               optional bearer API keys
|-- engine/pipeline/             extraction, ranking, docking
|-- engine/validation/           cases, controls, stored results
|-- engine/report.py             PDF shortlist
|-- engine/data/                 corpus, target sets, docking panel, reports
|-- web/                         Next.js workbench
|-- scripts/                     pitch-reel pipeline (separate from the product)
|-- requirements.txt
`-- README.md
```

## Business model

- **Annual licence (reports included)** for brands and contract manufacturers; per-report pricing for occasional users. Price: `[TODO: CFO to set; treat as an assumption to test in pilots]`. We use one pricing model in all materials so the price, the scenario below and the ask agree.
- **Services add-on:** custom analyses for a specific formulation, reviewed by a scientist, delivered as a dossier-ready white paper.
- **Later:** partnerships with testing labs, so a shortlist can lead directly to a lab-validation package.

**Illustrative scenario (assumptions, not forecasts):** India has roughly 8,500 to 9,000 licensed AYUSH drug manufacturing units (sources differ; `[TODO: cite the one you use]`). If 2% became customers (about 170) at an assumed Rs 50,000 a year, revenue would be about Rs 85 lakh a year. Both the adoption share and the price are untested.

## Where defensibility could come from

The pipeline uses public data and open-source tools, so the workflow alone is easy to copy. Our plan for a durable edge:

1. **A validated ranking:** benchmark results on published cases that competitors cannot get without doing the same work.
2. **Extraction- and plant-part-aware modelling,** which most generic tools skip.
3. **Licensed, curated Indian phytochemical data** and an accumulating library of formulation-level reports.
4. **Workflow and report quality:** dossier-ready outputs that a regulatory or R&D team can use directly.

These are plans, not yet achievements.

## How we differ

Enterprise docking and discovery suites are built for large pharma teams with trained computational chemists. PhytoLens is built for formulators and regulatory teams: formulation in, explainable and caveated shortlist out, at a price a mid-size manufacturer can justify.

## Why us

The team has hands-on experience in network pharmacology, molecular docking with AutoDock Vina, and medical-image analysis.

**Reuse note:** the PhytoLens application layer was built during the event. Parts of our earlier network pharmacology and docking work were adapted with the organizers' permission. `[TODO: list exactly what was reused]`

## Roadmap

1. Complete and publish the retrospective validation; refine weights only on the validation case, not on the demo.
2. Pilot with one export-oriented manufacturer and one college lab.
3. Resolve data licensing for commercial use.
4. Add ADMET and toxicity predictions to the shortlist.
5. Add literature-support tagging for each compound-target link.
6. Offer a lab-validation partnership for shortlisted candidates.
7. Benchmark docking on AlphaFold models against experimental structures for targets that have both.

## Pilot ask

`[TODO: amount, equity offered; be ready to justify the valuation it implies]`. Sized as validation-and-pilot capital for the first six months: finish validation, license or replace restricted datasets, run two pilots, add ADMET and literature tagging.

## Build status (tick off before the demo, delete anything not finished)

- [ ] Formulation input with plant part and solvent type
- [ ] Plant-to-compound lookup
- [ ] Extraction-aware (polarity) filter
- [ ] Drug-likeness filter
- [ ] Target prediction and disease overlap
- [ ] Network view with hub targets
- [ ] Structure selection (experimental vs AlphaFold) with source and confidence shown
- [ ] Pre-computed docking results loaded in demo mode
- [ ] Ranked shortlist table
- [ ] Retrospective validation run and result recorded
- [ ] PDF report with caveats page
- [ ] Unit tests for filter and network metrics

## Limitations (read these)

- Prototype only. No prospective laboratory validation has been done.
- Docking scores rank candidates; they do not show that a compound binds in practice, is absorbed, is safe, or has any effect in people.
- Predicted (AlphaFold) structures are static models without a bound ligand. Docking against them is less reliable than against experimental structures, especially where model confidence is low, and the binding site may be misplaced. Those results are flagged and treated with lower trust.
- Target predictions and database entries can be incomplete or wrong, and the output is only as good as the data behind it.
- The extraction filter is a polarity heuristic and does not model real extraction.
- Network and docking results depend on the chosen databases, structures and parameters.
- Whole formulations act through many compounds at once; this tool simplifies that picture.
- The demo uses data under academic terms; commercial use needs licensing changes.
- Nothing here is a health claim or medical advice.

## Team

| Role | Name |
|---|---|
| CEO | `[TODO]` |
| CTO | `[TODO]` |
| CPO | `[TODO]` |
| CFO | `[TODO]` |
| CMO | `[TODO]` |
| Scientific advisor (pharmacology / phytochemistry) | `[TODO]` |

## License

`[TODO: choose a licence]`
