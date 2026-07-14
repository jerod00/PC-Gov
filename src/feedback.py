"""Feedback ingestion: reads the GOOD/BAD mailto replies sent from the
digest email via IMAP, and records them the same way the CLI fallback does.

Subject line contract (set by email_digest.py's feedback links):
    FEEDBACK GOOD <dedup_key>
    FEEDBACK BAD <dedup_key>
"""

import email
import imaplib
import logging
import re
from datetime import datetime, timezone

from src import db

IMAP_HOST = "imap.gmail.com"
SUBJECT_PATTERN = re.compile(r"FEEDBACK\s+(GOOD|BAD)\s+(\S+)", re.IGNORECASE)

log = logging.getLogger(__name__)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def scan_imap_feedback(conn, gmail_address: str, gmail_app_password: str) -> int:
    """Connects to Gmail via IMAP, finds unread feedback-reply emails,
    records each as feedback, and marks them read so they aren't
    reprocessed. Returns the count processed. Any IMAP failure is logged and
    swallowed — feedback is a nice-to-have, it should never block the digest
    from going out."""
    processed = 0
    try:
        with imaplib.IMAP4_SSL(IMAP_HOST) as imap:
            imap.login(gmail_address, gmail_app_password)
            imap.select("INBOX")
            status, data = imap.search(None, "UNSEEN", "SUBJECT", '"FEEDBACK"')
            if status != "OK":
                log.warning("IMAP search failed: %s", status)
                return 0
            for msg_num in data[0].split():
                status, msg_data = imap.fetch(msg_num, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                subject = msg.get("Subject", "")
                match = SUBJECT_PATTERN.search(subject)
                if not match:
                    continue
                verdict, dedup_key = match.group(1).lower(), match.group(2)
                try:
                    db.record_feedback(conn, dedup_key, verdict, _now_iso())
                    processed += 1
                    imap.store(msg_num, "+FLAGS", "\\Seen")
                except ValueError as e:
                    log.warning("Skipping malformed feedback email (subject=%r): %s", subject, e)
    except (imaplib.IMAP4.error, OSError) as e:
        log.warning("IMAP feedback scan failed, continuing without it: %s", e)
        return processed
    return processed
