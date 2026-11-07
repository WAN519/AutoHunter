"""One-page mode: make the AWARDS section take one line.

1. Merge the award lines under the AWARDS heading into one paragraph joined
   by " · ", keeping each line's runs (and so its bold/italic). When every
   line ends with the same ", <Org>", only the last one keeps it.
2. Remove "Award: ..." lines hanging under bullets whose awards all appear in
   the AWARDS section — the section already says it. Lines marking an
   individual award stay: those are meant to be seen next to the work.
"""
from __future__ import annotations

import copy
import re

from docx.text.paragraph import Paragraph
from docx.text.run import Run

from .skills_filter import is_heading

_AWARDS_HEADING = re.compile(r"AWARD|HONOR", re.IGNORECASE)


def _section_lines(doc) -> list[Paragraph]:
    lines: list[Paragraph] = []
    inside = False
    for para in doc.paragraphs:
        if is_heading(para):
            if inside:
                break
            inside = bool(_AWARDS_HEADING.search(para.text))
            continue
        if inside and para.text.strip():
            lines.append(para)
    return lines


def _last_text_run(para: Paragraph):
    runs = [r for r in para.runs if r.text.strip()]
    return runs[-1] if runs else None


def _strip_common_suffix(lines: list[Paragraph]) -> None:
    """Drop a shared trailing ", Org" from every line but the last."""
    suffixes = set()
    for line in lines:
        m = re.search(r",\s*[^,]+$", line.text.strip())
        if not m:
            return
        suffixes.add(m.group(0).strip())
    if len(suffixes) != 1:
        return
    suffix = suffixes.pop()
    for line in lines[:-1]:
        run = _last_text_run(line)
        if run is None or not run.text.rstrip().endswith(suffix):
            return  # suffix split across runs; leave the lines as they are
    for line in lines[:-1]:
        run = _last_text_run(line)
        run.text = run.text.rstrip()[: -len(suffix)]


def _merge_lines(lines: list[Paragraph]) -> None:
    first = lines[0]
    for line in lines[1:]:
        # Separator takes the formatting of the text it follows (not bold).
        sep = copy.deepcopy((_last_text_run(first) or first.runs[-1])._r)
        first._p.append(sep)
        Run(sep, first).text = " · "
        for run in line.runs:
            first._p.append(copy.deepcopy(run._r))
        line._p.getparent().remove(line._p)
    for run in first.runs:  # tab-aligned lines would push text apart once joined
        run.text = run.text.replace("\t", "")


def drop_repeated_inline_awards(doc) -> int:
    lines = _section_lines(doc)
    if not lines:
        return 0
    removed = 0
    haystack = " ".join(l.text for l in lines).lower()
    for para in list(doc.paragraphs):
        label, sep, names = para.text.partition(":")
        if not sep or "award" not in label.lower() or is_heading(para):
            continue
        if "individual" in label.lower():
            continue
        if para.paragraph_format.left_indent is None:
            continue  # only lines hanging under a bullet
        parts = [n.strip() for n in re.split(r"[·,;]", names) if n.strip()]
        if parts and all(p.lower() in haystack for p in parts):
            para._p.getparent().remove(para._p)
            removed += 1
    return removed


def merge_awards_section(doc) -> bool:
    """Fold the AWARDS lines into one. Return True if anything changed."""
    lines = _section_lines(doc)
    if len(lines) < 2:
        return False
    _strip_common_suffix(lines)
    _merge_lines(lines)
    return True
