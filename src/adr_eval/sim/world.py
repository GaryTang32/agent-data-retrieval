"""The world of one simulated task (Phase 4 spec §13.1, §13.4; P35): the request record (facts
with their sources), the opening schedule (every opening ever made, `active` or `cancelled`),
the denial log and the escalation queue. Only executed side effects change it.

`end_state` reduces it to the three lists of `expected_state`: each opening as (request,
section, draw, `open_at`, status), cancelled ones included, and the request id of each denial
and escalation. `state_matches` compares two such states as multisets: an extra, missing or
duplicate opening, denial or escalation fails, and so does a cancelled opening (P35)."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

from adr_eval.sim.tasks import SimTask

__all__ = ["OPENING_KEYS", "World", "state_matches"]

OPENING_KEYS = ("request", "section", "draw", "open_at", "status")


@dataclass
class World:
    task: SimTask
    record: dict
    openings: list[dict] = field(default_factory=list)     # each with its opening_id
    denials: list[str] = field(default_factory=list)
    escalations: list[str] = field(default_factory=list)

    def end_state(self) -> dict:
        """{"openings": [...], "denials": [...], "escalations": [...]} (module text)."""
        return {"openings": [{k: o[k] for k in OPENING_KEYS} for o in self.openings],
                "denials": list(self.denials), "escalations": list(self.escalations)}


def _multiset(items: list) -> Counter:
    return Counter(json.dumps(x, sort_keys=True) for x in items)


def state_matches(end: dict, expected: dict) -> bool:
    """Whether `end` equals `expected` as three multisets (module text)."""
    return all(_multiset(end.get(k, [])) == _multiset(expected.get(k, []))
               for k in ("openings", "denials", "escalations"))
