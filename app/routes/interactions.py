from typing import Any

from fastapi import APIRouter, HTTPException

from app.background.interaction_worker import enqueue_interaction_event
from app.core.database import db
from app.models.schemas import (
    InteractionCreate,
    InteractionEventCreate,
    InteractionQueuedResponse,
    InteractionType,
)
from app.services.timeouts import with_timeout
from app.services.cache import invalidate_user_cache
from app.services.ids import resolve_item_id, resolve_user_id


router = APIRouter(tags=["interactions"])


@router.get("/interactions/{user_id}/items/{item_id}/summary")
async def interaction_summary(user_id: str, item_id: str) -> dict[str, Any]:
    try:
        user_oid = await resolve_user_id(user_id)
        item_oid = await resolve_item_id(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="User or item not found") from exc

    try:
        docs = await with_timeout(
            db.interactions.find({"userId": user_oid, "itemId": item_oid})
            .sort("timestamp", -1)
            .limit(100)
            .to_list(length=100),
            timeout_ms=2000,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Interaction summary unavailable") from exc

    return build_interaction_summary(user_id, item_id, docs)


@router.post("/interact", response_model=InteractionQueuedResponse)
async def interact(payload: InteractionCreate) -> InteractionQueuedResponse:
    return await queue_interaction(payload.model_dump())


@router.post("/interact/{interaction_type}", response_model=InteractionQueuedResponse)
async def interact_by_type(
    interaction_type: InteractionType,
    payload: InteractionEventCreate,
) -> InteractionQueuedResponse:
    data = payload.model_dump()
    data["type"] = interaction_type
    return await queue_interaction(data)


async def queue_interaction(payload: dict) -> InteractionQueuedResponse:
    interaction_type = str(getattr(payload.get("type"), "value", payload.get("type")))
    completion_rate = payload.get("completionRate")
    score = payload.get("score")
    position_seconds = payload.get("positionSeconds")
    duration_seconds = payload.get("durationSeconds")

    if completion_rate is None and position_seconds is not None and duration_seconds:
        payload["completionRate"] = min(max(float(position_seconds) / float(duration_seconds), 0), 1)
        completion_rate = payload["completionRate"]

    if interaction_type == "watch_progress" and completion_rate is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "watch_progress requires completionRate between 0 and 1 "
                "or positionSeconds + durationSeconds"
            ),
        )
    if interaction_type == "watch_complete" and completion_rate is None:
        payload["completionRate"] = 1.0
    if interaction_type == "rate" and score is None:
        raise HTTPException(status_code=422, detail="rate requires score")
    if interaction_type == "rate" and not 0.5 <= float(score) <= 5:
        raise HTTPException(status_code=422, detail="rate score must be between 0.5 and 5")
    if interaction_type in {"dislike", "hide"}:
        payload["score"] = payload.get("score") or 0
    if interaction_type == "watch_start":
        payload["completionRate"] = payload.get("completionRate") or 0

    try:
        event_id = await with_timeout(enqueue_interaction_event(payload))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Interaction queue unavailable") from exc
    if interaction_type != "impression":
        try:
            await with_timeout(invalidate_user_cache(payload.get("userId")))
        except Exception:
            pass

    return InteractionQueuedResponse(
        status="queued",
        eventId=str(event_id),
        userId=str(payload["userId"]),
        itemId=str(payload["itemId"]),
    )


def build_interaction_summary(
    user_id: str,
    item_id: str,
    docs: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_rating = next(
        (float(doc["score"]) for doc in docs if doc.get("type") == "rate" and doc.get("score") is not None),
        None,
    )
    max_completion = max(
        [float(doc.get("completionRate") or 0) for doc in docs if doc.get("completionRate") is not None],
        default=0.0,
    )
    event_counts: dict[str, int] = {}
    for doc in docs:
        event_type = doc.get("type")
        if event_type:
            event_counts[event_type] = event_counts.get(event_type, 0) + 1

    latest = docs[0] if docs else None
    return {
        "userId": user_id,
        "itemId": item_id,
        "hasInteracted": bool(docs),
        "latestRating": latest_rating,
        "maxCompletionRate": round(max_completion, 4),
        "watchCompleted": any(doc.get("type") == "watch_complete" for doc in docs)
        or max_completion >= 0.9,
        "watchStarted": any(
            doc.get("type") in {"watch_start", "watch_progress", "watch_complete"}
            for doc in docs
        ),
        "watchlistAdded": event_counts.get("watchlist_add", 0)
        > event_counts.get("watchlist_remove", 0),
        "liked": event_counts.get("like", 0) > event_counts.get("dislike", 0),
        "disliked": event_counts.get("dislike", 0) >= event_counts.get("like", 0)
        and event_counts.get("dislike", 0) > 0,
        "hidden": event_counts.get("hide", 0) > 0,
        "shareCount": event_counts.get("share", 0),
        "eventCounts": event_counts,
        "lastInteractionType": latest.get("type") if latest else None,
        "lastInteractionAt": latest.get("timestamp") if latest else None,
    }
