"""City of Amarillo — Bonfire portal (amarillo.bonfirehub.com) public
"Opportunity RSS Feed". Fetch/parse logic lives in bonfire_rss.py, shared
across Bonfire organizations; this module just supplies Amarillo's identity.

Independently checked live 2026-07-20 (part of the same expansion round as
Waco/Port of Galveston): robots.txt has an empty Disallow, and the RSS feed
was confirmed live with real current solicitations.
"""

from src.sources import bonfire_rss


def fetch(cfg: dict) -> list:
    return bonfire_rss.fetch(cfg, source_id="amarillo_bonfire", agency="City of Amarillo", city="Amarillo", state="TX")
