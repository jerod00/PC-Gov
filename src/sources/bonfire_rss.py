"""Shared fetch/parse logic for Bonfire's public per-organization
"Opportunity RSS Feed" (`https://<org>.bonfirehub.com/opportunities/rss`),
documented by Bonfire itself as an intentionally public feed meant for
external embedding -- not a reverse-engineered endpoint.

Confirmed against TWO independent Bonfire organizations with identical
item structure (City of Dallas and City of Fort Worth, both 2026-07-20),
so this is shared, verified logic -- not one org's format guessed onto
another's. Each org gets its own thin wrapper module
(dallas_bonfire.py, fort_worth_bonfire.py, ...) that calls fetch() below
with that org's source_id/agency/city/state; see dallas_bonfire.py's
docstring for the full story on why Bonfire orgs were long treated as a
blanket-blocked platform and how that assumption turned out to be wrong
(every org must be individually re-checked against its own live
robots.txt -- one org's policy is not evidence for another's).

Feed item shape, confirmed from real fetched samples on both orgs:
  <title>Reference #: <ref>. Name: <name></title>
  <description>Description: <details> ... Project closes <Mon DD, YYYY>
    <H:MM AM/PM> <TZ>.</description>
  <pubDate>Weekday, DD Mon YYYY HH:MM:SS -ZZZZ</pubDate>
  <link>https://<org>.bonfirehub.com/opportunities/<id></link>

The feed has no per-item value/NAICS/PSC field -- those stay unset, same
as several other lightweight sources in this project (Dallas County,
Wichita Falls). No pagination found in either org's feed; each appears to
list everything currently open on the public portal in one response.
"""

import logging
import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests

from src.sources.base import Opportunity, SourceError

REQUEST_TIMEOUT = 30
HEADERS = {"User-Agent": "PC-Gov-opportunity-finder/1.0"}

TITLE_RE = re.compile(r"^Reference #:\s*(?P<ref>.+?)\.\s*Name:\s*(?P<name>.+)$", re.DOTALL)
CLOSES_RE = re.compile(r"Project closes\s+([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})")


def _parse_title(raw_title: str):
    """Returns (notice_id, name). Falls back to the raw title as both if
    the "Reference #: ... Name: ..." pattern isn't found -- an unexpected
    title shape shouldn't drop an otherwise-valid opportunity."""
    if not raw_title:
        return None, ""
    match = TITLE_RE.match(raw_title.strip())
    if match is None:
        return raw_title.strip(), raw_title.strip()
    return match.group("ref").strip(), match.group("name").strip()


def _parse_deadline(description: str):
    if not description:
        return None
    match = CLOSES_RE.search(description)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%b %d, %Y").date()
    except ValueError:
        return None


def _parse_pub_date(raw_pub_date: str):
    if not raw_pub_date:
        return None
    try:
        return parsedate_to_datetime(raw_pub_date.strip()).date()
    except (ValueError, TypeError):
        return None


def _parse_item(item, today: date, source_id: str, agency: str, city: str, state: str):
    raw_title = (item.findtext("title") or "").strip()
    description = (item.findtext("description") or "").strip()
    link = (item.findtext("link") or "").strip()

    notice_id, name = _parse_title(raw_title)
    if not notice_id:
        return None

    deadline = _parse_deadline(description)
    if deadline is not None and deadline < today:
        return None  # belt-and-suspenders: skip stale deadlines even though this feed is meant to be "open only"

    return Opportunity(
        notice_id=notice_id,
        source_id=source_id,
        title=name or notice_id,
        agency=agency,
        url=link,
        description=description,
        posted_date=_parse_pub_date(item.findtext("pubDate")),
        response_deadline=deadline,
        state=state,
        city=city,
        raw={},
    )


def fetch(cfg: dict, source_id: str, agency: str, city: str, state: str) -> list:
    log = logging.getLogger(__name__)
    feed_url = cfg["source_urls"][source_id]
    today = date.today()

    try:
        resp = requests.get(feed_url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)
    except requests.RequestException as e:
        raise SourceError(f"{agency} Bonfire RSS fetch failed ({feed_url}): {e}") from e
    except ElementTree.ParseError as e:
        raise SourceError(f"{agency} Bonfire RSS: couldn't parse feed XML ({feed_url}): {e}") from e

    items = root.findall(".//item")
    opportunities = []
    for item in items:
        opp = _parse_item(item, today, source_id, agency, city, state)
        if opp is not None:
            opportunities.append(opp)

    log.info("%s Bonfire RSS returned %d open opportunities (of %d in feed)", agency, len(opportunities), len(items))
    return opportunities
