"""Rough page-count estimate for a .docx, for the one-page resume mode.

python-docx has no layout engine, so this models each paragraph as
`space_before + lines * line_height + space_after`, where `lines` comes from
character count against the usable line width. Good enough to decide "does
this still spill onto page 2?" for single-column resumes; not a renderer.
Calibrated against Microsoft Word page counts on real resumes.
"""
from __future__ import annotations

import math

from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.text.paragraph import Paragraph

# Average glyph width as a fraction of font size (Calibri-like body text).
_CHAR_WIDTH_EM = 0.41
# Single line spacing as a multiple of font size.
_LINE_HEIGHT_EM = 1.22
_DEFAULT_FONT_PT = 11.0
# Fit threshold, set from Word page counts on real resumes: estimates of
# 0.966 and 0.971 fit on one page, 0.986 spilled one line onto page 2.
FITS_ONE_PAGE = 0.975


def _style_chain(para: Paragraph):
    style = para.style
    while style is not None:
        yield style
        style = style.base_style


def _font_pt(para: Paragraph) -> float:
    sizes = [r.font.size.pt for r in para.runs if r.font.size is not None and r.text.strip()]
    if sizes:
        return max(sizes)
    for style in _style_chain(para):
        if style.font.size is not None:
            return style.font.size.pt
    return _DEFAULT_FONT_PT


def _spacing_pt(para: Paragraph, attr: str) -> float:
    value = getattr(para.paragraph_format, attr)
    if value is None:
        for style in _style_chain(para):
            value = getattr(style.paragraph_format, attr)
            if value is not None:
                break
    return value.pt if value is not None else 0.0


def is_numbered(para: Paragraph) -> bool:
    """Bulleted/numbered directly (Word, Google Docs) or via a list style."""
    ppr = para._p.pPr
    if ppr is not None and ppr.numPr is not None:
        return True
    return any(
        s.element.pPr is not None and s.element.pPr.numPr is not None
        for s in _style_chain(para)
    )


def left_indent_pt(para: Paragraph) -> float:
    ind = para.paragraph_format.left_indent
    if ind is not None:
        return max(ind.pt, 0.0)
    # List items without a direct indent inherit roughly 0.5" from numbering.
    return 36.0 if is_numbered(para) else 0.0


def _contextual_spacing(para: Paragraph) -> bool:
    """Word drops before/after spacing between list items whose style sets
    `contextualSpacing` (e.g. "List Paragraph"); approximated as always."""
    for style in _style_chain(para):
        ppr = style.element.pPr
        if ppr is not None and ppr.find(qn("w:contextualSpacing")) is not None:
            return True
    return False


def paragraph_height_pt(para: Paragraph, text_width_pt: float) -> float:
    font_pt = _font_pt(para)
    text = para.text
    if "\t" in text:
        lines = 1  # tab-aligned header rows ("Title<tab>Org<tab>Dates")
    else:
        width = max(text_width_pt - left_indent_pt(para), text_width_pt * 0.5)
        per_line = max(int(width / (font_pt * _CHAR_WIDTH_EM)), 1)
        lines = max(math.ceil(len(text) / per_line), 1)
    body = lines * font_pt * _LINE_HEIGHT_EM
    if _contextual_spacing(para):
        return body
    return _spacing_pt(para, "space_before") + body + _spacing_pt(para, "space_after")


def estimate_pages(doc: DocxDocument) -> float:
    section = doc.sections[0]
    usable_h = (section.page_height - section.top_margin - section.bottom_margin) / Pt(1)
    text_w = (section.page_width - section.left_margin - section.right_margin) / Pt(1)
    total = sum(paragraph_height_pt(p, text_w) for p in doc.paragraphs)
    return total / usable_h
