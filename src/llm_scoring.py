"""LLM-based opportunity relevance judgment, layered on top of the
deterministic keyword/NAICS scoring in scoring.py. Catches genuine fits
that keyword matching misses (or that use none of the configured terms),
and gives a plain-English reason for each digest entry instead of just a
list of matched words.

Uses Claude Haiku 4.5 by default (see config.yaml llm_scoring.model) — a
cheap, fast model, appropriate here because this runs once per fetched
opportunity per day (bulk classification), not a task that needs deep
reasoning. Forces a structured tool call (`strict: true`) so the result is
always a validated {relevant, confidence, reasoning} shape, never free-form
text to parse.

Judgments are cached in SQLite (src/db.py, same pattern as semantic.py's
embedding cache) keyed on dedup_key + a hash of the judged text, since a
recurring listing would otherwise be re-judged by Claude every single day it
stays open -- previously the dominant cost of both runtime and API spend,
since the same few hundred listings recur unchanged day after day.
judge_opportunities_cached() is the entry point run_daily.py should use;
judge_opportunity() (uncached, single-opportunity) is kept for that batch
function to call on a cache miss.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import anthropic

from src.sources.base import Opportunity

log = logging.getLogger(__name__)

MAX_TOKENS = 500

_client = None
_client_key = None


def _get_client(api_key: str):
    global _client, _client_key
    if _client is None or _client_key != api_key:
        _client = anthropic.Anthropic(api_key=api_key)
        _client_key = api_key
    return _client


def _now_iso():
    return datetime.now(timezone.utc).isoformat()

JUDGE_TOOL = {
    "name": "judge_relevance",
    "description": "Judge whether a government contract opportunity fits a metal fabrication company's capabilities.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "relevant": {
                "type": "boolean",
                "description": "True if this is plausibly something the company could bid on and win",
            },
            "confidence": {
                "type": "integer",
                "description": "0-100 confidence in the relevant judgment",
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "One or two plain-English sentences explaining the fit (or lack of fit), "
                    "written for a non-technical business owner reading a daily email digest"
                ),
            },
        },
        "required": ["relevant", "confidence", "reasoning"],
        "additionalProperties": False,
    },
}


@dataclass
class LLMJudgment:
    relevant: bool
    confidence: int
    reasoning: str


def _build_prompt(opp: Opportunity, company_profile: str, minimum_value: Optional[float] = None) -> str:
    size_note = ""
    if minimum_value:
        size_note = (
            f"\nThe company only pursues substantial projects — roughly "
            f"${minimum_value:,.0f} or more in contract value. Most listings here don't state "
            f"a dollar figure at all (many sources don't report one, and federal notices "
            f"usually only get a value after award), so judge likely scope from the work "
            f"itself: a single part, a spare/replacement component, or a small commodity "
            f"purchase is almost never that size even if it superficially fits the company's "
            f"trade (e.g. a single vehicle part is not a $500K+ fabrication project). Judge "
            f"those NOT relevant regardless of category fit.\n"
        )
    return (
        f"Company profile:\n{company_profile}\n\n"
        "Government contract opportunity:\n"
        f"Title: {opp.title}\n"
        f"Agency: {opp.agency}\n"
        f"Description: {opp.description or '(no description available)'}\n"
        f"NAICS code: {opp.naics_code or 'unknown'}\n"
        f"{size_note}\n"
        "Judge whether this opportunity is something the company described above could "
        "plausibly bid on and win, given its actual capabilities. Be specific and skeptical."
    )


def judge_opportunity(
    opp: Opportunity, company_profile: str, api_key: str, model: str, minimum_value: Optional[float] = None,
) -> Optional[LLMJudgment]:
    """Returns None on any failure. LLM judgment is a nice-to-have enhancement
    layered on deterministic scoring, never something that should block a
    run or crash it."""
    try:
        client = _get_client(api_key)
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            tools=[JUDGE_TOOL],
            tool_choice={"type": "tool", "name": "judge_relevance"},
            messages=[{"role": "user", "content": _build_prompt(opp, company_profile, minimum_value)}],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "judge_relevance":
                data = block.input
                return LLMJudgment(
                    relevant=bool(data["relevant"]),
                    confidence=int(data["confidence"]),
                    reasoning=str(data["reasoning"]),
                )
    except Exception as e:  # noqa: BLE001 — never let LLM scoring break a run
        log.warning("LLM judgment failed for %s: %s", opp.dedup_key, e)
    return None


def _cache_text(opp: Opportunity, minimum_value: Optional[float]) -> str:
    """Everything that actually varies _build_prompt's output for a given
    company_profile, so a change to any of these (a new addendum's
    description, a corrected NAICS code, a changed minimum_value in
    config.yaml) naturally busts the cache instead of serving a stale
    judgment."""
    return f"{opp.title}\n{opp.agency}\n{opp.description}\n{opp.naics_code}\n{minimum_value}"


def judge_opportunities_cached(
    opportunities: list, company_profile: str, conn, api_key: str, model: str,
    minimum_value: Optional[float] = None,
) -> dict:
    """Returns {dedup_key: LLMJudgment} for every opportunity that has a
    cached judgment already or was successfully judged this call. Only
    genuinely new or changed listings hit the Anthropic API — see module
    docstring."""
    from src import db  # local import — avoids a hard circular-import edge at module load

    result = {}
    for opp in opportunities:
        text = _cache_text(opp, minimum_value)
        cached = db.get_cached_llm_judgment(conn, opp.dedup_key, text)
        if cached is not None:
            result[opp.dedup_key] = LLMJudgment(**cached)
            continue
        judgment = judge_opportunity(opp, company_profile, api_key, model, minimum_value)
        if judgment is not None:
            result[opp.dedup_key] = judgment
            db.set_cached_llm_judgment(
                conn, opp.dedup_key, text, judgment.relevant, judgment.confidence, judgment.reasoning, _now_iso(),
            )
    return result
