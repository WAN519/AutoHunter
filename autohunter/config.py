"""Load the shared company list and the current user's private config."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .presets import EXCLUDE_TITLE_KEYWORDS, INTERN_TITLE_KEYWORDS, ROLE_PRESETS

ROOT = Path(__file__).resolve().parent.parent


def load_companies() -> dict:
    return json.loads((ROOT / "companies.json").read_text(encoding="utf-8"))


def boards_for(companies: dict, tags: list[str]) -> dict[str, list[str]]:
    """{source: [token, ...]}, restricted to boards carrying any of `tags` (all if empty)."""
    out = {}
    for src in ("greenhouse", "lever", "ashby", "workday", "smartrecruiters", "hn"):
        out[src] = [t for t, tt in companies.get(src, {}).items() if not tags or set(tags) & set(tt)]
    return out


def nonprofit_tokens(companies: dict) -> set[str]:
    return {t for src in ("greenhouse", "lever", "ashby")
            for t, tags in companies.get(src, {}).items() if "nonprofit" in tags}


def load_user(me: Path) -> dict:
    path = me / "config.json"
    if not path.exists():
        sys.exit(f"No {path}. Run /setup in Claude Code first (or copy config.example.json there).")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    unknown = [r for r in cfg.get("roles", []) if r not in ROLE_PRESETS]
    if unknown:
        sys.exit(f"Unknown roles {unknown} in {path}. Choose from: {', '.join(ROLE_PRESETS)}")
    return cfg


def topic_groups(cfg: dict) -> dict[str, list[str]]:
    groups = {r: ROLE_PRESETS[r] for r in cfg.get("roles", [])}
    groups.update(cfg.get("extra_topics", {}))
    return groups


def title_rules(cfg: dict) -> tuple[list[str], list[str]]:
    exclude = EXCLUDE_TITLE_KEYWORDS + cfg.get("exclude_title_keywords", [])
    if cfg.get("degree") != "phd":
        exclude = exclude + ["phd"]
    return INTERN_TITLE_KEYWORDS, exclude
