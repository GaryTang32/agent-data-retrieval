"""Run-to-run determinism metrics."""

from __future__ import annotations

from itertools import combinations

from adr_eval.scoring.exact import normalize_value
from adr_eval.scoring.outcomes import Outcome


def retrieval_identity_rate(runs: dict[str, list[list[str]]]) -> float:
    """Share of items whose repeats all returned the same ranked ids."""
    if not runs:
        return 0.0
    return sum(all(r == reps[0] for r in reps) for reps in runs.values()) / len(runs)


def answer_agreement(runs: dict[str, list[str]]) -> float | None:
    """Mean over items (>= 2 repeats) of the share of repeat pairs with equal normalized answers."""
    shares = []
    for reps in runs.values():
        if len(reps) < 2:
            continue
        norm = [normalize_value(r) for r in reps]
        pairs = list(combinations(norm, 2))
        shares.append(sum(a == b for a, b in pairs) / len(pairs))
    return sum(shares) / len(shares) if shares else None


def pass_hat_k(outcomes: dict[str, list[Outcome]]) -> float:
    """Share of items whose repeats are all `correct`."""
    if not outcomes:
        return 0.0
    passed = sum(bool(o) and all(x == "correct" for x in o) for o in outcomes.values())
    return passed / len(outcomes)
