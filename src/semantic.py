"""Semantic similarity scoring via text embeddings -- a third, opt-in signal
alongside deterministic keyword/code matching (scoring.py) and the LLM
relevance judge (llm_scoring.py). Catches a genuine fit that's phrased
nothing like any configured keyword, code, or capability description, e.g.
"gas turbine exhaust plenum assembly" scoring high against a "Turbine ducts
& filter housings" capability purely on meaning, not shared words.

Anthropic does not serve text embeddings itself -- Voyage AI is the
standard provider for this (see https://github.com/voyage-ai/voyageai-python
and https://docs.voyageai.com/docs/embeddings), reached here through the
`voyageai` package. Requires VOYAGE_API_KEY in .env; every function degrades
gracefully (returns None) when the key is missing or a call fails, same
pattern as llm_scoring.py -- nothing else in the project depends on this
being available, and config.yaml's semantic_scoring.enabled defaults to
off.

Opportunity embeddings are cached in SQLite (src/db.py, keyed on dedup_key
+ a hash of the embedded text) since the same recurring listing would
otherwise be re-embedded -- and re-billed -- every single day it stays
open. Capability-description embeddings are deliberately NOT cached: there
are only a handful of them, and always re-embedding means an edit to
config.yaml's capability descriptions takes effect immediately instead of
needing a cache bust.
"""

import logging
import math
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

_client = None
_client_key = None


def _get_client(api_key: str):
    global _client, _client_key
    if _client is None or _client_key != api_key:
        import voyageai  # imported lazily -- only needed when semantic_scoring is enabled
        _client = voyageai.Client(api_key=api_key)
        _client_key = api_key
    return _client


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def embed_texts(texts: list, api_key: str, model: str, input_type: Optional[str] = None) -> Optional[list]:
    """Returns a list of embedding vectors (one per input text, same order),
    or None on any failure -- missing key, network error, bad response.
    `input_type` should be "query" or "document" per Voyage's asymmetric
    retrieval convention when comparing two different kinds of text (a short
    capability description "querying" against opportunity "documents");
    leave it None when embedding same-kind text."""
    if not api_key or not texts:
        return None
    try:
        client = _get_client(api_key)
        result = client.embed(texts, model=model, input_type=input_type)
        return result.embeddings
    except Exception as e:  # noqa: BLE001 -- never let embeddings break a run
        log.warning("Embedding request failed (%d texts, model=%s): %s", len(texts), model, e)
        return None


def cosine_similarity(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def embed_capabilities(capabilities_cfg: list, api_key: str, model: str) -> dict:
    """Returns {capability_name: embedding_vector}. Not cached -- see module
    docstring. Returns {} if embedding fails or semantic scoring isn't
    usable, so callers can treat semantic scoring as simply unavailable
    rather than special-casing failure."""
    if not capabilities_cfg:
        return {}
    names = [c["name"] for c in capabilities_cfg]
    texts = [c.get("description", c["name"]) for c in capabilities_cfg]
    embeddings = embed_texts(texts, api_key, model, input_type="query")
    if embeddings is None:
        return {}
    return dict(zip(names, embeddings))


def embed_opportunities_cached(opportunities: list, conn, api_key: str, model: str) -> dict:
    """Returns {dedup_key: embedding_vector} for every opportunity that has
    either a cached embedding already or was successfully embedded this
    call. Batches every cache miss into as few embed_texts calls as
    possible (Voyage's batch limit is 1000 inputs per call)."""
    from src import db  # local import -- avoids a hard circular-import edge at module load

    BATCH_SIZE = 1000
    result = {}
    misses = []  # list of (dedup_key, text)

    for opp in opportunities:
        text = f"{opp.title}\n{opp.description}"
        cached = db.get_cached_embedding(conn, opp.dedup_key, text)
        if cached is not None:
            result[opp.dedup_key] = cached
        else:
            misses.append((opp.dedup_key, text))

    for i in range(0, len(misses), BATCH_SIZE):
        batch = misses[i:i + BATCH_SIZE]
        embeddings = embed_texts([text for _, text in batch], api_key, model, input_type="document")
        if embeddings is None:
            continue  # this batch's opportunities simply won't have a semantic score this run
        now_iso = _now_iso()
        for (dedup_key, text), vector in zip(batch, embeddings):
            result[dedup_key] = vector
            db.set_cached_embedding(conn, dedup_key, text, vector, now_iso)

    return result
