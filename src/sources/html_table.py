"""Shared heuristics for scraping plain server-rendered HTML bid-listing
tables (used by tx_esbd, san_antonio, and Phase 2's Oklahoma/Louisiana/
Missouri sources — all older non-SPA apps with a similar shape: one big
table, a header row, no JS rendering required)."""

from datetime import datetime

from bs4 import BeautifulSoup

HEADER_ALIASES = {
    "bid": ["bid no", "bid #", "solicitation", "reference", "id"],
    "title": ["title", "description", "project"],
    "agency": ["agency", "department", "division"],
    "close_date": ["close date", "closing date", "due date", "deadline"],
    "posted_date": ["post date", "posted date", "issue date"],
}


def match_header(header_cells: list, aliases: dict = HEADER_ALIASES) -> dict:
    """Map column index -> logical field name based on fuzzy header text."""
    mapping = {}
    for idx, cell in enumerate(header_cells):
        text = cell.lower().strip()
        for field, terms in aliases.items():
            if any(term in text for term in terms):
                mapping[idx] = field
                break
    return mapping


def best_table(soup: BeautifulSoup, aliases: dict = HEADER_ALIASES):
    """Pick the table most likely to be the bid listing: most rows among
    tables that also have a recognizable header row."""
    candidates = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        header_cells = [c.get_text() for c in rows[0].find_all(["th", "td"])]
        mapping = match_header(header_cells, aliases)
        if mapping:
            candidates.append((len(rows), table, mapping))
    if not candidates:
        return None, None
    candidates.sort(key=lambda c: c[0], reverse=True)
    return candidates[0][1], candidates[0][2]


def parse_date(text: str):
    text = (text or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
