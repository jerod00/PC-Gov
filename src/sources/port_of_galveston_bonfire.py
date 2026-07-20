"""Port of Galveston — Bonfire portal public "Opportunity RSS Feed".
Fetch/parse logic lives in bonfire_rss.py, shared across Bonfire
organizations; this module just supplies the Port of Galveston's identity.

Independently checked live 2026-07-20 (same round as Waco/Amarillo):
robots.txt has an empty Disallow, and the RSS feed was confirmed live with
real current solicitations, including "2026-008 RFB for Fuel Station".

A distinct entity from Galveston COUNTY's Bonfire subdomain, which is
STILL confirmed blocked (`Disallow: /`) — don't conflate the two.
"""

from src.sources import bonfire_rss


def fetch(cfg: dict) -> list:
    return bonfire_rss.fetch(
        cfg, source_id="port_of_galveston_bonfire", agency="Port of Galveston", city="Galveston", state="TX",
    )
