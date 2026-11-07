"""The AutoHunter Chrome: the user's installed Chrome, with its own profile and a CDP port.

Chrome refuses remote debugging on the default profile (since Chrome 136), so AutoHunter uses
its own. The user logs in there once (Google, etc.) and it remembers.
"""
from __future__ import annotations

import json
import platform
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

PORT = 9333
CDP = f"http://127.0.0.1:{PORT}"


def profile_dir() -> Path:
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "AutoHunter" / "chrome-profile"
    return Path.home() / ".autohunter" / "chrome-profile"


def chrome_binary() -> str:
    system = platform.system()
    if system == "Darwin":
        return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if system == "Windows":
        for base in (Path.home() / "AppData/Local", Path("C:/Program Files"), Path("C:/Program Files (x86)")):
            exe = base / "Google/Chrome/Application/chrome.exe"
            if exe.exists():
                return str(exe)
    return "google-chrome"


def _alive() -> bool:
    try:
        with urllib.request.urlopen(f"{CDP}/json/version", timeout=2) as r:
            return "webSocketDebuggerUrl" in json.loads(r.read())
    except OSError:
        return False


def _launch(url: str = "about:blank") -> None:
    """Start the AutoHunter Chrome, or ask the running one to open a window (same profile dir
    hands the URL to the existing process)."""
    profile_dir().mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [chrome_binary(), f"--user-data-dir={profile_dir()}", f"--remote-debugging-port={PORT}",
         "--no-first-run", "--no-default-browser-check", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )


def _open_blank_tab() -> None:
    """Ask Chrome over CDP for a new tab: works even when every window is closed."""
    try:
        req = urllib.request.Request(f"{CDP}/json/new?about:blank", method="PUT")
        urllib.request.urlopen(req, timeout=5).read()
    except OSError:
        pass


def ensure_running(timeout: float = 15) -> None:
    if _alive():
        return
    _launch()
    end = time.time() + timeout
    while time.time() < end:
        if _alive():
            return
        time.sleep(0.5)
    raise RuntimeError("AutoHunter Chrome didn't start. Is Google Chrome installed?")


@contextmanager
def connect():
    """Yield (playwright, browser, context). Leaves Chrome and its tabs open on exit."""
    from playwright.sync_api import Error, sync_playwright

    ensure_running()
    with sync_playwright() as p:
        browser = None
        # macOS Chrome with every window closed rejects new sessions: open a tab, retry.
        for attempt in range(4):
            try:
                browser = p.chromium.connect_over_cdp(CDP)
                break
            except Error:
                if attempt == 3:
                    raise
                _open_blank_tab() if attempt < 2 else _launch()
                time.sleep(1.5)
        yield p, browser, browser.contexts[0]


def find_page(context, url: str):
    """An open tab already on this posting, if any."""
    key = url.split("?")[0].rstrip("/")
    for page in context.pages:
        if page.url.split("?")[0].rstrip("/").startswith(key):
            return page
    return None
