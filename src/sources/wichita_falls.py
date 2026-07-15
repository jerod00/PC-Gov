"""City of Wichita Falls — CivicEngage "Bid Postings" board.

Confirmed live (2026-07): plain server-rendered ASP.NET page (CivicEngage/
CivicPlus platform), no JS rendering needed. `robots.txt` has no blanket
disallow and no named block for AI crawlers -- checked specifically after
finding that the *same* CivicEngage platform on Abilene, TX explicitly
disallows ClaudeBot (a deliberate policy, treated as a hard stop there
regardless of technical feasibility). Wichita Falls does not have that
block, so this one is fair game.

The default page (`Bids.aspx`, no query string) already filters
server-side to currently open bids via a "Show Me: Open Bids" dropdown --
confirmed empty at build time (zero open bids that day), so the actual
row markup was verified instead against `?showAllBids=on` (which also
shows closed/awarded/cancelled bids, structurally identical rows just
with a different Status value). Same lesson as Oklahoma/TX ESBD either
way: don't fully trust the server's own filtering -- each row's Status
span is checked client-side too, and only "Open" rows are kept.

No pagination found -- the board appears to list everything matching the
current filter on one page.
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
BID_NUMBER_RE = re.compile(r"Bid No\.\s*(\S+)", re.IGNORECASE)


def _fetch(page_url: str) -> BeautifulSoup:
    try:
        resp = requests.get(page_url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SourceError(f"Wichita Falls fetch failed ({page_url}): {e}") from e
    return BeautifulSoup(resp.text, "lxml")


def _parse_row(row, page_url: str):
    title_div = row.find("div", class_="bidTitle")
    if title_div is None:
        return None

    title_link = title_div.find("a", href=True)
    if title_link is None:
        return None
    title = title_link.get_text(strip=True)
    detail_url = urljoin(page_url, title_link["href"])

    full_text = title_div.get_text(" ", strip=True)
    bid_number_match = BID_NUMBER_RE.search(full_text)
    bid_number = bid_number_match.group(1) if bid_number_match else None

    spans = title_div.find_all("span", recursive=False)
    description = spans[2].get_text(" ", strip=True) if len(spans) > 2 else title

    status_div = row.find("div", class_="bidStatus")
    status = None
    closing_date = None
    if status_div is not None:
        value_divs = status_div.find_all("div", recursive=False)
        if len(value_divs) >= 2:
            value_spans = value_divs[1].find_all("span")
            if len(value_spans) >= 1:
                status = value_spans[0].get_text(strip=True)
            if len(value_spans) >= 2:
                closing_text = value_spans[1].get_text(strip=True).split()[0]
                closing_date = parse_date(closing_text)

    if status is not None and status.strip().lower() != "open":
        return None  # closed/awarded/cancelled -- not actionable

    notice_id = bid_number or detail_url

    return Opportunity(
        notice_id=notice_id,
        source_id="wichita_falls",
        title=title,
        agency="City of Wichita Falls",
        url=detail_url,
        description=description,
        response_deadline=closing_date,
        state="TX",
        city="Wichita Falls",
        raw={"status": status},
    )


def fetch(cfg: dict) -> list:
    log = logging.getLogger(__name__)
    page_url = cfg["source_urls"]["wichita_falls"]
    today = date.today()
    soup = _fetch(page_url)

    rows = soup.find_all("div", class_=lambda c: c and "listItemsRow" in c.split())
    opportunities = []
    for row in rows:
        opp = _parse_row(row, page_url)
        if opp is None:
            continue
        if opp.response_deadline is not None and opp.response_deadline < today:
            continue  # belt-and-suspenders: skip stale deadlines even if marked "Open"
        opportunities.append(opp)

    log.info("Wichita Falls returned %d open opportunities", len(opportunities))
    return opportunities
