"""Solver analysis of a draw's bindings (Phase 4 spec §12.4, P11, P32, P44; Task 16), with Z3
(`z3-solver==5.3.3.0`, the `[analysis]` extra). Only `adr bindings build` imports this module;
the gate never does.

**The encoding.** Every fact is known (the analysis looks at the rules, not at requests):
`minute` 0..1439; `weekday` 0..6 (Monday 0); `holiday`, a free Bool; `day_of_year` 1..366 on a
leap-year calendar of month-days ("02-29" is day 60, "12-31" day 366); `notice_minutes` >= 0;
`vessel_class` one of `VESSEL_CLASSES` (by index); `local_procedure_conflict` a Bool. Weekday,
holiday and date are independent of each other, so holidays are free exactly as `covers_all`
treats them: any day of any weekday may be a federal holiday or not. A window that crosses
midnight belongs to the night that starts on a listed day (P44): its minutes in [start, 1440)
are judged on the day's weekday, holiday and date; its minutes in [0, end) on the previous
day's: `previous weekday` = (weekday + 6) mod 7, a second free Bool `previous_day_holiday`, and
`previous_day_of_year`, the day before on the calendar (1 January follows 31 December, and
1 March follows 28 or 29 February: both are allowed). Expressions follow their two-valued
reading: `and`, `or`, `not`; `cmp` on an integer fact; `eq` and `in` on the vessel class, a
bool fact, the weekday or the month-day; `known` is True; `const`; `in_window`. Any other fact
is a fresh variable of its comparand's type.

**Per draw** (`analyse_draw`), the bindings given:
- **conflicts**: an overriding basis and a forbid of the draw that its `overrides` does not
  list, satisfiable together (an emergency would still be denied); an `overrides` entry that
  names no forbid of the draw; a cycle of overrides. A listed forbid is a declared override,
  and a plain basis True with a forbid is the decision rule's (the forbid wins): neither is a
  conflict.
- **vacuous** (binding ids): a forbid or basis that can never fire, or a forbid that always
  fires.
- **redundant** (binding ids, reported and kept): a binding that is not vacuous and whose
  condition implies the disjunction of the others of its effect with the same overrides.
- **gaps**: where no basis holds and no forbid fires, the gate escalates. One witness, the
  least point of the gap region in the order day of year, weekday, minute, notice, vessel
  class, conflict, holiday, previous-day holiday, previous day (Z3 `Optimize`, lexicographic),
  so the output is deterministic.

`mark_analysed` turns tested bindings `analysed`, recording what the analysis found of each;
a draw with a vacuous binding or a conflict is `rejected` whole (the others "blocked": a partial
set would change the draw's decision, and P32 lets a missing override entry block the set).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import z3

from adr_store.bindings.dsl import DAYS, Binding, Window
from adr_store.bindings.facts import VESSEL_CLASSES

__all__ = ["Analysis", "analyse_draw", "mark_analysed"]

_MONTH_DAYS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
MONTH_DAYS = [f"{m:02d}-{d:02d}" for m, n in enumerate(_MONTH_DAYS, 1) for d in range(1, n + 1)]
DAY_OF_YEAR = {md: i for i, md in enumerate(MONTH_DAYS, 1)}
MARCH_1, FEB_28 = DAY_OF_YEAR["03-01"], DAY_OF_YEAR["02-28"]


@dataclass(frozen=True)
class Analysis:
    conflicts: list[str]
    vacuous: list[str]
    redundant: list[str]
    gaps: list[dict]


class _Vars:
    def __init__(self) -> None:
        self.minute = z3.Int("minute")
        self.weekday = z3.Int("weekday")
        self.holiday = z3.Bool("holiday")
        self.doy = z3.Int("day_of_year")
        self.prev_holiday = z3.Bool("previous_day_holiday")
        self.prev_doy = z3.Int("previous_day_of_year")
        self.notice = z3.Int("notice_minutes")
        self.vessel = z3.Int("vessel_class")
        self.conflict = z3.Bool("local_procedure_conflict")
        self.extra: dict[str, Any] = {}

    def domain(self) -> list:
        return [0 <= self.minute, self.minute <= 1439, 0 <= self.weekday, self.weekday <= 6,
                1 <= self.doy, self.doy <= 366,
                z3.Or(self.prev_doy == z3.If(self.doy == 1, 366, self.doy - 1),
                      z3.And(self.doy == MARCH_1, self.prev_doy == FEB_28)),
                self.notice >= 0, 0 <= self.vessel, self.vessel < len(VESSEL_CLASSES)]

    def fact(self, name: str, like: Any):
        """The variable of an integer or bool fact (a fresh one for facts not modelled)."""
        known = {"minute": self.minute, "notice_minutes": self.notice,
                 "federal_holiday": self.holiday, "local_procedure_conflict": self.conflict}
        if name in known:
            return known[name]
        if name not in self.extra:
            self.extra[name] = (z3.Bool(name) if isinstance(like, bool) else
                                z3.Int(name) if isinstance(like, int) else z3.String(name))
        return self.extra[name]


def _admits(w: Window, weekday, holiday, doy) -> Any:
    cond = [z3.Or([weekday == DAYS.index(d) for d in w.days])]
    if w.except_federal_holidays:
        cond.append(z3.Not(holiday))
    if w.date_from is not None and w.date_to is not None:
        a, b = DAY_OF_YEAR[w.date_from], DAY_OF_YEAR[w.date_to]
        cond.append(z3.And(a <= doy, doy <= b) if a <= b else z3.Or(doy >= a, doy <= b))
    return z3.And(cond)


def _window(w: Window, v: _Vars) -> Any:
    m = v.minute
    if w.start < w.end:
        return z3.And(w.start <= m, m < w.end, _admits(w, v.weekday, v.holiday, v.doy))
    return z3.Or(z3.And(m >= w.start, _admits(w, v.weekday, v.holiday, v.doy)),
                 z3.And(m < w.end, _admits(w, (v.weekday + 6) % 7, v.prev_holiday, v.prev_doy)))


def _eq(fact: str, value: Any, v: _Vars) -> Any:
    if fact == "vessel_class":
        return v.vessel == VESSEL_CLASSES.index(value) if value in VESSEL_CLASSES else \
            z3.BoolVal(False)
    if fact == "weekday" and isinstance(value, str):
        return v.weekday == DAYS.index(value) if value in DAYS else z3.BoolVal(False)
    if fact == "month_day" and isinstance(value, str):
        return v.doy == DAY_OF_YEAR[value] if value in DAY_OF_YEAR else z3.BoolVal(False)
    var = v.fact(fact, value)
    return var == (z3.BoolVal(value) if isinstance(value, bool) else
                   z3.StringVal(value) if isinstance(value, str) else value)


def _encode(e: dict, v: _Vars) -> Any:
    op = next(k for k in e if k != "window")
    arg = e[op]
    if op == "and":
        return z3.And([_encode(x, v) for x in arg])
    if op == "or":
        return z3.Or([_encode(x, v) for x in arg])
    if op == "not":
        return z3.Not(_encode(arg, v))
    if op == "cmp":
        fact, o, c = arg
        x = v.fact(fact, 0)
        return {"<": x < c, "<=": x <= c, ">": x > c, ">=": x >= c, "==": x == c,
                "!=": x != c}[o]
    if op == "eq":
        return _eq(arg[0], arg[1], v)
    if op == "in":
        return z3.Or([_eq(arg[0], x, v) for x in arg[1]])
    if op == "known":
        return z3.BoolVal(True)
    if op == "const":
        return z3.BoolVal(arg)
    w = e["window"] if isinstance(e["window"], Window) else Window.model_validate(e["window"])
    return _window(w, v)


def _any(fs: list) -> Any:
    return z3.Or(fs) if fs else z3.BoolVal(False)


def _cycles(bindings: list[Binding]) -> list[list[str]]:
    """The cycles of the overrides graph, each once, starting at its least id."""
    ids = {b.binding_id for b in bindings}
    edges = {b.binding_id: sorted(x for x in set(b.overrides) if x in ids) for b in bindings}
    found: set[tuple[str, ...]] = set()

    def walk(path: list[str]) -> None:
        for nxt in edges[path[-1]]:
            if nxt == path[0]:
                found.add(tuple(path))
            elif nxt not in path and nxt > path[0]:
                walk([*path, nxt])

    for start in sorted(ids):
        walk([start])
    return [list(c) for c in sorted(found)]


def _witness(model, v: _Vars) -> dict:
    def val(x) -> Any:
        r = model.eval(x, model_completion=True)
        return z3.is_true(r) if z3.is_bool(r) else r.as_long()

    return {"month_day": MONTH_DAYS[val(v.doy) - 1], "weekday": DAYS[val(v.weekday)],
            "federal_holiday": val(v.holiday),
            "previous_month_day": MONTH_DAYS[val(v.prev_doy) - 1],
            "previous_day_holiday": val(v.prev_holiday), "minute": val(v.minute),
            "notice_minutes": val(v.notice), "vessel_class": VESSEL_CLASSES[val(v.vessel)],
            "local_procedure_conflict": val(v.conflict)}


def analyse_draw(bindings: list[Binding]) -> Analysis:
    """Conflicts, vacuity, redundancy and gaps of one draw's bindings (module text)."""
    bs = sorted(bindings, key=lambda b: b.binding_id)
    v = _Vars()
    enc = {b.binding_id: _encode(b.when, v) for b in bs}
    domain = v.domain()

    def sat(*fs) -> bool:
        s = z3.Solver()
        s.add(*domain, *fs)
        r = s.check()
        if r == z3.unknown:
            raise RuntimeError(f"z3 could not decide: {s.reason_unknown()}")
        return r == z3.sat

    forbids = [b for b in bs if b.effect == "forbid"]
    bases = [b for b in bs if b.effect == "basis"]
    forbid_ids = {b.binding_id for b in forbids}
    conflicts = []
    for o in (b for b in bases if b.overrides):
        for x in sorted(set(o.overrides) - forbid_ids):
            conflicts.append(f"{o.rule_id} basis {o.binding_id[:12]} overrides {x[:12]}, "
                             "which is no forbid of the draw")
        for f in forbids:
            if f.binding_id not in o.overrides and sat(enc[o.binding_id], enc[f.binding_id]):
                conflicts.append(f"{o.rule_id} basis {o.binding_id[:12]} does not override "
                                 f"{f.rule_id} forbid {f.binding_id[:12]}, and both can hold")
    for cycle in _cycles(bs):
        conflicts.append("overrides form a cycle: " + " -> ".join(
            x[:12] for x in [*cycle, cycle[0]]))
    vacuous = sorted(b.binding_id for b in bs if not sat(enc[b.binding_id]) or (
        b.effect == "forbid" and not sat(z3.Not(enc[b.binding_id]))))
    redundant = []
    for b in bs:
        if b.binding_id in vacuous:
            continue
        peers = [enc[p.binding_id] for p in bs if p.binding_id != b.binding_id
                 and p.effect == b.effect and set(p.overrides) == set(b.overrides)]
        if peers and not sat(enc[b.binding_id], z3.Not(_any(peers))):
            redundant.append(b.binding_id)
    gap = z3.And(z3.Not(_any([enc[b.binding_id] for b in bases])),
                 z3.Not(_any([enc[b.binding_id] for b in forbids])))
    gaps = []
    if sat(gap):
        opt = z3.Optimize()
        opt.add(*domain, gap)
        for x in (v.doy, v.weekday, v.minute, v.notice, v.vessel):
            opt.minimize(x)
        for x in (v.conflict, v.holiday, v.prev_holiday):
            opt.minimize(z3.If(x, 1, 0))
        opt.minimize(v.prev_doy)
        if opt.check() != z3.sat:
            raise RuntimeError("z3 found a gap but no least witness")
        gaps.append(_witness(opt.model(), v))
    return Analysis(sorted(conflicts), vacuous, sorted(redundant), gaps)


def _with(b: Binding, **update) -> Binding:
    return Binding.model_validate({**b.model_dump(), **update})


def mark_analysed(bindings: list[Binding], analysis: Analysis) -> list[Binding]:
    """The tested bindings of one draw, in order, `analysed` with what `analysis` found of
    each, or all `rejected` when the draw has a vacuous binding or a conflict (module text).
    ValueError for a binding that is not `tested`."""
    for b in bindings:
        if b.status != "tested":
            raise ValueError(f"only tested bindings are analysed; {b.binding_id[:12]} is "
                             f"{b.status}")
    blocked = bool(analysis.conflicts or analysis.vacuous)
    out = []
    for b in bindings:
        record = {"conflicts": list(analysis.conflicts),
                  "vacuous": b.binding_id in analysis.vacuous,
                  "redundant": b.binding_id in analysis.redundant,
                  "gaps": json.loads(json.dumps(analysis.gaps))}
        others = [x for x in analysis.vacuous if x != b.binding_id]
        if blocked and not record["vacuous"]:
            record["blocked_by"] = ["conflicts"] * bool(analysis.conflicts) + others
        out.append(_with(b, status="rejected" if blocked else "analysed", analysis=record))
    return out
