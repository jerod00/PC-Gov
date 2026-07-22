"""City of Odessa — CivicEngage "Bid Postings" board (`Bids.aspx`).

Independently confirmed live 2026-07-22: robots.txt shares the same
permissive template as Galveston/Midland (no blanket disallow), and the
rendered page matches the confirmed Wichita Falls/Galveston structure
exactly -- "Bid No." prefix pattern, "Status:"/"Closes:" labels, "[Read
on: ...]" bracket links -- across two separate full-page fetches. Unlike
Galveston, byte-level HTML (view-source) wasn't independently pulled for
this one; confidence here rests on that structural consistency plus the
platform already being proven twice elsewhere, not a literal markup
confirmation. Fetch/parse logic lives in civicengage_bids.py, shared
across CivicEngage organizations; this module just supplies Odessa's
identity.

Caveat: only the "Request for Proposal" category was confirmed (the page
header reads "Request for Proposal 147 Bids"); a `CatID=showStatus`/
`Status=open` querystring combo that combines all categories for Galveston
had no effect here (identical output either way), so Odessa's install
doesn't support that trick. If Odessa has a separate "Invitation to Bid"
category, those bids may not be covered by this URL -- worth checking
later, not treated as a blocker since "Request for Proposal" alone
already surfaces real, current, open items.
"""

from src.sources import civicengage_bids


def fetch(cfg: dict) -> list:
    return civicengage_bids.fetch(
        cfg, source_id="odessa", agency="City of Odessa", city="Odessa", state="TX",
    )
