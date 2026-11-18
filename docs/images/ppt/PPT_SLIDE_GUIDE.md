# PhytoLens — PPT Screenshot & Slide Deck Guide

All high-resolution (`3040 × 1960` Retina 2x) screenshots are stored in
[`docs/images/ppt/`](file:///C:/Projects/Photolens/docs/images/ppt/). Below is
each screenshot paired with its exact example formulation, what is shown on
screen, and ready-to-paste slide copy for your PPT.

---

## 1. Formulation Builder & Corpus Overview
- **File:** [`01_landing_formulation_builder.png`](file:///C:/Projects/Photolens/docs/images/ppt/01_landing_formulation_builder.png)
- **What it shows:** The initial PhytoLens workbench showing the Formulation Builder sidebar (Plant, Plant Part, Solvent, Condition, Shortlist Size), live corpus statistics (`4,154 plants`, `18,314 compounds`, `38,842 compound-target links`), and the 3-stage pipeline summary (`01 Extraction + flags`, `02 Gate, then rank`, `03 Three-target panel`).
- **Slide Copy:**
  - **Title:** *The Formulation Bottleneck: 168+ Phytochemicals in One Plant Part*
  - **Bullets:**
    - Traditional preparations specify **plant + plant part + extraction solvent** (e.g., 70% ethanol vs. aqueous decoction).
    - Built on **4,154 Indian medicinal plants** and **18,314 phytochemicals** with RDKit physicochemical descriptors and Open Targets human disease gene sets.

---

## 2. Example 1 (*Curcuma longa* Rhizome → Colitis): 3D Docking in COX-2 (`3NT1`)
- **File:** [`02_curcuma_overview_and_3d_cox2.png`](file:///C:/Projects/Photolens/docs/images/ppt/02_curcuma_overview_and_3d_cox2.png)
- **What it shows:**
  - **Narrowing Funnel:** `168 in part → 168 pass extraction → 24 reach a colitis target → 24/24 docked`.
  - **3D Molecular Docking Studio:** **#1 Bisdemethoxycurcumin** docked inside **COX-2 (`PTGS2 · PDB 3NT1`, `-8.08 kcal/mol`, `LE = -0.351 kcal/mol/HA`)** with the `20 × 20 × 20 Å` co-crystal naproxen (`NPS`) box, translucent emerald active-site pocket surface, all 9 Vina binding modes (`M1`–`M9`), `≤ 4.5 Å` pocket contact residues (`GLN 369 · 2.16 Å`, `GLN 370 · 2.64 Å`), 2D RDKit chemical depiction, and ADMET/Brenk alerts.
- **Slide Copy:**
  - **Title:** *Primary Demo: Curcuma longa Rhizome (70% Ethanol) → Ulcerative Colitis*
  - **Bullets:**
    - Narrows **168 rhizome compounds** down to the **24** that intersect verified Open Targets colitis genes.
    - **#1 Bisdemethoxycurcumin** docks into the **COX-2 (`3NT1`)** pocket at **`-8.08 kcal/mol`** (`Intermolecular E = -11.39 kcal/mol`).

---

## 3. Example 1b (*Curcuma longa*): 3D Docking in p38-α MAPK (`MAPK14 · 3D83`)
- **File:** [`03_curcuma_3d_p38_mapk14.png`](file:///C:/Projects/Photolens/docs/images/ppt/03_curcuma_3d_p38_mapk14.png)
- **What it shows:** **#1 Bisdemethoxycurcumin** inside the ATP-binding cleft of **p38-α MAPK (`MAPK14 · PDB 3D83`)** scoring **`-8.91 kcal/mol`** (`LE = -0.387 kcal/mol/HA`) across 9 Vina binding modes.
- **Slide Copy:**
  - **Title:** *Multi-Target Mechanistic Evidence: p38-α MAPK (`3D83`, 1.90 Å)*
  - **Bullets:**
    - Every candidate is scored across a 3-target inflammatory panel (`COX-2`, `5-LOX`, `p38-α`) rather than a single protein.
    - Strongest binding is observed in **p38-α (`-8.91 kcal/mol`)** inside the co-crystallised biphenyl amide inhibitor pocket (`GK6`).

---

## 4. Example 1c (*Curcuma longa*): 3D Docking of Curcumin in TNF-α (`2AZ5`)
- **File:** [`04_curcuma_3d_tnf_2az5.png`](file:///C:/Projects/Photolens/docs/images/ppt/04_curcuma_3d_tnf_2az5.png)
- **What it shows:** **#2 Curcumin** docked into the homodimer interface pocket of **human TNF-α (`TNF · PDB 2AZ5`, `-7.01 kcal/mol`)** with RDKit ADMET (`QED = 0.548`, `GI = high`, `BBB = no`, Brenk `Michael_acceptor_1`).
- **Slide Copy:**
  - **Title:** *On-Demand 4th Target: Human TNF-α Homodimer Interface (`2AZ5`)*
  - **Bullets:**
    - Supports on-demand live docking into **TNF-α (`2AZ5`, co-crystal ligand `307`)** at **`-7.01 kcal/mol`**.
    - Automatically flags **Brenk `Michael_acceptor_1`** and **`beta-keto/anhydride`** alerts so wet labs include Triton X-100 and GSH counter-screens.

---

## 5. Example 1d (*Curcuma longa*): Ranked Shortlist Table & Explainable Evidence Drawer
- **File:** [`05_curcuma_shortlist_and_evidence_drawer.png`](file:///C:/Projects/Photolens/docs/images/ppt/05_curcuma_shortlist_and_evidence_drawer.png)
- **What it shows:** The ranked shortlist table with **#1 Bisdemethoxycurcumin**, **#2 Curcumin**, **#3 Cholesterol** (disclosed sterol), and **#4 Demethoxycurcumin** (while **Eugenol** drops from #1 pre-docking to **#11**), with expanded evidence drawers showing `measured` vs. `predicted` target gene chips and term-by-term score contribution bars.
- **Slide Copy:**
  - **Title:** *Explainable Ranking: Every Score Decomposed, Every Caveat Disclosed*
  - **Bullets:**
    - **Before docking:** Naive target-count ranking puts **Eugenol #1** and buries **Curcumin at #8**.
    - **After docking:** The three clinically validated curcuminoids rank **#1, #2, and #4**; **Eugenol drops to #11**.
    - **Radical honesty:** **Cholesterol (#3)** is left in the table and explicitly disclosed rather than hidden behind a manual blocklist.

---

## 6. Example 1e (*Curcuma longa*): Bipartite Mechanism Topology (`Compound → Target → Colitis`)
- **File:** [`06_curcuma_network_graph.png`](file:///C:/Projects/Photolens/docs/images/ppt/06_curcuma_network_graph.png)
- **What it shows:** The interactive bipartite network graph linking top ranked turmeric compounds to human colitis targets (`PTGS2`, `TNF`, `STAT3`, `MMP9`, `IL6`, `NFKB1`) and the disease node, distinguishing **Measured (`ChEMBL / BindingDB`, solid green)** from **Predicted (`NPASS`, dashed amber)** links.
- **Slide Copy:**
  - **Title:** *Mechanism Topology: Measured Bioassays vs. Predicted Annotations*
  - **Bullets:**
    - Visualizes how shortlisted compounds converge on high-degree disease hub proteins (`PTGS2`, `TNF`, `STAT3`).
    - Separates experimental binding evidence (`ChEMBL / BindingDB`) from inferred predictions (`NPASS`).

---

## 7. Example 2 (*Boswellia serrata* Exudate → IBD): 5-LOX (`3V99`) Catalytic `Fe²⁺` Coordination
- **File:** [`07_boswellia_3d_alox5_fe2_coordination.png`](file:///C:/Projects/Photolens/docs/images/ppt/07_boswellia_3d_alox5_fe2_coordination.png)
- **What it shows:** *Boswellia serrata* (Frankincense) gum-resin exudate (`47 in part → 47 pass extraction → 17 reach IBD target → 17/17 docked`), with **#1 β-Boswellic acid** docked inside **5-LOX (`ALOX5 · PDB 3V99`, `-10.19 kcal/mol`)** directly coordinating the **catalytic `★ FE2 701 · 1.99 Å` non-heme iron cofactor** (visible as the golden sphere in the 3D pocket and the amber cofactor badge!).
- **Slide Copy:**
  - **Title:** *Example 2: Boswellia serrata Gum-Resin → IBD (5-LOX Catalytic Fe²⁺ Coordination)*
  - **Bullets:**
    - **β-Boswellic acid (#1)** and **α-Boswellic acid (#2)** score **`-10.19 kcal/mol`** in **5-LOX (`3V99`)**, coordinating directly to the catalytic **`Fe²⁺` ion at `1.99 Å`**.
    - Demotes **Geraniol** (99 annotated targets, #1 under naive network pharmacology) down to **#8**.

---

## 8. Example 2b (*Boswellia serrata*): Why Lipinski Rules Are Flags, Never Drops (AKBA)
- **File:** [`08_boswellia_shortlist_and_akba_flags.png`](file:///C:/Projects/Photolens/docs/images/ppt/08_boswellia_shortlist_and_akba_flags.png)
- **What it shows:** The *Boswellia serrata* shortlist table with **β-Boswellic acid (#1)**, **α-Boswellic acid (#2)**, **11-Keto-β-boswellic acid (#4)**, and **AKBA (`3-Acetyl-11-keto-beta-boswellic acid`, #7)** expanded, showing `lipinski_mw>500, lipinski_logp>5` preserved as non-destructive flags.
- **Slide Copy:**
  - **Title:** *Scientific Correction #1: Why Naive Drug-Likeness Filters Fail on Phytochemicals*
  - **Bullets:**
    - A textbook Lipinski filter (`MW ≤ 500`, `logP ≤ 5.0`) deletes **all five boswellic acids** (`logP 6.27–7.66`, AKBA `MW = 512.7`) while keeping 36 volatile monoterpenes.
    - PhytoLens widens the 70% ethanol window (`-1.0 ≤ logP ≤ 8.5`, `MW ≤ 700`) and turns Lipinski/Veber violations into **reportable flags**, preserving **4/4 known actives in the top 7**.

---

## 9. Example 3 (*Piper nigrum* Fruit → IBD): Piperine Lifted from #13 to #3
- **File:** [`09_piper_nigrum_piperine_3d_and_shortlist.png`](file:///C:/Projects/Photolens/docs/images/ppt/09_piper_nigrum_piperine_3d_and_shortlist.png)
- **What it shows:** *Piper nigrum* (Black Pepper) fruit (`100 in part → 92 pass extraction → 19 reach IBD target → 19/19 docked`), showing **Piperine** docked in **COX-2 (`3NT1`, `-7.88 kcal/mol`, `LE = -0.375 kcal/mol/HA`)** and ranked **#3** (up from **#13** without docking, `ΔMRR = +0.256`).
- **Slide Copy:**
  - **Title:** *Example 3: Piper nigrum (Black Pepper) Fruit → IBD*
  - **Bullets:**
    - Tests the pipeline on a non-curcuminoid alkaloid formulation (`100 → 92 → 19` funnel).
    - Molecular docking lifts **Piperine** from **#13 (annotation-only)** to **#3 (`-7.88 kcal/mol` on COX-2, `-7.99 kcal/mol` on p38-α)**.

---

## 10. Example 4 (*Withania somnifera* Root → IBD): The Honest Residual-Bias Control Case
- **File:** [`10_withania_somnifera_control_case.png`](file:///C:/Projects/Photolens/docs/images/ppt/10_withania_somnifera_control_case.png)
- **What it shows:** *Withania somnifera* (Ashwagandha) root (`25 in part → 21 pass extraction → 6 reach IBD target → 6/6 docked`), showing **Withanolide D (#3, `-10.10 kcal/mol` on `MAPK14`)** and **Withaferin A (#5, `-9.61 kcal/mol` on `MAPK14`)** alongside the residual annotation bias (**Nicotine**).
- **Slide Copy:**
  - **Title:** *Example 4 (Control Case): Withania somnifera Root → IBD*
  - **Bullets:**
    - Included deliberately as an **unflattering control case** (`6` candidates reaching IBD targets).
    - Shows both the strong steroidal lactone docking (`Withanolide D -10.10 kcal/mol`) and the remaining annotation-density bias (`Nicotine`), proving the benchmark is **untuned**.

---

## 11. Example 5 (*Zingiber officinale* Rhizome → Colitis): On-Demand Live Vina Docking
- **File:** [`11_zingiber_officinale_ginger_live_dock.png`](file:///C:/Projects/Photolens/docs/images/ppt/11_zingiber_officinale_ginger_live_dock.png)
- **What it shows:** *Zingiber officinale* (Ginger) rhizome (`183 in part → 178 pass extraction → 21 reach colitis target → 14/21 docked`), showing live on-demand AutoDock Vina scores for **Gingerol (`-6.45 kcal/mol` in `6.6 s`)** and **Shogaol (`-6.34 kcal/mol` in `5.1 s`)** merged into the shortlist.
- **Slide Copy:**
  - **Title:** *Example 5: Zingiber officinale (Ginger) Rhizome — Live On-Demand Vina Docking*
  - **Bullets:**
    - Demonstrates real-time `POST /v1/runs/{id}/dock` execution on compounds outside the precomputed panel (`Shogaol` in `5.1 s`, `Gingerol` in `6.6 s`).
    - Transparently flags **partial docking coverage (`14/21 docked`)** so mixed rankings are never misrepresented.

---

## 12. Retrospective Validation & The 23.9% Corpus-Bias Proof
- **File:** [`12_retrospective_validation_and_corpus_bias.png`](file:///C:/Projects/Photolens/docs/images/ppt/12_retrospective_validation_and_corpus_bias.png)
- **What it shows:** The complete validation dashboard: `4 cases`, `10/10 known actives found`, **`Mean MRR 0.414` vs. `0.197` without docking (`+0.217 ΔMRR`, +110% relative lift)**, **`24% (2,034 / 8,510)` corpus-wide bias**, and the per-case ablation + 1,000-permutation null p-values.
- **Slide Copy:**
  - **Title:** *Retrospective Validation: +110% MRR Lift Across 4 Untuned Benchmarks*
  - **Bullets:**
    - **23.9% Corpus Bias (`2,034 / 8,510` plant-part groups):** Raw target-count ranking returns the same 6 ubiquitous compounds (*Eugenol, Geraniol, Cinnamaldehyde, Quercetin, Eucalyptol, Safrole*) for 1 in 4 herbal preparations.
    - **Docking Ablation:** Mean Reciprocal Rank doubles from **`0.197` (without docking)** to **`0.414` (with docking)** (`p = 0.001` on *Curcuma*, `p = 0.008` on *Boswellia*).

---

## 13. Exportable 2-Page PDF Dossier (Shortlist + Mandatory Caveats & Provenance)
- **File:** [`docs/images/report.png`](file:///C:/Projects/Photolens/docs/images/report.png) (and [`engine/data/reports/demo_shortlist.pdf`](file:///C:/Projects/Photolens/engine/data/reports/demo_shortlist.pdf))
- **What it shows:** The auto-generated 2-page PDF report carrying config hashes (`extraction cb01967761fc / ranking e34ce582afd0`), monotonic funnel, per-target Vina affinities, mandatory **Limitations and Caveats** page, **Provenance Appendix**, and `DATA_LICENSE.md` footer.
