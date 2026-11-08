"""Background watcher for filled forms.

While a form waits for the user: re-inject the panel if the page reloaded, and keep a fresh
screenshot of the form (it captures the user's own edits too). When a confirmation page shows
up: save a final screenshot, append to applied.csv, mark the tracker row, notify. Exits when
nothing is pending, or after 12 hours.
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

from . import log
from .form import base_url, inject_panel, is_confirmation

SNAPSHOT_EVERY = 30
FAILED_RE = re.compile(r"something went wrong|submission failed|failed to submit|please try again|session (has )?expired|"
                       r"an error occurred|unable to (submit|process)|application could not be", re.I)
MAX_HOURS = 12

# Workday keep-alive. Its session times out after ~15-30 idle minutes and the half-filled
# application is wiped. While a Workday form waits for review we (a) nudge the mouse every few
# minutes, which counts as activity, and (b) click "Continue" on the timeout warning. This can't
# beat a hard session limit, which is why Workday forms are filled on demand (daily.py).
KEEPALIVE_EVERY = 240
TIMEOUT_WARN_RE = re.compile(r"session (is about to|will soon|will) (expire|time ?out)|about to (expire|time ?out)|"
                             r"due to inactivity|are you still (there|working)", re.I)
EXTEND_BTN_RE = re.compile(r"^\s*(continue|extend( session)?|stay (signed|logged) in|keep (me )?(signed|logged) in|"
                           r"i'?m still here|keep working)\s*$", re.I)
DIALOG_BUTTONS = "[role=dialog] button, [role=alertdialog] button, [data-automation-id*=opup] button"


def keep_alive(page, entry: dict, body: str, last: dict) -> None:
    """Keep a waiting Workday session from expiring. Never clicks anything except the
    session-timeout dialog's own continue button; never types."""
    if entry.get("platform") != "workday":
        return
    if TIMEOUT_WARN_RE.search(body):
        for btn in page.locator(DIALOG_BUTTONS).all():  # only inside the warning dialog, never the form
            try:
                if btn.is_visible() and EXTEND_BTN_RE.match(btn.inner_text(timeout=1000) or ""):
                    btn.click(timeout=3000)
                    print(f"kept session alive (dialog) {entry.get('company')}", flush=True)
                    break
            except Exception:
                continue
    if time.time() - last.get(entry["base"], 0) > KEEPALIVE_EVERY:
        try:  # a tiny pointer move in the page margin: activity without touching any field
            page.mouse.move(3, 200)
            page.mouse.move(4, 201)
            last[entry["base"]] = time.time()
        except Exception:
            pass


def notify(title: str, text: str) -> None:
    if platform.system() == "Darwin":
        esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'display notification "{esc(text)}" with title "{esc(title)}"'],
                       capture_output=True)


def _pidfile(me: Path) -> Path:
    return me / "output" / ".watch.pid"


def _running(me: Path) -> bool:
    try:
        os.kill(int(_pidfile(me).read_text()), 0)
        return True
    except (OSError, ValueError):
        return False


def start_background(me: Path, main_py: Path) -> None:
    """Start the watcher detached, unless one is already running."""
    if _running(me):
        return
    logf = open(me / "output" / "watch.log", "a", encoding="utf-8")
    subprocess.Popen([sys.executable, str(main_py), "--me", str(me), "apply", "watch"],
                     stdout=logf, stderr=logf, stdin=subprocess.DEVNULL, start_new_session=True)


def run(me: Path) -> None:
    from .browser import connect

    _pidfile(me).write_text(str(os.getpid()))
    started, last_shot, last_nudge = time.time(), {}, {}
    try:
        with connect() as (_, browser, context):
            while time.time() - started < MAX_HOURS * 3600:
                pending = log.load_pending(me)
                if not pending:
                    print("nothing pending, exiting", flush=True)
                    return
                for entry in pending:
                    for page in list(context.pages):
                        try:
                            if base_url(page.url) not in (entry["base"], entry.get("page_base")):
                                continue
                            body = page.evaluate("document.body ? document.body.innerText : ''")
                        except Exception:
                            continue
                        folder = Path(entry["folder"]) if entry.get("folder") else me / "output"
                        if is_confirmation(page.url, body):
                            shot = folder / "submitted.png"
                            try:
                                page.screenshot(path=str(shot), full_page=True)
                            except Exception:
                                shot = ""
                            row = log.record(me, entry, str(shot) if shot else "")
                            try:
                                from .. import sheets
                                ok, msg = sheets.push(me, [row])
                                print(f"sheets: {'ok' if ok else 'queued'} ({msg})", flush=True)
                            except Exception as e:
                                print(f"sheets: error {e}", flush=True)
                            log.save_pending(me, [p for p in log.load_pending(me) if p["base"] != entry["base"]])
                            notify("AutoHunter 已记录", f"{row['company']} · {row['title']}")
                            print(f"recorded {row['company']} | {row['title']}", flush=True)
                            break
                        if FAILED_RE.search(body) and not entry.get("failed_notified"):
                            entry["failed_notified"] = True
                            log.save_pending(me, [entry if log._same_job(p_, entry) else p_ for p_ in log.load_pending(me)])
                            notify("AutoHunter：页面过期或提交失败",
                                   f"{entry.get('company', '')}：在今日清单点「重新填一遍」（或在岗位页按快捷键），1–2 分钟就能重来")
                            print(f"submit failed? {entry.get('company')}", flush=True)
                        try:
                            keep_alive(page, entry, body, last_nudge)
                        except Exception:
                            pass
                        try:  # panel gone after a reload / next step: put it back
                            if not page.evaluate("!!document.getElementById('autohunter-panel')") and entry.get("panel"):
                                inject_panel(page, entry["panel"])
                        except Exception:
                            pass
                        if time.time() - last_shot.get(entry["base"], 0) > SNAPSHOT_EVERY:
                            try:
                                page.screenshot(path=str(folder / "form_snapshot.png"), full_page=True)
                                last_shot[entry["base"]] = time.time()
                            except Exception:
                                pass
                time.sleep(2)
    finally:
        _pidfile(me).unlink(missing_ok=True)
