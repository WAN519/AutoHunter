"""Fill job applications in a dedicated Chrome profile. Never submits: the user clicks Submit.

browser.py   start / connect to the AutoHunter Chrome (its own profile, CDP on localhost)
settings.py  first-run settings form (local page) + macOS Keychain for the Workday password
profile.py   the applicant's answers: rules that map a question label to a value
form.py      scan a form into questions, fill them, inject the review panel
log.py       pending fills, the applied log (me/output/applied.csv), duplicate checks
watch.py     background watcher: snapshots forms, records the application when it's submitted
pdf.py       .docx -> .pdf for upload via Microsoft Word (falls back to the .docx)

Needs `playwright` (job search itself stays stdlib-only).
"""
