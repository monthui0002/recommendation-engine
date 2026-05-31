from typing import Any

from bson import ObjectId

from app.db import db
from app.services.timeouts import with_timeout

from .signals import (
    EXPOSURE_ONLY_TYPES,
    POSITIVE_RATING_THRESHOLD,
    decay_score,
    implicit_weight,
)


async def user_genre_affinity(user_id: ObjectId) -> dict[str, float]:
    """
    Build a normalized genre+tag preference profile from interaction history.
    Weights are time-decayed implicit scores, so recently watched genres matter more.
    """
    try:
        interactions = await with_timeout(
            db.interactions.find({"userId": user_id})
            .sort("timestamp", -1)
            .limit(200)
            .to_list(length=200),
            timeout_ms=20000,
        )
    except Exception:
        return {}
    if not interactions:
        return {}

    item_ids = list({doc["itemId"] for doc in interactions})
    try:
        items = await with_timeout(
            db.items.find({"_id": {"$in": item_ids}}, {"genres": 1, "tags": 1}).to_list(
                length=len(item_ids)
            ),
            timeout_ms=20000,
        )
    except Exception:
        return {}

    item_map = {item["_id"]: item for item in items}
    affinity: dict[str, float] = {}
    for interaction in interactions:
        item = item_map.get(interaction["itemId"])
        if not item:
            continue
        if (
            interaction.get("type") == "rate"
            and float(interaction.get("score") or 0) < POSITIVE_RATING_THRESHOLD
        ):
            continue
        weight = implicit_weight(interaction.get("type", "impression"), interaction.get("score"))
        weight = decay_score(weight, interaction.get("timestamp"))
        if weight <= 0 or interaction.get("type") in EXPOSURE_ONLY_TYPES:
            continue
        for label in (item.get("genres") or []) + (item.get("tags") or []):
            affinity[label] = affinity.get(label, 0.0) + weight

    total = sum(affinity.values()) or 1.0
    return {genre: value / total for genre, value in affinity.items()}


def apply_genre_affinity(
    recs: list[dict[str, Any]],
    affinity: dict[str, float],
    strength: float = 0.35,
) -> list[dict[str, Any]]:
    """
    Multiplicatively boost candidates matching the user's genre/tag preferences.
    strength=0.35 means a perfectly matching item gets up to a +35% score lift.
    """
    for rec in recs:
        item_tags = set((rec["item"].get("genres") or []) + (rec["item"].get("tags") or []))
        boost = sum(affinity.get(genre, 0.0) for genre in item_tags)
        rec["score"] *= 1.0 + boost * strength
    return sorted(recs, key=lambda rec: rec["score"], reverse=True)
