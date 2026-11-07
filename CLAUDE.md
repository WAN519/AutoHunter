# AutoHunter

A shared internship-search tool for a small group of students. Code and skills are shared
through git; each person's data lives in their own git-ignored `me/` folder.

Workflow: `/setup` (once; `main.py doctor` shows what's missing) → `/hunt` (search + fit scoring) → `/tailor <ids>` (resume, cover
letter, outreach drafts) → `/apply <url|id>` (fill the form; the user reviews and submits;
logged automatically). `main.py daily install` runs that every day on its own. `/outreach` drafts cold emails (e.g. part-time CPT asks) for companies
without a matching posting, often from `main.py leads` (HN Who-is-hiring). `/style` remembers each user's tailoring preferences from their
feedback and their own edits. The skills live in `.claude/skills/`.

## Hard rules

1. **`me/` is private.** Never copy anything from `me/` into tracked files (code, skills,
   examples, commit messages). Examples use the fictional "Jane Doe". Never read another user's data.
2. **No LinkedIn automation.** Don't scrape, log in, search, or message on LinkedIn. Contacts come
   from Google X-ray search links that the user opens themselves.
3. **Never invent facts** on resumes, cover letters, or messages: no new skills, metrics, scopes,
   or outcomes. Never change numbers or dates. **One exception:** the expected graduation date
   follows the user's settings per job type (`graduation_intern` / `graduation_ng` in
   me/config.json → "apply"), e.g. a later date for internships because the user would delay
   graduation for an intern offer. The resume and the application form must always show the same
   date. Only that date changes, nothing else.
4. **Human in the loop.** Never click Submit; the user always reviews and submits. Never bypass
   CAPTCHAs (no solver services or tricks); the user handles any that appear. Filling application
   forms is allowed, but only in the AutoHunter Chrome (its own profile, `autohunter/apply/`), never
   the user's own browser, and never on LinkedIn. Required consent / acknowledgement boxes are
   ticked (users asked for this), and each one gets a plain-language summary in the panel.
   Optional marketing / alert / SMS boxes stay unticked. Passwords are never written to files, logs or chat: only the
   macOS Keychain, through the settings form. **Workday accounts:** create the account with the user's
   Workday email + Keychain password (users asked for this); don't use "Sign in with Google".
   Verification emails are read only through the user's own Apps Script (`sheets.verification`),
   which returns just the Workday verification link / code. Never type the user's Google password;
   never sign in to LinkedIn.
5. **No automated access to sites whose terms forbid it.** Jobright forbids any bot / script
   access (jobright.ai/legal/service), and Handshake's terms ban collecting job data with scripts,
   so never fetch jobright.ai or joinhandshake.com from code or tools. The user
   browses it and hands jobs over.

## Layout

```
main.py                      CLI: hunt | jd | update | resume ... | letter | contacts | settings | apply | sheets
companies.json               shared board list (Greenhouse / Lever / Ashby / Workday / SmartRecruiters tokens,
                             HN Who-is-hiring; + tags)
config.example.json          per-user config template
autohunter/
  sources.py                 ATS APIs (incl. Workday cxs, SmartRecruiters), HN Who-is-hiring, SimplifyJobs parser
  scoring.py                 keyword pre-filter (cheap, no LLM)
  presets.py                 role keyword presets, title rules, Simplify flags
  config.py, tracker.py      config loading; CSV tracker merge/update (utf-8-sig for Excel)
  jd.py                      JD text from a URL (ATS JSON, Workday cxs API, JSON-LD, HTML)
  contacts.py                X-ray search links
  resume.py                  dump / render / letter / diff / edits (user-edit detection)
  docx_render/               in-place .docx editing + page fitting, 1 or 2 pages (from JobHunter, MIT)
  handoff.py, hotkey.py      hotkey handoff: Hammerspoon reads the front Chrome tab → dedupe dialogs →
                             tracker (QUEUED) → queue.json → one background `claude -p` worker
                             (/tailor then /apply), notifications. Never fetches LinkedIn/Jobright/Handshake.
  doctor.py                  read-only health check: what's set up, what's missing, how to fix
  daily.py                   launchd: evening "how many tomorrow?" dialog → night hunt + /hunt scoring +
                             /tailor top N → morning: queue them on the handoff worker → today.html checklist
  sheets.py, sheets_script.gs  applied log → the user's own Google Sheet via an Apps Script web app
                             (token-checked; résumé PDFs to their Drive; their edits are never overwritten)
  apply/                     form filling (Playwright over CDP): browser, settings (+Keychain),
                             profile (label → answer rules), form (scan/fill/panel), log, watch,
                             workday (account + step-by-step fill to Review), kit + fillscript.js
                             (sites that reject automated submits: bookmarklet fills the user's own
                             Chrome from clipboard data; never signs, never submits)
me/                          per user, git-ignored: config.json (+ "apply" settings), answers.json,
                             experience.json (structured resume for forms),
                             (default + learned form answers), resume.docx, profile.md,
                             resume_style.md (learned preferences),
                             output/ (tracker.csv, applied.csv, pending.json, queue.json, workday_accounts.json,
                             leads.csv, jds/, contacts.csv),
                             applications/
me/applications/<folder>/    CV .docx, plan.json, notes.md, summary.json (short change summary),
                             .autohunter/<cv>.generated.docx (pristine copy for edit diffs)
```

## Conventions

- Job search code is **stdlib only**. Dependencies: `python-docx` (resume editing) and
  `playwright` (form filling only; import it lazily so `hunt` works without it).
  Run everything as `uv run main.py ...`.
- Form filling matches questions by **label text**, not per-site field names. A new common
  question → add a rule in `apply/profile.py`; a person-specific answer → that user's
  `me/answers.json` → `learned`. Test fills with fake Jane Doe data and no resume file, then
  close those tabs.
- Must work on macOS and Windows: use `pathlib`, write files with explicit `encoding=`, and never
  assume a shell.
- The tracker is keyed by `url`. A hunt refreshes the script columns and never overwrites the
  owned columns (`fit_*`, `status`, `folder`, `notes`, ...). Write owned columns only through
  `main.py update <json>`.
- Adding a board: put its token in `companies.json` with tags. Test it with a quick fetch first.
  A bad token only logs an error.
- New role family: add it to `ROLE_PRESETS` in `autohunter/presets.py` and list it in the setup skill.
