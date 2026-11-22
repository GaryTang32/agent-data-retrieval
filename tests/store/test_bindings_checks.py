"""Binding tests (Phase 4 spec §12.3, P12, P32, P37, P44, P46; builder note 14; Task 16):
boundary cases and complement probes generated from each binding's parameters, the B1 grid
against the reference evaluator, the gate's decision steps they share, and the statuses they
give. Runs without z3; no model call."""

from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime

import pytest

from adr_store.bindings import checks
from adr_store.bindings.checks import (
    GRID_STEP,
    MIN_CASES,
    boundary_cases,
    complement_probes,
    decide_bindings,
    grid_equivalence,
    grid_size,
    grid_times,
    has_threshold_or_window,
    mark_tested,
    notice_grid,
)
from adr_store.bindings.compile import ALL_TIMES
from adr_store.bindings.dsl import Binding, Tri, evaluate
from adr_store.bindings.facts import derive_facts
from adr_store.bindings.reference import RefDecision, RefDraw
from tests.store.bindings_fixtures import (
    BINDINGS_821,
    BINDINGS_CROSSING,
    BINDINGS_GENERAL,
    BINDINGS_NOTICE_PERIOD,
    BINDINGS_SIGNAL,
    CARD_A,
    CARD_B,
    EMERGENCY_CARD,
    FIXTURE_BINDINGS,
    GENERAL_CARD,
    REF_821,
    REF_SIGNAL,
    by_rule,
    rebuild,
    record,
    shift,
    with_when,
)

FORBID_821 = by_rule(BINDINGS_821, CARD_A.canonical_ref, "forbid")          # the 7-9 window
NOTICE_BASIS_821 = by_rule(BINDINGS_821, CARD_B.canonical_ref, "basis")     # not window, >= 240
NOTICE_FORBID_821 = by_rule(BINDINGS_821, CARD_B.canonical_ref, "forbid")   # not window, < 240
SIGNAL_BASIS_821 = by_rule(BINDINGS_821, CARD_A.canonical_ref, "basis")     # not window
EMERGENCY_821 = by_rule(BINDINGS_821, EMERGENCY_CARD.canonical_ref, "basis")


def window_of(b: Binding) -> dict:
    return b.when["window"]


def facts(at: datetime, **kw) -> dict:
    return derive_facts(at, record(at, **kw))


# -- the notice grid (builder note 14) -------------------------------------------------------------

def test_notice_grid():
    assert notice_grid(4) == (None, 0, 180, 239, 240, 300, 2880) and notice_grid(None) == (
        None, 0, 2880)
    # values met twice are listed once, in order
    assert notice_grid(1) == (None, 0, 59, 60, 120, 2880)
    assert notice_grid(48) == (None, 0, 2820, 2879, 2880, 2940)
    for bad in (0, -1, 2.5, True):
        with pytest.raises(ValueError):
            notice_grid(bad)


def test_grid_is_every_15_minutes_of_a_working_and_a_holiday_week():
    times = grid_times()
    assert GRID_STEP == 15 and len(times) == 2 * 7 * 24 * 4
    assert times[0] == datetime(2026, 8, 10, 0, 0) and times[-1] == datetime(2026, 9, 13, 23, 45)
    assert {t.date() for t in times} == {date(2026, 8, d) for d in range(10, 17)} | {
        date(2026, 9, d) for d in range(7, 14)}
    # each vessel class and unknown, conflict true and false
    assert grid_size(REF_821) == 1344 * 7 * 7 * 2
    assert grid_size(REF_SIGNAL) == 1344 * 3 * 7 * 2


# -- boundary cases and complement probes (§12.3) --------------------------------------------------

def test_boundary_and_complement_cases_are_at_least_four_each():
    for b in FIXTURE_BINDINGS:
        allow, forbid = boundary_cases(b)
        assert len(allow) >= MIN_CASES and len(forbid) >= MIN_CASES, b.derivation
        assert {c["expect"] for c in allow} == {"T"}
        assert {c["expect"] for c in forbid} <= {"F", "not_T"}
        if b.effect == "basis" and has_threshold_or_window(b):
            probes = complement_probes(b)
            assert len(probes) >= MIN_CASES, b.derivation
            assert {c["expect"] for c in probes} == {"F"}


def test_complement_probes_sit_just_outside_each_window_and_threshold():
    # a basis on "not the 7-9 window": the probes are the window's first and last minutes
    probes = complement_probes(SIGNAL_BASIS_821)
    minutes = {(c["facts"]["minute"]) for c in probes}
    assert {420, 539} <= minutes
    # a notice basis: notice one minute short, outside the window
    probes = complement_probes(NOTICE_BASIS_821)
    assert any(c["facts"].get("notice_minutes") == 239 for c in probes)
    # a forbid has no complement probes
    assert complement_probes(FORBID_821) == []
    assert not has_threshold_or_window(rebuild(SIGNAL_BASIS_821,
                                               when={"in_window": {"fact": "open_at"},
                                                     "window": ALL_TIMES.model_dump()}))


def test_compiled_bindings_pass_their_tests():
    for b in [*FIXTURE_BINDINGS, *BINDINGS_GENERAL]:
        assert checks.test_binding(b) == [], b.derivation


def test_a_binding_encoding_the_wrong_window_fails_its_tests():
    w = window_of(FORBID_821)
    wrong = [
        {**w, "start": 435},                                      # starts 15 minutes late
        {**w, "end": 541},                                        # one minute too long
        {**w, "days": ["Mon", "Tue", "Wed", "Thu"]},              # Friday lost
        {**w, "except_federal_holidays": False},                  # holidays closed too
        {**w, "date_from": "06-01", "date_to": "09-30"},          # a season it does not have
    ]
    for window in wrong:
        bad = with_when(FORBID_821, {"in_window": {"fact": "open_at"}, "window": window})
        assert checks.test_binding(bad), window
    # a wrong threshold or comparison in the notice pair
    for b, op, k in ((NOTICE_BASIS_821, ">=", 239), (NOTICE_BASIS_821, ">", 240),
                     (NOTICE_FORBID_821, "<=", 240), (NOTICE_FORBID_821, "<", 180)):
        when = {"and": [b.when["and"][0], {"cmp": ["notice_minutes", op, k]}]}
        assert checks.test_binding(with_when(b, when)), (op, k)
    # a period-less basis holds "at all other times": the other periods are not among its own
    # parameters, so a wrong complement is the grid's to catch (next section); but parameters
    # of a period it encodes no part for are a failure
    grouped = rebuild(SIGNAL_BASIS_821, params_prov={**SIGNAL_BASIS_821.params_prov,
                                                     **FORBID_821.params_prov})
    assert checks.test_binding(grouped)
    # § 117.31(b) with a class missing, or with the conflict defaulted to "no conflict"
    classes = EMERGENCY_821.when["and"][0]["in"][1]
    short = {"and": [{"in": ["vessel_class", classes[:-1]]}, EMERGENCY_821.when["and"][1]]}
    assert checks.test_binding(with_when(EMERGENCY_821, short))
    defaulted = {"and": [EMERGENCY_821.when["and"][0],
                         {"not": {"eq": ["local_procedure_conflict", True]}},
                         {"known": "vessel_class"}]}
    assert checks.test_binding(with_when(EMERGENCY_821, defaulted))   # a shape it never writes
    lenient = {"or": [EMERGENCY_821.when, {"not": {"known": "local_procedure_conflict"}}]}
    assert checks.test_binding(with_when(EMERGENCY_821, lenient))


def test_a_basis_one_minute_too_wide_fails_a_complement_probe():
    # the on-signal basis of a seasonal period, widened by one day at each end
    seasonal = by_rule(BINDINGS_NOTICE_PERIOD, CARD_A.canonical_ref, "basis")
    assert checks.test_binding(seasonal) == []
    window = seasonal.when["window"] if "window" in seasonal.when else None
    assert window is not None and window["date_from"] == "04-01"
    wide = with_when(seasonal, {"in_window": {"fact": "open_at"},
                                "window": {**window, "date_from": "03-31"}})
    probe_failures = [c for c in complement_probes(seasonal)
                      if evaluate(wide.when, c["facts"]) is Tri.T]
    assert probe_failures and checks.test_binding(wide)


def test_unknown_and_ill_typed_facts_never_make_a_binding_true():
    _, forbid = boundary_cases(NOTICE_BASIS_821)
    unknown = [c for c in forbid if c["expect"] == "not_T"]
    assert unknown
    dropped = {f for c in unknown for f in ("open_at", "notice_minutes")
               if c["facts"].get(f) is None}
    assert dropped == {"open_at", "notice_minutes"}
    # a binding that treats a missing notice as enough fails
    lenient = {"or": [NOTICE_BASIS_821.when, {"and": [NOTICE_BASIS_821.when["and"][0],
                                                       {"not": {"known": "notice_minutes"}}]}]}
    assert checks.test_binding(with_when(NOTICE_BASIS_821, lenient))
    # P37 for § 117.31(b): an unknown class or conflict is never a True override
    _, forbid = boundary_cases(EMERGENCY_821)
    assert any(c["expect"] == "not_T" and "vessel_class" not in c["facts"] for c in forbid)
    assert any(c["expect"] == "not_T" and "local_procedure_conflict" not in c["facts"]
               for c in forbid)


def test_a_constant_basis_has_no_false_cases():
    """Ruling: § 117.5 with no specific rule is `const true`; it has no boundary, so its false
    list is empty and that is no failure."""
    (duty,) = [b for b in BINDINGS_GENERAL if b.rule_id == GENERAL_CARD.canonical_ref]
    assert duty.when == {"const": True}
    allow, forbid = boundary_cases(duty)
    assert len(allow) >= MIN_CASES and forbid == [] and complement_probes(duty) == []
    assert checks.test_binding(duty) == []
    assert checks.test_binding(with_when(duty, {"const": False}))


def test_an_exception_while_testing_is_a_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("evaluator down")

    monkeypatch.setattr(checks, "evaluate", boom)
    assert any("RuntimeError" in f for f in checks.test_binding(FORBID_821))


def test_crossing_window_cases_follow_p44():
    forbid = [b for b in BINDINGS_CROSSING if b.effect == "forbid"][0]
    allow, rest = boundary_cases(forbid)
    # Tuesday early hours are in the Monday night closure; Monday early hours are not
    tue = [c for c in allow if c["facts"]["weekday"] == "Tue" and c["facts"]["minute"] < 360]
    mon = [c for c in rest if c["facts"].get("weekday") == "Mon" and
           c["facts"].get("minute", 9999) < 360]
    assert tue and mon
    # a binding reading the minutes after midnight on their own day fails
    w = forbid.when["window"]
    same_day = {"or": [{"in_window": {"fact": "open_at"}, "window": {**w, "end": 1440}},
                       {"in_window": {"fact": "open_at"}, "window": {**w, "start": 0}}]}
    assert checks.test_binding(with_when(forbid, same_day))


# -- the gate's decision over a draw's bindings (§12.6 steps 1-6) ----------------------------------

def test_decide_bindings_follows_the_gate_steps():
    fri = datetime(2026, 8, 14, 7, 30)
    noon = datetime(2026, 8, 14, 12, 0)
    d = decide_bindings(BINDINGS_821, facts(fri, notice=600, vessel="commercial", conflict=False))
    assert d == RefDecision("deny", frozenset({"117.821"}), ())
    # a True § 117.31(b) discards the forbids it lists and allows
    d = decide_bindings(BINDINGS_821, facts(fri, vessel="distress", conflict=False))
    assert d == RefDecision("allow", frozenset(), ())
    # a True forbid listed by an Unknown overriding basis escalates with its missing facts
    d = decide_bindings(BINDINGS_821, facts(fri, notice=600, conflict=False))
    assert d == RefDecision("escalate", frozenset(), ("vessel_class",))
    # an Unknown forbid escalates
    d = decide_bindings(BINDINGS_821, facts(noon, vessel="commercial", conflict=False))
    assert d == RefDecision("escalate", frozenset(), ("notice_minutes",))
    # no basis at all is no permission (P15)
    forbid_only = [FORBID_821]
    assert decide_bindings(forbid_only, facts(noon)) == RefDecision("escalate", frozenset(), ())
    # an Unknown basis escalates with its missing facts
    assert decide_bindings([NOTICE_BASIS_821], facts(noon)) == RefDecision(
        "escalate", frozenset(), ("notice_minutes",))


# -- grid equivalence (§12.3, criterion B1) --------------------------------------------------------

def test_grid_equivalence_holds_on_a_simple_draw_and_catches_a_shifted_window():
    assert grid_equivalence(BINDINGS_821, REF_821) == []
    assert grid_equivalence(shift(BINDINGS_821, minutes=15), REF_821)


def test_grid_equivalence_holds_on_signal_with_a_crossing_closure():
    assert grid_equivalence(BINDINGS_SIGNAL, REF_SIGNAL) == []


def test_grid_equivalence_catches_wrong_references_and_dropped_rules():
    mism = grid_equivalence(shift(BINDINGS_821, minutes=15), REF_821)
    row = next(m for m in mism if m["open_at"] == "2026-08-10T07:00:00")
    assert row["reference"]["outcome"] in ("deny", "escalate")
    assert row["bindings"]["outcome"] != row["reference"]["outcome"] or \
        row["bindings"]["missing"] != row["reference"]["missing"]
    # the notice complement dropped: short notice escalates for lack of a basis instead of
    # being denied
    dropped = [b for b in BINDINGS_821 if b.binding_id != NOTICE_FORBID_821.binding_id]
    emergency = rebuild(EMERGENCY_821, overrides=[FORBID_821.binding_id])
    dropped = [emergency if b.binding_id == EMERGENCY_821.binding_id else b for b in dropped]
    assert grid_equivalence(dropped, REF_821)
    # a reference with another threshold, or without the holiday exception
    assert grid_equivalence(BINDINGS_821, RefDraw(**{**REF_821.__dict__, "notice_hours": 2}))
    w = REF_821.closed[0].model_copy(update={"except_federal_holidays": False})
    assert grid_equivalence(BINDINGS_821, RefDraw(**{**REF_821.__dict__, "closed": (w,)}))
    # § 117.31(b) dropped: emergencies are denied where the reference allows
    assert grid_equivalence([b for b in BINDINGS_821 if b != EMERGENCY_821], REF_821)


def test_grid_equivalence_counts_an_exception_as_a_mismatch(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("evaluator down")

    monkeypatch.setattr(checks, "evaluate", boom)
    mism = grid_equivalence(BINDINGS_SIGNAL, REF_SIGNAL)
    assert len(mism) == grid_size(REF_SIGNAL)
    assert all("RuntimeError" in m["bindings"]["error"] for m in mism[:5])


def test_grid_equivalence_refuses_bindings_of_two_draws():
    other = rebuild(FORBID_821, target={"tool": "schedule_opening",
                                        "selector": {"section": "117.821", "draw": 2}})
    with pytest.raises(ValueError, match="one draw"):
        grid_equivalence([*BINDINGS_821, other], REF_821)


# -- statuses --------------------------------------------------------------------------------------

def test_mark_tested_passes_good_draws_and_rejects_a_failing_draw_whole():
    good = mark_tested(BINDINGS_821)
    assert [b.status for b in good] == ["tested"] * len(BINDINGS_821)
    assert all(b.tests and b.tests[0]["failures"] == [] for b in good)
    assert [b.binding_id for b in good] == [b.binding_id for b in BINDINGS_821]
    bad_forbid = with_when(FORBID_821, {"in_window": {"fact": "open_at"},
                                        "window": {**window_of(FORBID_821), "start": 435}})
    mixed = [bad_forbid if b.binding_id == FORBID_821.binding_id else b for b in BINDINGS_821]
    out = mark_tested([*mixed, *BINDINGS_SIGNAL])
    statuses = {(b.target["selector"]["draw"], b.binding_version): b.status for b in out}
    assert statuses[(1, bad_forbid.binding_version)] == "rejected"
    assert {b.status for b in out[:len(mixed)]} == {"rejected"}       # the draw is blocked
    blocked = [b for b in out[:len(mixed)] if b.binding_id != bad_forbid.binding_id]
    assert all("blocked" in b.tests[0]["failures"][0] for b in blocked)
    # the statuses went through validation: a binding of another draw keeps its own result
    sig = mark_tested(BINDINGS_SIGNAL)
    assert {b.status for b in sig} == {"tested"}
    with pytest.raises(ValueError, match="proposed"):
        mark_tested(good)


def test_mark_tested_validates_the_new_status(monkeypatch):
    monkeypatch.setattr(checks, "TESTED", "passed")       # not a binding status
    with pytest.raises(ValueError):
        mark_tested(BINDINGS_SIGNAL)


# -- z3 stays out of everything but the analysis ---------------------------------------------------

def test_only_analysis_imports_z3():
    out = subprocess.run([sys.executable, "-c", "import adr_store.bindings.dsl, "
                          "adr_store.bindings.compile, adr_store.bindings.reference, "
                          "adr_store.bindings.checks, sys; print('z3' in sys.modules)"],
                         capture_output=True, text=True)
    assert out.stdout.strip() == "False"     # Task 18 adds decide and gate.server to this list
