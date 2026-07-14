"""SQLite persistence: dedup history, rolling opportunity log, and feedback
used to nudge keyword weights over time."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from src.sources.base import Opportunity

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    dedup_key         TEXT PRIMARY KEY,
    source_id         TEXT NOT NULL,
    notice_id         TEXT NOT NULL,
    title             TEXT NOT NULL,
    agency            TEXT,
    url               TEXT,
    description       TEXT,
    naics_code        TEXT,
    psc_code          TEXT,
    value             REAL,
    set_aside         TEXT,
    posted_date       TEXT,
    response_deadline TEXT,
    city              TEXT,
    state             TEXT,
    lat               REAL,
    lon               REAL,
    score             REAL,
    matched_keywords  TEXT,      -- JSON list, snapshot at scoring time
    reason            TEXT,      -- human-readable fit reason, for the digest
    first_seen_at     TEXT NOT NULL,
    emailed_at        TEXT       -- NULL until included in a digest
);

CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key   TEXT NOT NULL,
    verdict     TEXT NOT NULL CHECK (verdict IN ('good', 'bad')),
    created_at  TEXT NOT NULL,
    FOREIGN KEY (dedup_key) REFERENCES opportunities (dedup_key)
);

CREATE TABLE IF NOT EXISTS learned_weights (
    keyword     TEXT PRIMARY KEY,
    adjustment  REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS run_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    source_id   TEXT NOT NULL,
    status      TEXT NOT NULL,   -- 'ok' or 'error'
    result_count INTEGER,
    detail      TEXT
);
"""

# Learned adjustments are nudged by this much per feedback event and clamped
# to +/- this bound so no single keyword can dominate or zero out the base
# weight set in config.yaml.
WEIGHT_STEP = 0.05
WEIGHT_BOUND = 0.5


def _iso(d):
    if d is None:
        return None
    if isinstance(d, (date, datetime)):
        return d.isoformat()
    return str(d)


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def session(db_path: str):
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def seen_keys(conn: sqlite3.Connection) -> set:
    return {row["dedup_key"] for row in conn.execute("SELECT dedup_key FROM opportunities")}


def upsert_scored(conn: sqlite3.Connection, opp: Opportunity, score: float, matched_keywords: list,
                   reason: str, now_iso: str):
    """Insert a new opportunity (or refresh a seen one's score/detail without
    touching first_seen_at / emailed_at)."""
    conn.execute(
        """
        INSERT INTO opportunities (
            dedup_key, source_id, notice_id, title, agency, url, description,
            naics_code, psc_code, value, set_aside, posted_date, response_deadline,
            city, state, lat, lon, score, matched_keywords, reason, first_seen_at, emailed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(dedup_key) DO UPDATE SET
            score = excluded.score,
            matched_keywords = excluded.matched_keywords,
            reason = excluded.reason
        """,
        (
            opp.dedup_key, opp.source_id, opp.notice_id, opp.title, opp.agency, opp.url,
            opp.description, opp.naics_code, opp.psc_code, opp.value, opp.set_aside,
            _iso(opp.posted_date), _iso(opp.response_deadline), opp.city, opp.state,
            opp.lat, opp.lon, score, json.dumps(matched_keywords), reason, now_iso,
        ),
    )


def mark_emailed(conn: sqlite3.Connection, dedup_keys: list, now_iso: str):
    conn.executemany(
        "UPDATE opportunities SET emailed_at = ? WHERE dedup_key = ?",
        [(now_iso, k) for k in dedup_keys],
    )


def unemailed_new(conn: sqlite3.Connection, min_score: float = 0) -> list:
    """Opportunities inserted this run that haven't been emailed yet."""
    rows = conn.execute(
        "SELECT * FROM opportunities WHERE emailed_at IS NULL AND score >= ? ORDER BY score DESC",
        (min_score,),
    ).fetchall()
    return [dict(r) for r in rows]


def history_since(conn: sqlite3.Connection, since_iso: str) -> list:
    """For 'what did we get last week' style queries."""
    rows = conn.execute(
        "SELECT * FROM opportunities WHERE first_seen_at >= ? ORDER BY first_seen_at DESC",
        (since_iso,),
    ).fetchall()
    return [dict(r) for r in rows]


def record_feedback(conn: sqlite3.Connection, dedup_key: str, verdict: str, now_iso: str):
    if verdict not in ("good", "bad"):
        raise ValueError(f"verdict must be 'good' or 'bad', got {verdict!r}")
    conn.execute(
        "INSERT INTO feedback (dedup_key, verdict, created_at) VALUES (?, ?, ?)",
        (dedup_key, verdict, now_iso),
    )
    row = conn.execute(
        "SELECT matched_keywords FROM opportunities WHERE dedup_key = ?", (dedup_key,)
    ).fetchone()
    if row is None or not row["matched_keywords"]:
        return
    delta = WEIGHT_STEP if verdict == "good" else -WEIGHT_STEP
    for kw in json.loads(row["matched_keywords"]):
        nudge_weight(conn, kw, delta)


def nudge_weight(conn: sqlite3.Connection, keyword: str, delta: float):
    conn.execute(
        """
        INSERT INTO learned_weights (keyword, adjustment) VALUES (?, ?)
        ON CONFLICT(keyword) DO UPDATE SET
            adjustment = MAX(-?, MIN(?, adjustment + ?))
        """,
        (keyword, max(-WEIGHT_BOUND, min(WEIGHT_BOUND, delta)), WEIGHT_BOUND, WEIGHT_BOUND, delta),
    )


def get_learned_weights(conn: sqlite3.Connection) -> dict:
    return {row["keyword"]: row["adjustment"] for row in conn.execute("SELECT keyword, adjustment FROM learned_weights")}


def log_run(conn: sqlite3.Connection, started_at: str, finished_at: str, source_id: str,
            status: str, result_count: int, detail: str = ""):
    conn.execute(
        """
        INSERT INTO run_log (started_at, finished_at, source_id, status, result_count, detail)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (started_at, finished_at, source_id, status, result_count, detail),
    )
