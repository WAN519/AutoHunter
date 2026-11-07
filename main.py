"""AutoHunter CLI. Run with `uv run main.py <command>` (or plain python for `hunt`).

  hunt                      fetch boards + Simplify lists, keyword-filter, update the tracker
  jd <id|url>               print a job description (cached under me/output/jds/)
  update <file.json>        write fit scores / status / notes into the tracker
  resume dump               print resume paragraphs verbatim (for tailoring)
  resume render <plan> <out.docx>
  resume diff <generated.docx> <edited.docx>
  resume edits [--ack]      resumes the user edited after /tailor (for learning their style)
  letter <spec.json> <out.docx>
  contacts <company>        Google X-ray links for recruiters / managers / alumni
  doctor                    what's set up / missing, with the fix for each
  daily install|status|...  every day: evening "how many?", night prep, morning fill + checklist
  hotkey install            set up the job-handoff hotkey (Hammerspoon) from your settings
  handoff <url>             what the hotkey runs: dedupe → tracker → background tailor + fill
  leads                     part-time / intern leads from HN Who-is-hiring -> output/leads.csv
  settings                  settings form: contact info, Workday password (Keychain), schedule
  apply scan|fill|go <url>  fill an application in the AutoHunter Chrome (never submits)
  apply kit <url>           manual-submit kit for sites that reject automated submits
  sheets setup|connect|sync|pull   applied log <-> your Google Sheet (Apps Script)

Personal files live in --me (default ./me), which is git-ignored.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from autohunter import config as C
from autohunter import tracker
from autohunter.contacts import display_name, xray_links

ROOT = Path(__file__).resolve().parent
TOPIC_QUERY = {
    "data-science": '"data science" OR "analytics"', "data-analyst": '"analytics" OR "data"',
    "data-engineering": '"data engineering" OR "data platform"',
    "ml-infra": '"ML infrastructure" OR "ML platform" OR "infrastructure"',
}


def _paths(me: Path):
    out = me / "output"
    return out, out / "tracker.csv", out / "jds"


def cmd_hunt(args, me: Path):
    cfg = C.load_user(me)
    companies = C.load_companies()
    boards = C.boards_for(companies, cfg.get("company_tags", []))
    names = companies.get("display_names", {})
    from autohunter.scoring import rank
    from autohunter.sources import fetch_all

    print("Fetching job boards and Simplify lists...")
    jobs, errors = fetch_all(boards, cfg.get("simplify_lists", ["off-season", "summer"]))
    n_sources = sum(len(v) for v in boards.values()) + len(cfg.get("simplify_lists", []))
    print(f"  {len(jobs)} postings from {n_sources - len(errors)}/{n_sources} sources")
    for e in errors:
        print("  ! " + e)

    part_time_only = args.part_time or cfg.get("employment") == "part-time"
    ranked = rank(jobs, cfg, C.nonprofit_tokens(companies), part_time_only=part_time_only)

    out, tracker_path, jd_dir = _paths(me)
    fresh = [{
        "score": s["score"], "company": display_name(j.company, names), "title": j.title,
        "location": j.location, "remote": "yes" if j.remote else "", "part_time": s["part_time"],
        "terms": j.terms, "topics": s["topics"], "start_signal": s["start_signal"],
        "flags": ", ".join(j.flags), "nonprofit": "yes" if s["nonprofit"] else "",
        "compensation": j.compensation, "posted": j.posted, "source": j.source, "url": j.url,
    } for j, s in ranked]
    rows, new = tracker.merge(tracker_path, fresh)
    tracker.save(tracker_path, rows)

    # Cache JD text we already have (ATS APIs include it) so scoring needn't refetch.
    jd_dir.mkdir(parents=True, exist_ok=True)
    by_url = {r["url"]: r["id"] for r in rows}
    for j, _ in ranked:
        f = jd_dir / f"{by_url[j.url]}.txt"
        if j.description and not f.exists():
            f.write_text(f"{j.title}\n{display_name(j.company, names)} | {j.location}\n{j.url}\n\n"
                         f"{j.description}", encoding="utf-8")

    school = cfg.get("school", "")
    topic = " OR ".join(TOPIC_QUERY[r] for r in cfg.get("roles", []) if r in TOPIC_QUERY) \
        or '"ML" OR "AI" OR "data"'
    companies_seen = sorted({r["company"] for r in fresh})
    with (out / "contacts.csv").open("w", encoding=tracker.ENCODING, newline="") as f:
        w = csv.writer(f)
        w.writerow(["company", "recruiter_search", "hiring_manager_search", "alumni_search"])
        for c in companies_seen:
            l = xray_links(c, school, topic)
            w.writerow([c, l["recruiter"], l["hiring_manager"], l.get("alumni", "")])

    print(f"\n{len(ranked)} matching internships, {new} new -> {tracker_path}")
    print(f"Contact search links for {len(companies_seen)} companies -> {out / 'contacts.csv'}\n")
    for r in [r for r in rows if r.get("score")][: args.top]:
        flag = " [REMOTE]" if r["remote"] else ""
        print(f"#{r['id']:>4} {r['score']:>4}  {r['company'][:16]:<16} {r['title'][:58]:<58}{flag}")
        print(f"            {r['location'][:60]} | {r['topics']} | {r['start_signal'] or r['terms']}")


def cmd_jd(args, me: Path):
    from autohunter.jd import fetch_jd
    _, tracker_path, jd_dir = _paths(me)
    key = args.target
    row = next((r for r in tracker.load(tracker_path) if r["id"] == key or r["url"] == key), None)
    cache = jd_dir / f"{row['id']}.txt" if row else None
    if cache and cache.exists():
        print(cache.read_text(encoding="utf-8"))
        return
    url = row["url"] if row else key
    title, text = fetch_jd(url)
    body = f"{title}\n{(row or {}).get('company', '')} | {(row or {}).get('location', '')}\n{url}\n\n{text}"
    if cache and len(text) > 500:  # don't cache a failed fetch (page chrome / JS shell)
        jd_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(body, encoding="utf-8")
    print(body)


def cmd_update(args, me: Path):
    _, tracker_path, _ = _paths(me)
    n = tracker.update(tracker_path, Path(args.file))
    print(f"updated {n} rows in {tracker_path}")


def cmd_resume(args, me: Path):
    from autohunter import resume
    if args.action == "edits":
        found = resume.edits(me / "applications", ack=args.ack)
        print(json.dumps(found, indent=2, ensure_ascii=False))
        return
    if args.action == "diff":
        if not (args.plan and args.out):
            sys.exit("usage: resume diff <generated.docx> <edited.docx>")
        print(json.dumps(resume.diff(Path(args.plan), Path(args.out)), indent=2, ensure_ascii=False))
        return
    src = Path(args.resume) if args.resume else me / "resume.docx"
    if not src.exists():
        sys.exit(f"No resume at {src}. Put your base resume there as .docx (run /setup).")
    if args.action == "dump":
        print(resume.dump(src))
    else:
        if not (args.plan and args.out):
            sys.exit("usage: resume render <plan.json> <out.docx>")
        print(json.dumps(resume.render(src, Path(args.plan), Path(args.out)), indent=2))


def cmd_letter(args, me: Path):
    from autohunter import resume
    print(resume.letter(Path(args.spec), Path(args.out)))


def cmd_contacts(args, me: Path):
    cfg = C.load_user(me)
    for role, link in xray_links(args.company, cfg.get("school", "")).items():
        print(f"{role}: {link}")


def cmd_leads(args, me: Path):
    """Part-time / intern / contract mentions from the latest HN Who-is-hiring thread → leads.csv.
    These usually aren't postings you can apply to; they're companies to email (see /outreach)."""
    import re
    from autohunter.scoring import location_ok
    from autohunter.sources import fetch_hn
    cfg = C.load_user(me)
    out = me / "output" / "leads.csv"
    fields = ["kind", "company", "headline", "location", "remote", "apply_link", "hn_link", "snippet",
              "thread", "first_seen", "status", "notes"]
    old = {}
    if out.exists():
        with out.open(newline="", encoding=tracker.ENCODING) as f:
            old = {r["hn_link"]: r for r in csv.DictReader(f)}
    from datetime import date
    rows = []
    for j in fetch_hn():
        if j.location and not location_ok(j, cfg):
            continue
        text = j.description
        kind = ", ".join(k for k, pat in (("part-time", r"part[- ]time"), ("intern", r"\bintern(ship)?s?\b"),
                                           ("co-op", r"\bco-?op\b"), ("contract", r"\bcontract(or)?\b"))
                         if re.search(pat, text, re.I))
        m = re.search(r"part[- ]time|\bintern(ship)?s?\b|\bco-?op\b", text, re.I)
        snippet = text[max(0, m.start() - 120): m.end() + 160].replace("\n", " ") if m else text[:280]
        hn = j.url if "news.ycombinator.com" in j.url else ""
        key = hn or j.url
        prev = old.get(key, {})
        rows.append({"kind": kind, "company": j.company, "headline": j.title, "location": j.location,
                     "remote": "yes" if j.remote else "", "apply_link": j.extra.get("apply_url", ""), "hn_link": key,
                     "snippet": snippet.strip(), "thread": j.extra.get("thread", ""),
                     "first_seen": prev.get("first_seen") or date.today().isoformat(),
                     "status": prev.get("status", ""), "notes": prev.get("notes", "")})
    rows.sort(key=lambda r: ("part-time" not in r["kind"], r["remote"] != "yes", r["company"].lower()))
    with out.open("w", newline="", encoding=tracker.ENCODING) as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} leads -> {out}")
    for r in rows[: args.top]:
        print(f"  [{r['kind']}] {r['company'][:24]:<24} {r['location'][:28]:<28} {r['apply_link'][:50]}")


def cmd_handoff(args, me: Path):
    from autohunter import handoff
    print(handoff.take(me, args.url, args.title or "", Path(__file__).resolve()))


def cmd_handoff_worker(args, me: Path):
    from autohunter import handoff
    handoff.work(me, Path(__file__).resolve())


def cmd_doctor(args, me: Path):
    from autohunter import doctor
    print(doctor.render(me, Path(__file__).resolve().parent))


def cmd_daily(args, me: Path):
    from autohunter import daily
    main_py = Path(__file__).resolve()
    fn = {"evening": lambda: daily.evening(me), "night": lambda: daily.night(me, main_py),
          "morning": lambda: daily.morning(me, main_py), "checklist": lambda: daily.checklist(me),
          "install": lambda: daily.install(me, main_py), "uninstall": daily.uninstall,
          "status": lambda: daily.status(me), "candidates": lambda: [
              f"#{r['id']} fit={r.get('fit_score') or '-'} {r['status']:<9} {r['company'][:18]:<18} {r['title'][:55]}"
              for r in daily._candidates(me)]}[args.action]
    out = fn()
    print("\n".join(out) if isinstance(out, list) and out and isinstance(out[0], str) else out)


def cmd_hotkey(args, me: Path):
    from autohunter import hotkey
    print(hotkey.install(me, Path(__file__).resolve()))


def cmd_settings(args, me: Path):
    from autohunter.apply import settings
    r = settings.run(me)
    print({"saved": r.get("ok", False), "password": r.get("password", "unchanged")})


def cmd_sheets(args, me: Path):
    from autohunter import sheets
    if args.action == "setup":
        out = sheets.setup(me)
        print(f"脚本已复制到剪贴板（也存在 {out}）。浏览器里打开了一个新表格，接下来按 /sheets 的步骤做。")
    elif args.action == "connect":
        if not args.url:
            sys.exit("usage: sheets connect <web app url>")
        r = sheets.connect(me, args.url)
        print(f"已连接表格：{r.get('sheet')}")
        ok, msg = sheets.sync(me)
        print(f"同步：{'成功' if ok else '失败'}（{msg}）")
    elif args.action == "sync":
        ok, msg = sheets.sync(me)
        print(f"同步：{'成功' if ok else '失败，已排队下次再试'}（{msg}）")
    elif args.action == "pull":
        print(f"从表格拉回 {sheets.pull(me)} 处改动")


def cmd_apply(args, me: Path):
    from autohunter.apply import flow
    if args.action == "kit":
        if not args.url:
            sys.exit("usage: apply kit <posting url>")
        flow.cmd_kit(me, args.url, args.folder, Path(__file__).resolve())
        return
    if args.action == "watch":
        from autohunter.apply import watch
        watch.run(me)
        return
    if not args.url:
        sys.exit("usage: apply scan|fill|go <posting url> [--folder F] [--force] [--base-resume]")
    flow.ALLOW_BASE["value"] = args.base_resume
    fn = {"scan": lambda: flow.cmd_scan(me, args.url, args.folder, args.force),
          "fill": lambda: flow.cmd_fill(me, args.url, args.folder, args.force, Path(__file__).resolve()),
          "go": lambda: flow.cmd_go(me, args.url, args.folder, args.force, Path(__file__).resolve())}
    fn[args.action]()


def _ensure_path() -> None:
    """Launched from Hammerspoon / launchd the PATH is nearly empty: add the usual places so
    osascript, uv and claude are found."""
    import os
    extra = ["/usr/bin", "/bin", "/usr/sbin", "/sbin", "/opt/homebrew/bin", "/usr/local/bin",
             str(Path.home() / ".local" / "bin")]
    have = os.environ.get("PATH", "").split(os.pathsep)
    os.environ["PATH"] = os.pathsep.join([p for p in have if p] + [p for p in extra if p not in have])


def main():
    _ensure_path()
    # Windows consoles default to a legacy code page; don't crash on "…" or "↳".
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--me", default=str(ROOT / "me"), help="your private folder (default ./me)")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("hunt")
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--part-time", action="store_true", help="only postings that mention part-time")
    p.set_defaults(fn=cmd_hunt)

    p = sub.add_parser("jd")
    p.add_argument("target", help="tracker id or a posting URL")
    p.set_defaults(fn=cmd_jd)

    p = sub.add_parser("update")
    p.add_argument("file")
    p.set_defaults(fn=cmd_update)

    p = sub.add_parser("resume")
    p.add_argument("action", choices=["dump", "render", "diff", "edits"])
    p.add_argument("plan", nargs="?", help="render: plan.json | diff: generated.docx")
    p.add_argument("out", nargs="?", help="render: out.docx | diff: edited.docx")
    p.add_argument("--resume", help="override base resume path")
    p.add_argument("--ack", action="store_true", help="edits: mark the reported edits as learned")
    p.set_defaults(fn=cmd_resume)

    p = sub.add_parser("letter")
    p.add_argument("spec")
    p.add_argument("out")
    p.set_defaults(fn=cmd_letter)

    p = sub.add_parser("contacts")
    p.add_argument("company")
    p.set_defaults(fn=cmd_contacts)

    p = sub.add_parser("handoff", help="take the job in the frontmost tab (called by the hotkey)")
    p.add_argument("url")
    p.add_argument("--title", default="")
    p.set_defaults(fn=cmd_handoff)

    p = sub.add_parser("handoff-worker", help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_handoff_worker)

    p = sub.add_parser("doctor", help="check what's set up and what's missing")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("daily", help="daily automation: evening / night / morning runs, launchd install")
    p.add_argument("action", choices=["evening", "night", "morning", "checklist", "install", "uninstall", "status", "candidates"])
    p.set_defaults(fn=cmd_daily)

    p = sub.add_parser("hotkey", help="install / update the Hammerspoon hotkey from your settings")
    p.add_argument("action", choices=["install"])
    p.set_defaults(fn=cmd_hotkey)

    p = sub.add_parser("leads", help="part-time / intern mentions from HN Who-is-hiring (for outreach)")
    p.add_argument("--top", type=int, default=20)
    p.set_defaults(fn=cmd_leads)

    p = sub.add_parser("settings", help="open the settings form (contact info, passwords, schedule)")
    p.set_defaults(fn=cmd_settings)

    p = sub.add_parser("sheets", help="sync the applied log with your Google Sheet")
    p.add_argument("action", choices=["setup", "connect", "sync", "pull"])
    p.add_argument("url", nargs="?")
    p.set_defaults(fn=cmd_sheets)

    p = sub.add_parser("apply", help="fill an application form (never submits)")
    p.add_argument("action", choices=["scan", "fill", "go", "watch", "kit"])
    p.add_argument("url", nargs="?")
    p.add_argument("--folder", help="application folder (default: the tracker row's folder)")
    p.add_argument("--force", action="store_true", help="fill even if it looks like a duplicate")
    p.add_argument("--base-resume", action="store_true", help="upload the untailored base resume (default: refuse)")
    p.set_defaults(fn=cmd_apply)

    argv = sys.argv[1:]
    if not any(a in sub.choices for a in argv):  # bare `main.py [--top N]` = hunt
        i = 2 if argv[:1] == ["--me"] else 0
        argv = argv[:i] + ["hunt"] + argv[i:]
    args = ap.parse_args(argv)
    args.fn(args, Path(args.me))


if __name__ == "__main__":
    main()
