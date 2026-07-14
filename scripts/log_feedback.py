#!/usr/bin/env python3
"""CLI fallback for recording feedback without relying on email replies.

Usage:
    python scripts/log_feedback.py <dedup_key> good|bad

<dedup_key> is the "source_id:notice_id" string shown in the digest's
feedback links, e.g. sam_gov:abc123. Find it by hovering the feedback link
in the email, or by querying the opportunities table directly.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
import os

load_dotenv()

from src import db  # noqa: E402


def main():
    if len(sys.argv) != 3 or sys.argv[2].lower() not in ("good", "bad"):
        print(__doc__)
        sys.exit(1)

    dedup_key, verdict = sys.argv[1], sys.argv[2].lower()
    db_path = os.getenv("DB_PATH", "data/opportunities.db")

    with db.session(db_path) as conn:
        row = conn.execute(
            "SELECT title FROM opportunities WHERE dedup_key = ?", (dedup_key,)
        ).fetchone()
        if row is None:
            print(f"No opportunity found with dedup_key={dedup_key!r}")
            sys.exit(1)
        db.record_feedback(conn, dedup_key, verdict, datetime.now(timezone.utc).isoformat())
        print(f"Recorded '{verdict}' for: {row['title']}")


if __name__ == "__main__":
    main()
