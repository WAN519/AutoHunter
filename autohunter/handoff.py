"""Hotkey handoff: the user presses the hotkey on a job page → we take it from there.

  handoff <url> [--title T]   called by Hammerspoon with the frontmost Chrome tab
    1. classify the page (company ATS / LinkedIn / Jobright / Handshake / other)
    2. duplicate check → native dialogs (已投过 / 正在填 / 可能是同一个)
    3. add to the tracker (status QUEUED) and to me/output/queue.json
    4. a single background worker runs Claude Code headless: /tailor then /apply, one job at a
       time, with macOS notifications at the start and the end

We never fetch Jobright / Handshake / LinkedIn pages (CLAUDE.md rules 2 and 5): those only tell
the user to open the company's own apply page and press the hotkey there.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from . import tracker

SUPPORTED = ("greenhouse", "lever", "ashby", "workday")
NO_TOUCH = {"linkedin.com": "LinkedIn", "jobright.ai": "Jobright", "joinhandshake.com": "Handshake",
            "indeed.com": "Indeed", "glassdoor.com": "Glassdoor", "wellfound.com": "Wellfound"}


# ---------------------------------------------------------------- macOS UI

def _osa(script: str, timeout: int = 600) -> str:
    if platform.system() != "Darwin":
        return ""
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return ""


def _q(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title: str, text: str) -> None:
    _osa(f"display notification {_q(text)} with title {_q(title)}", timeout=10)


def ask(message: str, buttons: list[str], default: str) -> str:
    """Native dialog; returns the button pressed ("" if dismissed / timed out)."""
    btns = "{" + ", ".join(_q(b) for b in buttons) + "}"
    out = _osa(f"display dialog {_q(message)} with title \"AutoHunter\" buttons {btns} "
               f"default button {_q(default)} giving up after 300")
    m = re.search(r"button returned:(.*?)(,|$)", out)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------- queue

def _queue_path(me: Path) -> Path:
    return me / "output" / "queue.json"


def load_queue(me: Path) -> list[dict]:
    p = _queue_path(me)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def save_queue(me: Path, items: list[dict]) -> None:
    _queue_path(me).write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def _worker_pid(me: Path) -> Path:
    return me / "output" / ".handoff.pid"


def _worker_alive(me: Path) -> bool:
    try:
        os.kill(int(_worker_pid(me).read_text()), 0)
        return True
    except (OSError, ValueError):
        return False


# ---------------------------------------------------------------- step 1-3

ATS_NAMES = {"icims.com": "iCIMS", "smartrecruiters.com": "SmartRecruiters", "oraclecloud.com": "Oracle",
             "taleo.net": "Taleo", "successfactors": "SuccessFactors", "jobvite.com": "Jobvite",
             "workable.com": "Workable", "bamboohr.com": "BambooHR", "eightfold.ai": "Eightfold"}
ATS_LINK = re.compile(r'https?://[\w.-]*(?:myworkdayjobs\.com|greenhouse\.io|lever\.co|ashbyhq\.com|icims\.com|'
                      r'smartrecruiters\.com|oraclecloud\.com|taleo\.net|jobvite\.com|workable\.com)[^"\'<>\s\\]*')


def resolve_apply_url(url: str) -> str | None:
    """A company careers page (allowed to read) often fronts a real ATS: find that apply link.
    Prefers an explicit apply_url, then an ATS link containing the posting's id."""
    from .sources import _get, _get_json
    pu = urlparse(url)
    pid = re.search(r"(?:[?&]pid=|/careers/job/)(\d+)", url)
    if pid:  # Eightfold career sites (…eightfold.ai, apply.<company>.com): public job API
        try:
            d = _get_json(f"{pu.scheme}://{pu.netloc}/api/apply/v2/jobs/{pid.group(1)}")
            if d.get("apply_redirect_url"):
                return d["apply_redirect_url"]
        except Exception:
            pass
    try:
        page = _get(url).decode("utf-8", "ignore")
    except Exception:
        return None
    m = re.search(r'"(?:apply_url|applyUrl|apply_link)"\s*:\s*"([^"]+)"', page)
    if m:
        return m.group(1).replace("\\/", "/")
    ids = re.findall(r"\d{4,}", url)
    links = [l for l in dict.fromkeys(ATS_LINK.findall(page)) if not re.search(r"\.(js|css|png|svg)(\?|$)", l)]
    return next((l for l in links if any(i in l for i in ids)), None)


def ats_name(url: str) -> str:
    host = urlparse(url).netloc
    return next((n for d, n in ATS_NAMES.items() if d in host), host)


def _company_from(url: str, title: str) -> str:
    host = urlparse(url).netloc
    if "myworkdayjobs" in host:
        return host.split(".")[0]
    parts = [p for p in urlparse(url).path.split("/") if p]
    if any(h in host for h in ("greenhouse", "lever.co", "ashbyhq")) and parts:
        return parts[0]
    m = re.search(r"\bat ([A-Z][\w&.\- ]{1,40})", title or "")
    if m:
        return m.group(1).strip()
    # careers.docusign.com / jobs.acme.com / uscareers-docusign.icims.com → docusign / acme
    labels = [x for x in host.replace("www.", "").split(".") if x]
    name = labels[-2] if len(labels) >= 2 else labels[0]
    if name in ("icims", "myworkdayjobs", "smartrecruiters", "oraclecloud") and labels:
        name = re.sub(r"^\w*careers-", "", labels[0])
    return name.capitalize() if name.islower() else name


def take(me: Path, url: str, title: str, main_py: Path) -> str:
    """Handle one hotkey press. Returns a short status (also shown as a notification)."""
    from .apply.form import base_url, platform_of
    from .apply.log import duplicates, load_pending

    host = urlparse(url).netloc.lower()
    for dom, name in NO_TOUCH.items():
        if host.endswith(dom):
            msg = (f"{name} 的页面我不能读取。点它的 Apply，跳到公司官网的申请页面后再按一次快捷键。"
                   if name != "LinkedIn" else
                   "LinkedIn 岗位：先找公司官网上的同一个岗位（Apply 按钮跳转后的页面），在那里按快捷键。")
            notify("AutoHunter", msg)
            return msg
    if not url.startswith("http"):
        notify("AutoHunter", "当前标签页不是网页")
        return "not a web page"

    plat = platform_of(url)
    original = url
    if plat not in SUPPORTED:
        real = resolve_apply_url(url)
        if real:
            url, plat = real, platform_of(real)
    base = base_url(url)
    trk = me / "output" / "tracker.csv"
    rows = tracker.load(trk)
    row = next((r for r in rows if r.get("url") and base_url(r["url"]) == base), None)
    company = (row or {}).get("company") or _company_from(original, title)
    job_title = (row or {}).get("title") or re.sub(r"\s*[|–-]\s*[^|–-]*$", "", title or "").strip() or title
    job_title = re.sub(r"\s+in\s+[A-Z][\w .,'-]+$", "", job_title)  # "… Intern in San Francisco, California"

    refill = False
    # duplicate check (applied log, pending fills, queue, similar titles at the same company)
    dup = duplicates(me, url, company, job_title, base)
    queued = [q for q in load_queue(me) if q["base"] == base and q["state"] in ("queued", "running")]
    if dup["applied"]:
        r = dup["applied"][0]
        if ask(f"⚠️ 你 {r['applied_on']} 已经投过：\n{r['company']} · {r['title']}", ["取消", "仍然填"], "取消") != "仍然填":
            return "duplicate: applied"
    elif queued:
        if ask(f"这个岗位正在准备：\n{company} · {job_title}", ["取消", "打开那个标签页"], "打开那个标签页") == "打开那个标签页":
            _focus_tab(base)
        return "duplicate: in progress"
    elif dup["pending"]:
        choice = ask(f"这个岗位已经填好、还没提交：\n{company} · {job_title}\n\n"
                     f"提交失败或者页面过期了，可以选「重新填一遍」（不重新改简历，1–2 分钟）。",
                     ["取消", "打开那个标签页", "重新填一遍"], "打开那个标签页")
        if choice == "打开那个标签页":
            _focus_tab(base)
            return "duplicate: open tab"
        if choice != "重新填一遍":
            return "duplicate: pending"
        from .apply.log import drop_pending
        for p_ in dup["pending"]:
            drop_pending(me, p_["base"])
        refill = True
    elif dup["similar"]:
        r = dup["similar"][0]
        if ask(f"可能和你 {r['applied_on']} 投的是同一个岗位：\n{r['company']} · {r['title']}\n\n这次：{job_title}",
               ["是同一个，取消", "不是，继续填"], "不是，继续填") != "不是，继续填":
            return "duplicate: similar"
    if dup["company_count"]:
        notify("AutoHunter", f"提醒：{company} 你已经投了 {dup['company_count']} 个岗位")

    if row is None:
        note = f"handed over {date.today()}" + (f"; company page {original}" if original != url else "")
        tid = tracker.add_manual(trk, {"company": company, "title": job_title, "url": url,
                                       "source": "hotkey", "notes": note})
    else:
        tid = row["id"]
    from .apply.flow import generic_ok
    if plat not in SUPPORTED and not generic_ok(url):
        msg = (f"已加入 tracker（#{tid}）：{company} 用的是 {ats_name(url)}，"
               f"这个平台还不能自动填，需要你自己投。")
        notify("AutoHunter", msg)
        return msg

    flags = [] if refill else red_flags(me, url, job_title)
    if flags:
        tracker_note(trk, tid, "red flags: " + "; ".join(flags))
        if ask(f"{company} · {job_title}\n\n这个岗位可能不适合你：\n• " + "\n• ".join(flags) +
               "\n\n还要准备吗？", ["不投了", "仍然填"], "不投了") != "仍然填":
            return "skipped: " + "; ".join(flags)

    items = load_queue(me)
    items.append({"base": base, "url": url, "tracker_id": tid, "company": company, "title": job_title,
                  "added": datetime.now().isoformat(timespec="seconds"), "state": "queued", "refill": refill})
    save_queue(me, items)
    ahead = sum(1 for q in items if q["state"] in ("queued", "running")) - 1
    notify("AutoHunter", f"⏳ 开始准备 {company} · {job_title}" + (f"（前面还有 {ahead} 个）" if ahead else ""))
    start_worker(me, main_py)
    return f"queued #{tid}"


def red_flags(me: Path, url: str, title: str) -> list[str]:
    """Cheap pre-screen before spending a background run: terms the user rejected, experience
    caps, undergrad-only. Reads only the posting (company ATS)."""
    try:
        from .jd import fetch_jd
        t, text = fetch_jd(url)
    except Exception:
        return []
    cfg = json.loads((me / "config.json").read_text(encoding="utf-8"))
    when = f"{t} {title} {text}".lower()
    flags = []
    from .scoring import score  # reuse the season-normalising + term logic
    from .sources import Job
    from .config import topic_groups
    s = score(Job("x", t or title, "", url, text, "check"), cfg, topic_groups(cfg), set())
    if s["start_signal"].startswith("BAD TERM?"):
        flags.append(f"开始时间不对：{s['start_signal'][10:]}（你说过只投 1–2 月开始的）")
    m = re.search(r"no more than (\d+) (months?|years?) of (?:prior |professional |full[- ]time )*(?:work )?experience", when)
    mine = float(cfg.get("apply", {}).get("years_experience") or 0)
    if m and mine:
        n = int(m.group(1)) / (12 if m.group(2).startswith("month") else 1)
        flags.append(f"经验上限：最多 {m.group(1)} {m.group(2)}（你有 {mine:g} 年）" if n < mine else "")
    undergrad_only = re.search(r"(currently|actively) (pursuing|enrolled in) an? (bachelor|undergraduate)|"
                               r"enrolled in an? bachelor|designed for (actively enrolled |current )?undergraduate", when)
    # Whole words only: a bare "ms " also matches "systems ", which used to cancel this flag.
    grad_ok = re.search(r"\bmaster|\bgraduate (degree|student|program)|\bm\.s\.|\bms (degree|student|in\b)|"
                        r"\bph\.?d|\bmba\b", when)
    if undergrad_only and not grad_ok:
        flags.append("只招本科生（你在读硕士）")
    if re.search(r"(u\.s\.|us) citizen(ship)? (is )?required|must be a u\.s\. citizen|security clearance", when):
        flags.append("要求美国公民 / 安全许可")
    return [f for f in flags if f]


def tracker_note(path: Path, tid: str, note: str) -> None:
    rows = tracker.load(path)
    for r in rows:
        if r["id"] == tid and note not in r.get("notes", ""):
            r["notes"] = (r.get("notes", "") + "; " + note).strip("; ")
    tracker.save(path, rows)


def _focus_tab(base: str) -> None:
    try:
        from .apply.browser import connect
        from .apply.form import base_url
        with connect() as (_, _, ctx):
            for p in ctx.pages:
                if base_url(p.url) == base:
                    p.bring_to_front()
                    return
    except Exception:
        pass


# ---------------------------------------------------------------- step 4: worker

PROMPT = """This is a BACKGROUND run started by the AutoHunter hotkey. The user is not here: do not
ask questions, do not wait for answers. Follow CLAUDE.md.

Job: tracker id {tid} — {company} · {title}
URL: {url}

1. If the tracker row has no tailored resume folder yet, run the /tailor skill for id {tid}
   (background mode: skill suggestions go to summary.json, no questions). Get the JD with
   `uv run main.py jd {tid}`: it falls back to the AutoHunter Chrome for sites that block
   scripts (403), so don't tailor from the title alone. If it still fails, say so in RESULT.
2. Then run the /apply skill for {url}: always actually run `uv run main.py apply go "<url>"`
   (for sites in me/output/manual_sites.json it automatically builds the manual-submit kit
   instead; that counts as `RESULT: ok`). If it reports `needs_letter: true`, write the cover
   letter (/tailor step 4, same folder) and run `uv run main.py apply fill --force "<url>"` again.
   (it drives a real Chrome, which works on sites that block plain HTTP). Never conclude a
   form can't be filled without running it. Duplicate check: the user already confirmed, so
   use --force if it reports a duplicate. Draft essays; personal facts you don't know stay unanswered
   (the panel lists them). Stop at the form / Review page. Never submit.
3. End with ONE line: `RESULT: ok` if the form is filled and waiting for review, otherwise
   `RESULT: <short reason in Chinese>`.
"""


def start_worker(me: Path, main_py: Path) -> None:
    if _worker_alive(me):
        return
    logf = open(me / "output" / "handoff.log", "a", encoding="utf-8")
    subprocess.Popen([sys.executable, str(main_py), "--me", str(me), "handoff-worker"], cwd=str(main_py.parent),
                     stdout=logf, stderr=logf, stdin=subprocess.DEVNULL, start_new_session=True)


def _claude() -> str:
    return shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")


def work(me: Path, main_py: Path, budget_usd: float = 4.0) -> None:
    """Process the queue one job at a time until it's empty."""
    _worker_pid(me).write_text(str(os.getpid()))
    try:
        while True:
            items = load_queue(me)
            job = next((q for q in items if q["state"] == "queued"), None)
            if not job:
                return
            job["state"], job["started"] = "running", datetime.now().isoformat(timespec="seconds")
            save_queue(me, items)
            print(f"[{job['started']}] {job['company']} | {job['title']}", flush=True)
            prompt = PROMPT.format(tid=job["tracker_id"], company=job["company"], title=job["title"], url=job["url"])
            if job.get("refill"):
                prompt += ("\nThis is a REFILL: the user's earlier submit failed or the page expired. The resume is "
                           "already tailored: skip /tailor and run `uv run main.py apply go --force \"<url>\"` straight away.\n")
            cmd = [_claude(), "-p", prompt, "--permission-mode", "acceptEdits",
                   "--max-budget-usd", str(job.get("budget") or budget_usd),
                   "--allowedTools", "Bash(uv run main.py:*)", "Bash(uv run main.py *)", "Read", "Write", "Edit",
                   "Glob", "Grep", "WebFetch", "Skill"]
            try:
                r = subprocess.run(cmd, cwd=str(main_py.parent), capture_output=True, text=True, timeout=1800)
                out = r.stdout.strip()
            except subprocess.TimeoutExpired:
                out = "RESULT: 超时（30 分钟）"
            print(out[-1500:], flush=True)
            m = re.search(r"RESULT:\s*(.+)", out)
            result = (m.group(1).strip() if m else "没有结果（看 me/output/handoff.log）")[:120]
            items = load_queue(me)
            for q in items:
                if q["base"] == job["base"] and q["state"] == "running":
                    q["state"] = "done" if result.lower().startswith("ok") else "failed"
                    q["result"], q["finished"] = result, datetime.now().isoformat(timespec="seconds")
            save_queue(me, [q for q in items if q["state"] in ("queued", "running")] +
                        [q for q in items if q["state"] in ("done", "failed")][-30:])
            if result.lower().startswith("ok"):
                notify("AutoHunter", f"✅ 填好了：{job['company']} · {job['title']}，去 AutoHunter 的 Chrome 里看看")
                _focus_tab(job["base"])
            else:
                notify("AutoHunter", f"⚠️ {job['company']} 没填完：{result}")
    finally:
        _worker_pid(me).unlink(missing_ok=True)
