---
name: outreach
description: "Write cold emails / LinkedIn notes to companies that haven't posted a matching job: small startups (YC) and HN Who-is-hiring leads, for part-time or full-time CPT internships, including unpaid ones with real project work. Checks each company is real first, proposes a concrete project, and states CPT logistics plainly. Use for: 冷邮件 / 兼职 CPT 邮件 / 找无薪实习 / unpaid internship / outreach to <company> / write to these leads / 帮我联系 <公司> / 找 startup."
---

# Outreach

Drafts only. Never send email, message anyone, or open LinkedIn. The user sends everything.

The goal is a **real internship with project work they can put on their resume**, whether it's
paid, stipended or unpaid. It is never a paper arrangement: CPT has to be real work related to
their degree, with a supervisor. If anything suggests otherwise, skip the company and say why.

Settings come from `me/config.json` → `outreach`: `compensation` (`unpaid-ok` /
`stipend-preferred` / `paid-only`), `availability` (one or more windows: type, start, end,
hours_per_week, note), `work_mode`, `must_have`. If the block is missing, ask once and add it.

## 1. Pick the targets

- No company named → `uv run main.py leads` (both sources; `--source yc` or `--source hn` to
  narrow it). Show the top rows with an empty `status`. Columns: company, fit, segment, team size
  and batch (YC) or kind (HN), headline. Let the user pick, or take the top 10–15 as one batch.
  Prefer segments that match their resume. Say which segments you picked and why.
- A company named → use it. If it has an open posting in the tracker, use /tailor instead: a
  posting deserves an application, not a cold email.

One batch at a time: 10–15 companies. Small startups usually take 1–2 weeks to reply.

## 2. Check the company is real (before writing anything)

For each target, WebFetch its `website` (and `yc_link` for YC leads). Record:

| Check | Pass if |
|---|---|
| Live product | a product, docs, or a demo people can use, not just a waitlist page |
| Users | customers, logos, case studies, public users, or an open-source repo with real use |
| Engineers | a technical founder / CTO or engineers named (someone can actually supervise) |
| Active | news, a changelog, posts, commits or jobs from the last ~6 months |
| No red flags | no fee to "join" / "buy" an internship, no "CPT/OPT sponsorship packages", no vague "training program" sold to students |

Any red flag → `SKIP`, whatever else passes. Two or more other checks failing → `SKIP`. Otherwise
`PASS`, with a one-line reason. Save all of them in one file:
`[{"company": "...", "check": "PASS: live product, 3 engineers, shipped Oct 2026"}, ...]` →
`uv run main.py leads --update <file>`. Skipped companies get `"status": "skip"` too.
Only PASS companies get a draft.

## 3. A concrete project idea (an opener, not a plan)

From what you read on their site and the user's resume (`uv run main.py resume dump` +
`me/profile.md`), propose **one** project that:
- they would plausibly need, judging from their product (not a guess about their internals)
- uses evidence the user really has: a bullet, a project, a named tool
- fits the user's availability window and could produce something they can describe on a resume

Shapes that work by segment (adapt to the user; never copy another user's background):
- **agent eval / observability**: an eval set and regression check for one of their agent flows
- **agent infra / framework**: a benchmark, an integration or connector, example apps for their SDK
- **vertical agent**: one workflow feature, with a measurable before/after
- **ML infra**: a profiling or benchmark harness, or one serving / pipeline improvement
- **data / DS**: an analysis or model on a question their product implies

Write it as one or two sentences that start with "for example", then add "or whatever is most
useful to you right now". The company decides the real project. This idea only makes a yes easy.

## 4. Write it

Facts only from the resume dump and profile.md. Follow `me/resume_style.md` self-intro rules
(lead with what this company needs). Banned phrases as in /tailor.

**Email (≤ 150 words)**, subject line included:
1. Who they are and the ask, in one line.
2. The specific thing about the company, tied to one concrete piece of the user's evidence.
3. The project idea from step 3.
4. Logistics, plainly, from `outreach.availability` and `work_mode`. Pick the window that fits
   this company, or offer both in one sentence. Always include: "authorized through CPT, so
   there's no visa sponsorship or cost on your side".
5. Compensation, by setting:
   - `unpaid-ok` → "I'm flexible on compensation, including unpaid." Never lead with "unpaid".
     Flexibility reads as serious; many for-profit startups are wary of formally unpaid interns.
   - `stipend-preferred` → "I'm flexible on compensation; a modest stipend would be ideal."
   - `paid-only` → say nothing about pay in the first email.
6. One line about what CPT needs: an offer letter describing the role and a supervisor. This is
   the school's requirement, and it screens out companies that aren't serious.
7. A small ask: a 15-minute call, or who the right person is. Then GitHub / LinkedIn.

**LinkedIn note (≤ 300 characters)**: the same in two sentences, without the CPT detail.

Template, filled with the fictional Jane Doe. Never paste her facts:

```
Subject: Spring ML intern for <Company>? (Northeastern M.S., CPT)

Hi <Name>,

I'm Jane Doe, an M.S. Data Science student at Northeastern, and I'd love to help <Company> this spring.
<Specific thing from their site>. I built <project> that <concrete result with a number>, using <tool>.
For example, I could <project idea>, or whatever is most useful to you right now.
I can do ~20 hours/week from January through April 2027, remote or in Boston. I'm authorized through CPT, so there's no visa sponsorship or cost on your side, and I'm flexible on compensation. CPT needs an offer letter describing the role and a supervisor.
Would a 15-minute call make sense?

Jane Doe · github.com/janedoe · linkedin.com/in/janedoe
```

## 5. Who to write to

`uv run main.py contacts "<Company>"` gives Google X-ray links (founders, eng leads, recruiters,
alumni of the user's school). The user opens them. Under ~50 people, a founder or eng lead is
better than a recruiter. If the HN post gave a contact email, use that.

## 6. Save and track

`me/applications/outreach/<yyyymmdd> <Company>.md` holds:
- the email, the LinkedIn note, the contact links
- **Why this company**: the check result and what the hook and project idea are based on (with URLs)
- **Before you accept an offer**, the same list every time:
  - [ ] a named supervisor and a regular (weekly) check-in
  - [ ] the project scope written down (it goes in the offer letter for OISS / the DSO)
  - [ ] what you can put on your resume / GitHub under their NDA
  - [ ] start and end dates and hours match your CPT application
  - [ ] no fee of any kind, ever

Then set `"status": "drafted"` through `leads --update`. When the user says they sent it:
`"status": "sent <date>"`, plus a note to follow up 7 days later. When they reply:
`"status": "replied"` and so on.

Finish with a table: company, segment, check, who to contact (link), subject line, file. Then
one line on the next step: "Send these this week. I'll draft follow-ups in 7 days."
