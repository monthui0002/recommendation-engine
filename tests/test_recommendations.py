from datetime import timedelta

from app.services.recommendations import (
    decay_score,
    freshness_boost,
    implicit_weight,
    rerank_multi_objective,
    should_update_positive_profile,
)
from app.utils import utcnow


def test_implicit_feedback_weighting() -> None:
    assert implicit_weight("impression") == 0
    assert implicit_weight("click") == 4
    assert implicit_weight("watchlist_add") == 6
    assert implicit_weight("watch_start") == 4
    assert implicit_weight("watch_complete") == 10
    assert implicit_weight("like") == 9
    assert implicit_weight("dislike") == -4
    assert implicit_weight("hide") == -8
    assert implicit_weight("search_click") == 9
    assert implicit_weight("share") == 6
    assert implicit_weight("rate", 4) == 12


def test_positive_profile_update_requires_real_positive_signal() -> None:
    assert not should_update_positive_profile("impression", 0)
    assert not should_update_positive_profile("rate", 10)
    assert should_update_positive_profile("rate", 12)
    assert should_update_positive_profile("watch_complete", 10)


def test_time_decay_reduces_old_scores() -> None:
    recent = decay_score(10, utcnow())
    old = decay_score(10, utcnow() - timedelta(days=10))

    assert recent > old
    assert old > 0


def test_time_decay_accepts_mongodb_naive_datetime() -> None:
    naive_timestamp = (utcnow() - timedelta(days=1)).replace(tzinfo=None)

    assert decay_score(10, naive_timestamp) > 0


def test_multi_objective_rerank_uses_margin_freshness_and_intent() -> None:
    older_high_raw = {
        "item": {
            "id": "a",
            "tags": ["finance"],
            "businessMargin": 0,
            "createdAt": utcnow() - timedelta(days=200),
        },
        "score": 10,
    }
    fresh_margin_intent = {
        "item": {
            "id": "b",
            "tags": ["gaming"],
            "businessMargin": 0.5,
            "createdAt": utcnow(),
        },
        "score": 8,
    }

    ranked = rerank_multi_objective([older_high_raw, fresh_margin_intent], {"gaming"})

    assert ranked[0]["item"]["id"] == "b"
    assert ranked[0]["rankingSignals"]["sessionIntentBoost"] == 1.35


def test_freshness_boost_caps_at_twenty_percent() -> None:
    assert freshness_boost(utcnow()) <= 0.2
