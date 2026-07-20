"""City of Waco — Bonfire portal (waco-texas.bonfirehub.com) public
"Opportunity RSS Feed". Fetch/parse logic lives in bonfire_rss.py, shared
across Bonfire organizations; this module just supplies Waco's identity.

Previously flagged as an unchecked loose end (README's Waco row noted its
Bonfire subdomain was never individually verified). Independently
re-checked live 2026-07-20: robots.txt has an empty Disallow, and the RSS
feed was confirmed live with real current solicitations (mostly mowing/
ROW/AE-services work outside Palcon's scope, plus a water-treatment-plant
vertical turbine PUMP installation -- a pump, not a gas turbine, so it
correctly scores 0 against the current capability profiles rather than
being a false-positive match).
"""

from src.sources import bonfire_rss


def fetch(cfg: dict) -> list:
    return bonfire_rss.fetch(cfg, source_id="waco_bonfire", agency="City of Waco", city="Waco", state="TX")
