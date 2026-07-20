"""Shared fetch/parse logic for CivicPlus/CivicEngage "Bids" module pages
(`Bids.aspx`), used by multiple orgs on the same commercial platform —
confirmed structurally identical markup across Wichita Falls and Galveston
(`listItemsRow`/`bidTitle`/`bidStatus` divs, same span ordering).

Each org gets its own robots.txt check (CivicEngage is shared hosting, not
one policy) -- Abilene, on the same platform, explicitly disallows
ClaudeBot, so never assume one org's policy for another.

Notice-id extraction: the `bidTitle` div's second direct-child span holds
"Bid No. <value>" text, e.g. "Bid No. RFQ 22-02" or "Bid No. 16-035" --
the value itself can contain spaces/multiple tokens, so this strips the
literal "Bid No." prefix rather than capturing a single \\S+ token (which
would truncate "RFQ 22-02" down to just "RFQ").
"""

import logging
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.sources.base import Opportunity, SourceError
from src.sources.html_table import parse_date

REQUEST_TIMEOUT = 30
HEADERS = {"User-Agent": "PC-Gov-opportunity-finder/1.0"}


def _bid_number(span_text: str) -> str:
    text = span_text.strip()
    lower = text.lower()
    if lower.startswith("bid no."):
        return text[len("bid no."):].strip()
    return text


def _fetch(page_url: str, agency: str) -> BeautifulSoup:
    try:
        resp = requests.get(page_url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SourceError(f"{agency} CivicEngage fetch failed ({page_url}): {e}") from e
    return BeautifulSoup(resp.text, "lxml")


def _parse_row(row, page_url: str, source_id: str, agency: str, city: str, state: str):
    title_div = row.find("div", class_="bidTitle")
    if title_div is None:
        return None

    title_link = title_div.find("a", href=True)
    if title_link is None:
        return None
    title = title_link.get_text(strip=True)
    detail_url = urljoin(page_url, title_link["href"])

    spans = title_div.find_all("span", recursive=False)
    bid_number = _bid_number(spans[1].get_text(" ", strip=True)) if len(spans) > 1 else ""
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
        source_id=source_id,
        title=title,
        agency=agency,
        url=detail_url,
        description=description,
        response_deadline=closing_date,
        state=state,
        city=city,
        raw={"status": status},
    )


def fetch(cfg: dict, source_id: str, agency: str, city: str, state: str) -> list:
    log = logging.getLogger(__name__)
    page_url = cfg["source_urls"][source_id]
    today = date.today()
    soup = _fetch(page_url, agency)

    rows = soup.find_all("div", class_=lambda c: c and "listItemsRow" in c.split())
    opportunities = []
    for row in rows:
        opp = _parse_row(row, page_url, source_id, agency, city, state)
        if opp is None:
            continue
        if opp.response_deadline is not None and opp.response_deadline < today:
            continue  # belt-and-suspenders: skip stale deadlines even if marked "Open"
        opportunities.append(opp)

    log.info("%s CivicEngage returned %d open opportunities", agency, len(opportunities))
    return opportunities
