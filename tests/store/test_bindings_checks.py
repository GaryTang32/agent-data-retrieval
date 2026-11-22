"""Binding tests (Phase 4 spec §12.3, P12, P32, P37, P44, P46; builder note 14; Task 16):
boundary cases and complement probes generated from each binding's parameters, the B1 grid
against the reference evaluator, the gate's decision steps they share, and the statuses they
give. Runs without z3; no model call."""

from __future__ import annotations

import random
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
from adr_store.bindings.compile import ALL_TIMES, compile_draw
from adr_store.bindings.dsl import DAYS, Binding, Tri, Window, evaluate
from adr_store.bindings.facts import derive_facts
from adr_store.bindings.reference import RefDecision, RefDraw
from tests.store.bindings_fixtures import (
    BINDINGS_821,
    BINDINGS_821_GROUPED,
    BINDINGS_CROSSING,
    BINDINGS_GENERAL,
    BINDINGS_NOTICE_PERIOD,
    BINDINGS_SAME_CARD_SIGNAL,
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
from tests.store.test_bindings_compile import (
    CARDS,
    IN_A,
    IN_B,
    WEEKDAYS,
    draw,
    g,
    on_signal,
    period,
    run,
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
        assert {c["expect"] for c in forbid} <= {"F", "U"}
        # probes are owed where the condition depends on its windows or thresholds
        if b.effect == "basis" and has_threshold_or_window(b) and any(
                c["expect"] == "F" for c in forbid):
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
    for bs in (BINDINGS_SAME_CARD_SIGNAL, BINDINGS_821_GROUPED):
        assert {b.status for b in mark_tested(bs)} == {"tested"}


def test_same_card_rules_keep_their_or_semantics():
    """C1: one binding per card and effect joins parts with `or`, and `or(T, U)` is T."""
    # on signal and its notice in one card: the basis is true at all times, so it owes no probe
    (basis,) = [b for b in BINDINGS_SAME_CARD_SIGNAL
                if b.effect == "basis" and b.rule_id == CARD_A.canonical_ref]
    assert "or" in basis.when and complement_probes(basis) == []
    allow, forbid = boundary_cases(basis)
    dropped = [c for c in allow if "notice_minutes" not in c["facts"]]
    assert dropped and all(evaluate(basis.when, c["facts"]) is Tri.T for c in dropped)
    # the closure and its notice complement in one card: inside the window, a missing notice
    # leaves the forbid true
    (forbid_b,) = [b for b in BINDINGS_821_GROUPED if b.effect == "forbid"]
    allow, _ = boundary_cases(forbid_b)
    inside = [c for c in allow if "notice_minutes" not in c["facts"]
              and 420 <= c["facts"]["minute"] < 540]
    assert inside and checks.test_binding(forbid_b) == []


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


def test_general_duty_inverted_to_a_forbid_fails_and_rejects_its_draw():
    """Fix round 2: § 117.5 binds as a basis; compiled as a forbid it would deny the openings
    the general duty requires."""
    (duty,) = [b for b in BINDINGS_NOTICE_PERIOD if b.rule_id == GENERAL_CARD.canonical_ref]
    assert checks.test_binding(duty) == []
    inverted = rebuild(duty, effect="forbid")
    assert "parameters: § 117.5 binds as a basis" in checks.test_binding(inverted)
    out = mark_tested([inverted if b.binding_id == duty.binding_id else b
                       for b in BINDINGS_NOTICE_PERIOD])
    assert {b.status for b in out} == {"rejected"}
    # the constant form too
    (const,) = [b for b in BINDINGS_GENERAL if b.rule_id == GENERAL_CARD.canonical_ref]
    assert checks.test_binding(rebuild(const, effect="forbid"))


def test_a_weekday_dropped_from_a_short_dated_window_fails():
    """Fix round 2: true cases fall on an admitted day of every listed weekday, so a weekday
    dropped from a short dated window is caught (the reviewer's 06-17..07-12 case)."""
    days = ("Mon", "Thu", "Fri", "Sun")
    bs = run(draw(periods=[on_signal("06-17", "07-12", start=360, end=1080, days=days)]))[0]
    basis = by_rule(bs, CARD_A.canonical_ref, "basis")
    assert checks.test_binding(basis) == []
    allow, _ = boundary_cases(basis)
    assert {c["facts"]["weekday"] for c in allow} >= set(days)
    for dropped in days:
        w = {**basis.when["window"], "days": [d for d in days if d != dropped]}
        bad = with_when(basis, {"in_window": {"fact": "open_at"}, "window": w})
        assert checks.test_binding(bad), dropped
    # a range that admits fewer weekdays than it lists uses those it admits
    one_day = run(draw(periods=[on_signal("12-25", "12-25", start=360, end=1080,
                                          days=days)]))[0]
    assert checks.test_binding(by_rule(one_day, CARD_A.canonical_ref, "basis")) == []


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
    unknown = [c for c in forbid if c["expect"] == "U"]
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
    assert any(c["expect"] == "U" and "vessel_class" not in c["facts"] for c in forbid)
    assert any(c["expect"] == "U" and "local_procedure_conflict" not in c["facts"]
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


def test_grid_equivalence_holds_on_grouped_rules_and_missing_counts_only_unknown_forbids():
    """I2: a True forbid listed by an Unknown overriding basis contributes no missing fact; the
    grouped 821 shape (closure and notice in one card) agrees with the reference everywhere."""
    fri = datetime(2026, 8, 14, 7, 30)
    d = decide_bindings(BINDINGS_821_GROUPED, facts(fri, conflict=False))
    assert d == RefDecision("escalate", frozenset(), ("vessel_class",))
    assert grid_equivalence(BINDINGS_821_GROUPED, REF_821) == []
    assert grid_equivalence(BINDINGS_SAME_CARD_SIGNAL, RefDraw(**{
        **REF_821.__dict__, "closed": ()})) == []


def test_grid_compares_denying_sections_and_missing_not_only_outcomes(monkeypatch):
    """M1: a mismatch in the denying sections or in the missing facts alone is a mismatch."""
    other = RefDraw(**{**REF_821.__dict__, "section": "117.999"})
    mism = grid_equivalence(BINDINGS_821, other)
    assert mism and all(m["bindings"]["outcome"] == m["reference"]["outcome"] == "deny"
                        for m in mism)
    real = checks._decide

    def extra_missing(*a, **k):
        d = real(*a, **k)
        return RefDecision(d.outcome, d.denying_sections, (*d.missing, "zzz")) \
            if d.outcome == "escalate" else d

    monkeypatch.setattr(checks, "_decide", extra_missing)
    mism = grid_equivalence(BINDINGS_821, REF_821)
    assert mism and all(m["bindings"]["outcome"] == m["reference"]["outcome"] == "escalate"
                        for m in mism)


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


def test_emergency_must_override_every_forbid_of_its_draw():
    """I3 (P32), without z3: an empty, partial or foreign override list rejects the draw."""
    for overrides in ([], [FORBID_821.binding_id],
                      [*EMERGENCY_821.overrides, "f" * 64]):
        bad = rebuild(EMERGENCY_821, overrides=overrides)
        assert checks.test_binding(bad) == []        # the binding alone cannot see its draw
        out = mark_tested([bad if b.binding_id == EMERGENCY_821.binding_id else b
                           for b in BINDINGS_821])
        assert {b.status for b in out} == {"rejected"}
        (em,) = [b for b in out if b.binding_id == EMERGENCY_821.binding_id]
        assert "§ 117.31(b)" in em.tests[0]["failures"][0]


def test_complements_must_negate_exactly_the_draws_periods():
    """Ruling 3: a period-less rule's "all other times" is checked against the periods its
    sibling bindings record (P46); a notice forbid over the wrong window fails."""
    w = window_of(FORBID_821)
    wrong = {"and": [{"not": {"in_window": {"fact": "open_at"}, "window": {**w, "start": 480}}},
                     NOTICE_FORBID_821.when["and"][1]]}
    bad = with_when(NOTICE_FORBID_821, wrong)
    assert checks.test_binding(bad) == []           # its own parameters hold no period
    out = mark_tested([bad if b.binding_id == NOTICE_FORBID_821.binding_id else b
                       for b in BINDINGS_821])
    assert {b.status for b in out} == {"rejected"}
    (nf,) = [b for b in out if b.binding_id == NOTICE_FORBID_821.binding_id]
    assert "P46" in nf.tests[0]["failures"][0]
    # all times instead of "not the window"
    everywhere = {"and": [{"in_window": {"fact": "open_at"}, "window": ALL_TIMES.model_dump()},
                          NOTICE_FORBID_821.when["and"][1]]}
    out = mark_tested([with_when(NOTICE_FORBID_821, everywhere)
                       if b.binding_id == NOTICE_FORBID_821.binding_id else b
                       for b in BINDINGS_821])
    assert {b.status for b in out} == {"rejected"}
    # § 117.5 over the wrong complement, in a draw with a gap
    (duty,) = [b for b in BINDINGS_NOTICE_PERIOD if b.rule_id == GENERAL_CARD.canonical_ref]
    inner = duty.when["not"]["or"]
    short = with_when(duty, {"not": inner[0]})
    assert checks.test_binding(short)               # its own parameters do hold the periods
    out = mark_tested([short if b.binding_id == duty.binding_id else b
                       for b in BINDINGS_NOTICE_PERIOD])
    assert {b.status for b in out} == {"rejected"}
    # § 117.5 at all times in a draw with periods, its own parameters stripped
    always = rebuild(duty, when={"const": True}, params_prov={})
    assert checks.test_binding(always) == []
    out = mark_tested([always if b.binding_id == duty.binding_id else b
                       for b in BINDINGS_NOTICE_PERIOD])
    (d,) = [b for b in out if b.binding_id == duty.binding_id]
    assert d.status == "rejected" and "§ 117.5 at all times" in d.tests[0]["failures"][0]


def test_mark_tested_validates_the_new_status(monkeypatch):
    monkeypatch.setattr(checks, "TESTED", "passed")       # not a binding status
    with pytest.raises(ValueError):
        mark_tested(BINDINGS_SIGNAL)


# -- z3 stays out of everything but the analysis ---------------------------------------------------

def test_only_analysis_imports_z3():
    out = subprocess.run([sys.executable, "-c", "import adr_store.bindings.dsl, "
                          "adr_store.bindings.compile, adr_store.bindings.reference, "
                          "adr_store.bindings.checks, adr_store.bindings.review, "
                          "adr_store.bindings.manifest, sys; print('z3' in sys.modules)"],
                         capture_output=True, text=True)
    assert out.stdout.strip() == "False"     # Task 18 adds decide and gate.server to this list


# -- compiler fuzz: every binding the compiler writes passes its tests (C1, ruling 3) --------------

FUZZ_SEED = 20261121
FUZZ_DRAWS = 200
_TIMES = [None, *range(0, 1441, 90)]
_DAY_SETS = [None, WEEKDAYS, ("Sat", "Sun"), ("Mon",), ("Tue", "Thu", "Sat"), DAYS]
_DATES = [None, None, ("04-01", "10-31"), ("11-01", "03-31"), ("12-31", "12-31"),
          ("02-28", "02-29"), ("06-15", "09-15")]


def _fuzz_period(rng: random.Random, simple: bool):
    effect = "need_not_open" if simple else rng.choice(
        ["need_not_open", "need_not_open", "on_signal", "notice_required"])
    start, end = rng.choice(_TIMES), rng.choice(_TIMES[1:])
    if start is None or rng.random() < 0.15:
        start = end = None                               # the whole day
    elif start == end % 1440:
        end = None if start is None else (start + 120) % 1440 or 1440
    dates = rng.choice(_DATES)
    return period(effect, start, end, days=rng.choice(_DAY_SETS),
                  holidays=rng.choice([None, True, False]), date_from=dates and dates[0],
                  date_to=dates and dates[1], at=rng.choice([IN_A, IN_B]))


def fuzz_draws(seed: int = FUZZ_SEED, n: int = FUZZ_DRAWS):
    """`n` random draws the compiler accepts (mixed shapes: closures, on-signal and notice
    periods, crossing windows, weekday sets, holiday exceptions, wrapping and leap-day dates,
    period-less rules, parameters in the same card or not), with their bindings."""
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        simple = rng.random() < 0.4
        periods = [_fuzz_period(rng, simple) for _ in range(rng.choice([0, 1, 1, 2, 3]))]
        basis = rng.choice(["on_signal", "advance_notice"] if simple else
                           [None, "on_signal", "on_signal", "advance_notice"])
        notice = rng.choice([None, 0, 1, 4, 24] if basis != "advance_notice" else [1, 4, 24])
        d = draw(n=len(out) + 1, notice_hours=notice, notice_at=rng.choice([IN_A, IN_B]),
                 periods=periods)
        if basis is not None:
            d = d.model_copy(update={"opening_basis": g(basis, rng.choice([IN_A, IN_B]))})
        bindings, problems = compile_draw("117.821", d, CARDS, GENERAL_CARD, EMERGENCY_CARD)
        if not problems:
            out.append((d, bindings))
    return out


def _ref_from_params(d) -> RefDraw | None:
    """The reference draw a simple-shape draw's parameters state, built here from the values
    (not by the compiler's `period_window`); None for any other draw."""
    basis = d.opening_basis.value
    if basis not in ("on_signal", "advance_notice") or any(
            p.effect.value != "need_not_open" for p in d.periods):
        return None
    windows = []
    for p in d.periods:
        start, end = p.start.value, p.end.value
        windows.append(Window(start=0 if start is None else start,
                              end=1440 if end is None else end,
                              days=tuple(p.days.value or DAYS),
                              except_federal_holidays=p.except_federal_holidays.value is True,
                              date_from=p.date_from.value, date_to=p.date_to.value))
    return RefDraw(section="117.821", draw=1, bridge=None, opens_on_signal=basis == "on_signal",
                   notice_hours=d.notice_hours.value or None, closed=tuple(windows))


def test_compiler_fuzz_every_binding_passes_its_tests():
    draws = fuzz_draws()
    assert len(draws) == FUZZ_DRAWS
    shapes = {(bool(d.periods), d.opening_basis.value, bool(d.notice_hours.value),
               any(p.start.value is not None and p.end.value is not None
                   and p.start.value > p.end.value for p in d.periods)) for d, _ in draws}
    assert len(shapes) >= 12             # the shapes are mixed, crossing windows among them
    failures = []
    for d, bindings in draws:
        for b in mark_tested(bindings):
            if b.status != "tested":
                failures.append((d.draw, b.derivation, b.tests[0]["failures"][:2]))
    assert failures == []


def test_compiler_fuzz_simple_draws_agree_with_the_reference_on_the_grid():
    simple = [(d, bs, _ref_from_params(d)) for d, bs in fuzz_draws()]
    simple = [x for x in simple if x[2] is not None]
    assert len(simple) >= 40
    # the grid is costly (1-3 s a draw): a fixed spread of the simple draws, closures and
    # crossing windows among them
    picked = simple[::max(1, len(simple) // 8)][:8]
    assert any(r.closed for _, _, r in picked) and any(r.notice_hours for _, _, r in picked)
    for d, bindings, ref in picked:
        assert grid_equivalence(bindings, ref) == [], d
