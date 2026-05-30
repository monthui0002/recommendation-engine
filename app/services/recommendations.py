import asyncio
import math
import random
from datetime import timedelta
from typing import Any, Literal

from bson import ObjectId

from app.config import get_settings
from app.db import db
from app.services.embeddings import average_embeddings
from app.services.ids import resolve_item_id, resolve_user_id
from app.services.timeouts import with_timeout
from app.utils import ensure_aware_utc, ensure_object_id, serialize_doc, utcnow


settings = get_settings()
INTERACTION_WEIGHTS = {"view": 1.0, "click": 2.0, "purchase": 5.0}
TIME_DECAY_LAMBDA = 0.1


def implicit_weight(interaction_type: str, score: float | None = None) -> float:
    if interaction_type == "rate":
        return float(score or 0) * 2
    return INTERACTION_WEIGHTS.get(interaction_type, 1.0)


def decay_score(score: float, timestamp: Any) -> float:
    timestamp = ensure_aware_utc(timestamp)
    if not timestamp:
        return score
    days = max((utcnow() - timestamp).total_seconds() / 86400, 0)
    return score * math.exp(-TIME_DECAY_LAMBDA * days)


def public_item(doc: dict[str, Any]) -> dict[str, Any]:
    item = serialize_doc(doc)
    item.pop("embedding", None)
    item.pop("recScore", None)
    return item


async def seen_item_ids(user_id: ObjectId, since_days: int | None = None) -> list[ObjectId]:
    query: dict[str, Any] = {"userId": user_id}
    if since_days is not None:
        query["timestamp"] = {"$gte": utcnow() - timedelta(days=since_days)}
    cursor = db.interactions.find(query, {"itemId": 1})
    try:
        docs = await with_timeout(cursor.to_list(length=5000))
    except Exception:
        return []
    return [doc["itemId"] for doc in docs]


async def interaction_count(user_id: ObjectId) -> int:
    try:
        return await with_timeout(db.interactions.count_documents({"userId": user_id}))
    except Exception:
        return 0


async def top_popular_items(limit: int = 20) -> list[dict[str, Any]]:
    try:
        cursor = db.items.find({"available": True}).sort("popularity", -1).limit(limit)
        docs = await with_timeout(cursor.to_list(length=limit))
    except Exception:
        return []
    return [
        {"item": public_item(doc), "score": float(doc.get("popularity", 0)), "source": "popular"}
        for doc in docs
    ]


async def get_user_profile_embedding(user_id: ObjectId) -> list[float]:
    try:
        profile = await with_timeout(
            db.user_profiles.find_one({"userId": user_id}, {"embedding": 1})
        )
    except Exception:
        return []
    embedding = (profile or {}).get("embedding") or []
    return embedding if len(embedding) == 1536 else []


async def recent_average_embedding(user_id: ObjectId) -> list[float]:
    try:
        recent = db.interactions.find({"userId": user_id}).sort("timestamp", -1).limit(5)
        recent_docs = await with_timeout(recent.to_list(length=5))
        recent_item_ids = [doc["itemId"] for doc in recent_docs]
        recent_items = await with_timeout(
            db.items.find(
                {"_id": {"$in": recent_item_ids}, "embedding": {"$exists": True}}
            ).to_list(length=5)
        )
    except Exception:
        return []
    return average_embeddings([item["embedding"] for item in recent_items if item.get("embedding")])


async def content_based_rec(
    user_id: str | int | ObjectId,
    limit: int = 20,
    context: str | int | ObjectId | None = None,
) -> list[dict[str, Any]]:
    user_oid = await resolve_user_id(user_id)

    # Cold start: too little behavior means vectors are noisy, so fall back to popularity.
    if await interaction_count(user_oid) < 3:
        return await top_popular_items(limit)

    seen_ids = await seen_item_ids(user_oid)
    query_vector = await get_user_profile_embedding(user_oid)
    if not query_vector:
        query_vector = await recent_average_embedding(user_oid)
    if not query_vector:
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
            docs = await with_timeout(local_vector_search(query_vector, seen_ids, limit))
        except Exception:
            return await top_popular_items(limit)

    recs = [{"item": public_item(doc), "score": float(doc.get("recScore", 0)), "source": "content"} for doc in docs]

    # Genre/tag affinity boost — personalises beyond pure embedding proximity
    affinity = await user_genre_affinity(user_oid)
    if affinity:
        recs = apply_genre_affinity(recs, affinity)

    return await apply_context_boost(recs, context)


async def collaborative_rec(
    user_id: str | int | ObjectId,
    limit: int = 20,
    context: str | int | ObjectId | None = None,
) -> list[dict[str, Any]]:
    user_oid = await resolve_user_id(user_id)

    # Cold start: collaborative overlap is unreliable below three interactions.
    if await interaction_count(user_oid) < 3:
        return await top_popular_items(limit)

    seen_ids = await seen_item_ids(user_oid)
    similar_users_pipeline = [
        {"$match": {"userId": user_oid}},
        {
            "$lookup": {
                "from": "interactions",
                "let": {"item_id": "$itemId", "current_user": "$userId"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$itemId", "$$item_id"]},
                                    {"$ne": ["$userId", "$$current_user"]},
                                ]
                            }
                        }
                    }
                ],
                "as": "otherInteractions",
            }
        },
        {"$unwind": "$otherInteractions"},
        {
            "$group": {
                "_id": "$otherInteractions.userId",
                "overlap": {"$sum": 1},
                "similarity": {"$sum": {"$ifNull": ["$otherInteractions.score", 1]}},
            }
        },
        {"$addFields": {"similarity": {"$multiply": ["$similarity", "$overlap"]}}},
        {"$sort": {"similarity": -1, "overlap": -1}},
        {"$limit": 30},
    ]
    try:
        similar_users = await with_timeout(
            db.interactions.aggregate(similar_users_pipeline).to_list(length=30)
        )
    except Exception:
        return []
    if not similar_users:
        return []

    similarity_by_user = {doc["_id"]: float(doc.get("similarity", 1)) for doc in similar_users}
    similar_user_ids = list(similarity_by_user.keys())
    liked_types = ["click", "purchase", "rate"]
    cursor = db.interactions.find(
        {
            "userId": {"$in": similar_user_ids},
            "itemId": {"$nin": seen_ids},
            "type": {"$in": liked_types},
        }
    )

    scores: dict[ObjectId, dict[str, Any]] = {}
    try:
        collab_docs = await with_timeout(cursor.to_list(length=5000))
    except Exception:
        return []
    for doc in collab_docs:
        base = implicit_weight(doc["type"], doc.get("score"))
        # Temporal dynamics: recent positive behavior should carry more collaborative weight.
        weighted = decay_score(base * similarity_by_user.get(doc["userId"], 1), doc.get("timestamp"))
        entry = scores.setdefault(
            doc["itemId"],
            {"score": 0.0, "lastInteraction": doc.get("timestamp")},
        )
        entry["score"] += weighted
        doc_timestamp = ensure_aware_utc(doc.get("timestamp"))
        entry_timestamp = ensure_aware_utc(entry["lastInteraction"])
        if doc_timestamp and (not entry_timestamp or doc_timestamp > entry_timestamp):
            entry["lastInteraction"] = doc_timestamp

    if not scores:
        return []

    top_ids = sorted(scores, key=lambda item_id: scores[item_id]["score"], reverse=True)[: limit * 3]
    try:
        items = await with_timeout(
            db.items.find({"_id": {"$in": top_ids}, "available": True}).to_list(length=len(top_ids))
        )
    except Exception:
        return []
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
    return await apply_context_boost(recs, context)


async def hybrid_rec(
    user_id: str | int | ObjectId,
    limit: int = 20,
    context: str | int | ObjectId | None = None,
    rec_type: Literal["offline", "session"] = "session",
) -> list[dict[str, Any]]:
    user_oid = await resolve_user_id(user_id)

    if await interaction_count(user_oid) < 3:
        recs = await top_popular_items(20)
        return await exploration_replace(user_oid, recs[:limit], limit)

    intent_tags = await session_intent_tags(user_oid)
    content, collab = await asyncio.gather(
        content_based_rec(user_oid, limit * 2, context),
        collaborative_rec(user_oid, limit * 2, context),
    )

    # Data sparsity: if collaborative candidates are thin, lean harder on content.
    content_weight, collab_weight = (0.8, 0.2) if len(collab) < 5 else (0.4, 0.6)
    if intent_tags:
        content_weight, collab_weight = max(content_weight, 0.75), min(collab_weight, 0.25)
    merged: dict[str, dict[str, Any]] = {}
    add_weighted_candidates(merged, content, content_weight)
    add_weighted_candidates(merged, collab, collab_weight)

    ranked = rerank_multi_objective(list(merged.values()), intent_tags)

    # Genre/tag affinity boost — explicit preference on top of implicit vectors
    affinity = await user_genre_affinity(user_oid)
    if affinity:
        ranked = apply_genre_affinity(ranked, affinity, strength=0.2)

    if not ranked:
        ranked = await top_popular_items(limit)
    filtered = await filtering_layer(user_oid, ranked)
    if not filtered:
        filtered = await top_popular_items(limit)

    # MMR diversity reranking — reduce genre/tag cluster redundancy
    diverse = mmr_rerank(filtered, lambda_=0.7, limit=limit * 2)
    explored = await exploration_replace(user_oid, diverse[:limit], limit, rec_type)
    return explored[:limit]


def add_weighted_candidates(
    merged: dict[str, dict[str, Any]], candidates: list[dict[str, Any]], weight: float
) -> None:
    for candidate in candidates:
        item = candidate["item"]
        item_id = item["id"]
        score = candidate.get("score", 0.0) * weight
        score = decay_score(score, candidate.get("lastInteraction"))
        if item_id not in merged:
            merged[item_id] = {"item": item, "score": 0.0, "sources": []}
        merged[item_id]["score"] += score
        merged[item_id]["sources"].append(candidate.get("source", "unknown"))


async def filtering_layer(user_id: ObjectId, recs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recent_seen = {str(item_id) for item_id in await seen_item_ids(user_id, since_days=7)}
    item_ids = [ensure_object_id(rec["item"]["id"]) for rec in recs]
    try:
        available_docs = await with_timeout(
            db.items.find(
                {"_id": {"$in": item_ids}, "available": True},
                {"_id": 1},
            ).to_list(length=len(item_ids))
        )
    except Exception:
        return recs
    available_ids = {str(doc["_id"]) for doc in available_docs}
    return [
        rec
        for rec in recs
        if rec["item"]["id"] in available_ids and rec["item"]["id"] not in recent_seen
    ]


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
        context_item = await with_timeout(db.items.find_one({"_id": context_oid}, {"tags": 1}))
    except Exception:
        return recs
    if not context_item:
        return recs
    context_tags = set(context_item.get("tags", []))
    for rec in recs:
        tags = set(rec["item"].get("tags", []))
        overlap = len(context_tags.intersection(tags))
        if overlap:
            rec["score"] *= 1 + min(overlap * 0.15, 0.6)
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
    since = utcnow() - timedelta(minutes=5)
    try:
        recent = await with_timeout(
            db.interactions.find(
                {"userId": user_id, "timestamp": {"$gte": since}},
                {"itemId": 1},
            ).to_list(length=20)
        )
        if len(recent) < 3:
            return set()
        items = await with_timeout(
            db.items.find(
                {"_id": {"$in": [doc["itemId"] for doc in recent]}},
                {"tags": 1},
            ).to_list(length=20)
        )
    except Exception:
        return set()

    tag_counts: dict[str, int] = {}
    for item in items:
        for tag in item.get("tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return {tag for tag, count in tag_counts.items() if count >= 3}


def rerank_multi_objective(
    recs: list[dict[str, Any]], intent_tags: set[str] | None = None
) -> list[dict[str, Any]]:
    intent_tags = intent_tags or set()
    for rec in recs:
        item = rec["item"]
        margin = float(item.get("businessMargin", 0) or 0)
        freshness = freshness_boost(item.get("createdAt"))
        intent_boost = 1.0
        if intent_tags and intent_tags.intersection(set(item.get("tags", []))):
            intent_boost = 1.35
        rec["score"] = float(rec.get("score", 0)) * (1 + margin) * (1 + freshness) * intent_boost
        rec["rankingSignals"] = {
            "businessMargin": margin,
            "freshnessBoost": round(freshness, 4),
            "sessionIntentBoost": intent_boost,
        }
    return sorted(recs, key=lambda rec: rec["score"], reverse=True)


def freshness_boost(created_at: Any) -> float:
    try:
        created_at = ensure_aware_utc(created_at)
    except ValueError:
        return 0.0
    if not created_at:
        return 0.0
    days = max((utcnow() - created_at).total_seconds() / 86400, 0)
    return min(math.exp(-0.05 * days) * 0.2, 0.2)


async def local_vector_search(
    query_vector: list[float], seen_ids: list[ObjectId], limit: int
) -> list[dict[str, Any]]:
    candidates = await db.items.find(
        {"_id": {"$nin": seen_ids}, "available": True, "embedding": {"$exists": True}}
    ).to_list(length=1000)
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


# ─── Diversity re-ranking: Maximal Marginal Relevance (MMR) ───────────────────

def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two tag/genre sets."""
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def mmr_rerank(
    recs: list[dict[str, Any]],
    lambda_: float = 0.7,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Maximal Marginal Relevance diversity reranking.

        score_mmr(d) = λ * relevance(d) - (1-λ) * max_{s∈Selected} sim(d, s)

    Balances relevance with diversity — prevents redundant genre/tag clusters
    dominating the recommendation list. Similarity is Jaccard on tags+genres.
    """
    if len(recs) <= 1:
        return recs[:limit]

    max_score = max(r["score"] for r in recs) or 1.0
    remaining = list(recs)
    selected: list[dict[str, Any]] = []

    while remaining and len(selected) < limit:
        best_idx, best_mmr = 0, -float("inf")
        for i, rec in enumerate(remaining):
            relevance = rec["score"] / max_score
            tags_i = set((rec["item"].get("tags") or []) + (rec["item"].get("genres") or []))
            if not selected:
                mmr_score = relevance
            else:
                max_sim = max(
                    _jaccard(
                        tags_i,
                        set(
                            (s["item"].get("tags") or [])
                            + (s["item"].get("genres") or [])
                        ),
                    )
                    for s in selected
                )
                mmr_score = lambda_ * relevance - (1 - lambda_) * max_sim
            if mmr_score > best_mmr:
                best_mmr, best_idx = mmr_score, i
        selected.append(remaining.pop(best_idx))

    return selected


# ─── Genre / Tag affinity profile ─────────────────────────────────────────────

async def user_genre_affinity(user_id: ObjectId) -> dict[str, float]:
    """
    Build a normalized genre+tag preference profile from interaction history.
    Weights are time-decayed implicit scores, so recently watched genres
    matter more than old ones.
    Returns {genre_or_tag: affinity_weight} or {} on data sparsity.
    """
    try:
        interactions = await with_timeout(
            db.interactions.find({"userId": user_id})
            .sort("timestamp", -1)
            .limit(200)
            .to_list(length=200)
        )
    except Exception:
        return {}
    if not interactions:
        return {}

    item_ids = list({doc["itemId"] for doc in interactions})
    try:
        items = await with_timeout(
            db.items.find(
                {"_id": {"$in": item_ids}}, {"genres": 1, "tags": 1}
            ).to_list(length=len(item_ids))
        )
    except Exception:
        return {}

    item_map = {item["_id"]: item for item in items}
    affinity: dict[str, float] = {}
    for interaction in interactions:
        item = item_map.get(interaction["itemId"])
        if not item:
            continue
        weight = implicit_weight(interaction.get("type", "view"), interaction.get("score"))
        weight = decay_score(weight, interaction.get("timestamp"))
        for label in (item.get("genres") or []) + (item.get("tags") or []):
            affinity[label] = affinity.get(label, 0.0) + weight

    total = sum(affinity.values()) or 1.0
    return {g: v / total for g, v in affinity.items()}


def apply_genre_affinity(
    recs: list[dict[str, Any]],
    affinity: dict[str, float],
    strength: float = 0.35,
) -> list[dict[str, Any]]:
    """
    Multiplicatively boost candidates matching the user's genre/tag preferences.
    strength=0.35 means a perfectly-matching item gets up to a +35% score lift.
    """
    for rec in recs:
        item_tags = set(
            (rec["item"].get("genres") or []) + (rec["item"].get("tags") or [])
        )
        boost = sum(affinity.get(g, 0.0) for g in item_tags)
        rec["score"] *= 1.0 + boost * strength
    return sorted(recs, key=lambda r: r["score"], reverse=True)


# ─── Trending recommendations (interaction velocity) ──────────────────────────

async def trending_items(
    user_id: ObjectId,
    limit: int = 20,
    window_hours: int = 24,
) -> list[dict[str, Any]]:
    """
    Surface items with high interaction velocity in the last `window_hours`.
    Groups by itemId, counts interactions, joins to items collection, and
    filters out already-seen items. Falls back to top-popular on cold start.
    """
    since = utcnow() - timedelta(hours=window_hours)
    seen_ids = await seen_item_ids(user_id)

    pipeline: list[dict[str, Any]] = [
        {"$match": {"timestamp": {"$gte": since}, "itemId": {"$nin": seen_ids}}},
        {
            "$group": {
                "_id": "$itemId",
                "interactionCount": {"$sum": 1},
                "totalScore": {"$sum": {"$ifNull": ["$score", 1.0]}},
            }
        },
        {"$sort": {"interactionCount": -1, "totalScore": -1}},
        {"$limit": limit * 3},
        {
            "$lookup": {
                "from": "items",
                "localField": "_id",
                "foreignField": "_id",
                "as": "itemDoc",
            }
        },
        {"$unwind": "$itemDoc"},
        {"$match": {"itemDoc.available": True}},
        {"$limit": limit},
    ]

    try:
        docs = await with_timeout(
            db.interactions.aggregate(pipeline).to_list(length=limit)
        )
    except Exception:
        docs = []

    if docs:
        return [
            {
                "item": public_item(doc["itemDoc"]),
                "score": float(doc["interactionCount"]),
                "trendScore": float(doc["interactionCount"]),
                "source": "trending",
            }
            for doc in docs
        ]

    # Cold start: no recent interactions → fall back to popularity ranking
    fallback = await top_popular_items(limit)
    return [dict(rec, source="trending") for rec in fallback]
