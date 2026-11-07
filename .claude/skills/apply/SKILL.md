---
name: apply
description: "Fill a job application form in the AutoHunter Chrome so the user only reviews and clicks Submit. Tailors the resume first if needed, checks for duplicates, answers the form's questions (rules + your drafts for essays), shows a panel with what changed, and records the application automatically once submitted. Use for: 帮我填这个 <url> / apply to <url> / 填表 #12 / fill this application. Greenhouse, Lever, Ashby and Workday."
---

# Apply

Never click Submit. Never try to bypass a CAPTCHA. If one appears, the user handles it, and it
usually only shows on Submit anyway. Required consent / acknowledgement boxes are ticked
automatically (the user asked for this), and each one is summarized in the panel. Optional ones
(job alerts, SMS, marketing) stay unticked. Everything here runs in the AutoHunter Chrome (its own
profile), never the user's own browser.

## 1. Find the job

- Tracker id → its `url`. Bare URL → look it up in `me/output/tracker.csv` (match on the posting
  URL). If it isn't there, it's fine: `apply` works with any Greenhouse / Lever / Ashby URL.
- Workday works too (see "Workday" below). Another platform (Oracle, iCIMS, …) → say it isn't
  supported yet and stop.
- LinkedIn URL → don't open it. Ask for the company's own posting link (CLAUDE.md rule 2).

## 2. Resume ready?

If the tracker row has no `folder`, or the folder has no `CV *.docx`, run /tailor for it first
(interactive: the user is here, so ask the skill questions there). Otherwise skip. `apply`
refuses to upload the untailored base resume unless you pass `--base-resume`, and only do that
if the user explicitly asks for it. Workday keeps exactly one resume: older uploads are deleted
first.

## 3. Scan

`uv run main.py apply scan "<url>"`

- **First run:** if settings are missing, this opens the settings page and waits. Tell the user
  to fill it in and click 保存.
- **Exit code 3 = possible duplicate.** It prints what matched. Ask the user with one question:
  已经投过 → [仍然填] [取消]; 正在填 → [打开那个标签页] [取消]; 可能是同一个 → [是同一个，取消]
  [不是，继续填]. Continue only on a yes, adding `--force` to scan and fill.
- Otherwise it prints `needs_answer`: the questions the rules couldn't answer, and the path of
  `form.json`.

## 4. Answer what's left

For each `needs_answer` item, decide:

- **Essay / open text** ("Why X?", "good fit", "hardest challenge"): draft it from
  `me/resume.docx` (dump), `me/profile.md`, the tailored CV, `jd.txt` and `me/resume_style.md`.
  Use the same rules as the cover letter in /tailor: facts only, no invented claims about the
  company, no banned phrases, the user's tone. Respect the length the question asks for
  (otherwise 80–150 words). Save each one also as `<folder>/answers/<short-name>.txt`.
- **A choice you can answer from facts** (degree, graduation year, start date, location
  preference already stated in profile.md): answer it.
- **Personal facts you don't know** (high school, languages, offer deadlines, preferred offices,
  anything about their plans): don't guess. Ask the user, all of them in one message. Then
  save the reusable ones in `me/answers.json` → `learned` as
  `{"match": "<distinctive part of the label, lowercase>", "answer": "...", "source": "<company> <date>"}`,
  so the rules answer them next time. Skip one-off ones ("Why Cohere").
- **Consent boxes** (`consents_to_tick` in the scan output): they get ticked automatically. For
  each one, write a one-sentence plain summary in the user's language of what they agree to
  (who gets what data, for what, anything unusual like AI notetakers, background checks,
  arbitration or non-competes), e.g. "同意面试时用 AI 记录员转录对话". Put them in `form.json`
  → `consent_summaries` as `{"q32": "..."}`. If a clause looks unusual or risky, start the
  summary with ⚠️ and mention it to the user too.

Write the answers into `form.json` → `answers`:
`{"q25": {"value": "...", "source": "claude"}, "q12": {"value": "No", "source": "user"}}`.
For radio / checkbox / select / combobox, the value must be one of that question's `options`
(a list for multi-select checkboxes).

## 5. Fill

`uv run main.py apply fill "<url>"` (add `--force` if the user okayed a duplicate)

It uploads the resume as PDF (exported from the tailored .docx through Word; .docx if that fails), fills
every answer, injects the panel (resume changes from summary.json, your drafts marked "请读一遍",
anything still missing) and starts the background watcher. When the user submits, the watcher
saves a screenshot, appends `me/output/applied.csv` and marks the tracker row APPLIED. No need
to ask them to report back.

## 5b. Cover letter field

If scan or fill reports `needs_letter: true` and me/config.json → "apply" → `cover_letter` isn't
`"required"`: write the letter now (the /tailor skill, step 4, into the same folder), then run
`apply fill` again. It uploads the PDF, or pastes the text if the form wants a text box. In the
background, do the same without asking.

## 6. Tell the user

Short: which tab, how many fields filled, the list from `todo` (essays to read, fields they
must fill), the consents ticked (`consents_ticked`, one line each), and that it'll be logged
automatically on Submit.

## Graduation date

Intern / co-op / fellowship postings get `graduation_intern` from the settings; new-grad and
full-time postings get `graduation_ng`. Both are chosen from the job title. If the title is
ambiguous, check the JD and say which one you used.

## Workday

Workday has no separate scan: questions appear step by step, so run
`uv run main.py apply go "<url>"` directly (after the duplicate check and /tailor as above).

- **Account:** one per company, tracked in `me/output/workday_accounts.json`. Existing → sign in;
  none → create it with the Workday email + Keychain password (the user asked for this). Many
  companies disqualify duplicate profiles, so never create a second one. If sign-in fails, tell
  the user; don't register again. A verification email is read from Gmail automatically.
- **My Experience** comes from `me/experience.json` (work, education, `field_alternates` in the
  user's order, links) plus the tailored skills. Never invent a field of study or degree; if none
  of the user's names exist in the tenant's list, ask.
- **Unknown required questions** stop the run on that step. The output lists them with an
  `answer_key` (`"<step>::<label>"`). Answer like in step 4 and put them in that form.json →
  `answers` as `{"<answer_key>": "<value>"}` (an exact option for dropdowns). Then run
  `apply go --force` again: it resumes the saved draft and continues.
- It stops at **Review**. The user reads it and clicks Submit; the watcher records it.
