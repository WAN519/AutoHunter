"""Daily automation (macOS launchd): evening question → night prep → morning fill → checklist.

  evening   ~30 min before the cutoff: "明天投几个？" dialog → me/output/tomorrow.json
  night     at the cutoff: hunt → background /hunt fit scoring → pick the top N SHORTLIST jobs
            → background /tailor for each → me/output/today.json
  morning   at fill time: queue today's jobs on the handoff worker (fills one by one, never
            submits), then write me/output/today.html and open it in the AutoHunter Chrome
  install / uninstall / status   the three LaunchAgents

Everything costs Claude usage; `daily_budget_usd` (settings) caps each night + morning run.
"""
from __future__ import annotations

import html
import json
import os
import plistlib
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from . import handoff, tracker

LABEL = "com.autohunter.{}"
AGENTS = Path.home() / "Library" / "LaunchAgents"


def _cfg(me: Path) -> dict:
    return json.loads((me / "config.json").read_text(encoding="utf-8"))


def _out(me: Path, name: str) -> Path:
    return me / "output" / name


def _log(me: Path, msg: str) -> None:
    with _out(me, "daily.log").open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')}  {msg}\n")
    print(msg, flush=True)


def _claude(me: Path, main_py: Path, prompt: str, budget: float, timeout: int = 3600) -> str:
    cmd = [handoff._claude(), "-p", prompt, "--permission-mode", "acceptEdits", "--max-budget-usd", str(budget),
           "--allowedTools", "Bash(uv run main.py:*)", "Bash(uv run main.py *)", "Read", "Write", "Edit",
           "Glob", "Grep", "WebFetch", "Skill", "Task"]
    try:
        r = subprocess.run(cmd, cwd=str(main_py.parent), capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except subprocess.TimeoutExpired:
        return "RESULT: timeout"


def _candidates(me: Path) -> list[dict]:
    """Jobs worth preparing: shortlisted (or new & scored high), not applied, fillable platforms."""
    from .apply.flow import generic_ok
    from .apply.form import platform_of
    cfg = _cfg(me)
    thr = int(cfg.get("fit_threshold", 70))
    from .apply.form import base_url
    from .apply.log import load_pending
    applied = {r.get("url") for r in _applied(me)}
    waiting = {p["base"] for p in load_pending(me)}  # filled, waiting for the user: don't redo
    rows = tracker.load(_out(me, "tracker.csv"))
    ok = []
    for r in rows:
        if r.get("url") in applied or r.get("status") in ("APPLIED", "SKIP", "LOW", "READY-DONE"):
            continue
        if base_url(r["url"]) in waiting:
            continue
        if (r.get("start_signal") or "").startswith("BAD TERM"):
            continue
        fit = int(r["fit_score"]) if (r.get("fit_score") or "").isdigit() else -1
        if r.get("status") not in ("SHORTLIST", "READY", "QUEUED") and fit < thr:
            continue
        if platform_of(r["url"]) not in handoff.SUPPORTED and not generic_ok(r["url"]):
            continue
        ok.append({**r, "_fit": fit})
    ok.sort(key=lambda r: (r.get("status") != "QUEUED", -r["_fit"], -int(r.get("score") or 0)))
    return ok


def _applied(me: Path) -> list[dict]:
    from .apply.log import load_applied
    return load_applied(me)


# ---------------------------------------------------------------- evening

def evening(me: Path) -> int:
    cap = int(_cfg(me).get("apply", {}).get("daily_cap", 8))
    n = len(_candidates(me))
    out = handoff._osa(
        f'display dialog "明天投几个？\\n\\n现在有 {n} 个已筛过的候选（今晚还会再搜一轮）。\\n填 0 就是明天休息。" '
        f'with title "AutoHunter" default answer "{cap}" buttons {{"明天休息", "好"}} default button "好" '
        f'giving up after 1800', timeout=1900)
    m = re.search(r"text returned:(\d+)", out)
    if "明天休息" in out:
        cap = 0
    elif m:
        cap = int(m.group(1))
    _out(me, "tomorrow.json").write_text(json.dumps({"date": (date.today() + timedelta(days=1)).isoformat(),
                                                     "cap": cap, "asked": bool(out)}), encoding="utf-8")
    _log(me, f"evening: cap={cap} (candidates now {n}; {'answered' if out else 'no answer → default'})")
    return cap


def _cap_for_tomorrow(me: Path) -> int:
    p = _out(me, "tomorrow.json")
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("date") == (date.today() + timedelta(days=1)).isoformat() or d.get("date") == date.today().isoformat():
            return int(d.get("cap", 0))
    return int(_cfg(me).get("apply", {}).get("daily_cap", 8))


# ---------------------------------------------------------------- night

NIGHT_HUNT = """BACKGROUND run (the user is asleep; never ask questions). Run the /hunt skill: score up to
{n} NEW unscored jobs, highest keyword score first. Follow its rubric and hard rules (SKIP for terms
outside the user's window, citizenship, excluded degree). End with `RESULT: ok`."""

NIGHT_TAILOR = """BACKGROUND run (the user is asleep; never ask questions). Run the /tailor skill for tracker ids
{ids}, in background mode (skill suggestions go to summary.json). Don't fill any forms.
End with `RESULT: ok` or `RESULT: <short reason>`."""


def night(me: Path, main_py: Path) -> list[dict]:
    cap = _cap_for_tomorrow(me)
    budget = float(_cfg(me).get("apply", {}).get("daily_budget_usd", 10))
    if cap <= 0:
        _log(me, "night: cap 0, resting")
        _out(me, "today.json").write_text("[]", encoding="utf-8")
        return []
    _log(me, f"night: hunting (cap {cap})")
    subprocess.run([sys.executable, str(main_py), "--me", str(me), "hunt", "--top", "0"], cwd=str(main_py.parent),
                   capture_output=True, text=True, timeout=1800)
    # One daily budget: 15% scoring, 35% tailoring (night), 50% filling (morning, split per job).
    out = _claude(me, main_py, NIGHT_HUNT.format(n=max(15, cap * 2)), budget * 0.15)
    _log(me, "night: scored · " + (re.search(r"RESULT:.*", out) or re.search(".*", "RESULT: ?")).group(0)[:80])
    picks = []
    for r in _candidates(me):
        if len(picks) >= cap:
            break
        flags = handoff.red_flags(me, r["url"], r["title"])
        if flags:
            handoff.tracker_note(_out(me, "tracker.csv"), r["id"], "night red flags: " + "; ".join(flags))
            continue
        picks.append(r)
    need = [r["id"] for r in picks if not r.get("folder")]
    if need:
        out = _claude(me, main_py, NIGHT_TAILOR.format(ids=" ".join(need)), budget * 0.35)
        _log(me, f"night: tailored {need} · " + (re.search(r"RESULT:.*", out) or re.search(".*", "RESULT: ?")).group(0)[:80])
    rows = {r["id"]: r for r in tracker.load(_out(me, "tracker.csv"))}
    today = [{"id": r["id"], "company": rows[r["id"]]["company"], "title": rows[r["id"]]["title"],
              "url": rows[r["id"]]["url"], "fit": rows[r["id"]].get("fit_score", ""),
              "folder": rows[r["id"]].get("folder", ""), "state": "prepared" if rows[r["id"]].get("folder") else "no-resume"}
             for r in picks]
    _out(me, "today.json").write_text(json.dumps(today, indent=2, ensure_ascii=False), encoding="utf-8")
    _log(me, f"night: {len(today)} jobs ready for the morning")
    return today


# ---------------------------------------------------------------- morning

def morning(me: Path, main_py: Path, wait_minutes: int = 120) -> Path:
    from .apply.form import base_url
    today = json.loads(_out(me, "today.json").read_text(encoding="utf-8")) if _out(me, "today.json").exists() else []
    items = handoff.load_queue(me)
    queued = {q["base"] for q in items if q["state"] in ("queued", "running")}
    budget = float(_cfg(me).get("apply", {}).get("daily_budget_usd", 10))
    per_job = round(max(1.0, budget * 0.5 / max(1, len(today))), 2)
    for j in today:
        if j["state"] != "prepared" or base_url(j["url"]) in queued:
            continue
        items.append({"base": base_url(j["url"]), "url": j["url"], "tracker_id": j["id"], "company": j["company"],
                      "title": j["title"], "added": datetime.now().isoformat(timespec="seconds"), "state": "queued",
                      "daily": date.today().isoformat(), "budget": per_job})
    handoff.save_queue(me, items)
    if today:
        handoff.notify("AutoHunter", f"早上好：开始填今天的 {len(today)} 个岗位")
        handoff.start_worker(me, main_py)
    end = time.time() + wait_minutes * 60
    while time.time() < end and any(q["state"] in ("queued", "running") for q in handoff.load_queue(me)):
        time.sleep(20)
    page = checklist(me)
    _open_checklist(page)
    done = sum(1 for q in handoff.load_queue(me) if q.get("daily") == date.today().isoformat() and q["state"] == "done")
    handoff.notify("AutoHunter", f"今日清单：{done}/{len(today)} 个已填好，等你检查提交")
    _log(me, f"morning: {done}/{len(today)} filled → {page}")
    return page


def checklist(me: Path) -> Path:
    """me/output/today.html: one card per job with its state, resume changes, what to check."""
    from .apply.log import load_pending
    today = json.loads(_out(me, "today.json").read_text(encoding="utf-8")) if _out(me, "today.json").exists() else []
    queue = {q["tracker_id"]: q for q in handoff.load_queue(me)}
    pending = {p.get("tracker_id"): p for p in load_pending(me)}
    applied = {r.get("tracker_id") for r in _applied(me)}
    cards = []
    for j in today:
        q, p = queue.get(j["id"], {}), pending.get(j["id"], {})
        summary = {}
        if j.get("folder"):
            sp = me / "applications" / j["folder"] / "summary.json"
            if sp.exists():
                summary = json.loads(sp.read_text(encoding="utf-8"))
        if j["id"] in applied:
            state, cls = "✅ 已提交", "ok"
        elif p:
            state, cls = "🟢 已填好，等你检查并提交", "ready"
        elif q.get("state") == "failed":
            state, cls = f"⚠️ 没填完：{q.get('result', '')}", "warn"
        elif j["state"] == "no-resume":
            state, cls = "⚠️ 简历没准备好", "warn"
        else:
            state, cls = "⏳ " + q.get("state", "未开始"), "wait"
        todo = (p.get("panel") or {}).get("todo", [])
        pts = (summary.get("resume") or {}).get("points", [])
        cards.append(f"""
        <section class="{cls}"><h2>{html.escape(j['company'])} · {html.escape(j['title'])}</h2>
        <div class="meta">匹配 {html.escape(str(j.get('fit') or '?'))} · <a href="{html.escape(j['url'])}">岗位页面</a></div>
        <div class="state">{html.escape(state)}</div>
        {'<b>📄 简历改动</b><ul>' + ''.join(f'<li>{html.escape(x)}</li>' for x in pts) + '</ul>' if pts else ''}
        {'<b>⚠️ 需要你看</b><ul>' + ''.join(f'<li>{html.escape(x)}</li>' for x in todo) + '</ul>' if todo else ''}
        </section>""")
    body = "".join(cards) or "<p>今天没有安排岗位。</p>"
    page = _out(me, "today.html")
    page.write_text(f"""<!doctype html><meta charset="utf-8"><title>AutoHunter 今日清单</title>
<style>body{{font:14px/1.5 -apple-system,"PingFang SC",sans-serif;background:#f5f5f7;margin:0}} main{{max-width:760px;margin:28px auto;padding:0 16px}}
h1{{font-size:22px}} section{{background:#fff;border-radius:12px;padding:14px 18px;margin:12px 0;border-left:5px solid #d2d2d7}}
section.ready{{border-color:#34c759}} section.warn{{border-color:#ff9f0a}} section.ok{{border-color:#0071e3}} h2{{font-size:16px;margin:0 0 4px}}
.meta{{color:#6e6e73;font-size:12px}} .state{{margin:8px 0;font-weight:600}} ul{{margin:4px 0 8px;padding-left:20px}}</style>
<main><h1>AutoHunter 今日清单 · {date.today().isoformat()}</h1>
<p>填好的岗位都在 AutoHunter 的 Chrome 标签页里，每页右上角有面板。检查后你自己点 Submit，提交后会自动记录。</p>{body}</main>""",
                    encoding="utf-8")
    return page


def _open_checklist(page: Path) -> None:
    try:
        from .apply.browser import connect
        with connect() as (_, _, ctx):
            tab = next((p for p in ctx.pages if p.url.endswith("today.html")), None) or ctx.new_page()
            tab.goto(page.resolve().as_uri())
            tab.bring_to_front()
    except Exception:
        subprocess.run(["open", str(page)])


# ---------------------------------------------------------------- launchd

def _hm(t: str) -> tuple[int, int]:
    h, m = (t or "00:00").split(":")[:2]
    return int(h), int(m)


def install(me: Path, main_py: Path) -> str:
    cfg = _cfg(me).get("apply", {})
    ch, cm = _hm(cfg.get("cutoff", "23:00"))
    fh, fm = _hm(cfg.get("fill_time", "08:00"))
    eh, em = divmod(ch * 60 + cm - 30, 60)
    uv = handoff.shutil.which("uv") or "/opt/homebrew/bin/uv"
    AGENTS.mkdir(parents=True, exist_ok=True)
    plans = {"evening": (eh % 24, em), "night": (ch, cm), "morning": (fh, fm)}
    for name, (h, m) in plans.items():
        plist = {"Label": LABEL.format(name), "WorkingDirectory": str(main_py.parent),
                 "ProgramArguments": [uv, "run", "main.py", "--me", str(me), "daily", name],
                 "StartCalendarInterval": {"Hour": h, "Minute": m},
                 "EnvironmentVariables": {"PATH": f"/opt/homebrew/bin:/usr/local/bin:{Path.home()}/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                                          "HOME": str(Path.home())},
                 "StandardOutPath": str(_out(me, f"launchd-{name}.log")),
                 "StandardErrorPath": str(_out(me, f"launchd-{name}.log"))}
        path = AGENTS / f"{LABEL.format(name)}.plist"
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], capture_output=True)
        path.write_bytes(plistlib.dumps(plist))
        subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], capture_output=True)
    wake = f"{(fh * 60 + fm - 5) // 60 % 24:02d}:{(fh * 60 + fm - 5) % 60:02d}:00"
    return (f"已装好：{eh % 24:02d}:{em:02d} 问明天投几个 · {ch:02d}:{cm:02d} 准备岗位 · {fh:02d}:{fm:02d} 填表。\n"
            f"想让 Mac 合着盖也按时醒来，需要你在终端运行一次（要输入开机密码）：\n"
            f"  sudo pmset repeat wakeorpoweron MTWRFSU {wake}\n"
            f"（并插着电源；睡眠中错过的任务会在醒来后补跑）")


def uninstall() -> str:
    for name in ("evening", "night", "morning"):
        path = AGENTS / f"{LABEL.format(name)}.plist"
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], capture_output=True)
        path.unlink(missing_ok=True)
    return "已移除每日任务（pmset 唤醒如果设过，用 sudo pmset repeat cancel 取消）"


def status(me: Path) -> str:
    lines = []
    for name in ("evening", "night", "morning"):
        r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL.format(name)}"], capture_output=True, text=True)
        lines.append(f"{name:<8} {'已安装' if r.returncode == 0 else '未安装'}")
    if _out(me, "today.json").exists():
        lines.append(f"today.json: {len(json.loads(_out(me, 'today.json').read_text()))} 个岗位")
    log = _out(me, "daily.log")
    if log.exists():
        lines += log.read_text(encoding="utf-8").splitlines()[-5:]
    return "\n".join(lines)
