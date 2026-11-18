"""PDF report tests: renders, contains the caveats, and is reproducible."""
from __future__ import annotations

from pypdf import PdfReader

from engine.pipeline import ranking as rk
from engine.report import CAVEATS, build_report


def text_of(path):
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages), len(reader.pages)


def _result():
    return rk.run("Curcuma longa", "rhizome", "ethanol", "colitis", top=6)


def test_report_is_a_pdf_with_content(tmp_path):
    path = build_report(_result(), tmp_path / "shortlist.pdf", top=6)
    data = path.read_bytes()
    assert data.startswith(b"%PDF")
    assert data.rstrip().endswith(b"%%EOF")
    assert len(data) > 4_000

    text, pages = text_of(path)
    assert pages >= 2, "caveats belong on their own page"
    assert "Limitations and caveats" in text
    assert "Provenance appendix" in text
    assert "DATA_LICENSE.md" in text
    assert "Curcuma longa" in text


def test_report_content_is_reproducible(tmp_path):
    """Same inputs -> same text. PDF object ids/timestamps are not asserted."""
    a = build_report(_result(), tmp_path / "a.pdf", top=6)
    b = build_report(_result(), tmp_path / "b.pdf", top=6)
    assert text_of(a)[0] == text_of(b)[0]


def test_caveats_include_the_required_claims():
    text = " ".join(CAVEATS).lower()
    assert "hypothes" in text
    assert "not evidence" in text
    assert "medical advice" in text
    assert "imppat" in text
    assert "calibrat" not in text  # no invented validation claim


def test_report_discloses_partial_docking(tmp_path):
    base = rk.run("Curcuma longa", "rhizome", "ethanol", "colitis", top=5)
    first = base.ranked[0].compound.id
    partial = rk.run("Curcuma longa", "rhizome", "ethanol", "colitis", top=5,
                     docking_scores={first: {"PTGS2": -8.0}})
    assert partial.summary()["docking"]["partial"] is True
    path = build_report(partial, tmp_path / "partial.pdf", top=5)
    text, _ = text_of(path)
    assert "Partial docking coverage" in text


def test_report_handles_pending_docking(tmp_path):
    result = _result()
    assert result.docking_pending is True
    path = build_report(result, tmp_path / "pending.pdf", top=3)
    assert path.stat().st_size > 4_000
    assert "Docking has not run" in text_of(path)[0]
