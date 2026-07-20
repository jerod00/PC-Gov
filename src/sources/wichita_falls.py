"""City of Wichita Falls — CivicEngage "Bid Postings" board.

Confirmed live (2026-07): plain server-rendered ASP.NET page (CivicEngage/
CivicPlus platform), no JS rendering needed. `robots.txt` has no blanket
disallow and no named block for AI crawlers -- checked specifically after
finding that the *same* CivicEngage platform on Abilene, TX explicitly
disallows ClaudeBot (a deliberate policy, treated as a hard stop there
regardless of technical feasibility). Wichita Falls does not have that
block, so this one is fair game.

Fetch/parse logic lives in civicengage_bids.py, shared across CivicEngage
organizations (confirmed structurally identical to Galveston's own Bids.aspx
markup); this module just supplies Wichita Falls' identity.

The default page (`Bids.aspx`, no query string) already filters
server-side to currently open bids via a "Show Me: Open Bids" dropdown --
confirmed empty at build time (zero open bids that day), so the actual
row markup was verified instead against `?showAllBids=on` (which also
shows closed/awarded/cancelled bids, structurally identical rows just
with a different Status value). Same lesson as Oklahoma/TX ESBD either
way: don't fully trust the server's own filtering -- each row's Status
span is checked client-side too, and only "Open" rows are kept.

No pagination found -- the board appears to list everything matching the
current filter on one page.
"""

from src.sources import civicengage_bids


def fetch(cfg: dict) -> list:
    return civicengage_bids.fetch(
        cfg, source_id="wichita_falls", agency="City of Wichita Falls", city="Wichita Falls", state="TX",
    )
