import asyncio
from collections import defaultdict
from typing import Any

from app.db import create_indexes, db
from app.services.embeddings import get_embedding, inferred_tags
from app.services.recommendations import POSITIVE_RATING_THRESHOLD, implicit_weight
from app.utils import utcnow


async def refresh_item_embeddings() -> dict[Any, list[float]]:
    embedding_by_item_id: dict[Any, list[float]] = {}
    cursor = db.items.find({}, {"title": 1, "genres": 1, "tags": 1, "description": 1})

    async for item in cursor:
        title = item.get("title") or ""
        genres = item.get("genres") or []
        tags = item.get("tags") or []
        text = f"{title} {' '.join(genres)} {' '.join(tags)} {item.get('description') or ''}"
        semantic_tags = inferred_tags(text)
        merged_tags = sorted(set(tags + semantic_tags))
        embedding = get_embedding(f"{title} {' '.join(genres)} {' '.join(merged_tags)}")
        embedding_by_item_id[item["_id"]] = embedding
        await db.items.update_one(
            {"_id": item["_id"]},
            {"$set": {"embedding": embedding, "tags": merged_tags}},
        )

    return embedding_by_item_id


async def rebuild_user_profiles(embedding_by_item_id: dict[Any, list[float]]) -> None:
    await db.user_profiles.delete_many({})
    profile_sums: dict[Any, list[float]] = {}
    profile_weights: dict[Any, float] = defaultdict(float)

    cursor = db.interactions.find(
        {
            "type": {"$in": ["rate", "click", "search_click", "watch_complete", "like", "watchlist_add"]},
            "$or": [
                {"type": {"$ne": "rate"}},
                {"type": "rate", "score": {"$gte": POSITIVE_RATING_THRESHOLD}},
            ],
        },
        {"userId": 1, "itemId": 1, "type": 1, "score": 1, "weightedScore": 1},
    )
    async for interaction in cursor:
        embedding = embedding_by_item_id.get(interaction["itemId"])
        if not embedding:
            continue
        weight = interaction.get("weightedScore")
        if weight is None:
            weight = implicit_weight(interaction.get("type", ""), interaction.get("score"))
        weight = float(weight or 0)
        if weight <= 0:
            continue

        current = profile_sums.setdefault(interaction["userId"], [0.0] * 1536)
        for index, value in enumerate(embedding):
            current[index] += value * weight
        profile_weights[interaction["userId"]] += weight

    now = utcnow()
    profile_docs = []
    for user_id, vector_sum in profile_sums.items():
        total_weight = profile_weights[user_id]
        if total_weight <= 0:
            continue
        profile_docs.append(
            {
                "userId": user_id,
                "embedding": [value / total_weight for value in vector_sum],
                "interactionWeight": total_weight,
                "updatedAt": now,
            }
        )

    if profile_docs:
        await db.user_profiles.insert_many(profile_docs)


async def main() -> None:
    await create_indexes()
    embedding_by_item_id = await refresh_item_embeddings()
    await rebuild_user_profiles(embedding_by_item_id)
    print(f"Refreshed embeddings for {len(embedding_by_item_id)} items")
    print("Rebuilt user_profiles")


if __name__ == "__main__":
    asyncio.run(main())
