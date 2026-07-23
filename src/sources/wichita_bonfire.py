"""City of Wichita, KS — Bonfire portal (wichita.bonfirehub.com) public
"Opportunity RSS Feed". Fetch/parse logic lives in bonfire_rss.py, shared
across Bonfire organizations; this module just supplies Wichita's identity.

Confirmed live 2026-07-23: `wichita.bonfirehub.com/robots.txt` reads
`User-agent: * / Disallow:` (empty — nothing disallowed), the same open
policy already found for Dallas, Fort Worth, Harris County, San Angelo,
Waco, Amarillo, and the Port of Galveston. The RSS feed itself
(`/opportunities/rss`) was independently fetched and matches the shared
item shape byte-for-byte (same "Reference #: ... Name: ..." title format,
same "Project closes <Mon DD, YYYY> <H:MM AM/PM> <TZ>." description
format, same RFC822 pubDate, same /opportunities/<id> link pattern) — a
third independent confirmation of this feed format, not assumed from the
first two orgs.
"""

from src.sources import bonfire_rss


def fetch(cfg: dict) -> list:
    return bonfire_rss.fetch(cfg, source_id="wichita_bonfire", agency="City of Wichita", city="Wichita", state="KS")
