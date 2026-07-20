"""Harris County (Houston's county) — Bonfire portal
(harriscountytx.bonfirehub.com) public "Opportunity RSS Feed". Fetch/parse
logic lives in bonfire_rss.py, shared across Bonfire organizations; this
module just supplies Harris County's identity.

Previously confirmed blocked (blanket `robots.txt` disallow), and unlike
Dallas County, Harris County's own domain (purchasing.harriscountytx.gov)
has no standalone listing to fall back on -- a dead end at the time.
Independently re-checked live 2026-07-20 (third Bonfire org re-checked
this round, after Dallas and Fort Worth): robots.txt now has an empty
Disallow, and the RSS feed was confirmed live with a large batch of real
current solicitations spanning many county departments/precincts (HCTRA,
Harris Health, Flood Control District, various Precincts) -- titles don't
cleanly separate into a single department field, so `agency` here is just
"Harris County"; the department context stays in the description text for
keyword matching.

No city -- this is a county, not a municipality, same convention as
dallas_county.py.
"""

from src.sources import bonfire_rss


def fetch(cfg: dict) -> list:
    return bonfire_rss.fetch(cfg, source_id="harris_county", agency="Harris County", city=None, state="TX")
