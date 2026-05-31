import math
from typing import Any

from app.utils import ensure_aware_utc, utcnow


INTERACTION_WEIGHTS = {
    # Exposure only: used for CTR / negative sampling, never as positive preference.
    "impression": 0.0,
    "click": 4.0,
    "watchlist_add": 6.0,
    "watch_start": 4.0,
    "watch_progress": 5.0,
    "watch_complete": 10.0,
    "watchlist_remove": -2.0,
    "like": 9.0,
    "dislike": -4.0,
    "hide": -8.0,
    "search_click": 9.0,
    "share": 6.0,
}

TIME_DECAY_LAMBDA = 0.1
MIN_TIME_DECAY_FACTOR = 0.05
RECENT_PROFILE_WEIGHT = 0.8
POSITIVE_RATING_THRESHOLD = 3.5
POSITIVE_RATING_WEIGHT_THRESHOLD = POSITIVE_RATING_THRESHOLD * 3
EXPOSURE_ONLY_TYPES = {"impression"}
ENGAGEMENT_TYPES = [
    "click",
    "watchlist_add",
    "watch_start",
    "watch_progress",
    "watch_complete",
    "rate",
    "like",
    "search_click",
    "share",
]
POSITIVE_NON_RATING_TYPES = [
    interaction_type for interaction_type in ENGAGEMENT_TYPES if interaction_type != "rate"
]


def interaction_source_multiplier(source: str | None, interaction_type: str) -> float:
    if interaction_type == "impression":
        return 1.0
    if source == "detail_page":
        return 2.5
    if source == "search":
        return 2.0
    if source == "context":
        return 1.8
    if source == "recommendation":
        return 1.3
    return 1.0


def implicit_weight(interaction_type: str, score: float | None = None) -> float:
    if interaction_type == "rate":
        return float(score or 0) * 3
    return INTERACTION_WEIGHTS.get(interaction_type, 1.0)


def should_update_positive_profile(interaction_type: str, weighted_score: float) -> bool:
    if interaction_type == "rate":
        return weighted_score >= POSITIVE_RATING_WEIGHT_THRESHOLD
    return interaction_type in POSITIVE_NON_RATING_TYPES and weighted_score > 0


def positive_engagement_filter() -> dict[str, Any]:
    return {
        "type": {"$in": ENGAGEMENT_TYPES},
        "$or": [
            {"type": {"$in": POSITIVE_NON_RATING_TYPES}},
            {"type": "rate", "score": {"$gte": POSITIVE_RATING_THRESHOLD}},
        ],
    }


def decay_score(score: float, timestamp: Any) -> float:
    timestamp = ensure_aware_utc(timestamp)
    if not timestamp:
        return score
    days = max((utcnow() - timestamp).total_seconds() / 86400, 0)
    return score * max(math.exp(-TIME_DECAY_LAMBDA * days), MIN_TIME_DECAY_FACTOR)


def blend_embeddings(
    long_term: list[float],
    recent: list[float],
    recent_weight: float = RECENT_PROFILE_WEIGHT,
) -> list[float]:
    if not long_term:
        return recent
    if not recent:
        return long_term
    if len(long_term) != len(recent):
        return long_term
    long_term_weight = 1 - recent_weight
    return [
        (long_term[index] * long_term_weight) + (recent[index] * recent_weight)
        for index in range(len(long_term))
    ]
