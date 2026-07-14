"""Texas ESBD (Electronic State Business Daily) via TxSmartBuy.

Confirmed live structure (2026-07): plain server-rendered HTML, no login,
no postback needed for the default view — each listing is a
`<div class="esbd-result-row">` (title link + labeled `<p><strong>Label:
</strong> value</p>` fields), NOT a table. Pagination is a plain
`?page=N` query string.

The default (unfiltered) view returns every solicitation ever posted,
sorted by most-recently-updated first, across thousands of pages. We only
need the first few pages each day — new/updated postings sort to the top,
and dedup in db.py handles anything that overlaps across days.

Listings mix live and dead postings (Posted, Addendum Posted, but also
Awarded, Closed, No Award, Posting Cancelled) — only the live ones are kept.
The same page also carries an agency dropdown mapping member numbers (e.g.
"M0152") to real names (e.g. "City of San Antonio"), used to resolve a
human-readable agency name instead of the bare code.
"""

import logging
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.sources.base import Opportunity, SourceError

REQUEST_TIMEOUT = 30
MAX_PAGES = 5              # ~20 rows/page; increase if daily volume outgrows this
PAGE_DELAY_SECONDS = 1.5   # be polite between paginated requests
LIVE_STATUSES = {"posted", "addendum posted"}


def _parse_date(text: str):
    text = (text or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _build_agency_map(soup: BeautifulSoup) -> dict:
    """The agency <select>'s option values are 'Name - Number' — build a
    {number: name} lookup so result rows (which only show the number) can
    display a real agency name."""
    mapping = {}
    select = soup.find("select", attrs={"name": "agency"})
    if not select:
        return mapping
    for option in select.find_all("option"):
        value = option.get("value", "").strip()
        if " - " not in value:
            continue
        name, _, number = value.rpartition(" - ")
        mapping[number.strip()] = name.strip()
    return mapping


def _row_fields(row) -> dict:
    fields = {}
    for p in row.find_all("p"):
        strong = p.find("strong")
        if not strong:
            continue
        label = strong.get_text(strip=True).rstrip(":").strip()
        full_text = p.get_text(" ", strip=True)
        label_text = strong.get_text(strip=True)
        value = full_text[len(label_text):].strip()
        fields[label] = value
    return fields


def _fetch_page(base_url: str, page: int) -> BeautifulSoup:
    url = base_url if page == 1 else f"{base_url}?page={page}"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "PC-Gov-opportunity-finder/1.0"})
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SourceError(f"TX ESBD fetch failed ({url}): {e}") from e
    return BeautifulSoup(resp.text, "lxml")


def fetch(cfg: dict) -> list:
    base_url = cfg["source_urls"]["tx_esbd"]
    opportunities = []
    agency_map = {}

    for page in range(1, MAX_PAGES + 1):
        soup = _fetch_page(base_url, page)
        if page == 1:
            agency_map = _build_agency_map(soup)

        rows = soup.find_all("div", class_="esbd-result-row")
        if not rows:
            if page == 1:
                raise SourceError(
                    "TX ESBD: no result rows found on page 1 — the site's markup has "
                    "likely changed again. See README 'Debugging a source'."
                )
            break  # ran past the last page

        for row in rows:
            title_link = row.select_one(".esbd-result-title a")
            if not title_link:
                continue
            fields = _row_fields(row)
            status = fields.get("Status", "").strip().lower()
            if status not in LIVE_STATUSES:
                continue

            member_number = fields.get("Agency/Texas SmartBuy Member Number", "").strip()
            agency = agency_map.get(member_number, f"TX SmartBuy Member {member_number}" if member_number else "Texas state agency")

            opportunities.append(
                Opportunity(
                    notice_id=fields.get("Solicitation ID", "").strip() or title_link.get_text(strip=True)[:80],
                    source_id="tx_esbd",
                    title=title_link.get_text(strip=True),
                    agency=agency,
                    url=urljoin(base_url, title_link["href"]),
                    posted_date=_parse_date(fields.get("Posting Date", "")),
                    response_deadline=_parse_date(fields.get("Due Date", "")),
                    state="TX",
                    raw=fields,
                )
            )

        if page < MAX_PAGES:
            time.sleep(PAGE_DELAY_SECONDS)

    logging.getLogger(__name__).info(
        "TX ESBD returned %d live opportunities across %d page(s)", len(opportunities), min(MAX_PAGES, page)
    )
    return opportunities
