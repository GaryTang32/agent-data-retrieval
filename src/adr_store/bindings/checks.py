"""Binding tests (Phase 4 spec §12.3, P12, P15, P32, P37, P44, P46; builder note 14; Task 16):
behavioural tests generated from each binding's own parameters, complement probes, the B1
grid against the reference evaluator, and the statuses they give. No z3 here.

**The intended condition** of a binding is rebuilt from its parameters (`params_prov`, the
enrichment values the compiler recorded), not from its `when`, so that a wrong encoding of the
parameters fails (the spec: these tests "check the encoding of their parameters, not the
parameters"). Each period it records gives a window (no times is the whole day, no days every
day, no dates all year), and the period's effect gives the part: `need_not_open` a forbid in
the window, `on_signal` a basis in it, `notice_required` with N hours a basis with at least 60N
minutes of notice and a forbid with less (N = 0: a basis, no forbid). A period-less notice or
on-signal basis (P46, recognised by its `notice_hours` without a notice period, or its
`opening_basis`) holds at all other times: the draw's other periods are not among the
binding's parameters, so the complement is taken as the `when` writes it, and it must leave
out the binding's own periods (a wrong complement on its own is for the grid to catch). § 117.5
holds outside every period it records (always, with none); § 117.31(b) holds for an emergency
class with no conflict. Parameters with no part, a period-less parameter with no
all-other-times condition, or a condition the compiler never writes are failures.

**Cases** (`boundary_cases`, at least `MIN_CASES` each way): for every window of the binding
(its parameters' and its `when`'s), the minutes just before, at, just inside the end of and at
the end, on two days each window admits, on an admitted day of each weekday it lists (of those
its dates admit), and on the days it shuts out (a weekday it lacks, a
federal holiday it excepts, the days just outside its dates), each also on the day before and
after (a crossing window's early minutes are judged on the day before, P44), every day with
every window's edge minutes; the notice values
at and one below each threshold, 0 and 48 hours; each vessel class with the conflict true and
false for § 117.31(b). Each is labelled by the intended condition (`expect` "T" or "F"), its
windows judged by the reference's own `ref_in_window`, not by the evaluator's. Then, in two
true cases and in one where each part holds, every fact the binding reads is dropped, nulled
or given the wrong type, and the case is labelled with the intended condition's strong Kleene
value with that fact unknown ("T", "F" or "U": an `or` of T and U is T, so a part that does
not read the fact can keep the binding true). A constant has no boundary: § 117.5 at all
times gets true cases only (ruling). Complement probes (`complement_probes`, bases with a
window or threshold): false cases one minute, one day or one notice minute from a true one
("one minute before a window opens, one minute after it closes, notice one minute short"; a
day for a weekday or date-range limit), owed (at least `MIN_CASES`) only by a basis whose
intended condition is false somewhere, i.e. depends on its windows or thresholds.
`test_binding` runs them all; any mismatch, too few cases or an exception is a failure.

**The grid** (`grid_equivalence`, criterion B1): every 15 minutes of 2026-08-10…16 and of
2026-09-07…13 (Labor Day week), × `notice_grid(ref.notice_hours)` (none for a missing notice)
× each vessel class and unknown × conflict true and false; at each point the draw's bindings
(`decide_bindings`: the gate's steps 1-6 of §12.6, implemented once in `decide.decide_values`)
and the reference must give the same outcome, denying sections and missing facts. An
exception is a mismatch. Missing facts follow `decide`'s rule: the absent facts of the
Unknown forbids and of the Unknown overriding bases listing an unsure forbid (a True forbid
stays True whatever its absent facts), then of the Unknown bases.

**Statuses** (`mark_tested`): it also checks what only the whole draw shows
(`_draw_problems`): § 117.31(b) must override every forbid of its draw and nothing else (P32),
and each "all other times" condition (a period-less rule's, § 117.5's) must leave out exactly
the union of the periods the draw's bindings record (P46). A draw's bindings pass or fail
together. A failing binding is
`rejected`, and so are the others of its draw ("blocked"), since a partial set changes the
draw's decision (a dropped forbid allows what the rule forbids; dropped overrides dangle); the
gate then escalates the draw's calls for lack of a binding. Passing bindings become `tested`.
Every new status is validated through `Binding.model_validate`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import product
from typing import Any

from adr_store.bindings.compile import ALL_TIMES, EMERGENCY, GENERAL_DUTY
from adr_store.bindings.decide import decide_values, section_of
from adr_store.bindings.decide import prepared as _fast
from adr_store.bindings.dsl import DAYS, Binding, Tri, Window, evaluate
from adr_store.bindings.facts import (
    EMERGENCY_CLASSES,
    VESSEL_CLASSES,
    derive_facts,
    federal_holidays,
)
from adr_store.bindings.reference import RefDecision, RefDraw, decide_facts, ref_in_window
from adr_store.units.ecfr import normalise_rule_id

__all__ = ["GRID_STEP", "GRID_WEEKS", "MIN_CASES", "boundary_cases", "complement_probes",
           "decide_bindings", "grid_equivalence", "grid_size", "grid_times",
           "has_threshold_or_window", "mark_tested", "notice_grid", "section_of",
           "test_binding"]

GRID_STEP = 15
MIN_CASES = 4
GRID_WEEKS = (date(2026, 8, 10), date(2026, 9, 7))      # a working week; Labor Day week
VESSELS = (*VESSEL_CLASSES, None)
CONFLICTS = (True, False)
NOTICE = "notice_minutes"
TESTED, REJECTED = "tested", "rejected"
MAX_MESSAGES = 20
# "just outside": one minute, or one day (a weekday or date-range limit), from a true case
_STEPS = (timedelta(minutes=-1), timedelta(minutes=1), timedelta(days=-1), timedelta(days=1))
_PERIOD_KEY = re.compile(r"periods\[(\d+)\]\.(\w+)")
_WRONG_TYPE = {"open_at": ("2026-08-12", 0), NOTICE: ("240", True),
               "vessel_class": (1, True), "local_procedure_conflict": ("false", 0)}


# -- the grid ------------------------------------------------------------------------------------

def notice_grid(n_hours: int | None) -> tuple[int | None, ...]:
    """The notice values of the B1 grid, in minutes: none (missing), 0, N h − 1 h, N h − 1 min,
    N h, N h + 1 h and 48 h for a threshold of N hours; none, 0 and 48 h without one (builder
    note 14). A value met twice is listed once. ValueError for a threshold that is not a
    positive whole number of hours."""
    if n_hours is None:
        return (None, 0, 2880)
    if type(n_hours) is not int or n_hours < 1:
        raise ValueError(f"a notice threshold is a positive whole number of hours, not "
                         f"{n_hours!r}")
    n = 60 * n_hours
    return tuple(dict.fromkeys((None, 0, n - 60, n - 1, n, n + 60, 2880)))


def grid_times() -> list[datetime]:
    """Every `GRID_STEP` minutes of the two grid weeks, in order."""
    return [datetime.combine(start + timedelta(days=d), datetime.min.time())
            + timedelta(minutes=m)
            for start in GRID_WEEKS for d in range(7) for m in range(0, 1440, GRID_STEP)]


def grid_size(ref: RefDraw) -> int:
    """The number of B1 grid points of a reference draw."""
    return len(grid_times()) * len(notice_grid(ref.notice_hours)) * len(VESSELS) * len(CONFLICTS)


def _record(at: datetime, notice: int | None, vessel: str | None, conflict: bool | None
            ) -> dict:
    out: dict = {}
    if notice is not None:
        out["notice_received_at"] = {"value": (at - timedelta(minutes=notice)).isoformat(),
                                     "source": "record"}
    if vessel is not None:
        out["vessel_class"] = {"value": vessel, "source": "record"}
    if conflict is not None:
        out["local_procedure_conflict"] = {"value": conflict, "source": "record"}
    return out


# -- the gate's decision over a draw's bindings (§12.6 steps 1-6) ---------------------------------

def _decide(bindings: list[Binding], values: dict[str, Tri], facts: dict) -> RefDecision:
    """`decide.decide_values` (the gate's one decision) in the reference's terms."""
    d = decide_values(bindings, values, facts)
    return RefDecision(d.outcome, d.sections, d.missing)


def decide_bindings(bindings: list[Binding], facts: dict) -> RefDecision:
    """The gate's decision for `schedule_opening` over one draw's bindings (§12.6 steps 1-6,
    `decide.decide_draw`, the one implementation the gate and `check_rules` use), as a
    `RefDecision`. Exceptions propagate (the caller fails closed)."""
    return _decide(bindings, {b.binding_id: evaluate(b.when, facts) for b in bindings}, facts)


def _as_dict(d: RefDecision | None, err: Exception | None) -> dict:
    if err is not None:
        return {"error": f"{type(err).__name__}: {err}"}
    return {"outcome": d.outcome, "denying_sections": sorted(d.denying_sections),
            "missing": list(d.missing)}


def grid_equivalence(draw_bindings: list[Binding], ref: RefDraw) -> list[dict]:
    """The B1 grid points (module text) where the draw's bindings and the reference decide
    differently, in grid order; [] when they agree everywhere. ValueError when the bindings
    target more than one draw."""
    targets = {json.dumps(b.target, sort_keys=True) for b in draw_bindings}
    if len(targets) > 1:
        raise ValueError("grid_equivalence takes the bindings of one draw")
    fast = [(b, _fast(b.when)) for b in draw_bindings]
    cache: dict[tuple, Tri] = {}
    mismatches = []
    for at in grid_times():
        for notice in notice_grid(ref.notice_hours):
            base = derive_facts(at, _record(at, notice, None, None))
            for vessel, conflict in product(VESSELS, CONFLICTS):
                # as `derive_facts` with the class and conflict in the record (both valid)
                facts = {**base, "local_procedure_conflict": conflict}
                if vessel is not None:
                    facts["vessel_class"] = vessel
                got, err = None, None
                try:
                    values = {}
                    for b, when in fast:
                        key = (b.binding_id, *(facts.get(f) for f in b.required_facts))
                        if key not in cache:
                            cache[key] = evaluate(when, facts)
                        values[b.binding_id] = cache[key]
                    got = _decide(draw_bindings, values, facts)
                except Exception as e:  # noqa: BLE001 - any failure is a mismatch (P15)
                    err = e
                want = decide_facts(ref, facts)
                if err is not None or got != want:
                    mismatches.append({"open_at": facts["open_at"], NOTICE: notice,
                                       "vessel_class": vessel,
                                       "local_procedure_conflict": conflict,
                                       "bindings": _as_dict(got, err),
                                       "reference": _as_dict(want, None)})
    return mismatches


# -- the intended condition ------------------------------------------------------------------------

@dataclass(frozen=True)
class _Part:
    """One way the intended condition holds: inside one of `inside` (None: anywhere), outside
    all of `outside` (None: no such limit), notice `op` minutes, an emergency override."""

    inside: tuple[Window, ...] | None = None
    outside: tuple[Window, ...] | None = None
    notice: tuple[str, int] | None = None
    emergency: bool = False


@dataclass(frozen=True)
class _Shape:
    kind: str                          # window, elsewhere, const, emergency, other
    windows: tuple[Window, ...] = ()
    cmp: tuple[str, int] | None = None
    value: Any = None


def _win(e: dict) -> Window | None:
    if set(e) == {"in_window", "window"} and e["in_window"] == {"fact": "open_at"}:
        return e["window"] if isinstance(e["window"], Window) else Window.model_validate(
            e["window"])
    return None


def _windows_of(e: dict) -> tuple[Window, ...] | None:
    w = _win(e)
    if w is not None:
        return (w,)
    if set(e) == {"or"} and all(_win(x) is not None for x in e["or"]):
        return tuple(_win(x) for x in e["or"])
    return None


def _shape(e: dict) -> _Shape:
    w = _win(e)
    if w is not None:
        return _Shape("window", (w,))
    if set(e) == {"not"} and isinstance(e["not"], dict) and _windows_of(e["not"]) is not None:
        return _Shape("elsewhere", _windows_of(e["not"]))
    if set(e) == {"const"}:
        return _Shape("const", value=e["const"])
    if set(e) == {"and"} and len(e["and"]) == 2:
        first, second = e["and"]
        if isinstance(second, dict) and set(second) == {"cmp"} and second["cmp"][0] == NOTICE:
            inner = _shape(first)
            if inner.kind in ("window", "elsewhere"):
                return _Shape(inner.kind, inner.windows, (second["cmp"][1], second["cmp"][2]))
        if first == {"in": ["vessel_class", list(first.get("in", [None, []])[1])]} and \
                second == {"not": {"eq": ["local_procedure_conflict", True]}}:
            return _Shape("emergency", value=tuple(first["in"][1]))
    return _Shape("other")


def _parts_of(when: dict) -> list[_Shape]:
    return [_shape(x) for x in (when["or"] if set(when) == {"or"} else [when])]


def _under(rule_id: str, ref: str) -> bool:
    r = normalise_rule_id(rule_id)
    return r is not None and (r == ref or r.startswith(ref + "("))


def _prov_value(prov: dict, key: str) -> Any:
    entry = prov.get(key)
    return entry.get("value") if isinstance(entry, dict) else None


def _prov_window(vals: dict) -> Window | None:
    start, end = vals.get("start"), vals.get("end")
    if start is None and end is None:
        start, end = 0, 1440
    if start is None or end is None:
        return None
    try:
        return Window(start=start, end=end, days=tuple(vals.get("days") or DAYS),
                      except_federal_holidays=vals.get("except_federal_holidays") is True,
                      date_from=vals.get("date_from"), date_to=vals.get("date_to"))
    except (ValueError, TypeError):
        return None


def _periods(b: Binding) -> dict[int, dict]:
    """The binding's recorded periods: index -> {field: value}."""
    out: dict[int, dict] = {}
    for key, entry in b.params_prov.items():
        m = _PERIOD_KEY.fullmatch(key)
        if m and isinstance(entry, dict):
            out.setdefault(int(m[1]), {})[m[2]] = entry.get("value")
    return out


def _complements(b: Binding, own: set[Window]) -> list[tuple[tuple[Window, ...], tuple | None]]:
    """The "all other times" conditions of the binding's `when`: (the windows left out, the
    notice comparison or None); an all-times window is one leaving out nothing when the
    binding has no all-times period of its own."""
    out = []
    for s in _parts_of(b.when):
        if s.kind == "elsewhere":
            out.append((s.windows, s.cmp))
        elif s.kind == "window" and s.windows == (ALL_TIMES,) and ALL_TIMES not in own:
            out.append(((), s.cmp))
    return out


def _intended(b: Binding) -> tuple[list[_Part], list[str], list[_Shape]]:
    """(the intended condition's parts, the problems found, the `when`'s shapes) (module
    text)."""
    shapes = _parts_of(b.when)
    problems = [f"a condition the compiler does not write: {json.dumps(b.when, default=str)}"
                ] if any(s.kind == "other" for s in shapes) else []
    if _under(b.rule_id, EMERGENCY):
        if b.effect != "basis":
            problems.append("§ 117.31(b) binds as a basis")
        return [_Part(emergency=True)], problems, shapes
    periods = _periods(b)
    windows: dict[int, Window] = {}
    for i, vals in sorted(periods.items()):
        w = _prov_window(vals)
        if w is None:
            problems.append(f"periods[{i}]: its parameters give no window")
        else:
            windows[i] = w
    if _under(b.rule_id, GENERAL_DUTY):
        if b.effect != "basis":
            problems.append("§ 117.5 binds as a basis")
        ws = tuple(windows.values())
        return [_Part(outside=ws) if ws else _Part()], problems, shapes
    n = _prov_value(b.params_prov, "notice_hours")
    basis = _prov_value(b.params_prov, "opening_basis")
    op = ">=" if b.effect == "basis" else "<"
    parts: list[_Part] = []
    for i, w in windows.items():
        effect = periods[i].get("effect")
        if (effect, b.effect) in (("need_not_open", "forbid"), ("on_signal", "basis")) or (
                effect == "notice_required" and n == 0 and b.effect == "basis"):
            parts.append(_Part(inside=(w,)))
        elif effect == "notice_required" and isinstance(n, int) and n > 0:
            parts.append(_Part(inside=(w,), notice=(op, 60 * n)))
        else:
            problems.append(f"periods[{i}] ({effect}) gives no {b.effect} part")
    # P46: a period-less notice or on-signal basis, at all other times
    has_notice_period = any(p.get("effect") == "notice_required" for p in periods.values())
    pl_notice = n is not None and (basis == "advance_notice" or not has_notice_period)
    pl_basis = basis == "on_signal"
    own = set(windows.values())
    elsewhere = _complements(b, own)
    for ws, cmp in elsewhere:
        if not own <= set(ws):
            problems.append("its all-other-times condition does not leave out its own periods")
        if cmp is not None:
            if not (pl_notice and isinstance(n, int) and n > 0):
                problems.append("an all-other-times notice condition with no period-less "
                                "notice")
                continue
            parts.append(_Part(outside=ws, notice=(op, 60 * n)))
        elif b.effect == "basis" and (pl_basis or (pl_notice and n == 0)):
            parts.append(_Part(outside=ws))
        else:
            problems.append(f"an all-other-times condition with no period-less {b.effect}")
    if pl_notice and isinstance(n, int) and n > 0 and not any(c for _, c in elsewhere):
        problems.append("its period-less notice is not written for all other times")
    if b.effect == "basis" and (pl_basis and n is None or pl_notice and n == 0) and \
            not any(c is None for _, c in elsewhere):
        problems.append("its period-less opening basis is not written for all other times")
    return parts, problems, shapes


def _and3(vals: list[str]) -> str:
    return "F" if "F" in vals else "U" if "U" in vals else "T"


def _or3(vals: list[str]) -> str:
    return "T" if "T" in vals else "U" if "U" in vals else "F"


def _value(parts: list[_Part], at: datetime, notice: int | None, vessel: str | None,
           conflict: bool | None, unknown: frozenset[str] = frozenset()) -> str:
    """The intended condition's strong Kleene value ("T", "F", "U") with the facts in `unknown`
    (or None) unknown; windows judged by the reference's own `ref_in_window` (P44)."""
    def b(x: bool) -> str:
        return "T" if x else "F"

    minute, day = at.hour * 60 + at.minute, at.date()
    no_time = "open_at" in unknown
    vals = []
    for p in parts:
        conds = []
        if p.inside is not None:
            conds.append("U" if no_time else b(any(ref_in_window(w, minute, day)
                                                   for w in p.inside)))
        if p.outside is not None:
            conds.append("U" if no_time else b(not any(ref_in_window(w, minute, day)
                                                       for w in p.outside)))
        if p.notice is not None:
            op, k = p.notice
            conds.append("U" if NOTICE in unknown or notice is None else
                         b(notice >= k if op == ">=" else notice < k))
        if p.emergency:
            conds.append("U" if "vessel_class" in unknown or vessel is None else
                         b(vessel in EMERGENCY_CLASSES))
            conds.append("U" if "local_procedure_conflict" in unknown or conflict is None else
                         b(conflict is not True))
        vals.append(_and3(conds))
    return _or3(vals)


def _holds(parts: list[_Part], at: datetime, notice: int | None, vessel: str | None,
           conflict: bool | None) -> bool:
    return _value(parts, at, notice, vessel, conflict) == "T"


# -- cases -----------------------------------------------------------------------------------------

def _admits(w: Window, d: date) -> bool:
    return ref_in_window(w, w.start, d)


def _grid_days() -> list[date]:
    return [start + timedelta(days=k) for start in GRID_WEEKS for k in range(7)]


def _bound_dates(md: str) -> list[date]:
    """The month-day `md` in years that put it on every weekday at least twice: 2026-2040, or
    14 leap years for 29 February."""
    years = range(2028, 2084, 4) if md == "02-29" else range(2026, 2041)
    return [date(y, int(md[:2]), int(md[3:])) for y in years]


def _pool(ws: list[Window]) -> list[date]:
    """Candidate days: seven weeks around the grid weeks, the federal holidays of 2026-2027,
    and the days around each date bound of the windows, in many years."""
    start = GRID_WEEKS[0] - timedelta(days=7)
    days = {start + timedelta(days=k) for k in range(49)} | set(_grid_days())
    for y in (2026, 2027):
        days |= set(federal_holidays(y))
    for w in ws:
        for md in (w.date_from, w.date_to):
            if md is not None:
                days |= {b + timedelta(days=k) for b in _bound_dates(md) for k in range(-8, 9)}
    return sorted(days)


def _days_for(w: Window, pool: list[date]) -> list[date]:
    """Two days `w` admits and one admitted day of each weekday it lists (of those its dates
    admit), then the days it shuts out by each limit it has: two with a weekday it lacks, two
    federal holidays it excepts, and the day nearest each end of its date range."""
    admitted = [d for d in pool if _admits(w, d)]
    out = admitted[:2] + [d for wd in w.days
                          for d in [next((x for x in admitted if DAYS[x.weekday()] == wd), None)]
                          if d is not None]
    relax = {"days": {"days": DAYS}, "holidays": {"except_federal_holidays": False},
             "dates": {"date_from": None, "date_to": None}}
    for limit, update in relax.items():
        relaxed = w.model_copy(update=update)
        if relaxed == w:
            continue
        found = [d for d in pool if _admits(relaxed, d) and not _admits(w, d)]
        if limit == "dates":
            for md in (w.date_from, w.date_to):
                near = [(min(abs((d - b).days) for b in _bound_dates(md)), d) for d in found]
                out += [d for _, d in sorted(near)[:1]]
        else:
            out += found[:2]
    return list(dict.fromkeys(out))


def _edge_minutes(w: Window) -> set[int]:
    return {m for m in (w.start - 1, w.start, w.end - 1, w.end) if 0 <= m < 1440}


@dataclass(frozen=True)
class _Cases:
    parts: list[_Part]
    problems: list[str]
    true: list[dict]
    false: list[dict]
    probes: list[dict]
    need_probes: bool


def _facts(at: datetime, notice: int | None, vessel: str | None, conflict: bool | None
           ) -> dict:
    return derive_facts(at, _record(at, notice, vessel, conflict))


def _case(at, notice, vessel, conflict, expect: str) -> dict:
    return {"facts": _facts(at, notice, vessel, conflict), "expect": expect}


def _variants(case: dict, fact: str, expect: str) -> list[dict]:
    """`case` with `fact` dropped, nulled and given each wrong type, all expecting `expect`
    (the intended condition's Kleene value with `fact` unknown)."""
    base = {k: v for k, v in case["facts"].items() if k != fact}
    return [{"facts": f, "expect": expect} for f in
            [base, {**base, fact: None},
             *({**base, fact: v} for v in _WRONG_TYPE.get(fact, ("?", 1.5)))]]


def _cases(b: Binding) -> _Cases:
    parts, problems, shapes = _intended(b)
    windows = list(dict.fromkeys(
        [w for p in parts for w in (p.inside or ()) + (p.outside or ())]
        + [w for s in shapes for w in s.windows]))
    windows = [w for w in windows if w != ALL_TIMES]
    thresholds = {p.notice[1] for p in parts if p.notice} | {
        s.cmp[1] for s in shapes if s.cmp and isinstance(s.cmp[1], int)}
    reads_time = "open_at" in b.required_facts or any(p.inside or p.outside for p in parts)
    reads_notice = NOTICE in b.required_facts or bool(thresholds)
    reads_vessel = any(p.emergency for p in parts) or "vessel_class" in b.required_facts
    pool = _pool(windows)
    # every candidate day with every window's edge minutes: where windows meet, the edges of
    # one fall on the days of another
    days = dict.fromkeys(day for w in windows for d in _days_for(w, pool)
                         for day in (d - timedelta(days=1), d, d + timedelta(days=1)))
    minutes = sorted(set().union(*(_edge_minutes(w) for w in windows)))
    points: list[datetime] = [datetime.combine(day, datetime.min.time()) + timedelta(minutes=m)
                              for day in days for m in minutes]
    if reads_time or not windows:      # far points: midnight and noon of the working week
        points += [datetime.combine(d, datetime.min.time()) + timedelta(minutes=m)
                   for d in _grid_days()[:7] for m in (0, 720)]
    notices: list[int | None] = sorted({0, 2880} | {k for t in thresholds
                                                    for k in (t - 1, t) if k >= 0}) \
        if reads_notice else [None]
    people = list(product(VESSEL_CLASSES, (False, True))) if reads_vessel else [
        ("commercial", False)]
    true: dict[str, dict] = {}
    false: dict[str, dict] = {}
    probes: dict[str, dict] = {}
    raw: dict[str, tuple] = {}
    for at in dict.fromkeys(points):
        for notice in notices:
            for vessel, conflict in people:
                holds = _holds(parts, at, notice, vessel, conflict)
                case = _case(at, notice, vessel, conflict, "T" if holds else "F")
                key = json.dumps(case["facts"], sort_keys=True)
                (true if holds else false)[key] = case
                raw[key] = (at, notice, vessel, conflict)
                if not holds and b.effect == "basis" and (
                        any(_holds(parts, at + step, notice, vessel, conflict) for step in _STEPS)
                        or (notice is not None
                            and _holds(parts, at, notice + 1, vessel, conflict))):
                    probes[key] = case
    # every fact the binding reads, unknown in two true cases: the expectation is the intended
    # condition's Kleene value without it (an `or` of T and U is T)
    # (from the first two true cases, and the first in which each part holds)
    seeds = list(true)[:2] + [next((k for k in true if _value([p], *raw[k]) == "T"), None)
                              for p in parts]
    variants = [v for key in dict.fromkeys(k for k in seeds if k is not None)
                for f in b.required_facts
                for v in _variants(true[key], f, _value(parts, *raw[key],
                                                        unknown=frozenset({f})))]
    # probes are owed only where the condition depends on its windows or thresholds at all
    need = b.effect == "basis" and has_threshold_or_window(b) and bool(false)
    return _Cases(parts, problems, [*true.values(), *(v for v in variants if v["expect"] == "T")],
                  [*false.values(), *(v for v in variants if v["expect"] != "T")],
                  list(probes.values()) if has_threshold_or_window(b) else [], need)


def has_threshold_or_window(b: Binding) -> bool:
    """Whether the binding's condition reads a notice threshold or a window short of all
    times."""
    def walk(e: Any) -> bool:
        if isinstance(e, list):
            return any(walk(x) for x in e)
        if not isinstance(e, dict):
            return False
        if "cmp" in e and e["cmp"][0] == NOTICE:
            return True
        w = _win(e)
        if w is not None:
            return w != ALL_TIMES
        return any(walk(v) for k, v in e.items() if k != "window")
    return walk(b.when)


def boundary_cases(b: Binding) -> tuple[list[dict], list[dict]]:
    """(cases where the binding must be true, cases where it must not be): each
    `{"facts", "expect"}` with `expect` "T", or "F" / "U" (module text)."""
    c = _cases(b)
    return c.true, c.false


def complement_probes(b: Binding) -> list[dict]:
    """False cases just outside each window or threshold of a basis (module text); [] for a
    forbid or a basis with neither."""
    if b.effect != "basis":
        return []
    return _cases(b).probes


def _test(b: Binding) -> tuple[_Cases | None, list[str]]:
    failures: list[str] = []
    c = None
    try:
        c = _cases(b)
        failures += [f"parameters: {p}" for p in c.problems]
        if b.required_facts and (len(c.true) < MIN_CASES or len(c.false) < MIN_CASES):
            failures.append(f"fewer than {MIN_CASES} cases each way: {len(c.true)} true, "
                            f"{len(c.false)} false")
        if c.need_probes and len(c.probes) < MIN_CASES:
            failures.append(f"fewer than {MIN_CASES} complement probes: {len(c.probes)}")
        when = _fast(b.when)
        for case in [*c.true, *c.false, *c.probes]:
            got = evaluate(when, case["facts"])
            if got.value != case["expect"]:
                f = case["facts"]
                failures.append(f"expected {case['expect']}, got {got.value} at "
                                + ", ".join(f"{k}={f[k]!r}" for k in sorted(f)
                                            if k in (*b.required_facts, "weekday",
                                                     "federal_holiday")))
    except Exception as err:  # noqa: BLE001 - an exception is a failure, never a pass
        failures.append(f"error: {type(err).__name__}: {err}")
    out = list(dict.fromkeys(failures))
    if len(out) > MAX_MESSAGES:
        out = [*out[:MAX_MESSAGES], f"and {len(out) - MAX_MESSAGES} more"]
    return c, out


def test_binding(b: Binding) -> list[str]:
    """The failures of the binding's tests (module text); [] when it passes."""
    return _test(b)[1]


test_binding.__test__ = False       # not a pytest test, whatever imports it


# -- statuses --------------------------------------------------------------------------------------

def _with(b: Binding, **update) -> Binding:
    """`b` with `update`, validated as a new binding (statuses go through validation)."""
    return Binding.model_validate({**b.model_dump(), **update})


def _draw_key(b: Binding) -> str:
    return json.dumps([b.doc_id, b.target], sort_keys=True)


def _draw_problems(draw: list[Binding]) -> dict[str, list[str]]:
    """Problems only the whole draw shows, by binding id: a § 117.31(b) basis must override
    every forbid of its draw and nothing else (P32); every "all other times" condition (a
    period-less rule's, § 117.5's) must leave out exactly the draw's periods, the union of the
    periods its bindings record (P46). § 117.5 written as a constant needs a draw with no
    period."""
    forbids = {b.binding_id for b in draw if b.effect == "forbid"}
    periods: dict[int, Window | None] = {}
    for b in draw:
        for i, vals in _periods(b).items():
            periods.setdefault(i, _prov_window(vals))
    every = {w for w in periods.values() if w is not None}
    out: dict[str, list[str]] = {}
    for b in draw:
        found = []
        if _under(b.rule_id, EMERGENCY):
            missing, extra = forbids - set(b.overrides), set(b.overrides) - forbids
            if missing:
                found.append("§ 117.31(b) must override every forbid of its draw (P32); it "
                             f"leaves out {', '.join(sorted(x[:12] for x in missing))}")
            if extra:
                found.append(f"§ 117.31(b) overrides {', '.join(sorted(x[:12] for x in extra))},"
                             " which is no forbid of the draw")
            out[b.binding_id] = found
            continue
        own = {w for w in (_prov_window(v) for v in _periods(b).values()) if w is not None}
        for ws, _ in _complements(b, own):
            if set(ws) != every:
                found.append("its all-other-times condition is not the negation of the draw's "
                             f"{len(every)} period(s) (P46)")
        if _under(b.rule_id, GENERAL_DUTY) and b.when == {"const": True} and every:
            found.append("§ 117.5 at all times in a draw with periods")
        out[b.binding_id] = found
    return out


def mark_tested(bindings: list[Binding]) -> list[Binding]:
    """The bindings, in order, each `tested` with its test summary, or `rejected` with its
    failures; a draw with a failing binding is rejected whole (module text). ValueError for a
    binding that is not `proposed`."""
    for b in bindings:
        if b.status != "proposed":
            raise ValueError(f"only proposed bindings are tested; {b.binding_id[:12]} is "
                             f"{b.status}")
    draws: dict[str, list[Binding]] = {}
    for b in bindings:
        draws.setdefault(_draw_key(b), []).append(b)
    whole: dict[tuple[str, str], list[str]] = {}
    for key, draw in draws.items():
        try:
            for bid, found in _draw_problems(draw).items():
                whole[(key, bid)] = found
        except Exception as err:  # noqa: BLE001 - an exception is a failure, never a pass
            for b in draw:
                whole[(key, b.binding_id)] = [f"error: {type(err).__name__}: {err}"]
    results = []
    for b in bindings:
        c, failures = _test(b)
        failures = [*failures, *whole.get((_draw_key(b), b.binding_id), [])]
        counts = (len(c.true), len(c.false), len(c.probes)) if c is not None else (0, 0, 0)
        results.append((*counts, failures))
    failing: dict[str, list[str]] = {}
    for b, result in zip(bindings, results, strict=True):
        if result[3]:
            failing.setdefault(_draw_key(b), []).append(b.binding_id)
    out = []
    for b, (n_true, n_false, n_probes, failures) in zip(bindings, results, strict=True):
        bad = failing.get(_draw_key(b), [])
        if not failures and bad:
            failures = [f"blocked: binding {', '.join(x[:12] for x in bad)} of the draw failed"]
        summary = {"kind": "boundary", "true": n_true, "false": n_false, "probes": n_probes,
                   "failures": failures}
        out.append(_with(b, status=REJECTED if bad else TESTED, tests=[summary]))
    return out
