import asyncio
import json
import signal
from contextlib import suppress
from typing import Any

from bson import ObjectId
from redis.exceptions import ResponseError

from app.core.config import get_settings
from app.core.database import close_connections, create_indexes, check_connections, db, redis_client
from app.services.cache import invalidate_user_cache
from app.services.ids import resolve_item_id, resolve_user_id
from app.services.recommendations import (
    implicit_weight,
    interaction_source_multiplier,
    should_update_positive_profile,
)
from app.utils import utcnow


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
        "completionRate": ""
        if payload.get("completionRate") is None
        else str(payload["completionRate"]),
        "source": "" if payload.get("source") is None else str(payload["source"]),
        "positionSeconds": ""
        if payload.get("positionSeconds") is None
        else str(payload["positionSeconds"]),
        "durationSeconds": ""
        if payload.get("durationSeconds") is None
        else str(payload["durationSeconds"]),
        "clientEventId": ""
        if payload.get("clientEventId") is None
        else str(payload["clientEventId"]),
        "recommendationId": ""
        if payload.get("recommendationId") is None
        else str(payload["recommendationId"]),
        "contextItemId": ""
        if payload.get("contextItemId") is None
        else str(payload["contextItemId"]),
        "metadata": json.dumps(payload.get("metadata") or {}),
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
    completion_rate = (
        float(fields["completionRate"]) if fields.get("completionRate") else None
    )
    position_seconds = (
        float(fields["positionSeconds"]) if fields.get("positionSeconds") else None
    )
    duration_seconds = (
        float(fields["durationSeconds"]) if fields.get("durationSeconds") else None
    )
    try:
        metadata = json.loads(fields.get("metadata") or "{}")
    except json.JSONDecodeError:
        metadata = {}
    interaction_type = fields["type"]
    if completion_rate is None and position_seconds is not None and duration_seconds:
        completion_rate = min(max(position_seconds / duration_seconds, 0), 1)

    user = await db.users.find_one({"_id": user_id}, {"_id": 1, "movielensUserId": 1})
    item = await db.items.find_one({"_id": item_id})
    if not user or not item:
        raise ValueError("User or item not found")

    metadata = json.loads(fields.get("metadata") or "{}")
    timestamp = utcnow()
    weighted_score = implicit_weight(interaction_type, score)
    if interaction_type == "watch_progress" and completion_rate is not None:
        weighted_score *= max(0.0, min(completion_rate, 1.0))
    weighted_score *= interaction_source_multiplier(fields.get("source") or None, interaction_type)

    doc = {
        "userId": user_id,
        "itemId": item_id,
        "type": interaction_type,
        "score": score,
        "completionRate": completion_rate,
        "positionSeconds": position_seconds,
        "durationSeconds": duration_seconds,
        "source": fields.get("source") or None,
        "clientEventId": fields.get("clientEventId") or None,
        "recommendationId": fields.get("recommendationId") or None,
        "contextItemId": fields.get("contextItemId") or None,
        "metadata": metadata,
        "movielensUserId": user.get("movielensUserId"),
        "movieId": item.get("movieId"),
        "weightedScore": weighted_score,
        "timestamp": timestamp,
    }
    result = await db.interactions.insert_one(doc)
    if should_update_positive_profile(interaction_type, weighted_score):
        await update_user_profile(user_id, item, weighted_score)
    if interaction_type != "impression":
        await invalidate_user_cache(
            fields.get("userId"),
            str(user_id),
            user.get("movielensUserId"),
        )
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
    await check_connections()
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
