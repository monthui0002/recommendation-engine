import asyncio
import signal
from contextlib import suppress
from typing import Any

from bson import ObjectId
from redis.exceptions import ResponseError

from app.core.config import get_settings
from app.core.database import close_connections, create_indexes, db, redis_client
from app.services.cache import invalidate_user_cache
from app.services.ids import resolve_item_id, resolve_user_id
from app.services.recommendations import implicit_weight
from app.utils import ensure_object_id, utcnow


settings = get_settings()
STOP = asyncio.Event()


def _stop(*_args: Any) -> None:
    STOP.set()


async def enqueue_interaction_event(payload: dict[str, Any]) -> str:
    interaction_type = payload["type"]
    event = {
        "userId": str(payload["userId"]),
        "itemId": str(payload["itemId"]),
        "type": str(getattr(interaction_type, "value", interaction_type)),
        "score": "" if payload.get("score") is None else str(payload["score"]),
        "createdAt": utcnow().isoformat(),
    }
    return await redis_client.xadd(settings.interaction_stream, event)


async def ensure_consumer_group() -> None:
    try:
        await redis_client.xgroup_create(
            settings.interaction_stream,
            settings.interaction_group,
            id="0",
            mkstream=True,
        )
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def process_interaction_event(fields: dict[str, str]) -> ObjectId:
    user_id = await resolve_user_id(fields["userId"])
    item_id = await resolve_item_id(fields["itemId"])
    score = float(fields["score"]) if fields.get("score") else None
    interaction_type = fields["type"]

    user = await db.users.find_one({"_id": user_id}, {"_id": 1})
    item = await db.items.find_one({"_id": item_id})
    if not user or not item:
        raise ValueError("User or item not found")

    timestamp = utcnow()
    doc = {
        "userId": user_id,
        "itemId": item_id,
        "type": interaction_type,
        "score": score,
        "weightedScore": implicit_weight(interaction_type, score),
        "timestamp": timestamp,
    }
    result = await db.interactions.insert_one(doc)
    await update_user_profile(user_id, item, doc["weightedScore"])
    await invalidate_user_cache(str(user_id))
    return result.inserted_id


async def update_user_profile(
    user_id: ObjectId, item: dict[str, Any], weight: float
) -> None:
    embedding = item.get("embedding") or []
    if len(embedding) != 1536 or weight <= 0:
        return

    profile = await db.user_profiles.find_one({"userId": user_id})
    now = utcnow()
    if not profile:
        await db.user_profiles.insert_one(
            {
                "userId": user_id,
                "embedding": embedding,
                "interactionWeight": weight,
                "updatedAt": now,
            }
        )
        return

    previous_weight = float(profile.get("interactionWeight", 0))
    total_weight = previous_weight + weight
    previous_embedding = profile.get("embedding") or embedding
    updated_embedding = [
        ((previous_embedding[i] * previous_weight) + (embedding[i] * weight)) / total_weight
        for i in range(1536)
    ]
    await db.user_profiles.update_one(
        {"userId": user_id},
        {
            "$set": {
                "embedding": updated_embedding,
                "interactionWeight": total_weight,
                "updatedAt": now,
            }
        },
    )


async def run_worker(consumer_name: str = "worker-1") -> None:
    await create_indexes()
    await ensure_consumer_group()
    while not STOP.is_set():
        response = await redis_client.xreadgroup(
            settings.interaction_group,
            consumer_name,
            {settings.interaction_stream: ">"},
            count=10,
            block=1000,
        )
        for _stream, messages in response:
            for event_id, fields in messages:
                try:
                    await process_interaction_event(fields)
                    await redis_client.xack(
                        settings.interaction_stream,
                        settings.interaction_group,
                        event_id,
                    )
                except Exception as exc:
                    await db.failed_interaction_events.insert_one(
                        {
                            "eventId": event_id,
                            "fields": fields,
                            "error": str(exc),
                            "timestamp": utcnow(),
                        }
                    )


async def main() -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _stop)
    try:
        await run_worker()
    finally:
        await close_connections()


if __name__ == "__main__":
    asyncio.run(main())
