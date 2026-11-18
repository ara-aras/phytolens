# PhytoLens — Prospective Wet-Lab Validation Protocol (Collaborator Hand-Off)

This protocol defines the prospective wet-lab assay matrix required to validate
PhytoLens's top in-silico hypotheses for *Curcuma longa* (rhizome, 70% ethanol →
colitis) and *Boswellia serrata* (gum-resin exudate, 70% ethanol → IBD).

---

## 1. Candidate Panel & Controls

| ID | Compound | Formulation Source | PhytoLens Rank | Primary Docked Targets | Structural / ADMET Notes |
|---|---|---|---|---|---|
| `IMPHY014839` | **Bisdemethoxycurcumin** | *Curcuma longa* rhizome | #1 (`0.6425`) | `MAPK14` (-9.11), `PTGS2` (-8.08), `ALOX5` (-6.94) | Brenk: `Michael_acceptor_1`, `beta-keto/anhydride`; GI high |
| `IMPHY002883` | **Curcumin** | *Curcuma longa* rhizome | #2 (`0.5835`) | `MAPK14` (-8.34), `PTGS2` (-7.96), `ALOX5` (-6.73) | Promiscuous (84 measured targets); Brenk: `Michael_acceptor_1` |
| `IMPHY012071` | **Demethoxycurcumin** | *Curcuma longa* rhizome | #4 (`0.5421`) | `MAPK14` (-8.58), `PTGS2` (-8.08), `ALOX5` (-6.37) | Brenk: `Michael_acceptor_1`, `beta-keto/anhydride`; GI high |
| `IMPHY004623` | **β-Boswellic acid** | *Boswellia serrata* exudate | #1 (`0.4319`) | `ALOX5` (-10.19, `1.99 Å` to `Fe²⁺`) | Lipinski `logP > 5` (7.09); GI low; 0 PAINS/Brenk alerts |
| `IMPHY011938` | **AKBA** | *Boswellia serrata* exudate | #7 (`0.3821`) | `ALOX5` (-10.13, `2.35 Å` to `Fe²⁺`) | Lipinski `MW > 500`, `logP > 5`; 0 PAINS/Brenk alerts |
| **Negative Control 1** | **Eugenol** | *Curcuma* / *Boswellia* | #11 (dropped from #1) | Weak across panel (-5.32 to -6.14) | Tests that docking correctly demoted the annotation-bias leader |
| **Negative Control 2** | **Geraniol** | *Boswellia* / *Curcuma* | #8 / #13 (dropped from #1) | Weak across panel (-5.40 to -6.05) | Tests that docking correctly demoted the 99-target volatile |

---

## 2. Biochemical Target Assays (8-Point IC50, Triplicate)

Concentrations: `0.03, 0.1, 0.3, 1.0, 3.0, 10, 30, 100 μM` in `1% DMSO`.

1. **Human Recombinant COX-2 (`PTGS2`, corresponds to PDB `3NT1`):**
   - **Assay:** Fluorometric / EIA prostaglandin H2 synthase assay (arachidonic acid substrate `10 μM`).
   - **Positive Control:** Celecoxib (`IC50 ~ 0.05 μM`) and Naproxen (`NPS`, co-crystal ligand of `3NT1`).
2. **Human Recombinant 5-LOX (`ALOX5`, corresponds to PDB `3V99`):**
   - **Assay:** UV/fluorescence hydroperoxide formation assay with catalytic `Fe²⁺` preserved (`20 μM` arachidonic acid).
   - **Positive Control:** Zileuton (`IC50 ~ 0.5 μM`).
3. **Human p38-α MAPK (`MAPK14`, corresponds to PDB `3D83`):**
   - **Assay:** TR-FRET / ADP-Glo kinase assay (`ATP = 10 μM`, close to apparent $K_m$).
   - **Positive Control:** SB203580 (`IC50 ~ 0.04 μM`).
4. **Human TNF-α Dimer Disruption (`TNF`, corresponds to PDB `2AZ5`):**
   - **Assay:** Homogeneous TR-FRET TNF-α — TNFR1 binding inhibition assay.
   - **Positive Control:** SPD304 / Inhibitor `307`.

---

## 3. Mandatory Counter-Screens for Assay Interference (PAINS / Brenk)

Because `engine/pipeline/admet.py` flags the curcuminoids for `Michael_acceptor_1`
and `beta-keto/anhydride` motifs:
- **Detergent Counter-Screen (Colloidal Aggregation):** Re-run every biochemical IC50 curve with and without **`0.01% Triton X-100`**. Any compound whose IC50 shifts by `> 3-fold` upon detergent addition is classified as a colloidal aggregator.
- **Thiol Reactivity Check:** Incubate `10 μM` test compound with `1 mM` reduced glutathione (GSH) at pH 7.4 (`37 °C, 60 min`) and monitor adduct formation by LC-MS to separate reversible binding from covalent Michael addition.

---

## 4. Pre-Registered Pass / Fail Criterion

The prospective test succeeds if:
1. At least **two of the three curcuminoids** (ranked #1, #2, #4) show non-aggregating inhibition (`IC50 < 25 μM` in the presence of `0.01% Triton X-100`) on `PTGS2` or `MAPK14` **and** outperform **Eugenol** (ranked #1 by naive target count, #11 by PhytoLens) by `≥ 3-fold`.
2. **AKBA** and **β-Boswellic acid** (ranked #1 and #7 in *Boswellia*, coordinating `Fe²⁺` at `1.99–2.35 Å` in `3V99`) inhibit `ALOX5` with `IC50 < 25 μM` **and** outperform **Geraniol** (ranked #1 by naive target count, #8 by PhytoLens) by `≥ 5-fold`.
