"""
config_loader.py
Loads and validates config.json for the OpportunityBot engine.
"""
import json
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any

# Resolve project root (two levels up from this file: job_hunter/ -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"
RESUMES_DIR = PROJECT_ROOT / "resumes"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = DATA_DIR / "reports"


@dataclass
class ResumeProfile:
    id: str
    name: str
    filename: str
    target_roles: List[str]
    extracted_skills: List[str]
    last_updated: str = ""
    # Cache of the last successful LLM parse, keyed by a hash of the PDF
    # bytes — lets the engine skip re-parsing (and re-spending LLM quota)
    # when the resume file hasn't changed since the last run.
    resume_hash: str = ""
    extracted_full: Dict[str, Any] = field(default_factory=dict)

    @property
    def pdf_path(self) -> Path:
        return RESUMES_DIR / self.filename


@dataclass
class Config:
    # Profile
    user_name: str = ""
    branch: str = ""
    graduation_year: int = 2027
    college: str = ""

    # Email
    sender_email: str = ""
    recipient_email: str = ""
    send_time_ist: str = "07:00"

    # Preferences
    locations: List[str] = field(default_factory=lambda: ["Bengaluru"])
    job_types: List[str] = field(default_factory=lambda: ["Internship", "Full-time"])
    min_salary_lpa: float = 0.0
    min_match_percent: int = 40
    batch_year: int = 2027

    # Watchlist
    watchlist_companies: List[str] = field(default_factory=list)

    # Sources
    enabled_sources: Dict[str, bool] = field(default_factory=lambda: {
        "linkedin": True, "indeed": True, "glassdoor": True,
        "naukri": True, "wellfound": True, "internshala": True,
        "unstop": True, "yc_jobs": True, "hackernews": True, "cutshort": True
    })

    # Resume profiles
    resume_profiles: List[ResumeProfile] = field(default_factory=list)


def load_config() -> Config:
    """Load and parse config.json into a Config dataclass."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"config.json not found at {CONFIG_PATH}")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    profiles = [
        ResumeProfile(
            id=p["id"],
            name=p["name"],
            filename=p["filename"],
            target_roles=p.get("target_roles", []),
            extracted_skills=p.get("extracted_skills", []),
            last_updated=p.get("last_updated", ""),
            resume_hash=p.get("resume_hash", ""),
            extracted_full=p.get("extracted_full", {}) or {},
        )
        for p in raw.get("resume_profiles", [])
    ]

    cfg = Config(
        user_name=raw.get("profile", {}).get("name", ""),
        branch=raw.get("profile", {}).get("branch", ""),
        graduation_year=raw.get("profile", {}).get("graduation_year", 2027),
        college=raw.get("profile", {}).get("college", ""),
        sender_email=raw.get("email", {}).get("sender_email", ""),
        recipient_email=raw.get("email", {}).get("recipient_email", ""),
        send_time_ist=raw.get("email", {}).get("send_time_ist", "07:00"),
        locations=raw.get("preferences", {}).get("locations", ["Bengaluru"]),
        job_types=raw.get("preferences", {}).get("job_types", ["Internship", "Full-time"]),
        min_salary_lpa=raw.get("preferences", {}).get("min_salary_lpa", 0),
        min_match_percent=raw.get("preferences", {}).get("min_match_percent", 40),
        batch_year=raw.get("preferences", {}).get("batch_year", 2027),
        watchlist_companies=raw.get("watchlist_companies", []),
        enabled_sources=raw.get("enabled_sources", {}),
        resume_profiles=profiles,
    )
    return cfg


def save_resume_cache(profile_id: str, resume_hash: str, extracted_full: Dict[str, Any]) -> None:
    """Persist a fresh resume parse into config.json so the next run can
    skip calling the LLM again for an unchanged PDF. Only touches the one
    matching resume_profiles entry — re-reads the file first so we don't
    clobber unrelated settings someone else (e.g. the Streamlit app) saved
    since this process started."""
    if not CONFIG_PATH.exists():
        return

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    found = False
    for p in raw.get("resume_profiles", []):
        if p.get("id") == profile_id:
            p["resume_hash"] = resume_hash
            # Never persist the raw resume text — only the structured parse.
            p["extracted_full"] = {k: v for k, v in extracted_full.items() if k != "_raw_text"}
            found = True
            break

    if not found:
        return

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)


def get_openrouter_api_key() -> str:
    """Fetch OPENROUTER_API_KEY from environment."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise EnvironmentError("OPENROUTER_API_KEY environment variable not set.")
    return key


def get_gmail_app_password() -> str:
    pwd = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not pwd:
        raise EnvironmentError("GMAIL_APP_PASSWORD environment variable not set.")
    return pwd


def get_serpapi_key() -> str:
    key = os.environ.get("SERPAPI_API_KEY", "")
    return key


def ensure_dirs():
    """Create necessary data directories if they don't exist."""
    for d in [DATA_DIR, REPORTS_DIR, RESUMES_DIR]:
        d.mkdir(parents=True, exist_ok=True)
