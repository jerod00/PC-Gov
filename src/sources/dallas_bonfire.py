"""City of Dallas — Bonfire portal (dallascityhall.bonfirehub.com) public
"Opportunity RSS Feed". Fetch/parse logic lives in bonfire_rss.py, shared
across Bonfire organizations; this module just supplies Dallas' identity.

IMPORTANT — this reverses an earlier finding in this project. Dallas'
Bonfire subdomain was previously confirmed (documented in config.yaml/
README) to have a blanket `robots.txt` block (`User-agent: * / Disallow:
/`), the same policy every other Bonfire/Euna-family portal in this
project has, and was deliberately left un-scraped as a result. Re-checked
live 2026-07-20: `dallascityhall.bonfirehub.com/robots.txt` now reads
`User-agent: * / Disallow:` (empty -- nothing disallowed). Whether this is
a deliberate policy change or the block was scoped differently than
assumed, the current live file is what governs, and it permits this.

Fort Worth (see fort_worth_bonfire.py) was independently re-checked the
same way and found open too, but that does NOT mean every Bonfire-family
subdomain in this project follows -- Harris County, San Angelo, and
Tarrant County/Ion Wave stay disabled until each is individually
re-checked against its own live robots.txt.
"""

from src.sources import bonfire_rss


def fetch(cfg: dict) -> list:
    return bonfire_rss.fetch(cfg, source_id="dallas_bonfire", agency="City of Dallas", city="Dallas", state="TX")
