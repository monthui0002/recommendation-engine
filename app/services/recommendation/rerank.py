import math
from typing import Any

from app.utils import ensure_aware_utc, utcnow

from .signals import decay_score


def add_weighted_candidates(
    merged: dict[str, dict[str, Any]], candidates: list[dict[str, Any]], weight: float
) -> None:
    for candidate in candidates:
        item = candidate["item"]
        item_id = item["id"]
        score = candidate.get("score", 0.0) * weight
        score = decay_score(score, candidate.get("lastInteraction"))
        if item_id not in merged:
            merged[item_id] = {"item": item, "score": 0.0, "sources": []}
        merged[item_id]["score"] += score
        merged[item_id]["sources"].append(candidate.get("source", "unknown"))


def normalize_candidate_scores(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not candidates:
        return []
    scores = [float(candidate.get("score", 0.0) or 0.0) for candidate in candidates]
    min_score = min(scores)
    max_score = max(scores)
    if math.isclose(max_score, min_score):
        return [dict(candidate, score=1.0) for candidate in candidates]

    normalized = []
    for candidate in candidates:
        score = float(candidate.get("score", 0.0) or 0.0)
        normalized.append(dict(candidate, score=(score - min_score) / (max_score - min_score)))
    return normalized


def rerank_multi_objective(
    recs: list[dict[str, Any]], intent_tags: set[str] | None = None
) -> list[dict[str, Any]]:
    intent_tags = intent_tags or set()
    for rec in recs:
        item = rec["item"]
        margin = float(item.get("businessMargin", 0) or 0)
        freshness = freshness_boost(item.get("createdAt"))
        intent_boost = 1.0
        if intent_tags and intent_tags.intersection(set(item.get("tags", []))):
            intent_boost = 1.35
        rec["score"] = float(rec.get("score", 0)) * (1 + margin) * (1 + freshness) * intent_boost
        rec["rankingSignals"] = {
            "businessMargin": margin,
            "freshnessBoost": round(freshness, 4),
            "sessionIntentBoost": intent_boost,
        }
    return sorted(recs, key=lambda rec: rec["score"], reverse=True)


def freshness_boost(created_at: Any) -> float:
    try:
        created_at = ensure_aware_utc(created_at)
    except ValueError:
        return 0.0
    if not created_at:
        return 0.0
    days = max((utcnow() - created_at).total_seconds() / 86400, 0)
    return min(math.exp(-0.05 * days) * 0.2, 0.2)


def _jaccard(a: set, b: set) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def mmr_rerank(
    recs: list[dict[str, Any]],
    lambda_: float = 0.7,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Maximal Marginal Relevance: preserve relevance while reducing repeated genres/tags.
    """
    if len(recs) <= 1:
        return recs[:limit]

    max_score = max(rec["score"] for rec in recs) or 1.0
    remaining = list(recs)
    selected: list[dict[str, Any]] = []

    while remaining and len(selected) < limit:
        best_idx, best_mmr = 0, -float("inf")
        for index, rec in enumerate(remaining):
            relevance = rec["score"] / max_score
            tags_i = set((rec["item"].get("tags") or []) + (rec["item"].get("genres") or []))
            if not selected:
                mmr_score = relevance
            else:
                max_sim = max(
                    _jaccard(
                        tags_i,
                        set((chosen["item"].get("tags") or []) + (chosen["item"].get("genres") or [])),
                    )
                    for chosen in selected
                )
                mmr_score = lambda_ * relevance - (1 - lambda_) * max_sim
            if mmr_score > best_mmr:
                best_mmr, best_idx = mmr_score, index
        selected.append(remaining.pop(best_idx))

    return selected
