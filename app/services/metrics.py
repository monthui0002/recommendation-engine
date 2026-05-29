import random

from bson import ObjectId

from app.db import db
from app.services.ids import resolve_user_id


async def metrics_for_user(user_id: str | int | ObjectId, k: int = 10) -> dict[str, float]:
    oid = await resolve_user_id(user_id)
    interactions = await db.interactions.find({"userId": oid}).sort("timestamp", -1).limit(k).to_list(length=k)
    tags: set[str] = set()
    if interactions:
        item_ids = [doc["itemId"] for doc in interactions]
        items = await db.items.find({"_id": {"$in": item_ids}}, {"tags": 1}).to_list(length=len(item_ids))
        for item in items:
            tags.update(item.get("tags", []))

    # Precision@K is mocked because there is no held-out ground truth in this sample app.
    precision_at_k = round(random.uniform(0.45, 0.9), 3)
    diversity = round(min(len(tags) / max(k, 1), 1.0), 3)
    return {"precisionAtK": precision_at_k, "diversityScore": diversity}
