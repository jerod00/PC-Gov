"""City of San Antonio open bids/contract opportunities.

The city runs a custom, server-rendered ASP.NET WebForms app (not a modern
JS SPA), which makes it more scrape-feasible than the Bonfire-based Dallas/
Fort Worth portals — but WebForms apps commonly paginate/filter via postback
(viewstate tokens) rather than plain query strings, so this only reliably
sees whatever the *default* GET of the base URL renders (typically the
current open-bids list, unpaginated or first page).

CAVEAT: built without live access to the site (network access to .gov
domains was unavailable in the build environment). If a real run returns 0
rows, see README "Debugging a source": fetch the page yourself, inspect the
actual table structure, and adjust html_table.HEADER_ALIASES or the
table-selection heuristic if the markup differs from what's assumed here.
"""

import logging
import re

import requests
from bs4 import BeautifulSoup

from src.sources.base import Opportunity, SourceError
from src.sources.html_table import best_table, parse_date

REQUEST_TIMEOUT = 30


def fetch(cfg: dict) -> list:
    url = cfg["source_urls"]["san_antonio"]
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "PC-Gov-opportunity-finder/1.0"})
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SourceError(f"San Antonio fetch failed ({url}): {e}") from e

    soup = BeautifulSoup(resp.text, "lxml")
    table, mapping = best_table(soup)
    if table is None:
        raise SourceError(
            "San Antonio: no recognizable bid table found on the page — the site "
            "likely changed markup or is now rendering the list via JS/postback. "
            "See README 'Debugging a source'."
        )

    opportunities = []
    rows = table.find_all("tr")[1:]  # skip header
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
                source_id="san_antonio",
                title=title,
                agency="City of San Antonio",
                url=link,
                posted_date=parse_date(values.get("posted_date", "")),
                response_deadline=parse_date(values.get("close_date", "")),
                city="San Antonio",
                state="TX",
                raw=values,
            )
        )

    logging.getLogger(__name__).info("San Antonio returned %d rows", len(opportunities))
    return opportunities
