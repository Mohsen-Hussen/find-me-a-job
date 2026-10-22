"""SQLite store: every job seen, its Claude screen + assessment, and what was emailed."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone

from .settings import DB_FILE, DATA

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    source TEXT DEFAULT 'linkedin',
    title TEXT, company TEXT, location TEXT, url TEXT,
    posted_date TEXT, salary_text TEXT,
    first_seen TEXT, last_seen TEXT,
    searches TEXT DEFAULT '[]',
    prefilter TEXT,
    description TEXT, criteria TEXT, applicants TEXT, detail_location TEXT,
    closed INTEGER DEFAULT 0,
    detail_at TEXT,
    screen TEXT, screen_model TEXT, screen_at TEXT,
    assess TEXT, assess_model TEXT, assess_key TEXT, assess_at TEXT,
    user_status TEXT DEFAULT '',
    emailed_at TEXT,
    errors INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT, finished_at TEXT, status TEXT, stats TEXT, log TEXT
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DATA.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn) -> None:
    have = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    for column, ddl in [("source", "TEXT DEFAULT 'linkedin'"), ("errors", "INTEGER DEFAULT 0")]:
        if column not in have:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {ddl}")
    conn.commit()


def kv_get(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def kv_set(conn, key: str, value) -> None:
    conn.execute(
        "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )
    conn.commit()


NOISE = re.compile(
    r"\bref\s*#?\s*\w+|\b100\s*%|\b(fully |full )?remote( work| first)?\b|\bworldwide\b|\banywhere\b"
    r"|\b(trabalho|trabajo) remoto\b|\bhybrid\b|\bm/w/d\b|\bf/m/d\b|\bw/m/d\b|\bm/f/x\b"
)


def dup_key(company: str, title: str) -> str:
    t = NOISE.sub(" ", (title or "").lower())
    return (company or "").strip().lower() + "|" + re.sub(r"\W+", " ", t).strip()


def find_original(conn, card: dict) -> str | None:
    """Same company + same title already stored → the same job posted in another city."""
    key = dup_key(card["company"], card["title"])
    for row in conn.execute("SELECT id, company, title FROM jobs WHERE lower(company)=? AND prefilter NOT LIKE 'duplicate%'",
                            ((card["company"] or "").strip().lower(),)):
        if row["id"] != card["id"] and dup_key(row["company"], row["title"]) == key:
            return row["id"]
    return None


def upsert_card(conn, card: dict, search_label: str, prefilter: str) -> bool:
    """Insert or refresh a search card. Returns True when the job is new."""
    row = conn.execute("SELECT searches FROM jobs WHERE id=?", (card["id"],)).fetchone()
    stamp = now()
    if row:
        searches = json.loads(row["searches"] or "[]")
        if search_label not in searches:
            searches.append(search_label)
        conn.execute(
            "UPDATE jobs SET last_seen=?, searches=? WHERE id=?",
            (stamp, json.dumps(searches), card["id"]),
        )
        return False
    if prefilter == "ok":
        original = find_original(conn, card)
        if original:
            prefilter = f"duplicate of {original}"
    conn.execute(
        """INSERT INTO jobs (id, source, title, company, location, url, posted_date, salary_text,
               first_seen, last_seen, searches, prefilter)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            card["id"], card.get("source", "linkedin"), card["title"], card["company"], card["location"], card["url"],
            card["posted_date"], card["salary_text"], stamp, stamp,
            json.dumps([search_label]), prefilter,
        ),
    )
    return True


def save_detail(conn, job_id: str, detail: dict | None) -> None:
    if detail is None:
        conn.execute("UPDATE jobs SET closed=1, detail_at=? WHERE id=?", (now(), job_id))
    else:
        conn.execute(
            """UPDATE jobs SET description=?, criteria=?, applicants=?, detail_location=?,
                   closed=?, detail_at=?, salary_text=COALESCE(NULLIF(?, ''), salary_text)
               WHERE id=?""",
            (
                detail["description"], json.dumps(detail["criteria"]), detail["applicants"],
                detail["detail_location"], detail["closed"], now(), detail["salary_text"], job_id,
            ),
        )
    conn.commit()


def save_screen(conn, job_id: str, data: dict, model: str) -> None:
    conn.execute(
        "UPDATE jobs SET screen=?, screen_model=?, screen_at=? WHERE id=?",
        (json.dumps(data), model, now(), job_id),
    )
    conn.commit()


def save_assess(conn, job_id: str, data: dict, model: str, key: str) -> None:
    conn.execute(
        "UPDATE jobs SET assess=?, assess_model=?, assess_key=?, assess_at=? WHERE id=?",
        (json.dumps(data), model, key, now(), job_id),
    )
    conn.commit()


def record_error(conn, job_id: str) -> None:
    conn.execute("UPDATE jobs SET errors=errors+1 WHERE id=?", (job_id,))
    conn.commit()


def job_dict(row: sqlite3.Row) -> dict:
    job = dict(row)
    for key in ("searches", "criteria", "screen", "assess"):
        job[key] = json.loads(job[key]) if job.get(key) else None
    return job
