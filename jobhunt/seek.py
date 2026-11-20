"""Seek New Zealand job search (public endpoints, no key, no login).

Two calls per listing of interest:
  * the logged-out search API (nz.seek.com/api/jobsearch/v5) for the cards, and
  * Seek's public GraphQL endpoint for the full job description.

No Seek account is used, so your account is never involved. Seek NZ is a New
Zealand board — most roles are onsite/hybrid and need NZ work rights. The
listing header states that, and Claude's eligibility screen decides per job
whether someone in your country can actually take it.

Like Himalayas, this is a bonus source: any error is logged and skipped rather
than failing the run.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .linkedin import UA, _description_text

SEARCH_API = "https://nz.seek.com/api/jobsearch/v5/search"
GRAPHQL = "https://nz.seek.com/graphql"

_HEADERS = {"User-Agent": UA, "Accept": "application/json", "Referer": "https://nz.seek.com/"}

_DETAIL_QUERY = (
    "query jobDetails($jobId: ID!) { "
    "jobDetails(id: $jobId, tracking: null) { job { content(platform: WEB) } } }"
)


def _get_json(url: str, headers: dict, data: bytes | None = None, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _search_page(term: str, where: str, page: int) -> list[dict]:
    params = {
        "siteKey": "NZ-Main",
        "sourcesystem": "houston",
        "where": where,
        "keywords": term,
        "page": page,
        "pageSize": 20,
        "sortmode": "ListedDate",
    }
    return _get_json(SEARCH_API + "?" + urllib.parse.urlencode(params), _HEADERS).get("data", [])


def detail(seek_id: str, log=print) -> str:
    """Full job description (plain text) via GraphQL, or '' on any problem."""
    body = json.dumps(
        {"operationName": "jobDetails", "variables": {"jobId": str(seek_id)}, "query": _DETAIL_QUERY}
    ).encode()
    headers = {**_HEADERS, "Content-Type": "application/json",
               "seek-request-brand": "seek", "seek-request-country": "NZ"}
    try:
        data = _get_json(GRAPHQL, headers, data=body)
    except Exception as err:
        log(f"  Seek detail error for {seek_id}: {err}")
        return ""
    job = (((data or {}).get("data") or {}).get("jobDetails") or {}).get("job") or {}
    return _description_text(job.get("content") or "")


def _posted(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def search(term: str, where: str, since: datetime, max_pages: int, log=print) -> list[dict]:
    """Search cards only (no detail call). Each card carries a provisional
    description (header + teaser + bullets); fetch the full text later with
    detail() using the card's 'seek_id', so only jobs worth screening cost a
    second request."""
    jobs: list[dict] = []
    for page in range(1, max_pages + 1):
        try:
            batch = _search_page(term, where, page)
        except Exception as err:  # Seek is a bonus source; never fail the run
            log(f"  Seek error for '{term}': {err}")
            break
        if not batch:
            break
        too_old = 0
        for j in batch:
            posted = _posted(j.get("listingDate"))
            if posted and posted < since:
                too_old += 1
                continue
            jid = str(j.get("id") or "")
            if not jid:
                continue
            arrangement = (j.get("workArrangements") or {}).get("displayText") or "n/a"
            work_types = ", ".join(j.get("workTypes") or []) or "n/a"
            places = [loc.get("label") for loc in (j.get("locations") or []) if loc.get("label")]
            where_txt = ", ".join(places) if places else "New Zealand"
            header = (
                f"[Seek New Zealand listing] Location: {where_txt}, New Zealand. "
                f"Work arrangement: {arrangement}. Employment type: {work_types}. "
                "Seek NZ is a New Zealand job board; most roles need New-Zealand work rights "
                "and local presence unless the listing says it is open to remote candidates "
                "abroad.\n\n"
            )
            teaser = j.get("teaser") or ""
            bullets = j.get("bulletPoints") or []
            provisional = teaser + ("\n" + "\n".join(f"• {b}" for b in bullets) if bullets else "")
            company = j.get("companyName") or (j.get("advertiser") or {}).get("description") or ""
            jobs.append(
                {
                    "id": "seek-" + jid,
                    "seek_id": jid,
                    "source": "seek",
                    "title": j.get("title") or "",
                    "company": company,
                    "location": f"{where_txt}, New Zealand",
                    "url": f"https://nz.seek.com/job/{jid}",
                    "posted_date": posted.date().isoformat() if posted else "",
                    "salary_text": j.get("salaryLabel") or "",
                    "header": header,
                    "description": header + provisional.strip(),
                    "criteria": {
                        "Work arrangement": arrangement,
                        "Employment type": work_types,
                        "Location": f"{where_txt}, New Zealand",
                    },
                }
            )
        if too_old == len(batch):
            break
        time.sleep(1.5)
    return jobs
