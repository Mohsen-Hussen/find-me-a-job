"""Local dashboard + scheduler on http://localhost:8765 (only reachable from this Mac)."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db, notify, pipeline, settings as settings_mod
from .countries import COUNTRIES, REGIONS

STATIC = Path(__file__).parent / "static"
USER_STATUSES = {"", "saved", "applied", "hidden"}
MAX_UPLOAD = 10 * 1024 * 1024


def _last_run(conn) -> dict | None:
    row = conn.execute("SELECT id, started_at, finished_at, status, stats FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    run = dict(row)
    run["stats"] = json.loads(run["stats"]) if run["stats"] else None
    return run


def _minutes_since(iso: str) -> float:
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 60


def start_run() -> bool:
    if pipeline.STATE["running"]:
        return False
    threading.Thread(target=pipeline.run, kwargs={"echo": True}, daemon=True).start()
    return True


class Scheduler(threading.Thread):
    daemon = True

    def run(self) -> None:
        time.sleep(5)
        while True:
            try:
                s = settings_mod.load()
                if s["schedule"]["enabled"]:
                    conn = db.connect()
                    last = _last_run(conn)
                    conn.close()
                    if not last or _minutes_since(last["started_at"]) >= float(s["schedule"]["interval_minutes"]):
                        start_run()
            except Exception as err:  # never let the scheduler die
                print(f"scheduler error: {err}", flush=True)
            time.sleep(30)


def state() -> dict:
    s = settings_mod.load()
    conn = db.connect()
    last = _last_run(conn)
    totals = dict(conn.execute("SELECT COUNT(*) AS jobs, SUM(assess IS NOT NULL) AS assessed FROM jobs").fetchone())
    conn.close()
    running = pipeline.STATE["running"]
    # Read the shared log file so runs started from the terminal show progress too.
    log = pipeline.RUN_LOG.read_text(encoding="utf-8").splitlines()[-250:] if pipeline.RUN_LOG.exists() else []
    next_run = None
    if s["schedule"]["enabled"] and last:
        started = datetime.fromisoformat(last["started_at"])
        next_run = (started + timedelta(minutes=float(s["schedule"]["interval_minutes"]))).isoformat()
    cv = settings_mod.cv_text()
    return {
        "running": running or ((last or {}).get("status") == "running" and _minutes_since(last["started_at"]) < 90),
        "log": log,
        "last_run": last,
        "next_run": next_run,
        "totals": totals,
        "settings": s,
        "email_ready": notify.email_ready(s),
        "cv_text": cv,
        "places": {"regions": REGIONS, "countries": COUNTRIES},
    }


def jobs_payload() -> dict:
    s = settings_mod.load()
    conn = db.connect()
    jobs = pipeline.all_jobs(conn, s)
    conn.close()
    for job in jobs:
        job.pop("description", None)
    return {"jobs": jobs}


def job_detail(job_id: str) -> dict | None:
    conn = db.connect()
    row = conn.execute("SELECT description FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    return {"description": row["description"] or ""} if row else None


class Handler(BaseHTTPRequestHandler):
    server_version = "jobhunt"

    def log_message(self, fmt, *args) -> None:
        pass

    def _send(self, code: int, body, ctype: str = "application/json") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _host_ok(self) -> bool:
        # Blocks DNS-rebinding: only answer requests addressed to this machine or its private Tailscale name.
        host = (self.headers.get("Host") or "").split(":")[0].lower().rstrip(".")
        allowed = {"localhost", "127.0.0.1"} | {h.lower().rstrip(".") for h in settings_mod.load()["server"]["allowed_hosts"]}
        return host in allowed

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if url.path == "/api/state":
            return self._send(200, state())
        if url.path == "/api/jobs":
            return self._send(200, jobs_payload())
        if url.path == "/api/job":
            detail = job_detail(parse_qs(url.query).get("id", [""])[0])
            return self._send(200 if detail else 404, detail or {"error": "not found"})
        return self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        # The custom header can't be sent cross-site without CORS, so other web pages can't drive this API.
        if not self._host_ok() or self.headers.get("X-Jobhunt") != "1":
            return self._send(403, {"error": "forbidden"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            return self._send(413, {"error": "file too large"})
        raw = self.rfile.read(length) if length else b""
        path = urlparse(self.path).path
        try:
            if path == "/api/run":
                return self._send(200, {"started": start_run()})
            if path == "/api/open":
                s = settings_mod.load()
                conn = db.connect()
                last = _last_run(conn)
                conn.close()
                stale = not last or _minutes_since(last["started_at"]) >= float(s["schedule"]["run_on_open_after_minutes"])
                return self._send(200, {"started": start_run() if stale else False})
            if path == "/api/settings":
                return self._send(200, settings_mod.save(json.loads(raw)))
            if path == "/api/job_status":
                body = json.loads(raw)
                if body.get("status") not in USER_STATUSES:
                    return self._send(400, {"error": "bad status"})
                conn = db.connect()
                conn.execute("UPDATE jobs SET user_status=? WHERE id=?", (body["status"], str(body.get("id"))))
                conn.commit()
                conn.close()
                return self._send(200, {"ok": True})
            if path == "/api/block_company":
                company = str(json.loads(raw).get("company", "")).strip()
                if not company:
                    return self._send(400, {"error": "no company"})
                s = settings_mod.load()
                if company.lower() not in (c.lower() for c in s["fit"]["blocked_companies"]):
                    s["fit"]["blocked_companies"].append(company)
                return self._send(200, settings_mod.save(s))
            if path == "/api/cv":
                text = settings_mod.save_cv_pdf(raw)
                return self._send(200, {"chars": len(text)})
            if path == "/api/cv_text":
                text = json.loads(raw).get("text", "").strip()
                if len(text) < 200:
                    return self._send(400, {"error": "CV text looks too short"})
                settings_mod.DATA.mkdir(exist_ok=True)
                settings_mod.CV_TEXT_FILE.write_text(text, encoding="utf-8")
                return self._send(200, {"chars": len(text)})
            if path == "/api/test_email":
                notify.send_test(settings_mod.load(), settings_mod.load()["server"]["public_url"])
                return self._send(200, {"ok": True})
        except Exception as err:
            return self._send(400, {"error": str(err)})
        return self._send(404, {"error": "not found"})


def _clear_interrupted_runs() -> None:
    """A run cut off by a restart or kill stays 'running' in the database; mark it interrupted."""
    from . import filelock

    settings_mod.DATA.mkdir(exist_ok=True)
    with open(settings_mod.DATA / "run.lock", "w") as lock:
        try:
            filelock.acquire(lock)
        except filelock.LockBusy:
            return  # a run really is in progress (e.g. started from the terminal)
        conn = db.connect()
        conn.execute("UPDATE runs SET status='interrupted', finished_at=? WHERE status='running'", (db.now(),))
        conn.commit()
        conn.close()
        filelock.release(lock)


def serve(port: int = 8765, scheduler: bool = True) -> None:
    db.connect().close()
    _clear_interrupted_runs()
    if scheduler:
        Scheduler().start()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Dashboard on http://localhost:{port}", flush=True)
    server.serve_forever()
