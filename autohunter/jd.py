"""Fetch a job description as plain text from a posting URL.

Uses each ATS's public JSON endpoint when the URL is recognised (Greenhouse,
Lever, Ashby, Workday), otherwise falls back to stripping the page's HTML.
Workday pages are JavaScript-only, so the JSON endpoint is the only way to get
their text without a browser.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from .sources import _get, _get_json, strip_html


def _greenhouse(u):
    # Custom career domains (…?gh_jid=123) don't reveal the board token; those
    # fall through to the HTML fallback.
    m = re.search(r"greenhouse\.io/([\w-]+)/jobs/(\d+)", u)
    if not m:
        return None
    d = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}")
    return d["title"], strip_html(d.get("content", ""))


def _lever(u):
    m = re.search(r"jobs\.lever\.co/([\w.-]+)/([0-9a-f-]{36})", u)
    if not m:
        return None
    d = _get_json(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}")
    lists = "\n".join(strip_html(l.get("content", "")) for l in d.get("lists") or [])
    return d["text"], "\n".join([d.get("descriptionPlain", ""), lists, d.get("additionalPlain", "")])


def _ashby(u):
    m = re.search(r"jobs\.ashbyhq\.com/([\w.-]+)/([0-9a-f-]{36})", u)
    if not m:
        return None
    board = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}")
    for j in board.get("jobs", []):
        if m.group(2) in j.get("jobUrl", "") or j.get("id") == m.group(2):
            return j["title"], j.get("descriptionPlain", "")
    return None


def _workday(u):
    p = urlparse(u)
    if "myworkdayjobs.com" not in p.netloc:
        return None
    tenant = p.netloc.split(".")[0]
    parts = [x for x in p.path.split("/") if x]
    if parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
        parts = parts[1:]  # drop locale like en-US
    if len(parts) < 2 or "job" not in parts:
        return None
    site, rest = parts[0], "/".join(parts[parts.index("job"):])
    d = _get_json(f"https://{p.netloc}/wday/cxs/{tenant}/{site}/{rest}")
    info = d.get("jobPostingInfo", {})
    return info.get("title", ""), strip_html(info.get("jobDescription", ""))


def _oracle(u):
    """Oracle Recruiting Cloud (…oraclecloud.com/hcmUI/CandidateExperience/…/sites/<site>/job/<id>)."""
    m = re.search(r"https://([^/]*oraclecloud\.com)/hcmUI/CandidateExperience/[^/]+/sites/([^/]+)/job/(\d+)", u)
    if not m:
        return None
    host, site, jid = m.groups()
    d = _get_json(f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
                  f"?expand=all&onlyData=true&finder=ById;Id=%22{jid}%22,siteNumber={site}")
    item = (d.get("items") or [{}])[0]
    text = "\n".join(strip_html(item.get(k) or "") for k in
                     ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr"))
    return item.get("Title", ""), text


MIN_JD_CHARS = 500  # less than this is page chrome or an empty JS shell, not a job description


def fetch_jd(url: str) -> tuple[str, str]:
    """Return (title, plain-text description). Raises on network errors."""
    for fn in (_greenhouse, _lever, _ashby, _workday, _oracle):
        try:
            got = fn(url)
        except Exception:
            got = None
        if got and got[1].strip():
            return got
    try:
        raw = _get(url).decode("utf-8", errors="replace")
    except Exception:
        got = _via_browser(url)  # e.g. tesla.com answers 403 to scripts but serves a real browser
        if got:
            return got
        raise
    # Many career sites embed JSON-LD JobPosting; prefer it over the page chrome.
    for block in re.findall(r'<script[^>]+ld\+json[^>]*>(.*?)</script>', raw, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for d in data if isinstance(data, list) else [data]:
            if isinstance(d, dict) and d.get("@type") == "JobPosting":
                return d.get("title", ""), strip_html(d.get("description", ""))
    title = re.search(r"<title>(.*?)</title>", raw, re.S)
    body = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", "", raw, flags=re.S | re.I)
    result = (strip_html(title.group(1)) if title else ""), strip_html(body)
    # JS-rendered pages (careers.ibm.com) and bot challenges (202 with an empty body) come back
    # "successfully" with no text. A real browser renders them.
    if len(result[1]) < MIN_JD_CHARS:
        got = _via_browser(url)
        if got and len(got[1]) > len(result[1]):
            return got
    return result


def _via_browser(url: str) -> tuple[str, str] | None:
    """Read a company's posting in the AutoHunter Chrome (a normal browser, like the user would).
    Only for company career pages; never for LinkedIn / Jobright / Handshake (CLAUDE.md)."""
    if re.search(r"linkedin\.com|jobright\.ai|joinhandshake\.com", url):
        return None
    try:
        from .apply.browser import connect
    except Exception:
        return None
    try:
        with connect() as (_, _, ctx):
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="load", timeout=60000)
                page.wait_for_timeout(3500)
                title = page.title()
                # Prefer the main region, but some sites (careers.ibm.com) have a near-empty <main>
                # and the posting elsewhere: then use the whole body.
                text = page.evaluate("""() => { const m = document.querySelector('main, [role=main], article');
                                              const t = m ? m.innerText : '';
                                              return t.length >= 500 ? t : document.body.innerText; }""")
            finally:
                page.close()
        return (title, text) if text and len(text) > 300 else None
    except Exception:
        return None
