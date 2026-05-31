from app.models.schemas import InteractionEventCreate, InteractionType


def test_supported_core_interaction_types() -> None:
    assert {item.value for item in InteractionType} == {
        "impression",
        "click",
        "watchlist_add",
        "watch_start",
        "watch_progress",
        "watch_complete",
        "rate",
        "watchlist_remove",
        "like",
        "dislike",
        "hide",
        "search_click",
        "share",
    }


def test_watch_progress_accepts_completion_rate_alias() -> None:
    event = InteractionEventCreate(
        userId=1,
        itemId=1,
        completion_rate=0.72,
        position_seconds=4320,
        duration_seconds=6000,
        source="player",
    )

    assert event.completionRate == 0.72
    assert event.positionSeconds == 4320
    assert event.durationSeconds == 6000
