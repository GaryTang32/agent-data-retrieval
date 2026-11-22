"""Z3 analysis of a draw's bindings (Phase 4 spec §12.4, P32, P44; Task 16): conflicts with
declared overrides, vacuity, redundancy and gaps, over minute, weekday, holiday, day of year,
notice, vessel class and conflict, with crossing windows judged on the previous day. Skipped
where the `[analysis]` extra is not installed (CI); no model call."""

from __future__ import annotations

import pytest

pytest.importorskip("z3")

from datetime import datetime  # noqa: E402

from adr_store.bindings.analysis import Analysis, analyse_draw, mark_analysed  # noqa: E402
from adr_store.bindings.checks import mark_tested  # noqa: E402
from adr_store.bindings.dsl import DAYS, Tri, evaluate  # noqa: E402
from adr_store.bindings.facts import derive_facts  # noqa: E402
from tests.store.bindings_fixtures import (  # noqa: E402
    BINDINGS_821,
    BINDINGS_CROSSING,
    BINDINGS_GENERAL,
    BINDINGS_NOTICE_PERIOD,
    BINDINGS_SHUT,
    BINDINGS_SIGNAL,
    CARD_A,
    CARD_B,
    EMERGENCY_CARD,
    by_rule,
    rebuild,
    record,
    with_when,
)

FORBID_821 = by_rule(BINDINGS_821, CARD_A.canonical_ref, "forbid")
NOTICE_FORBID_821 = by_rule(BINDINGS_821, CARD_B.canonical_ref, "forbid")
EMERGENCY_821 = by_rule(BINDINGS_821, EMERGENCY_CARD.canonical_ref, "basis")


def win(start: int, end: int, days=DAYS, holidays: bool = False, date_from=None, date_to=None):
    return {"in_window": {"fact": "open_at"},
            "window": {"start": start, "end": end, "days": list(days),
                       "except_federal_holidays": holidays, "date_from": date_from,
                       "date_to": date_to}}


def replace(bindings, old, new):
    return [new if b.binding_id == old.binding_id else b for b in bindings]


def test_compiled_draws_are_clean():
    for bs in (BINDINGS_821, BINDINGS_SIGNAL, BINDINGS_NOTICE_PERIOD, BINDINGS_GENERAL,
               BINDINGS_CROSSING):     # (BINDINGS_SHUT is vacuous by design)
        a = analyse_draw(bs)
        assert (a.conflicts, a.vacuous, a.gaps) == ([], [], []), bs[0].derivation


def test_declared_override_is_not_a_conflict():
    assert analyse_draw(BINDINGS_821).conflicts == []
    # and a plain basis True together with a forbid is the decision rule's, not a conflict
    signal = by_rule(BINDINGS_821, CARD_A.canonical_ref, "basis")
    overlapping = with_when(signal, win(0, 1440))
    assert analyse_draw(replace(BINDINGS_821, signal, overlapping)).conflicts == []


def test_missing_override_entry_is_a_conflict():
    partial = rebuild(EMERGENCY_821, overrides=[FORBID_821.binding_id])
    a = analyse_draw(replace(BINDINGS_821, EMERGENCY_821, partial))
    assert len(a.conflicts) == 1
    assert NOTICE_FORBID_821.binding_id[:12] in a.conflicts[0]
    assert "both can hold" in a.conflicts[0]


def test_an_unlisted_forbid_that_cannot_hold_with_the_override_is_no_conflict():
    partial = rebuild(EMERGENCY_821, overrides=[NOTICE_FORBID_821.binding_id])
    never_with_emergency = with_when(FORBID_821, {"and": [
        FORBID_821.when, {"in": ["vessel_class", ["commercial", "recreational"]]}]})
    bs = replace(replace(BINDINGS_821, EMERGENCY_821, partial), FORBID_821,
                 never_with_emergency)
    assert analyse_draw(bs).conflicts == []


def test_override_naming_no_forbid_and_override_cycles_are_conflicts():
    signal = by_rule(BINDINGS_821, CARD_A.canonical_ref, "basis")
    ghost = rebuild(EMERGENCY_821, overrides=[*EMERGENCY_821.overrides, "f" * 64])
    a = analyse_draw(replace(BINDINGS_821, EMERGENCY_821, ghost))
    assert any("ffffffffffff" in c and "no forbid" in c for c in a.conflicts)
    # two bases that override each other: each names no forbid, and they form a cycle
    a_ = rebuild(signal, overrides=[EMERGENCY_821.binding_id])
    b_ = rebuild(EMERGENCY_821, overrides=[*EMERGENCY_821.overrides, signal.binding_id])
    a = analyse_draw(replace(replace(BINDINGS_821, signal, a_), EMERGENCY_821, b_))
    assert sum("no forbid" in c for c in a.conflicts) == 2
    assert any(c.startswith("overrides form a cycle") for c in a.conflicts)


def test_never_firing_and_always_firing_forbids_are_vacuous():
    never = with_when(FORBID_821, {"and": [win(420, 540), {"not": win(400, 600)}]})
    always = with_when(FORBID_821, {"const": True})
    negative = with_when(NOTICE_FORBID_821, {"cmp": ["notice_minutes", "<", 0]})
    for bad in (never, always):
        assert analyse_draw(replace(BINDINGS_821, FORBID_821, bad)).vacuous == [bad.binding_id]
    assert analyse_draw(replace(BINDINGS_821, NOTICE_FORBID_821, negative)).vacuous == [
        negative.binding_id]
    # a basis that can never fire is vacuous; one that always fires is not
    signal = by_rule(BINDINGS_821, CARD_A.canonical_ref, "basis")
    dead = with_when(signal, {"const": False})
    assert analyse_draw(replace(BINDINGS_821, signal, dead)).vacuous == [dead.binding_id]
    assert analyse_draw(replace(BINDINGS_821, signal, with_when(signal, win(0, 1440)))
                        ).vacuous == []


def test_gaps_are_reported():
    assert analyse_draw(BINDINGS_821).gaps == []
    # an on-signal basis only from 9:00 to 17:00 leaves the evening uncovered
    signal = by_rule(BINDINGS_821, CARD_A.canonical_ref, "basis")
    notice_basis = by_rule(BINDINGS_821, CARD_B.canonical_ref, "basis")
    bs = [b for b in replace(BINDINGS_821, signal, with_when(signal, win(540, 1020)))
          if b.binding_id not in (notice_basis.binding_id, NOTICE_FORBID_821.binding_id)]
    bs = [rebuild(b, overrides=[FORBID_821.binding_id]) if b.overrides else b for b in bs]
    (gap,) = analyse_draw(bs).gaps
    # the witness is the least gap point, and no binding of the draw holds there
    assert gap == {"month_day": "01-01", "weekday": "Mon", "federal_holiday": False,
                   "previous_month_day": "12-31", "previous_day_holiday": False, "minute": 0,
                   "notice_minutes": 0, "vessel_class": "commercial",
                   "local_procedure_conflict": False}
    at = datetime(2029, 1, 1, 0, 0)          # a Monday, 1 January (a holiday in fact; Z3's is free)
    f = derive_facts(at, record(at, notice=0, vessel="commercial", conflict=False))
    assert all(evaluate(b.when, f) is Tri.F for b in bs)


def test_holidays_are_free_variables():
    """Holidays are free in Z3, as in `covers_all`: any day may be one. A basis on weekdays
    except federal holidays plus one on weekends leaves holiday weekdays as a gap."""
    signal = by_rule(BINDINGS_SIGNAL, CARD_A.canonical_ref, "basis")
    emergency = by_rule(BINDINGS_SIGNAL, EMERGENCY_CARD.canonical_ref, "basis")
    weekdays = with_when(signal, win(0, 1440, DAYS[:5], holidays=True))
    weekend = rebuild(signal, rule_id="33 CFR 117.821(b)", when=win(0, 1440, DAYS[5:]))
    (gap,) = analyse_draw([weekdays, weekend, rebuild(emergency, overrides=[])]).gaps
    assert gap["federal_holiday"] is True and gap["weekday"] in DAYS[:5]


def test_crossing_windows_take_the_previous_day():
    """P44: a Monday 23:00-06:00 closure holds Tuesday 00:00-06:00, so a Tuesday 00:00-06:00
    closure is implied by it (redundant), and a forbid on that night's minutes that falls on
    Monday's own early hours can never fire (vacuous)."""
    forbid = [b for b in BINDINGS_CROSSING if b.effect == "forbid"][0]
    tuesday = rebuild(forbid, rule_id="33 CFR 117.821(b)", when=win(0, 360, ("Tue",)))
    a = analyse_draw([*BINDINGS_CROSSING, tuesday])
    assert a.redundant == [tuesday.binding_id] and a.conflicts
    monday_early = rebuild(forbid, rule_id="33 CFR 117.821(c)",
                           when={"and": [forbid.when, win(0, 360, ("Mon",))]})
    assert monday_early.binding_id in analyse_draw([*BINDINGS_CROSSING, monday_early]).vacuous
    # the year end: a December 31 night closure holds 1 January's early hours
    nye = rebuild(forbid, rule_id="33 CFR 117.821(d)",
                  when=win(1380, 360, date_from="12-31", date_to="12-31"))
    jan1 = rebuild(forbid, rule_id="33 CFR 117.821(e)",
                   when=win(0, 360, date_from="01-01", date_to="01-01"))
    assert analyse_draw([nye, jan1]).redundant == [jan1.binding_id]
    # and 1 March's early hours follow 28 or 29 February
    feb = rebuild(forbid, rule_id="33 CFR 117.821(f)",
                  when=win(1380, 360, date_from="02-28", date_to="02-28"))
    mar1 = rebuild(forbid, rule_id="33 CFR 117.821(g)",
                   when=win(0, 360, date_from="03-01", date_to="03-01"))
    assert analyse_draw([feb, mar1]).redundant == []                 # not after 29 February
    leap = rebuild(feb, when=win(1380, 360, date_from="02-28", date_to="02-29"))
    assert analyse_draw([leap, mar1]).redundant == [mar1.binding_id]
    # but a 28 February night does reach 1 March (in a common year): not vacuous
    reach = rebuild(forbid, rule_id="33 CFR 117.821(h)", when={"and": [feb.when, mar1.when]})
    assert analyse_draw([reach]).vacuous == []


def test_redundancy_is_reported_and_kept():
    # in the on-signal-with-notice shape the notice basis implies the on-signal basis's region
    # (both hold outside the window; the notice forbid decides), so it is redundant, and kept
    notice_basis = by_rule(BINDINGS_821, CARD_B.canonical_ref, "basis")
    assert analyse_draw(BINDINGS_821).redundant == [notice_basis.binding_id]
    signal = by_rule(BINDINGS_821, CARD_A.canonical_ref, "basis")
    prov = {"periods[0].effect": {"value": "on_signal"}, "periods[0].start": {"value": 600},
            "periods[0].end": {"value": 700}}
    twin = rebuild(signal, rule_id="33 CFR 117.821(b)", when=win(600, 700), params_prov=prov)
    a = analyse_draw([*BINDINGS_821, twin])
    assert a.redundant == sorted([notice_basis.binding_id, twin.binding_id])
    assert a.vacuous == [] and a.conflicts == []
    out = mark_analysed(mark_tested([*BINDINGS_821, twin]), a)
    assert {b.status for b in out} == {"analysed"}
    assert [b.analysis["redundant"] for b in out] == [b.binding_id in a.redundant for b in out]


def test_mark_analysed_statuses():
    tested = mark_tested(BINDINGS_821)
    a = analyse_draw(tested)
    out = mark_analysed(tested, a)
    assert {b.status for b in out} == {"analysed"}
    assert all(b.analysis == {"conflicts": [], "vacuous": False,
                              "redundant": b.binding_id in a.redundant, "gaps": []}
               for b in out)
    # a vacuous binding rejects the draw (the rest are blocked): closed at all times
    tested = mark_tested(BINDINGS_SHUT)
    assert {b.status for b in tested} == {"tested"}
    out = mark_analysed(tested, analyse_draw(tested))
    assert {b.status for b in out} == {"rejected"}
    assert [b.analysis["vacuous"] for b in out].count(True) == 1
    assert all(b.analysis["blocked_by"] for b in out if not b.analysis["vacuous"])
    # so does a conflict
    partial = rebuild(EMERGENCY_821, overrides=[FORBID_821.binding_id])
    bad = mark_tested(replace(BINDINGS_821, EMERGENCY_821, partial))
    assert {b.status for b in bad} == {"tested"}
    out = mark_analysed(bad, analyse_draw(bad))
    assert {b.status for b in out} == {"rejected"} and out[0].analysis["conflicts"]
    with pytest.raises(ValueError, match="tested"):
        mark_analysed(BINDINGS_821, analyse_draw(BINDINGS_821))


def test_analysis_is_deterministic():
    assert analyse_draw(BINDINGS_821) == analyse_draw(list(reversed(BINDINGS_821)))
    assert isinstance(analyse_draw(BINDINGS_821), Analysis)
