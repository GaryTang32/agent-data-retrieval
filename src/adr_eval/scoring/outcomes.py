"""Outcome labels and the abstention-penalised score."""

from __future__ import annotations

from typing import Literal

Outcome = Literal["correct", "partial", "wrong", "abstained", "error"]


def penalised_score(outcomes: list[Outcome], t: float) -> float:
    """Mean of correct=1, abstained=0, wrong/partial=-t/(1-t); `error` is excluded."""
    scored = [o for o in outcomes if o != "error"]
    if not scored:
        return 0.0
    penalty = -t / (1.0 - t)
    return sum(1.0 if o == "correct" else 0.0 if o == "abstained" else penalty
               for o in scored) / len(scored)
