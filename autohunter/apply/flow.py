"""`main.py apply ...`: scan a form, fill it, hand it to the watcher.

  scan <url>   open the form, answer what the rules know, write form.json, print the questions
               that still need an answer (Claude fills those in form.json → "answers")
  fill <url>   fill everything (rules + form.json answers), show the panel, start the watcher
  go <url>     scan + fill in one step, no Claude: unknown questions are left for the user
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from .. import tracker
from . import log, settings
from .form import base_url, fill, form_url, inject_panel, open_form, plan, platform_of, scan
from .pdf import to_pdf
from .profile import Profile, job_kind

DUPLICATE_EXIT = 3


def _job(me: Path, url: str) -> dict:
    """Tracker row for this posting (matched on the posting URL), or a bare dict."""
    base = base_url(url)
    rows = tracker.load(me / "output" / "tracker.csv") if (me / "output" / "tracker.csv").exists() else []
    row = next((r for r in rows if r.get("url") and base_url(r["url"]) == base), None)
    return row or {"url": url}


def _folder(me: Path, job: dict, override: str | None) -> Path | None:
    if override:
        return Path(override)
    if job.get("folder"):
        f = me / "applications" / job["folder"]
        return f if f.exists() else None
    return None


ALLOW_BASE = {"value": False}  # set by --base-resume


def _files(me: Path, folder: Path | None) -> tuple[dict, list[str]]:
    notes = []
    cv = next(iter(sorted(folder.glob("CV *.docx"))), None) if folder else None
    if cv is None and not ALLOW_BASE["value"]:
        sys.exit("这个岗位还没有定制简历：先跑 /tailor（或者确认要用基础简历时加 --base-resume）。")
    base = cv is None
    if base:
        cv = me / "resume.docx"
        notes.append("⚠️ 传的是基础简历（完整版，没为这个岗位定制、没删到一页）：先跑 /tailor 更好")
    letter = next(iter(sorted(folder.glob("Cover Letter *.docx"))), None) if folder else None
    files = {"resume": str(to_pdf(cv)) if cv.exists() else ""}
    if base and files["resume"].endswith(".pdf"):
        # A recruiter sees the file name: "CV First Last.pdf", not "resume.pdf".
        import shutil
        user = json.loads((me / "config.json").read_text(encoding="utf-8")).get("apply", {})
        named = me / "output" / f"CV {user.get('first_name', '')} {user.get('last_name', '')}".strip().replace("  ", " ")
        named = named.with_name(named.name + ".pdf")
        shutil.copy2(files["resume"], named)
        files["resume"] = str(named)
    if letter:
        files["letter"] = str(to_pdf(letter))
        try:  # for forms that want the letter pasted into a text box instead of uploaded
            from docx import Document
            files["letter_text"] = "\n\n".join(p.text.strip() for p in Document(str(letter)).paragraphs if p.text.strip())
        except Exception:
            pass
    if files["resume"].endswith(".docx"):
        notes.append("简历传的是 .docx（没能导出 PDF：需要 Microsoft Word）")
    return files, notes


def _form_path(me: Path, folder: Path | None, url: str) -> Path:
    if folder:
        return folder / "form.json"
    slug = re.sub(r"[^a-z0-9]+", "-", base_url(url).split("//")[-1].lower()).strip("-")[:80]
    p = me / "output" / "forms" / f"{slug}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _require_settings(me: Path) -> None:
    if settings.missing(me):
        print("第一次运行：先填一下设置（会打开一个网页）。")
        settings.run(me)
        if settings.missing(me):
            sys.exit("设置还没填完，先不填表。运行 `main.py settings` 补上。")


def _check_duplicates(me: Path, job: dict, url: str, force: bool) -> dict:
    dup = log.duplicates(me, url, job.get("company", ""), job.get("title", ""), base_url(url))
    if (dup["applied"] or dup["pending"] or dup["similar"]) and not force:
        print(json.dumps({"duplicate": True,
                          "applied": [{k: r[k] for k in ("applied_on", "company", "title", "url")} for r in dup["applied"]],
                          "pending": [{k: p.get(k) for k in ("company", "title", "url", "started")} for p in dup["pending"]],
                          "similar": [{k: r[k] for k in ("applied_on", "company", "title", "url")} for r in dup["similar"]],
                          "company_count": dup["company_count"]}, ensure_ascii=False, indent=2))
        print("可能重复，没有填。确认要填的话加 --force。", file=sys.stderr)
        sys.exit(DUPLICATE_EXIT)
    return dup


def _profile(me: Path, files: dict, title: str = "") -> tuple[Profile, dict]:
    cfg, answers = settings.load(me)
    user = json.loads((me / "config.json").read_text(encoding="utf-8"))
    cfg = {"school": user.get("school", ""), "degree": user.get("degree", ""), **cfg}
    profile = Profile(cfg, answers, files, job_kind(title))
    profile.me = me
    return profile, cfg


def cmd_scan(me: Path, url: str, folder_arg: str | None, force: bool, quiet: bool = False) -> dict:
    from .browser import connect

    _require_settings(me)
    job = _job(me, url)
    folder = _folder(me, job, folder_arg)
    _check_duplicates(me, job, url, force)
    files, notes = _files(me, folder)
    profile, _ = _profile(me, files, job.get("title", "") or url)
    with connect() as (_, _, context):
        page = open_form(context, url)
        questions = scan(page)
        title = page.title()
    auto, unknown = plan(questions, profile)
    path = _form_path(me, folder, url)
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data = {"url": url, "form_url": form_url(url), "platform": platform_of(url), "page_title": title,
            "scanned": datetime.now().isoformat(timespec="seconds"), "questions": questions, "auto": auto,
            "unknown": [q["key"] for q in unknown], "answers": old.get("answers", {}),
            "consent_summaries": old.get("consent_summaries", {}), "notes": notes}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    if not quiet:
        print(json.dumps({"form": str(path), "platform": data["platform"], "answered_by_rules": len(auto),
                          "needs_answer": [{"key": q["key"], "kind": q["kind"], "label": q["label"],
                                            "required": q["required"], "options": q["options"][:30]}
                                           for q in unknown if q["key"] not in data["answers"]],
                          "needs_letter": needs_letter(questions, files),
                          "consents_to_tick": [{"key": q["key"], "label": q["label"][:600], "choice": auto[q["key"]]["value"]}
                                               for q in questions if auto.get(q["key"], {}).get("source") == "consent"],
                          "notes": notes}, ensure_ascii=False, indent=2))
    return data


def _skills_for(me: Path, folder: Path | None) -> list[str]:
    """Skills to add on Workday: the tailored resume's JD-relevant list, else the resume's own."""
    if folder and (folder / "plan.json").exists():
        plan_ = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
        got = plan_.get("relevant_skills", []) + [a.get("skill") for a in plan_.get("skill_additions", []) if a.get("skill")]
        if got:
            return got
    exp = me / "experience.json"
    return json.loads(exp.read_text(encoding="utf-8")).get("skills", [])[:15] if exp.exists() else []


def cmd_fill_workday(me: Path, url: str, folder_arg: str | None, force: bool, main_py: Path) -> None:
    """Workday: account → every step → stop at Review. Unknown required questions are printed;
    answers go in form.json → "answers" as {"<step>::<label>": value}, then run fill again."""
    from . import settings, workday
    from .browser import connect
    from .watch import start_background

    _require_settings(me)
    job = _job(me, url)
    folder = _folder(me, job, folder_arg)
    dup = _check_duplicates(me, job, url, force)
    files, notes = _files(me, folder)
    profile, cfg = _profile(me, files, job.get("title", "") or url)
    email = cfg.get("workday_email") or cfg.get("email")
    password = settings.get_password(email)
    if not password:
        sys.exit("钥匙串里没有 Workday 密码：运行 main.py settings 设一个。")
    path = _form_path(me, folder, url)
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    extra = {**saved.get("answers", {}), "_skills": _skills_for(me, folder)}
    company = job.get("company", "") or workday.tenant_of(url).split(".")[0]
    with connect() as (_, _, context):
        page = context.new_page()
        result = workday.run(page, me, url, profile, files, extra, email, password, company)
        summary = {}
        if folder and (folder / "summary.json").exists():
            summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        todo = [f"“{u['label'][:50]}”（{u['step']}）必填，还没答" for u in result["unknown"]] + result["problems"] + notes
        if not result["reached_review"] and not result["unknown"]:
            todo.insert(0, f"停在了 {result['step'] or '登录'}，没走到 Review")
        warn = []
        if dup["company_count"]:
            warn.append(f"这家公司你已经投了 {dup['company_count']} 个")
        consents = [{"label": x[3:].strip()[:80], "chosen": "勾选", "summary": x[3:].strip()[:160]} for x in result["log"] if x.startswith("☑️")]
        panel = {"title": f"{job.get('company', company)} · {job.get('title', '')}".strip(" ·"), "fit": job.get("fit_score", ""),
                 "resume_oneline": (summary.get("resume") or {}).get("oneline", ""), "points": (summary.get("resume") or {}).get("points", []),
                 "letter": "", "todo": todo, "warn": warn, "consents": consents,
                 "done_count": 0, "collapsed": cfg.get("panel") == "collapsed"}
        inject_panel(page, panel)
        page.bring_to_front()
    if result["unknown"]:
        saved.setdefault("answers", {})
        saved["workday_unknown"] = result["unknown"]
        path.write_text(json.dumps({**saved, "url": url}, indent=2, ensure_ascii=False), encoding="utf-8")
    log.add_pending(me, {"base": base_url(url), "url": url, "folder": str(folder) if folder else "",
                         "tracker_id": job.get("id", ""), "company": job.get("company", company), "title": job.get("title", ""),
                         "platform": "workday", "resume": files.get("resume", ""), "letter": files.get("letter", ""),
                         "source": job.get("source", "") or "manual", "panel": panel,
                         "started": datetime.now().isoformat(timespec="seconds")})
    start_background(me, main_py)
    print(json.dumps({"step": result["step"], "reached_review": result["reached_review"], "unknown": result["unknown"],
                      "todo": todo, "consents": [c["summary"] for c in consents], "form": str(path)}, ensure_ascii=False, indent=2))


ACCOUNT_ATS = ("icims.com", "oraclecloud.com", "taleo.net", "successfactors", "jobvite.com", "brassring")


LETTER_RE = re.compile(r"cover letter|letter of (interest|motivation)|motivation letter", re.I)


def needs_letter(questions: list[dict], files: dict) -> bool:
    """The form has a cover-letter field (upload or text box, required or optional) but no letter
    has been written for this job yet. The user's rule: then write one."""
    if files.get("letter"):
        return False
    return any(q["kind"] in ("file", "textarea") and LETTER_RE.search(f"{q.get('label', '')} {q.get('hint', '')}".replace("_", " "))
               for q in questions)


def generic_ok(url: str) -> bool:
    """A company-built form we can try with the generic multi-step engine (no ATS account)."""
    return platform_of(url) == "other" and not any(h in url for h in ACCOUNT_ATS)


def cmd_fill_generic(me: Path, url: str, folder_arg: str | None, force: bool, main_py: Path) -> None:
    from .browser import connect
    from .form import fill_multistep, open_generic
    from .watch import start_background

    _require_settings(me)
    job = _job(me, url)
    folder = _folder(me, job, folder_arg)
    dup = _check_duplicates(me, job, url, force)
    files, notes = _files(me, folder)
    profile, cfg = _profile(me, files, job.get("title", "") or url)
    path = _form_path(me, folder, url)
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    with connect() as (_, _, context):
        page = open_generic(context, url)
        r = fill_multistep(page, profile, files, saved.get("label_answers", {}))
        summary = json.loads((folder / "summary.json").read_text(encoding="utf-8")) if folder and (folder / "summary.json").exists() else {}
        todo = [f"“{u['label'][:50]}”（第 {u['step']} 步）必填，还没答" for u in r["unknown"]] + r["todo"] + notes
        if r.get("needs_letter"):
            todo.insert(0, "✉️ 这个表有 cover letter 栏，还没写：让我写一封再重新填（按你的规则，选填也写）")
        if not r["at_submit"] and not r["unknown"]:
            todo.insert(0, f"停在第 {r['steps']} 步，没走到提交页")
        warn = [f"这家公司你已经投了 {dup['company_count']} 个"] if dup["company_count"] else []
        summaries = saved.get("consent_summaries", {})
        consents = [{"label": c[:80], "chosen": "勾选", "summary": summaries.get(c, c)} for c in r["consents"]]
        panel = {"title": f"{job.get('company', '')} · {job.get('title', '') or page.title()}".strip(" ·"),
                 "fit": job.get("fit_score", ""), "resume_oneline": (summary.get("resume") or {}).get("oneline", ""),
                 "points": (summary.get("resume") or {}).get("points", []), "letter": "", "todo": todo, "warn": warn,
                 "consents": consents, "done_count": len(r["done"]), "collapsed": cfg.get("panel") == "collapsed"}
        inject_panel(page, panel)
        page_url = page.url
    saved.update(url=url, generic_unknown=r["unknown"], filled=r["filled"], apply_page=page_url)
    saved.setdefault("label_answers", {})
    path.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    log.add_pending(me, {"base": base_url(url), "page_base": base_url(page_url), "url": url,
                         "folder": str(folder) if folder else "",
                         "tracker_id": job.get("id", ""), "company": job.get("company", ""), "title": job.get("title", ""),
                         "platform": "generic", "resume": files.get("resume", ""), "letter": files.get("letter", ""),
                         "source": job.get("source", "") or "manual", "panel": panel,
                         "started": datetime.now().isoformat(timespec="seconds")})
    start_background(me, main_py)
    print(json.dumps({"steps": r["steps"], "at_submit": r["at_submit"], "filled": len(r["done"]), "unknown": r["unknown"],
                      "needs_letter": r.get("needs_letter", False),
                      "todo": todo, "consents": r["consents"], "form": str(path),
                      "how_to_answer": "put {label: value} in form.json → label_answers, then run apply fill again"},
                     ensure_ascii=False, indent=2))


def cmd_fill(me: Path, url: str, folder_arg: str | None, force: bool, main_py: Path) -> None:
    from .browser import connect
    from .watch import start_background

    if platform_of(url) == "workday":
        return cmd_fill_workday(me, url, folder_arg, force, main_py)
    from .kit import is_manual
    if is_manual(me, url):
        return cmd_kit(me, url, folder_arg, main_py)
    if generic_ok(url):
        return cmd_fill_generic(me, url, folder_arg, force, main_py)
    _require_settings(me)
    job = _job(me, url)
    folder = _folder(me, job, folder_arg)
    dup = _check_duplicates(me, job, url, force)
    files, notes = _files(me, folder)
    profile, cfg = _profile(me, files, job.get("title", "") or url)
    path = _form_path(me, folder, url)
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    extra = saved.get("answers", {})

    with connect() as (_, _, context):
        page = open_form(context, url)
        questions = scan(page)  # same DOM order → same keys as the scan Claude answered
        old_labels = {q["key"]: q["label"] for q in saved.get("questions", [])}
        auto, unknown = plan(questions, profile)
        answers = {k: v["value"] for k, v in auto.items()}
        drafts = []
        for key, a in extra.items():
            if old_labels and old_labels.get(key) != next((q["label"] for q in questions if q["key"] == key), None):
                notes.append(f"表单变了，没用上之前给 {key} 的答案")
                continue
            answers[key] = a["value"] if isinstance(a, dict) else a
            if isinstance(a, dict) and a.get("source") == "claude":
                drafts.append(next(q["label"] for q in questions if q["key"] == key)[:50])
        done, todo = fill(page, questions, answers, files)
        letter_missing = needs_letter(questions, files)
        if letter_missing:
            todo.insert(0, "✉️ 这个表有 cover letter 栏，还没写：让我写一封再重新填（按你的规则，选填也写）")
        summaries = saved.get("consent_summaries", {})
        consents = [{"label": q["label"][:80], "chosen": str(answers[q["key"]])[:40],
                     "summary": summaries.get(q["key"]) or (q["label"][:140] + ("…" if len(q["label"]) > 140 else ""))}
                    for q in questions if auto.get(q["key"], {}).get("source") == "consent" and q["label"][:50] in done]
        todo = [f"“{d}” 是我写的草稿，请读一遍" for d in drafts] + todo + notes

        summary = {}
        if folder and (folder / "summary.json").exists():
            summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        warn = []
        if dup["applied"] or dup["similar"]:
            warn.append("你可能已经投过这个岗位（你确认过仍然要填）")
        if dup["company_count"]:
            warn.append(f"这家公司你已经投了 {dup['company_count']} 个")
        for s in summary.get("skill_suggestions") or []:
            todo.append(f"建议加技能 {s['skill']}：{s.get('why', '')}（告诉我要不要加）")
        panel = {"title": f"{job.get('company', '')} · {job.get('title', '') or page.title()}".strip(" ·"),
                 "fit": job.get("fit_score", ""), "resume_oneline": (summary.get("resume") or {}).get("oneline", ""),
                 "points": (summary.get("resume") or {}).get("points", []),
                 "letter": (summary.get("cover_letter") or {}).get("oneline", "") if summary.get("cover_letter") else "",
                 "todo": todo, "warn": warn, "consents": consents, "done_count": len(done), "collapsed": cfg.get("panel") == "collapsed"}
        inject_panel(page, panel)
        target = next((q for q in questions if q["key"] in unknown and q["required"]), None)
        if target:
            page.locator(f'[data-ah="{target["key"]}"]').first.scroll_into_view_if_needed()
        page.bring_to_front()

    log.add_pending(me, {"base": base_url(url), "url": url, "folder": str(folder) if folder else "",
                         "tracker_id": job.get("id", ""), "company": job.get("company", ""), "title": job.get("title", ""),
                         "platform": platform_of(url), "resume": files.get("resume", ""), "letter": files.get("letter", ""),
                         "source": job.get("source", "") or "manual", "panel": panel,
                         "started": datetime.now().isoformat(timespec="seconds")})
    start_background(me, main_py)
    print(json.dumps({"filled": len(done), "todo": todo, "warn": warn, "needs_letter": letter_missing,
                      "consents_ticked": [c["label"] for c in consents]}, ensure_ascii=False, indent=2))


def cmd_go(me: Path, url: str, folder_arg: str | None, force: bool, main_py: Path) -> None:
    if platform_of(url) == "workday":  # Workday has no separate scan: questions appear step by step
        return cmd_fill_workday(me, url, folder_arg, force, main_py)
    from .kit import is_manual
    if is_manual(me, url):
        return cmd_kit(me, url, folder_arg, main_py)
    if generic_ok(url):
        return cmd_fill_generic(me, url, folder_arg, force, main_py)
    cmd_scan(me, url, folder_arg, force, quiet=True)
    cmd_fill(me, url, folder_arg, force, main_py)


def cmd_kit(me: Path, url: str, folder_arg: str | None, main_py: Path) -> None:
    """Manual-submit kit: (re)fill in the AutoHunter Chrome to collect answers, then open the apply
    page in the user's own Chrome next to a copy-paste cheat sheet, and remember the site."""
    from . import kit
    from .browser import connect
    from .form import fill_multistep, open_generic
    job = _job(me, url)
    folder = _folder(me, job, folder_arg)
    if folder is None:
        sys.exit("这个岗位还没有定制简历：先跑 /tailor。")
    files, _ = _files(me, folder)
    path = _form_path(me, folder, url)
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not saved.get("filled"):
        profile, _ = _profile(me, files, job.get("title", "") or url)
        with connect() as (_, _, context):
            page = open_generic(context, url)
            r = fill_multistep(page, profile, files, saved.get("label_answers", {}))
            saved.update(filled=r["filled"], generic_unknown=r["unknown"], apply_page=page.url)
            page.close()  # the automated tab is only scratch here
        path.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    sheet = kit.build(me, folder, saved, job, files.get("resume", ""))
    kit.copy_to_clipboard(json.dumps(kit.fill_data(saved, files.get("resume", "")), ensure_ascii=False))
    kit.remember(me, url)
    log.drop_pending(me, base_url(url))
    kit.open_in_users_chrome(saved.get("apply_page") or url)
    kit.open_in_users_chrome(sheet.resolve().as_uri())
    print(json.dumps({"kit": str(sheet), "apply_page": saved.get("apply_page") or url, "answers": len(saved.get("filled", [])),
                      "remembered_manual_site": True}, ensure_ascii=False, indent=2))
