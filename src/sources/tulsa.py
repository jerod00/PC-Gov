"""City of Tulsa — "Bid Opportunities and Results" page.

Independently confirmed live 2026-07-22: `robots.txt` 404s at this exact
path (no file declared -- same precedent as San Antonio/Austin, treated
as "no restriction, clear to crawl"), and the real page source confirms
a plain server-rendered `<table>` (columns: Bid # (Addendum) / Response
Deadline / Description), no JS rendering needed. Structurally the
simplest source in this project: no agency field, no full description
paragraph, no dollar value -- just a bid number, a deadline, and a short
title, similar in spirit to Dallas County's thin listing.

Oklahoma City, in contrast, was checked the same round and is a dead
end: its primary channel is BidNet Direct (already declined elsewhere in
this project for blocking ClaudeBot/anthropic-ai by name in robots.txt),
and its own okc.gov "Bidding" page is just a pointer back to BidNet
Direct, not a native listing.

One real wrinkle: the bid number cell includes a parenthesized addendum
count that increments over the life of a bid, e.g. "TAC 195G (0)" ->
"TAC 195G (1)" if an addendum is posted later -- confirmed live (a real
item, "RFP 26-917 (2)", already had two). Using that full string as
notice_id would treat the same bid as a new opportunity every time an
addendum posts, so notice_id strips the "(N)" suffix to stay stable; the
full addendum-count text is kept in raw for reference.
"""

import logging
import re
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.sources.base import Opportunity, SourceError
from src.sources.html_table import parse_date

REQUEST_TIMEOUT = 30
HEADERS = {"User-Agent": "PC-Gov-opportunity-finder/1.0"}
BASE_URL = "https://www.cityoftulsa.org"
ADDENDUM_RE = re.compile(r"^(.*?)\s*\(\d+\)\s*$")


def _fetch(page_url: str) -> BeautifulSoup:
    try:
        resp = requests.get(page_url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SourceError(f"Tulsa fetch failed ({page_url}): {e}") from e
    return BeautifulSoup(resp.text, "lxml")


def _find_target_table(soup):
    for table in soup.find_all("table"):
        text = table.get_text(" ", strip=True)
        if "Bid #" in text and "Response Deadline" in text:
            return table
    return None


def _parse_row(cells, page_url: str, today: date):
    bid_cell, deadline_cell, description_cell = cells[0], cells[1], cells[2]

    bid_text = bid_cell.get_text(strip=True)
    if not bid_text:
        return None
    match = ADDENDUM_RE.match(bid_text)
    notice_id = match.group(1).strip() if match else bid_text

    link = bid_cell.find("a", href=True)
    detail_url = urljoin(BASE_URL, link["href"]) if link is not None else page_url

    closing_date = parse_date(deadline_cell.get_text(strip=True))
    if closing_date is not None and closing_date < today:
        return None  # belt-and-suspenders, even though this page appears to list only current bids

    description = description_cell.get_text(" ", strip=True)

    return Opportunity(
        notice_id=notice_id,
        source_id="tulsa",
        title=description or bid_text,
        agency="City of Tulsa",
        url=detail_url,
        description=description,
        response_deadline=closing_date,
        state="OK",
        city="Tulsa",
        raw={"bid_text": bid_text},
    )


def fetch(cfg: dict) -> list:
    log = logging.getLogger(__name__)
    page_url = cfg["source_urls"]["tulsa"]
    today = date.today()
    soup = _fetch(page_url)

    table = _find_target_table(soup)
    if table is None:
        raise SourceError(
            "Tulsa: bid table not found — markup likely changed. See README 'Debugging a source'."
        )

    opportunities = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue  # header row (uses <th>, not <td>)
        opp = _parse_row(cells, page_url, today)
        if opp is not None:
            opportunities.append(opp)

    log.info("Tulsa returned %d open opportunities", len(opportunities))
    return opportunities
