"""Federal opportunities via the SAM.gov Contract Opportunities API (v2).

Docs: https://open.gsa.gov/api/get-opportunities-public-api/
Two query strategies are combined and deduped by noticeId:
  1. NAICS-code search (broad, catches anything correctly coded)
  2. Title-keyword search per high-value term (catches miscoded postings
     that NAICS filtering alone would miss)
No geographic filtering — federal opportunities are pulled nationwide.
"""

import logging
from datetime import date, datetime, timedelta

import requests

from src.sources.base import Opportunity, SourceError

BASE_URL = "https://api.sam.gov/opportunities/v2/search"
DESC_URL = "https://api.sam.gov/opportunities/v2/noticedesc"
PAGE_SIZE = 100
MAX_PAGES = 10          # safety cap per query (up to 1000 results)
REQUEST_TIMEOUT = 30

log = logging.getLogger(__name__)


def _get(params: dict, api_key: str) -> dict:
    params = {**params, "api_key": api_key}
    try:
        resp = requests.get(BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise SourceError(f"SAM.gov request failed: {e}") from e


def _paginate(base_params: dict, api_key: str) -> list:
    results = []
    for page in range(MAX_PAGES):
        params = {**base_params, "limit": PAGE_SIZE, "offset": page * PAGE_SIZE}
        data = _get(params, api_key)
        batch = data.get("opportunitiesData", [])
        results.extend(batch)
        total = data.get("totalRecords", len(batch))
        if len(results) >= total or not batch:
            break
    return results


def _fetch_description(notice_id: str, desc_field: str, api_key: str) -> str:
    """The list endpoint's `description` field is a URL to the full text,
    not the text itself. Best-effort fetch; empty string on any failure so a
    slow/broken description endpoint never blocks the whole run."""
    if not desc_field or not desc_field.startswith("http"):
        return ""
    try:
        resp = requests.get(desc_field, params={"api_key": api_key}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get("description", "") if isinstance(data, dict) else ""
    except requests.RequestException:
        log.warning("SAM.gov description fetch failed for notice %s", notice_id)
        return ""


def _parse_date(s: str):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _to_opportunity(raw: dict, api_key: str, fetch_full_description: bool) -> Opportunity:
    notice_id = raw.get("noticeId", "")
    pop = raw.get("placeOfPerformance") or {}
    description = ""
    if fetch_full_description:
        description = _fetch_description(notice_id, raw.get("description", ""), api_key)

    value = None
    award = raw.get("award") or {}
    if award.get("amount"):
        try:
            value = float(award["amount"])
        except (TypeError, ValueError):
            value = None

    return Opportunity(
        notice_id=notice_id,
        source_id="sam_gov",
        title=raw.get("title", "").strip(),
        agency=raw.get("fullParentPathName", "") or raw.get("organizationType", ""),
        url=raw.get("uiLink") or f"https://sam.gov/opp/{notice_id}/view",
        description=description,
        naics_code=raw.get("naicsCode"),
        psc_code=raw.get("classificationCode"),
        value=value,
        set_aside=raw.get("typeOfSetAsideDescription") or raw.get("typeOfSetAside"),
        posted_date=_parse_date(raw.get("postedDate")),
        response_deadline=_parse_date(raw.get("responseDeadLine")),
        city=pop.get("city", {}).get("name") if isinstance(pop.get("city"), dict) else pop.get("city"),
        state=pop.get("state", {}).get("code") if isinstance(pop.get("state"), dict) else pop.get("state"),
        raw=raw,
    )


def fetch(cfg: dict, api_key: str) -> list:
    if not api_key:
        raise SourceError("SAM_GOV_API_KEY is not set — see README for how to get one")

    sam_cfg = cfg["sam_gov"]
    lookback = sam_cfg.get("lookback_days", 1)
    posted_to = date.today()
    posted_from = posted_to - timedelta(days=lookback)
    date_params = {
        "postedFrom": posted_from.strftime("%m/%d/%Y"),
        "postedTo": posted_to.strftime("%m/%d/%Y"),
    }

    raw_by_notice = {}

    # 1. NAICS-code search — comma-separated codes in one query.
    naics_codes = sam_cfg.get("naics_codes", [])
    if naics_codes:
        try:
            batch = _paginate({**date_params, "ncode": ",".join(naics_codes)}, api_key)
            for r in batch:
                raw_by_notice[r.get("noticeId")] = r
        except SourceError:
            raise  # let run_daily.py log and isolate this source's failure
        log.info("SAM.gov NAICS search returned %d results", len(batch))

    # 2. Keyword title search — one query per high-value term, to catch
    #    postings that would be miscoded/missed by NAICS filtering alone.
    keywords_cfg = cfg.get("keywords", {})
    high_value_terms = keywords_cfg.get("high_value", {}).get("terms", [])
    for term in high_value_terms:
        try:
            batch = _paginate({**date_params, "title": term}, api_key)
        except SourceError as e:
            log.warning("SAM.gov keyword search for %r failed: %s", term, e)
            continue
        for r in batch:
            raw_by_notice.setdefault(r.get("noticeId"), r)

    log.info("SAM.gov combined unique notices: %d", len(raw_by_notice))

    # Fetching full description text for every notice is expensive at scale;
    # do it for all of them here since NAICS+keyword pre-filtering already
    # keeps the daily volume manageable (typically well under a few hundred).
    return [_to_opportunity(r, api_key, fetch_full_description=True) for r in raw_by_notice.values()]
