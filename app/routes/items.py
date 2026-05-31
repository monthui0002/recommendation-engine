from typing import Any

from fastapi import APIRouter, Query
from bson import ObjectId

from app.config import get_settings
from app.db import db
from app.services.ids import resolve_user_id
from app.services.timeouts import with_timeout
from app.utils import serialize_doc

router = APIRouter(prefix="/items", tags=["items"])
settings = get_settings()


def _normalize_imdb_id(imdb_id: str) -> str:
    """Strip 'tt' prefix from OMDB-format IDs so we can match the imdbId field in MongoDB."""
    return imdb_id[2:] if imdb_id.startswith("tt") else imdb_id


def _public_item(doc: dict[str, Any]) -> dict[str, Any]:
    item = serialize_doc(doc)
    item.pop("embedding", None)
    return item


@router.get("/{imdb_id}/similar")
async def similar_items(
    imdb_id: str,
    limit: int = Query(12, ge=1, le=50),
) -> dict[str, Any]:
    """
    Find movies similar to the one identified by `imdb_id` (accepts both
    OMDB-style tt-prefixed IDs like tt0803093 and bare numeric strings like 0803093).

    Uses Atlas Vector Search on the item's stored embedding — returns the
    closest neighbours by cosine similarity, excluding the source item itself.
    """
    clean_id = _normalize_imdb_id(imdb_id)

    # Look up the source item by the imdbId field stored in MongoDB
    try:
        source = await with_timeout(
            db.items.find_one({"imdbId": clean_id}, {"embedding": 1, "title": 1})
        )
    except Exception:
        source = None

    if not source or not source.get("embedding"):
        return {"imdbId": imdb_id, "sourceTitle": None, "count": 0, "items": []}

    query_vector: list[float] = source["embedding"]

    pipeline: list[dict[str, Any]] = [
        {
            "$vectorSearch": {
                "index": settings.vector_index_name,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": max((limit + 1) * 10, 150),
                "limit": limit + 1,  # fetch one extra to drop the source item
            }
        },
        # exclude the source movie itself
        {"$match": {"_id": {"$ne": source["_id"]}, "available": True}},
        {"$addFields": {"similarityScore": {"$meta": "vectorSearchScore"}}},
        {"$limit": limit},
        {"$project": {"embedding": 0}},
    ]

    try:
        docs = await with_timeout(db.items.aggregate(pipeline).to_list(length=limit))
    except Exception:
        docs = []

    return {
        "imdbId": imdb_id,
        "sourceTitle": source.get("title"),
        "count": len(docs),
        "items": [
            {
                "item": _public_item(doc),
                "score": round(float(doc.get("similarityScore", 0)), 4),
                "source": "similar",
            }
            for doc in docs
        ],
    }


@router.get("/watchlist/{user_id}")
async def get_watchlist(user_id: str) -> dict[str, Any]:
    """
    Return the current watchlist for a user.
    An item is on the watchlist when its watchlist_add count exceeds watchlist_remove count.
    """
    try:
        uid = await resolve_user_id(user_id)
    except Exception:
        return {"userId": user_id, "count": 0, "items": []}

    # Aggregate add/remove counts per item
    pipeline = [
        {
            "$match": {
                "userId": uid,
                "type": {"$in": ["watchlist_add", "watchlist_remove"]},
            }
        },
        {
            "$group": {
                "_id": "$itemId",
                "adds": {
                    "$sum": {"$cond": [{"$eq": ["$type", "watchlist_add"]}, 1, 0]}
                },
                "removes": {
                    "$sum": {"$cond": [{"$eq": ["$type", "watchlist_remove"]}, 1, 0]}
                },
                "lastAdded": {"$max": "$timestamp"},
            }
        },
        # Keep only items where net adds > 0
        {"$match": {"$expr": {"$gt": ["$adds", "$removes"]}}},
        {"$sort": {"lastAdded": -1}},
        # Join with items collection to get details
        {
            "$lookup": {
                "from": "items",
                "localField": "_id",
                "foreignField": "_id",
                "as": "item",
            }
        },
        {"$unwind": "$item"},
        {"$project": {"item.embedding": 0}},
    ]

    try:
        docs = await with_timeout(
            db.interactions.aggregate(pipeline).to_list(length=500)
        )
    except Exception:
        docs = []

    return {
        "userId": user_id,
        "count": len(docs),
        "items": [_public_item(doc["item"]) for doc in docs],
    }
