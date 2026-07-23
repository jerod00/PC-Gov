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

from src import db, email_digest, feedback, llm_scoring, logging_setup, scoring, semantic  # noqa: E402
from src.geo import is_in_scope  # noqa: E402
from src.sources.base import SourceError  # noqa: E402
from src.sources import sam_gov, tx_esbd, san_antonio, austin, oklahoma, louisiana, houston, dallas_county, wichita_falls, dallas_bonfire, fort_worth_bonfire, harris_county_bonfire, san_angelo_bonfire, waco_bonfire, amarillo_bonfire, port_of_galveston_bonfire, galveston, odessa, midland, new_orleans, tulsa, wichita_bonfire  # noqa: E402

SOURCE_FETCHERS = {
    "sam_gov": lambda cfg, api_key: sam_gov.fetch(cfg, api_key),
    "tx_esbd": lambda cfg, api_key: tx_esbd.fetch(cfg),
    "san_antonio": lambda cfg, api_key: san_antonio.fetch(cfg),
    "austin": lambda cfg, api_key: austin.fetch(cfg),
    "oklahoma": lambda cfg, api_key: oklahoma.fetch(cfg),
    "louisiana": lambda cfg, api_key: louisiana.fetch(cfg),
    "houston": lambda cfg, api_key: houston.fetch(cfg),
    "dallas_county": lambda cfg, api_key: dallas_county.fetch(cfg),
    "wichita_falls": lambda cfg, api_key: wichita_falls.fetch(cfg),
    "dallas_bonfire": lambda cfg, api_key: dallas_bonfire.fetch(cfg),
    "fort_worth_bonfire": lambda cfg, api_key: fort_worth_bonfire.fetch(cfg),
    "harris_county": lambda cfg, api_key: harris_county_bonfire.fetch(cfg),
    "san_angelo": lambda cfg, api_key: san_angelo_bonfire.fetch(cfg),
    "waco_bonfire": lambda cfg, api_key: waco_bonfire.fetch(cfg),
    "amarillo_bonfire": lambda cfg, api_key: amarillo_bonfire.fetch(cfg),
    "port_of_galveston_bonfire": lambda cfg, api_key: port_of_galveston_bonfire.fetch(cfg),
    "galveston": lambda cfg, api_key: galveston.fetch(cfg),
    "odessa": lambda cfg, api_key: odessa.fetch(cfg),
    "midland": lambda cfg, api_key: midland.fetch(cfg),
    "new_orleans": lambda cfg, api_key: new_orleans.fetch(cfg),
    "tulsa": lambda cfg, api_key: tulsa.fetch(cfg),
    "wichita_bonfire": lambda cfg, api_key: wichita_bonfire.fetch(cfg),
}
NATIONWIDE_SOURCES = {"sam_gov"}  # skip the state/local geo gate entirely


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def run(cfg: dict, conn, sam_api_key: str, anthropic_api_key: str, voyage_api_key: str, log: logging.Logger):
    learned_weights = db.get_learned_weights(conn)
    today = datetime.now().date()

    llm_cfg = cfg.get("llm_scoring", {})
    llm_enabled = bool(llm_cfg.get("enabled")) and bool(anthropic_api_key)
    if llm_cfg.get("enabled") and not anthropic_api_key:
        log.info("llm_scoring.enabled is true but ANTHROPIC_API_KEY is not set — skipping LLM "
                 "judgment this run, using keyword/NAICS scoring only")
    llm_model = llm_cfg.get("model", "claude-haiku-4-5")
    company_profile = cfg["company"]["capabilities_description"]

    semantic_cfg = cfg.get("semantic_scoring", {})
    semantic_enabled = bool(semantic_cfg.get("enabled")) and bool(voyage_api_key)
    if semantic_cfg.get("enabled") and not voyage_api_key:
        log.info("semantic_scoring.enabled is true but VOYAGE_API_KEY is not set — skipping semantic "
                 "similarity this run, using keyword/NAICS/capability-code scoring only")
    semantic_model = semantic_cfg.get("model", "voyage-3.5")
    capability_embeddings = {}
    if semantic_enabled:
        capability_embeddings = semantic.embed_capabilities(cfg.get("capabilities", []), voyage_api_key, semantic_model)
        if cfg.get("capabilities") and not capability_embeddings:
            log.warning("semantic_scoring is enabled but capability embeddings failed — "
                        "continuing without semantic similarity this run")

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

        in_scope_opps = [
            opp for opp in opportunities
            if (source_id in NATIONWIDE_SOURCES or is_in_scope(opp.state, opp.lat, opp.lon, opp.city, cfg))
            and scoring.meets_minimum_value(opp, cfg)
        ]

        opp_embeddings = {}
        if semantic_enabled and capability_embeddings:
            opp_embeddings = semantic.embed_opportunities_cached(in_scope_opps, conn, voyage_api_key, semantic_model)

        llm_judgments = {}
        if llm_enabled:
            llm_judgments = llm_scoring.judge_opportunities_cached(
                in_scope_opps, company_profile, conn, anthropic_api_key, llm_model,
                minimum_value=cfg["scoring"].get("minimum_contract_value"),
            )

        kept = 0
        for opp in in_scope_opps:
            judgment = llm_judgments.get(opp.dedup_key)
            score, matched, matched_capability = scoring.score_opportunity(
                opp, cfg, learned_weights, today=today, llm_judgment=judgment,
                opp_embedding=opp_embeddings.get(opp.dedup_key), capability_embeddings=capability_embeddings,
            )
            reason = scoring.fit_reason(opp, matched, cfg, llm_judgment=judgment, matched_capability=matched_capability)
            db.upsert_scored(conn, opp, score, matched, reason, _now_iso(), matched_capability=matched_capability)
            kept += 1

        log.info("Source %s: %d fetched, %d kept after geo/value filters", source_id, len(opportunities), kept)
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
    voyage_api_key = os.getenv("VOYAGE_API_KEY", "")

    if not gmail_address or not gmail_app_password:
        log.error("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set in .env — cannot send digest. Aborting.")
        sys.exit(1)

    with db.session(db_path) as conn:
        processed = feedback.scan_imap_feedback(conn, gmail_address, gmail_app_password)
        log.info("Processed %d feedback replies", processed)

        run(cfg, conn, sam_api_key, anthropic_api_key, voyage_api_key, log)

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
