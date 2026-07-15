"""Louisiana LaPAC (Office of State Purchasing) — open solicitations search.

Confirmed live structure (2026-07): plain server-rendered ColdFusion page,
a single <table class="bid"> with columns Bid Number / Description / Date
Issued / Bid Open Date/Time / Help. No login, no JS rendering, no page
parameter found — the "open" search (compareDate=O) appears to return
everything currently open on one page.

IMPORTANT — this is NOT one row per bid. The site groups a bid's original
posting and its addenda into a run of physical <tr>s that share one logical
entry: the first row carries the bid number, open date, and help-contact
cells with rowspan (2+), and every following row until the next bid only
repeats a "Description"-column cell (the addendum text) and a "Date Issued"
cell. We only need the first physical row of each group — its description
cell already reflects the bid's current status (e.g. a cancelled bid shows
"Bid Cancelled: <date>" right there), so there is no need to also read the
addendum rows just to find out a bid was cancelled. A group-start row is
identified structurally: it has >= 5 <td>s and its first <td> contains the
<span> holding the bid number; continuation rows don't carry that span.

response_deadline handling: cancelled bids show a sentinel open date of
12/30/9999 (a valid Python date — year 9999 is datetime.MAXYEAR — so it
parses without error but is meaningless). Treated as "no real deadline"
below rather than surfaced as a real date, though in practice this should
only ever show up on bids we've already filtered out via the cancellation
text check.

No per-listing agency/city field is exposed on this results table (the
Department dropdown filters the search but isn't echoed per row, and the
Help link's contact popup would need one extra request per listing to
resolve — not worth it for an MVP). Distance filtering therefore falls back
to the Louisiana state centroid (src/geo.py), same approach used for
Oklahoma; central/northern Louisiana cities are the ones actually within
500 miles of Stephenville, TX, and are the closest match to a fabrication
shop's likely customer base in-state, but a bid from a city near New
Orleans would be misclassified as in-radius by this fallback — see the
"NOTE ON DATA" caveat already in geo.py.
"""

import logging
import re

import requests
from bs4 import BeautifulSoup

from src.sources.base import Opportunity, SourceError
from src.sources.html_table import parse_date

REQUEST_TIMEOUT = 30
HEADERS = {"User-Agent": "PC-Gov-opportunity-finder/1.0"}
CANCELLED_RE = re.compile(r"cancell?ed", re.IGNORECASE)
SENTINEL_MAX_YEAR = 9000  # LaPAC uses 12/30/9999 to mean "no real open date"


def _fetch(url: str) -> BeautifulSoup:
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SourceError(f"Louisiana LaPAC fetch failed ({url}): {e}") from e
    return BeautifulSoup(resp.text, "lxml")


def _clean_text_with_breaks(cell) -> str:
    for br in cell.find_all("br"):
        br.replace_with("\n")
    return "\n".join(line.strip() for line in cell.get_text().split("\n") if line.strip())


def _parse_group_row(row, url: str):
    cells = row.find_all("td")
    if len(cells) < 5:
        return None  # continuation row (addendum) — no new bid to report

    bid_span = cells[0].find("span")
    if bid_span is None:
        return None
    bid_number = bid_span.get_text(strip=True)
    if not bid_number:
        return None

    full_text = _clean_text_with_breaks(cells[1])
    if not full_text:
        return None
    if CANCELLED_RE.search(full_text):
        return None  # cancelled — not actionable

    title = full_text.split("\n")[0]
    posted_date = parse_date(cells[2].get_text(strip=True))

    open_date_text = cells[3].get_text(" ", strip=True)
    response_deadline = parse_date(open_date_text.split()[0]) if open_date_text else None
    if response_deadline is not None and response_deadline.year >= SENTINEL_MAX_YEAR:
        response_deadline = None

    return Opportunity(
        notice_id=bid_number,
        source_id="louisiana",
        title=title[:120] if title else bid_number,
        agency="Louisiana Office of State Purchasing (LaPAC)",
        url=url,
        description=full_text,
        posted_date=posted_date,
        response_deadline=response_deadline,
        state="LA",
        raw={},
    )


def fetch(cfg: dict) -> list:
    url = cfg["source_urls"]["louisiana"]
    log = logging.getLogger(__name__)

    soup = _fetch(url)
    table = soup.find("table", class_="bid")
    if table is None:
        raise SourceError(
            "Louisiana LaPAC: bid table not found — markup likely changed. "
            "See README 'Debugging a source'."
        )

    rows = table.find_all("tr")[1:]  # skip header row
    opportunities = []
    for row in rows:
        opp = _parse_group_row(row, url)
        if opp is not None:
            opportunities.append(opp)

    log.info("Louisiana LaPAC returned %d open opportunities", len(opportunities))
    return opportunities
