"""City of New Orleans — "View bid opportunities" page
(`nola.gov/view-bid-opportunities/`).

Independently confirmed live 2026-07-22: `robots.txt`'s wildcard rule
(`User-agent: * / Disallow: /admin`) doesn't restrict this page -- the
more specific rules further down (blocking query-string URLs, `/311/
quick-access`) are scoped to named bots like Googlebot/bingbot, not the
wildcard group. Real page source (view-source, not just rendered text)
confirms this is a plain server-rendered Kentico CMS page -- the bid list
itself is present in the initial HTML, no JS rendering needed, even
though each listing links out to an external Infor CloudSuite supplier
portal (sms-nola-prd.inforcloudsuite.com) for the actual submission/detail
view. Title, description, and every lifecycle date (including the
closing deadline) live on nola.gov's own page.

New Orleans (505.9mi from Stephenville, TX) is right at the edge of the
company's service radius -- see geo.py's explicit ("New Orleans", "LA")
CITY_CENTROIDS entry and config.yaml's widened radius_miles (525),
both added specifically to bring this source into scope accurately rather
than relying on the much-closer Louisiana state centroid fallback.

Uses BeautifulSoup's "html.parser" backend, not lxml -- confirmed against
the real page that lxml silently mis-parses this page's nested-<li>
structure (each bid's date list is itself a <ul> of <li> elements nested
inside that bid's outer <li>), corrupting item boundaries so fields from
one bid item leak into another (e.g. a later item's "Set-Aside Program
Eligible" flag showed up on every earlier item too). html.parser handles
the same markup correctly.
"""

import logging
import re
from datetime import date, datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.sources.base import Opportunity, SourceError

REQUEST_TIMEOUT = 30
HEADERS = {"User-Agent": "PC-Gov-opportunity-finder/1.0"}
NOTICE_RE = re.compile(r"#(\d+)\s+(\S+)")


def _parse_date(text: str):
    """This page's dates are abbreviated-month ("Jul 24, 2026"), not the
    full-month format html_table.parse_date expects -- a local parser here
    avoids adding a format to that shared helper other sources don't need."""
    if not text:
        return None
    try:
        return datetime.strptime(text, "%b %d, %Y").date()
    except ValueError:
        return None


def _fetch(page_url: str) -> BeautifulSoup:
    try:
        resp = requests.get(page_url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SourceError(f"New Orleans fetch failed ({page_url}): {e}") from e
    return BeautifulSoup(resp.text, "html.parser")


def _date_fields(li) -> dict:
    """Each date li is `<li><strong>Label:</strong><br/>Value</li>` --
    strip the label's own text off the front of the combined text to get
    just the value (value is often blank, e.g. an unfilled "Submitted by:")."""
    fields = {}
    rows = li.find_all("div", class_="row", recursive=False)
    if len(rows) < 2:
        return fields
    date_list = rows[1].find("ul")
    if date_list is None:
        return fields
    for item in date_list.find_all("li", recursive=False):
        strong = item.find("strong")
        if strong is None:
            continue
        label = strong.get_text(strip=True).rstrip(":")
        full_text = item.get_text(" ", strip=True)
        label_text = strong.get_text(strip=True)
        value = full_text[len(label_text):].strip()
        fields[label] = value
    return fields


def _parse_closing_date(value: str):
    if not value:
        return None
    date_part = value.split(" at ")[0].strip()
    return _parse_date(date_part)


def _parse_item(li, page_url: str, today: date):
    h3 = li.find("h3")
    if h3 is None:
        return None
    small = h3.find("small")
    link = h3.find("a", href=True)
    if link is None:
        return None
    title = link.get_text(strip=True)
    detail_url = urljoin(page_url, link["href"])

    notice_id = None
    if small is not None:
        match = NOTICE_RE.search(small.get_text(strip=True))
        if match:
            notice_id = match.group(1)
    if notice_id is None:
        return None

    rows = li.find_all("div", class_="row", recursive=False)
    description = rows[0].get_text(" ", strip=True) if rows else title

    fields = _date_fields(li)
    closes_value = fields.get("Closes", "")
    closing_date = _parse_closing_date(closes_value)
    if closing_date is not None and closing_date < today:
        return None  # belt-and-suspenders, even though the page's own heading says "currently open"

    posted_date = _parse_closing_date(fields.get("Solicitation Release", ""))
    agency = fields.get("Submitted by") or "City of New Orleans"
    set_aside = None
    if li.find("div", class_="media-left-text-aside") is not None:
        set_aside = "Set-Aside Program Eligible"

    return Opportunity(
        notice_id=notice_id,
        source_id="new_orleans",
        title=title,
        agency=agency,
        url=detail_url,
        description=description,
        posted_date=posted_date,
        response_deadline=closing_date,
        set_aside=set_aside,
        state="LA",
        city="New Orleans",
        raw=fields,
    )


def fetch(cfg: dict) -> list:
    log = logging.getLogger(__name__)
    page_url = cfg["source_urls"]["new_orleans"]
    today = date.today()
    soup = _fetch(page_url)

    items = soup.find_all("li", class_="media-bid-opportunity")
    opportunities = []
    for li in items:
        opp = _parse_item(li, page_url, today)
        if opp is not None:
            opportunities.append(opp)

    log.info("New Orleans returned %d open opportunities (of %d listed)", len(opportunities), len(items))
    return opportunities
