---
name: hunt
description: "Find new internships and score how well each fits the user's resume. Runs the job search, reads the top new postings, scores them 0-100 against me/resume.docx, and writes results to the tracker. Use for: hunt / find jobs / 找工作 / 今天有什么新岗位 / score jobs."
---

# Hunt

## 1. Search

`uv run main.py hunt --top 0`. Report fetch errors briefly (a timed-out board is normal).
If `me/config.json` is missing, run the setup skill instead.

## 2. Pick candidates

From `me/output/tracker.csv`, take rows with `status` = `NEW` and an empty `fit_score`, highest
`score` first. Default 15 jobs; use the number the user gave if any.

## 3. Score

Inputs for every job: `uv run main.py resume dump`, `me/profile.md`, `me/config.json`, and the JD
from `uv run main.py jd <id>`. If that fails or returns page chrome instead of a job description,
try WebFetch on the URL. If there's still no usable JD, record `fit_notes: "JD unavailable"`,
leave `fit_score` empty, and move on.

For more than 5 jobs, spawn subagents in parallel (about 5 jobs each). Give each one the resume
dump, profile.md, the config's degree / work_authorization / terms / locations, the rubric below,
and its list of tracker ids. Tell it to fetch JDs itself and return ONLY the JSON array described
in Output. Subagents must not write to the tracker; you merge their results.

### Rubric (0–100)

| Part | Points | What counts |
| --- | --- | --- |
| Required qualifications | 40 | Hard skills / experience the JD requires, evidenced on the resume or in profile.md |
| Preferred qualifications | 15 | Nice-to-haves covered |
| Role fit | 15 | The day-to-day work matches the role families in config |
| Eligibility | 15 | Degree level accepted, term / start date and duration fit, location / remote, work authorization |
| Domain | 15 | Industry or problem-area experience |

Calibration bands: 90+ near-perfect · 70–89 strong, minor gaps · 50–69 stretch · 30–49 weak · <30 misaligned.

Hard rules:
- Requires US citizenship, security clearance, or "must not need sponsorship now or in the future"
  when the user will need it later → `status: SKIP`, say which rule.
- Degree level explicitly excluded (PhD-only for a master's student, undergrad-only for a grad
  student) → `SKIP`.
- Term clearly outside the user's window (e.g. Fall 2026 when they start Jan 2027) → `SKIP`.
- Seniority gap of two levels or more (e.g. "5+ years production ML" for an intern) → score ≤ 35.
- Never credit a skill that's absent from both the resume and profile.md. Gaps are concrete missing
  requirements, never personal critique.
- Vague JD → score ≤ 50 with note "thin JD".

Status: `SHORTLIST` if score ≥ `fit_threshold`, otherwise `LOW` (unless `SKIP`).

### Output

```json
[{"id": "12", "fit_score": 78, "status": "SHORTLIST",
  "fit_notes": "Strong: LangGraph agents + eval loops match. Gap: Kubernetes. Deadline Nov 20. Jan 4–Apr 9, on-site SF."}]
```

`fit_notes` is at most 200 characters: strongest match, main gap, then any deadline, dates,
pay, hours, or eligibility detail found in the JD.

## 4. Save and report

Write the merged array to `me/output/scores.json`, then `uv run main.py update me/output/scores.json`.

Show one table sorted by fit_score: id, company, title, fit, the key point from fit_notes. Put
SHORTLIST first, then mention how many were LOW or SKIP and why in one line each. End with:
"Reply `/tailor <ids>` to prepare applications (e.g. `/tailor 3 7 12`)."
