from typing import Any

from bson import ObjectId

from app.db import db
from app.services.ids import resolve_user_id
from app.services.timeouts import with_timeout
from app.utils import ensure_aware_utc

from .common import interaction_count, public_item, seen_item_ids, top_popular_items
from .filters import apply_context_boost
from .signals import decay_score, implicit_weight, positive_engagement_filter


async def collaborative_rec(
    user_id: str | int | ObjectId,
    limit: int = 20,
    context: str | int | ObjectId | None = None,
) -> list[dict[str, Any]]:
    user_oid = await resolve_user_id(user_id)

    # Cold start: collaborative overlap is unreliable below three interactions.
    if await interaction_count(user_oid) < 3:
        print("fallback====================================================", "cold start")
        return await top_popular_items(limit)

    seen_ids = await seen_item_ids(user_oid)
    try:
        user_positive_docs = await with_timeout(
            db.interactions.find(
                {"userId": user_oid, **positive_engagement_filter()},
                {"itemId": 1},
            )
            .sort("timestamp", -1)
            .limit(500)
            .to_list(length=500),
            timeout_ms=15000,
        )
    except Exception as e:
        print("fallback====================================================", e)
        return await top_popular_items(limit)

    user_item_ids = list({doc["itemId"] for doc in user_positive_docs})
    if len(user_item_ids) < 3:
        print("fallback====================================================", "not enough positive interactions")
        return await top_popular_items(limit)

    similar_users_pipeline = [
        {
            "$match": {
                "itemId": {"$in": user_item_ids},
                "userId": {"$ne": user_oid},
                **positive_engagement_filter(),
            }
        },
        {
            "$group": {
                "_id": "$userId",
                "overlap": {"$sum": 1},
                "similarity": {
                    "$sum": {"$ifNull": ["$weightedScore", {"$ifNull": ["$score", 1]}]}
                },
            }
        },
        {"$addFields": {"similarity": {"$multiply": ["$similarity", "$overlap"]}}},
        {"$sort": {"similarity": -1, "overlap": -1}},
        {"$limit": 30},
    ]
    try:
        similar_users = await with_timeout(
            db.interactions.aggregate(similar_users_pipeline).to_list(length=30),
            timeout_ms=30000,
        )
    except Exception as e:
        print("fallback====================================================", e)
        return await top_popular_items(limit)
    if not similar_users:
        print("fallback====================================================", "no similar users")
        return await top_popular_items(limit)

    similarity_by_user = {doc["_id"]: float(doc.get("similarity", 1)) for doc in similar_users}
    similar_user_ids = list(similarity_by_user.keys())
    cursor = db.interactions.find(
        {
            "userId": {"$in": similar_user_ids},
            "itemId": {"$nin": seen_ids},
            **positive_engagement_filter(),
        }
    )

    scores: dict[ObjectId, dict[str, Any]] = {}
    try:
        collab_docs = await with_timeout(cursor.to_list(length=5000), timeout_ms=30000)
    except Exception as e:
        print("fallback====================================================1", e)
        return await top_popular_items(limit)
    for doc in collab_docs:
        base = doc.get("weightedScore")
        if base is None:
            base = implicit_weight(doc["type"], doc.get("score"))
        base = float(base)
        weighted = decay_score(base * similarity_by_user.get(doc["userId"], 1), doc.get("timestamp"))
        entry = scores.setdefault(doc["itemId"], {"score": 0.0, "lastInteraction": doc.get("timestamp")})
        entry["score"] += weighted
        doc_timestamp = ensure_aware_utc(doc.get("timestamp"))
        entry_timestamp = ensure_aware_utc(entry["lastInteraction"])
        if doc_timestamp and (not entry_timestamp or doc_timestamp > entry_timestamp):
            entry["lastInteraction"] = doc_timestamp

    if not scores:
        print("fallback====================================================", "not scores")
        return await top_popular_items(limit)

    top_ids = sorted(scores, key=lambda item_id: scores[item_id]["score"], reverse=True)[: limit * 3]
    try:
        items = await with_timeout(
            db.items.find({"_id": {"$in": top_ids}, "available": True}).to_list(length=len(top_ids)),
            timeout_ms=15000,
        )
    except Exception as e:
        print("fallback====================================================", e)
        return await top_popular_items(limit)
    by_id = {item["_id"]: item for item in items}
    recs = []
    for item_id in top_ids:
        item = by_id.get(item_id)
        if item:
            recs.append(
                {
                    "item": public_item(item),
                    "score": scores[item_id]["score"],
                    "source": "collaborative",
                    "lastInteraction": scores[item_id]["lastInteraction"],
                }
            )
        if len(recs) >= limit:
            break
    if not recs:
        print("fallback====================================================")
        return await top_popular_items(limit)
    return await apply_context_boost(recs, context)
