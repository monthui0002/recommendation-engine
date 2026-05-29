from fastapi import APIRouter, HTTPException

from app.background.interaction_worker import enqueue_interaction_event
from app.models.schemas import InteractionCreate, InteractionQueuedResponse
from app.services.timeouts import with_timeout


router = APIRouter(tags=["interactions"])


@router.post("/interact", response_model=InteractionQueuedResponse)
async def interact(payload: InteractionCreate) -> InteractionQueuedResponse:
    try:
        event_id = await with_timeout(enqueue_interaction_event(payload.model_dump()))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Interaction queue unavailable") from exc

    return InteractionQueuedResponse(
        status="queued",
        eventId=str(event_id),
        userId=str(payload.userId),
        itemId=str(payload.itemId),
    )
