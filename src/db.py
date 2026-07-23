"""SQLite persistence: dedup history, rolling opportunity log, and feedback
used to nudge keyword weights over time."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional

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
    nigp_codes        TEXT,      -- JSON list of NIGP codes/category names, when the source has them
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
    matched_capability TEXT,     -- name of the best-fit capability profile, if any (see scoring.py)
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

-- Learned adjustments, generalized across three dimensions so feedback
-- improves more than just individual keyword weights: a source or a NAICS
-- code with a track record of bad feedback gets automatically dampened
-- over time too, not just the specific words in its listings.
--   kind: 'keyword' | 'source' | 'naics'
--   key:  the keyword string, source_id, or NAICS code being adjusted
CREATE TABLE IF NOT EXISTS learned_adjustments (
    kind        TEXT NOT NULL,
    key         TEXT NOT NULL,
    adjustment  REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, key)
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

-- Caches opportunity embeddings (src/semantic.py) keyed by dedup_key + a hash
-- of the embedded text, so a recurring listing isn't re-embedded (and
-- re-billed) every single day it stays open. Capability-description
-- embeddings are NOT cached here -- there are only a handful of them, config
-- edits should be picked up immediately, and re-embedding them each run is
-- cheap.
CREATE TABLE IF NOT EXISTS embedding_cache (
    cache_key   TEXT PRIMARY KEY,   -- f"{dedup_key}:{sha256(text)}"
    embedding   TEXT NOT NULL,      -- JSON list[float]
    created_at  TEXT NOT NULL
);

-- Same idea as embedding_cache, for LLM relevance judgments (src/llm_scoring.py).
-- Before this existed, every in-scope opportunity was re-judged by Claude on
-- every single run regardless of whether it had been seen (and judged)
-- yesterday -- the dominant cost of both runtime and API spend, since the
-- same few hundred listings recur unchanged day after day. Keyed the same
-- way as embedding_cache: a changed title/description/NAICS/minimum_value
-- naturally busts the cache since it changes the hash.
CREATE TABLE IF NOT EXISTS llm_judgment_cache (
    cache_key   TEXT PRIMARY KEY,   -- f"{dedup_key}:{sha256(text)}"
    relevant    INTEGER NOT NULL,   -- 0/1
    confidence  INTEGER NOT NULL,
    reasoning   TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""

# Columns added to `opportunities` after the table's original release.
# CREATE TABLE IF NOT EXISTS never alters an existing table, so an
# already-deployed database (this project has been running in production
# since before this migration) needs these added explicitly.
_MIGRATIONS = [
    ("opportunities", "nigp_codes", "TEXT"),
    ("opportunities", "matched_capability", "TEXT"),
]


def _migrate_schema(conn: sqlite3.Connection):
    for table, column, coltype in _MIGRATIONS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")

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
    _migrate_schema(conn)
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
                   reason: str, now_iso: str, matched_capability: Optional[str] = None):
    """Insert a new opportunity (or refresh a seen one's score/detail without
    touching first_seen_at / emailed_at)."""
    conn.execute(
        """
        INSERT INTO opportunities (
            dedup_key, source_id, notice_id, title, agency, url, description,
            naics_code, psc_code, nigp_codes, value, set_aside, posted_date, response_deadline,
            city, state, lat, lon, score, matched_keywords, matched_capability, reason,
            first_seen_at, emailed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(dedup_key) DO UPDATE SET
            score = excluded.score,
            matched_keywords = excluded.matched_keywords,
            matched_capability = excluded.matched_capability,
            reason = excluded.reason
        """,
        (
            opp.dedup_key, opp.source_id, opp.notice_id, opp.title, opp.agency, opp.url,
            opp.description, opp.naics_code, opp.psc_code, json.dumps(opp.nigp_codes or []),
            opp.value, opp.set_aside, _iso(opp.posted_date), _iso(opp.response_deadline),
            opp.city, opp.state, opp.lat, opp.lon, score, json.dumps(matched_keywords),
            matched_capability, reason, now_iso,
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
    """Records the verdict, then nudges learned adjustments across all three
    dimensions for this opportunity: each matched keyword, its source, and
    its NAICS code (when known). A source or code that keeps getting
    thumbs-down gets automatically deprioritized over time, not just the
    specific keywords in its listings."""
    if verdict not in ("good", "bad"):
        raise ValueError(f"verdict must be 'good' or 'bad', got {verdict!r}")
    conn.execute(
        "INSERT INTO feedback (dedup_key, verdict, created_at) VALUES (?, ?, ?)",
        (dedup_key, verdict, now_iso),
    )
    row = conn.execute(
        "SELECT matched_keywords, source_id, naics_code, matched_capability FROM opportunities WHERE dedup_key = ?",
        (dedup_key,),
    ).fetchone()
    if row is None:
        return
    delta = WEIGHT_STEP if verdict == "good" else -WEIGHT_STEP
    for kw in json.loads(row["matched_keywords"] or "[]"):
        nudge_weight(conn, "keyword", kw, delta)
    if row["source_id"]:
        nudge_weight(conn, "source", row["source_id"], delta)
    if row["naics_code"]:
        nudge_weight(conn, "naics", row["naics_code"], delta)
    if row["matched_capability"]:
        nudge_weight(conn, "capability", row["matched_capability"], delta)


def nudge_weight(conn: sqlite3.Connection, kind: str, key: str, delta: float):
    conn.execute(
        """
        INSERT INTO learned_adjustments (kind, key, adjustment) VALUES (?, ?, ?)
        ON CONFLICT(kind, key) DO UPDATE SET
            adjustment = MAX(-?, MIN(?, adjustment + ?))
        """,
        (kind, key, max(-WEIGHT_BOUND, min(WEIGHT_BOUND, delta)), WEIGHT_BOUND, WEIGHT_BOUND, delta),
    )


def get_learned_weights(conn: sqlite3.Connection) -> dict:
    """Returns {'keyword': {...}, 'source': {...}, 'naics': {...},
    'capability': {...}}, each mapping key -> adjustment. Missing keys
    default to 0 (no adjustment) wherever scoring.py looks them up."""
    result = {"keyword": {}, "source": {}, "naics": {}, "capability": {}}
    for row in conn.execute("SELECT kind, key, adjustment FROM learned_adjustments"):
        if row["kind"] in result:
            result[row["kind"]][row["key"]] = row["adjustment"]
    return result


def _embedding_cache_key(dedup_key: str, text: str) -> str:
    return f"{dedup_key}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def get_cached_embedding(conn: sqlite3.Connection, dedup_key: str, text: str) -> Optional[list]:
    """Returns the cached embedding vector for this exact (dedup_key, text)
    pair, or None if not cached (a miss also happens whenever the listing's
    title/description text changes, which is correct -- a changed listing
    needs a fresh embedding)."""
    row = conn.execute(
        "SELECT embedding FROM embedding_cache WHERE cache_key = ?",
        (_embedding_cache_key(dedup_key, text),),
    ).fetchone()
    return json.loads(row["embedding"]) if row else None


def set_cached_embedding(conn: sqlite3.Connection, dedup_key: str, text: str, embedding: list, now_iso: str):
    conn.execute(
        """
        INSERT INTO embedding_cache (cache_key, embedding, created_at) VALUES (?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET embedding = excluded.embedding
        """,
        (_embedding_cache_key(dedup_key, text), json.dumps(embedding), now_iso),
    )


def _llm_judgment_cache_key(dedup_key: str, text: str) -> str:
    return f"{dedup_key}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def get_cached_llm_judgment(conn: sqlite3.Connection, dedup_key: str, text: str) -> Optional[dict]:
    """Returns {'relevant': bool, 'confidence': int, 'reasoning': str} for
    this exact (dedup_key, text) pair, or None if not cached (a miss also
    happens whenever the listing's judged text changes, which is correct)."""
    row = conn.execute(
        "SELECT relevant, confidence, reasoning FROM llm_judgment_cache WHERE cache_key = ?",
        (_llm_judgment_cache_key(dedup_key, text),),
    ).fetchone()
    if row is None:
        return None
    return {"relevant": bool(row["relevant"]), "confidence": row["confidence"], "reasoning": row["reasoning"]}


def set_cached_llm_judgment(conn: sqlite3.Connection, dedup_key: str, text: str,
                            relevant: bool, confidence: int, reasoning: str, now_iso: str):
    conn.execute(
        """
        INSERT INTO llm_judgment_cache (cache_key, relevant, confidence, reasoning, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            relevant = excluded.relevant, confidence = excluded.confidence, reasoning = excluded.reasoning
        """,
        (_llm_judgment_cache_key(dedup_key, text), int(relevant), confidence, reasoning, now_iso),
    )


def log_run(conn: sqlite3.Connection, started_at: str, finished_at: str, source_id: str,
            status: str, result_count: int, detail: str = ""):
    conn.execute(
        """
        INSERT INTO run_log (started_at, finished_at, source_id, status, result_count, detail)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (started_at, finished_at, source_id, status, result_count, detail),
    )
