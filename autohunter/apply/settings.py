"""First-run settings form, served on 127.0.0.1 and opened in the browser.

Saves plain settings to me/config.json → "apply", default answers to me/answers.json, and the
Workday password to the macOS Keychain. The password is never written to a file or printed.
"""
from __future__ import annotations

import json
import platform
import re
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

KEYCHAIN_SERVICE = "AutoHunter Workday"
REQUIRED = ["first_name", "last_name", "email", "phone", "city"]

DEFAULT_ANSWERS = {
    "authorized_us": "Yes",
    "sponsorship_now": "No",
    "sponsorship_future": "Yes",
    "how_heard": "Company website",
    "previously_employed": "No",
    "gender": "Decline to self-identify",
    "race": "Decline to self-identify",
    "hispanic": "Decline to self-identify",
    "veteran": "I don't wish to answer",
    "disability": "I don't wish to answer",
    "available_start": "",  # e.g. "January 4, 2027": earliest start date for "when can you start?"
}


# ---------- Keychain ----------

def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save_password(account: str, password: str) -> bool:
    if platform.system() != "Darwin":
        return False
    # `security -i` reads the command from stdin, so the password never appears in argv / ps.
    cmd = f"add-generic-password -U -s {_q(KEYCHAIN_SERVICE)} -a {_q(account)} -w {_q(password)}\n"
    r = subprocess.run(["security", "-i"], input=cmd, text=True, capture_output=True)
    return r.returncode == 0 and "error" not in (r.stdout + r.stderr).lower()


def get_password(account: str) -> str | None:
    if platform.system() != "Darwin" or not account:
        return None
    r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
                       capture_output=True, text=True)
    return r.stdout.rstrip("\n") if r.returncode == 0 else None


# ---------- load / save ----------

def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load(me: Path) -> tuple[dict, dict]:
    """(apply settings, answers). Missing answers fall back to DEFAULT_ANSWERS."""
    cfg = _read(me / "config.json").get("apply", {})
    answers = _read(me / "answers.json")
    answers["defaults"] = {**DEFAULT_ANSWERS, **answers.get("defaults", {})}
    answers.setdefault("learned", [])
    return cfg, answers


def missing(me: Path) -> list[str]:
    cfg, _ = load(me)
    return [k for k in REQUIRED if not str(cfg.get(k, "")).strip()]


def _from_resume(me: Path) -> dict:
    """Prefill guesses from the resume header: name line + contact line."""
    path = me / "resume.docx"
    if not path.exists():
        return {}
    try:
        from docx import Document
        lines = [p.text.strip() for p in Document(str(path)).paragraphs if p.text.strip()][:3]
    except Exception:
        return {}
    out, text = {}, " | ".join(lines[1:3])
    if lines:
        parts = lines[0].split()
        if len(parts) >= 2 and len(lines[0]) < 40:
            out["first_name"], out["last_name"] = parts[0], " ".join(parts[1:])
    if m := re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
        out["email"] = m.group(0)
    if m := re.search(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", text):
        out["phone"] = m.group(0)
    if m := re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+", text):
        out["linkedin"] = "https://" + re.sub(r"^https?://", "", m.group(0))
    if m := re.search(r"(?:https?://)?github\.com/[\w-]+", text):
        out["github"] = "https://" + re.sub(r"^https?://", "", m.group(0))
    if m := re.match(r"\s*([A-Za-z .'-]+),\s*([A-Z]{2})\b", text):
        out["city"], out["state"] = m.group(1).strip(), m.group(2)
    return out


def _initial(me: Path) -> dict:
    cfg, answers = load(me)
    user = _read(me / "config.json")
    guess = _from_resume(me)
    data = {"country": "United States", "school": user.get("school", ""), "degree": user.get("degree", ""),
            "hotkey": "⌥Space", "cutoff": "23:00", "fill_time": "07:00", "daily_cap": 8,
            "panel": "collapsed", "workday_same": True, **guess, **cfg}
    data["answers"] = answers["defaults"]
    data["has_password"] = bool(get_password(cfg.get("workday_email") or cfg.get("email", "")))
    data["is_mac"] = platform.system() == "Darwin"
    return data


def _save(me: Path, form: dict) -> dict:
    password = form.pop("workday_password", "") or ""
    answers = form.pop("answers", {})
    form.pop("has_password", None), form.pop("is_mac", None)
    if form.get("workday_same"):
        form["workday_email"] = form.get("email", "")
    cfg_path = me / "config.json"
    user = _read(cfg_path)
    user["apply"] = {**user.get("apply", {}), **form}
    cfg_path.write_text(json.dumps(user, indent=2, ensure_ascii=False), encoding="utf-8")
    ans_path = me / "answers.json"
    stored = _read(ans_path)
    stored["defaults"] = {**DEFAULT_ANSWERS, **stored.get("defaults", {}), **answers}
    stored.setdefault("learned", [])
    ans_path.write_text(json.dumps(stored, indent=2, ensure_ascii=False), encoding="utf-8")
    result = {"ok": True, "password": "unchanged"}
    if password:
        ok = save_password(form["workday_email"], password)
        result["password"] = "saved" if ok else "failed"
    return result


# ---------- server ----------

def run(me: Path, open_browser: bool = True) -> dict:
    """Serve the form until the user saves; return what happened (no secrets)."""
    page = (Path(__file__).parent / "settings.html").read_text(encoding="utf-8")
    done: dict = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep the terminal quiet; never log request bodies
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/":
                self._send(200, page, "text/html")
            elif self.path == "/data":
                self._send(200, json.dumps(_initial(me), ensure_ascii=False))
            else:
                self._send(404, "{}")

        def do_POST(self):
            if self.path != "/save" or self.headers.get("Origin", "").split("//")[-1] != self.headers.get("Host"):
                return self._send(403, "{}")
            form = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            done.update(_save(me, form))
            self._send(200, json.dumps(done))
            threading.Thread(target=server.shutdown, daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"AutoHunter 设置：{url}  （填完点保存，这个窗口会自动结束）")
    if open_browser:
        webbrowser.open(url)
    server.serve_forever()
    return done
