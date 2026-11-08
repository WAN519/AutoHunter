"""Outreach leads: companies to write to, not postings to apply to.

  hn   part-time / intern / co-op mentions in the latest HN "Who is hiring?" thread
  yc   small, recent, hiring YC startups whose description matches the user's role keywords;
       the best bet for a part-time or unpaid CPT internship with real project work

Both go to me/output/leads.csv. Columns the user / Claude own (check, status, notes) survive re-runs.
"""
from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

from . import tracker
from .config import topic_groups
from .scoring import _has, location_ok
from .sources import Job

FIELDS = ["source", "kind", "segment", "fit", "company", "headline", "location", "remote", "team_size",
          "batch", "website", "apply_link", "hn_link", "yc_link", "snippet", "thread",
          "check", "first_seen", "status", "notes"]
OWNED = ["check", "first_seen", "status", "notes"]

YC_DEFAULTS = {"min_team": 2, "max_team": 15, "min_batch_year": 2023}

# Agent companies, split by what an intern would actually work on.
AGENT_RE = re.compile(r"\bagent(s|ic)?\b|multi-agent", re.I)
SEGMENTS = [
    ("agent eval / observability", r"\bevals?\b|evaluation|observab|guardrail|red[- ]team|tracing|"
                                   r"(production|agent) monitoring"),
    ("agent infra / framework", r"framework|\bsdk\b|infrastructure|orchestrat|runtime|sandbox|browser|developer tool|api\b"),
    ("vertical agent", r"customer|sales|legal|health|medical|finance|accounting|insurance|support|recruit|"
                       r"real estate|logistics|compliance|procurement"),
]


def _key(r: dict) -> str:
    return r.get("hn_link") or r.get("yc_link") or ""


def _segment(text: str, topics: list[str]) -> str:
    if AGENT_RE.search(text):
        for name, pat in SEGMENTS:
            if re.search(pat, text, re.I):
                return name
        return "agent (other)"
    return ", ".join(topics[:2])


def _topic_hits(text: str, groups: dict[str, list[str]]) -> tuple[int, list[str]]:
    low = text.lower()
    hits, topics = 0, []
    for name, kws in groups.items():
        n = sum(1 for k in kws if _has(low, k))
        if n:
            hits += n
            topics.append(name)
    return hits, topics


def yc_leads(cfg: dict) -> list[dict]:
    from .sources import fetch_yc_hiring
    opts = {**YC_DEFAULTS, **(cfg.get("outreach", {}).get("yc") or {})}
    groups = topic_groups(cfg)
    home = (cfg.get("home_city") or "").lower()
    rows = []
    for c in fetch_yc_hiring():
        if not (opts["min_team"] <= c["team_size"] <= opts["max_team"]):
            continue
        if c["batch_year"] and c["batch_year"] < opts["min_batch_year"]:
            continue
        where = "; ".join(x for x in (c["location"], c["regions"]) if x)
        if where and not location_ok(Job("", "", where, "", "", "yc"), cfg):
            continue
        head = f"{c['one_liner']} {c['tags']}"
        text = f"{head} {c['description']}"
        head_hits, _ = _topic_hits(head, groups)
        hits, topics = _topic_hits(text, groups)
        if not head_hits and hits < 2:  # one stray keyword in a long description isn't a match
            continue
        remote = "remote" in where.lower()
        fit = min(hits, 8) * 3 + head_hits * 4 + (5 if remote else 0) + (5 if home and home in where.lower() else 0) \
            + (3 if c["team_size"] <= 10 else 0) + (3 if c["batch_year"] >= date.today().year - 1 else 0)
        rows.append({
            "source": "yc", "kind": "startup (no posting)", "segment": _segment(text, topics), "fit": fit,
            "company": c["company"], "headline": c["one_liner"][:160], "location": c["location"][:80],
            "remote": "yes" if remote else "", "team_size": c["team_size"], "batch": c["batch"],
            "website": c["website"], "yc_link": c["yc_link"], "snippet": c["description"][:300].replace("\n", " "),
        })
    return rows


def hn_leads(cfg: dict) -> list[dict]:
    from .sources import fetch_hn
    groups = topic_groups(cfg)
    rows = []
    for j in fetch_hn():
        if j.location and not location_ok(j, cfg):
            continue
        text = j.description
        kind = ", ".join(k for k, pat in (("part-time", r"part[- ]time"), ("intern", r"\bintern(ship)?s?\b"),
                                           ("co-op", r"\bco-?op\b"), ("contract", r"\bcontract(or)?\b"))
                         if re.search(pat, text, re.I))
        m = re.search(r"part[- ]time|\bintern(ship)?s?\b|\bco-?op\b", text, re.I)
        snippet = text[max(0, m.start() - 120): m.end() + 160].replace("\n", " ") if m else text[:280]
        hits, topics = _topic_hits(text, groups)
        hn = j.url if "news.ycombinator.com" in j.url else ""
        rows.append({
            "source": "hn", "kind": kind, "segment": _segment(text, topics),
            "fit": min(hits, 8) * 3 + (10 if "part-time" in kind else 0) + (5 if j.remote else 0),
            "company": j.company, "headline": j.title, "location": j.location, "remote": "yes" if j.remote else "",
            "apply_link": j.extra.get("apply_url", ""), "hn_link": hn or j.url, "snippet": snippet.strip(),
            "thread": j.extra.get("thread", ""),
        })
    return rows


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding=tracker.ENCODING) as f:
        return list(csv.DictReader(f))


def refresh(me: Path, cfg: dict, sources: list[str]) -> tuple[list[dict], list[str]]:
    """Fetch the chosen sources, merge into leads.csv keeping owned columns. Returns (rows, errors)."""
    path = me / "output" / "leads.csv"
    old = {_key(r): r for r in load(path)}
    fresh, errors = [], []
    for name, fn in (("hn", hn_leads), ("yc", yc_leads)):
        if name not in sources:
            continue
        try:
            fresh += fn(cfg)
        except Exception as e:
            errors.append(f"{name}: {e}")
    today = date.today().isoformat()
    rows, seen = [], set()
    for r in fresh:
        k = _key(r)
        if not k or k in seen:
            continue
        seen.add(k)
        prev = old.get(k, {})
        for f in OWNED:
            r[f] = prev.get(f, "")
        r["first_seen"] = r["first_seen"] or today
        rows.append(r)
    # Keep leads the user worked on even if they dropped out of the source (or weren't refreshed).
    for k, prev in old.items():
        if k not in seen and (prev.get("status") or prev.get("source", "hn") not in sources):
            rows.append(prev)
    rows.sort(key=lambda r: (r.get("status") in ("skip", "SKIP"), -int(r.get("fit") or 0), r["company"].lower()))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding=tracker.ENCODING) as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return rows, errors


def update(me: Path, updates: list[dict]) -> int:
    """Set owned columns by company name (case-insensitive) or link: [{"company": ..., "check": ...}]."""
    path = me / "output" / "leads.csv"
    rows = load(path)
    n = 0
    for u in updates:
        for r in rows:
            if (u.get("link") and u["link"] in (r.get("hn_link"), r.get("yc_link"))) or \
                    (u.get("company") and u["company"].lower() == r["company"].lower()):
                for f in OWNED:
                    if f in u:
                        r[f] = str(u[f])
                n += 1
                break
    with path.open("w", newline="", encoding=tracker.ENCODING) as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return n
