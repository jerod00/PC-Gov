"""City of Midland — CivicEngage "Bid Postings" board
(`www.midlandtexas.gov/Bids.aspx`).

This is a SEPARATE host and platform from Midland's Bonfire portal
(`midlandtexas.bonfirehub.com`), which is still confirmed blocked
(`Disallow: /`) -- the two must not be conflated. The city migrated actual
solicitation management to Bonfire, but this CivicEngage board still
lists a lightweight index of each open bid (title, bid number, status,
closing date) with a generic description pointing vendors to email
purchasing or log into Bonfire for full details -- unlike Wichita Falls/
Galveston/Odessa, where the description text itself is the real
solicitation notice. That means keyword/NAICS scoring here has much less
to work with; these listings function more as a "something's open, go
check" signal than rich matchable text.

Independently confirmed live 2026-07-22: robots.txt shares the same
permissive template as Odessa/Galveston, and the rendered page matches
the confirmed structure ("Bid No." pattern, "Status:"/"Closes:" labels) --
same caveat as odessa.py, byte-level view-source wasn't independently
pulled, confidence rests on structural consistency plus the platform
being proven twice elsewhere. Bids are grouped by department and the same
bid can be cross-listed under more than one department heading (seen live:
one bid appeared under both "Engineering Department" and "Utilities
Department") -- civicengage_bids.py dedupes by bid number to handle this.
Fetch/parse logic lives in civicengage_bids.py, shared across CivicEngage
organizations; this module just supplies Midland's identity.
"""

from src.sources import civicengage_bids


def fetch(cfg: dict) -> list:
    return civicengage_bids.fetch(
        cfg, source_id="midland", agency="City of Midland", city="Midland", state="TX",
    )
