"""Deterministic rules applied on top of Claude's reading of each listing.

Claude extracts facts (eligibility, time zone, pay, engagement). These rules
compare them with your settings, so changing a setting never needs re-scoring.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .settings import ELIGIBILITY_ORDER

CAIRO = ZoneInfo("Africa/Cairo")

ZONE_ALIASES = {
    "pt": "America/Los_Angeles", "pst": "America/Los_Angeles", "pdt": "America/Los_Angeles",
    "pacific": "America/Los_Angeles",
    "mt": "America/Denver", "mst": "America/Denver", "mdt": "America/Denver", "mountain": "America/Denver",
    "ct": "America/Chicago", "cst": "America/Chicago", "cdt": "America/Chicago", "central": "America/Chicago",
    "et": "America/New_York", "est": "America/New_York", "edt": "America/New_York", "eastern": "America/New_York",
    "gmt": "Europe/London", "uk": "Europe/London", "bst": "Europe/London",
    "cet": "Europe/Berlin", "cest": "Europe/Berlin",
}


# Rough USD rates — only used to compare listed pay with your minimum.
FX = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CAD": 0.73, "AUD": 0.66, "NZD": 0.60, "CHF": 1.12, "SGD": 0.75,
      "AED": 0.27, "SAR": 0.27, "QAR": 0.27, "EGP": 0.021, "INR": 0.012, "PLN": 0.25, "SEK": 0.095,
      "NOK": 0.093, "DKK": 0.145, "ILS": 0.27, "TRY": 0.03, "BRL": 0.18, "MXN": 0.055, "ZAR": 0.055}
SYMBOLS = [("US$", "USD"), ("CA$", "CAD"), ("C$", "CAD"), ("A$", "AUD"), ("NZ$", "NZD"), ("S$", "SGD"),
           ("€", "EUR"), ("£", "GBP"), ("₹", "INR"), ("$", "USD")]


def pay_from_text(text: str, hours_per_year: int = 2000) -> tuple[float, float] | None:
    """(min, max) USD per year parsed from free-text pay, or None if no amount is stated."""
    if not text:
        return None
    t = text.replace(",", "")
    code = re.search(r"\b(" + "|".join(FX) + r")\b", t.upper())
    currency = code.group(1) if code else next((c for sym, c in SYMBOLS if sym in t), None)
    if not currency:
        return None
    amounts = []
    for num, k in re.findall(r"(\d+(?:\.\d+)?)\s*([kK])?\b", t):
        value = float(num) * (1000 if k else 1)
        if value >= 5:
            amounts.append(value)
    if not amounts:
        return None
    low = t.lower()
    if re.search(r"/\s*h(ou)?r|per hour|hourly|an hour|/h\b", low):
        factor = hours_per_year
    elif re.search(r"/\s*mo|per month|monthly|a month", low):
        factor = 12
    else:
        factor = 1
    lo, hi = min(amounts) * factor * FX[currency], max(amounts) * factor * FX[currency]
    if hi < 1000:  # e.g. a stray small number with no clear period
        return None
    return lo, hi


def prefilter(title: str, search: dict, fit: dict | None = None) -> str:
    """'ok', or the reason the title alone rules the job out (saves requests and tokens)."""
    t = title.lower()
    native = re.search(r"android|kotlin|\bnative (android|mobile)\b", t)
    for focus, pattern in (("flutter", r"flutter"), ("react-native", r"react[ -]?native")):
        if fit and focus in fit.get("exclude_role_focus", []) and re.search(pattern, t) and not native:
            return f"{focus.replace('-', ' ').title()}-first title"
    if not re.search(search["title_must_match"], t):
        return "title doesn't match your roles"
    m = re.search(search["title_exclude"], t)
    if m:
        return f"title contains '{m.group(0)}'"
    if not search.get("include_ios_only_titles"):
        ios_only = re.search(r"\bios\b|swift", t) and not re.search(
            r"android|mobile|kotlin|flutter|react|cross|multi", t
        )
        if ios_only:
            return "iOS-only title"
    return "ok"


def _zone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    key = name.strip()
    key = ZONE_ALIASES.get(key.lower(), key)
    try:
        return ZoneInfo(key)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _hhmm(value: str) -> tuple[int, int]:
    h, m = (value or "0:0").split(":")
    return int(h), int(m)


def _user_window(fit: dict, day: date) -> tuple[datetime, datetime]:
    sh, sm = _hhmm(fit["work_window_start"])
    eh, em = _hhmm(fit["work_window_end"])
    start = datetime(day.year, day.month, day.day, sh, sm, tzinfo=CAIRO)
    end = datetime(day.year, day.month, day.day, eh, em, tzinfo=CAIRO)
    if end <= start:  # e.g. 09:00 -> 00:00 runs past midnight
        end += timedelta(days=1)
    return start, end


def timezone_check(screen: dict, fit: dict, today: date | None = None) -> tuple[str, str]:
    """('yes'|'no'|'unclear', human explanation in Cairo time)."""
    raw = (screen.get("tz_zone") or "").strip().lower()
    if raw in ("", "none", "async", "any", "flexible"):
        return "yes", screen.get("tz_text") or "no time-zone requirement stated"
    zone = _zone(screen.get("tz_zone"))
    if zone is None:
        return "unclear", screen.get("tz_text") or "time zone unclear"
    today = today or date.today()
    start_h = screen.get("tz_window_start")
    end_h = screen.get("tz_window_end")
    overlap = screen.get("tz_overlap_hours")
    start_h = 9 if start_h is None else float(start_h)
    end_h = 17 if end_h is None else float(end_h)
    job_start = datetime(today.year, today.month, today.day, tzinfo=zone) + timedelta(hours=start_h)
    job_end = datetime(today.year, today.month, today.day, tzinfo=zone) + timedelta(hours=end_h)
    if job_end <= job_start:
        job_end += timedelta(days=1)
    js, je = job_start.astimezone(CAIRO), job_end.astimezone(CAIRO)
    ws, we = _user_window(fit, js.date())
    if js < ws and _user_window(fit, js.date() - timedelta(days=1))[1] > js:
        ws, we = _user_window(fit, js.date() - timedelta(days=1))
    shared = max(timedelta(0), min(je, we) - max(js, ws)).total_seconds() / 3600
    window = f"{js:%H:%M}–{je:%H:%M} Cairo"
    if overlap:
        ok = shared + 1e-6 >= float(overlap)
        return ("yes" if ok else "no"), f"needs {overlap:g}h overlap with {window}; you can cover {shared:.1f}h"
    needed = (je - js).total_seconds() / 3600
    ok = shared + 1e-6 >= needed
    return ("yes" if ok else "no"), f"works {window}; you can cover {shared:.1f}h of {needed:.1f}h"


def evaluate(job: dict, settings: dict) -> dict:
    """Combine Claude's facts with settings into a status: match | excluded | pending."""
    fit = settings["fit"]
    screen = job.get("screen")
    reasons: list[str] = []
    if job.get("prefilter") not in (None, "ok"):
        return {"status": "excluded", "reasons": [job["prefilter"]], "tz": None}
    if job.get("closed"):
        return {"status": "excluded", "reasons": ["no longer accepting applications"], "tz": None}
    if not screen:
        return {"status": "pending", "reasons": [], "tz": None}

    if not screen.get("relevant", True):
        reasons.append("not a mobile engineering role")
    if screen.get("role_focus") in fit.get("exclude_role_focus", []):
        reasons.append(f"role is {screen['role_focus']}-first")

    blocked = next((b for b in fit.get("blocked_companies", []) if b.strip() and re.search(
        rf"\b{re.escape(b.strip())}\b", job.get("company") or "", re.I)), None)
    if blocked:
        reasons.append(f"company blocked ({blocked})")
    skipped = sorted(set(screen.get("industries") or []) & set(fit.get("exclude_industries", [])))
    if skipped:
        reasons.append(f"industry: {', '.join(skipped)}")

    elig = screen.get("egypt_eligible", "unclear")
    floor = fit.get("min_eligibility", "unclear")
    if ELIGIBILITY_ORDER.index(elig) > ELIGIBILITY_ORDER.index(floor):
        reasons.append(f"Egypt eligibility: {elig} — {screen.get('eligibility_evidence', '')}".strip(" —"))

    eng = screen.get("engagement", "unclear")
    if eng not in ("unclear", "") and eng not in fit["engagement"]:
        reasons.append(f"engagement is {eng}")

    pay_max = screen.get("pay_max_usd_year") or screen.get("pay_min_usd_year")
    if not pay_max:
        parsed = pay_from_text(screen.get("pay_text", ""), fit.get("hours_per_year", 2000)) or pay_from_text(
            job.get("salary_text") or "", fit.get("hours_per_year", 2000))
        pay_max = parsed[1] if parsed else None
    pay_flag = None
    if pay_max and fit.get("min_pay_usd_year") and pay_max < fit["min_pay_usd_year"]:
        pay_flag = f"pay up to ${pay_max:,.0f}/yr is below your ${fit['min_pay_usd_year']:,.0f}"
        if fit.get("below_min_pay", "drop") == "drop":
            reasons.append(pay_flag)

    tz_ok, tz_note = timezone_check(screen, fit)
    if tz_ok == "no" or (tz_ok == "unclear" and fit.get("unclear_timezone") == "drop"):
        reasons.append(f"time zone: {tz_note}")

    result = {"status": "excluded" if reasons else "match", "reasons": reasons, "tz": [tz_ok, tz_note]}
    if pay_flag and not reasons:
        result["flags"] = [pay_flag]
    return result
