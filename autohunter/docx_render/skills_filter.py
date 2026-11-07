"""Trim the resume's SKILLS section to the skills a JD actually needs.

Skills lines look like "Label: item, item, item." with the label in its own
(usually bold) run. Each line keeps only items matching a relevant skill;
a line left with no items is removed. Lines that list credentials rather
than skills (certifications, awards, spoken languages) are left alone.
"""
from __future__ import annotations

import re

from docx.text.paragraph import Paragraph

_EXEMPT_LABEL = re.compile(r"certif|award|honou?r|spoken", re.IGNORECASE)
# Split on commas that aren't inside parentheses: "Linux (WSL2), Docker".
_ITEM_SPLIT = re.compile(r",\s*(?![^()]*\))")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+#]+", " ", s.lower()).strip()


def is_heading(para: Paragraph) -> bool:
    if para.style is not None and para.style.name.lower().startswith("heading"):
        return True
    text = para.text.strip()
    return bool(text) and text.isupper() and len(text.split()) <= 4


def _matches(item: str, terms: list[str]) -> bool:
    """Whole-word containment either way: "Claude" keeps "Claude API",
    "Computer Vision (YOLOv8)" is kept by "YOLOv8"; "R" never keeps "Jira"."""
    n = f" {_norm(item)} "
    return any(f" {t} " in n or n in f" {t} " for t in terms)


def _skills_lines(doc) -> list[Paragraph]:
    lines: list[Paragraph] = []
    in_skills = False
    for para in doc.paragraphs:
        if is_heading(para):
            in_skills = "SKILL" in para.text.upper()
            continue
        if in_skills and ":" in para.text:
            lines.append(para)
    return lines


def _set_items(para: Paragraph, label_len: int, items_text: str) -> None:
    """Keep the runs that make up the label; put `items_text` right after it."""
    consumed = 0
    placed = False
    for run in para.runs:
        start, end = consumed, consumed + len(run.text)
        consumed = end
        if end <= label_len:
            continue  # pure label run: keep as is
        if not placed:
            keep = run.text[: max(label_len - start, 0)]
            run.text = keep + items_text
            placed = True
        else:
            run.text = ""


def _split(para: Paragraph) -> tuple[str, list[str]]:
    head = re.match(r"[^:]*:\s*", para.text).group(0)
    rest = para.text[len(head):]
    return head, [i.strip() for i in _ITEM_SPLIT.split(rest.strip().rstrip(".")) if i.strip()]


def _write(para: Paragraph, head: str, items: list[str]) -> None:
    sep = "" if head[-1].isspace() else " "
    _set_items(para, len(head), sep + ", ".join(items) + ".")


def rename_and_add(doc, renames: list[dict], additions: list[dict]) -> tuple[list[str], list[str]]:
    """Apply user-approved skill edits before filtering.

    renames:   [{"from": "LLM Evaluation", "to": "Model Evaluation"}]: same skill, the JD's name.
               Matches a whole item, or an item's name before " (...)".
    additions: [{"skill": "Kubernetes", "line": "Tools"}]: only skills the user confirmed.
               `line` is the start of a skills-line label; falls back to the last skills line.
    Returns (names now present that came from these edits, entries that matched nothing).
    """
    present, missed = [], []
    lines = [p for p in _skills_lines(doc) if not _EXEMPT_LABEL.search(p.text.partition(":")[0])]
    for r in renames or []:
        src, dst = r.get("from"), r.get("to")
        if not (isinstance(src, str) and isinstance(dst, str) and src.strip() and dst.strip()):
            continue
        hit = False
        for para in lines:
            head, items = _split(para)
            new = []
            for item in items:
                base, paren, tail = item.partition(" (")
                if _norm(item) == _norm(src):
                    new.append(dst); hit = True
                elif paren and _norm(base) == _norm(src):
                    new.append(f"{dst} ({tail}"); hit = True
                else:
                    new.append(item)
            if new != items:
                _write(para, head, new)
        (present if hit else missed).append(dst if hit else src)
    for a in additions or []:
        skill, label = a.get("skill"), a.get("line") or ""
        if not (isinstance(skill, str) and skill.strip()) or not lines:
            continue
        target = next((p for p in lines if _norm(p.text.partition(":")[0]).startswith(_norm(label))
                       and label.strip()), lines[-1])
        head, items = _split(target)
        if not any(_norm(i) == _norm(skill) for i in items):
            _write(target, head, items + [skill])
        present.append(skill)
    return present, missed


def filter_skill_lines(doc, keep: list[str]) -> int:
    """Return how many skills lines were trimmed or removed. No-op if `keep`
    is empty, so a missing Tailor list never wipes the section."""
    terms = []
    for k in keep:
        if isinstance(k, str):
            terms.extend(_norm(part) for part in k.split("/"))
    terms = [t for t in terms if t]
    if not terms:
        return 0

    changed = 0
    for para in _skills_lines(doc):
        label, _, rest = para.text.partition(":")
        if _EXEMPT_LABEL.search(label):
            continue
        # "Label: " — the space after the colon often lives in the bold label run.
        head = re.match(r"[^:]*:\s*", para.text).group(0)
        items = [i.strip() for i in _ITEM_SPLIT.split(rest.strip().rstrip(".")) if i.strip()]
        kept = [i for i in items if _matches(i, terms)]
        if len(kept) == len(items):
            continue
        changed += 1
        if not kept:
            para._p.getparent().remove(para._p)
        else:
            sep = "" if head[-1].isspace() else " "
            _set_items(para, len(head), sep + ", ".join(kept) + ".")
    return changed
