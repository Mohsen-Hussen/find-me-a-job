"""Himalayas remote-jobs API (free, no key). Each job lists the countries and
UTC offsets it accepts, so a country filter (e.g. Egypt) pre-screens eligibility.
Terms: credit Himalayas and link back to the listing (https://himalayas.app/api).
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .linkedin import UA, _description_text

API = "https://himalayas.app/jobs/api/search"


def _get(params: dict) -> list[dict]:
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read()).get("jobs", [])


def _posted(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _offsets(values: list) -> str:
    if not values or len(values) >= 30:
        return "any time zone"
    return "UTC" + ", ".join(f"{v:+g}" for v in sorted(values))


def search(term: str, country: str, since: datetime, max_pages: int, log=print) -> list[dict]:
    jobs: list[dict] = []
    for page in range(1, max_pages + 1):
        try:
            batch = _get({"q": term, "country": country, "sort": "recent", "page": page})
        except Exception as err:  # Himalayas is a bonus source; never fail the run
            log(f"  Himalayas error for '{term}': {err}")
            break
        if not batch:
            break
        too_old = 0
        for j in batch:
            posted = _posted(j.get("pubDate"))
            if posted and posted < since:
                too_old += 1
                continue
            places = j.get("locationRestrictions") or []
            where = ", ".join(places) if places else "Worldwide"
            salary = ""
            if j.get("minSalary") or j.get("maxSalary"):
                salary = f"{j.get('minSalary') or ''}–{j.get('maxSalary') or ''} {j.get('currency') or ''} {j.get('salaryPeriod') or ''}".strip()
            seniority = j.get("seniority")
            seniority = ", ".join(seniority) if isinstance(seniority, list) else (seniority or "n/a")
            header = (
                f"[Himalayas listing] Open to candidates in: {where}. "
                f"Time zones accepted: {_offsets(j.get('timezoneRestrictions'))}. "
                f"Employment type: {j.get('employmentType') or 'n/a'}. Seniority: {seniority}.\n\n"
            )
            guid = str(j.get("guid") or j.get("applicationLink"))
            jobs.append(
                {
                    "id": "him-" + hashlib.sha1(guid.encode()).hexdigest()[:14],
                    "source": "himalayas",
                    "title": j.get("title") or "",
                    "company": j.get("companyName") or "",
                    "location": f"Remote ({where})",
                    "url": guid if guid.startswith("http") else (j.get("applicationLink") or ""),
                    "posted_date": posted.date().isoformat() if posted else "",
                    "salary_text": salary,
                    "description": header + _description_text(j.get("description") or j.get("excerpt") or ""),
                    "criteria": {
                        "Employment type": j.get("employmentType") or "",
                        "Seniority": seniority,
                    },
                }
            )
        if too_old == len(batch):
            break
        time.sleep(1.5)
    return jobs
