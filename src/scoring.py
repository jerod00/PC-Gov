"""Config-driven opportunity scoring.

Every weight/keyword lives in config.yaml, not here — this module only
implements how the factors combine. Reading it should never be necessary to
retune the ranking; edit config.yaml instead.
"""

import re
from datetime import date
from typing import Optional

from src.geo import distance_from_home
from src.sources.base import Opportunity


def _find_matches(text: str, terms: list) -> list:
    text_lower = text.lower()
    hits = []
    for term in terms:
        pattern = r"\b" + re.escape(term.lower()) + r"\b"
        if re.search(pattern, text_lower):
            hits.append(term)
    return hits


def _keyword_score(opp: Opportunity, keywords_cfg: dict, learned_weights: dict):
    text = f"{opp.title}\n{opp.description}"
    total = 0.0
    matched = []
    for _category, spec in keywords_cfg.items():
        base_weight = spec.get("weight", 0)
        for term in _find_matches(text, spec.get("terms", [])):
            adjustment = learned_weights.get(term, 0.0)
            total += base_weight * (1 + adjustment)
            matched.append(term)
    return total, matched


def _value_score(value: Optional[float], curve_cfg: dict) -> float:
    if not value or value <= 0:
        return 0.0
    import math
    lo, hi = curve_cfg["min_value"], curve_cfg["max_value"]
    value = max(lo, min(hi, value))
    frac = (math.log10(value) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
    return frac * curve_cfg["max_points"]


def _proximity_score(opp: Opportunity, cfg: dict) -> float:
    curve = cfg["scoring"]["proximity_curve"]
    if opp.source_id == "sam_gov":
        return curve["max_points"]  # federal is nationwide by design
    home = cfg["company"]["home_location"]
    dist = distance_from_home(opp.lat, opp.lon, opp.city, opp.state, home["lat"], home["lon"])
    if dist is None:
        return 0.0
    if dist <= curve["full_points_within_miles"]:
        return curve["max_points"]
    if dist >= curve["radius_miles"]:
        return 0.0
    span = curve["radius_miles"] - curve["full_points_within_miles"]
    frac = 1 - (dist - curve["full_points_within_miles"]) / span
    return max(0.0, frac) * curve["max_points"]


def _deadline_score(deadline: Optional[date], curve_cfg: dict, today: date) -> float:
    if deadline is None:
        return 0.0
    days = (deadline - today).days
    if days < 0:
        return 0.0
    max_pts = curve_cfg["max_points"]
    sweet_spot = curve_cfg["sweet_spot_days"]
    too_soon = curve_cfg["too_soon_days"]
    if days <= too_soon:
        return max_pts * curve_cfg["too_soon_penalty"]
    if days <= sweet_spot:
        soon_floor = max_pts * curve_cfg["too_soon_penalty"]
        frac = (days - too_soon) / max(1, (sweet_spot - too_soon))
        return soon_floor + frac * (max_pts - soon_floor)
    # taper off the further past the sweet spot the deadline is
    far_horizon = sweet_spot * 6
    if days >= far_horizon:
        return 0.0
    frac = 1 - (days - sweet_spot) / (far_horizon - sweet_spot)
    return max(0.0, frac) * max_pts


def score_opportunity(opp: Opportunity, cfg: dict, learned_weights: dict, today: Optional[date] = None):
    """Returns (score: float, matched_keywords: list[str])."""
    today = today or date.today()
    weights = cfg["scoring"]["weights"]

    kw_score, matched = _keyword_score(opp, cfg["keywords"], learned_weights)

    naics_psc_bonus = 0.0
    naics_psc_matched = False
    if opp.naics_code and opp.naics_code in cfg["sam_gov"]["naics_codes"]:
        naics_psc_bonus = weights["naics_psc_match"]
        naics_psc_matched = True
    elif opp.psc_code and opp.psc_code in cfg["sam_gov"]["psc_codes"]:
        naics_psc_bonus = weights["naics_psc_match"]
        naics_psc_matched = True

    # Relevance gate: proximity/deadline/value/set-aside describe HOW GOOD an
    # opportunity is, not WHETHER it's relevant at all. Without at least one
    # matched keyword or a configured NAICS/PSC match, there's zero evidence
    # this listing has anything to do with our capabilities — don't let a
    # close, no-deadline, unrestricted listing coast to a passing score on
    # bonuses alone (this is exactly what let a flood of irrelevant City of
    # San Antonio listings clear the digest threshold in initial testing).
    if not matched and not naics_psc_matched:
        return 0.0, matched

    value_pts = _value_score(opp.value, cfg["scoring"]["contract_value_curve"])

    qualifying = cfg["scoring"]["qualifying_set_asides"]
    set_aside_bonus = weights["set_aside_eligible"] if (opp.set_aside in qualifying or not opp.set_aside) else 0.0

    proximity_pts = _proximity_score(opp, cfg)
    deadline_pts = _deadline_score(opp.response_deadline, cfg["scoring"]["deadline_curve"], today)

    total = (
        kw_score * weights["keyword_relevance"]
        + naics_psc_bonus
        + value_pts * weights["contract_value"]
        + set_aside_bonus
        + proximity_pts * weights["proximity"]
        + deadline_pts * weights["deadline_urgency"]
    )
    return round(max(0.0, total), 1), matched


def fit_reason(opp: Opportunity, matched_keywords: list, cfg: dict) -> str:
    """Short human-readable reason this opportunity was surfaced, for the
    digest email. Only cites NAICS/PSC when it actually matched a configured
    code — otherwise showing the code implies it contributed to the score
    when it didn't."""
    bits = []
    if matched_keywords:
        top = matched_keywords[:3]
        bits.append(f"Matches: {', '.join(top)}")
    if opp.naics_code and opp.naics_code in cfg["sam_gov"]["naics_codes"]:
        bits.append(f"NAICS {opp.naics_code}")
    elif opp.psc_code and opp.psc_code in cfg["sam_gov"]["psc_codes"]:
        bits.append(f"PSC {opp.psc_code}")
    if opp.set_aside and opp.set_aside.lower() not in ("none", ""):
        bits.append(f"Set-aside: {opp.set_aside}")
    if not bits:
        bits.append("Matched search criteria")
    return " · ".join(bits)
