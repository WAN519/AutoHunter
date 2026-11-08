"""Fetch postings from public sources:

- Greenhouse / Lever / Ashby public job-board APIs (what company career pages use)
- Workday career sites, through the public JSON search every Workday career page uses
  (`/wday/cxs/<tenant>/<site>/jobs`): intern / co-op postings only
- SmartRecruiters public posting API (intern-like titles)
- Hacker News "Who is hiring?" monthly thread (comments mentioning interns / co-ops / part-time)
- SimplifyJobs internship lists on GitHub (community-maintained, includes Workday roles)

No login, no LinkedIn, nothing whose terms forbid automated access (Jobright, Handshake).
"""
from __future__ import annotations

import html
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .presets import SIMPLIFY_FLAGS

UA = {"User-Agent": "AutoHunter/0.2 (student job search)"}

SIMPLIFY_URLS = {
    "summer": "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md",
    "off-season": "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README-Off-Season.md",
}


@dataclass
class Job:
    company: str
    title: str
    location: str
    url: str
    description: str
    source: str
    remote: bool = False
    posted: str = ""
    compensation: str = ""
    terms: str = ""
    flags: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _get_json(url: str):
    return json.loads(_get(url))


def _post_json(url: str, payload: dict):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={**UA, "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def strip_html(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<br\s*/?>|</p>|</li>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def _is_remote(*parts: str) -> bool:
    return any("remote" in (p or "").lower() for p in parts)


# ---------------------------------------------------------------- ATS boards

def fetch_greenhouse(token: str) -> list[Job]:
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    jobs = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        jobs.append(Job(
            company=token, title=j.get("title", ""), location=loc,
            url=j.get("absolute_url", ""), description=strip_html(j.get("content", "")),
            source="greenhouse", remote=_is_remote(loc, j.get("title", "")),
            posted=(j.get("updated_at") or "")[:10],
        ))
    return jobs


def fetch_lever(token: str) -> list[Job]:
    data = _get_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        loc = cats.get("location", "") or ", ".join(cats.get("allLocations") or [])
        desc = "\n".join([
            j.get("descriptionPlain", ""),
            "\n".join(strip_html(l.get("content", "")) for l in j.get("lists") or []),
            j.get("additionalPlain", ""),
        ])
        created = j.get("createdAt")
        posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if created else ""
        jobs.append(Job(
            company=token, title=j.get("text", ""), location=loc,
            url=j.get("hostedUrl", ""), description=desc, source="lever",
            remote=j.get("workplaceType") == "remote" or _is_remote(loc),
            posted=posted, extra={"commitment": cats.get("commitment", "")},
        ))
    return jobs


def fetch_ashby(token: str) -> list[Job]:
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true")
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        loc = "; ".join(l for l in locs if l)
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        jobs.append(Job(
            company=token, title=j.get("title", ""), location=loc,
            url=j.get("jobUrl", ""), description=j.get("descriptionPlain", "") or "",
            source="ashby",
            remote=bool(j.get("isRemote")) or j.get("workplaceType") == "Remote" or _is_remote(loc),
            posted=(j.get("publishedAt") or "")[:10], compensation=comp,
            extra={"employmentType": j.get("employmentType", "")},
        ))
    return jobs


_WD_INTERN = re.compile(r"\b(intern(ship)?s?|co-?op|apprentice)\b", re.I)


def fetch_workday(token: str, max_pages: int = 10) -> list[Job]:
    """token = "<tenant>.<wdN>/<site>", e.g. "nvidia.wd5/NVIDIAExternalCareerSite".

    Searches the site for "intern" and "co-op", keeps intern-like titles, then fetches each
    posting's description (needed to read start terms like "Spring 2027")."""
    host, site = token.split("/", 1)
    tenant = host.split(".")[0]
    base = f"https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
    found: dict[str, dict] = {}
    for query in ("intern", "co-op"):
        for page in range(max_pages):
            d = _post_json(f"{base}/jobs", {"appliedFacets": {}, "limit": 20, "offset": page * 20, "searchText": query})
            posts = d.get("jobPostings") or []
            for j in posts:
                if j.get("externalPath") and _WD_INTERN.search(j.get("title", "")):
                    found.setdefault(j["externalPath"], j)
            if len(posts) < 20 or (page + 1) * 20 >= (d.get("total") or 0):
                break

    def detail(item):
        path, j = item
        try:
            info = _get_json(f"{base}{path}").get("jobPostingInfo", {})
        except Exception:
            info = {}
        loc = info.get("location") or j.get("locationsText", "")
        extra_locs = info.get("additionalLocations") or []
        loc = "; ".join([loc] + [x for x in extra_locs if x])
        return Job(
            company=tenant, title=info.get("title") or j.get("title", ""), location=loc,
            url=f"https://{host}.myworkdayjobs.com/{site}{path}",
            description=strip_html(info.get("jobDescription", "")), source="workday",
            remote=_is_remote(loc, info.get("remoteType", "") or ""),
            posted=j.get("postedOn", "") or info.get("postedOn", ""),
            extra={"timeType": info.get("timeType", ""), "requisition": info.get("jobReqId", "")},
        )

    with ThreadPoolExecutor(6) as ex:
        return list(ex.map(detail, found.items()))


def fetch_smartrecruiters(token: str) -> list[Job]:
    """token = SmartRecruiters company id (jobs.smartrecruiters.com/<id>). Intern-like titles only."""
    base = f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
    posts, offset = [], 0
    while offset < 2000:
        d = _get_json(f"{base}?limit=100&offset={offset}")
        page = d.get("content") or []
        posts += [p for p in page if _WD_INTERN.search(p.get("name", ""))]
        offset += 100
        if len(page) < 100 or offset >= (d.get("totalFound") or 0):
            break

    def detail(p):
        try:
            info = _get_json(f"{base}/{p['id']}")
        except Exception:
            info = {}
        sections = (info.get("jobAd") or {}).get("sections") or {}
        text = "\n".join(strip_html((sections.get(k) or {}).get("text", ""))
                         for k in ("jobDescription", "qualifications", "additionalInformation"))
        loc = p.get("location") or {}
        where = ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country", "").upper()) if x)
        return Job(
            company=token, title=p.get("name", ""), location=where,
            url=info.get("postingUrl") or f"https://jobs.smartrecruiters.com/{token}/{p['id']}",
            description=text, source="smartrecruiters", remote=bool(loc.get("remote")) or _is_remote(where),
            posted=(p.get("releasedDate") or "")[:10],
            extra={"employmentType": "PartTime" if "part" in ((p.get("typeOfEmployment") or {}).get("label", "").lower()) else ""},
        )

    with ThreadPoolExecutor(6) as ex:
        return list(ex.map(detail, posts))


_HN_FIRST = re.compile(r"^(.*?)(?:<p>|\n|$)", re.S)


def fetch_hn(token: str = "whoishiring") -> list[Job]:
    """The latest "Ask HN: Who is hiring?" thread (official HN data via the public Algolia API).
    Keeps top-level comments that mention interns, co-ops or part-time work."""
    hits = _get_json("https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring"
                     "&query=%22who%20is%20hiring%22&hitsPerPage=5").get("hits", [])
    story = next((h for h in hits if "who is hiring" in h.get("title", "").lower()), None)
    if not story:
        return []
    thread = _get_json(f"https://hn.algolia.com/api/v1/items/{story['objectID']}")
    month = re.sub(r".*\((.*)\).*", r"\1", thread.get("title", ""))
    jobs = []
    for c in thread.get("children") or []:
        raw = c.get("text") or ""
        text = strip_html(raw)
        if not re.search(r"\b(intern(ship)?s?|co-?op|part[- ]time)\b", text, re.I):
            continue
        head = strip_html(_HN_FIRST.match(raw).group(1)).strip()
        parts = [x.strip() for x in head.split("|")]
        if len(parts) < 2:
            continue
        loc = next((x for x in parts[1:] if re.search(r"remote|onsite|on-site|hybrid|, [A-Z]{2}\b|usa|united states|sf|nyc|seattle", x, re.I)), "")
        roles = [x for x in parts[1:] if x != loc]
        title = next((x for x in roles if re.search(r"intern|co-?op|part[- ]time", x, re.I)), roles[0] if roles else "")
        if not re.search(r"intern|co-?op|part[- ]time", title, re.I):
            title = f"{title} (mentions internships)" if re.search(r"\bintern", text, re.I) else f"{title} (mentions part-time)"
        links = re.findall(r'href="([^"]+)"', raw)
        apply = next((html.unescape(u) for u in links if not re.search(r"news\.ycombinator|mailto:", u)), "")
        ats = re.search(r"greenhouse\.io|lever\.co|ashbyhq\.com|myworkdayjobs\.com", apply)
        jobs.append(Job(
            company=parts[0][:60], title=title[:120], location=loc[:80],
            url=apply if ats else f"https://news.ycombinator.com/item?id={c.get('id')}", description=text, source="hn",
            remote=_is_remote(head), posted=(c.get("created_at") or "")[:10],
            extra={"apply_url": apply, "thread": month},
        ))
    return jobs


YC_HIRING_URL = "https://yc-oss.github.io/api/companies/hiring.json"


def fetch_yc_hiring() -> list[dict]:
    """YC companies currently marked as hiring (community mirror of YC's public directory).
    Companies, not postings: used as outreach leads for small startups."""
    out = []
    for c in _get_json(YC_HIRING_URL):
        if c.get("status") != "Active":
            continue
        year = re.search(r"(20\d\d)", c.get("batch") or "")
        out.append({
            "company": c.get("name", ""), "one_liner": c.get("one_liner") or "",
            "description": c.get("long_description") or "",
            "tags": ", ".join((c.get("tags") or []) + (c.get("industries") or [])),
            "team_size": c.get("team_size") or 0, "batch": c.get("batch") or "",
            "batch_year": int(year.group(1)) if year else 0,
            "location": c.get("all_locations") or "", "regions": ", ".join(c.get("regions") or []),
            "website": c.get("website") or "",
            "yc_link": f"https://www.ycombinator.com/companies/{c.get('slug', '')}",
        })
    return out


ATS_FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby,
                "workday": fetch_workday, "smartrecruiters": fetch_smartrecruiters, "hn": fetch_hn}


# ---------------------------------------------------------------- SimplifyJobs

_SECTION = re.compile(r"^## (.+?) Internship Roles\s*$", re.M)
_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_HEAD = re.compile(r"<th[^>]*>(.*?)</th>", re.S)
_HREF = re.compile(r'href="([^"]+)"')


def _clean_url(u: str) -> str:
    u = html.unescape(u)
    u = re.sub(r"[?&](utm_source|utm_medium|ref)=[^&]*", "", u)
    return u.replace("?&", "?").rstrip("?&")


def parse_simplify(md: str, list_name: str) -> list[Job]:
    """Parse the HTML tables in a SimplifyJobs README. Skips the collapsed
    "Inactive roles" tables (inside <details>)."""
    md = re.sub(r"<details>.*?</details>", "", md, flags=re.S) if "Inactive roles" in md else md
    jobs: list[Job] = []
    sections = list(_SECTION.finditer(md))
    for i, sec in enumerate(sections):
        category = re.sub(r"^[^\w]+", "", sec.group(1)).strip()
        body = md[sec.end(): sections[i + 1].start() if i + 1 < len(sections) else len(md)]
        for table in re.findall(r"<table>(.*?)</table>", body, re.S):
            headers = [strip_html(h).lower() for h in _HEAD.findall(table)]
            last_company = ""
            for row in _ROW.findall(table):
                cells = _CELL.findall(row)
                if len(cells) != len(headers) or not cells:
                    continue
                c = dict(zip(headers, cells))
                company = strip_html(c.get("company", "")).replace("🔥", "").strip()
                if company in ("↳", ""):
                    company = last_company
                last_company = company
                raw_title = c.get("role", "")
                flags = [v for k, v in SIMPLIFY_FLAGS.items() if k in raw_title or k in c.get("company", "")
                         or k in c.get("application", "")]
                title = strip_html(raw_title)
                for k in SIMPLIFY_FLAGS:
                    title = title.replace(k, "")
                links = _HREF.findall(c.get("application", ""))
                apply = next((l for l in links if "simplify.jobs/p/" not in l), links[0] if links else "")
                loc = strip_html(c.get("location", "")).replace("\n", "; ")
                loc = re.sub(r"^\d+ locations\s*;?\s*", "", loc)
                jobs.append(Job(
                    company=company, title=title.strip(), location=loc,
                    url=_clean_url(apply), description="", source=f"simplify-{list_name}",
                    remote=_is_remote(loc), terms=strip_html(c.get("terms", "")),
                    posted=strip_html(c.get("age", "")), flags=flags,
                    extra={"category": category},
                ))
    return jobs


def fetch_simplify(list_name: str) -> list[Job]:
    return parse_simplify(_get(SIMPLIFY_URLS[list_name]).decode("utf-8"), list_name)


# ---------------------------------------------------------------- orchestration

def fetch_all(boards: dict[str, list[str]], simplify_lists: list[str],
              workers: int = 16) -> tuple[list[Job], list[str]]:
    """Fetch every board + Simplify list in parallel. Returns (jobs, errors)."""
    tasks = [(src, tok) for src, toks in boards.items() for tok in toks]
    tasks += [("simplify", name) for name in simplify_lists]
    jobs: list[Job] = []
    errors: list[str] = []

    def run(task):
        src, tok = task
        try:
            fn = fetch_simplify if src == "simplify" else ATS_FETCHERS[src]
            return fn(tok), None
        except Exception as e:  # one bad board shouldn't kill the run
            return [], f"{src}/{tok}: {e}"

    with ThreadPoolExecutor(workers) as ex:
        for got, err in ex.map(run, tasks):
            jobs.extend(got)
            if err:
                errors.append(err)
    return jobs, errors
