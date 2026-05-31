"""
Hybrid movie search: Atlas full-text ($search) + vector ($vectorSearch)
combined with Reciprocal Rank Fusion (RRF).

Endpoint: GET /search/movies?q=...&limit=20&mode=hybrid|text|vector
"""
import asyncio
from typing import Any, Literal

from app.config import get_settings
from app.db import db
from app.services.embeddings import get_embedding
from app.services.timeouts import with_timeout
from app.utils import serialize_doc

settings = get_settings()

# Standard RRF constant — rank 1 contributes 1/(60+1) ≈ 0.016
_RRF_K = 60
_TEXT_INDEX = "items_text_search_index"


# ─── helpers ──────────────────────────────────────────────────────────────────

def _public_item(doc: dict[str, Any]) -> dict[str, Any]:
    item = serialize_doc(doc)
    item.pop("embedding", None)
    item.pop("textScore", None)
    item.pop("vectorScore", None)
    return item


# ─── individual searches ───────────────────────────────────────────────────────

async def _text_search(query: str, limit: int) -> list[dict[str, Any]]:
    """BM25 full-text search via Atlas Search ($search)."""
    pipeline: list[dict[str, Any]] = [
        {
            "$search": {
                "index": _TEXT_INDEX,
                "compound": {
                    "should": [
                        # title carries 3× boost
                        {
                            "text": {
                                "query": query,
                                "path": "title",
                                "score": {"boost": {"value": 3}},
                            }
                        },
                        {"text": {"query": query, "path": "description"}},
                        {"text": {"query": query, "path": "tags"}},
                        {"text": {"query": query, "path": "genres"}},
                    ]
                },
            }
        },
        {"$match": {"available": True}},
        {"$addFields": {"textScore": {"$meta": "searchScore"}}},
        {"$limit": limit},
        {"$project": {"embedding": 0}},
    ]
    try:
        return await with_timeout(db.items.aggregate(pipeline).to_list(length=limit))
    except Exception:
        return []


async def _vector_search(query_vector: list[float], limit: int) -> list[dict[str, Any]]:
    """ANN semantic search via Atlas Vector Search ($vectorSearch)."""
    pipeline: list[dict[str, Any]] = [
        {
            "$vectorSearch": {
                "index": settings.vector_index_name,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": max(limit * 10, 100),
                "limit": limit,
            }
        },
        {"$match": {"available": True}},
        {"$addFields": {"vectorScore": {"$meta": "vectorSearchScore"}}},
        {"$limit": limit},
        {"$project": {"embedding": 0}},
    ]
    try:
        return await with_timeout(db.items.aggregate(pipeline).to_list(length=limit))
    except Exception:
        return []


# ─── Reciprocal Rank Fusion ────────────────────────────────────────────────────

def _rrf_merge(
    text_docs: list[dict[str, Any]],
    vector_docs: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """
    Merge two ranked lists using RRF:
        score(d) = Σ  1 / (k + rank_i(d))
    Higher score = better combined rank.
    """
    scores: dict[str, dict[str, Any]] = {}

    for rank, doc in enumerate(text_docs, 1):
        key = str(doc["_id"])
        entry = scores.setdefault(
            key, {"doc": doc, "textRrf": 0.0, "vectorRrf": 0.0}
        )
        entry["textRrf"] = 1.0 / (_RRF_K + rank)

    for rank, doc in enumerate(vector_docs, 1):
        key = str(doc["_id"])
        entry = scores.setdefault(
            key, {"doc": doc, "textRrf": 0.0, "vectorRrf": 0.0}
        )
        entry["vectorRrf"] = 1.0 / (_RRF_K + rank)

    merged = []
    for entry in scores.values():
        doc = entry["doc"]
        rrf_score = entry["textRrf"] + entry["vectorRrf"]
        merged.append(
            {
                "item": _public_item(doc),
                "rrfScore": round(rrf_score, 6),
                "textScore": round(float(doc.get("textScore") or 0), 4),
                "vectorScore": round(float(doc.get("vectorScore") or 0), 4),
                "source": "hybrid",
            }
        )

    return sorted(merged, key=lambda r: r["rrfScore"], reverse=True)[:limit]


# ─── public API ───────────────────────────────────────────────────────────────

async def movie_search(
    query: str,
    limit: int = 20,
    mode: Literal["hybrid", "text", "vector"] = "hybrid",
) -> list[dict[str, Any]]:
    """
    Search movies by query string.

    Modes:
      text   — Atlas Search BM25 only
      vector — Atlas Vector Search only (semantic)
      hybrid — both, merged via RRF (default)
    """
    if mode == "text":
        docs = await _text_search(query, limit)
        return [
            {
                "item": _public_item(doc),
                "rrfScore": round(float(doc.get("textScore") or 0), 4),
                "textScore": round(float(doc.get("textScore") or 0), 4),
                "vectorScore": 0.0,
                "source": "text",
            }
            for doc in docs
        ]

    # embed query in thread pool (works for both mock and real Gemini)
    loop = asyncio.get_event_loop()
    query_vector: list[float] = await loop.run_in_executor(None, get_embedding, query)

    if mode == "vector":
        docs = await _vector_search(query_vector, limit)
        return [
            {
                "item": _public_item(doc),
                "rrfScore": round(float(doc.get("vectorScore") or 0), 4),
                "textScore": 0.0,
                "vectorScore": round(float(doc.get("vectorScore") or 0), 4),
                "source": "vector",
            }
            for doc in docs
        ]

    # hybrid: run both in parallel, then merge
    text_docs, vector_docs = await asyncio.gather(
        _text_search(query, limit * 2),
        _vector_search(query_vector, limit * 2),
    )
    return _rrf_merge(text_docs, vector_docs, limit)


async def movie_by_imdb_id(imdb_id: str) -> dict[str, Any] | None:
    bare_imdb_id = imdb_id.removeprefix("tt")
    doc = await db.items.find_one({"imdbId": bare_imdb_id, "available": True})
    if not doc:
        return None
    return _public_item(doc)
