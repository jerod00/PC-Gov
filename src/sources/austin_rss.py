"""City of Austin solicitations via its official RSS feed.

This is the most stable of the Texas local sources — Austin Finance Online
is a plain server-rendered (ColdFusion) system with a real RSS feed, no
login, no JS rendering to fight.

CAVEAT: the exact feed URL in config.yaml source_urls.austin_rss was not
verified against the live site while building this (network access to
.gov/.tx.us domains was unavailable in the build environment) — confirm it
resolves and adjust if Austin has since restructured the feed.
"""

import logging
import re
from datetime import date

import feedparser
import requests

from src.sources.base import Opportunity, SourceError

REQUEST_TIMEOUT = 30
STATE_LOCAL_ELIGIBLE = True  # Austin is always in-radius (Texas)


def _extract_notice_id(link: str, guid: str) -> str:
    match = re.search(r"[?&]sid=([\w-]+)", link or "")
    if match:
        return match.group(1)
    return guid or link


def _parse_entry(entry) -> Opportunity:
    link = entry.get("link", "")
    guid = entry.get("id", "") or entry.get("guid", "")
    notice_id = _extract_notice_id(link, guid)

    posted = None
    if entry.get("published_parsed"):
        posted = date(*entry.published_parsed[:3])

    return Opportunity(
        notice_id=notice_id,
        source_id="austin_rss",
        title=entry.get("title", "").strip(),
        agency="City of Austin",
        url=link,
        description=entry.get("summary", "") or entry.get("description", ""),
        posted_date=posted,
        city="Austin",
        state="TX",
        raw=dict(entry),
    )


def fetch(cfg: dict) -> list:
    url = cfg["source_urls"]["austin_rss"]
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "PC-Gov-opportunity-finder/1.0"})
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SourceError(f"Austin RSS fetch failed ({url}): {e}") from e

    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        raise SourceError(f"Austin RSS did not parse as a valid feed ({url}): {feed.bozo_exception}")

    logging.getLogger(__name__).info("Austin RSS returned %d entries", len(feed.entries))
    return [_parse_entry(e) for e in feed.entries]
