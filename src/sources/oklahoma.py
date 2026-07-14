"""Oklahoma OMES Central Purchasing — Solicitation Search Utility.

Confirmed live structure (2026-07): plain server-rendered PHP page, GET-based
search and pagination (?page=N), a real <table class="table_wrapper"> with
columns SW Number / Solicitation Number / Description / Amendments / Status /
Closing Date / Closing Date Status / Awarded Date. No login, no JS rendering.

IMPORTANT: the "open-pending" status bucket includes solicitations whose
Status text is something like "Pending Award" even when their Closing Date
is years in the past (confirmed in testing: a 2019 closing date showed up
under the "open" search) — status text alone isn't a reliable "can we still
bid on this" signal here, same lesson as TX ESBD. Filtered by closing date
instead: a listing is kept only if its closing date is blank/unparseable
(assume still open) or not yet past.

No per-listing agency/city field exists on this results table — the
purchasing agency, if mentioned at all, is embedded in the free-text
description. Distance filtering therefore falls back to the Oklahoma state
centroid (src/geo.py) rather than a real per-listing location; in practice
this is a reasonable approximation since even Oklahoma's panhandle is within
~400 miles of Stephenville, TX — comfortably inside the 500-mile radius.
"""

import logging
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.sources.base import Opportunity, SourceError
from src.sources.html_table import parse_date

REQUEST_TIMEOUT = 30
MAX_PAGES = 10
HEADERS = {"User-Agent": "PC-Gov-opportunity-finder/1.0"}


def _fetch_page(base_url: str, page: int) -> BeautifulSoup:
    url = base_url if page == 1 else f"{base_url}&page={page}"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SourceError(f"Oklahoma OMES fetch failed ({url}): {e}") from e
    return BeautifulSoup(resp.text, "lxml")


def _parse_row(row, base_url: str, today: date):
    cells = row.find_all("td")
    if len(cells) < 6:
        return None

    sol_link = cells[1].find("a", href=True)
    if not sol_link:
        return None
    sol_number = sol_link.get_text(strip=True)
    description = cells[2].get_text(" ", strip=True)
    status = cells[4].get_text(strip=True)
    closing_date = parse_date(cells[5].get_text(strip=True))

    if closing_date is not None and closing_date < today:
        return None  # bid window already closed, regardless of status text

    return Opportunity(
        notice_id=sol_number,
        source_id="oklahoma",
        title=description[:120] if description else sol_number,
        agency="Oklahoma OMES Central Purchasing",
        url=urljoin(base_url, sol_link["href"]),
        description=description,
        response_deadline=closing_date,
        state="OK",
        raw={"status": status},
    )


def fetch(cfg: dict) -> list:
    base_url = cfg["source_urls"]["oklahoma"]
    log = logging.getLogger(__name__)
    today = date.today()
    opportunities = []

    for page in range(1, MAX_PAGES + 1):
        soup = _fetch_page(base_url, page)
        table = soup.find("table", class_="table_wrapper")
        if table is None:
            if page == 1:
                raise SourceError(
                    "Oklahoma OMES: solicitation table not found — markup likely changed. "
                    "See README 'Debugging a source'."
                )
            break

        rows = table.find_all("tr")[1:]  # skip header row
        if not rows:
            break
        for row in rows:
            opp = _parse_row(row, base_url, today)
            if opp is not None:
                opportunities.append(opp)

        if not soup.find("a", title="Next Page"):
            break  # reached the last page

    log.info("Oklahoma OMES returned %d still-open opportunities", len(opportunities))
    return opportunities
