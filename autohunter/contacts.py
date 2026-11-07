"""Google "X-ray" search links for finding people at a company.

We deliberately do NOT scrape LinkedIn (against its ToS, risks your account).
These are links you open yourself in a browser.
"""
from __future__ import annotations

from urllib.parse import quote_plus

ROLES = {
    "recruiter": '("university recruiter" OR "technical recruiter" OR "campus recruiter" OR "talent")',
    "hiring_manager": '("engineering manager" OR "head of" OR "tech lead" OR "manager") ({topic})',
}


def display_name(token: str, names: dict[str, str]) -> str:
    if token in names:
        return names[token]
    return token if any(c.isupper() or c == " " for c in token) else token.capitalize()


def xray_links(company: str, school: str, topic: str = '"data" OR "ML" OR "AI"') -> dict[str, str]:
    queries = {
        "recruiter": ROLES["recruiter"],
        "hiring_manager": ROLES["hiring_manager"].format(topic=topic),
    }
    if school:
        queries["alumni"] = f'"{school}"'
    return {
        role: "https://www.google.com/search?q=" + quote_plus(f'site:linkedin.com/in "{company}" {q}')
        for role, q in queries.items()
    }
