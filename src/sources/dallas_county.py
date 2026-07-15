"""Dallas County (not City of Dallas) — "Current Formal Business
Opportunities" listing.

Distinct from the City of Dallas, whose only real bid data lives on the
Bonfire-hosted portal blocked by robots.txt (see config.yaml comments).
Dallas County is a separate government entity with its own domain
(dallascounty.org), whose robots.txt is wide open (`Allow: /`, no
disallow rules at all). Dallas County's *interactive* solicitation
platform is BidNet (same platform whose robots.txt names anthropic-ai/
ClaudeBot as disallowed elsewhere -- not used here), but the county also
publishes a plain, view-and-download-only mirror of current solicitations
on its own site, confirmed live (2026-07): a real server-rendered
Percussion-CMS page with one HTML <table> (columns Solicitation Number /
Title / Anticipated Closing Date / Buyer Name / Buyer E-mail Address),
each row linking directly to the actual bid packet PDF. No pagination
found -- the table appears to list everything currently open on one page.

Two markup quirks specific to this table, both confirmed against the real
page rather than guessed:
- The header row is a real `<tr>` with `<td>` cells (not `<th>`), marked
  only by a `class="tableHeaderBlue"` on the row itself -- skipped by
  checking for that class, not by cell count (it has the same 5 cells as
  every data row).
- Immediately after the header is a single blank spacer `<tr>` (all empty
  `<td>`s, height: 0px) -- skipped by checking the first cell has no text.

"Anticipated Closing Date" is sometimes literally "TBD" for solicitations
that haven't set a firm date yet; `response_deadline` is simply left None
for those rather than treated as an error.
"""

import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.sources.base import Opportunity, SourceError
from src.sources.html_table import parse_date

REQUEST_TIMEOUT = 30
HEADERS = {"User-Agent": "PC-Gov-opportunity-finder/1.0"}
BASE_URL = "https://www.dallascounty.org"


def _fetch(page_url: str) -> BeautifulSoup:
    try:
        resp = requests.get(page_url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SourceError(f"Dallas County fetch failed ({page_url}): {e}") from e
    return BeautifulSoup(resp.text, "lxml")


def _find_target_table(soup):
    for table in soup.find_all("table"):
        text = table.get_text(" ", strip=True)
        if "Solicitation Number" in text and "Anticipated Closing Date" in text:
            return table
    return None


def _parse_row(cells, page_url: str):
    sol_cell = cells[0]
    sol_number_tag = sol_cell.find("p")
    sol_number = (sol_number_tag.get_text(strip=True) if sol_number_tag
                  else sol_cell.get_text(" ", strip=True).split()[0])
    if not sol_number:
        return None

    doc_link = sol_cell.find("a", href=True)
    doc_title = ""
    doc_url = page_url
    if doc_link is not None:
        doc_title = doc_link.get("title") or doc_link.get_text(strip=True)
        doc_url = urljoin(BASE_URL, doc_link["href"])

    title = cells[1].get_text(" ", strip=True)
    closing_date = parse_date(cells[2].get_text(strip=True))
    buyer_name = cells[3].get_text(" ", strip=True)

    agency = f"Dallas County — {buyer_name}" if buyer_name else "Dallas County"
    description = doc_title or title

    return Opportunity(
        notice_id=sol_number,
        source_id="dallas_county",
        title=title or sol_number,
        agency=agency,
        url=doc_url,
        description=description,
        response_deadline=closing_date,
        state="TX",
        raw={},
    )


def fetch(cfg: dict) -> list:
    log = logging.getLogger(__name__)
    page_url = cfg["source_urls"]["dallas_county"]
    soup = _fetch(page_url)

    table = _find_target_table(soup)
    if table is None:
        raise SourceError(
            "Dallas County: solicitation table not found — markup likely changed. "
            "See README 'Debugging a source'."
        )

    opportunities = []
    for row in table.find_all("tr"):
        classes = row.get("class") or []
        if "tableHeaderBlue" in classes:
            continue  # header row
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        if not cells[0].get_text(strip=True):
            continue  # blank spacer row
        opp = _parse_row(cells, page_url)
        if opp is not None:
            opportunities.append(opp)

    log.info("Dallas County returned %d current opportunities", len(opportunities))
    return opportunities
