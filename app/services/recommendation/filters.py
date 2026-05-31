import random
from datetime import timedelta
from typing import Any

from bson import ObjectId

from app.db import db
from app.services.ids import resolve_item_id
from app.services.timeouts import with_timeout
from app.utils import ensure_object_id, utcnow

from .common import public_item, seen_item_ids, top_popular_items
from .contextual import context_similarity_boost
from .signals import implicit_weight, positive_engagement_filter


async def filtering_layer(user_id: ObjectId, recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not recs:
        return []
    recent_seen = {str(item_id) for item_id in await seen_item_ids(user_id, since_days=7)}
    hidden = {str(item_id) for item_id in await negative_item_ids(user_id, {"hide", "dislike"})}
    item_ids = [ensure_object_id(rec["item"]["id"]) for rec in recs]
    try:
        available_docs = await with_timeout(
            db.items.find({"_id": {"$in": item_ids}, "available": True}, {"_id": 1}).to_list(
                length=len(item_ids)
            ),
            timeout_ms=2000,
        )
    except Exception:
        return recs
    available_ids = {str(doc["_id"]) for doc in available_docs}
    return [
        rec
        for rec in recs
        if rec["item"]["id"] in available_ids
        and rec["item"]["id"] not in recent_seen
        and rec["item"]["id"] not in hidden
    ]


async def fill_with_popular(recs: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(recs) >= limit:
        return recs
    existing_ids = {rec["item"]["id"] for rec in recs}
    popular = await top_popular_items(limit * 2)
    for rec in popular:
        if rec["item"]["id"] in existing_ids:
            continue
        recs.append(rec)
        existing_ids.add(rec["item"]["id"])
        if len(recs) >= limit:
            break
    return recs


async def negative_item_ids(user_id: ObjectId, negative_types: set[str]) -> list[ObjectId]:
    try:
        docs = await with_timeout(
            db.interactions.find(
                {"userId": user_id, "type": {"$in": list(negative_types)}},
                {"itemId": 1},
            ).to_list(length=5000),
            timeout_ms=2000,
        )
    except Exception:
        return []
    return [doc["itemId"] for doc in docs]


async def apply_context_boost(
    recs: list[dict[str, Any]], context: str | int | ObjectId | None
) -> list[dict[str, Any]]:
    if not context:
        return recs
    try:
        context_oid = await resolve_item_id(context)
    except ValueError:
        return recs
    try:
        context_item = await with_timeout(
            db.items.find_one({"_id": context_oid}, {"tags": 1, "genres": 1, "title": 1}),
            timeout_ms=2000,
        )
    except Exception:
        return recs
    if not context_item:
        return recs
    for rec in recs:
        rec["score"] *= context_similarity_boost(context_item, rec["item"])
    return sorted(recs, key=lambda item: item["score"], reverse=True)


async def exploration_replace(
    user_id: ObjectId,
    recs: list[dict[str, Any]],
    limit: int,
    rec_type: str = "session",
) -> list[dict[str, Any]]:
    # Epsilon-greedy: 10% of requests swap one slot with a less-popular unseen item.
    if not recs or random.random() >= 0.10:
        return recs

    seen = set(await seen_item_ids(user_id))
    current_ids = {ensure_object_id(rec["item"]["id"]) for rec in recs}
    try:
        cutoff = await with_timeout(
            db.items.find_one({"available": True}, sort=[("popularity", -1)], skip=20)
        )
    except Exception:
        return recs
    query: dict[str, Any] = {
        "available": True,
        "_id": {"$nin": list(seen.union(current_ids))},
    }
    if cutoff:
        query["popularity"] = {"$lt": cutoff.get("popularity", 0)}

    try:
        count = await with_timeout(db.items.count_documents(query))
    except Exception:
        return recs
    if count == 0:
        return recs

    try:
        random_item = await with_timeout(db.items.find_one(query, skip=random.randrange(count)))
    except Exception:
        return recs
    if not random_item:
        return recs

    replacement = {
        "item": public_item(random_item),
        "score": float(random_item.get("popularity", 0)) * 0.01,
        "sources": ["exploration"],
    }
    index = random.randrange(min(len(recs), limit))
    old_item_id = recs[index]["item"]["id"]
    recs[index] = replacement
    try:
        await with_timeout(
            db.explorations.insert_one(
                {
                    "userId": user_id,
                    "itemId": random_item["_id"],
                    "replacedItemId": ensure_object_id(old_item_id),
                    "type": rec_type,
                    "timestamp": utcnow(),
                }
            )
        )
    except Exception:
        pass
    return recs


async def session_intent_tags(user_id: ObjectId) -> set[str]:
    since = utcnow() - timedelta(minutes=15)
    try:
        recent = await with_timeout(
            db.interactions.find(
                {
                    "userId": user_id,
                    "timestamp": {"$gte": since},
                    **positive_engagement_filter(),
                },
                {"itemId": 1, "type": 1, "score": 1, "weightedScore": 1},
            ).to_list(length=20),
            timeout_ms=2000,
        )
        if len(recent) < 1:
            return set()
        items = await with_timeout(
            db.items.find(
                {"_id": {"$in": [doc["itemId"] for doc in recent]}},
                {"tags": 1, "genres": 1},
            ).to_list(length=20),
            timeout_ms=2000,
        )
    except Exception:
        return set()

    item_weights: dict[ObjectId, float] = {}
    for interaction in recent:
        weight = interaction.get("weightedScore")
        if weight is None:
            weight = implicit_weight(interaction.get("type", ""), interaction.get("score"))
        item_weights[interaction["itemId"]] = max(item_weights.get(interaction["itemId"], 0.0), float(weight))

    tag_counts: dict[str, float] = {}
    for item in items:
        weight = item_weights.get(item["_id"], 1.0)
        for tag in (item.get("tags") or []) + (item.get("genres") or []):
            tag_counts[tag] = tag_counts.get(tag, 0.0) + weight
    return {tag for tag, score in tag_counts.items() if score >= 6}
