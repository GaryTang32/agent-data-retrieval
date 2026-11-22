"""Shared fixtures for the Task 16 tests (reference evaluator, binding tests, grid equivalence,
Z3 analysis): compiled bindings of a few draw shapes, built by the Task 15 compiler from the
synthetic cards and parameters of `test_bindings_compile`, the reference draw that § 117.821's
fixture draw should equal, and helpers that rebuild a binding with a changed condition (new
ids, validated through `Binding.model_validate`). Store-free; no model call."""

from __future__ import annotations

from datetime import datetime, timedelta

from adr_store.bindings.compile import ALL_TIMES
from adr_store.bindings.dsl import DAYS, Binding, Window, binding_ids, required_facts
from adr_store.bindings.reference import RefDraw
from tests.store.test_bindings_compile import (
    CARD_A,
    CARD_B,
    EMERGENCY_CARD,
    GENERAL_CARD,
    IN_A,
    IN_B,
    WEEKDAYS,
    closed,
    draw,
    notice_period,
    on_signal,
    run,
)

__all__ = ["BINDINGS_821", "BINDINGS_821_GROUPED", "BINDINGS_SAME_CARD_SIGNAL",
           "BINDINGS_CROSSING", "BINDINGS_GENERAL", "BINDINGS_NOTICE_PERIOD",
           "BINDINGS_SHUT", "BINDINGS_SIGNAL", "CARD_A", "CARD_B", "EMERGENCY_CARD",
           "FIXTURE_BINDINGS", "GENERAL_CARD", "REF_821", "REF_SIGNAL", "W_821", "by_rule",
           "record", "rebuild", "shift", "stamp_analysed", "with_when"]

UNIT_821 = "8" * 64
W_821 = Window(start=420, end=540, days=WEEKDAYS, except_federal_holidays=True, date_from=None,
               date_to=None)

# § 117.821's fixture draw: on signal, 4 hours notice at all other times (P46), closed 7-9
# a.m. on weekdays except federal holidays -> a closed-window forbid, the notice basis and its
# complement over "not the window", the on-signal basis there, and § 117.31(b) overriding both
# forbids.
DRAW_821 = draw(opening_basis="on_signal", notice_hours=4,
                periods=[closed(420, 540, days=WEEKDAYS, holidays=True)])
BINDINGS_821 = run(DRAW_821)[0]
REF_821 = RefDraw(section="117.821", draw=1, bridge="Main Street drawbridge",
                  opens_on_signal=True, notice_hours=4, closed=(W_821,), unit=UNIT_821,
                  section_draws=(("Main Street drawbridge", 3.4),))

# on signal at all times except a closed window that crosses midnight (every day, P44); the
# enrichment numbers it draw 2 of the section, Phase 3 draw 1
DRAW_SIGNAL = draw(n=2, opening_basis="on_signal", periods=[closed(1380, 360)])
BINDINGS_SIGNAL = run(DRAW_SIGNAL)[0]
REF_SIGNAL = RefDraw(section="117.821", draw=1, bridge="Main Street drawbridge",
                     opens_on_signal=True, notice_hours=None,
                     closed=(Window(start=1380, end=360, days=DAYS, except_federal_holidays=False,
                                    date_from=None, date_to=None),),
                     unit=UNIT_821, section_draws=(("Main Street drawbridge", 3.4),))

# on signal in a season, a notice period with its complement, and § 117.5 in the gap left
BINDINGS_NOTICE_PERIOD = run(draw(notice_hours=2, periods=[
    on_signal("04-01", "10-31"), notice_period(0, 1440, days=("Sat", "Sun"), at=IN_B)]))[0]

# no rule at all: § 117.5 at all times (a constant) and § 117.31(b) with nothing to override
BINDINGS_GENERAL = run(draw(periods=[]))[0]

# a Monday-only night closure that crosses midnight, as the compiler takes it from enrichment
# periods (P44: Tuesday 01:00 is in it, Monday 01:00 is not), on signal otherwise
BINDINGS_CROSSING = run(draw(opening_basis="on_signal",
                             periods=[closed(1380, 360, days=("Mon",))]))[0]

# a need-not-open period with no times, days or dates: closed at all times; the compiler
# emits its always-firing forbid, which the analysis rejects as vacuous (§12.4)
BINDINGS_SHUT = run(draw(opening_basis="on_signal", periods=[closed(None, None)]))[0]

# the same rules quoted in one card, as 33 CFR 117 usually writes them: "shall open on signal
# if at least 4 hours notice is given" (on signal and the notice in one phrase, so the basis is
# `or(notice at all times, at all times)`), and § 117.821's closure with its notice in one
# paragraph (the forbid is `or(window, not window and notice short)`)
BINDINGS_SAME_CARD_SIGNAL = run(draw(opening_basis="on_signal", notice_hours=4,
                                     notice_at=IN_A))[0]
DRAW_821_GROUPED = draw(opening_basis="on_signal", notice_hours=4, notice_at=IN_A,
                        periods=[closed(420, 540, days=WEEKDAYS, holidays=True)])
BINDINGS_821_GROUPED = run(DRAW_821_GROUPED)[0]

FIXTURE_BINDINGS = [b for bs in (BINDINGS_821, BINDINGS_SIGNAL, BINDINGS_NOTICE_PERIOD,
                                 BINDINGS_CROSSING, BINDINGS_SHUT, BINDINGS_SAME_CARD_SIGNAL,
                                 BINDINGS_821_GROUPED) for b in bs]


def by_rule(bindings: list[Binding], rule_id: str, effect: str) -> Binding:
    """The one binding of `rule_id` and `effect`."""
    (b,) = [b for b in bindings if b.rule_id == rule_id and b.effect == effect]
    return b


def rebuild(b: Binding, **update) -> Binding:
    """`b` with `update` applied and its ids and required facts recomputed, validated."""
    data = {**b.model_dump(), **update}
    bid, version = binding_ids(data)
    return Binding.model_validate({**data, "binding_id": bid, "binding_version": version,
                                   "required_facts": required_facts(data["when"])})


def with_when(b: Binding, when: dict) -> Binding:
    return rebuild(b, when=when)


def _shift_expr(e, minutes: int):
    if isinstance(e, list):
        return [_shift_expr(x, minutes) for x in e]
    if not isinstance(e, dict):
        return e
    out = {k: _shift_expr(v, minutes) for k, v in e.items()}
    if "window" in e and e["window"] != ALL_TIMES.model_dump(mode="json"):
        w = e["window"]
        start, end = (w["start"] + minutes) % 1440, (w["end"] + minutes) % 1440 or 1440
        out["window"] = {**w, "start": start, "end": end}
    return out


def shift(bindings: list[Binding], minutes: int) -> list[Binding]:
    """Every window of every binding moved by `minutes` (binding ids do not depend on the
    condition, so overrides still name the same forbids)."""
    return [rebuild(b, when=_shift_expr(b.when, minutes)) for b in bindings]


def record(open_at: datetime | None = None, *, notice: int | None = None,
           vessel: str | None = None, conflict: bool | None = None) -> dict:
    """A request record: notice received `notice` minutes before `open_at`."""
    out: dict = {}
    if notice is not None:
        out["notice_received_at"] = {"value": (open_at - timedelta(minutes=notice)).isoformat(),
                                     "source": "record"}
    if vessel is not None:
        out["vessel_class"] = {"value": vessel, "source": "record"}
    if conflict is not None:
        out["local_procedure_conflict"] = {"value": conflict, "source": "record"}
    return out


STAMPED = {"conflicts": [], "vacuous": False, "redundant": False, "gaps": [],
           "stamped": "tests: no z3 analysis"}


def stamp_analysed(bindings: list[Binding]) -> list[Binding]:
    """`tested` bindings `analysed` with the `STAMPED` record (validated); every other binding
    as it is. A test helper standing in for `analysis.mark_analysed` where z3 is absent."""
    return [Binding.model_validate({**b.model_dump(), "status": "analysed",
                                    "analysis": dict(STAMPED)})
            if b.status == "tested" else b for b in bindings]
