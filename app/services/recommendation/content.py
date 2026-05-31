from typing import Any

from bson import ObjectId

from app.config import get_settings
from app.db import db
from app.services.ids import resolve_user_id
from app.services.timeouts import with_timeout

from .affinity import apply_genre_affinity, user_genre_affinity
from .common import (
    get_user_profile_embedding,
    interaction_count,
    local_vector_search,
    public_item,
    recent_average_embedding,
    seen_item_ids,
    top_popular_items,
)
from .contextual import contextual_item_rec
from .filters import apply_context_boost
from .signals import blend_embeddings


settings = get_settings()


async def content_based_rec(
    user_id: str | int | ObjectId,
    limit: int = 20,
    context: str | int | ObjectId | None = None,
) -> list[dict[str, Any]]:
    user_oid = await resolve_user_id(user_id)

    # Cold start: with a movie context, recommend similar movies instead of generic popular.
    if await interaction_count(user_oid) < 3:
        if context:
            context_recs = await contextual_item_rec(context, user_oid, limit)
            if context_recs:
                return context_recs
        return await top_popular_items(limit)

    seen_ids = await seen_item_ids(user_oid)
    long_term_vector = await get_user_profile_embedding(user_oid)
    recent_vector = await recent_average_embedding(user_oid)
    query_vector = blend_embeddings(long_term_vector, recent_vector)
    if not query_vector:
        if context:
            context_recs = await contextual_item_rec(context, user_oid, limit)
            if context_recs:
                return context_recs
        return await top_popular_items(limit)

    pipeline: list[dict[str, Any]] = [
        {
            "$vectorSearch": {
                "index": settings.vector_index_name,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": max(limit * 20, 100),
                "limit": max(limit * 5, 50),
            }
        },
        {"$match": {"_id": {"$nin": seen_ids}, "available": True}},
        {"$addFields": {"recScore": {"$meta": "vectorSearchScore"}}},
        {"$limit": limit},
    ]
    try:
        docs = await with_timeout(db.items.aggregate(pipeline).to_list(length=limit))
    except Exception:
        try:
            docs = await with_timeout(local_vector_search(query_vector, seen_ids, limit), timeout_ms=8000)
        except Exception:
            return await top_popular_items(limit)

    recs = [
        {"item": public_item(doc), "score": float(doc.get("recScore", 0)), "source": "content"}
        for doc in docs
    ]
    if not recs:
        if context:
            context_recs = await contextual_item_rec(context, user_oid, limit)
            if context_recs:
                return context_recs
        return await top_popular_items(limit)

    affinity = await user_genre_affinity(user_oid)
    if affinity:
        recs = apply_genre_affinity(recs, affinity)

    if context:
        context_recs = await contextual_item_rec(context, user_oid, limit)
        existing = {rec["item"]["id"] for rec in recs}
        for rec in context_recs:
            if rec["item"]["id"] not in existing:
                recs.append(rec)
                existing.add(rec["item"]["id"])
        recs = sorted(recs, key=lambda rec: rec["score"], reverse=True)[:limit]

    return await apply_context_boost(recs, context)
