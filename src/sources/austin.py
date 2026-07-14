"""City of Austin (Austin Finance Online) active solicitations.

There is no RSS feed — that was a wrong guess in an earlier version of this
scraper (the guessed URL 404'd). The real active-solicitations page
(https://financeonline.austintexas.gov/afo/account_services/solicitation/
solicitations.cfm) is plain server-rendered ColdFusion HTML with the full
listing already present in the initial page load — the page also loads a
solicitations.js that makes $.ajax calls, but those are for interactive
vendor actions (submitting bids, deactivating an eBid), not for loading the
list, so a plain GET + BeautifulSoup is enough; no headless browser needed.

Confirmed structure (2026-07): each solicitation is a
`<div class="well parent"><div class="td-space-left clearfix child">...`
block containing, in order:
  1. a category icon (`<i class="... thumbnail" title="category description">`)
  2. `<strong><a href="solicitation_details.cfm?sid=N">SOLICITATION NUMBER</a></strong>`
  3. a duplicate "View Details" link to the same sid
  4. `Due Date: <strong>MM/DD/YYYY at H(AM|PM)</strong>`
  5. `<strong>PLAIN-ENGLISH TITLE</strong>`

The page's "View All" category filter appears to be the default (a broad
mix of categories showed up in initial testing with no filter applied), and
no pagination controls were found — this assumes the page lists ALL current
active solicitations on one request. If that assumption turns out wrong
(e.g. Austin later adds pagination), this will need extending.
"""

import logging
import re
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.sources.base import Opportunity, SourceError
from src.sources.html_table import parse_date as parse_mdy_date

REQUEST_TIMEOUT = 30
HEADERS = {"User-Agent": "PC-Gov-opportunity-finder/1.0"}
DUE_DATE_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})")


def _parse_block(block, base_url: str):
    strongs = block.find_all("strong")
    if len(strongs) < 2:
        return None

    id_link = strongs[0].find("a", href=True)
    if not id_link:
        return None
    solicitation_number = strongs[0].get_text(strip=True)
    full_url = urljoin(base_url, id_link["href"])
    sid = (parse_qs(urlparse(full_url).query).get("sid") or [None])[0]
    if not sid:
        return None

    due_match = DUE_DATE_RE.search(strongs[1].get_text(" ", strip=True))
    deadline = parse_mdy_date(due_match.group(1)) if due_match else None

    plain_title = strongs[2].get_text(strip=True) if len(strongs) > 2 else ""
    title = f"{solicitation_number} — {plain_title}" if plain_title else solicitation_number

    category_icon = block.find("i", class_="thumbnail")
    category_desc = category_icon.get("title", "") if category_icon else ""

    return Opportunity(
        notice_id=sid,
        source_id="austin",
        title=title,
        agency="City of Austin",
        url=full_url,
        description=f"{category_desc} {plain_title}".strip(),
        response_deadline=deadline,
        city="Austin",
        state="TX",
        raw={"solicitation_number": solicitation_number},
    )


def fetch(cfg: dict) -> list:
    url = cfg["source_urls"]["austin"]
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SourceError(f"Austin fetch failed ({url}): {e}") from e

    soup = BeautifulSoup(resp.text, "lxml")
    blocks = soup.select("div.well.parent")
    if not blocks:
        raise SourceError(
            "Austin: no 'well parent' solicitation blocks found — markup likely changed. "
            "See README 'Debugging a source'."
        )

    opportunities = [o for o in (_parse_block(b, url) for b in blocks) if o is not None]
    logging.getLogger(__name__).info("Austin returned %d opportunities", len(opportunities))
    return opportunities
