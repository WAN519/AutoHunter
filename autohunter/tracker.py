"""The CSV tracker. Script-owned columns are refreshed every run; user/Claude-owned
columns (status, fit_*, notes, ...) are never overwritten by a hunt."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

SCRIPT_FIELDS = [
    "score", "company", "title", "location", "remote", "part_time", "terms", "topics",
    "start_signal", "flags", "nonprofit", "compensation", "posted", "source", "url",
]
OWNED_FIELDS = [
    "fit_score", "fit_notes", "status", "applied_on", "contact", "folder", "notes", "first_seen",
]
FIELDS = ["id"] + SCRIPT_FIELDS + OWNED_FIELDS

# utf-8-sig so Excel on Windows shows non-ASCII characters correctly
ENCODING = "utf-8-sig"


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding=ENCODING) as f:
        return list(csv.DictReader(f))


def save(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding=ENCODING) as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)  # atomic: a crash never leaves a half-written tracker


def merge(path: Path, fresh: list[dict]) -> tuple[list[dict], int]:
    """Merge freshly-scraped rows into the tracker. Returns (rows, new_count)."""
    old = {r["url"]: r for r in load(path)}
    next_id = max((int(r["id"]) for r in old.values() if r.get("id", "").isdigit()), default=0) + 1
    today = date.today().isoformat()
    rows, seen, new = [], set(), 0
    for r in fresh:
        seen.add(r["url"])
        prev = old.get(r["url"])
        if prev:
            r["id"] = prev["id"]
            for k in OWNED_FIELDS:
                r[k] = prev.get(k, "")
        else:
            r["id"] = str(next_id)
            next_id += 1
            r["status"], r["first_seen"] = "NEW", today
            new += 1
        rows.append(r)
    # Keep anything the user touched even if the posting disappeared.
    for url, prev in old.items():
        if url in seen or prev.get("status") in ("", "NEW"):
            continue
        if "[posting gone?]" not in prev.get("notes", ""):
            prev["notes"] = (prev.get("notes", "") + " [posting gone?]").strip()
        rows.append(prev)
    return rows, new


def add_manual(path: Path, row: dict) -> str:
    """Add a job the user handed over (hotkey / "fill this"). Returns its id. Status QUEUED, so
    later hunts keep it even though no board lists it."""
    rows = load(path)
    for r in rows:
        if r.get("url") == row["url"]:
            return r["id"]
    next_id = max((int(r["id"]) for r in rows if r.get("id", "").isdigit()), default=0) + 1
    new = {k: "" for k in FIELDS}
    new.update({k: v for k, v in row.items() if k in FIELDS})
    new.update(id=str(next_id), status="QUEUED", first_seen=date.today().isoformat())
    save(path, rows + [new])
    return new["id"]


def update(path: Path, updates_file: Path) -> int:
    """Apply a JSON list of {"id" or "url": ..., field: value} to owned columns."""
    updates = json.loads(updates_file.read_text(encoding="utf-8"))
    rows = load(path)
    by_id = {r["id"]: r for r in rows}
    by_url = {r["url"]: r for r in rows}
    n = 0
    for u in updates:
        row = by_id.get(str(u.get("id", ""))) or by_url.get(u.get("url", ""))
        if not row:
            print(f"  ! no tracker row for {u.get('id') or u.get('url')}")
            continue
        for k, v in u.items():
            if k in OWNED_FIELDS:
                row[k] = str(v)
        n += 1
    save(path, rows)
    return n
