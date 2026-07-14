"""City of San Antonio open bids/contract opportunities.

Confirmed live structure (2026-07): classic ASP.NET WebForms GridView
(id="ContentPlaceHolder1_gvBidContractOpps") with columns Description
(title + link), Type, Department, Post Date, Political Contribution
Black-Out Start Date, Solicitation Deadline. Page 1 is a plain GET; paging
beyond that is a real __doPostBack form submission (not JS-rendered
content), which is simulated below with a plain requests.Session — no
headless browser needed.

IMPORTANT: the GridView's last row is a pager widget containing a *nested*
<table> (page links "1 2 3..."), not bid data. An earlier version of this
scraper naively recursed into every <tr> in the outer table, which picked
up the pager's inner row as if it were a real listing (that's where
garbage titles like "12" and "1" came from in initial testing). Rows are
now restricted to direct children of the outer table, and any row
containing a nested table is explicitly skipped as the pager.
"""

import logging
import re
import time
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.sources.base import Opportunity, SourceError
from src.sources.html_table import parse_date

REQUEST_TIMEOUT = 30
MAX_PAGES = 5
PAGE_DELAY_SECONDS = 1.5
TABLE_ID = "ContentPlaceHolder1_gvBidContractOpps"
EVENT_TARGET = "ctl00$ContentPlaceHolder1$gvBidContractOpps"
HEADERS = {"User-Agent": "PC-Gov-opportunity-finder/1.0"}


def _hidden_value(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find("input", attrs={"name": name})
    return tag["value"] if tag and tag.has_attr("value") else ""


def _is_pager_row(row) -> bool:
    return row.find("table") is not None


def _parse_row(row, base_url: str):
    cells = row.find_all("td", recursive=False)
    if len(cells) < 6:
        return None
    desc_cell, type_cell, dept_cell, post_cell, _blackout_cell, deadline_cell = cells[:6]

    link = desc_cell.find("a", href=True)
    if not link:
        return None
    title = link.get_text(strip=True)
    full_url = urljoin(base_url, link["href"])
    notice_id = (parse_qs(urlparse(full_url).query).get("id") or [None])[0] or title[:80]

    department = dept_cell.get_text(strip=True)
    agency = f"City of San Antonio — {department}" if department else "City of San Antonio"

    return Opportunity(
        notice_id=notice_id,
        source_id="san_antonio",
        title=title,
        agency=agency,
        url=full_url,
        posted_date=parse_date(post_cell.get_text(strip=True)),
        response_deadline=parse_date(deadline_cell.get_text(strip=True)),
        city="San Antonio",
        state="TX",
        raw={"type": type_cell.get_text(strip=True), "department": department},
    )


def _next_page_link(pager_row, next_page: int):
    if pager_row is None:
        return None
    pattern = re.compile(re.escape(f"Page${next_page}") + r"\b")
    return pager_row.find("a", href=pattern)


def fetch(cfg: dict) -> list:
    url = cfg["source_urls"]["san_antonio"]
    log = logging.getLogger(__name__)
    session = requests.Session()

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SourceError(f"San Antonio fetch failed ({url}): {e}") from e

    soup = BeautifulSoup(resp.text, "lxml")
    opportunities = []
    page = 1

    while True:
        table = soup.find("table", id=TABLE_ID)
        if table is None:
            if page == 1:
                raise SourceError(
                    f"San Antonio: table #{TABLE_ID} not found on page 1 — markup likely changed. "
                    "See README 'Debugging a source'."
                )
            log.warning("San Antonio: expected table missing after paging to page %d, stopping there", page)
            break

        rows = table.find_all("tr", recursive=False)[1:]  # skip header
        pager_row = None
        for row in rows:
            if _is_pager_row(row):
                pager_row = row
                continue
            opp = _parse_row(row, url)
            if opp:
                opportunities.append(opp)

        if page >= MAX_PAGES:
            break
        link = _next_page_link(pager_row, page + 1)
        if link is None:
            break  # no further page offered — this was the last one

        form_data = {
            "__EVENTTARGET": EVENT_TARGET,
            "__EVENTARGUMENT": f"Page${page + 1}",
            "__VIEWSTATE": _hidden_value(soup, "__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": _hidden_value(soup, "__VIEWSTATEGENERATOR"),
            "__EVENTVALIDATION": _hidden_value(soup, "__EVENTVALIDATION"),
        }
        time.sleep(PAGE_DELAY_SECONDS)
        try:
            resp = session.post(url, data=form_data, timeout=REQUEST_TIMEOUT, headers=HEADERS)
            resp.raise_for_status()
        except requests.RequestException as e:
            log.warning("San Antonio: postback to page %d failed (%s), stopping there", page + 1, e)
            break
        soup = BeautifulSoup(resp.text, "lxml")
        page += 1

    log.info("San Antonio returned %d opportunities across %d page(s)", len(opportunities), page)
    return opportunities
