---
name: style
description: "Learn how this user wants their resume and cover letters tailored, and remember it in me/resume_style.md so every later /tailor follows it. Use when the user gives feedback on a generated resume or letter (\"summary 太长了\", \"别改我的 title\", \"以后多突出 eval\", \"too wordy\"), marks one as good (\"这份好\", \"save this as an example\"), or asks to learn from resumes they edited (\"学一下我改的\", \"learn from my edits\"). Also run automatically at the start of /tailor."
---

# Style

Each user's preferences live in `me/resume_style.md`. /tailor reads it before every plan.
Write it in the language the user talks to you in. Never copy anything from it into tracked files.

## The file

Create it from this template if it's missing:

```markdown
# Resume style

AutoHunter keeps this file. You can also edit it directly; your edits win.

## Rules
<!-- Newest first. One line each: [date] rule. (source: what the user said or did) -->

## Watching
<!-- Patterns seen in your own edits, not yet confirmed. Ask at 2 sightings. -->

## Good examples
<!-- [date] folder: what makes it good -->
```

## Precedence

Used by /tailor, highest first:

1. Fact safety (CLAUDE.md rule 3 and /tailor rules 3, 4 and 9). A preference can never add a
   skill, number, scope or outcome, or change a date. If the user asks for that, say no and
   explain why. Don't record it as a rule.
2. `## Rules` in resume_style.md, newest first. When a new rule contradicts an older one, delete
   the older one; don't keep both.
3. /tailor's default editing rules. Preferences may override these. For example, "rewrite more
   freely" can lift the 4–6 bullet limit, but only within fact safety.

## A. The user says what they want

1. Restate it as one concrete, checkable rule. Bad: "make it better". Good: "Summary: one
   sentence, ≤ 25 words".
2. If it's vague, ask one question to pin it down. If it's clear, don't ask.
3. Add it to the top of `## Rules`: `- [yyyy-mm-dd] <rule>. (source: "<their words>")`. Remove
   any rule it contradicts.
4. Reply with one line: the rule you saved. If it changes an application that isn't submitted
   yet, offer to regenerate that one.

## B. Learn from the user's own edits

1. Run `uv run main.py resume edits`. It lists resumes the user changed after /tailor made them,
   as `changed` / `added` / `removed` paragraphs. `[]` means nothing new; stop.
2. Compare with `uv run main.py resume dump` (the base resume) to read each change correctly:
   - an `after` that matches base text means they **reverted** your edit
   - a `removed` bullet means they didn't want it for this kind of job
   - a rewrite tells you their preferred wording, length or emphasis
3. Name the general pattern behind each change, e.g. "reverts edits to the Acme bullets",
   "shortens the summary", "drops older QA bullets for ML roles". Ignore one-off fixes like typos
   or a company name.
4. For each pattern, look in `## Watching`:
   - not there: add `- <pattern> — 1× (<folder>)`
   - already there: increment the count. At **2 or more**, ask the user:
     "你已经 2 次把 Acme 那条改回原文了，以后都不改这条？" If they say yes, move it to
     `## Rules`. If they say no, delete it from Watching and don't ask again.
5. Never promote a pattern to a rule without a yes.
6. Run `uv run main.py resume edits --ack` so these edits aren't counted again.

## C. The user marks a resume or letter as good

1. Read that folder's `notes.md` and `summary.json`.
2. Add to `## Good examples`: `- [yyyy-mm-dd] <folder>: <what makes it good, in one line>`.
   Ask what they liked if it isn't obvious.
3. Keep at most 5 examples. Drop the oldest.

/tailor uses the examples' edits and tone as a model. It never copies facts from them.
