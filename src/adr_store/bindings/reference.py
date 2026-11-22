"""The reference evaluator (Phase 4 spec §12.3, P12, P32, P34, P37, P44, P46; Task 16): a plain
Python reading of the desk's decision for draws of the simple shape, from the *Phase 3
second-pass facts* and the window grammar, never from a binding, the DSL evaluator or the
enrichment parameters (the tests of §12.3 must not share the bindings' source).

**The simple shape** (`ref_draws`). One `RefDraw` per second-pass draw of a section unit of
the requested document (key: the section and the draw's 1-based position in the facts, the
Phase 3 numbering, which differs from the enrichment's), when its facts give: an opening basis
(`opens_on_signal` known; `False` needs a notice threshold), at most one whole-hour notice
threshold that holds wherever no closed window does (0 hours is none), and closed windows the
grammar reads. `opens_on_signal` True with a threshold is read as one threshold at all times:
the facts cannot tell it from a period-specific rule (§4.5), and the agreement set (below)
keeps only draws whose enrichment states the simple shape. A draw is left out, counted under
the first reason that applies (`ref_census`): `signal_unknown`, `notice_failed` (the notice
answer failed its checks), `notice_not_whole`, `no_basis` (does not open on signal and states
no notice), `closed_failed`, a closed period that does not read (below), or `seasonal` (the
section's rules differ by season and none of the draw's closed windows is dated: the season
must lie in a period-specific opening rule, P46).

**Closed windows** (`read_closed`, the Task 14/15 rulings). The second pass quotes one string
per draw. It is expanded to its sentence in the section text (`enrich.read_sentence`, anchored
on the quote's clock times, else the whole quote): the grammar's widest reading around it is
the draw's windows. The sentence decides, whatever the bare quote reads. Not read:
`unquoted`; `conditioned` (the quote's clause says "only", "unless" or "notice": no plain
closure); `unreadable` (no reading in the sentence); `qualifiers` (the clause states days, a
holiday exception or dates that the reading lacks, `missing_qualifiers`: the window would be
too broad). `ref_census` counts each rule and whether the sentence read the same windows as
the quote alone.

**The decision** (`ref_decide`), on the facts of `facts.derive_facts` (the fact module the gate
shares; builder note 15): an emergency class (`EMERGENCY_CLASSES`) with no conflicting local
procedure allows (§ 117.31(b), P32). Otherwise an opening inside a closed window
(`dsl.in_window`, P44 for crossing windows) is denied, and outside one a draw with a threshold
escalates when notice is unknown and denies when it is short; the deny names the draw's section
("117.821", P34). Everything else is allowed (on signal, advance notice given, or § 117.5).
P37: where the outcome would be deny or escalate and § 117.31(b) could still apply (the vessel
class unknown, or an emergency class with the conflict unknown, and no known conflict), the
reference escalates and lists the unknown facts that could change the outcome, sorted: the
class and the conflict, and the notice when it is unknown. `ref_next_allowed` scans minute by
minute over the seven days after the requested minute for the first `allow`.

**The agreement set** (`agreement_set`, §12.3, criterion B1's domain): the draws, numbered as
the bindings target them, that have bindings, whose enrichment parameters have the simple shape
(no failed value; opening basis `on_signal` or `advance_notice` with notice; every period a
grammar-readable `need_not_open` window) and equal the reference's facts (opens on signal as
E2 reads it, the threshold, the closed windows as a set), for the same section text. Draws are
paired as Phase 3 E2 pairs them (`paired_refs`): by bridge key, then by mile, over every
second-pass draw of the section, never by draw number.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from adr_store.bindings.dsl import Window, in_window
from adr_store.bindings.enrich import (
    FAILED,
    PERIOD_FIELDS,
    SectionEnrichment,
    missing_qualifiers,
    period_window,
    read_sentence,
    section_key,
)
from adr_store.bindings.facts import EMERGENCY_CLASSES, derive_facts
from adr_store.bindings.windows import parse_windows
from adr_store.tables import extract as ex
from adr_store.units.grounding import clock_times

__all__ = ["EXCLUSIONS", "RefDecision", "RefDraw", "agreement_set", "paired_refs",
           "read_closed", "ref_census", "ref_decide", "ref_draws", "ref_next_allowed"]

SCAN_DAYS = 7
NOTICE = "notice_minutes"
VESSEL = "vessel_class"
CONFLICT = "local_procedure_conflict"
EXCLUSIONS = ("signal_unknown", "notice_failed", "notice_not_whole", "no_basis", "closed_failed",
              "closed_unquoted", "closed_conditioned", "closed_unreadable", "closed_qualifiers",
              "seasonal")
READINGS = ("same_as_quote", "sentence_only", "sentence_differs", "conditioned", "unreadable",
            "unreadable_quote_reads", "qualifiers", "unquoted")


@dataclass(frozen=True)
class RefDraw:
    """One draw of the simple shape (module text). `unit` is the SHA-256 of the section text
    (the Phase 3 unit key) and `section_draws` the (bridge, mile) of every second-pass draw of
    the section in order, so that enrichment draws pair with Phase 3 draws as E2 pairs them."""

    section: str
    draw: int
    bridge: str | None
    opens_on_signal: bool
    notice_hours: int | None
    closed: tuple[Window, ...]
    unit: str = ""
    section_draws: tuple[tuple[str | None, float | None], ...] = ()


@dataclass(frozen=True)
class RefDecision:
    outcome: Literal["allow", "deny", "escalate"]
    denying_sections: frozenset[str]
    missing: tuple[str, ...]


# -- the decision ----------------------------------------------------------------------------------

def _override(facts: dict[str, Any]) -> bool | None:
    """Whether § 117.31(b) applies: True, False, or None when unknown facts could make it."""
    vessel, conflict = facts.get(VESSEL), facts.get(CONFLICT)
    if conflict is True or (vessel is not None and vessel not in EMERGENCY_CLASSES):
        return False
    if vessel is not None and conflict is False:
        return True
    return None


def decide_facts(d: RefDraw, facts: dict[str, Any]) -> RefDecision:
    """`ref_decide` on facts already derived by `derive_facts`."""
    override = _override(facts)
    if override is True:
        return RefDecision("allow", frozenset(), ())
    at = datetime.fromisoformat(facts["open_at"])
    minute, day = at.hour * 60 + at.minute, at.date()
    missing: list[str] = []
    if any(in_window(w, minute, day) for w in d.closed):
        outcome = "deny"
    elif d.notice_hours is not None:
        notice = facts.get(NOTICE)
        if notice is None:
            outcome = "escalate"
            missing.append(NOTICE)
        else:
            outcome = "deny" if notice < 60 * d.notice_hours else "allow"
    else:
        outcome = "allow"
    if outcome == "allow":
        return RefDecision("allow", frozenset(), ())
    if override is None:          # P37: § 117.31(b) could still apply
        missing += [f for f in (VESSEL, CONFLICT) if facts.get(f) is None]
        return RefDecision("escalate", frozenset(), tuple(sorted(missing)))
    if outcome == "deny":
        return RefDecision("deny", frozenset({d.section}), ())
    return RefDecision("escalate", frozenset(), tuple(sorted(missing)))


def ref_decide(d: RefDraw, open_at: datetime, record: dict) -> RefDecision:
    """The desk's decision on an opening of draw `d` at `open_at` under the request `record`
    (module text). ValueError for a malformed record (the caller fails closed)."""
    return decide_facts(d, derive_facts(open_at, record))


def ref_next_allowed(d: RefDraw, open_at: datetime, record: dict) -> datetime | None:
    """The first minute after `open_at` (seconds dropped), within seven days, at which the
    reference allows the opening; None when there is none."""
    start = open_at.replace(second=0, microsecond=0)
    for k in range(1, SCAN_DAYS * 1440 + 1):
        at = start + timedelta(minutes=k)
        if ref_decide(d, at, record).outcome == "allow":
            return at
    return None


# -- reading the facts -----------------------------------------------------------------------------

def read_closed(text: str, v: ex.Value) -> tuple[tuple[Window, ...] | None, str]:
    """(the closed windows of a second-pass `closed_periods` value read on its sentence in
    `text`, the section text; or None) and the rule that decided (`READINGS`)."""
    if v.quote is None or v.start is None or v.end is None:
        return None, "unquoted"
    bare = parse_windows(v.quote)
    times = clock_times(v.quote)
    a, b = ((v.start + times[0][0], v.start + times[-1][1]) if times else (v.start, v.end))
    reading = read_sentence(text, a, b)
    if reading.conditions:
        return None, "conditioned"
    if reading.windows is None:
        return None, "unreadable_quote_reads" if bare is not None else "unreadable"
    if any(missing_qualifiers(w, reading) for w in reading.windows):
        return None, "qualifiers"
    full = tuple(reading.windows)
    if bare is not None and tuple(bare) == full:
        return full, "same_as_quote"
    return full, "sentence_only" if bare is None else "sentence_differs"


def _value(d: dict[str, ex.Value], column: str) -> ex.Value:
    return d.get(column) or ex.ABSENT


def _failed(v: ex.Value) -> bool:
    return v.value is None and v.null_reason in FAILED


def _whole_hours(value: Any) -> int | None:
    """`value` as whole hours, or None when it is not a non-negative whole number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if value >= 0 and float(value).is_integer() else None


@dataclass(frozen=True)
class _Reading:
    ref: RefDraw | None
    reason: str | None
    closed_rule: str | None


def _read_draw(section: str, n: int, d: dict[str, ex.Value], text: str, seasonal: bool,
               sha: str, siblings: tuple) -> _Reading:
    closed_v = _value(d, "closed_periods")
    windows: tuple[Window, ...] | None = ()
    rule = None
    if closed_v.value:
        windows, rule = read_closed(text, closed_v)
    signal = _value(d, "opens_on_signal").value
    notice_v = _value(d, "notice_hours")
    notice = _whole_hours(notice_v.value)

    def out(reason: str | None) -> _Reading:
        if reason is not None:
            return _Reading(None, reason, rule)
        bridge = _value(d, "bridge").value
        return _Reading(RefDraw(section=section, draw=n, bridge=bridge if isinstance(
            bridge, str) else None, opens_on_signal=signal, notice_hours=notice or None,
            closed=windows, unit=sha, section_draws=siblings), None, rule)

    if not isinstance(signal, bool):
        return out("signal_unknown")
    if _failed(notice_v):
        return out("notice_failed")
    if notice_v.value is not None and notice is None:
        return out("notice_not_whole")
    if signal is False and not notice:
        return out("no_basis")
    if _failed(closed_v):
        return out("closed_failed")
    if windows is None:
        return out(f"closed_{rule.removesuffix('_quote_reads')}")
    if seasonal and not any(w.date_from is not None for w in windows):
        return out("seasonal")
    return out(None)


def _sections(facts: list[ex.Facts], sections: list[ex.Unit], doc_id: str | None
              ) -> list[tuple[str, ex.Unit, ex.Facts]]:
    """(section, unit, facts) for each unit of the document that has facts, sorted by section;
    ValueError when two texts are given for one section."""
    by_unit = {f.unit: f for f in facts}
    found: dict[str, tuple[ex.Unit, ex.Facts]] = {}
    for u in sections:
        occ = [o for o in u.occurrences if doc_id is None or o.doc_id == doc_id]
        f = by_unit.get(u.text_sha256)
        if not occ or f is None:
            continue
        section = occ[0].section
        if section in found and found[section][0].text_sha256 != u.text_sha256:
            raise ValueError(f"two section texts for {section}: name the document (doc_id)")
        found[section] = (u, f)
    return [(s, *found[s]) for s in sorted(found, key=section_key)]


def _readings(facts: list[ex.Facts], sections: list[ex.Unit], doc_id: str | None
              ) -> list[_Reading]:
    out = []
    for section, u, f in _sections(facts, sections, doc_id):
        seasonal = _value(f.section, "seasonal").value is True
        siblings = tuple((_value(d, "bridge").value, _value(d, "mile").value) for d in f.draws)
        out += [_read_draw(section, n, d, u.text, seasonal, u.text_sha256, siblings)
                for n, d in enumerate(f.draws, 1)]
    return out


def ref_draws(facts: list[ex.Facts], sections: list[ex.Unit], *, doc_id: str | None = None
              ) -> dict[tuple[str, int], RefDraw]:
    """The simple-shape draws of the second-pass `facts` over the Phase 3 section units
    `sections` (`tables.extract.units`), keyed by (section, Phase 3 draw number); only the
    units occurring in `doc_id` when it is given (module text)."""
    return {(r.ref.section, r.ref.draw): r.ref for r in _readings(facts, sections, doc_id)
            if r.ref is not None}


def ref_census(facts: list[ex.Facts], sections: list[ex.Unit], *, doc_id: str | None = None
               ) -> dict:
    """Totals of `ref_draws`: draws, simple, excluded by first reason (`EXCLUSIONS`), the
    closed-period readings of every draw with a closed period (`READINGS`), and the closed
    windows of the simple draws read the same from the quote alone or only from the
    sentence."""
    rs = _readings(facts, sections, doc_id)
    excluded = Counter(r.reason for r in rs if r.reason is not None)
    rules = Counter(r.closed_rule for r in rs if r.closed_rule is not None)
    windows = Counter()
    for r in rs:
        if r.ref is not None and r.ref.closed:
            windows["same_as_quote" if r.closed_rule == "same_as_quote" else
                    "from_sentence"] += len(r.ref.closed)
    return {"draws": len(rs), "simple": sum(r.ref is not None for r in rs),
            "excluded": {k: excluded[k] for k in EXCLUSIONS if excluded[k]},
            "closed": {"draws": sum(rules.values()),
                       **{k: rules[k] for k in READINGS if rules[k]}},
            "windows": {k: windows[k] for k in ("same_as_quote", "from_sentence")}}


# -- the agreement set -----------------------------------------------------------------------------

def paired_refs(enrich: list[SectionEnrichment], refs: dict[tuple[str, int], RefDraw]
                ) -> dict[tuple[str, int], tuple[str, int]]:
    """(section, enrichment draw) -> (section, Phase 3 draw) for the enrichment draws paired with
    a simple reference draw of the same section text, by `tables.extract.match_draws` over every
    second-pass draw of the section (bridge key, then mile)."""
    by_section: dict[str, RefDraw] = {}
    for r in refs.values():
        by_section.setdefault(r.section, r)
    out: dict[tuple[str, int], tuple[str, int]] = {}
    for item in enrich:
        r0 = by_section.get(item.section)
        if r0 is None or r0.unit != item.section_sha256:
            continue
        mine = [{"bridge": d.bridge.value, "mile": d.mile.value} for d in item.draws]
        theirs = [{"bridge": b, "mile": m} for b, m in r0.section_draws]
        for i, j in ex.match_draws(mine, theirs):
            if i is not None and j is not None and (item.section, j + 1) in refs:
                out[(item.section, item.draws[i].draw)] = (item.section, j + 1)
    return out


def _enrichment_shape(d) -> tuple[bool, int | None, frozenset[Window]] | None:
    """(opens on signal, threshold, closed windows) of an enrichment draw of the simple shape;
    None for any other draw."""
    values = [d.opening_basis, d.notice_hours] + [getattr(p, f) for p in d.periods
                                                   for f in PERIOD_FIELDS]
    if any(g.null_reason in FAILED for g in values):
        return None
    basis = d.opening_basis.value
    notice = _whole_hours(d.notice_hours.value) if d.notice_hours.value is not None else 0
    if basis not in ("on_signal", "advance_notice") or notice is None:
        return None
    if basis == "advance_notice" and not notice:
        return None
    windows = set()
    for p in d.periods:
        if p.effect.value != "need_not_open" or p.window_readable is not True:
            return None
        w, _ = period_window(p)
        if w is None:
            return None
        windows.add(w)
    return True, notice or None, frozenset(windows)


def agreement_set(bindings_by_draw: dict, enrich: list[SectionEnrichment],
                  refs: dict[tuple[str, int], RefDraw]) -> list[tuple[str, int]]:
    """The agreement set (module text): (section, draw) as the bindings target them, sorted by
    section then draw. `bindings_by_draw` maps (section, draw) to the draw's bindings."""
    pairs = paired_refs(enrich, refs)
    out = []
    for item in enrich:
        for d in item.draws:
            key = (item.section, d.draw)
            if key not in pairs or not bindings_by_draw.get(key):
                continue
            shape = _enrichment_shape(d)
            r = refs[pairs[key]]
            if shape == (r.opens_on_signal, r.notice_hours, frozenset(r.closed)):
                out.append(key)
    return sorted(set(out), key=lambda k: (section_key(k[0]), k[1]))
