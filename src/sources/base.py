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
    value: Optional[float] = None
    set_aside: Optional[str] = None
    posted_date: Optional[date] = None
    response_deadline: Optional[date] = None

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
