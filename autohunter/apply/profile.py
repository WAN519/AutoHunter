"""Map an application question (its label, kind, options) to the applicant's answer.

Answers come from me/config.json → "apply" (contact, school), me/answers.json → "defaults"
(work authorization, EEO, ...) and → "learned" (answers the user or Claude gave to questions the
rules didn't know, reused next time). Anything else is left for Claude / the user.
"""
from __future__ import annotations

import re

SKIP = object()      # known question, deliberately left blank (e.g. Twitter, referral name)
SIGNATURE = object() # an e-signature: never typed by us, always left for the user
RESUME = "<resume>"
LETTER = "<cover letter>"

DECLINE = ["decline", "prefer not", "don't wish", "do not wish", "not wish to", "not to disclose",
           "choose not", "rather not", "not to answer", "not to say", "do not want", "don't want", "not want to"]
DEGREES = {
    "bachelors": ["Bachelor's", "Bachelors", "Bachelor", "BS", "B.S.", "BA", "Undergrad", "Undergraduate"],
    "masters": ["Master's/MBA", "Master's", "Masters", "Master", "MS", "M.S.", "Graduate"],
    "phd": ["PhD", "Ph.D.", "Doctorate", "Doctoral"],
}
STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
          "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
          "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
          "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
          "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
          "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
          "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
          "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
          "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
          "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
          "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"}

CHOICE_KINDS = {"select", "combobox", "radio", "checkbox"}
CONSENT_YES = ["Yes, I consent", "I consent", "I agree", "I acknowledge", "I understand", "I accept",
               "Yes", "Agree", "Accept", "Acknowledge", "Acknowledged", "Confirm", "I confirm"]
CONSENT_RE = re.compile(r"\bconsent|\backnowledg|\bi agree\b|agree to (the |our |this )?(terms|privacy|polic|notice)|"
                        r"\bcertify\b|\battest\b|privacy (policy|notice|statement)|terms (of|and) |\bi understand\b|"
                        r"\bi confirm\b|(accurate|true),? and complete", re.I)


def is_consent(q: dict) -> bool:
    if q["kind"] not in ("checkbox", "radio", "select", "combobox"):
        return False
    return bool(CONSENT_RE.search(q["label"])) or any(CONSENT_RE.search(o) for o in q.get("options", [])[:3])


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9'+#/ ]", " ", (s or "").lower())).strip()


def pick_option(options: list[str], candidates: list[str], loose: bool = True) -> str | None:
    """The option best matching the first candidate that matches anything."""
    opts = [(o, norm(o)) for o in options if norm(o)]
    cands = [norm(c) for c in candidates if norm(c)]
    # Exact matches for every candidate first: "WA" must beat "Washington" → "Washington, D.C.".
    tests = [lambda n, c: n == c,
             lambda n, c: n.startswith(c + " ") or n.startswith(c + ","),
             lambda n, c: len(c) > 3 and re.search(rf"(^| ){re.escape(c)}( |$)", n)]
    for test in tests if loose else tests[:2]:
        for c in cands:
            for o, n in opts:
                if test(n, c):
                    return o
    return None


def _yes_no(v: str) -> list[str]:
    return [v] + (["Yes, I am", "I am authorized", "True"] if v.lower() == "yes" else ["No, I am not", "I am not", "False"])


def _decline_or(v: str) -> list[str]:
    return [v] + DECLINE if any(d in v.lower() for d in DECLINE) else [v]


class Profile:
    def __init__(self, cfg: dict, answers: dict, files: dict, job_kind: str = "intern"):
        self.c, self.d, self.learned, self.files = cfg, answers["defaults"], answers.get("learned", []), files
        self.job_kind = job_kind  # "intern" or "ng": interns may report a later (delayed) graduation

    def graduation(self) -> str:
        c = self.c
        if self.job_kind == "ng":
            return c.get("graduation_ng") or c.get("graduation", "")
        return c.get("graduation_intern") or c.get("graduation", "")

    def graduation_day(self) -> str:
        """Graduation as an exact MM/DD/YYYY, for fields that want a day. Uses the
        graduation_intern_date / graduation_ng_date setting; falls back to the month setting."""
        key = "graduation_ng_date" if self.job_kind == "ng" else "graduation_intern_date"
        return self.c.get(key) or self.graduation()

    def _location(self) -> str:
        return ", ".join(x for x in (self.c.get("city"), self.c.get("state")) if x)

    def answer(self, q: dict):
        """Return (value, source) or (None, None) if unknown. value is a str, a list of option
        candidates (choice kinds), SKIP, RESUME or LETTER."""
        label, kind = norm(q["label"]), q["kind"]
        c, d = self.c, self.d
        choice = kind in CHOICE_KINDS

        def val(v, src="settings"):
            if v is None or v == "":
                return None, None
            return v, src

        if kind == "file":
            label = f"{label} {norm(q.get('hint', '').replace('_', ' '))}"
            if "autofill" in label:
                return SKIP, "rule"
            if re.search(r"cover letter", label):
                return (LETTER, "file") if self.files.get("letter") else (SKIP, "no letter")
            if re.search(r"resume|cv\b|curriculum", label) or not label:
                return RESUME, "file"
            return None, None

        if kind == "textarea" and re.search(r"cover letter|letter of (interest|motivation)|motivation letter", label):
            text = self.files.get("letter_text")
            return (text, "letter") if text else (None, None)  # no letter yet → Claude / the user writes it

        for item in self.learned:  # the user's own past answers win over generic rules
            if item.get("match") and norm(item["match"]) in label:
                a = item.get("answer")
                return ([a] if choice and isinstance(a, str) else a), "learned"

        if kind in ("text", "") and re.search(r"^(legal name|full legal name|signature|electronic signature|e-?signature|"
                                             r"type your (full |legal )?name|sign(ed)? here)$", label):
            return SIGNATURE, "signature"  # typing a name here signs the agreements above: the user does that
        if is_consent(q):
            # The user asked us to tick required consent / acknowledgement boxes; the panel lists
            # each one with a summary. Optional ones (job alerts, SMS, marketing) stay unticked.
            if not q.get("required") or re.search(r"marketing|newsletter|job alert|text message|\bsms\b|promotional", label):
                return SKIP, "optional consent"
            return CONSENT_YES, "consent"
        if re.search(r"\b(sponsor|visa|immigration)", label) or \
                re.search(r"(employer|company) (support|assistance).{0,60}(authori[sz]ation|work)", label):
            key = "sponsorship_future" if re.search(r"future|now or|will you|maintain", label) else "sponsorship_now"
            return val(_yes_no(d[key]) if choice else d[key], "answers")
        if re.search(r"authori[sz]ed to work|legally (authorized|eligible|able)|eligible to work|right to work|work authori[sz]ation", label):
            return val(_yes_no(d["authorized_us"]) if choice else d["authorized_us"], "answers")
        if re.search(r"how (did )?you (hear|heard|find|found|learn)|where did you (hear|find|see)|^source\b|referral source", label):
            return val([d["how_heard"], "Careers", "Company website", "Website", "Job board", "Other"] if choice else d["how_heard"], "answers")
        if re.search(r"\breferred\b|referral", label):
            return (["No"], "rule") if choice else (SKIP, "rule")
        if re.search(r"previously (worked|been employed)|ever (worked|been employed)|former employee|currently (employed|work) (at|by|for)", label):
            return val(_yes_no(d["previously_employed"]) if choice else d["previously_employed"], "answers")
        if re.search(r"hispanic|latin[oa]", label):
            return val(_decline_or(d["hispanic"]), "answers")
        if re.search(r"\brace\b|ethnicit", label):
            return val(_decline_or(d["race"]), "answers")
        if re.search(r"gender|\bsex\b", label):
            return val(_decline_or(d["gender"]), "answers")
        if re.search(r"veteran", label):
            v = d["veteran"]
            if re.search(r"\bnot\b", v, re.I) and not any(x in v.lower() for x in DECLINE):
                # "Not a protected veteran" = not a veteran. Never land on "I identify as a veteran,
                # just not a protected veteran", which says the opposite.
                return val(["I am not a veteran", "I am not a protected veteran", "not a veteran", "No"], "answers")
            return val(_decline_or(v), "answers")
        if re.search(r"disabilit", label):
            return val(_decline_or(d["disability"]), "answers")
        if re.search(r"sexual orientation|transgender|lgbt|pronoun", label):
            return (DECLINE, "rule") if choice else (SKIP, "rule")
        if re.search(r"18 years|age of 18|at least 18", label):
            return (["Yes"], "rule") if choice else ("Yes", "rule")
        if re.search(r"full[- ]time", label) and re.search(r"availab|able|commit", label):
            return (["Yes"], "rule") if choice else ("Yes", "rule")

        if re.search(r"notice period|how soon (can|could) you start", label) and choice and d.get("available_start"):
            from datetime import date as _date, datetime as _dt
            try:
                start = _dt.strptime(d["available_start"], "%B %d, %Y").date()
                weeks = max(0, (start - _date.today()).days // 7)
            except ValueError:
                weeks = None
            if weeks is not None:
                for o in q.get("options", []):
                    nums = [int(x) for x in re.findall(r"\d+", o)]
                    if (re.search(r"immediate", o, re.I) and weeks <= 1) or \
                       (len(nums) == 2 and nums[0] <= weeks <= nums[1]) or \
                       (re.search(r"more than|over|\+", o, re.I) and nums and weeks > nums[0]):
                        return [o], "answers (weeks until available_start)"
        if re.search(r"current(ly)? (a |an )?(university |college )?student|currently enrolled", label):
            return (["Yes"], "rule") if choice else ("Yes", "rule")
        if re.search(r"(former|current|previous)[/ a-z]{0,12}(intern|contractor|employee)", label):
            return val(_yes_no(d["previously_employed"]) if choice else d["previously_employed"], "answers")
        if re.search(r"text messages|\bsms\b|marketing|newsletter|other job opportunities|talent community", label) and not q.get("required"):
            return SKIP, "optional"
        if re.search(r"(available|availability) to start|earliest (possible )?start|start date|when can you start|available start", label):
            v = d.get("available_start", "")
            return (val([v] if choice else v, "answers")) if v else (None, None)
        if re.search(r"phone (device )?type|type of phone", label):
            return (["Mobile", "Cell", "Cellular", "Mobile Phone", "Home Cellular", "Personal Cell"], "rule") if choice else ("Mobile", "rule")
        if re.search(r"middle name|name suffix|^suffix", label):
            return SKIP, "rule"
        if re.search(r"preferred (first )?name|nickname", label):
            return val(c.get("preferred_name") or c.get("first_name"))
        if re.search(r"first name|given name|^first$", label):
            return val(c.get("first_name"))
        if re.search(r"last name|family name|surname|^last$", label):
            return val(c.get("last_name"))
        if re.search(r"^(full |legal |your )?name$|^full name|^legal name", label):
            return val(f"{c.get('first_name', '')} {c.get('last_name', '')}".strip())
        if re.search(r"e ?mail", label):
            return val(c.get("email"))
        if re.search(r"phone|mobile|cell", label) and kind != "select":
            return val(c.get("phone"))
        if re.search(r"linkedin", label):
            return val(c.get("linkedin"))
        if re.search(r"github", label):
            return val(c.get("github"))
        if re.search(r"website|portfolio|personal (site|url)|blog", label):
            return val(c.get("website") or c.get("github"))
        if re.search(r"twitter|\bx\.com|instagram|facebook", label):
            return SKIP, "rule"
        if re.search(r"current (company|employer)|^company$|^organization$|^org$", label):
            return SKIP, "rule"
        if re.search(r"^country|country of residence", label):
            return val([c.get("country", "United States"), "United States", "USA", "US"] if choice else c.get("country"))
        if re.search(r"state of residence|^state\b|^province", label):
            st = c.get("state", "")
            return val([STATES.get(st.upper(), st), st] if choice else STATES.get(st.upper(), st))
        if label == "city":
            return val([c.get("city", "")] if choice else c.get("city"))
        if re.search(r"location|city|where are you (based|located)|current address|^address", label) \
                and not re.search(r"closest|nearest|prefer|willing|relocat|which (office|location)", label):
            return val([self._location(), c.get("city", "")] if choice else self._location())
        if re.search(r"graduat|completion date|expected (grad|completion)", label) and not re.search(r"high school", label):
            g = self.graduation()
            year = (re.findall(r"20\d\d", g) or [""])[0]
            if re.search(r"\byear\b", label) and not re.search(r"\bdate\b|\bday\b|mm/dd|dd/mm|month", label):
                return val([year, g] if choice else year)
            # A field that wants a day (date input, calendar picker, "date" / "MM/DD" in the
            # label) gets the exact day; month-only fields keep "Dec 2027".
            wants_day = kind == "date" or (not choice and re.search(r"\bdate\b|\bday\b|mm/dd|dd/mm", label)
                                            and not re.search(r"month|mm/yy", label))
            if wants_day:
                day = self.graduation_day()
                if kind == "date":  # <input type=date> only accepts YYYY-MM-DD
                    from datetime import datetime as _dt
                    # month-only fallback ("May 2027") becomes the 1st of that month
                    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%b %Y", "%B %Y"):
                        try:
                            day = _dt.strptime(day, fmt).strftime("%Y-%m-%d")
                            break
                        except ValueError:
                            continue
                return val(day)
            return val([g, year] if choice else g)
        if re.search(r"school|university|college|institution", label) and not re.search(r"high school", label):
            return val([c.get("school", "")] if choice else c.get("school"))
        if re.search(r"degree|level of education|education level", label):
            names = DEGREES.get(c.get("degree", ""), [])
            return val(names if choice else (names[0] if names else None))
        if re.search(r"major|field of study|area of study|discipline|concentration", label):
            return val(c.get("major"))
        return None, None


def job_kind(title: str) -> str:
    """'intern' for internships / co-ops / fellowships, else 'ng' (new grad / full-time)."""
    return "intern" if re.search(r"\b(intern(ship)?|co-?op|fellow(ship)?|summer|winter|apprentice)", title or "", re.I) else "ng"
