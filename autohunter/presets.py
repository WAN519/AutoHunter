"""Keyword presets per role family. A user's config picks families by name in
`roles`, and can add their own groups under `extra_topics`."""

ROLE_PRESETS: dict[str, list[str]] = {
    "ai-engineer": [
        "ai engineer", "llm", "agent", "agentic", "genai", "generative ai", "applied ai",
        "rag", "retrieval", "prompt", "nlp", "foundation model",
    ],
    "ml-infra": [
        "ml infra", "machine learning infra", "ml platform", "inference", "training infra",
        "distributed", "gpu", "kubernetes", "serving", "mlops", "infrastructure",
    ],
    "machine-learning": [
        "machine learning", "ml engineer", "deep learning", "computer vision", "pytorch",
        "applied scientist", "research engineer", "modeling",
    ],
    "data-science": [
        "data science", "data scientist", "statistic", "experimentation", "a/b test",
        "causal", "forecast", "predictive", "analytics", "machine learning",
    ],
    "data-analyst": [
        "data analyst", "business analyst", "analytics", "sql", "tableau", "power bi",
        "dashboard", "business intelligence", "insights",
    ],
    "data-engineering": [
        "data engineer", "etl", "pipeline", "spark", "airflow", "dbt", "warehouse", "data platform",
    ],
    "software-engineer": [
        "software engineer", "backend", "full stack", "full-stack", "swe", "developer",
    ],
    "eval-quality": [
        "eval", "evaluation", "benchmark", "quality", "test automation", "reliability",
        "red team", "safety",
    ],
}

INTERN_TITLE_KEYWORDS = [
    "intern", "internship", "co-op", "coop", "working student", "student researcher",
    "apprentice", "fellow",
]

# Titles that are almost never a technical student role.
EXCLUDE_TITLE_KEYWORDS = [
    "high school", "revenue", "legal", "medical", "sales", "marketing", "finance",
    "recruiting", "people", "design", "product management", "technical writer",
    "civil liberties", "account", "firmware", "electrical", "mechanical", "hardware",
]

# A location that only matched "remote" is rejected if it names one of these.
NON_US_PLACES = [
    "canada", "toronto", "ontario", "montreal", "quebec", "vancouver", "uk", "united kingdom",
    "london", "europe", "emea", "germany", "berlin", "france", "paris", "ireland", "netherlands",
    "amsterdam", "poland", "spain", "india", "bangalore", "bengaluru", "singapore", "japan",
    "china", "korea", "australia", "israel", "mexico", "brazil", "latam", "apac", "dubai", "uae",
]

# Simplify list markers -> meaning.
SIMPLIFY_FLAGS = {
    "🛂": "no-sponsorship",
    "🇺🇸": "us-citizen-only",
    "🎓": "advanced-degree",
    "🔥": "faang",
    "🔒": "closed",
}
