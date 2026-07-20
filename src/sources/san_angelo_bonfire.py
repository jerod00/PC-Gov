"""City of San Angelo — Bonfire portal (cosatx.bonfirehub.com) public
"Opportunity RSS Feed". Fetch/parse logic lives in bonfire_rss.py, shared
across Bonfire organizations; this module just supplies San Angelo's
identity.

Previously confirmed blocked (the 7th Bonfire subdomain checked in this
project at the time, and the 7th found blocked). Independently re-checked
live 2026-07-20 (fourth Bonfire org re-checked this round): robots.txt now
has an empty Disallow. The RSS feed itself loads and is well-formed but
currently has zero open items -- an empty board, not a broken feed, same
case seen with Wichita Falls earlier in this project. Kept enabled
despite the empty feed since there's nothing wrong with the source itself
and the board naturally fills and empties over time.
"""

from src.sources import bonfire_rss


def fetch(cfg: dict) -> list:
    return bonfire_rss.fetch(cfg, source_id="san_angelo", agency="City of San Angelo", city="San Angelo", state="TX")
