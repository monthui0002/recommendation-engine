from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import RecommendationResponse
from app.services.cache import with_cache
from app.services.ids import resolve_user_id
from app.services.recommendations import collaborative_rec, content_based_rec, hybrid_rec, trending_items


router = APIRouter(prefix="/recommend", tags=["recommendations"])


async def validate_user_id(user_id: str) -> None:
    try:
        await resolve_user_id(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid userId or MovieLens userId") from exc


@router.get("/{user_id}", response_model=RecommendationResponse)
async def recommend(
    user_id: str,
    limit: int = Query(20, ge=1, le=100),
    context: str | None = Query(None),
    cache_type: str = Query("session", pattern="^(session|offline)$"),
) -> RecommendationResponse:
    await validate_user_id(user_id)

    ttl = 3600 if cache_type == "offline" else 60
    cache_variant = f"v9:{cache_type}:limit={limit}:context={context or 'none'}"
    key = f"rec:{user_id}:{cache_variant}"
    items = await with_cache(
        key,
        ttl,
        lambda: hybrid_rec(user_id, limit=limit, context=context, rec_type=cache_type),
    )
    return RecommendationResponse(
        userId=user_id,
        type="hybrid",
        count=len(items),
        items=items,
    )


@router.get("/{user_id}/content", response_model=RecommendationResponse)
async def recommend_content(
    user_id: str,
    limit: int = Query(20, ge=1, le=100),
    context: str | None = Query(None),
) -> RecommendationResponse:
    await validate_user_id(user_id)

    items = await content_based_rec(user_id, limit=limit, context=context)
    return RecommendationResponse(
        userId=user_id,
        type="content",
        count=len(items),
        items=items,
    )


@router.get("/{user_id}/collab", response_model=RecommendationResponse)
async def recommend_collab(
    user_id: str,
    limit: int = Query(20, ge=1, le=100),
    context: str | None = Query(None),
) -> RecommendationResponse:
    await validate_user_id(user_id)

    items = await collaborative_rec(user_id, limit=limit, context=context)
    return RecommendationResponse(
        userId=user_id,
        type="collaborative",
        count=len(items),
        items=items,
    )


@router.get("/{user_id}/trending", response_model=RecommendationResponse)
async def recommend_trending(
    user_id: str,
    limit: int = Query(20, ge=1, le=100),
    window_hours: int = Query(24, ge=1, le=168),
) -> RecommendationResponse:
    """
    Trending items by interaction velocity in the last `window_hours` (default 24h).
    Filters out items already seen by the user. Falls back to popularity on cold start.
    """
    await validate_user_id(user_id)

    user_oid = await resolve_user_id(user_id)
    items = await trending_items(user_oid, limit=limit, window_hours=window_hours)
    return RecommendationResponse(
        userId=user_id,
        type="trending",
        count=len(items),
        items=items,
    )
