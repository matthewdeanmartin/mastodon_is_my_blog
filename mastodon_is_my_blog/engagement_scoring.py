# mastodon_is_my_blog/engagement_scoring.py
import math
from datetime import datetime

REPLY = 10
QUOTE = 7
REBLOG = 5
FAVOURITE = 1

HALF_LIFE_DAYS = 180.0


def decayed_weight(base: int, age_days: float) -> float:
    if age_days < 0:
        age_days = 0.0
    return base * math.exp(-math.log(2) * age_days / HALF_LIFE_DAYS)


def score_interactions(rows: list[dict]) -> float:
    """Sum decayed weighted events.

    Each row must have:
      - type: str — 'mention' | 'reblog' | 'favourite' | 'quote' (notification types)
      - age_days: float — how old the interaction is
    """
    total = 0.0
    for row in rows:
        interaction_type = row.get("type", "")
        age_days = float(row.get("age_days", 0.0))
        if interaction_type in ("mention", "status"):
            base = REPLY
        elif interaction_type == "quote":
            base = QUOTE
        elif interaction_type == "reblog":
            base = REBLOG
        elif interaction_type == "favourite":
            base = FAVOURITE
        else:
            base = 1
        total += decayed_weight(base, age_days)
    return total
