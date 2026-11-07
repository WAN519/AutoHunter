"""Resume helpers used by the /tailor skill.

- dump:   print the resume's paragraphs verbatim, so Claude can quote them exactly
- render: apply a tailoring plan (JSON) to the original .docx, keeping its formatting
- letter: write a plain cover-letter .docx from JSON
- edits:  find resumes the user edited after /tailor generated them, as paragraph diffs,
          so the style skill can learn their preferences

Every render also saves a pristine copy at <folder>/.autohunter/<name>.generated.docx. The user
edits the visible .docx in place; comparing the two shows what they changed.
"""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path

from docx import Document
from docx.shared import Pt

from .docx_render.docx_inplace import render_tailored_docx
from .docx_render.page_estimate import estimate_pages, is_numbered


def dump(resume: Path) -> str:
    doc = Document(str(resume))
    lines = [f"# {resume.name}  (estimated pages: {estimate_pages(doc):.2f})",
             "# B = bullet paragraph. Quote text exactly as shown when editing."]
    for i, p in enumerate(doc.paragraphs):
        t = p.text.strip()
        if t:
            lines.append(f"[{i:03d}]{' B' if is_numbered(p) else '  '} {p.text}")
    return "\n".join(lines)


def render(resume: Path, plan_file: Path, out: Path) -> dict:
    """Plan JSON keys: replacements [{original_text, tailored_text}],
    title_replacements [{original_title, tailored_title, org}], relevant_skills [..],
    skill_renames [{from, to}], skill_additions [{skill, line}] (user-approved only),
    date_replacements [{line, from, to}] (graduation date only, from the user's settings),
    drop_texts [text | [texts dropped together]] (least relevant first),
    max_pages (1 or 2; default 1; old plans may say one_page)."""
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    res = render_tailored_docx(
        resume.read_bytes(),
        plan.get("replacements", []),
        plan.get("title_replacements", []),
        one_page=bool(plan.get("one_page", True)),
        max_pages=plan.get("max_pages"),
        drop_texts=plan.get("drop_texts", []),
        relevant_skills=plan.get("relevant_skills", []),
        skill_renames=plan.get("skill_renames", []),
        skill_additions=plan.get("skill_additions", []),
        date_replacements=plan.get("date_replacements", []),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(res.docx_bytes)
    pristine = generated_copy(out)
    pristine.parent.mkdir(exist_ok=True)
    pristine.write_bytes(res.docx_bytes)
    report = {
        "output": str(out), "replaced": res.replaced, "dropped": res.dropped,
        "estimated_pages": res.estimated_pages, "unmatched": res.unmatched,
    }
    pages = int(plan.get("max_pages") or 1)
    if res.estimated_pages and res.estimated_pages > pages:
        report["warning"] = f"still over {pages} page(s): add more drop_texts"
    return report


def generated_copy(out: Path) -> Path:
    return out.parent / ".autohunter" / f"{out.stem}.generated.docx"


def _paragraphs(path: Path) -> list[str]:
    return [p.text.strip() for p in Document(str(path)).paragraphs if p.text.strip()]


def diff(generated: Path, edited: Path) -> list[dict]:
    """Paragraph-level changes from `generated` to `edited`: changed / added / removed."""
    a, b = _paragraphs(generated), _paragraphs(edited)
    changes = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        before, after = a[i1:i2], b[j1:j2]
        if op == "replace" and len(before) == len(after):
            changes += [{"kind": "changed", "before": x, "after": y} for x, y in zip(before, after)]
        else:
            changes += [{"kind": "removed", "before": x} for x in before]
            changes += [{"kind": "added", "after": y} for y in after]
    return changes


def _text_hash(path: Path) -> str:
    # Hash the text, not the bytes: Word rewrites the file on every save.
    return hashlib.sha256("\n".join(_paragraphs(path)).encode("utf-8")).hexdigest()[:16]


def edits(applications: Path, ack: bool = False) -> list[dict]:
    """Resumes under `applications/*/` whose text differs from their generated copy and that
    haven't been learned from yet. With ack=True, record them as learned instead of reporting."""
    found = []
    for pristine in sorted(applications.glob("*/.autohunter/*.generated.docx")):
        folder = pristine.parent.parent
        edited = folder / pristine.name.replace(".generated.docx", ".docx")
        if not edited.exists():
            continue
        h = _text_hash(edited)
        if h == _text_hash(pristine):
            continue
        state_file = pristine.parent / "learned.json"
        state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
        if state.get(edited.name) == h:
            continue
        if ack:
            state[edited.name] = h
            state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        found.append({"folder": folder.name, "file": edited.name,
                      "changes": diff(pristine, edited)})
    return found


def letter(spec_file: Path, out: Path) -> str:
    """Spec JSON: {name, contact_line, date, greeting, opener, body_paragraphs[], closer, signoff}."""
    s = json.loads(spec_file.read_text(encoding="utf-8"))
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name, style.font.size = "Calibri", Pt(11)
    head = doc.add_paragraph()
    head.add_run(s.get("name", "")).bold = True
    if s.get("contact_line"):
        doc.add_paragraph(s["contact_line"])
    for key in ("date", "greeting", "opener"):
        if s.get(key):
            doc.add_paragraph(s[key])
    for para in s.get("body_paragraphs", []):
        doc.add_paragraph(para)
    for key in ("closer", "signoff"):
        if s.get(key):
            doc.add_paragraph(s[key])
    doc.add_paragraph(s.get("name", ""))
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return str(out)
