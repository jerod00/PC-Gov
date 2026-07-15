#!/usr/bin/env python3
"""Entry point for the daily opportunity-finder run. Invoked by cron / Task
Scheduler Monday-Friday mornings. Every source runs independently — one
source failing never blocks the others or stops the digest from sending.
"""

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))

load_dotenv()

from src import db, email_digest, feedback, llm_scoring, logging_setup, scoring  # noqa: E402
from src.geo import is_in_scope  # noqa: E402
from src.sources.base import SourceError  # noqa: E402
from src.sources import sam_gov, tx_esbd, san_antonio, austin, oklahoma, louisiana  # noqa: E402

SOURCE_FETCHERS = {
    "sam_gov": lambda cfg, api_key: sam_gov.fetch(cfg, api_key),
    "tx_esbd": lambda cfg, api_key: tx_esbd.fetch(cfg),
    "san_antonio": lambda cfg, api_key: san_antonio.fetch(cfg),
    "austin": lambda cfg, api_key: austin.fetch(cfg),
    "oklahoma": lambda cfg, api_key: oklahoma.fetch(cfg),
    "louisiana": lambda cfg, api_key: louisiana.fetch(cfg),
}
NATIONWIDE_SOURCES = {"sam_gov"}  # skip the state/local geo gate entirely


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def run(cfg: dict, conn, sam_api_key: str, anthropic_api_key: str, log: logging.Logger):
    learned_weights = db.get_learned_weights(conn)
    today = datetime.now().date()

    llm_cfg = cfg.get("llm_scoring", {})
    llm_enabled = bool(llm_cfg.get("enabled")) and bool(anthropic_api_key)
    if llm_cfg.get("enabled") and not anthropic_api_key:
        log.info("llm_scoring.enabled is true but ANTHROPIC_API_KEY is not set — skipping LLM "
                 "judgment this run, using keyword/NAICS scoring only")
    llm_model = llm_cfg.get("model", "claude-haiku-4-5")
    company_profile = cfg["company"]["capabilities_description"]

    for source_id, enabled in cfg["sources"].items():
        if not enabled or source_id not in SOURCE_FETCHERS:
            continue
        started = _now_iso()
        try:
            opportunities = SOURCE_FETCHERS[source_id](cfg, sam_api_key)
        except SourceError as e:
            log.error("Source %s failed: %s", source_id, e)
            db.log_run(conn, started, _now_iso(), source_id, "error", 0, str(e))
            continue
        except Exception as e:  # noqa: BLE001 — isolate unexpected failures too
            log.exception("Source %s raised an unexpected error", source_id)
            db.log_run(conn, started, _now_iso(), source_id, "error", 0, repr(e))
            continue

        kept = 0
        for opp in opportunities:
            if source_id not in NATIONWIDE_SOURCES:
                if not is_in_scope(opp.state, opp.lat, opp.lon, opp.city, cfg):
                    continue
            judgment = None
            if llm_enabled:
                judgment = llm_scoring.judge_opportunity(opp, company_profile, anthropic_api_key, llm_model)
            score, matched = scoring.score_opportunity(opp, cfg, learned_weights, today=today, llm_judgment=judgment)
            reason = scoring.fit_reason(opp, matched, cfg, llm_judgment=judgment)
            db.upsert_scored(conn, opp, score, matched, reason, _now_iso())
            kept += 1

        log.info("Source %s: %d fetched, %d kept after geo filter", source_id, len(opportunities), kept)
        db.log_run(conn, started, _now_iso(), source_id, "ok", kept, f"{len(opportunities)} fetched")


def main():
    logging_setup.configure(os.getenv("LOG_PATH", "logs/run.log"))
    log = logging.getLogger("run_daily")
    log.info("=== Daily run starting ===")

    cfg = load_config()
    db_path = os.getenv("DB_PATH", "data/opportunities.db")
    gmail_address = os.getenv("GMAIL_ADDRESS")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")
    recipients = [addr.strip() for addr in (os.getenv("DIGEST_RECIPIENT") or gmail_address or "").split(",") if addr.strip()]
    sam_api_key = os.getenv("SAM_GOV_API_KEY", "")
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")

    if not gmail_address or not gmail_app_password:
        log.error("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set in .env — cannot send digest. Aborting.")
        sys.exit(1)

    with db.session(db_path) as conn:
        processed = feedback.scan_imap_feedback(conn, gmail_address, gmail_app_password)
        log.info("Processed %d feedback replies", processed)

        run(cfg, conn, sam_api_key, anthropic_api_key, log)

        min_score = cfg["email"]["digest_min_score_to_include"]
        max_items = cfg["email"]["max_items_per_digest"]
        rows = db.unemailed_new(conn, min_score=min_score)[:max_items]

        html = email_digest.build_html(rows, gmail_address)
        today_str = datetime.now().strftime("%Y-%m-%d")
        subject = (
            f"PC-Gov Opportunity Digest — {today_str} — {len(rows)} new"
            if rows
            else f"PC-Gov Opportunity Digest — {today_str} — nothing new today"
        )

        try:
            email_digest.send_digest(html, subject, gmail_address, gmail_app_password, recipients)
            log.info("Digest sent to %s (%d opportunities)", ", ".join(recipients), len(rows))
        except Exception:
            log.exception("Failed to send digest email")
            sys.exit(1)

        if rows:
            db.mark_emailed(conn, [r["dedup_key"] for r in rows], _now_iso())

    log.info("=== Daily run finished ===")


if __name__ == "__main__":
    main()
