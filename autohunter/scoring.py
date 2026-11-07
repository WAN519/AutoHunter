"""Keyword pre-filter: cheap, deterministic, no LLM. Claude Code does the real
fit scoring afterwards (see .claude/skills/hunt)."""
from __future__ import annotations

import re

from .config import title_rules, topic_groups
from .presets import NON_US_PLACES
from .sources import Job


def _has(text: str, kw: str) -> bool:
    # word-boundary match so "intern" doesn't hit "internal"/"international"
    return re.search(r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])", text) is not None


def is_internship(job: Job, intern_kw: list[str], exclude_kw: list[str]) -> bool:
    t = job.title.lower()
    if any(_has(t, k) for k in exclude_kw):
        return False
    if job.source.startswith("simplify"):
        return True  # the whole list is internships
    if any(_has(t, k) for k in intern_kw):
        return True
    # Part-time student roles (CPT-friendly) often aren't called "intern".
    if re.search(r"part[- ]time", t) and re.search(r"student|graduate|assistant|junior|entry|research", t):
        return True
    return job.extra.get("employmentType") == "Intern"


def location_ok(job: Job, cfg: dict) -> bool:
    loc = job.location.lower()
    if not loc:
        return True  # unknown: keep, let a human check
    hits = [k for k in cfg.get("locations_ok", []) if k in loc]
    if not hits:
        return False
    # "Remote in Canada" matches "remote" but isn't workable from the US.
    if all(k == "remote" for k in hits):
        return not any(_has(loc, f) for f in NON_US_PLACES)
    return True


PART_TIME_PATTERNS = [
    r"part[- ]time",
    r"\b\d{1,2}\s*(?:-|–|to)?\s*\d{0,2}\s*hours?\s*(?:per|a|/)\s*week",
    r"during the (?:school|academic) year",
    r"flexible (?:schedule|hours)",
]


def part_time_signal(job: Job) -> str:
    """Return the evidence that a posting allows part-time work, or ''."""
    if job.extra.get("employmentType") == "PartTime":
        return "employmentType=PartTime"
    if "part" in job.extra.get("commitment", "").lower():
        return "commitment=" + job.extra["commitment"]
    if "part" in job.extra.get("timeType", "").lower():  # Workday
        return "timeType=" + job.extra["timeType"]
    if re.search(r"part[- ]time", job.title.lower()):
        return "title"
    text = job.description.lower()
    for p in PART_TIME_PATTERNS:
        for m in re.finditer(p, text):
            s = max(0, m.start() - 40)
            window = text[s:m.end() + 40]
            hours = [int(h) for h in re.findall(r"\d{1,2}", m.group())]
            # "full-time (40 hours/week)" is the opposite of what we want
            if "full-time" in window or "full time" in window or (hours and max(hours) >= 30):
                continue
            return "…" + window.strip() + "…"
    return ""


def score(job: Job, cfg: dict, groups: dict[str, list[str]], nonprofits: set[str]) -> dict:
    title = job.title.lower()
    body = f"{title} {job.description.lower()}"

    topics, pts = [], 0
    for topic, kws in groups.items():
        in_title = [k for k in kws if _has(title, k)]
        in_body = [k for k in kws if _has(body, k)]
        if in_title or in_body:
            topics.append(topic)
            pts += 25 if in_title else min(15, 3 * len(in_body))

    if job.remote and cfg.get("prefer_remote"):
        pts += 20
    home = (cfg.get("home_city") or "").lower()
    if home and home in job.location.lower():
        pts += 10

    def seasons(text: str) -> str:
        """Add "summer 2027" for "2027 Summer", "Summer '27", "Summer-2027" etc., so terms match either order."""
        out = [f"{a} 20{b[-2:]}" for a, b in re.findall(r"\b(summer|winter|spring|fall|autumn)[\s'’-]*((?:20)?\d\d)\b", text)]
        out += [f"{b} {a}" for a, b in re.findall(r"\b(20\d\d)[\s-]*(summer|winter|spring|fall|autumn)\b", text)]
        return text + " " + " ".join(out)

    when = seasons(f"{job.terms.lower()} {title} {job.description.lower()}")
    title_s = seasons(title)
    best = [k for k in cfg.get("terms_best", []) if k in when]
    bad = [k for k in cfg.get("terms_bad", []) if k in when]
    # An OK term that only appears inside a bad one ("2027" in "summer 2027") doesn't count.
    rest = when
    for k in bad:
        rest = rest.replace(k, " ")
    ok = [k for k in cfg.get("terms_ok", []) if k in rest and k not in best]
    # The title is what the posting is: "2027 Summer Intern" stays a summer role even if the body
    # mentions co-ops elsewhere.
    title_bad = [k for k in bad if k in title_s]
    title_best = [k for k in cfg.get("terms_best", []) if k in title_s]
    if title_bad and not title_best:
        best = []
    if best:
        pts += 25
    elif ok:
        pts += 10
    if bad and not best:
        pts -= 30

    if job.company in nonprofits:
        pts += 5

    return {
        "score": pts,
        "topics": ", ".join(topics),
        "start_signal": ("BAD TERM? " + ", ".join(bad)) if bad and not best else ", ".join(best + ok),
        "nonprofit": job.company in nonprofits,
        "part_time": part_time_signal(job),
    }


def rank(jobs: list[Job], cfg: dict, nonprofits: set[str],
         part_time_only: bool = False) -> list[tuple[Job, dict]]:
    intern_kw, exclude_kw = title_rules(cfg)
    groups = topic_groups(cfg)
    skip_flags = set(cfg.get("skip_flags", []))
    seen: set[str] = set()
    out = []
    for j in jobs:
        # Same role is often listed several times (one link per req / location).
        dup_key = f"{j.company.lower()}|{j.title.lower()}|{j.location.lower()}"
        if not j.url or j.url in seen or dup_key in seen:
            continue
        if skip_flags & set(j.flags):
            continue
        if not (is_internship(j, intern_kw, exclude_kw) and location_ok(j, cfg)):
            continue
        s = score(j, cfg, groups, nonprofits)
        if not s["topics"]:
            continue
        if part_time_only and not s["part_time"]:
            continue
        seen.update((j.url, dup_key))
        out.append((j, s))
    out.sort(key=lambda x: x[1]["score"], reverse=True)
    return out
