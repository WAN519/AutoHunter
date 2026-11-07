"""`main.py doctor`: one screen showing what's set up and what's missing, with the fix for each.

Read-only: checks files, tools and settings; never changes anything.
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

OK, WARN, BAD = "✅", "⚠️ ", "❌"


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def check(me: Path, root: Path) -> list[tuple[str, str, str]]:
    """[(status, item, how to fix)]"""
    mac = platform.system() == "Darwin"
    out: list[tuple[str, str, str]] = []

    def add(ok: bool | None, item: str, fix: str = "", warn: bool = False):
        out.append((OK if ok else (WARN if warn else BAD), item, "" if ok else fix))

    # basics: search + resume
    add(bool(shutil.which("uv")), "uv", "curl -LsSf https://astral.sh/uv/install.sh | sh")
    add((me / "config.json").exists(), "me/config.json（求职设置）", "在 Claude Code 里运行 /setup")
    add((me / "resume.docx").exists(), "me/resume.docx（基础简历，.docx）", "/setup 第 4 轮")
    add((me / "profile.md").exists(), "me/profile.md", "/setup 第 5 轮")
    add((me / "resume_style.md").exists(), "me/resume_style.md（简历偏好）", "/setup 第 5 轮", warn=True)
    add((me / "experience.json").exists(), "me/experience.json（Workday 工作经历用）", "/setup 第 5 步", warn=True)

    # form filling
    has_pw = importlib.util.find_spec("playwright") is not None
    add(has_pw, "playwright（自动填表）", "uv sync")
    chrome = Path("/Applications/Google Chrome.app") if mac else None
    add(bool(chrome and chrome.exists()) or not mac, "Google Chrome", "安装 Chrome")
    try:
        from .apply import settings
        missing = settings.missing(me) if (me / "config.json").exists() else ["all"]
        add(not missing, "填表设置（联系方式等）" + (f"，缺 {', '.join(missing)}" if missing else ""), "uv run main.py settings")
        cfg = json.loads((me / "config.json").read_text(encoding="utf-8")).get("apply", {}) if (me / "config.json").exists() else {}
        acct = cfg.get("workday_email") or cfg.get("email", "")
        add(bool(settings.get_password(acct)) if mac and acct else False,
            "Workday / 账号密码（钥匙串）", "uv run main.py settings → 设密码", warn=True)
    except Exception as e:
        add(False, f"填表设置（读取失败：{e}）", "uv run main.py settings")
        cfg = {}
    add(Path("/Applications/Microsoft Word.app").exists() if mac else False,
        "Microsoft Word（简历导出 PDF）", "没有 Word 也能用，但只能上传 .docx", warn=True)

    # Google Sheets + Gmail
    try:
        from . import sheets
        conf = sheets.configured(me)
        add(conf, "Google Sheets 投递记录", "uv run main.py sheets setup，按 README 部署后 sheets connect <url>", warn=True)
        if conf:
            add(sheets.mail_ready(me), "Gmail 读验证邮件（Apps Script 新版本）",
                "把 me/output/AutoHunter-sheets.gs 贴进 Apps Script，运行 authorize，重新部署新版本", warn=True)
    except Exception:
        pass

    # hotkey
    if mac:
        hs = Path("/Applications/Hammerspoon.app").exists()
        add(hs, "Hammerspoon（快捷键）", "brew install --cask hammerspoon，然后打开它，在 系统设置→隐私→辅助功能 里允许")
        lua = Path.home() / ".hammerspoon" / "autohunter.lua"
        add(lua.exists(), f"快捷键 {cfg.get('hotkey', '⌥Space')}", "uv run main.py hotkey install")
        if hs and lua.exists() and shutil.which("hs"):
            code, txt = _run(["hs", "-c", "return tostring(autohunterHotkey ~= nil)"], timeout=12)
            add(txt.endswith("true"), "快捷键已加载", "打开 Hammerspoon，并允许辅助功能权限；再 uv run main.py hotkey install", warn=True)

    # daily
    if mac:
        uid = os.getuid()
        loaded = all(_run(["launchctl", "print", f"gui/{uid}/com.autohunter.{n}"])[0] == 0
                     for n in ("evening", "night", "morning"))
        add(loaded, "每日自动运行（22:30 / 23:00 / 08:00 这类）", "uv run main.py daily install", warn=True)
        code, txt = _run(["pmset", "-g", "sched"])
        repeating = txt.split("Scheduled power events")[0]
        add("Repeating power events" in repeating and "wake" in repeating.lower(), "Mac 定时唤醒",
            "sudo pmset repeat wakeorpoweron MTWRFSU 07:55:00（可选）", warn=True)
    claude = shutil.which("claude") or (Path.home() / ".local" / "bin" / "claude").exists()
    add(bool(claude), "Claude Code CLI（后台改简历 / 填表）", "安装 Claude Code")
    if not mac:
        out.append((WARN, "自动填表、快捷键、每日运行目前只支持 macOS", "找岗位 + 改简历在 Windows 上照常能用"))
    return out


def render(me: Path, root: Path) -> str:
    rows = check(me, root)
    lines = ["AutoHunter 体检", ""]
    for status, item, fix in rows:
        lines.append(f"{status} {item}" + (f"\n      → {fix}" if fix else ""))
    bad = sum(1 for s, _, _ in rows if s == BAD)
    lines += ["", "全部就绪 🎉" if not bad else f"{bad} 项必须先解决（❌），⚠️ 是可选或建议"]
    return "\n".join(lines)
