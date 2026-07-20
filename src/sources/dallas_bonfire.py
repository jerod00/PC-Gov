"""City of Dallas — Bonfire portal (dallascityhall.bonfirehub.com) public
"Opportunity RSS Feed".

IMPORTANT — this reverses an earlier finding in this project. Dallas'
Bonfire subdomain was previously confirmed (documented in config.yaml/
README) to have a blanket `robots.txt` block (`User-agent: * / Disallow:
/`), the same policy every other Bonfire/Euna-family portal in this
project has, and was deliberately left un-scraped as a result. Re-checked
live 2026-07-20: `dallascityhall.bonfirehub.com/robots.txt` now reads
`User-agent: * / Disallow:` (empty -- nothing disallowed). Whether this is
a deliberate policy change or the block was scoped differently than
assumed, the current live file is what governs, and it permits this.

Fort Worth (`fortworthtexas.bonfirehub.com`) and every other Bonfire-family
subdomain in this project (Harris County, San Angelo, Tarrant County/Ion
Wave) are NOT assumed to share this change -- each was independently
confirmed blocked before, "one Bonfire org changed its robots.txt" is not
evidence another did too, and they stay disabled until individually
re-checked against their own live robots.txt.

Rather than scrape the portal's HTML (a SPA, like Houston's Beacon Bid),
Bonfire publishes a stable, intentionally-public RSS feed per organization
meant for external embedding (Bonfire's own vendor-support documentation:
"Opportunity RSS Feed" -- provides "all opportunities for this
organization that are visible through the public portal"). URL pattern:
`https://<org>.bonfirehub.com/opportunities/rss`. This is plain RSS 2.0
XML, confirmed against a real fetched sample (2026-07-20) -- no
JavaScript, no session cookie, no login.

Feed item shape, confirmed from the real sample:
  <title>Reference #: <ref>. Name: <name></title>
  <description>Description: <details> ... Project closes <Mon DD, YYYY>
    <H:MM AM/PM> <TZ>.</description>
  <pubDate>Weekday, DD Mon YYYY HH:MM:SS -ZZZZ</pubDate>
  <link>https://dallascityhall.bonfirehub.com/opportunities/<id></link>

The feed has no per-item value/NAICS/PSC field -- those stay unset, same
as several other lightweight sources in this project (Dallas County,
Wichita Falls). No pagination in the sample; the feed appears to list
everything currently open on the public portal in one response.
"""

import logging
import re
from datetime import date
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
        from datetime import datetime
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


def _parse_item(item, today: date):
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
        source_id="dallas_bonfire",
        title=name or notice_id,
        agency="City of Dallas",
        url=link,
        description=description,
        posted_date=_parse_pub_date(item.findtext("pubDate")),
        response_deadline=deadline,
        state="TX",
        city="Dallas",
        raw={},
    )


def fetch(cfg: dict) -> list:
    log = logging.getLogger(__name__)
    feed_url = cfg["source_urls"]["dallas_bonfire"]
    today = date.today()

    try:
        resp = requests.get(feed_url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)
    except requests.RequestException as e:
        raise SourceError(f"Dallas Bonfire RSS fetch failed ({feed_url}): {e}") from e
    except ElementTree.ParseError as e:
        raise SourceError(f"Dallas Bonfire RSS: couldn't parse feed XML ({feed_url}): {e}") from e

    items = root.findall(".//item")
    opportunities = []
    for item in items:
        opp = _parse_item(item, today)
        if opp is not None:
            opportunities.append(opp)

    log.info("Dallas Bonfire RSS returned %d open opportunities (of %d in feed)", len(opportunities), len(items))
    return opportunities
