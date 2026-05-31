import asyncio
from typing import Any, Literal

from bson import ObjectId

from app.services.ids import resolve_user_id

from .affinity import apply_genre_affinity, user_genre_affinity
from .collaborative import collaborative_rec
from .common import interaction_count, top_popular_items
from .content import content_based_rec
from .contextual import contextual_item_rec
from .filters import exploration_replace, fill_with_popular, filtering_layer, session_intent_tags
from .rerank import (
    add_weighted_candidates,
    mmr_rerank,
    normalize_candidate_scores,
    rerank_multi_objective,
)


async def hybrid_rec(
    user_id: str | int | ObjectId,
    limit: int = 20,
    context: str | int | ObjectId | None = None,
    rec_type: Literal["offline", "session"] = "session",
) -> list[dict[str, Any]]:
    user_oid = await resolve_user_id(user_id)

    if await interaction_count(user_oid) < 3:
        if context:
            recs = await contextual_item_rec(context, user_oid, limit)
            if recs:
                return await exploration_replace(user_oid, recs[:limit], limit)
        recs = await top_popular_items(20)
        return await exploration_replace(user_oid, recs[:limit], limit)

    intent_tags = await session_intent_tags(user_oid)
    content, collab, context_recs = await asyncio.gather(
        content_based_rec(user_oid, limit * 2, context),
        collaborative_rec(user_oid, limit * 2, context),
        contextual_item_rec(context, user_oid, limit * 2) if context else asyncio.sleep(0, result=[]),
    )

    # Data sparsity: if collaborative candidates are thin, lean harder on content.
    content_weight, collab_weight = (0.8, 0.2) if len(collab) < 5 else (0.4, 0.6)
    context_weight = 0.0
    if context:
        # Detail pages should feel item-to-item first, user-profile second.
        content_weight, collab_weight, context_weight = 0.25, 0.10, 2.5
    elif intent_tags:
        content_weight, collab_weight = max(content_weight, 0.75), min(collab_weight, 0.25)

    merged: dict[str, dict[str, Any]] = {}
    add_weighted_candidates(merged, normalize_candidate_scores(content), content_weight)
    add_weighted_candidates(merged, normalize_candidate_scores(collab), collab_weight)
    if context_recs:
        add_weighted_candidates(merged, normalize_candidate_scores(context_recs), context_weight)

    ranked = rerank_multi_objective(list(merged.values()), intent_tags)

    affinity = await user_genre_affinity(user_oid)
    if affinity:
        ranked = apply_genre_affinity(ranked, affinity, strength=0.2)

    if not ranked:
        ranked = await top_popular_items(limit)
    filtered = await filtering_layer(user_oid, ranked)
    if not filtered:
        filtered = await top_popular_items(limit)

    diverse = mmr_rerank(filtered, lambda_=0.9 if context else 0.7, limit=limit * 2)
    diverse = await fill_with_popular(diverse, limit)
    explored = await exploration_replace(user_oid, diverse[:limit], limit, rec_type)
    return explored[:limit]
