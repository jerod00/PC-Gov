"""City of Galveston — CivicEngage "Bids and RFP's" board
(`www.galvestontx.gov/Bids.aspx`).

Independently confirmed live 2026-07-20: robots.txt has no blanket
disallow, and the rendered page's real HTML (view-source, not just the
text listing) shows markup byte-for-byte structurally identical to the
already-working Wichita Falls CivicEngage scraper (`listItemsRow`/
`bidTitle`/`bidStatus` divs, same span ordering) -- reused directly rather
than guessed. Fetch/parse logic lives in civicengage_bids.py, shared
across CivicEngage organizations; this module just supplies Galveston's
identity and its `showAllBids=on` listing URL (630 total bids at check
time, open + closed together; only "Open" rows are kept client-side).

Odessa and Midland run the same CivicEngage platform and share an
identical robots.txt, but their own `Bids.aspx` markup was never
independently fetched and inspected -- per this project's standing rule
(never build a scraper against unconfirmed structure, even on a platform
already proven elsewhere), those two stay unbuilt until someone actually
pulls their real page source.
"""

from src.sources import civicengage_bids


def fetch(cfg: dict) -> list:
    return civicengage_bids.fetch(
        cfg, source_id="galveston", agency="City of Galveston", city="Galveston", state="TX",
    )
