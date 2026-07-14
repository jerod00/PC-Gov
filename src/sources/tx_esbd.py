"""Texas ESBD (Electronic State Business Daily) via TxSmartBuy.

This is the single highest-value state source (all Texas state-agency
solicitations in one place) but also the most fragile: TxSmartBuy is a
stateful ASP.NET WebForms app, and search/pagination normally happens via
postback rather than plain query strings. This module only reads whatever
the base URL's default GET renders (typically the current open-solicitations
list). If that stops being enough (e.g. the list is paginated and later
pages hide relevant results), this needs real browser automation (Playwright)
instead of plain requests — flagged as a known limitation, not silently
worked around.

CAVEAT: built without live access to the site (network access to .gov
domains was unavailable in the build environment) — the table-detection
heuristic is generic (see html_table.py) rather than tuned to confirmed
markup. If a real run returns 0 rows, see README "Debugging a source".
Consider TxSmartBuy's CMBL vendor-notification signup as a supplement
regardless, since even a working scraper only sees the current snapshot.
"""

import logging
import re

import requests
from bs4 import BeautifulSoup

from src.sources.base import Opportunity, SourceError
from src.sources.html_table import best_table, parse_date

REQUEST_TIMEOUT = 30


def fetch(cfg: dict) -> list:
    url = cfg["source_urls"]["tx_esbd"]
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "PC-Gov-opportunity-finder/1.0"})
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SourceError(f"TX ESBD fetch failed ({url}): {e}") from e

    soup = BeautifulSoup(resp.text, "lxml")
    table, mapping = best_table(soup)
    if table is None:
        raise SourceError(
            "TX ESBD: no recognizable solicitation table found — the page is likely "
            "rendering results via postback/JS rather than the plain GET this scraper "
            "reads. See README 'Debugging a source', and consider the CMBL vendor "
            "notification signup as a supplement in the meantime."
        )

    opportunities = []
    rows = table.find_all("tr")[1:]
    for row in rows:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        values = {mapping[i]: cells[i].get_text(strip=True) for i in mapping if i < len(cells)}
        link_tag = row.find("a", href=True)
        link = link_tag["href"] if link_tag else url
        if link.startswith("/"):
            link = re.sub(r"(https?://[^/]+).*", r"\1", url) + link

        bid_no = values.get("bid", "").strip()
        title = values.get("title", "").strip()
        if not title:
            continue

        opportunities.append(
            Opportunity(
                notice_id=bid_no or title[:80],
                source_id="tx_esbd",
                title=title,
                agency=values.get("agency", "Texas state agency") or "Texas state agency",
                url=link,
                posted_date=parse_date(values.get("posted_date", "")),
                response_deadline=parse_date(values.get("close_date", "")),
                state="TX",
                raw=values,
            )
        )

    logging.getLogger(__name__).info("TX ESBD returned %d rows", len(opportunities))
    return opportunities
