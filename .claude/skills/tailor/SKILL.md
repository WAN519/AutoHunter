---
name: tailor
description: "Prepare applications for chosen tracker ids: a lightly tailored resume fitted to one page by default (.docx, original formatting kept), a cover letter when needed, and contact links plus outreach drafts. Use for: tailor 3 7 / 改简历 / prepare application / 帮我准备 #12."
---

# Tailor

For each tracker id the user gave. Never submit an application, never sign in anywhere, never
message anyone. The user reviews and applies.

## 0. Learn first (once per run, not per id)

Follow the /style skill, part B: learn from resumes the user edited since last time, and ask
about any pattern that has now shown up twice. Then read `me/resume_style.md`, if it exists.

## 1. Folder and JD

Folder: `me/applications/<yyyymmdd> <Company> - <Role>/` (strip characters Windows forbids:
`<>:"/\|?*`). Save `uv run main.py jd <id>` output as `jd.txt` (WebFetch fallback, as in /hunt).

## 2. Plan

Read `uv run main.py resume dump`, `me/profile.md`, `me/resume_style.md`, the JD, and the
row's `fit_notes`. If resume_style.md lists good examples, read their `notes.md` and match how
they edit: how much, which kind of bullets, the summary's tone. Never copy their facts.
Write `plan.json`:

```json
{
  "replacements": [{"original_text": "<exact paragraph text from the dump>", "tailored_text": "..."}],
  "title_replacements": [],
  "relevant_skills": ["<items verbatim from the SKILLS lines>"],
  "skill_renames": [{"from": "<item as on the resume>", "to": "<the JD's name for the same skill>"}],
  "skill_additions": [{"skill": "<user-approved skill>", "line": "<start of a skills-line label, e.g. Tools>"}],
  "date_replacements": [{"line": "<school name>", "from": "<graduation date on the resume>", "to": "<per job type>"}],
  "drop_texts": ["<exact bullet text>", ["<job bullet>", "<job bullet>", "<that job's header line>"]],
  "max_pages": 1
}
```

### Editing rules: minimal touch

The goal is a resume that still reads like the user wrote it, with the JD's relevant evidence up front.

1. Pick the 4–6 bullets that best support this JD. Leaving a bullet unchanged is the normal case.
   Only add a replacement when an edit actually helps.
2. Allowed edits, in order of preference: none; reorder a clause so a JD term the bullet already
   contains comes first; use the JD's exact name for a tool or method the bullet already describes
   (e.g. "LLM evaluation" for "automated evaluation loops").
3. Never add a technology, metric, number, scope, team size, award or outcome that isn't in the
   source bullet or in profile.md's "skills not on the resume". Never change numbers or dates.
4. `original_text` must be copied character-for-character from the dump. Bullet paragraphs are
   marked `B`. Don't include the `[NNN]` prefix.
5. Summary paragraph: may be rewritten for the JD as a normal replacement. 1–2 sentences, ≤ 45
   words, no "I", every fact taken from the resume, nothing from the gaps, no target company name.
6. Job titles: only if profile.md allows it. Same function and level, JD wording only
   (`{"original_title", "tailored_title", "org"}`). Never raise the level or change the function.
7. `relevant_skills`: 10–20 items copied verbatim from the SKILLS lines that the JD asks for or
   that the selected bullets rely on. Everything else is removed from those lines. Certification
   and award lines are kept automatically.
8. `drop_texts`: every bullet you didn't select, least relevant first (old unrelated work first;
   for students, keep JD-relevant projects near the end). Code keeps going until the resume fits
   `max_pages` (default 1; resume_style.md may allow 2 for some kinds of job). To drop a whole
   job, use one list entry: its bullets, any sub-titles, then the header line (company, title,
   dates) last. It's removed all at once, so no orphan header is left behind.
9. Respect everything profile.md says must never change.
9b. Graduation date (the only date that may change, CLAUDE.md rule 3): read `graduation_intern`
    and `graduation_ng` from me/config.json → "apply". Intern / co-op / fellowship postings use
    the intern date; new-grad / full-time postings use the NG date. If the resume's expected
    graduation (the current school's education line) differs, add
    `{"line": "<school name>", "from": "<date as on the resume>", "to": "<target>"}` to
    `date_replacements`, and mention it in summary.json `points` ("毕业时间 → Dec 2027（实习）").
    The application form uses the same setting, so they always match.
10. Skill names: if the JD calls a skill the user already lists by another name, rename it with
    `skill_renames`. Only for the **same** skill (e.g. "LLM Evaluation" → "Model Evaluation",
    "Survival Analysis" → "Time-to-Event Modeling"), never a different tool (PyTorch ↛ TensorFlow).
    Renamed names are kept automatically; don't list them again in `relevant_skills`.
11. Skill suggestions: if the JD wants a skill that isn't on the resume or in profile.md, but the
    user very likely has it (it's a standard part of work their bullets already describe), don't
    add it. Suggest it (see 2b). Skip anything in profile.md's "Don't suggest" list. At most 3
    per job.
12. Then apply `## Rules` from resume_style.md, using the precedence in the /style skill:
    fact safety (3, 4, 9, 11) first, then the user's rules (newest wins), then rules 1, 2, 5–8
    and 10.

### 2b. Ask about suggested skills

For each suggestion from rule 11, give one line of evidence, e.g. "Kubernetes: JD 要求；你的
Docker 和 CI 经历里很可能用过".

- **The user is here** (an interactive /tailor): ask before rendering, with one multi-select
  question: "这些技能 JD 需要、你可能会但简历没写，要加上吗？" Put approved skills in
  `skill_additions`. Record each answer in profile.md: yes → "Skills not on the resume", so it's
  never asked again and can be used in bullets too; no → "Don't suggest".
- **The user isn't here** (a night or background run): render without them and list them in
  `summary.json` → `skill_suggestions` (see 6). The panel next to the application asks
  [加上] [不加]. On 加上, record it in profile.md, add it to `skill_additions`, and render again.

## 3. Render and check

`uv run main.py resume render "<folder>/plan.json" "<folder>/CV <Name> - <Company>.docx"`

- `unmatched` is not empty → fix those `original_text` values to match the dump exactly, then
  render again. A `skill: X` entry means a rename's `from` isn't on the resume: copy it from the
  SKILLS lines exactly. A `date: X` entry means the graduation date on the resume isn't
  written as X: copy it from the dump.
- `warning` says it's over the page limit → add more `drop_texts` and render again.
- Then dump the result with `--resume "<output>"` and reread it once: does it still read naturally?

## 4. Cover letter (only if the JD asks for one, or the user does)

Write `letter.json` → `uv run main.py letter "<folder>/letter.json" "<folder>/Cover Letter <Name> - <Company>.docx"`.
Keys: `name`, `contact_line`, `date`, `greeting`, `opener`, `body_paragraphs`, `closer`, `signoff`.

- 180–320 words. Opener: the role, the company, and the single most relevant piece of evidence.
  Body: 1–2 paragraphs, each built on 2–3 tailored bullets tied to specific JD requirements.
  Closer: one sentence inviting a conversation.
- Use only facts from the resume and profile.md. Make no claims about the company beyond what the
  JD says. Don't mention awards. Don't name skills from the gaps.
- Banned phrases: "passionate about", "self-starter", "quick learner", "team player",
  "great fit", "as you can see from my resume", "I look forward to", "thank you for your consideration".
- If profile.md has an approved example letter, match its structure and tone, but never its facts.

## 5. Contacts and outreach

`uv run main.py contacts "<Company>"` → write `contacts.md` with:
- The search links (recruiter, hiring manager, alumni). The user opens them; we never scrape LinkedIn.
- A LinkedIn connection note (≤ 300 characters): who they are, the specific role, one concrete
  piece of matching evidence, and a small ask (a 15-minute chat, or who to talk to).
- A short cold email (≤ 120 words) with the same content, plus a subject line.
- Fill in the user's real details. Use the role name from the JD. Leave `<Name>` for the
  recipient's name.

## 6. Notes and tracker

`notes.md`: fit score, every edit as before → after, the top gaps, and anything the user should
check (deadlines, start dates, hours, sponsorship wording, whether a cover letter is required).

`summary.json`: the short version of what changed, shown in the Google Sheet, the morning
checklist and the panel beside the application form. Write it in the user's language.

```json
{
  "resume": {
    "oneline": "Summary 突出 LLM 评测；Acme 测试框架那条提前；删 2 条 Globex",
    "points": ["Summary：改为突出 LLM 评测经验",
               "Acme 第 2 条：\"automated test framework\" → \"evaluation harness\"",
               "删除：Globex 两条早期经历（篇幅）"]
  },
  "cover_letter": {
    "oneline": "开头讲 eval pipeline 项目；第二段对应 JD 的分布式训练要求",
    "points": ["开头：eval pipeline 项目", "第二段：分布式测试经验 ↔ JD 分布式训练"]
  },
  "skill_suggestions": [
    {"skill": "Kubernetes", "line": "Tools", "why": "JD 要求；你的 Docker 和 CI 经历里很可能用过"}
  ]
}
```

Skill renames count as resume edits, so mention them in `points` (e.g. "技能改名：LLM
Evaluation → Model Evaluation"). Leave `skill_suggestions` out when there are none, or when the
user already answered them in this run.

- `oneline` ≤ 60 characters. `points` at most 3 for the resume and 2 for the letter, each one
  short line. Say what changed and why it matters for this JD. Don't repeat the whole bullet.
- Group small edits: "Skills 只留 14 项" rather than one point per skill.
- No edits at all → `"oneline": "未改动（原版已匹配）"`, `"points": []`.
- No cover letter → `"cover_letter": null`.

Then write a `me/output/scores.json` entry: `{"id": ..., "status": "READY", "folder": "<folder>"}`,
and run `uv run main.py update me/output/scores.json`.

Finish with a table: id, company, folder, pages, resume `oneline`, cover letter `oneline` (or —).
Then say once: "觉得哪份不对，直接告诉我怎么改，我会记住；你自己改了简历也行，下次我会学。"
Remind the user to open each .docx, export a PDF if the site wants one, and submit it themselves.
If they change the resume, they should edit and save that same file without renaming it, so the
next run can learn from the change.
After they apply, they (or you, when asked) set `status: APPLIED` and `applied_on`.
