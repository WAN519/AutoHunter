"""In-place .docx editing: swap tailored bullet text into the user's original
resume, preserving all formatting.

The onboarding pipeline keeps only extracted text, so a generated resume can't
reproduce the user's layout. Instead we take their original .docx and replace
just the paragraphs whose text matches a tailored bullet's source — every font,
margin, heading, and bullet glyph is left untouched.
"""
from __future__ import annotations

import io
import re
from collections.abc import Iterator
from dataclasses import dataclass

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Emu, Inches
from docx.text.paragraph import Paragraph

from .page_estimate import FITS_ONE_PAGE, estimate_pages, is_numbered, left_indent_pt
from .awards_compact import drop_repeated_inline_awards, merge_awards_section
from .skills_filter import filter_skill_lines, rename_and_add

_WS = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _iter_paragraphs(doc) -> Iterator[Paragraph]:
    """All paragraphs in the document body and inside any tables."""
    yield from doc.paragraphs
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs


def _set_paragraph_text(para: Paragraph, text: str) -> None:
    """Replace a paragraph's text, keeping its first run's character formatting.

    Intra-paragraph formatting (e.g. a single bolded word) is not preserved —
    the whole bullet takes the first run's style. Paragraph-level formatting
    (style, bullet glyph, indentation, spacing) is fully preserved.
    """
    if not para.runs:
        para.add_run(text)
        return
    para.runs[0].text = text
    for run in para.runs[1:]:
        run.text = ""


@dataclass
class RenderResult:
    docx_bytes: bytes
    replaced: int
    unmatched: list[str]
    dropped: int = 0
    estimated_pages: float | None = None


# One-page mode never tightens margins beyond these.
_COMPACT_TOP_BOTTOM = Inches(0.5)
_COMPACT_LEFT_RIGHT = Inches(0.7)


def _compact_margins(doc) -> None:
    """Shrink margins to the compact minimum, moving right-aligned tab stops
    that sat on the old right margin (dates in header rows) to the new one."""
    section = doc.sections[0]
    old_width = Emu(section.page_width - section.left_margin - section.right_margin)
    section.top_margin = min(section.top_margin, _COMPACT_TOP_BOTTOM)
    section.bottom_margin = min(section.bottom_margin, _COMPACT_TOP_BOTTOM)
    section.left_margin = min(section.left_margin, _COMPACT_LEFT_RIGHT)
    section.right_margin = min(section.right_margin, _COMPACT_LEFT_RIGHT)
    new_width = Emu(section.page_width - section.left_margin - section.right_margin)
    old_twips, new_twips = str(old_width.twips), str(new_width.twips)
    for tab in doc.element.body.iter(qn("w:tab")):
        if tab.get(qn("w:val")) == "right" and tab.get(qn("w:pos")) == old_twips:
            tab.set(qn("w:pos"), new_twips)


def _is_continuation(para: Paragraph) -> bool:
    """An indented, un-numbered, untabbed line hanging under a bullet (e.g. an
    "Award: ..." line) belongs to that bullet and goes when it goes."""
    if is_numbered(para):
        return False
    indent = para.paragraph_format.left_indent
    return bool(para.text.strip()) and "\t" not in para.text and bool(indent and indent > 0)


def _is_child_of(para: Paragraph, header: Paragraph) -> bool:
    return is_numbered(para) and left_indent_pt(para) > left_indent_pt(header)


def _group_headers(doc) -> list[Paragraph]:
    """Bullets that head a group of deeper bullets (project / sub-project titles)."""
    paras = doc.paragraphs
    return [
        p for p, nxt in zip(paras, paras[1:])
        if is_numbered(p) and _is_child_of(nxt, p)
    ]


def _prune_orphan_headers(doc, headers: list[Paragraph]) -> None:
    """Remove group headers whose child bullets have all been dropped."""
    for header in headers:
        if header._p.getparent() is None:
            continue
        nxt = header._p.getnext()
        if nxt is None or nxt.tag != qn("w:p") or not _is_child_of(
            Paragraph(nxt, header._parent), header
        ):
            _remove_paragraph(header)


def _remove_paragraph(para: Paragraph) -> None:
    para._p.getparent().remove(para._p)


def _drop_text(doc, text: str) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    key = _normalize(text)
    paras = doc.paragraphs
    for i, para in enumerate(paras):
        if _normalize(para.text) == key:
            following = paras[i + 1] if i + 1 < len(paras) else None
            _remove_paragraph(para)
            if following is not None and _is_continuation(following):
                _remove_paragraph(following)
            return True
    return False


def page_limit(max_pages: int) -> float:
    """Estimate threshold for `max_pages` (same safety margin as one page)."""
    return max_pages - (1 - FITS_ONE_PAGE)


def fit_to_one_page(doc, drop_texts: list, max_pages: int = 1) -> tuple[int, float]:
    """Make `doc` fit `max_pages` (default one): compact margins (one page only), fold AWARDS
    into one line, drop inline award lines the AWARDS section repeats, then remove entries in
    `drop_texts` order (least relevant first) until the estimate fits.

    An entry is a paragraph's text, or a list of texts removed together as one unit. Use a list
    to drop a whole job: its bullets, then its header line, so no orphan header is left behind.
    A project / sub-project title is removed once all its bullets are gone.
    Returns (paragraphs dropped, final estimated pages). If the list runs out first, the result
    is still too long and the caller should warn.
    """
    limit = page_limit(max_pages)
    if estimate_pages(doc) <= limit:
        return 0, estimate_pages(doc)
    if max_pages == 1:
        _compact_margins(doc)
    if estimate_pages(doc) > limit:
        merge_awards_section(doc)
    if estimate_pages(doc) > limit:
        drop_repeated_inline_awards(doc)
    headers = _group_headers(doc)
    dropped = 0
    for entry in drop_texts:
        if estimate_pages(doc) <= limit:
            break
        for text in entry if isinstance(entry, list) else [entry]:
            if _drop_text(doc, text):
                dropped += 1
        _prune_orphan_headers(doc, headers)
    return dropped, estimate_pages(doc)


def _replace_title(para: Paragraph, original: str, tailored: str, org: str) -> bool:
    """Swap a job title at the start of a header line, leaving the rest intact.

    Header lines are usually "<title><tab><org><tab><dates>" across several
    runs, so the paragraph is never rewritten wholesale — only the run that
    contains the title is edited (python-docx keeps "\\t" as a real tab). The
    line must start with the title and, when given, mention the org, so the
    same title at two employers is only changed on the approved one. A title
    split across runs is not handled and is reported as unmatched.
    """
    text = _normalize(para.text)
    if not text.startswith(_normalize(original)):
        return False
    if org and _normalize(org) not in text:
        return False
    for run in para.runs:
        if original in run.text:
            run.text = run.text.replace(original, tailored, 1)
            return True
    return False


def _replace_across_runs(para: Paragraph, src: str, dst: str) -> bool:
    """Replace `src` in a paragraph even when Word split it over several runs ("Dec" / " " /
    "2027"). The new text goes into the run where the match starts, so it keeps that formatting."""
    runs = para.runs
    full = "".join(r.text for r in runs)
    i = full.find(src)
    if i < 0:
        return False
    j, pos = i + len(src), 0
    placed = False
    for r in runs:
        start, end = pos, pos + len(r.text)
        pos = end
        if end <= i or start >= j:
            continue
        keep_head = r.text[: max(i - start, 0)]
        keep_tail = r.text[max(j - start, 0):] if end > j else ""
        r.text = keep_head + (dst if not placed else "") + keep_tail
        placed = True
    return True


def replace_dates(doc, items: list[dict]) -> list[str]:
    """Swap the graduation date in the paragraph that contains `line`, keeping formatting. Only for
    the graduation date, which the user sets per job type. Returns entries that matched nothing."""
    missed = []
    for it in items or []:
        line, src, dst = it.get("line", ""), it.get("from", ""), it.get("to", "")
        if not (isinstance(src, str) and isinstance(dst, str) and src and dst) or src == dst:
            continue
        hit = False
        for para in _iter_paragraphs(doc):
            if (not line or line in para.text) and _replace_across_runs(para, src, dst):
                hit = True
        if not hit:
            missed.append(f"date: {src} in {line or 'any line'}")
    return missed


def render_tailored_docx(
    docx_bytes: bytes,
    replacements: list[dict],
    title_replacements: list[dict] | None = None,
    one_page: bool = False,
    max_pages: int | None = None,
    drop_texts: list[str] | None = None,
    relevant_skills: list[str] | None = None,
    skill_renames: list[dict] | None = None,
    skill_additions: list[dict] | None = None,
    date_replacements: list[dict] | None = None,
) -> RenderResult:
    """Apply {original_text -> tailored_text} swaps to the original .docx.

    Only paragraphs whose normalized text equals a replacement's normalized
    `original_text` are changed. No-op replacements (tailored == original),
    malformed entries (non-string / missing fields), and unmatched originals
    are skipped; unmatched originals are reported so the caller can surface a
    warning. The rest of the document is untouched.

    `title_replacements` ({original_title, tailored_title, org?}) are applied
    to job-title header lines via `_replace_title`, one line per entry.

    `relevant_skills` trims the SKILLS section to JD-relevant items before
    any page fitting, so skills give way before projects do.

    `one_page` runs `fit_to_one_page` last, after all text swaps, so the
    estimate sees the final wording. `drop_texts` are original bullet texts,
    least relevant first.
    """
    by_original: dict[str, str] = {}
    for r in replacements:
        original_raw = r.get("original_text")
        tailored = r.get("tailored_text")
        if not isinstance(original_raw, str) or not isinstance(tailored, str):
            continue
        original = _normalize(original_raw)
        if original and _normalize(tailored) != original:
            by_original[original] = tailored

    doc = Document(io.BytesIO(docx_bytes))
    replaced = 0
    matched: set[str] = set()
    for para in _iter_paragraphs(doc):
        key = _normalize(para.text)
        if key in by_original:
            _set_paragraph_text(para, by_original[key])
            matched.add(key)
            replaced += 1

    unmatched_titles: list[str] = []
    for t in title_replacements or []:
        original = t.get("original_title")
        tailored = t.get("tailored_title")
        org = t.get("org") or ""
        if not isinstance(original, str) or not isinstance(tailored, str):
            continue
        if not original.strip() or original == tailored or not isinstance(org, str):
            continue
        if any(_replace_title(p, original, tailored, org) for p in _iter_paragraphs(doc)):
            replaced += 1
        else:
            unmatched_titles.append(original)

    # Renamed / user-approved skills must survive the relevance filter that follows.
    date_missed = replace_dates(doc, date_replacements or [])
    skill_names, skill_missed = rename_and_add(doc, skill_renames or [], skill_additions or [])
    keep = list(relevant_skills or [])
    if keep:
        keep += skill_names
    filter_skill_lines(doc, keep)

    dropped, estimated = 0, None
    if one_page or max_pages:
        dropped, estimated = fit_to_one_page(doc, drop_texts or [], max_pages or 1)

    out = io.BytesIO()
    doc.save(out)
    unmatched = [orig for orig in by_original if orig not in matched]
    unmatched.extend(unmatched_titles)
    unmatched.extend(f"skill: {s}" for s in skill_missed)
    unmatched.extend(date_missed)
    return RenderResult(
        docx_bytes=out.getvalue(),
        replaced=replaced,
        unmatched=unmatched,
        dropped=dropped,
        estimated_pages=estimated,
    )