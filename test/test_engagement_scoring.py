import math
import pytest

from mastodon_is_my_blog.engagement_scoring import (
    FAVOURITE,
    HALF_LIFE_DAYS,
    REBLOG,
    REPLY,
    decayed_weight,
    score_interactions,
)


def test_decayed_weight_zero_age():
    assert decayed_weight(REPLY, 0) == pytest.approx(REPLY)


def test_decayed_weight_at_half_life():
    result = decayed_weight(REPLY, HALF_LIFE_DAYS)
    assert result == pytest.approx(REPLY / 2, rel=1e-6)


def test_decayed_weight_future_date_clamped():
    # Negative age_days should be clamped to 0
    assert decayed_weight(REPLY, -10) == pytest.approx(REPLY)


def test_decayed_weight_decreases_monotonically():
    prev = decayed_weight(REBLOG, 0)
    for days in [30, 90, 180, 365]:
        curr = decayed_weight(REBLOG, days)
        assert curr < prev
        prev = curr


def test_score_interactions_empty():
    assert score_interactions([]) == 0.0


def test_score_interactions_single_reply():
    rows = [{"type": "mention", "age_days": 0}]
    result = score_interactions(rows)
    assert result == pytest.approx(REPLY)


def test_score_interactions_single_reblog():
    rows = [{"type": "reblog", "age_days": 0}]
    result = score_interactions(rows)
    assert result == pytest.approx(REBLOG)


def test_score_interactions_single_favourite():
    rows = [{"type": "favourite", "age_days": 0}]
    result = score_interactions(rows)
    assert result == pytest.approx(FAVOURITE)


def test_score_interactions_mixed():
    rows = [
        {"type": "mention", "age_days": 0},
        {"type": "reblog", "age_days": 0},
        {"type": "favourite", "age_days": 0},
    ]
    result = score_interactions(rows)
    assert result == pytest.approx(REPLY + REBLOG + FAVOURITE)


def test_score_interactions_aged_event_lower_than_fresh():
    fresh = score_interactions([{"type": "mention", "age_days": 0}])
    old = score_interactions([{"type": "mention", "age_days": 365}])
    assert old < fresh


def test_score_interactions_unknown_type_uses_weight_one():
    rows = [{"type": "unknown_type", "age_days": 0}]
    result = score_interactions(rows)
    assert result == pytest.approx(1.0)
