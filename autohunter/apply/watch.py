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
    started, last_shot = time.time(), {}
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
                            notify("AutoHunter：提交好像失败了",
                                   f"{entry.get('company', '')}：在岗位页面按快捷键，选「重新填一遍」，1–2 分钟就能重来")
                            print(f"submit failed? {entry.get('company')}", flush=True)
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
