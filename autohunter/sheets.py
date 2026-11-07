"""Sync me/output/applied.csv with the user's own Google Sheet, through an Apps Script web app.

  setup         make a token, put the script (with the token) on the clipboard, open a new sheet
  connect <url> save the web-app URL, test it, push everything
  sync          push every applied row (idempotent: rows are keyed by posting URL); retries the outbox
  pull          copy the statuses / notes you edited in the sheet back into applied.csv

Failures never lose data: unsent rows wait in me/output/sheets_outbox.jsonl. Stdlib only.
"""
from __future__ import annotations

import base64
import csv
import json
import platform
import secrets
import subprocess
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from . import tracker

SCRIPT = Path(__file__).parent / "sheets_script.gs"
MAX_PDF = 4 * 1024 * 1024
OWNED = {"状态": "status", "跟进日期": "follow_up", "联系人": "contact", "备注": "notes"}


def _cfg_path(me: Path) -> Path:
    return me / "config.json"


def _cfg(me: Path) -> dict:
    p = _cfg_path(me)
    return json.loads(p.read_text(encoding="utf-8")).get("apply", {}) if p.exists() else {}


def _save_cfg(me: Path, **kw) -> None:
    p = _cfg_path(me)
    user = json.loads(p.read_text(encoding="utf-8"))
    user.setdefault("apply", {}).update(kw)
    p.write_text(json.dumps(user, indent=2, ensure_ascii=False), encoding="utf-8")


def configured(me: Path) -> bool:
    c = _cfg(me)
    return bool(c.get("sheets_url") and c.get("sheets_token"))


def _post(url: str, payload: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    # Apps Script answers with a 302 to googleusercontent.com; urllib follows it as a GET.
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(url: str, token: str, timeout: int = 60) -> dict:
    with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode({'token': token})}", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _synced_path(me: Path) -> Path:
    return me / "output" / "sheets_synced.json"


def _synced(me: Path) -> set[str]:
    p = _synced_path(me)
    return set(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else set()


def _mark_synced(me: Path, keys: list[str]) -> None:
    _synced_path(me).write_text(json.dumps(sorted(_synced(me) | set(keys))), encoding="utf-8")


def to_sheet_row(row: dict, with_pdf: bool = True) -> dict:
    out = {"key": row.get("url", ""), "投递日期": row.get("applied_on", ""), "公司": row.get("company", ""),
           "职位": row.get("title", ""), "状态": row.get("status", "") or "Applied",
           "跟进日期": row.get("follow_up", ""), "简历改动": row.get("resume_changes", ""),
           "Cover letter 要点": row.get("letter_points", ""), "链接": row.get("url", ""),
           "平台": row.get("platform", ""), "来源": row.get("source", ""),
           "联系人": row.get("contact", ""), "备注": row.get("notes", "")}
    resume = Path(row.get("resume") or "")
    if with_pdf and resume.suffix.lower() == ".pdf" and resume.exists() and resume.stat().st_size <= MAX_PDF:
        out["resume_pdf_b64"] = base64.b64encode(resume.read_bytes()).decode("ascii")
        out["resume_name"] = resume.name
    return out


def _outbox(me: Path) -> Path:
    return me / "output" / "sheets_outbox.jsonl"


def push(me: Path, rows: list[dict]) -> tuple[bool, str]:
    """Send applied rows; on any failure keep them in the outbox for the next sync."""
    if not rows:
        return True, "nothing to send"
    if not configured(me):
        return False, "Google Sheets 还没连接（main.py sheets setup）"
    c = _cfg(me)
    done = _synced(me)  # résumé PDFs go up to Drive only the first time a row is sent
    try:
        r = _post(c["sheets_url"], {"token": c["sheets_token"], "action": "upsert",
                                    "rows": [to_sheet_row(x, with_pdf=x.get("url") not in done) for x in rows]})
        if r.get("ok"):
            _mark_synced(me, [x.get("url", "") for x in rows])
            return True, f"{r.get('rows', 0)} rows"
        err = r.get("error", "unknown error")
    except Exception as e:  # offline, Google hiccup, …
        err = f"{type(e).__name__}: {e}"
    with _outbox(me).open("a", encoding="utf-8") as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    return False, err


def _applied(me: Path) -> list[dict]:
    p = me / "output" / "applied.csv"
    if not p.exists():
        return []
    with p.open(newline="", encoding=tracker.ENCODING) as f:
        return list(csv.DictReader(f))


def sync(me: Path) -> tuple[bool, str]:
    rows = _applied(me)
    ok, msg = push(me, rows)  # everything: the outbox is a subset of applied.csv
    if ok:
        _outbox(me).unlink(missing_ok=True)
    return ok, msg


def pull(me: Path) -> int:
    """Copy user-owned columns edited in the sheet back into applied.csv. Returns rows changed."""
    from .apply.log import APPLIED_FIELDS
    c = _cfg(me)
    data = _get(c["sheets_url"], c["sheets_token"])
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "pull failed"))
    remote = {r.get("key"): r for r in data["rows"] if r.get("key")}
    rows, changed = _applied(me), 0
    for row in rows:
        r = remote.get(row.get("url"))
        if not r:
            continue
        for zh, en in OWNED.items():
            if r.get(zh, "") != "" and r[zh] != row.get(en, ""):
                row[en] = r[zh]
                changed += 1
    if changed:
        p = me / "output" / "applied.csv"
        with p.open("w", newline="", encoding=tracker.ENCODING) as f:
            w = csv.DictWriter(f, fieldnames=APPLIED_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    return changed


def verification(me: Path, hint: str = "", since_iso: str = "", wait: int = 180) -> dict | None:
    """Poll the user's Gmail (through their Apps Script) for a Workday verification email that
    arrived after `since_iso`. Returns {links, codes, subject, ...} or None after `wait` seconds."""
    import time
    c = _cfg(me)
    if not configured(me):
        return None
    end = time.time() + wait
    while time.time() < end:
        try:
            r = _post(c["sheets_url"], {"token": c["sheets_token"], "action": "verification",
                                        "since": since_iso, "hint": hint})
            if r.get("ok") and r.get("messages"):
                return r["messages"][0]
            if not r.get("ok"):
                raise RuntimeError(r.get("error", "verification failed"))
        except RuntimeError:
            raise
        except Exception:
            pass
        time.sleep(10)
    return None


def mail_ready(me: Path) -> bool:
    """True if the deployed script has the Gmail verification reader."""
    c = _cfg(me)
    try:
        return bool(_post(c["sheets_url"], {"token": c["sheets_token"], "action": "ping"}).get("mail"))
    except Exception:
        return False


def setup(me: Path) -> Path:
    """Token + script on the clipboard + a new sheet in the browser. Returns the script file."""
    c = _cfg(me)
    token = c.get("sheets_token") or secrets.token_urlsafe(24)
    _save_cfg(me, sheets_token=token)
    code = SCRIPT.read_text(encoding="utf-8").replace("__TOKEN__", token)
    out = me / "output" / "AutoHunter-sheets.gs"
    out.write_text(code, encoding="utf-8")
    if platform.system() == "Darwin":
        subprocess.run(["pbcopy"], input=code.encode("utf-8"))
    webbrowser.open("https://sheets.new")
    return out


def connect(me: Path, url: str) -> dict:
    url = url.strip()
    if not url.startswith("https://script.google.com/"):
        raise ValueError("应该是 https://script.google.com/macros/s/…/exec 这样的网址")
    c = _cfg(me)
    r = _post(url, {"token": c.get("sheets_token", ""), "action": "ping"})
    if not r.get("ok"):
        raise RuntimeError(f"连上了但被拒绝：{r.get('error')}（脚本里的 TOKEN 和设置不一致？重新运行 sheets setup）")
    _save_cfg(me, sheets_url=url)
    return r
