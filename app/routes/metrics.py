from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import MetricsResponse
from app.services.ids import resolve_user_id
from app.services.metrics import metrics_for_user


router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/{user_id}", response_model=MetricsResponse)
async def metrics(user_id: str, k: int = Query(10, ge=1, le=100)) -> MetricsResponse:
    try:
        await resolve_user_id(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid userId or MovieLens userId") from exc

    data = await metrics_for_user(user_id, k)
    return MetricsResponse(userId=user_id, **data)
