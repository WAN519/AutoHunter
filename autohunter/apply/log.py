"""Pending fills, the applied log, and duplicate checks.

me/output/pending.json   forms that are filled and waiting for the user to click Submit
me/output/applied.csv    one row per submitted application (Google Sheets sync comes later)
"""
from __future__ import annotations

import csv
import difflib
import json
import re
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from .. import tracker

APPLIED_FIELDS = ["applied_on", "company", "title", "source", "platform", "url", "resume", "cover_letter",
                  "snapshot", "resume_changes", "letter_points", "status", "follow_up", "contact", "notes",
                  "tracker_id", "folder"]


def _paths(me: Path):
    out = me / "output"
    out.mkdir(parents=True, exist_ok=True)
    return out / "pending.json", out / "applied.csv", out / "tracker.csv"


def load_pending(me: Path) -> list[dict]:
    p, _, _ = _paths(me)
    if not p.exists():
        return []
    items = json.loads(p.read_text(encoding="utf-8"))
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    return [i for i in items if i.get("started", "") >= cutoff]


def save_pending(me: Path, items: list[dict]) -> None:
    p, _, _ = _paths(me)
    p.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def add_pending(me: Path, entry: dict) -> None:
    items = [i for i in load_pending(me) if i["base"] != entry["base"]]
    save_pending(me, items + [entry])


def load_applied(me: Path) -> list[dict]:
    _, a, _ = _paths(me)
    if not a.exists():
        return []
    with a.open(newline="", encoding=tracker.ENCODING) as f:
        return list(csv.DictReader(f))


def _norm_title(t: str) -> str:
    t = re.sub(r"\(.*?\)|\b(intern(ship)?|co-?op|20\d\d|summer|winter|spring|fall)\b", " ", t.lower())
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def duplicates(me: Path, url: str, company: str, title: str, base: str) -> dict:
    """{'applied': [...], 'pending': [...], 'similar': [...], 'company_count': n}"""
    applied, pending = load_applied(me), load_pending(me)
    res = {"applied": [], "pending": [], "similar": [], "company_count": 0}
    for r in applied:
        same_co = company and r["company"].strip().lower() == company.strip().lower()
        if same_co:
            res["company_count"] += 1
        if r["url"] and (r["url"].rstrip("/") == url.rstrip("/") or r["url"].startswith(base)):
            res["applied"].append(r)
        elif same_co and title and difflib.SequenceMatcher(None, _norm_title(r["title"]), _norm_title(title)).ratio() > 0.85:
            res["similar"].append(r)
    res["pending"] = [p for p in pending if p["base"] == base]
    return res


def record(me: Path, entry: dict, snapshot: str = "") -> dict:
    """Append a submitted application to applied.csv and mark the tracker row APPLIED."""
    _, a, t = _paths(me)
    folder = Path(entry.get("folder", "")) if entry.get("folder") else None
    summary = {}
    if folder and (folder / "summary.json").exists():
        summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    row = {
        "applied_on": date.today().isoformat(), "company": entry.get("company", ""), "title": entry.get("title", ""),
        "source": entry.get("source", "AutoHunter"), "platform": entry.get("platform", ""), "url": entry.get("url", ""),
        "resume": entry.get("resume", ""), "cover_letter": entry.get("letter", ""), "snapshot": snapshot,
        "resume_changes": (summary.get("resume") or {}).get("oneline", ""),
        "letter_points": (summary.get("cover_letter") or {}).get("oneline", "") if summary.get("cover_letter") else "",
        "status": "Applied", "follow_up": (date.today() + timedelta(days=14)).isoformat(),
        "contact": "", "notes": "", "tracker_id": entry.get("tracker_id", ""), "folder": folder.name if folder else "",
    }
    new = not a.exists()
    with a.open("a", newline="", encoding=tracker.ENCODING) as f:
        w = csv.DictWriter(f, fieldnames=APPLIED_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    if entry.get("tracker_id") and t.exists():
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump([{"id": entry["tracker_id"], "status": "APPLIED", "applied_on": row["applied_on"]}], tmp)
        tracker.update(t, Path(tmp.name))
        Path(tmp.name).unlink(missing_ok=True)
    return row
