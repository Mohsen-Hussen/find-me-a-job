"""One run: search LinkedIn → fetch new listings → Claude screen → rules → Claude assess → alert."""

from __future__ import annotations

import fcntl
import json
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone

from . import db, himalayas, linkedin, notify, rules, scoring, settings as settings_mod
from .settings import DATA

DASHBOARD_URL = "http://localhost:8765"
RUN_LOG = DATA / "run.log"
MAX_ERRORS = 3
STATE = {"running": False, "log": [], "started": None}
_state_lock = threading.Lock()


def _logger(echo: bool):
    def log(message: str) -> None:
        line = f"{datetime.now():%H:%M:%S} {message}"
        with _state_lock:
            STATE["log"].append(line)
            del STATE["log"][:-400]
            with open(RUN_LOG, "a") as fh:
                fh.write(line + "\n")
        if echo:
            print(line, flush=True)
    return log


def all_jobs(conn, settings: dict) -> list[dict]:
    jobs = []
    for row in conn.execute("SELECT * FROM jobs ORDER BY first_seen DESC"):
        job = db.job_dict(row)
        job["eval"] = rules.evaluate(job, settings)
        jobs.append(job)
    return jobs


def _window(conn, settings, key: str) -> tuple[int, bool]:
    """Seconds to look back: since the last successful fetch (+1h overlap), or first_run_days."""
    cap = int(settings["search"]["first_run_days"] * 86400)
    last = db.kv_get(conn, key)
    if not last:
        return cap, True
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
    return int(min(cap, max(3600, elapsed + 3600))), False


def _fetch_linkedin(conn, settings, client, log, stats) -> None:
    s = settings["search"]
    seconds, first = _window(conn, settings, "linkedin_last_fetch")
    started = db.now()
    geo_cache = db.kv_get(conn, "geo_cache", {})
    suffix = " remote" if s.get("add_remote_keyword") else ""
    pages = int(s["max_pages"]) if first else max(1, min(2, int(s["max_pages"])))
    log(f"LinkedIn: {len(s['terms'])} terms × {len(s['locations'])} places, posted in the last {seconds / 3600:.0f}h")
    try:
        for place in s["locations"]:
            geo = linkedin.resolve_geo(client, place, geo_cache)
            if not geo:
                log(f"  can't find LinkedIn location '{place}' — skipped")
                continue
            for term in s["terms"]:
                label = f"{term} @ {place}"
                new_here = 0
                for page in range(pages):
                    cards = linkedin.search_page(client, term + suffix, geo, seconds, page * 10)
                    stats["cards"] += len(cards)
                    new_here += sum(db.upsert_card(conn, c, label, rules.prefilter(c["title"], s, settings["fit"])) for c in cards)
                    conn.commit()
                    if len(cards) < 10:
                        break
                stats["new"] += new_here
                log(f"  {label}: {new_here} new")
    finally:
        db.kv_set(conn, "geo_cache", geo_cache)
    db.kv_set(conn, "linkedin_last_fetch", started)


def _fetch_himalayas(conn, settings, log, stats) -> None:
    s = settings["search"]
    country = settings["sources"].get("himalayas_country") or "Egypt"
    seconds, _ = _window(conn, settings, "himalayas_last_fetch")
    started = db.now()
    since = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    log(f"Himalayas: {len(s['terms'])} terms, remote jobs open to {country}")
    for term in s["terms"]:
        new_here = 0
        for card in himalayas.search(term, country, since, int(s["max_pages"]), log):
            stats["cards"] += 1
            if db.upsert_card(conn, card, f"{term} @ Himalayas", rules.prefilter(card["title"], s, settings["fit"])):
                new_here += 1
                db.save_detail(conn, card["id"], {
                    "description": card["description"], "criteria": card["criteria"], "applicants": "",
                    "salary_text": card["salary_text"], "detail_location": card["location"], "closed": 0,
                })
        conn.commit()
        stats["new"] += new_here
        log(f"  {term} @ Himalayas: {new_here} new")
    db.kv_set(conn, "himalayas_last_fetch", started)


def _screen_one(job_id: str, settings: dict, cv: str, key: str, log, stats) -> None:
    """Read one listing with Claude, then score it straight away if it passes the rules."""
    sc = settings["scoring"]
    conn = db.connect()
    try:
        job = db.job_dict(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
        data = scoring.screen_job(job, sc["screen_model"], sc.get("screen_effort", "low"))
        db.save_screen(conn, job_id, data, f"{sc['screen_model']}#{scoring.SCREEN_VERSION}")
        stats["screened"] += 1
    except Exception as err:  # keep going; retried next run (up to MAX_ERRORS)
        db.record_error(conn, job_id)
        stats["errors"] += 1
        log(f"  screen failed for {job_id}: {err}")
        conn.close()
        return
    conn.close()
    job["screen"] = data
    if rules.evaluate(job, settings)["status"] == "match":
        _assess_one(job, settings, cv, sc["assess_model"], key, log, stats)


def _assess_one(job: dict, settings: dict, cv: str, model: str, key: str, log, stats) -> None:
    conn = db.connect()
    try:
        data = scoring.assess_job(job, settings, cv, model, settings["scoring"].get("assess_effort", "medium"))
        db.save_assess(conn, job["id"], data, model, key)
        stats["assessed"] += 1
        log(f"  [{data['fit_score']:>3}] {job['title']} — {job['company']}")
    except Exception as err:
        db.record_error(conn, job["id"])
        stats["errors"] += 1
        log(f"  assess failed for {job['id']}: {err}")
    finally:
        conn.close()


def _details_and_screen(conn, settings, client, log, stats) -> None:
    """Fetch descriptions one by one and screen each with Claude as soon as it arrives."""
    sc = settings["scoring"]
    cv = settings_mod.cv_text()
    key = settings_mod.assess_fingerprint(settings)
    need_detail = [r["id"] for r in conn.execute(
        "SELECT id FROM jobs WHERE prefilter='ok' AND detail_at IS NULL AND closed=0 "
        "AND source='linkedin' ORDER BY first_seen")]
    need_screen = [r["id"] for r in conn.execute(
        "SELECT id FROM jobs WHERE prefilter='ok' AND detail_at IS NOT NULL AND closed=0 AND errors < ? "
        "AND (screen IS NULL OR COALESCE(screen_model, '') NOT LIKE ?)", (MAX_ERRORS, f"%#{scoring.SCREEN_VERSION}"))]
    log(f"Reading {len(need_detail)} new listings; {len(need_screen)} already read listings to (re)check")
    with ThreadPoolExecutor(max_workers=int(sc["concurrency"])) as pool:
        futures = [pool.submit(_screen_one, jid, settings, cv, key, log, stats) for jid in need_screen]
        for i, job_id in enumerate(need_detail, 1):
            try:
                detail = linkedin.job_detail(client, job_id)
            except linkedin.RateLimited as err:
                log(f"  stopped reading listings: {err}")
                break
            db.save_detail(conn, job_id, detail)
            stats["details"] += 1
            if detail and not detail["closed"] and detail["description"]:
                futures.append(pool.submit(_screen_one, job_id, settings, cv, key, log, stats))
            if i % 25 == 0:
                log(f"  read {i}/{len(need_detail)} listings ({client.throttled} LinkedIn slow-downs so far)")
        wait(futures)


def _assess(conn, settings, log, stats) -> None:
    sc = settings["scoring"]
    cv = settings_mod.cv_text()
    key = settings_mod.assess_fingerprint(settings)
    todo = [
        j for j in all_jobs(conn, settings)
        if j["eval"]["status"] == "match" and j.get("errors", 0) < MAX_ERRORS
        and (j["assess"] is None or j["assess_key"] != key)
    ]
    log(f"Scoring fit for {len(todo)} jobs that pass your rules")
    with ThreadPoolExecutor(max_workers=int(sc["concurrency"])) as pool:
        wait([pool.submit(_assess_one, j, settings, cv, sc["assess_model"], key, log, stats) for j in todo])


def _notify(conn, settings, log, stats) -> None:
    threshold = settings["fit"]["email_min_score"]
    fresh = [
        j for j in all_jobs(conn, settings)
        if j["eval"]["status"] == "match" and j["assess"] and j["assess"]["fit_score"] >= threshold
        and not j["emailed_at"] and j["user_status"] != "hidden"
    ]
    if not fresh:
        log("No new matches to alert about")
        return
    fresh.sort(key=lambda j: -j["assess"]["fit_score"])
    stats["alerted"] = len(fresh)
    channel = "mac"
    if notify.email_ready(settings):
        try:
            notify.send_digest(settings, fresh[:20], settings["server"]["public_url"])
            channel = "email"
            log(f"Emailed {min(len(fresh), 20)} new matches to {settings['email']['to']}")
        except Exception as err:
            log(f"Email failed: {err}")
            return  # retry next run
    top = fresh[0]
    notify.mac_notification(
        f"{len(fresh)} new job match{'es' if len(fresh) > 1 else ''}",
        f"[{top['assess']['fit_score']}] {top['title']} — {top['company']}",
    )
    stamp = f"{channel}:{db.now()}"
    conn.executemany("UPDATE jobs SET emailed_at=? WHERE id=?", [(stamp, j["id"]) for j in fresh])
    conn.commit()


def run(stages=("fetch", "screen", "assess", "notify"), echo=True) -> dict:
    DATA.mkdir(exist_ok=True)
    lock_file = open(DATA / "run.lock", "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return {"skipped": "another run is in progress"}
    RUN_LOG.write_text("")
    log = _logger(echo)
    with _state_lock:
        STATE.update(running=True, log=[], started=db.now())
    settings = settings_mod.load()
    conn = db.connect()
    stats = {"cards": 0, "new": 0, "details": 0, "screened": 0, "assessed": 0, "alerted": 0, "errors": 0}
    run_id = conn.execute("INSERT INTO runs(started_at, status) VALUES(?, 'running')", (db.now(),)).lastrowid
    conn.commit()
    status = "ok"
    t0 = time.time()
    try:
        client = linkedin.Client(log=log)
        if "fetch" in stages and settings["sources"].get("himalayas"):
            _fetch_himalayas(conn, settings, log, stats)
        if "fetch" in stages and settings["sources"].get("linkedin"):
            try:
                _fetch_linkedin(conn, settings, client, log, stats)
            except linkedin.RateLimited as err:
                log(f"LinkedIn searching stopped early: {err}")
                status = "partial"
        if "screen" in stages:
            _details_and_screen(conn, settings, client, log, stats)
        if "assess" in stages:
            _assess(conn, settings, log, stats)
        if "notify" in stages:
            _notify(conn, settings, log, stats)
        stats["linkedin_requests"] = client.requests
    except Exception as err:
        status = f"error: {err}"
        log(traceback.format_exc())
    finally:
        stats["seconds"] = round(time.time() - t0)
        log(f"Done ({status}): {json.dumps(stats)}")
        with _state_lock:
            STATE["running"] = False
            run_log = "\n".join(STATE["log"])
        conn.execute(
            "UPDATE runs SET finished_at=?, status=?, stats=?, log=? WHERE id=?",
            (db.now(), status, json.dumps(stats), run_log, run_id),
        )
        conn.commit()
        conn.close()
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()
    return {"status": status, **stats}
