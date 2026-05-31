from datetime import timedelta
from typing import Any

from bson import ObjectId

from app.db import db
from app.services.timeouts import with_timeout
from app.utils import utcnow

from .common import public_item, seen_item_ids, top_popular_items
from .signals import positive_engagement_filter


async def trending_items(
    user_id: ObjectId,
    limit: int = 20,
    window_hours: int = 24,
) -> list[dict[str, Any]]:
    """
    Surface items with high interaction velocity in the recent window.
    """
    since = utcnow() - timedelta(hours=window_hours)
    seen_ids = await seen_item_ids(user_id)

    pipeline: list[dict[str, Any]] = [
        {
            "$match": {
                "timestamp": {"$gte": since},
                "itemId": {"$nin": seen_ids},
                **positive_engagement_filter(),
            }
        },
        {
            "$group": {
                "_id": "$itemId",
                "interactionCount": {"$sum": 1},
                "totalScore": {
                    "$sum": {"$ifNull": ["$weightedScore", {"$ifNull": ["$score", 1.0]}]}
                },
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
        docs = await with_timeout(db.interactions.aggregate(pipeline).to_list(length=limit))
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

    fallback = await top_popular_items(limit)
    return [dict(rec, source="trending") for rec in fallback]
