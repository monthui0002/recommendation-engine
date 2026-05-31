import math
from datetime import timedelta
from typing import Any

from bson import ObjectId

from app.db import db
from app.services.embeddings import average_embeddings
from app.services.timeouts import with_timeout
from app.utils import serialize_doc, utcnow

from .signals import (
    EXPOSURE_ONLY_TYPES,
    decay_score,
    implicit_weight,
    positive_engagement_filter,
)


def public_item(doc: dict[str, Any]) -> dict[str, Any]:
    item = serialize_doc(doc)
    item.pop("embedding", None)
    item.pop("recScore", None)
    return item


async def seen_item_ids(
    user_id: ObjectId,
    since_days: int | None = None,
    include_impressions: bool = False,
) -> list[ObjectId]:
    query: dict[str, Any] = {"userId": user_id}
    if since_days is not None:
        query["timestamp"] = {"$gte": utcnow() - timedelta(days=since_days)}
    if not include_impressions:
        query["type"] = {"$nin": list(EXPOSURE_ONLY_TYPES)}
    cursor = db.interactions.find(query, {"itemId": 1})
    try:
        docs = await with_timeout(cursor.to_list(length=5000), timeout_ms=10000)
    except Exception:
        return []
    return [doc["itemId"] for doc in docs]


async def interaction_count(user_id: ObjectId) -> int:
    try:
        return await with_timeout(
            db.interactions.count_documents(
                {"userId": user_id, "type": {"$nin": list(EXPOSURE_ONLY_TYPES)}}
            ),
            timeout_ms=20000,
        )
    except Exception:
        return 0


async def top_popular_items(limit: int = 20) -> list[dict[str, Any]]:
    try:
        cursor = db.items.find({"available": True}).sort("popularity", -1).limit(limit)
        docs = await with_timeout(cursor.to_list(length=limit), timeout_ms=3000)
    except Exception:
        return []
    return [
        {
            "item": public_item(doc),
            "score": float(doc.get("popularity", 0)),
            "source": "popular",
        }
        for doc in docs
    ]


async def get_user_profile_embedding(user_id: ObjectId) -> list[float]:
    try:
        profile = await with_timeout(
            db.user_profiles.find_one({"userId": user_id}, {"embedding": 1}),
            timeout_ms=2000,
        )
    except Exception:
        return []
    embedding = (profile or {}).get("embedding") or []
    return embedding if len(embedding) == 1536 else []


async def recent_average_embedding(user_id: ObjectId) -> list[float]:
    try:
        recent = (
            db.interactions.find({"userId": user_id, **positive_engagement_filter()})
            .sort("timestamp", -1)
            .limit(16)
        )
        recent_docs = await with_timeout(recent.to_list(length=16), timeout_ms=2000)
        recent_item_ids = [doc["itemId"] for doc in recent_docs]
        recent_items = await with_timeout(
            db.items.find(
                {"_id": {"$in": recent_item_ids}, "embedding": {"$exists": True}}
            ).to_list(length=16),
            timeout_ms=2000,
        )
    except Exception:
        return []
    item_map = {item["_id"]: item for item in recent_items}
    weighted_vectors: list[tuple[list[float], float]] = []
    for index, interaction in enumerate(recent_docs):
        item = item_map.get(interaction["itemId"])
        embedding = (item or {}).get("embedding") or []
        if len(embedding) != 1536:
            continue
        base = interaction.get("weightedScore")
        if base is None:
            base = implicit_weight(interaction.get("type", ""), interaction.get("score"))
        # Newest interactions should steer session recommendations aggressively.
        recency_rank_boost = 1 + ((len(recent_docs) - index) / max(len(recent_docs), 1))
        weight = decay_score(float(base), interaction.get("timestamp")) * recency_rank_boost
        if weight > 0:
            weighted_vectors.append((embedding, weight))

    if not weighted_vectors:
        return average_embeddings([item["embedding"] for item in recent_items if item.get("embedding")])

    total_weight = sum(weight for _embedding, weight in weighted_vectors)
    return [
        sum(embedding[index] * weight for embedding, weight in weighted_vectors) / total_weight
        for index in range(1536)
    ]


async def local_vector_search(
    query_vector: list[float], seen_ids: list[ObjectId], limit: int
) -> list[dict[str, Any]]:
    candidate_limit = max(min(limit * 40, 700), 250)
    candidates = await db.items.find(
        {"_id": {"$nin": seen_ids}, "available": True, "embedding": {"$exists": True}}
    ).to_list(length=candidate_limit)
    scored = []
    for item in candidates:
        embedding = item.get("embedding") or []
        if len(embedding) != len(query_vector):
            continue
        item["recScore"] = cosine_similarity(query_vector, embedding)
        scored.append(item)
    return sorted(scored, key=lambda doc: doc.get("recScore", 0), reverse=True)[:limit]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
