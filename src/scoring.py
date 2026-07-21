"""Config-driven opportunity scoring.

Every weight/keyword/capability lives in config.yaml, not here — this
module only implements how the factors combine. Reading it should never be
necessary to retune the ranking; edit config.yaml instead.

Scoring combines several independent signals into one confidence score:
  - keyword_relevance: the flat high/medium/low/negative keyword lists
    (unchanged from the original design — a global "does this text mention
    anything we care about" pass).
  - naics_psc_match: whether the opportunity's code is in the flat
    sam_gov.naics_codes/psc_codes lists, now with graduated (not just
    exact) credit — see _code_credit.
  - capability_relevance (NEW): the best-fitting entry in
    cfg["capabilities"], each of which represents one thing Pal-Con
    actually manufactures/does, combining that capability's own keywords,
    NAICS/PSC/NIGP codes (again graduated, not a hard filter), and
    (optionally) semantic similarity between the opportunity's text and the
    capability's description — see _capability_fit.
  - contract_value / proximity / deadline_urgency / set_aside_eligible:
    unchanged from the original design.
  - llm_relevance: unchanged — the optional LLM second opinion.
  - learned adjustments (feedback.py): unchanged in kind, extended with a
    new 'capability' dimension alongside keyword/source/naics.

None of the original signals were removed or had their meaning changed;
capability profiles and semantic similarity are additive.
"""

import re
from datetime import date
from typing import Optional

from src.geo import distance_from_home
from src.llm_scoring import LLMJudgment
from src.semantic import cosine_similarity
from src.sources.base import Opportunity


def _find_matches(text: str, terms: list) -> list:
    text_lower = text.lower()
    hits = []
    for term in terms:
        pattern = r"\b" + re.escape(term.lower()) + r"\b"
        if re.search(pattern, text_lower):
            hits.append(term)
    return hits


def _keyword_score(opp: Opportunity, keywords_cfg: dict, learned_keyword_weights: dict):
    """Returns (total_score, positive_matched). Negative-weighted categories
    (e.g. `negative`) still fully apply their penalty to total_score, but
    their terms are deliberately excluded from positive_matched -- a term
    that only matched because it's a *penalty* signal is not evidence of
    relevance, and must never satisfy the relevance gate in
    score_opportunity() or show up as a "Matches: ..." reason in the
    digest. (Found live: "DR15 6A Edgewood Park Detention Basin" scored 25
    and displayed "Matches: landscaping" -- landscaping is a negative term,
    penalizing the score, not the reason it passed the gate.)"""
    text = f"{opp.title}\n{opp.description}"
    total = 0.0
    positive_matched = []
    for _category, spec in keywords_cfg.items():
        base_weight = spec.get("weight", 0)
        is_negative = base_weight < 0
        for term in _find_matches(text, spec.get("terms", [])):
            adjustment = learned_keyword_weights.get(term, 0.0)
            total += base_weight * (1 + adjustment)
            if not is_negative:
                positive_matched.append(term)
    return total, positive_matched


def _code_credit(code: Optional[str], configured_codes: list, prefix_len: int) -> float:
    """1.0 for an exact match, 0.5 for a family/group-level match (same
    first `prefix_len` characters — e.g. NAICS's first 4 digits share an
    industry group, PSC/FSC's first 2 digits share a supply group), 0.0
    otherwise. This is what turns NAICS/PSC from a hard yes/no filter into
    a graduated signal: a code that's *close* to one we target is still
    worth something, not treated identically to a code with nothing to do
    with our capabilities."""
    if not code or not configured_codes:
        return 0.0
    if code in configured_codes:
        return 1.0
    prefix = code[:prefix_len]
    if len(prefix) < prefix_len:
        return 0.0
    for cc in configured_codes:
        if len(cc) >= prefix_len and cc[:prefix_len] == prefix:
            return 0.5
    return 0.0


def _nigp_credit(opp_nigp_codes: list, configured_nigp: list) -> float:
    """NIGP is frequently just free-text category names (see
    src/sources/houston.py), not a clean numeric code, so this is
    substring-based rather than prefix-based: 1.0 if any configured NIGP
    entry and any of the opportunity's NIGP entries contain one another
    (case-insensitive), else 0.0."""
    if not opp_nigp_codes or not configured_nigp:
        return 0.0
    for opp_entry in opp_nigp_codes:
        opp_l = opp_entry.lower()
        for cfg_entry in configured_nigp:
            cfg_l = cfg_entry.lower()
            if cfg_l in opp_l or opp_l in cfg_l:
                return 1.0
    return 0.0


def _capability_fit(opp: Opportunity, capability: dict, learned_capability_weights: dict,
                     opp_embedding: Optional[list], capability_embeddings: dict,
                     capability_scoring_cfg: dict, semantic_cfg: dict):
    """Returns (score, matched_keywords, similarity_or_None) for a single
    capability profile. Combines that capability's own keyword list,
    graduated NAICS/PSC/NIGP credit, and (when embeddings are available)
    semantic similarity between the opportunity's text and the
    capability's description."""
    text = f"{opp.title}\n{opp.description}"
    matched = _find_matches(text, capability.get("keywords", []))
    points_per_term = capability_scoring_cfg.get("keyword_points_per_term", 10)
    max_keyword_points = capability_scoring_cfg.get("max_keyword_points", 30)
    keyword_pts = min(len(matched) * points_per_term, max_keyword_points)

    code_pts = capability_scoring_cfg.get("code_match_points", 15)
    naics_prefix_len = capability_scoring_cfg.get("naics_prefix_length", 4)
    psc_prefix_len = capability_scoring_cfg.get("psc_prefix_length", 2)

    naics_credit = _code_credit(opp.naics_code, capability.get("naics_codes", []), naics_prefix_len)
    psc_credit = _code_credit(opp.psc_code, capability.get("psc_codes", []), psc_prefix_len)
    nigp_credit = _nigp_credit(opp.nigp_codes, capability.get("nigp_codes", []))
    code_credit_pts = max(naics_credit, psc_credit, nigp_credit) * code_pts

    similarity = None
    semantic_pts = 0.0
    cap_vector = capability_embeddings.get(capability["name"]) if capability_embeddings else None
    if opp_embedding is not None and cap_vector is not None:
        similarity = cosine_similarity(opp_embedding, cap_vector)
        floor = semantic_cfg.get("min_similarity", 0.3)
        max_points = semantic_cfg.get("max_points", 25)
        if similarity > floor:
            semantic_pts = ((similarity - floor) / (1 - floor)) * max_points

    adjustment = learned_capability_weights.get(capability["name"], 0.0)
    raw = keyword_pts + code_credit_pts + semantic_pts
    return raw * (1 + adjustment), matched, similarity


def _best_capability_match(opp: Opportunity, cfg: dict, learned_capability_weights: dict,
                            opp_embedding: Optional[list], capability_embeddings: dict):
    """Evaluates every configured capability and returns the single
    best-fitting one (score, name, matched_keywords, similarity) — or all
    zero/None if there are no capabilities configured or none fit at all.
    Taking the max (not the sum) across capabilities is deliberate: an
    opportunity that's a mediocre fit for five different capabilities isn't
    more relevant than one that's a strong fit for just one of them."""
    capabilities = cfg.get("capabilities") or []
    capability_scoring_cfg = cfg["scoring"].get("capability_scoring", {})
    semantic_cfg = cfg.get("semantic_scoring", {})

    best_score, best_name, best_matched, best_similarity = 0.0, None, [], None
    for capability in capabilities:
        score, matched, similarity = _capability_fit(
            opp, capability, learned_capability_weights, opp_embedding,
            capability_embeddings, capability_scoring_cfg, semantic_cfg,
        )
        if score > best_score:
            best_score, best_name, best_matched, best_similarity = score, capability["name"], matched, similarity
    return best_score, best_name, best_matched, best_similarity


def _value_score(value: Optional[float], curve_cfg: dict) -> float:
    if not value or value <= 0:
        return 0.0
    import math
    lo, hi = curve_cfg["min_value"], curve_cfg["max_value"]
    value = max(lo, min(hi, value))
    frac = (math.log10(value) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
    return frac * curve_cfg["max_points"]


def meets_minimum_value(opp: Opportunity, cfg: dict) -> bool:
    """Hard floor on contract size, applied before scoring ever runs.

    Only SAM.gov currently reports a structured dollar value -- every other
    source (Texas/Bonfire/CivicEngage/etc.) leaves `value` unset because
    their listing pages don't expose one. This only drops an opportunity
    when its value is actually KNOWN to be below the floor; unknown-value
    listings pass through unaffected, since there's no size data to judge
    them by and dropping them would silently gut most of the state/local
    coverage this project has.
    """
    minimum = cfg["scoring"].get("minimum_contract_value")
    if not minimum or opp.value is None:
        return True
    return opp.value >= minimum


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


def score_opportunity(opp: Opportunity, cfg: dict, learned: dict, today: Optional[date] = None,
                       llm_judgment: Optional[LLMJudgment] = None, opp_embedding: Optional[list] = None,
                       capability_embeddings: Optional[dict] = None):
    """Returns (score: float, matched_keywords: list[str], matched_capability: Optional[str]).

    `learned` is db.get_learned_weights()'s output: {'keyword': {...},
    'source': {...}, 'naics': {...}, 'capability': {...}}, each mapping a
    key to a bounded [-0.5, +0.5] adjustment nudged by accumulated
    feedback. Keyword/capability adjustments scale those individual
    signals; source/NAICS adjustments scale the opportunity's final score,
    so a source or code with a track record of bad feedback gets
    automatically deprioritized over time, not just the specific words in
    its listings.

    `llm_judgment`, when provided (see src/llm_scoring.py, opt-in via
    config.yaml llm_scoring), can independently satisfy the relevance gate
    below and adds a confidence-scaled bonus — this is what lets a genuine
    fit that happens to use none of the configured keywords still surface.

    `opp_embedding`/`capability_embeddings`, when provided (see
    src/semantic.py, opt-in via config.yaml semantic_scoring), let the
    best-fitting capability's score include a semantic-similarity
    component — this is what lets a genuine fit that's phrased completely
    differently than any configured keyword, code, or capability
    description still surface."""
    today = today or date.today()
    weights = cfg["scoring"]["weights"]
    capability_embeddings = capability_embeddings or {}

    kw_score, matched = _keyword_score(opp, cfg["keywords"], learned.get("keyword", {}))

    naics_credit = _code_credit(opp.naics_code, cfg["sam_gov"]["naics_codes"],
                                 cfg["scoring"].get("capability_scoring", {}).get("naics_prefix_length", 4))
    psc_credit = _code_credit(opp.psc_code, cfg["sam_gov"]["psc_codes"],
                               cfg["scoring"].get("capability_scoring", {}).get("psc_prefix_length", 2))
    naics_psc_credit = max(naics_credit, psc_credit)
    naics_psc_bonus = naics_psc_credit * weights["naics_psc_match"]
    naics_psc_matched = naics_psc_credit > 0

    capability_score, capability_name, capability_matched_kw, _similarity = _best_capability_match(
        opp, cfg, learned.get("capability", {}), opp_embedding, capability_embeddings,
    )
    capability_relevant = capability_score > 0

    llm_relevant = llm_judgment is not None and llm_judgment.relevant

    # Relevance gate: proximity/deadline/value/set-aside describe HOW GOOD an
    # opportunity is, not WHETHER it's relevant at all. Without at least one
    # matched keyword, a configured NAICS/PSC match, a capability-profile
    # match, or a positive LLM judgment, there's zero evidence this listing
    # has anything to do with our capabilities — don't let a close,
    # no-deadline, unrestricted listing coast to a passing score on bonuses
    # alone (this is exactly what let a flood of irrelevant City of San
    # Antonio listings clear the digest threshold in initial testing).
    if not matched and not naics_psc_matched and not capability_relevant and not llm_relevant:
        return 0.0, matched, None

    value_pts = _value_score(opp.value, cfg["scoring"]["contract_value_curve"])

    qualifying = cfg["scoring"]["qualifying_set_asides"]
    set_aside_bonus = weights["set_aside_eligible"] if (opp.set_aside in qualifying or not opp.set_aside) else 0.0

    proximity_pts = _proximity_score(opp, cfg)
    deadline_pts = _deadline_score(opp.response_deadline, cfg["scoring"]["deadline_curve"], today)

    llm_bonus = 0.0
    if llm_relevant:
        llm_bonus = weights.get("llm_relevance", 0) * (llm_judgment.confidence / 100)

    # capability_matched_kw also count toward the digest's matched-keyword
    # list (deduped) so fit_reason() can cite them even when they came from
    # a capability's own keyword list rather than the global one.
    matched = list(dict.fromkeys(matched + capability_matched_kw))

    total = (
        kw_score * weights["keyword_relevance"]
        + naics_psc_bonus
        + capability_score * weights.get("capability_relevance", 1.0)
        + value_pts * weights["contract_value"]
        + set_aside_bonus
        + proximity_pts * weights["proximity"]
        + deadline_pts * weights["deadline_urgency"]
        + llm_bonus
    )

    source_adj = learned.get("source", {}).get(opp.source_id, 0.0)
    naics_adj = learned.get("naics", {}).get(opp.naics_code, 0.0) if opp.naics_code else 0.0
    total *= (1 + source_adj) * (1 + naics_adj)

    return round(max(0.0, total), 1), matched, capability_name


def fit_reason(opp: Opportunity, matched_keywords: list, cfg: dict,
               llm_judgment: Optional[LLMJudgment] = None, matched_capability: Optional[str] = None) -> str:
    """Short human-readable reason this opportunity was surfaced, for the
    digest email. Prefers the LLM's plain-English reasoning when available
    (more useful than a bare keyword list); only cites NAICS/PSC when it
    actually matched a configured code — otherwise showing the code implies
    it contributed to the score when it didn't."""
    bits = []
    if llm_judgment is not None and llm_judgment.relevant and llm_judgment.reasoning:
        bits.append(llm_judgment.reasoning.strip())
    elif matched_keywords:
        top = matched_keywords[:3]
        bits.append(f"Matches: {', '.join(top)}")
    if matched_capability:
        bits.append(f"Capability: {matched_capability}")
    if opp.naics_code and opp.naics_code in cfg["sam_gov"]["naics_codes"]:
        bits.append(f"NAICS {opp.naics_code}")
    elif opp.psc_code and opp.psc_code in cfg["sam_gov"]["psc_codes"]:
        bits.append(f"PSC {opp.psc_code}")
    if opp.set_aside and opp.set_aside.lower() not in ("none", ""):
        bits.append(f"Set-aside: {opp.set_aside}")
    if not bits:
        bits.append("Matched search criteria")
    return " · ".join(bits)
