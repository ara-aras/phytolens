"""PDF shortlist report with a mandatory caveats page and provenance appendix.

The report is generated from a `RankingResult`, never from the database
directly, so a PDF always corresponds to exactly one computed ranking and its
two config hashes.

Run:
    python -m engine.report --plant "Curcuma longa" --part rhizome \
        --condition colitis --out report.pdf
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

from engine.pipeline import ranking as rk

ENGINE_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = ENGINE_DIR / "data" / "reports"

INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#4B5563")
ACCENT = colors.HexColor("#0E7490")
WARN = colors.HexColor("#B45309")
RULE = colors.HexColor("#D1D5DB")
PALE = colors.HexColor("#F3F4F6")

CAVEATS = [
    "This is an in-silico prioritisation tool. Every output is a hypothesis for "
    "laboratory validation, not evidence that a formulation or compound works.",
    "Docking scores rank candidates. They do not show binding in practice, "
    "absorption, safety, or any effect in people. Vina also favours larger "
    "ligands, which is why ligand efficiency is shown alongside affinity.",
    "Only the targets listed in the panel were docked. A compound that binds "
    "nothing in this panel may still be active through an untested target.",
    "The extraction filter is a calculated-logP heuristic, not an extraction "
    "model. It reports what a solvent can plausibly carry.",
    "Compound-target links are database annotations. NPASS-only links are "
    "predicted; ChEMBL and BindingDB links are measured. Each row's evidence "
    "mix is visible in the shortlist.",
    "Annotation depth is biased toward well-studied compounds. The ranking "
    "therefore gates on target overlap and weights docking, but residual bias "
    "remains and is disclosed where it is known.",
    "The plant-compound corpus is IMPPAT 2.0, licensed CC BY-NC-ND 4.0: "
    "academic and non-commercial use only. Commercial use needs a licence or a "
    "replacement source.",
    "Nothing in this report is medical advice, a diagnosis, a treatment "
    "recommendation, or a substantiated health claim.",
]


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Helvetica-Bold",
                                fontSize=19, leading=23, textColor=INK,
                                alignment=TA_LEFT, spaceAfter=2),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontName="Helvetica",
                                   fontSize=9.5, leading=13, textColor=MUTED),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold",
                             fontSize=12, leading=15, textColor=ACCENT,
                             spaceBefore=10, spaceAfter=5),
        "body": ParagraphStyle("body", parent=base["Normal"], fontName="Helvetica",
                               fontSize=8.8, leading=12.2, textColor=INK),
        "small": ParagraphStyle("small", parent=base["Normal"], fontName="Helvetica",
                                fontSize=7.6, leading=10, textColor=MUTED),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontName="Helvetica",
                               fontSize=7.8, leading=9.6, textColor=INK),
        "cell_bold": ParagraphStyle("cell_bold", parent=base["Normal"],
                                    fontName="Helvetica-Bold", fontSize=7.8,
                                    leading=9.6, textColor=INK),
        "bullet": ParagraphStyle("bullet", parent=base["Normal"], fontName="Helvetica",
                                 fontSize=8.4, leading=11.4, textColor=INK,
                                 leftIndent=9, bulletIndent=0, spaceAfter=4),
    }


def _table(rows, widths, *, header=True, zebra=True):
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, RULE),
    ]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), PALE))
    if zebra:
        for i in range(2, len(rows), 2):
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FAFAFA")))
    table.setStyle(TableStyle(style))
    return table


def _fmt(value, digits=2):
    return "n/a" if value is None else f"{value:.{digits}f}"


def build_report(result: rk.RankingResult, out_path: str | Path, *,
                 title: str = "PhytoLens research shortlist",
                 docking_meta: dict | None = None,
                 top: int | None = None) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    s = _styles()
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=title, author="PhytoLens",
        subject=("In-silico research shortlist. Hypotheses for laboratory "
                 "validation only."),
    )
    story = []
    e = result.extraction
    cond = result.condition
    summary = result.summary()
    rows = result.ranked[:top] if top else result.ranked

    # ---- header ----------------------------------------------------------
    story.append(Paragraph(title, s["title"]))
    story.append(Paragraph(
        f"{e.plant_name} &nbsp;|&nbsp; part: <b>{e.part}</b> &nbsp;|&nbsp; "
        f"solvent: <b>{e.solvent_label}</b> &nbsp;|&nbsp; condition: "
        f"<b>{cond.name}</b> ({len(cond.genes)} targets, {cond.source})",
        s["subtitle"]))
    story.append(Spacer(1, 3 * mm))

    meta = [
        [Paragraph("Generated", s["cell"]), Paragraph(date.today().isoformat(), s["cell"]),
         Paragraph("Config hashes", s["cell"]),
         Paragraph(f"extraction {e.config_hash} / ranking {result.config_hash}", s["cell"])],
        [Paragraph("Docking", s["cell"]),
         Paragraph("pending" if result.docking_pending else "included", s["cell"]),
         Paragraph("Condition data", s["cell"]),
         Paragraph(f"{cond.source}, retrieved {cond.retrieved or 'n/a'}, "
                   f"score >= {cond.min_score}", s["cell"])],
    ]
    story.append(_table(meta, [26 * mm, 56 * mm, 30 * mm, 62 * mm],
                        header=False, zebra=False))

    # ---- funnel ----------------------------------------------------------
    f = summary["funnel"]
    story.append(Paragraph("How the formulation narrowed", s["h2"]))
    funnel_rows = [[Paragraph("Stage", s["cell_bold"]),
                    Paragraph("Compounds", s["cell_bold"])]]
    for label, key in (
        ("In the chosen plant part", "in_part"),
        ("Pass extraction window and MW ceiling", "pass_extraction"),
        ("Carry a drug-likeness flag (kept, not dropped)", "flagged_druglikeness"),
        ("Reach at least one condition target", "with_condition_target"),
        ("Excluded for no condition target", "excluded_no_condition_target"),
    ):
        funnel_rows.append([Paragraph(label, s["cell"]),
                            Paragraph(str(f[key]), s["cell"])])
    story.append(_table(funnel_rows, [120 * mm, 28 * mm]))

    # ---- shortlist -------------------------------------------------------
    targets = sorted({g for r in rows for g in r.docking})
    story.append(Paragraph("Ranked shortlist", s["h2"]))
    story.append(Paragraph(
        "Scores are the weighted composite described in <i>ranking.yaml</i>. "
        "Docking columns are AutoDock Vina affinities in kcal/mol; lower is "
        "better. A dash means the compound was not docked against that target.",
        s["small"]))
    story.append(Spacer(1, 2 * mm))

    header = [Paragraph("Rank", s["cell_bold"]), Paragraph("Compound", s["cell_bold"]),
              Paragraph("Score", s["cell_bold"]), Paragraph("Targets", s["cell_bold"]),
              Paragraph("Measured", s["cell_bold"])]
    header += [Paragraph(t, s["cell_bold"]) for t in targets]
    header.append(Paragraph("Flags", s["cell_bold"]))
    table_rows = [header]
    for r in rows:
        cells = [Paragraph(str(r.rank), s["cell"]),
                 Paragraph(r.compound.name[:34], s["cell"]),
                 Paragraph(_fmt(r.score, 3), s["cell"]),
                 Paragraph(str(len(r.overlap_all)), s["cell"]),
                 Paragraph(str(len(r.overlap_measured)), s["cell"])]
        cells += [Paragraph(_fmt(r.docking.get(t)), s["cell"]) for t in targets]
        cells.append(Paragraph(", ".join(r.flags)[:34] or "-", s["cell"]))
        table_rows.append(cells)
    widths = [11 * mm, 46 * mm, 13 * mm, 14 * mm, 16 * mm]
    widths += [15 * mm for _ in targets]
    widths.append(41 * mm)
    story.append(_table(table_rows, widths))

    docking_info = summary["docking"]
    if result.docking_pending:
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            "Docking has not run for this formulation. The docking weight was "
            "redistributed across the remaining terms, so this ordering is "
            "preliminary and must not be presented as final.", s["body"]))
    elif docking_info["partial"]:
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            f"Partial docking coverage: {docking_info['docked']} of "
            f"{docking_info['candidates']} candidates were docked. Undocked rows "
            "were scored with the docking weight redistributed, so their scores "
            "are not directly comparable with docked rows. Treat the mixed "
            "ordering as provisional.", s["body"]))

    # ---- page 2: caveats + provenance ------------------------------------
    story.append(PageBreak())
    story.append(Paragraph("Limitations and caveats", s["h2"]))
    story.append(Paragraph(
        "These caveats are part of the result. A shortlist presented without "
        "them is not this tool's output.", s["small"]))
    story.append(Spacer(1, 2 * mm))
    for item in CAVEATS:
        story.append(Paragraph(item, s["bullet"], bulletText="\u2022"))

    story.append(Paragraph("Provenance appendix", s["h2"]))
    prov = [
        ("Plant and compound corpus",
         "IMPPAT 2.0, CC BY-NC-ND 4.0 (academic / non-commercial; no derivatives)."),
        ("Compound properties",
         "RDKit 2025.09.6: Crippen logP, TPSA, HBD/HBA, rotatable bonds."),
        ("Compound-target links",
         "IMPPAT target table, which unions ChEMBL, BindingDB and NPASS. "
         "NPASS-only links are treated as predicted."),
        ("Condition target set",
         f"Open Targets Platform GraphQL v4, CC0 1.0. {len(cond.genes)} targets "
         f"at association score >= {cond.min_score}."),
        ("Structures",
         "RCSB PDB experimental structures; the box is the centroid of a "
         "co-crystallised inhibitor, never a hand-picked coordinate."),
        ("Docking",
         "AutoDock Vina, CPU. Seed 42, exhaustiveness 8, 20 A box. Ligands "
         "prepared with RDKit ETKDGv3 + MMFF, converted with Open Babel."),
        ("Ranking configuration",
         f"engine/config/ranking.yaml, hash {result.config_hash}."),
        ("Extraction configuration",
         f"engine/config/extraction.yaml, hash {e.config_hash}."),
    ]
    prov_rows = [[Paragraph("Item", s["cell_bold"]), Paragraph("Source", s["cell_bold"])]]
    prov_rows += [[Paragraph(k, s["cell"]), Paragraph(v, s["cell"])] for k, v in prov]
    story.append(_table(prov_rows, [44 * mm, 134 * mm]))

    if docking_meta:
        story.append(Spacer(1, 3 * mm))
        trows = [[Paragraph("Target", s["cell_bold"]), Paragraph("PDB", s["cell_bold"]),
                  Paragraph("Box ligand", s["cell_bold"]),
                  Paragraph("Box", s["cell_bold"])]]
        for gene, m in sorted(docking_meta.items()):
            box = m.get("box", {})
            trows.append([
                Paragraph(gene, s["cell"]), Paragraph(m.get("pdb_id", "-"), s["cell"]),
                Paragraph(str(m.get("ligand_code", "-")), s["cell"]),
                Paragraph(f"{box.get('center', ['-'] * 3)} / "
                          f"{box.get('size', ['-'] * 3)}", s["cell"]),
            ])
        story.append(_table(trows, [30 * mm, 24 * mm, 30 * mm, 94 * mm]))

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(16 * mm, 11 * mm, A4[0] - 16 * mm, 11 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(16 * mm, 7 * mm,
                          "PhytoLens - hypotheses for laboratory validation. "
                          "Not a medical device. Not for clinical decisions.")
        canvas.drawRightString(A4[0] - 16 * mm, 7 * mm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render a PhytoLens PDF shortlist")
    ap.add_argument("--plant", required=True)
    ap.add_argument("--part", required=True)
    ap.add_argument("--solvent", default="ethanol")
    ap.add_argument("--condition", required=True)
    ap.add_argument("--dock", help="panel JSON from engine/scripts/run_panel.py")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--out", default=str(REPORTS_DIR / "shortlist.pdf"))
    args = ap.parse_args(argv)

    docking = None
    meta = None
    if args.dock:
        from engine.pipeline import docking as dk
        panel = dk.load_panel(args.dock)
        docking = dk.panel_affinities(panel)
        meta = panel.get("targets")

    result = rk.run(args.plant, args.part, args.solvent, args.condition,
                    docking_scores=docking)
    path = build_report(result, args.out, docking_meta=meta, top=args.top)
    print(f"written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
