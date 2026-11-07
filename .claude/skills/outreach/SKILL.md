---
name: outreach
description: "Write cold emails / LinkedIn notes to companies that haven't posted a matching job, especially part-time CPT asks (spring semester, ~20 h/week) and off-cycle internship asks. Uses me/output/leads.csv (HN Who-is-hiring) or any company the user names. Use for: 冷邮件 / 兼职 CPT 邮件 / outreach to <company> / write to these leads / 帮我联系 <公司>."
---

# Outreach

Drafts only. Never send email, never message anyone, never open LinkedIn. The user sends.

## 1. Pick the targets

- "leads" / no company named → run `uv run main.py leads` and take the rows the user picks, or
  the top 5 with `part-time` first.
- A company name → use it. If it has an open posting in the tracker, use /tailor instead: a
  posting deserves an application, not a cold email.

For each target, read what's public about it in what we already have: the lead's `snippet` and
`headline`, its site (WebFetch the `apply_link` if it's a careers / about page). Find one
specific, true thing to connect to: what they build, a stack they named, a problem they mentioned.
Make no claims beyond what you read.

## 2. Who to write to

`uv run main.py contacts "<Company>"` gives Google X-ray links (founders, eng leads, recruiters,
Northeastern alumni). The user opens them. For startups under ~50 people, a founder or eng lead
beats a recruiter. If the HN post gave a contact email, use that.

## 3. Write it

Facts only from `me/resume.docx` (dump) and `me/profile.md`. Follow `me/resume_style.md`
(self-intro rules: lead with what this company needs; QA background as support unless it's a QA
role). Banned phrases as in /tailor.

**Email (≤ 150 words)**, subject line included:

1. One line: who they are + the ask, up front.
2. One or two lines: the specific thing about the company, tied to one concrete piece of their
   evidence (a project with a number or a named tool).
3. The logistics, plainly. This is what makes a part-time ask easy to say yes to:
   - **part-time CPT** (spring semester): "~20 hours/week, January–April 2027, remote or
     Seattle; work authorization through CPT, so no sponsorship or cost on your side"
   - **full-time off-cycle**: "full-time internship any time January–September 2027 through CPT"
   - Use the dates and hours from me/config.json and the user's own words. Ask if unsure.
4. A small ask: a 15-minute call, or who the right person is. Then a link (GitHub / LinkedIn).

**LinkedIn note (≤ 300 characters)**: the same in two sentences.

Template, filled with the fictional Jane Doe. Never paste her facts:

```
Subject: Part-time ML engineer for spring? (Northeastern M.S., CPT)

Hi <Name>,

I'm Jane Doe, an M.S. Data Science student at Northeastern, and I'd like to help <Company> part-time this spring.
Your post mentioned <specific problem>; I built <project> that <concrete result with a number>, using <tool they named>.
I can commit ~20 hours/week from January through April 2027, remote or in Seattle. I'm authorized through CPT, so there's no sponsorship or cost on your side.
Would a 15-minute call make sense, or is there someone better to ask?

Jane Doe · github.com/janedoe · linkedin.com/in/janedoe
```

## 4. Save and track

Write `me/applications/outreach/<yyyymmdd> <Company>.md` with the email, the note, the contact
links and what you based the hook on. Set `status: drafted` in `me/output/leads.csv` for that
row. When the user says they sent it: `sent <date>`, plus a follow-up line 7 days later.

Finish with a table: company, who to contact (link), subject line, file.
