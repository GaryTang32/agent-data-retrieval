"""The binding compiler (Phase 4 spec §12.2, P14, P32, P37, P44; builder note 13; Task 15):
`adr-dsl@1` bindings from the enrichment's typed parameters, by code, one set per draw.

**Per draw** (`compile_draw`), every binding targets `{"tool": "schedule_opening",
"selector": {"section", "draw"}}` with status `proposed`:
- an `on_signal` period: `basis` when `in_window(p)`;
- a `need_not_open` window: `forbid` when `in_window(w)` (P14: the desk does not schedule an
  opening the rule does not require);
- notice N in a `notice_required` period: `basis` when `in_window(p) and notice_minutes >=
  60N`, and its complement written out, `forbid` when `in_window(p) and notice_minutes <
  60N`; a notice with no `notice_required` period, and an `on_signal` opening basis with no
  `on_signal` period, hold in the all-times window;
- § 117.5: `basis` when `not (in_window(p1) or ...)` over every window above, emitted only
  when `covers_all` finds a gap (builder note 13: else it can never fire); with no window at
  all it holds at all times;
- § 117.31(b): the overriding `basis` when `vessel_class in EMERGENCY_CLASSES and not
  local_procedure_conflict`, with `overrides` naming every `forbid` of the draw (P32). An
  unknown vessel class or conflict leaves it Unknown (P37): nothing is defaulted.

`rule_id` and `rule_version` are the `canonical_ref` and `version` of the card whose source
span holds the parameter's quote (a period's effect quote, else its first quoted field; a
period-less notice its `notice_hours` quote, a period-less basis its `opening_basis` quote);
the document is that card's. Bindings of one card and effect are one binding, their
conditions joined by `or` (one binding per identity, Task 14). Each binding records the
quotes of its parameters (`params_prov`), its `derivation` (`sentence`), and in `review` the
flags Task 17's review must surface: `sentence_qualifiers` (what the parameters' sentences
state and the parameters lack), `sentence_conditions` ("only", "unless", "notice" around a
closed window) and `auto_accepted` (parameters whose value is not in its quote).

**No bindings** for a draw with a parameter that failed checks 1-3 (`unparseable`,
`ungrounded`, `model_error`), a closed window whose quote the window grammar cannot read, a
period that is no window (one time, one end of a date range, an empty window, no effect), a
notice period or advance-notice basis with no notice hours, a quote no card holds, or a draw
closed to navigation (an always-firing forbid is vacuous, builder note 13): the draw is listed
with its problems and the gate escalates its calls.

`covers_all` is exact without a solver: `in_window` is piecewise constant between window
boundaries, so the union covers every (minute, day) when it covers every critical point:
each boundary minute and the minute before it; each weekday; the holiday flag of the day and
of the day before, both free (as the analysis treats `federal_holiday`); and every date-range
boundary day, the days around it and the leap day, with the day before (P44 judges the
minutes after midnight of a crossing window on the previous day's weekday, holiday and date).
"""

from __future__ import annotations

import json
from collections import Counter

from adr_store.bindings.dsl import (
    DAYS,
    Binding,
    Expr,
    Window,
    binding_ids,
    required_facts,
)
from adr_store.bindings.enrich import (
    FAILED,
    PERIOD_FIELDS,
    DrawParams,
    Grounded,
    Period,
    SectionEnrichment,
    _in_section,
    _section_key,
    period_window,
)
from adr_store.bindings.facts import EMERGENCY_CLASSES
from adr_store.units.ecfr import normalise_rule_id
from adr_store.units.envelope import Unit

__all__ = ["ALL_TIMES", "EMERGENCY", "GENERAL_DUTY", "TOOL", "compile_bindings",
           "compile_draw", "covers_all", "sentence"]

GENERAL_DUTY = "33 CFR 117.5"
EMERGENCY = "33 CFR 117.31(b)"
TOOL = "schedule_opening"
ALL_TIMES = Window(start=0, end=1440, days=DAYS, except_federal_holidays=False, date_from=None,
                   date_to=None)
NOTICE = "notice_minutes"
_MONTH_DAYS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_YEAR = [f"{m:02d}-{d:02d}" for m, n in enumerate(_MONTH_DAYS, 1) for d in range(1, n + 1)]


# -- covers_all ----------------------------------------------------------------------------------

def _admits(w: Window, weekday: int, md: str, holiday: bool) -> bool:
    if DAYS[weekday] not in w.days or (w.except_federal_holidays and holiday):
        return False
    if w.date_from is not None and w.date_to is not None:
        if w.date_from <= w.date_to:
            return w.date_from <= md <= w.date_to
        return not w.date_to < md < w.date_from
    return True


def _holds(w: Window, minute: int, weekday: int, md: str, holiday: bool, prev_md: str,
           prev_holiday: bool) -> bool:
    """`in_window` at an abstract day (P44: a crossing window's minutes after midnight on the
    day before)."""
    if w.start < w.end:
        return w.start <= minute < w.end and _admits(w, weekday, md, holiday)
    if minute >= w.start:
        return _admits(w, weekday, md, holiday)
    return minute < w.end and _admits(w, (weekday - 1) % 7, prev_md, prev_holiday)


def _shift(md: str, k: int) -> str:
    return _YEAR[(_YEAR.index(md) + k) % len(_YEAR)]


def _previous(md: str) -> tuple[str, ...]:
    """The month-days that can come before `md` (1 March follows 28 or 29 February)."""
    return ("02-28", "02-29") if md == "03-01" else (_shift(md, -1),)


def covers_all(windows: list[Window]) -> bool:
    """Whether the windows together hold every minute of every day (module text)."""
    ws = list(windows)
    if not ws:
        return False
    if any(w.start == 0 and w.end == 1440 and w.days == DAYS and not w.except_federal_holidays
           and w.date_from is None for w in ws):
        return True
    minutes = sorted({m % 1440 for w in ws for b in (w.start, w.end) for m in (b, b - 1)} | {0})
    crossing = any(w.start > w.end for w in ws)
    flags = (False, True) if any(w.except_federal_holidays for w in ws) else (False,)
    bounds = {b for w in ws if w.date_from is not None for b in (w.date_from, w.date_to)}
    mds = sorted({_shift(b, k) for b in bounds for k in (-1, 0, 1, 2)}
                 | ({"01-01", "02-28", "02-29", "03-01"} if bounds else {"01-01"}))
    for md in mds:
        for prev_md in _previous(md) if crossing else (md,):
            for weekday in range(7):
                for holiday in flags:
                    for prev_holiday in flags if crossing else (False,):
                        for minute in minutes:
                            if not any(_holds(w, minute, weekday, md, holiday, prev_md,
                                              prev_holiday) for w in ws):
                                return False
    return True


# -- expressions ---------------------------------------------------------------------------------

def _in(w: Window) -> Expr:
    return {"in_window": {"fact": "open_at"}, "window": w.model_dump(mode="json")}


def _any(exprs: list[Expr]) -> Expr:
    return exprs[0] if len(exprs) == 1 else {"or": exprs}


def _emergency_when() -> Expr:
    return {"and": [{"in": ["vessel_class", list(EMERGENCY_CLASSES)]},
                    {"not": {"eq": ["local_procedure_conflict", True]}}]}


# -- compile_draw --------------------------------------------------------------------------------

def _card_of(cards: list[Unit], g: Grounded) -> Unit | None:
    """The first card (in document order) whose source span holds `g`'s quote."""
    if g.start is None:
        return None
    holding = [c for c in cards if c.source_refs and c.source_refs[0].start <= g.start
               and g.end <= c.source_refs[0].end]
    return min(holding, key=lambda c: c.source_refs[0].start) if holding else None


def _period_card(cards: list[Unit], p: Period) -> Unit | None:
    """The card holding a period's effect quote, else its first quoted field."""
    anchor = p.effect if p.effect.start is not None else next(
        (g for g in (getattr(p, f) for f in PERIOD_FIELDS) if g.start is not None), None)
    return None if anchor is None else _card_of(cards, anchor)


def _prov(path: str, g: Grounded) -> dict:
    return {path: {"value": g.value, "quote": g.quote, "span": [g.start, g.end],
                   "status": g.status}} if g.value is not None else {}


def _period_prov(i: int, p: Period) -> dict:
    out: dict = {}
    for f in PERIOD_FIELDS:
        out.update(_prov(f"periods[{i}].{f}", getattr(p, f)))
    return out


class _Part:
    """One condition for (card, effect), with its parameters' provenance and review flags."""

    def __init__(self, card: Unit, effect: str, when: Expr, prov: dict, qualifiers=(),
                 conditions=()):
        self.card, self.effect, self.when, self.prov = card, effect, when, prov
        self.qualifiers, self.conditions = set(qualifiers), set(conditions)


def _review(parts: list[_Part]) -> dict:
    prov = {k: v for p in parts for k, v in p.prov.items()}
    review: dict = {}
    qualifiers = sorted({q for p in parts for q in p.qualifiers})
    conditions = sorted({c for p in parts for c in p.conditions})
    auto = sorted(k for k, v in prov.items() if v["status"] == "auto-accepted")
    if qualifiers:
        review["sentence_qualifiers"] = qualifiers
    if conditions:
        review["sentence_conditions"] = conditions
    if auto:
        review["auto_accepted"] = auto
    return review


def _binding(card: Unit, effect: str, when: Expr, target: dict, prov: dict, review: dict,
             bridge: str | None, overrides: list[str] | None = None) -> Binding:
    core = {"rule_id": card.canonical_ref, "rule_version": card.version, "doc_id": card.doc_id,
            "target": target, "effect": effect, "when": when, "overrides": overrides or []}
    bid, version = binding_ids(core)
    b = Binding.model_validate({**core, "binding_id": bid, "binding_version": version,
                                "required_facts": required_facts(when), "derivation": "",
                                "params_prov": prov, "tests": [], "analysis": {},
                                "review": review, "status": "proposed"})
    b.derivation = sentence(b, bridge)       # validated on assignment
    return b


def _problems(draw: DrawParams, cards: list[Unit]) -> tuple[list[str], list[Window | None]]:
    out = [f"{f}: {getattr(draw, f).null_reason}" for f in ("opening_basis", "notice_hours")
           if getattr(draw, f).null_reason in FAILED]
    out += [f"periods[{i}].{f}: {getattr(p, f).null_reason}" for i, p in enumerate(draw.periods)
            for f in PERIOD_FIELDS if getattr(p, f).null_reason in FAILED]
    if out:
        return out, []
    if draw.opening_basis.value == "closed_to_navigation":
        return ["the draw is closed to navigation: its always-firing forbid would be vacuous "
                "(builder note 13)"], []
    windows: list[Window | None] = []
    for i, p in enumerate(draw.periods):
        effect = p.effect.value
        if effect is None:
            out.append(f"periods[{i}].effect: {p.effect.null_reason}")
        window, problem = period_window(p)
        windows.append(window)
        if problem:
            out.append(f"periods[{i}]: {problem}")
        if effect == "need_not_open" and p.window_readable is not True:
            out.append(f"periods[{i}]: the window grammar cannot read its quote")
        if effect == "notice_required" and draw.notice_hours.value is None:
            out.append(f"periods[{i}]: a notice period with no notice hours")
        if _period_card(cards, p) is None:
            out.append(f"periods[{i}]: no rule card holds its quote")
    if draw.opening_basis.value == "advance_notice" and draw.notice_hours.value is None:
        out.append("opening_basis: advance notice with no notice hours")
    effects = {p.effect.value for p in draw.periods}
    if draw.notice_hours.value is not None and "notice_required" not in effects and \
            _card_of(cards, draw.notice_hours) is None:
        out.append("notice_hours: no rule card holds its quote")
    if draw.opening_basis.value == "on_signal" and "on_signal" not in effects and \
            _card_of(cards, draw.opening_basis) is None:
        out.append("opening_basis: no rule card holds its quote")
    return out, windows


def compile_draw(section: str, draw: DrawParams, cards: list[Unit], general: Unit,
                 emergency: Unit) -> tuple[list[Binding], list[str]]:
    """(the bindings of one draw, []) or ([], the problems that give it none) (module
    text). `cards` are the section's rule cards; `general` and `emergency` the § 117.5 and
    § 117.31(b) cards of the same document."""
    problems, windows = _problems(draw, cards)
    if problems:
        return [], problems
    target = {"tool": TOOL, "selector": {"section": section, "draw": draw.draw}}
    bridge = draw.bridge.value
    n = draw.notice_hours.value
    notice_prov = _prov("notice_hours", draw.notice_hours)
    parts: list[_Part] = []
    specific: list[Window] = []
    for i, (p, w) in enumerate(zip(draw.periods, windows, strict=True)):
        card = _period_card(cards, p)
        prov, flags = _period_prov(i, p), (p.sentence_qualifiers, p.sentence_conditions)
        specific.append(w)
        effect = p.effect.value
        if effect == "on_signal":
            parts.append(_Part(card, "basis", _in(w), prov, *flags))
        elif effect == "need_not_open":
            parts.append(_Part(card, "forbid", _in(w), prov, *flags))
        else:
            for eff, op in (("basis", ">="), ("forbid", "<")):
                parts.append(_Part(card, eff, {"and": [_in(w), {"cmp": [NOTICE, op, 60 * n]}]},
                                   {**prov, **notice_prov}, *flags))
    effects = {p.effect.value for p in draw.periods}
    if n is not None and "notice_required" not in effects:
        card = _card_of(cards, draw.notice_hours)
        specific.append(ALL_TIMES)
        for eff, op in (("basis", ">="), ("forbid", "<")):
            parts.append(_Part(card, eff, {"and": [_in(ALL_TIMES), {"cmp": [NOTICE, op, 60 * n]}]},
                               {**notice_prov, **_prov("opening_basis", draw.opening_basis)},
                               draw.sentence_qualifiers))
    if draw.opening_basis.value == "on_signal" and "on_signal" not in effects:
        specific.append(ALL_TIMES)
        parts.append(_Part(_card_of(cards, draw.opening_basis), "basis", _in(ALL_TIMES),
                           _prov("opening_basis", draw.opening_basis),
                           draw.sentence_qualifiers))
    grouped: dict[tuple[str, str], list[_Part]] = {}
    for part in parts:
        grouped.setdefault((part.card.unit_id, part.effect), []).append(part)
    out = []
    for (_, effect), group in sorted(grouped.items(), key=lambda kv: (
            kv[1][0].card.canonical_ref, kv[1][0].card.unit_id, kv[0][1])):
        prov = {k: v for p in group for k, v in p.prov.items()}
        out.append(_binding(group[0].card, effect, _any([p.when for p in group]), target, prov,
                            _review(group), bridge))
    if not covers_all(specific):      # the general duty where no specific rule holds
        when = {"not": _any([_in(w) for w in specific])} if specific else {"const": True}
        duty = _Part(general, "basis", when, {k: v for p in parts for k, v in p.prov.items()},
                     {q for p in parts for q in p.qualifiers},
                     {c for p in parts for c in p.conditions})
        out.append(_binding(general, "basis", when, target, duty.prov, _review([duty]), bridge))
    forbids = sorted(b.binding_id for b in out if b.effect == "forbid")
    out.append(_binding(emergency, "basis", _emergency_when(), target, {}, {}, bridge, forbids))
    return out, []


# -- compile_bindings ----------------------------------------------------------------------------

def _at_or_under(raw: str, ref: str) -> bool:
    r = normalise_rule_id(raw)
    return r is not None and (r == ref or r.startswith(ref + "("))


def _rule_card(cards: list[Unit], doc_id: str, ref: str) -> Unit:
    """The first card (document order) of `doc_id` at or under rule id `ref`."""
    found = [c for c in cards if c.doc_id == doc_id and _at_or_under(c.canonical_ref, ref)]
    if not found:
        raise ValueError(f"{doc_id[:12]}: no rule card at or under {ref}")
    return min(found, key=lambda c: c.source_refs[0].start)


def compile_bindings(items: list[SectionEnrichment], cards: list[Unit]
                     ) -> tuple[list[Binding], dict]:
    """(the bindings of every draw of `items`, the compile report). The § 117.5 and
    § 117.31(b) cards are found in each item's document by rule id (preflight C14); a section's
    cards are the cards of its document at or under the section. The report: sections, draws
    (total, compiled, failed), bindings by effect and by kind, the listed draws with their
    problems, the draws whose parameters' sentences state qualifiers they lack
    (`sentence_qualifiers`), and the window grammar's agreement counts over the closed windows."""
    bindings: list[Binding] = []
    failed: list[dict] = []
    flagged: list[dict] = []
    grammar, draws, kinds = Counter(), Counter(), Counter()
    for item in sorted(items, key=lambda i: _section_key(i.section)):
        if not item.draws:
            continue
        general = _rule_card(cards, item.doc_id, GENERAL_DUTY)
        emergency = _rule_card(cards, item.doc_id, EMERGENCY)
        own = [c for c in cards if c.doc_id == item.doc_id
               and _in_section(c.canonical_ref, item.section)]
        for d in item.draws:
            draws["total"] += 1
            for p in d.periods:
                if p.effect.value == "need_not_open":
                    grammar[{True: "agree", False: "disagree", None: "not_compared"}[
                        p.window_grammar_agrees]] += 1
                    grammar["conditioned"] += bool(p.sentence_conditions)
            qualifiers = sorted(set(d.sentence_qualifiers).union(
                *(p.sentence_qualifiers for p in d.periods)))
            if qualifiers:
                flagged.append({"section": item.section, "draw": d.draw,
                                "qualifiers": qualifiers})
            got, problems = compile_draw(item.section, d, own, general, emergency)
            if problems:
                draws["failed"] += 1
                failed.append({"section": item.section, "draw": d.draw, "problems": problems})
            else:
                draws["compiled"] += 1
                bindings += got
                kinds.update("general_duty" if b.rule_id == general.canonical_ref else
                             "emergency" if b.rule_id == emergency.canonical_ref else
                             "specific" for b in got)
    report = {
        "sections": sum(1 for i in items if i.draws),
        "draws": {k: draws[k] for k in ("total", "compiled", "failed")},
        "bindings": len(bindings),
        "by_effect": dict(sorted(Counter(b.effect for b in bindings).items())),
        "by_kind": dict(sorted(kinds.items())),
        "failed": failed, "sentence_qualifiers": flagged,
        "window_grammar": {k: grammar[k] for k in ("agree", "disagree", "not_compared",
                                                   "conditioned")}}
    return bindings, report


# -- the derivation sentence ---------------------------------------------------------------------

_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August",
                "September", "October", "November", "December")
_CLASS_WORDS = {"public_safety": "public-safety", "distress": "distress",
                "rescue_salvage": "rescue or salvage",
                "severe_weather_shelter": "severe-weather-shelter"}


def _hm(m: int) -> str:
    return f"{m // 60}:{m % 60:02d}"


def _date(md: str) -> str:
    return f"{_MONTH_NAMES[int(md[:2]) - 1]} {int(md[3:])}"


def _days_phrase(days: tuple[str, ...]) -> str:
    idx = [DAYS.index(d) for d in days]
    names = [_DAY_NAMES[i] for i in idx]
    if len(idx) >= 3 and idx == list(range(idx[0], idx[0] + len(idx))):
        return f"{names[0]} to {names[-1]}"
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _qualifiers(w: Window) -> list[str]:
    out = []
    if w.days != DAYS:
        out.append(_days_phrase(w.days))
    if w.except_federal_holidays:
        out.append("except federal holidays")
    if w.date_from is not None:
        out.append(f"{_date(w.date_from)} to {_date(w.date_to)}")
    return out


def _times(w: Window) -> str | None:
    return None if (w.start, w.end) == (0, 1440) else f"from {_hm(w.start)} to {_hm(w.end)}"


def _windows_phrase(ws: list[Window]) -> str:
    if all(w == ALL_TIMES for w in ws):
        return "at any time"
    quals = [_qualifiers(w) for w in ws]
    if all(q == quals[0] for q in quals):
        times = [t for w in ws if (t := _times(w))] or ["all day"]
        return ", ".join([" or ".join(times), *quals[0]])
    return "; or ".join(", ".join([_times(w) or "all day", *_qualifiers(w)]) for w in ws)


def _window_list(e: Expr) -> list[Window] | None:
    if "in_window" in e:
        return [Window.model_validate(e["window"])]
    if "or" in e and all("in_window" in x for x in e["or"]):
        return [Window.model_validate(x["window"]) for x in e["or"]]
    return None


def _hours(minutes: int) -> str:
    if minutes % 60:
        return f"{minutes} minutes"
    h = minutes // 60
    return f"{h} hour{'s' if h != 1 else ''}"


def _phrase(e: Expr) -> str:
    ws = _window_list(e)
    if ws is not None:
        return _windows_phrase(ws)
    if "and" in e:
        return " ".join(_phrase(x) for x in e["and"])
    if "or" in e:
        return " or ".join(_phrase(x) for x in e["or"])
    if "not" in e:
        inner = e["not"]
        if inner == {"eq": ["local_procedure_conflict", True]}:
            return "when no approved local emergency procedure conflicts"
        ws = _window_list(inner)
        if ws is not None:
            return f"at any time except {_windows_phrase(ws)}"
        return f"unless {_phrase(inner)}"
    if "cmp" in e and e["cmp"][0] == NOTICE and e["cmp"][1] in (">=", "<"):
        return f"with {'at least' if e['cmp'][1] == '>=' else 'less than'} " \
               f"{_hours(e['cmp'][2])} notice"
    if "in" in e and e["in"][0] == "vessel_class":
        words = [_CLASS_WORDS.get(c, c) for c in e["in"][1]]
        listed = words[0] if len(words) == 1 else f"{', '.join(words[:-1])}, or {words[-1]}"
        return f"for a {listed} vessel"
    if e == {"const": True}:
        return "at any time"
    return json.dumps(e, sort_keys=True)


def _draw_name(bridge: str | None) -> str | None:
    if not isinstance(bridge, str) or not bridge.strip():
        return None
    name = bridge.strip()
    for suffix in (" drawbridge", " bridge", " draw"):
        if name.lower().endswith(suffix):
            name = name[:-len(suffix)].rstrip()
            break
    return name or None


def sentence(b: Binding, bridge: str | None) -> str:
    """The binding in words ("Forbid scheduling an opening of the Main Street draw from 7:00
    to 9:00, Monday to Friday, except federal holidays"): Forbid or Allow, the draw named by
    its bridge without "bridge"/"drawbridge", the condition, and the forbids it overrides."""
    name = _draw_name(bridge)
    sel = b.target.get("selector", {})
    who = f"the {name} draw" if name else f"draw {sel.get('draw')} of § {sel.get('section')}"
    verb = "Forbid" if b.effect == "forbid" else "Allow"
    text = f"{verb} scheduling an opening of {who} {_phrase(b.when)}"
    if b.overrides:
        k = len(b.overrides)
        text += f", overriding {k} forbid{'s' if k != 1 else ''}"
    return text
