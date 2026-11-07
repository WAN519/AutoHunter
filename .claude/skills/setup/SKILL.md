---
name: setup
description: "First-time AutoHunter setup for a new user: check the environment, interview them, create their private me/ folder (config.json, resume.docx, profile.md, experience.json), then switch on form filling, the job-handoff hotkey, the Google Sheets log and the daily schedule. Use when the user says setup / 初始化 / first time, when me/config.json is missing, or for one part only (\"/setup hotkey\", \"/setup sheets\", \"/setup daily\")."
---

# Setup

Goal: a working `me/` folder for THIS user, one test hunt, then (on macOS) form filling, the
hotkey, the Sheets log and the daily schedule. `me/` is git-ignored; every personal fact goes
there and nowhere else. Never guess personal facts — ask. Never ask for or type passwords:
the settings page sends them straight to the macOS Keychain.

Start with `uv run main.py doctor`: it lists what's done and what's missing. Skip the parts that
are already ✅. If the user asked for one part only (`/setup hotkey`, `/setup sheets`,
`/setup daily`), do just that section of part B.

# Part A: finding jobs and tailoring

## 1. Environment

Run `uv --version`. If missing, give the install command for their OS and stop until it works:
- macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

Then `uv sync` (installs python-docx and playwright into `.venv`; playwright uses the installed
Google Chrome, so no browser download).

If `me/config.json` already exists, show its key settings and ask: update it, or keep it and stop?

## 2. Interview

Ask in rounds; after each round, repeat the answers back as a short list and fix mistakes.
Use AskUserQuestion for choices (max 4 options per question), plain chat for free text.

**Round 1 — who**: name, school, degree (`bachelors` / `masters` / `phd`), work authorization in
their own words (e.g. "F-1, CPT for internships", "US citizen").

**Round 2 — what**: role families, multi-select. Options are the keys of `ROLE_PRESETS` in
`autohunter/presets.py`: `ai-engineer`, `ml-infra`, `machine-learning`, `data-science`,
`data-analyst`, `data-engineering`, `software-engineer`, `eval-quality`. Split across two questions
if needed. Then ask for any niche keywords (→ `extra_topics`) and title words to exclude.

**Round 3 — when / where**:
- Employment: `full-time`, `part-time` (filters to postings that mention part-time), or `either`.
- Term(s) and start month. Turn the answer into `terms_best` / `terms_ok` / `terms_bad` phrases as
  they appear in postings (e.g. "spring 2027", "winter 2027", "co-op", "summer 2027").
- Locations: US-wide? specific cities? remote preferred? home city (gets a small bonus).
- Sponsorship: always skip `us-citizen-only` unless they are a citizen. For `no-sponsorship`
  (Simplify 🛂): F-1 students on CPT/OPT can often still apply, so default to `flag_only` and say why.

**Round 4 — resume**: path to their base resume **.docx** (the renderer edits the original file
to keep its formatting; a PDF won't work — ask them to export one from Word / Google Docs).
Copy it to `me/resume.docx` (copy, never move). Run `uv run main.py resume dump` and confirm the
text and estimated page count look right.

**Round 5 — profile.md** (free text, used by /hunt and /tailor):
- Real skills or tools NOT on the resume that may be added when a job asks
- Things that must never change (numbers, titles, dates, section order)
- Whether job-title rewording is allowed (default: no)
- 3–5 sentences about themselves and what they want, for cover letters and outreach
- Optional: an approved cover letter to use as a style reference

## 3. Write files

- `me/config.json`: same keys as `config.example.json`, filled from the interview. Keep
  `simplify_lists: ["off-season", "summer"]` and `company_tags: []` unless they asked otherwise.
  `fit_threshold` default 70.
- `me/profile.md`: Round 5 answers under clear headings. Always include `## Skills not on the
  resume` and `## Don't suggest`, even if empty: /tailor adds to both when the user answers a
  skill suggestion. If they can't remember extra skills, leave it empty. Suggestions will
  come up per job.
- `me/resume_style.md`: the template from the /style skill. If Round 5 included preferences about
  *how* to tailor, rather than facts (e.g. "keep the summary short", "don't touch my Acme
  bullets"), add them as the first `## Rules`, with today's date and source `setup`.

Show a one-screen summary and let them correct it.

## 4. Test

Run `uv run main.py hunt --top 10` and show the result. If nothing matches, loosen `roles`,
`locations_ok` or the term phrases with them.

# Part B: applying for them (macOS)

On Windows / Linux, stop after part A: hunting, scoring, tailoring and outreach all work;
form filling, the hotkey and the daily schedule are macOS-only for now. Say so.

## 5. Experience (for Workday-style forms)

Write `me/experience.json` from `uv run main.py resume dump`. Copy facts verbatim, invent
nothing:

```json
{"work": [{"title": "...", "company": "...", "location": "", "from": "Mon YYYY", "to": "Mon YYYY or Present",
           "bullets": ["<each bullet of that job, verbatim>"]}],
 "education": [{"school": "...", "degree": "Master's|Bachelor's|PhD", "field": "<as on the resume>",
                "field_alternates": [], "from": "Mon YYYY", "to": "graduation_setting for the current school, else Mon YYYY"}],
 "skills": ["<every item of the SKILLS lines>"], "links": {"linkedin": "", "github": ""}}
```

Ask once: if a form has no exact match for their field of study, which names may stand in, in
order (e.g. "Data Analytics Engineering → Data Science → Computer Science")? Put them in
`field_alternates`. Show the file's jobs and schools as a short list to confirm.

## 6. Settings page

`uv run main.py settings` opens a local page. Tell them what it covers so they fill it in one go:
contact details, the email for ATS accounts (Workday etc.), the account password (stored in the
Keychain, or "generate"), graduation date for internships vs new-grad roles (they may differ if
they'd delay graduation for an internship), years of full-time experience, earliest start date,
default answers (sponsorship now / future, EEO; "decline" is fine), hotkey, evening cutoff and
morning fill time, jobs per day, daily Claude budget. Wait until it prints that it's saved, then
run `doctor` again.

## 7. AutoHunter Chrome

The first form fill starts Chrome with its own profile (it can't drive their everyday Chrome).
Nothing to do now. If a site needs them logged in (rare: ATS accounts are created for them),
they log in once in that window and it's remembered.

## 8. Google Sheets log (optional, recommended)

1. `uv run main.py sheets setup` copies the script to the clipboard and opens a new sheet.
2. Guide them: Extensions → Apps Script → paste → save → in the toolbar pick `authorize` → ▶ Run
   → allow (Google says "unverified app": it's their own script; Advanced → Go to … → Allow) →
   Deploy → New deployment → ⚙ Web app, Execute as **me**, access **Anyone** → Deploy → copy the
   `/exec` URL. The URL isn't enough to write to the sheet: every call needs the token baked
   into their script.
3. `uv run main.py sheets connect <url>`. Use a personal Gmail rather than a school account (schools
   may block scripts or close the account later). The same script reads the ATS's verification
   emails, so their ATS account email should be that Gmail too.

## 9. Hotkey

1. Hammerspoon: `brew install --cask hammerspoon` if `doctor` says it's missing. Open it, then
   System Settings → Privacy & Security → Accessibility → turn Hammerspoon on.
2. `uv run main.py hotkey install`. Ask them to open any job page in their normal Chrome, press
   the hotkey, and check `me/output/hotkey.log`. On LinkedIn / Jobright / Handshake it only tells
   them to open the company's own apply page, by design.

## 9b. Fill bookmark (for sites that reject automated submits)

Some sites (e.g. Tesla) reject submissions from the AutoHunter Chrome. For those, AutoHunter opens
the apply page in the user's own Chrome and a bookmark fills it. Install once: open
`me/output/bookmarklet.html` (created by `uv run python -c "from pathlib import Path; from
autohunter.apply import kit; print(kit.install_page(Path('me')))"`) in their normal Chrome and drag
the blue button to the bookmarks bar. Chrome asks once to allow clipboard access: allow.

## 10. Daily schedule (optional)

Explain the cost first: roughly $1–2 of Claude usage per job (scoring + tailoring + filling),
capped by their daily budget. Then `uv run main.py daily install`. For the Mac to wake on its
own: they run `sudo pmset repeat wakeorpoweron MTWRFSU <fill time minus 5 min>` themselves
(it needs their password), with the Mac plugged in.

Finish with `doctor` and the everyday commands: hotkey on a job page · "帮我填这个 <url>" ·
`/hunt` · `/tailor <id>` · `/outreach` · `daily status`.
