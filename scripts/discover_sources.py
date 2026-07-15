#!/usr/bin/env python3
"""Occasional (not daily) AI-assisted scan for candidate new procurement
sources within Palcon's 500-mile bid radius that this project doesn't cover
yet.

This is a REPORT-ONLY tool. It never touches config.yaml, never writes a
scraper, and never gets wired into run_daily.py automatically — it writes a
markdown report to data/ for a human to read, verify, and act on manually,
following the same process used for every other source in this project
(check robots.txt, fetch real markup, build against confirmed structure).

Run it manually, every month or two:

    python scripts/discover_sources.py

Requires ANTHROPIC_API_KEY in .env. Uses Claude Opus (web search + real
reasoning to judge whether a candidate is a genuine fit, not bulk
classification like the daily llm_scoring pass, which is why this uses a
different, more capable model).
"""

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("discover_sources")

MODEL = "claude-opus-4-8"
MAX_TOKENS = 8000
MAX_PAUSE_RESTARTS = 5

# Entities/portals already covered by a live scraper, disabled-but-known, or
# already investigated and rejected (see README.md "Sources not automated"
# and "Third-party bid aggregators" sections) — kept here so the model
# doesn't waste searches rediscovering ground we've already covered. Update
# this list if README's tables change.
ALREADY_KNOWN = [
    "SAM.gov (federal, nationwide)",
    "San Antonio, TX (ASP.NET GridView bid portal)",
    "Austin, TX (Austin Finance Online solicitations)",
    "Oklahoma OMES Central Purchasing (Solicitation Search Utility)",
    "Texas ESBD / TxSmartBuy (robots.txt disallows crawling, disabled)",
    "TxDOT open lettings (PDF-only forward schedule)",
    "Dallas, TX Bonfire portal (robots.txt disallows crawling)",
    "Fort Worth, TX Bonfire portal (robots.txt disallows crawling)",
    "Houston, TX Beacon Bid / SAP Ariba (login-gated)",
    "Arkansas state purchasing (mid-migration to SAP Ariba as of mid-2026)",
    "New Mexico state purchasing (three parallel/transitioning systems)",
    "Kansas state purchasing (PeopleSoft Fluid, JS/session-driven)",
    "BidNet Direct (robots.txt names anthropic-ai/ClaudeBot as disallowed)",
    "Public Purchase (real bids sit behind a client-side drill-down, not a browsable page)",
    "DemandStar (open bids require a $550/yr paid subscription for Texas)",
    "BidPrime, GovWin IQ, Periscope S2G (paid enterprise SLED subscriptions)",
    "Louisiana LaPAC (osp/lapac on doa.louisiana.gov — in progress, not yet built)",
    "Missouri MissouriBUYS (not yet built)",
]

REPORT_TOOL = {
    "name": "report_candidates",
    "description": (
        "Report candidate government procurement portals worth a human evaluating "
        "for possible future automation."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "description": "New candidate portals not already covered or previously rejected.",
                "items": {
                    "type": "object",
                    "properties": {
                        "entity_name": {"type": "string", "description": "Government entity name, e.g. 'City of Lubbock, TX'"},
                        "entity_type": {
                            "type": "string",
                            "description": "One of: state_agency, county, city, school_district, university, utility_district, dot, other",
                        },
                        "state": {"type": "string", "description": "Two-letter state code"},
                        "portal_url": {"type": "string", "description": "Best-known URL for the bid/solicitation listing page"},
                        "why_relevant": {
                            "type": "string",
                            "description": "Why this entity plausibly issues solicitations matching Palcon's capabilities, and why it's in-scope (within 500mi of Stephenville, TX)",
                        },
                        "apparent_tech": {
                            "type": "string",
                            "description": "Best guess at the portal's tech stack from what's visible (e.g. 'plain server-rendered HTML table', 'Bonfire SPA', 'unknown — not inspected closely')",
                        },
                        "robots_txt_caveat": {
                            "type": "string",
                            "description": "Whatever is known/suspected about robots.txt restrictions; 'not checked' if the search didn't turn this up — MUST be verified by a human before any scraper is built",
                        },
                        "confidence": {
                            "type": "integer",
                            "description": "0-100 confidence this is both genuinely relevant and genuinely new (not already known/rejected)",
                        },
                    },
                    "required": [
                        "entity_name", "entity_type", "state", "portal_url",
                        "why_relevant", "apparent_tech", "robots_txt_caveat", "confidence",
                    ],
                    "additionalProperties": False,
                },
            },
            "search_summary": {
                "type": "string",
                "description": "Brief note on what was searched and any gaps/limitations in this pass",
            },
        },
        "required": ["candidates", "search_summary"],
        "additionalProperties": False,
    },
}

WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_prompt(cfg: dict) -> str:
    company = cfg["company"]
    states = ", ".join(company["state_local_states"])
    known = "\n".join(f"- {item}" for item in ALREADY_KNOWN)
    return (
        f"Company profile:\n{company['capabilities_description']}\n\n"
        f"We're looking for STATE AND LOCAL government procurement portals — state agencies, "
        f"counties, cities, school districts, universities, and utility districts/special "
        f"districts — that plausibly post solicitations this company could bid on, located "
        f"within roughly {company['radius_miles']} miles of {company['home_location']['label']} "
        f"(this covers all of Texas and parts of {states}, excluding TX which is always in scope).\n\n"
        f"Sources ALREADY covered by a working scraper, already investigated and rejected, or "
        f"already known and out of scope — do NOT re-suggest these or close variants of them:\n"
        f"{known}\n\n"
        "Use web search to find a handful of genuinely NEW candidate portals we haven't "
        "considered yet — larger cities/counties/school districts/universities in the covered "
        "states are more likely to have real fabrication/industrial-equipment solicitations "
        "than small municipalities, so weight your search that way. For each candidate, note "
        "what you can find out about its robots.txt (search for '<domain> robots.txt' if "
        "helpful) and its apparent technology (plain HTML table, ASP.NET GridView, a named "
        "vendor platform like Bonfire/OpenGov/Ariba/PlanetBids, etc.) so a human reviewer knows "
        "roughly what they're getting into. Be honest about uncertainty — a 'not checked' or "
        "'unclear' note is more useful than a guess stated as fact. When you've gathered enough "
        "to report, call report_candidates with what you found."
    )


def run_discovery(cfg: dict, api_key: str) -> dict:
    client = anthropic.Anthropic(api_key=api_key)
    messages = [{"role": "user", "content": build_prompt(cfg)}]
    tools = [WEB_SEARCH_TOOL, REPORT_TOOL]

    restarts = 0
    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            tools=tools,
            tool_choice={"type": "auto"},
            messages=messages,
        )

        if response.stop_reason == "pause_turn":
            restarts += 1
            if restarts > MAX_PAUSE_RESTARTS:
                raise RuntimeError("Giving up: turn still paused after max restarts")
            log.info("Server-tool turn paused (long-running search) — resubmitting, restart %d", restarts)
            messages.append({"role": "assistant", "content": response.content})
            continue

        for block in response.content:
            if block.type == "tool_use" and block.name == "report_candidates":
                return block.input

        if response.stop_reason == "end_turn":
            log.warning("Model ended the turn without calling report_candidates — no results this run")
            return {"candidates": [], "search_summary": "Model did not produce a structured report."}

        # Any other stop_reason (e.g. max_tokens) with no report_candidates call:
        # nudge once, then give up rather than loop indefinitely.
        messages.append({"role": "assistant", "content": response.content})
        messages.append({
            "role": "user",
            "content": "Please call report_candidates now with whatever candidates you've found so far.",
        })
        tool_choice_forced = {"type": "tool", "name": "report_candidates"}
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            tools=[REPORT_TOOL],
            tool_choice=tool_choice_forced,
            messages=messages,
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "report_candidates":
                return block.input
        return {"candidates": [], "search_summary": "Model did not produce a structured report after a nudge."}


def render_report(result: dict, run_date: str) -> str:
    candidates = result.get("candidates", [])
    lines = [
        f"# Candidate source discovery — {run_date}",
        "",
        "**This is a report for human review only.** Nothing here has been added to "
        "`config.yaml` or wired into `run_daily.py`. Before building a scraper for any "
        "candidate below, follow the same process used for every existing source: check "
        "`robots.txt` yourself, fetch the real listing page and inspect its actual markup, "
        "then build against confirmed structure — never against a guess (including this "
        "report's own guesses about tech stack).",
        "",
        f"_Search summary: {result.get('search_summary', '(none provided)')}_",
        "",
    ]
    if not candidates:
        lines.append("No candidates surfaced this run.")
        return "\n".join(lines) + "\n"

    for c in candidates:
        lines.append(f"## {c.get('entity_name', 'Unknown entity')} ({c.get('state', '?')})")
        lines.append(f"- **Type:** {c.get('entity_type', 'unknown')}")
        lines.append(f"- **Portal URL:** {c.get('portal_url', '(none found)')}")
        lines.append(f"- **Why relevant:** {c.get('why_relevant', '')}")
        lines.append(f"- **Apparent tech:** {c.get('apparent_tech', 'unknown')}")
        lines.append(f"- **robots.txt:** {c.get('robots_txt_caveat', 'not checked')} — **verify before scraping**")
        lines.append(f"- **Confidence:** {c.get('confidence', '?')}/100")
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.error("ANTHROPIC_API_KEY not set in .env — source discovery requires it. Skipping.")
        sys.exit(1)

    cfg = load_config()
    log.info("Searching for candidate sources within %s miles of %s...",
              cfg["company"]["radius_miles"], cfg["company"]["home_location"]["label"])

    result = run_discovery(cfg, api_key)

    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_md = render_report(result, run_date)

    out_dir = Path("data")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"source_discovery_{run_date}.md"
    out_path.write_text(report_md, encoding="utf-8")

    log.info("Found %d candidate(s). Report written to %s", len(result.get("candidates", [])), out_path)


if __name__ == "__main__":
    main()
