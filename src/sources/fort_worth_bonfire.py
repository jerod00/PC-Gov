"""City of Fort Worth — Bonfire portal (fortworthtexas.bonfirehub.com)
public "Opportunity RSS Feed". Fetch/parse logic lives in bonfire_rss.py,
shared across Bonfire organizations; this module just supplies Fort
Worth's identity.

Like City of Dallas (see dallas_bonfire.py), Fort Worth's Bonfire
subdomain was originally confirmed blocked (`robots.txt` disallowing all
crawling) and left un-scraped. Independently re-checked live 2026-07-20:
`fortworthtexas.bonfirehub.com/robots.txt` now reads `User-agent: * /
Disallow:` (empty -- nothing disallowed), and the RSS feed was confirmed
live with real current solicitations, including at least one directly
relevant item ("RFP Aluminum, Iron, Rebar, and Steel"). Fort Worth's own
main domain (`fortworthtexas.gov`, separate from Bonfire) is unaffected by
this and still returns "Access Denied" from Akamai's bot-mitigation layer
-- not used here regardless, since the Bonfire subdomain is the real bid
data source.
"""

from src.sources import bonfire_rss


def fetch(cfg: dict) -> list:
    return bonfire_rss.fetch(cfg, source_id="fort_worth_bonfire", agency="City of Fort Worth", city="Fort Worth", state="TX")
