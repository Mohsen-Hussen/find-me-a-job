"""User settings: defaults merged with data/settings.json (edited from the dashboard)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SETTINGS_FILE = DATA / "settings.json"
CV_TEXT_FILE = DATA / "cv.txt"
CV_PDF_FILE = DATA / "cv.pdf"
DB_FILE = DATA / "jobs.db"

DEFAULTS: dict = {
    "profile": {
        "based_in": "Egypt (Cairo time)",
        "citizenship": "Egyptian and New Zealand",
        "goal": "Work remotely from Egypt for a US-based company (contractor or full-time via an employer-of-record).",
        "primary_skills": "Android: Kotlin, Jetpack Compose, Coroutines, server-driven UI, SDKs, mobile architecture, CI/CD, team leadership.",
        "secondary_skills": "React Native and Flutter (some hands-on experience) — fine as a plus on a native Android role, but not looking for React Native- or Flutter-first roles.",
        "rusty_skills": "iOS (Swift/SwiftUI/Objective-C): strong years ago but not interview-ready now. iOS-heavy roles are a poor fit.",
        "notes": "",
    },
    "search": {
        "terms": [
            "Senior Android Developer",
            "Senior Mobile Developer",
            "Mobile Team Lead",
            "Mobile Lead",
            "Mobile Engineer",
        ],
        "locations": ["Worldwide", "United States", "Egypt", "EMEA"],
        "add_remote_keyword": True,
        "first_run_days": 7,
        "max_pages": 3,
        "include_ios_only_titles": False,
        "title_must_match": r"android|mobile|kotlin|flutter|react[ -]?native|\bios\b|\bapp (developer|engineer)|\bsdks?\b",
        "title_exclude": r"junior|\bjr\b|intern|graduate|trainee|entry[ -]level|apprentice|\bqa\b|tester|test engineer|sdet|designer|product manager|marketing|sales|recruit|back[- ]?end|data engineer|devops|technician|hybrid|on-?site|in[- ]office",
    },
    "sources": {
        "linkedin": True,
        "himalayas": True,
        "himalayas_country": "Egypt",
    },
    "fit": {
        "work_window_start": "09:00",
        "work_window_end": "00:00",
        "unclear_timezone": "keep",
        "engagement": ["full-time", "contract"],
        "min_pay_usd_year": 120000,
        "hours_per_year": 2000,
        "below_min_pay": "drop",
        "min_eligibility": "unclear",
        "exclude_industries": ["fintech", "banking", "crypto", "dating"],
        "exclude_role_focus": ["react-native", "flutter"],
        "blocked_companies": ["Deed"],
        "email_min_score": 70,
    },
    "schedule": {
        "enabled": True,
        "interval_minutes": 30,
        "run_on_open_after_minutes": 30,
    },
    "email": {
        "to": "",
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 465,
        "smtp_user": "",
    },
    "scoring": {
        "screen_model": "haiku",
        "screen_effort": "low",
        "assess_model": "sonnet",
        "assess_effort": "medium",
        "concurrency": 4,
    },
    "ui": {
        "app_name": "Job Radar",
    },
    "server": {
        "allowed_hosts": [],
        "public_url": "http://localhost:8765",
    },
}

ELIGIBILITY_ORDER = ["yes", "likely", "unclear", "unlikely", "no"]


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load() -> dict:
    DATA.mkdir(exist_ok=True)
    saved = {}
    if SETTINGS_FILE.exists():
        saved = json.loads(SETTINGS_FILE.read_text())
    return _merge(DEFAULTS, saved)


def save(settings: dict) -> dict:
    merged = _merge(DEFAULTS, settings)
    DATA.mkdir(exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(merged, indent=2))
    return merged


def cv_text() -> str:
    return CV_TEXT_FILE.read_text() if CV_TEXT_FILE.exists() else ""


def assess_fingerprint(settings: dict) -> str:
    """Changes when the CV or profile changes, so stale fit scores can be redone."""
    from .scoring import RUBRIC_VERSION

    blob = json.dumps(settings["profile"], sort_keys=True) + cv_text() + RUBRIC_VERSION
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


def save_cv_pdf(pdf_bytes: bytes) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if len(text) < 200:
        raise ValueError("Could not read text from this PDF (is it a scanned image?)")
    DATA.mkdir(exist_ok=True)
    CV_PDF_FILE.write_bytes(pdf_bytes)
    CV_TEXT_FILE.write_text(text)
    return text
