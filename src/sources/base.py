"""Common shape every source module returns, so scoring/db/email never need
to know which source an opportunity came from."""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Opportunity:
    # Stable unique identifier for dedup — the source's own notice/solicitation
    # number. Must be unique *within* a source; source_id is prefixed onto it
    # when stored so two sources can't collide on the same raw number.
    notice_id: str
    source_id: str          # e.g. "sam_gov", "tx_esbd", "txdot"
    title: str
    agency: str
    url: str

    description: str = ""
    naics_code: Optional[str] = None
    psc_code: Optional[str] = None
    # NIGP commodity codes/category names, when the source exposes them
    # (e.g. Houston Beacon Bid's `categories`). Not merged into naics_code/
    # psc_code -- NIGP is a different classification system and conflating
    # them would misrepresent a NIGP match as a NAICS/PSC match in scoring.
    # Some sources only expose free-text category names, not numeric codes --
    # this field holds whatever the source actually has, matched against
    # capability profiles as free text either way.
    nigp_codes: list = field(default_factory=list)
    value: Optional[float] = None
    set_aside: Optional[str] = None
    posted_date: Optional[date] = None
    response_deadline: Optional[date] = None

    # Point of contact, when the source exposes one (currently only SAM.gov's
    # pointOfContact field) -- who to reach out to about this notice, or about
    # future similar work from the same office. None for sources that don't
    # have this data rather than guessing.
    poc_name: Optional[str] = None
    poc_email: Optional[str] = None
    poc_phone: Optional[str] = None

    # Location, when the source provides it. city/state are used for the
    # human-readable digest; lat/lon (when known) drive the proximity score.
    # For federal (SAM.gov) and Texas state/local, distance is not checked —
    # see geo.py and config.yaml state_local_states.
    city: Optional[str] = None
    state: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None

    raw: dict = field(default_factory=dict)  # original payload, for debugging

    @property
    def dedup_key(self) -> str:
        return f"{self.source_id}:{self.notice_id}"


class SourceError(Exception):
    """Raised by a source module on unrecoverable fetch/parse failure.

    run_daily.py catches this per-source so one bad source never blocks the
    others or stops the digest from going out.
    """
