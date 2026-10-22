"""LinkedIn's logged-out ("guest") job endpoints. No login, so no account risk.

Requests are paced with jitter and back off on HTTP 429, because LinkedIn
rate-limits by IP.
"""

from __future__ import annotations

import html
import http.client
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://www.linkedin.com"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

# Regions the typeahead can't resolve.
KNOWN_GEO = {
    "worldwide": "92000000",
    "emea": "91000007",
    "european union": "91000000",
    "united states": "103644278",
    "egypt": "106155005",
    "new zealand": "105490917",
    "australia": "101452733",
    "united kingdom": "101165590",
}


class RateLimited(RuntimeError):
    pass


class Client:
    def __init__(self, log=print, delay=(4.0, 7.0)):
        self.log = log
        self.base = delay
        self.delay = list(delay)
        self._last = 0.0
        self._streak = 0
        self.requests = 0
        self.throttled = 0

    def _slow_down(self) -> None:
        # Each 429 costs ~25 s, so after one, space requests out more; ease back after a clean streak.
        self.delay = [min(d + 1.5, cap) for d, cap in zip(self.delay, (10.0, 13.0))]
        self._streak = 0
        self.throttled += 1

    def _speed_up(self) -> None:
        self._streak += 1
        if self._streak >= 15 and self.delay[0] > self.base[0]:
            self.delay = [max(d - 0.5, b) for d, b in zip(self.delay, self.base)]
            self._streak = 0

    def get(self, url: str) -> str | None:
        last_problem = "unknown error"
        for attempt in range(5):
            wait = self._last + random.uniform(*self.delay) - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            self.requests += 1
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read().decode("utf-8", "replace")
                self._speed_up()
                return body
            except urllib.error.HTTPError as err:
                if err.code in (400, 404, 410):
                    return None
                if err.code in (429, 999) or err.code >= 500:
                    self._slow_down()
                    pause = min(240, 20 * 2**attempt) + random.uniform(0, 5)
                    self.log(f"  LinkedIn said {err.code}; waiting {pause:.0f}s")
                    last_problem = f"LinkedIn said {err.code} (rate limit)"
                    time.sleep(pause)
                    continue
                raise
            # OSError covers URLError, timeouts and connection resets while the body downloads;
            # HTTPException covers half-sent responses.
            except (OSError, http.client.HTTPException) as err:
                pause = 10 * (attempt + 1)
                self.log(f"  network error ({err!r}); retrying in {pause}s")
                last_problem = f"network error, is the internet down? ({err!r})"
                time.sleep(pause)
        raise RateLimited(f"gave up after 5 tries, last problem: {last_problem}. {url}")


def _text(fragment: str) -> str:
    fragment = re.sub(r"<!--.*?-->", "", fragment, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _first(pattern: str, source: str) -> str:
    m = re.search(pattern, source, re.S)
    return _text(m.group(1)) if m else ""


def resolve_geo(client: Client, place: str, cache: dict) -> str | None:
    key = place.strip().lower()
    if key.isdigit():
        return key
    if key in KNOWN_GEO:
        return KNOWN_GEO[key]
    if key in cache:
        return cache[key]
    url = f"{BASE}/jobs-guest/api/typeaheadHits?" + urllib.parse.urlencode(
        {
            "query": place,
            "typeaheadType": "GEO",
            "geoTypes": "POPULATED_PLACE,ADMIN_DIVISION_2,MARKET_AREA,COUNTRY_REGION",
        }
    )
    body = client.get(url)
    hits = json.loads(body) if body else []
    cache[key] = hits[0]["id"] if hits else None
    return cache[key]


def search_page(client: Client, keywords: str, geo_id: str, seconds: int, start: int):
    # Logged-out search ignores f_WT/f_E/f_JT/sortBy (since Sep 2026); f_TPR still works.
    params = {"keywords": keywords, "geoId": geo_id, "f_TPR": f"r{seconds}", "start": start}
    body = client.get(f"{BASE}/jobs-guest/jobs/api/seeMoreJobPostings/search?" + urllib.parse.urlencode(params))
    if not body:
        return []
    cards = []
    for chunk in body.split("<li>"):
        m = re.search(r"urn:li:jobPosting:(\d+)", chunk)
        if not m:
            continue
        posted = re.search(r'<time[^>]*datetime="([^"]+)"', chunk)
        cards.append(
            {
                "id": m.group(1),
                "title": _first(r'base-search-card__title">(.*?)</h3>', chunk),
                "company": _first(r'base-search-card__subtitle">(.*?)</h4>', chunk),
                "location": _first(r'job-search-card__location">(.*?)</span>', chunk),
                "posted_date": posted.group(1) if posted else "",
                "salary_text": _first(r'job-search-card__salary-info">(.*?)</span>', chunk),
                "url": f"{BASE}/jobs/view/{m.group(1)}/",
            }
        )
    return cards


def _description_text(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"<li[^>]*>", "\n• ", fragment)
    fragment = re.sub(r"</(p|div|ul|ol|h\d)>", "\n", fragment)
    text = html.unescape(re.sub(r"<[^>]+>", "", fragment))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def job_detail(client: Client, job_id: str) -> dict | None:
    body = client.get(f"{BASE}/jobs-guest/jobs/api/jobPosting/{job_id}")
    if not body:
        return None
    desc = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', body, re.S)
    headers = re.findall(r'description__job-criteria-subheader">(.*?)</h3>', body, re.S)
    values = re.findall(r'description__job-criteria-text[^>]*>(.*?)</span>', body, re.S)
    return {
        "description": _description_text(desc.group(1)) if desc else "",
        "criteria": {_text(h): _text(v) for h, v in zip(headers, values)},
        "applicants": _first(r'num-applicants__caption[^>]*>(.*?)</', body),
        "salary_text": _first(r'compensation__salary[^>]*>(.*?)</div>', body),
        "detail_location": _first(r'topcard__flavor topcard__flavor--bullet[^>]*>(.*?)</span>', body),
        "closed": int("No longer accepting applications" in body),
    }
