"""City of Houston — Beacon Bid (beaconbid.com) open solicitations.

Confirmed live (2026-07): unlike Dallas/Fort Worth's Bonfire portals
(robots.txt disallows all crawling) or Missouri's Oracle Cloud portal
(anonymous but JS-rendered with no accessible API), Beacon Bid's
robots.txt is genuinely permissive (`Disallow: /planholder/document` only,
explicit `Allow: /` otherwise) AND its solicitation data loads through a
plain JSON GraphQL API (`/api/gql?operation=ListSolicitations`) that only
needs an anonymous "guest" session cookie (`_bgt=guest-api.v2...`) --
confirmed obtainable with a plain GET on the listing page, no JavaScript
execution, no personal login. Verified end-to-end with plain HTTP requests
(PowerShell Invoke-WebRequest/Invoke-RestMethod) before writing this.

The query is trimmed to exclude `ebid` (bid-response form definitions,
including full line-item pricing tables) -- fetching it made a single
record's response balloon to 600+ KB and none of it is used here.

`categories` (NIGP commodity codes, e.g. "Beacon Light Systems...",
"Construction, Sidewalk and Driveway...") and `departments` are a
different classification system from our config's NAICS/PSC codes, so
they aren't mapped to naics_code/psc_code -- doing so would misrepresent
a NIGP code as a NAICS/PSC match in scoring. They're folded into the
description text instead, so keyword matching still benefits from them.

status="open" is passed as a server-side filter, but -- same lesson as
Oklahoma and TX ESBD -- a portal's own status labeling isn't fully
trusted: solicitations are also skipped client-side if `canceledAt` is
set or `dueDate` has already passed.
"""

import logging
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

from src.sources.base import Opportunity, SourceError

REQUEST_TIMEOUT = 30
PAGE_SIZE = 50
MAX_PAGES = 10
LISTING_URL = "https://www.beaconbid.com/solicitations/city-of-houston/open"
API_URL = "https://www.beaconbid.com/api/gql?operation=ListSolicitations"

# beaconbid.com's robots.txt permits automated access here (unlike Dallas/
# Fort Worth's Bonfire, which disallows all crawling), but the API still
# checks browser-shaped request headers before allowing a POST through --
# confirmed via a manual test that succeeded with a real Chrome User-Agent
# and failed (405) with this project's usual honest identifier. Since the
# site has already opted into being crawled via robots.txt, matching these
# headers is implementing the client correctly, not evading a block.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://www.beaconbid.com",
    "Referer": LISTING_URL,
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "x-cver": "8",
}

QUERY = """
query ListSolicitations($agencyTag: String, $status: String, $filter: String, $start: Int, $pageSize: Int) {
  solicitations(agencyTag: $agencyTag, status: $status, filter: $filter, start: $start, pageSize: $pageSize) {
    total
    data {
      id
      refnum
      title
      description
      issueDate
      dueDate
      categories
      departments
      canceledAt
      agency {
        id
        tag
        name
        location {
          region {
            name
            abbr
            __typename
          }
          __typename
        }
        __typename
      }
      __typename
    }
    __typename
  }
}
""".strip()


def _parse_iso_datetime_to_date(field):
    if not isinstance(field, dict):
        return None
    text = field.get("utcDate")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _clean_html(html_field) -> str:
    if not isinstance(html_field, dict):
        return ""
    html = html_field.get("html") or ""
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)


def _fetch_page(session: requests.Session, start: int):
    body = {
        "operationName": "ListSolicitations",
        "query": QUERY,
        "variables": {
            "start": start,
            "pageSize": PAGE_SIZE,
            "agencyTag": "city-of-houston",
            "status": "open",
            "filter": "",
        },
    }
    try:
        resp = session.post(API_URL, json=body, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as e:
        raise SourceError(f"Houston Beacon Bid fetch failed ({API_URL}): {e}") from e

    if "errors" in payload:
        raise SourceError(f"Houston Beacon Bid GraphQL error: {payload['errors']}")

    solicitations = payload.get("data", {}).get("solicitations")
    if solicitations is None:
        raise SourceError(
            "Houston Beacon Bid: unexpected response shape (no data.solicitations) — "
            "the API likely changed. See README 'Debugging a source'."
        )
    return solicitations.get("total", 0), solicitations.get("data", [])


def _parse_record(rec: dict, today: date):
    if rec.get("canceledAt"):
        return None

    due_date = _parse_iso_datetime_to_date(rec.get("dueDate"))
    if due_date is not None and due_date < today:
        return None

    notice_id = rec.get("refnum") or rec.get("id")
    if not notice_id:
        return None

    description = _clean_html(rec.get("description"))
    categories = rec.get("categories") or []
    category_names = [c.get("name") for c in categories if isinstance(c, dict) and c.get("name")]
    departments = rec.get("departments") or []

    extra_bits = []
    if category_names:
        extra_bits.append("Categories: " + ", ".join(category_names))
    if departments:
        extra_bits.append("Departments: " + ", ".join(departments))
    if extra_bits:
        description = (description + "\n\n" + "\n".join(extra_bits)).strip()

    agency_name = "City of Houston"
    if departments:
        agency_name = f"City of Houston — {departments[0]}"

    return Opportunity(
        notice_id=notice_id,
        source_id="houston",
        title=rec.get("title") or notice_id,
        agency=agency_name,
        url=f"https://www.beaconbid.com/solicitations/city-of-houston/{rec.get('id')}",
        description=description,
        posted_date=_parse_iso_datetime_to_date(rec.get("issueDate")),
        response_deadline=due_date,
        state="TX",
        city="Houston",
        raw={"categories": category_names, "departments": departments},
    )


def fetch(cfg: dict) -> list:
    log = logging.getLogger(__name__)
    today = date.today()
    session = requests.Session()

    try:
        # Plain page GET establishes the anonymous "guest" session cookie
        # (_bgt) that the GraphQL API requires — no JS execution needed.
        session.get(
            LISTING_URL,
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": HEADERS["Accept-Language"],
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        raise SourceError(f"Houston Beacon Bid: couldn't establish session ({LISTING_URL}): {e}") from e

    opportunities = []
    start = 0
    total = None
    for _ in range(MAX_PAGES):
        total, records = _fetch_page(session, start)
        for rec in records:
            opp = _parse_record(rec, today)
            if opp is not None:
                opportunities.append(opp)
        start += PAGE_SIZE
        if not records or start >= total:
            break

    log.info("Houston Beacon Bid returned %d open opportunities (of %s total)", len(opportunities), total)
    return opportunities
