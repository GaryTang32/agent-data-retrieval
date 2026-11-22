"""The binding language `adr-dsl@1`: strong Kleene evaluation, half-open minute windows that
may cross midnight and wrap the year end, the construct checker, required facts, binding ids
and versions, and the `Binding` model (Phase 4 spec §12.1, §12.6; plan Task 14, Review Focus
2). Pure functions: no store, no model and nothing under `.cache/`."""

import hashlib
import json
from datetime import date, datetime
from typing import get_args

import pytest
from pydantic import ValidationError

from adr_store.bindings.dsl import (
    DAYS,
    IDENTITY_FIELDS,
    LANGUAGE,
    LOGIC_FIELDS,
    Binding,
    BindingStatus,
    Tri,
    Window,
    binding_ids,
    check_expr,
    evaluate,
    in_window,
    required_facts,
)

WEEKDAYS = DAYS[:5]


def W(start: int, end: int, days=DAYS, hol: bool = False, date_from=None, date_to=None):
    return Window(start=start, end=end, days=days, except_federal_holidays=hol,
                  date_from=date_from, date_to=date_to)


def win_dict(start=420, end=540, days=WEEKDAYS, hol=True, date_from=None, date_to=None) -> dict:
    return {"start": start, "end": end, "days": list(days), "except_federal_holidays": hol,
            "date_from": date_from, "date_to": date_to}


# T, F and U as expressions: constants, and a comparison on a fact the facts never hold
EXPR = {"T": {"const": True}, "F": {"const": False}, "U": {"cmp": ["absent_fact", ">=", 0]}}


# -- strong Kleene ---------------------------------------------------------------------------

@pytest.mark.parametrize("op,a,b,want", [("and", "T", "U", "U"), ("and", "F", "U", "F"),
    ("or", "T", "U", "T"), ("or", "F", "U", "U"), ("not", "U", None, "U")])
def test_strong_kleene(op, a, b, want):
    e = {"not": EXPR[a]} if op == "not" else {op: [EXPR[a], EXPR[b]]}
    assert evaluate(e, {}) is Tri(want)


# the full tables, written out (not computed): rows are the left operand, columns the right
AND_TABLE = [("T", "T", "T"), ("T", "F", "F"), ("T", "U", "U"),
             ("F", "T", "F"), ("F", "F", "F"), ("F", "U", "F"),
             ("U", "T", "U"), ("U", "F", "F"), ("U", "U", "U")]
OR_TABLE = [("T", "T", "T"), ("T", "F", "T"), ("T", "U", "T"),
            ("F", "T", "T"), ("F", "F", "F"), ("F", "U", "U"),
            ("U", "T", "T"), ("U", "F", "U"), ("U", "U", "U")]
NOT_TABLE = [("T", "F"), ("F", "T"), ("U", "U")]


@pytest.mark.parametrize("a,b,want", AND_TABLE)
def test_kleene_and_table(a, b, want):
    assert evaluate({"and": [EXPR[a], EXPR[b]]}, {}) is Tri(want)


@pytest.mark.parametrize("a,b,want", OR_TABLE)
def test_kleene_or_table(a, b, want):
    assert evaluate({"or": [EXPR[a], EXPR[b]]}, {}) is Tri(want)


@pytest.mark.parametrize("a,want", NOT_TABLE)
def test_kleene_not_table(a, want):
    assert evaluate({"not": EXPR[a]}, {}) is Tri(want)


@pytest.mark.parametrize("ops,and_want,or_want", [
    (["T", "T", "T"], "T", "T"), (["T", "U", "T"], "U", "T"), (["U", "U", "F"], "F", "U"),
    (["F", "F", "F"], "F", "F"), (["U"], "U", "U"), (["T"], "T", "T"), (["F", "U", "T"], "F", "T"),
])
def test_kleene_over_more_or_fewer_operands(ops, and_want, or_want):
    assert evaluate({"and": [EXPR[o] for o in ops]}, {}) is Tri(and_want)
    assert evaluate({"or": [EXPR[o] for o in ops]}, {}) is Tri(or_want)


def test_unknown_propagates_through_nesting():
    # not (U and T) = U; not (U and F) = T; (U or T) and not F = T
    assert evaluate({"not": {"and": [EXPR["U"], EXPR["T"]]}}, {}) is Tri.U
    assert evaluate({"not": {"and": [EXPR["U"], EXPR["F"]]}}, {}) is Tri.T
    assert evaluate({"and": [{"or": [EXPR["U"], EXPR["T"]]}, {"not": EXPR["F"]}]}, {}) is Tri.T


# -- the leaves ------------------------------------------------------------------------------

def test_missing_fact_makes_comparison_unknown():
    assert evaluate({"cmp": ["notice_minutes", ">=", 240]}, {}) is Tri.U
    assert evaluate({"known": "notice_minutes"}, {}) is Tri.F


@pytest.mark.parametrize("op,value,want", [
    (">=", 240, "T"), (">=", 239, "F"), (">", 241, "T"), (">", 240, "F"), ("<", 239, "T"),
    ("<", 240, "F"), ("<=", 240, "T"), ("<=", 241, "F"), ("==", 240, "T"), ("==", 0, "F"),
    ("!=", 0, "T"), ("!=", 240, "F"),
])
def test_cmp_operators_against_240(op, value, want):
    assert evaluate({"cmp": ["notice_minutes", op, 240]}, {"notice_minutes": value}) is Tri(want)


def test_a_null_or_ill_typed_fact_is_no_value():
    # silence (None) is absent; a value of the wrong type is no value of the construct's type
    assert evaluate({"cmp": ["notice_minutes", ">=", 240]}, {"notice_minutes": None}) is Tri.U
    assert evaluate({"cmp": ["notice_minutes", ">=", 240]}, {"notice_minutes": "300"}) is Tri.U
    assert evaluate({"cmp": ["notice_minutes", ">=", 0]}, {"notice_minutes": True}) is Tri.U
    assert evaluate({"eq": ["vessel_class", "distress"]}, {"vessel_class": 3}) is Tri.U
    assert evaluate({"in": ["vessel_class", ["distress"]]}, {"vessel_class": None}) is Tri.U
    assert evaluate({"known": "vessel_class"}, {"vessel_class": None}) is Tri.F
    # known agrees: a fact no construct can read is not known (P: Minor 4 of the review)
    for bad in (None, 2.5, [1], {"a": 1}, b"x"):
        assert evaluate({"known": "notice_minutes"}, {"notice_minutes": bad}) is Tri.F, bad
    for good in (0, -1, "distress", False, "2026-08-14T07:30:00"):
        assert evaluate({"known": "notice_minutes"}, {"notice_minutes": good}) is Tri.T, good


def test_eq_in_known_const():
    facts = {"vessel_class": "distress", "local_procedure_conflict": False}
    assert evaluate({"eq": ["vessel_class", "distress"]}, facts) is Tri.T
    assert evaluate({"eq": ["vessel_class", "commercial"]}, facts) is Tri.F
    assert evaluate({"eq": ["vessel_class", "distress"]}, {}) is Tri.U
    assert evaluate({"in": ["vessel_class", ["public_safety", "distress"]]}, facts) is Tri.T
    assert evaluate({"in": ["vessel_class", ["commercial"]]}, facts) is Tri.F
    assert evaluate({"in": ["vessel_class", ["commercial"]]}, {}) is Tri.U
    # a bool fact is an enum of two values: eq takes a bool comparand
    assert evaluate({"eq": ["local_procedure_conflict", False]}, facts) is Tri.T
    assert evaluate({"eq": ["local_procedure_conflict", True]}, facts) is Tri.F
    assert evaluate({"eq": ["local_procedure_conflict", False]}, {}) is Tri.U
    # a bool fact does not equal its name as a string, and a string fact is not a bool
    assert evaluate({"eq": ["local_procedure_conflict", "false"]}, facts) is Tri.U
    assert evaluate({"eq": ["vessel_class", True]}, facts) is Tri.U
    assert evaluate({"known": "vessel_class"}, facts) is Tri.T
    assert evaluate({"const": True}, {}) is Tri.T and evaluate({"const": False}, {}) is Tri.F


def test_emergency_basis_shape_is_three_valued():
    """§ 117.31(b): vessel_class in the emergency classes and not local_procedure_conflict."""
    e = {"and": [{"in": ["vessel_class", ["public_safety", "distress"]]},
                 {"not": {"eq": ["local_procedure_conflict", True]}}]}
    assert evaluate(e, {"vessel_class": "distress", "local_procedure_conflict": False}) is Tri.T
    assert evaluate(e, {"vessel_class": "distress", "local_procedure_conflict": True}) is Tri.F
    assert evaluate(e, {"vessel_class": "distress"}) is Tri.U
    assert evaluate(e, {"vessel_class": "commercial"}) is Tri.F       # F and U = F
    assert evaluate(e, {"local_procedure_conflict": False}) is Tri.U
    assert evaluate(e, {}) is Tri.U


# -- windows ---------------------------------------------------------------------------------

def D(md: str, year: int = 2028) -> date:
    """A day of a leap year, so 02-29 exists (2028-01-03 is a Monday)."""
    return date.fromisoformat(f"{year}-{md}")


@pytest.mark.parametrize("minute,inside", [(419, False), (420, True), (539, True), (540, False)])
def test_window_is_half_open(minute, inside):                      # Review Focus 2
    assert in_window(W(420, 540, WEEKDAYS), minute, date(2026, 8, 10)) is inside   # a Monday


def test_window_crossing_midnight_and_wrapping_dates():
    w = Window(start=1380, end=360, days=DAYS, except_federal_holidays=False, date_from="11-01",
               date_to="03-31")
    assert in_window(w, 1400, date(2026, 12, 31)) and in_window(w, 100, date(2027, 1, 1))
    assert not in_window(w, 1400, date(2027, 4, 1))


@pytest.mark.parametrize("minute,inside", [(1379, False), (1380, True), (1439, True), (0, True),
                                           (359, True), (360, False), (720, False)])
def test_crossing_midnight_minutes(minute, inside):
    assert in_window(W(1380, 360), minute, date(2026, 6, 6)) is inside


# P44: the minutes after midnight of a crossing window belong to the night that started the
# day before, for the days, the holiday exception and the date range alike

@pytest.mark.parametrize("day,minute,inside", [
    (date(2026, 8, 10), 1390, True),     # Monday 23:10: the Monday night
    (date(2026, 8, 11), 60, True),       # Tuesday 01:00: still the Monday night
    (date(2026, 8, 10), 60, False),      # Monday 01:00: the Sunday night
    (date(2026, 8, 11), 1390, False),    # Tuesday 23:10: the Tuesday night
    (date(2026, 8, 11), 360, False),     # Tuesday 06:00: half-open end
])
def test_crossing_window_belongs_to_the_night_it_starts(day, minute, inside):
    assert in_window(W(1380, 360, ("Mon",)), minute, day) is inside


@pytest.mark.parametrize("day,minute,inside", [
    (date(2027, 4, 1), 120, True),       # the night of 03-31 into 04-01
    (date(2026, 12, 1), 120, False),     # the night of 11-30 into 12-01
    (date(2026, 12, 1), 1230, True),     # 12-01 20:30 starts the first night
    (date(2027, 3, 31), 1230, True),
    (date(2027, 4, 1), 1230, False),
    (date(2027, 1, 1), 120, True),       # the year wrap: the night of 12-31
    (date(2027, 4, 1), 240, False),
])
def test_crossing_window_date_range_follows_the_start_night(day, minute, inside):
    w = W(1200, 240, date_from="12-01", date_to="03-31")      # Dec 1 - Mar 31, 8 p.m. - 4 a.m.
    assert in_window(w, minute, day) is inside


def test_crossing_window_holiday_exception_covers_the_next_morning():
    w = W(1380, 360, WEEKDAYS, hol=True)
    # Friday 2026-07-03 is the observed Independence Day: no window that night...
    assert not in_window(w, 1400, date(2026, 7, 3))
    assert not in_window(w, 60, date(2026, 7, 4))          # ...nor in its early hours
    # Thursday 2026-07-02 is an ordinary day: its night runs into the holiday morning
    assert in_window(w, 1400, date(2026, 7, 2)) and in_window(w, 60, date(2026, 7, 3))
    # Monday 2026-09-07 is Labor Day: the early hours belong to Sunday's night (not a weekday)
    assert not in_window(w, 60, date(2026, 9, 7)) and in_window(w, 60, date(2026, 9, 8)) is False
    assert in_window(w, 60, date(2026, 9, 9))               # Tuesday's night, Wednesday 01:00
    # New Year's Day 2027 is a Friday holiday; the night of Thursday 12-31 runs into it
    assert in_window(w, 60, date(2027, 1, 1)) and not in_window(w, 60, date(2027, 1, 2))


@pytest.mark.parametrize("md,inside", [("10-31", False), ("11-01", True), ("12-31", True),
                                       ("01-01", True), ("02-29", True), ("03-31", True),
                                       ("04-01", False), ("07-04", False)])
def test_wrapping_date_range_is_inclusive_at_both_ends(md, inside):
    assert in_window(W(0, 1440, date_from="11-01", date_to="03-31"), 600, D(md)) is inside


@pytest.mark.parametrize("md,inside", [("03-31", False), ("04-01", True), ("07-04", True),
                                       ("10-31", True), ("11-01", False)])
def test_plain_date_range(md, inside):
    assert in_window(W(0, 1440, date_from="04-01", date_to="10-31"), 600, D(md)) is inside


def test_single_day_date_range():
    w = W(1320, 1440, date_from="07-04", date_to="07-04")
    assert in_window(w, 1320, date(2026, 7, 4))
    assert not in_window(w, 1320, date(2026, 7, 3))


def test_days_and_holiday_exception():
    w = W(420, 540, WEEKDAYS, hol=True)
    assert in_window(w, 450, date(2026, 8, 14))                 # an ordinary Friday
    assert not in_window(w, 450, date(2026, 8, 15))             # Saturday
    assert not in_window(w, 450, date(2026, 7, 3))              # a holiday Friday: no window
    assert in_window(W(420, 540, WEEKDAYS, hol=False), 450, date(2026, 7, 3))
    assert not in_window(w, 450, date(2027, 12, 31))            # observed New Year's Day 2028


def test_all_day_window():
    w = W(0, 1440)
    assert all(in_window(w, m, date(2026, 7, d)) for m in (0, 719, 1439) for d in range(1, 8))


def test_in_window_refuses_inputs_outside_its_domain():
    w = W(420, 540)
    for args in [(1440, date(2026, 8, 14)), (-1, date(2026, 8, 14)), (True, date(2026, 8, 14)),
                 (420, "2026-08-14"), (420, datetime(2026, 8, 14, 7, 0))]:
        with pytest.raises(ValueError):
            in_window(w, *args)


@pytest.mark.parametrize("bad", [
    {"start": -1}, {"start": 1440}, {"end": 0}, {"end": 1441}, {"start": 420, "end": 420},
    {"days": ()}, {"days": ("Mon", "Funday")}, {"days": ("Tue", "Mon")}, {"days": ("Mon", "Mon")},
    {"date_from": "04-01", "date_to": None}, {"date_from": "13-01", "date_to": "12-01"},
    {"date_from": "02-30", "date_to": "03-01"}, {"date_from": "4-1", "date_to": "10-31"},
    {"start": "420"}, {"start": 420.0}, {"start": True}, {"except_federal_holidays": "yes"},
])
def test_window_model_refuses_out_of_range_fields(bad):
    fields = {"start": 420, "end": 540, "days": WEEKDAYS, "except_federal_holidays": False,
              "date_from": None, "date_to": None, **bad}
    with pytest.raises(ValidationError):
        Window(**fields)


def test_window_is_frozen_and_accepts_leap_day():
    w = W(0, 1440, date_from="02-29", date_to="02-29")
    with pytest.raises(ValidationError):
        w.start = 5


def test_in_window_expression_reads_the_open_at_fact():
    e = {"in_window": {"fact": "open_at"}, "window": win_dict()}
    assert evaluate(e, {"open_at": "2026-08-14T07:30:00"}) is Tri.T     # an ordinary Friday
    assert evaluate(e, {"open_at": "2026-08-14T09:00:00"}) is Tri.F     # half-open end
    assert evaluate(e, {"open_at": "2026-07-03T07:30:00"}) is Tri.F     # observed holiday
    assert evaluate(e, {"open_at": "2026-08-16T07:30:00"}) is Tri.F     # Sunday
    # the derived parts are not read: open_at is the fact (P44 needs the day before)
    assert evaluate(e, {"minute": 450, "weekday": "Fri", "month_day": "08-14",
                        "federal_holiday": False}) is Tri.U
    for bad in (None, "2026-08-14", "2026-08-14T07:30:00+00:00", "yesterday", 450,
                datetime(2026, 8, 14, 7, 30)):
        assert evaluate(e, {"open_at": bad}) is Tri.U, bad
    # a Window instance and its dict evaluate alike
    e2 = {"in_window": {"fact": "open_at"}, "window": Window(**win_dict())}
    assert evaluate(e2, {"open_at": "2026-08-14T07:30:00"}) is Tri.T


# -- check_expr ------------------------------------------------------------------------------

def test_check_expr_refuses_unknown_constructs():
    assert check_expr({"python": "os.system('x')"}) == ["unknown construct 'python'"]


GOOD = [
    {"const": True},
    {"known": "notice_minutes"},
    {"cmp": ["notice_minutes", ">=", 240]},
    {"eq": ["vessel_class", "distress"]},
    {"eq": ["local_procedure_conflict", False]},
    {"in": ["vessel_class", ["distress", "rescue_salvage"]]},
    {"in_window": {"fact": "open_at"}, "window": win_dict()},
    {"in_window": {"fact": "open_at"}, "window": Window(**win_dict())},
    {"in_window": {"fact": "open_at"},
     "window": win_dict(1380, 360, DAYS, False, "11-01", "03-31")},
    {"not": {"const": False}},
    {"and": [{"const": True}]},
    {"or": [{"cmp": ["notice_minutes", "<", 240]}, {"and": [{"known": "x"}, {"not": {
        "in_window": {"fact": "open_at"}, "window": win_dict()}}]}]},
]


@pytest.mark.parametrize("e", GOOD)
def test_check_expr_accepts_every_construct(e):
    assert check_expr(e) == []


@pytest.mark.parametrize("e,problems", [
    ([], ["expression must be an object, got list"]),
    ("const", ["expression must be an object, got str"]),
    ({}, ["empty expression"]),
    ({"and": [{"const": True}], "or": [{"const": True}]}, ["more than one construct: and, or"]),
    ({"python": 1, "eval": 2}, ["unknown construct 'eval'", "unknown construct 'python'"]),
    ({"window": win_dict()}, ["'window' outside in_window"]),
    # arities
    ({"and": []}, ["and: expects a non-empty list of expressions"]),
    ({"or": {"const": True}}, ["or: expects a non-empty list of expressions"]),
    ({"not": [{"const": True}]}, ["not: expects one expression"]),
    ({"cmp": ["notice_minutes", ">="]}, ["cmp: expects [fact, op, int]"]),
    ({"cmp": ["notice_minutes", ">=", 240, 1]}, ["cmp: expects [fact, op, int]"]),
    ({"eq": ["vessel_class"]}, ["eq: expects [fact, str or bool]"]),
    ({"in": ["vessel_class", "distress"]}, ["in: expects [fact, [str, ...]]"]),
    ({"in": ["vessel_class", []]}, ["in: expects [fact, [str, ...]]"]),
    ({"in": ["vessel_class", ["distress", 3]]}, ["in: expects [fact, [str, ...]]"]),
    ({"known": ["x"]}, ["known: fact must be a non-empty string"]),
    ({"const": 1}, ["const: expects a bool"]),
    ({"in_window": {"fact": "open_at"}}, ["in_window: needs a window"]),
    ({"in_window": "open_at", "window": win_dict()}, ['in_window: expects {"fact": "open_at"}']),
    ({"in_window": {"fact": "notice_received_at"}, "window": win_dict()},
     ['in_window: expects {"fact": "open_at"}']),
    # comparands, operators and facts
    ({"cmp": ["notice_minutes", ">=", 240.0]}, ["cmp: comparand must be an int, got float"]),
    ({"cmp": ["notice_minutes", ">=", "240"]}, ["cmp: comparand must be an int, got str"]),
    ({"cmp": ["notice_minutes", ">=", True]}, ["cmp: comparand must be an int, got bool"]),
    ({"cmp": ["notice_minutes", "=>", 240]}, ["cmp: unknown operator '=>'"]),
    ({"cmp": ["notice_minutes", "in", 240]}, ["cmp: unknown operator 'in'"]),
    ({"cmp": ["", ">=", 240]}, ["cmp: fact must be a non-empty string"]),
    ({"eq": ["vessel_class", 3]}, ["eq: comparand must be a str or a bool, got int"]),
])
def test_check_expr_problems(e, problems):
    assert check_expr(e) == problems


@pytest.mark.parametrize("window,needle", [
    (win_dict(start=-5), "start"), (win_dict(end=1441), "end"), (win_dict(start=540, end=540),
                                                                 "start"),
    (win_dict(days=["Mon", "Holiday"]), "days"), (win_dict(date_from="02-30", date_to="03-01"),
                                                  "date"),
    ({**win_dict(), "extra": 1}, "extra"), ({k: v for k, v in win_dict().items() if k != "days"},
                                            "days"),
])
def test_check_expr_refuses_a_window_with_fields_out_of_range(window, needle):
    problems = check_expr({"in_window": {"fact": "open_at"}, "window": window})
    assert len(problems) == 1 and problems[0].startswith("in_window.window: ")
    assert needle in problems[0]


def test_check_expr_recurses_and_names_the_path():
    e = {"and": [{"const": True},
                 {"or": [{"cmp": ["notice_minutes", "=>", 240]},
                         {"not": {"python": "x"}}]},
                 {"in_window": {"fact": "open_at"}, "window": win_dict(end=2000)}]}
    problems = check_expr(e)
    assert problems[:2] == ["and[1].or[0]: cmp: unknown operator '=>'",
                            "and[1].or[1].not: unknown construct 'python'"]
    assert len(problems) == 3 and problems[2].startswith("and[2]: in_window.window: ")


def test_evaluate_refuses_a_malformed_expression():
    with pytest.raises(ValueError, match="unknown construct 'python'"):
        evaluate({"python": "os.system('x')"}, {})
    with pytest.raises(ValueError):
        evaluate({"and": [{"cmp": ["notice_minutes", ">=", "240"]}]}, {"notice_minutes": 300})


# -- required facts --------------------------------------------------------------------------

def test_required_facts_sorted_unique():
    e = {"or": [{"and": [{"in_window": {"fact": "open_at"}, "window": win_dict()},
                         {"cmp": ["notice_minutes", "<", 240]}]},
                {"and": [{"in": ["vessel_class", ["distress"]]},
                         {"not": {"eq": ["local_procedure_conflict", True]}},
                         {"known": "notice_minutes"}, {"const": True}]}]}
    assert required_facts(e) == ["local_procedure_conflict", "notice_minutes", "open_at",
                                 "vessel_class"]
    assert required_facts({"const": False}) == []


def test_required_facts_refuses_what_check_expr_refuses():
    for bad in ({"python": "x"}, {"and": [{"known": "x"}, {"cmp": ["y", "=>", 1]}]}, [], {}):
        with pytest.raises(ValueError):
            required_facts(bad)


# -- ids and versions ------------------------------------------------------------------------

CORE = {"rule_id": "33 CFR 117.1081(b)", "rule_version": "0123456789ab", "doc_id": "d" * 64,
        "target": {"tool": "schedule_opening", "selector": {"section": "117.1081", "draw": 2}},
        "effect": "forbid",
        "when": {"in_window": {"fact": "open_at"}, "window": win_dict()},
        "overrides": []}


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_binding_ids_are_sha256_of_canonical_identity_and_logic():
    bid, ver = binding_ids(CORE)
    ident = {k: CORE[k] for k in IDENTITY_FIELDS}
    logic = {"language": LANGUAGE, "when": CORE["when"], "overrides": []}
    assert bid == hashlib.sha256(canon(ident).encode("utf-8")).hexdigest()
    assert ver == hashlib.sha256(canon(logic).encode("utf-8")).hexdigest()
    assert set(IDENTITY_FIELDS).isdisjoint(LOGIC_FIELDS)


def test_binding_ids_ignore_key_order():
    def reverse(o):
        if isinstance(o, dict):
            return {k: reverse(o[k]) for k in reversed(list(o))}
        return [reverse(x) for x in o] if isinstance(o, list) else o
    assert binding_ids(reverse(CORE)) == binding_ids(CORE)


@pytest.mark.parametrize("field,value", [
    ("rule_id", "33 CFR 117.1081(c)"), ("rule_version", "ba9876543210"), ("doc_id", "e" * 64),
    ("target", {"tool": "schedule_opening", "selector": {"section": "117.1081", "draw": 3}}),
    ("effect", "basis"),
])
def test_identity_fields_move_the_id_only(field, value):
    bid, ver = binding_ids(CORE)
    bid2, ver2 = binding_ids({**CORE, field: value})
    assert bid2 != bid and ver2 == ver


@pytest.mark.parametrize("field,value", [
    ("when", {"in_window": {"fact": "open_at"}, "window": win_dict(end=541)}),
    ("when", {"not": {"in_window": {"fact": "open_at"}, "window": win_dict()}}),
    ("overrides", ["f" * 64]),
])
def test_logic_fields_move_the_version_only(field, value):
    bid, ver = binding_ids(CORE)
    bid2, ver2 = binding_ids({**CORE, field: value})
    assert bid2 == bid and ver2 != ver


def test_other_fields_move_neither_and_overrides_are_a_set():
    rest = {"binding_id": "x", "binding_version": "y", "status": "signed_off", "tests": [{"a": 1}],
            "review": {"verdict": "approve"}, "derivation": "anything", "params_prov": {"q": "z"},
            "required_facts": ["open_at"], "analysis": {"vacuous": []}, "verifier": "v"}
    assert binding_ids({**CORE, **rest}) == binding_ids(CORE)
    two = {**CORE, "effect": "basis", "overrides": ["a" * 64, "b" * 64]}
    assert binding_ids(two) == binding_ids({**two, "overrides": ["b" * 64, "a" * 64]})
    # a Window instance hashes like its dict
    assert binding_ids({**CORE, "when": {"in_window": {"fact": "open_at"},
                                         "window": Window(**win_dict())}}) == binding_ids(CORE)


def test_binding_ids_need_the_identity_and_the_logic():
    for k in (*IDENTITY_FIELDS, "when"):
        with pytest.raises(ValueError, match=k):
            binding_ids({f: v for f, v in CORE.items() if f != k})
    # overrides defaults to none, as on the model
    assert binding_ids({f: v for f, v in CORE.items() if f != "overrides"}) == binding_ids(CORE)


# -- the Binding model -----------------------------------------------------------------------

def binding(**over) -> Binding:
    """A binding whose ids are computed from its fields unless given."""
    fields = {**CORE, "required_facts": ["open_at"], "params_prov": {}, "status": "proposed",
              "derivation": "need not open 7 to 9 a.m. weekdays", **over}
    bid, ver = binding_ids(fields)
    fields.setdefault("binding_id", bid)
    fields.setdefault("binding_version", ver)
    return Binding(**fields)


def test_binding_model_round_trips_through_json():
    b = binding()
    again = Binding.model_validate_json(b.model_dump_json())
    assert again == b and again.overrides == [] and again.verifier is None
    assert binding_ids(again.model_dump()) == (b.binding_id, b.binding_version)


def test_binding_model_refuses_bad_fields():
    with pytest.raises(ValidationError, match="unknown construct"):
        binding(when={"python": "x"})
    with pytest.raises(ValidationError):
        binding(effect="allow")
    with pytest.raises(ValidationError):
        binding(status="approved")
    with pytest.raises(ValidationError, match="overrides"):
        binding(effect="forbid", overrides=["a" * 64])         # only a basis overrides
    with pytest.raises(ValidationError):
        binding(surprise=1)
    assert binding(effect="basis", overrides=["a" * 64]).overrides == ["a" * 64]


def test_binding_model_checks_its_own_ids_and_required_facts():
    bid, ver = binding_ids(CORE)
    with pytest.raises(ValidationError, match="binding_id"):
        binding(binding_id="0" * 64)
    with pytest.raises(ValidationError, match="binding_version"):
        binding(binding_version="0" * 64)
    with pytest.raises(ValidationError, match="binding_id"):      # ids of another identity
        binding(binding_id=bid, binding_version=ver, rule_id="33 CFR 117.1081(c)")
    with pytest.raises(ValidationError, match="binding_version"):  # ids of another condition
        binding(binding_id=bid, binding_version=ver, when={"const": True}, required_facts=[])
    with pytest.raises(ValidationError, match="required_facts"):
        binding(required_facts=["open_at", "notice_minutes"])
    with pytest.raises(ValidationError, match="required_facts"):
        binding(required_facts=[])
    b = binding(when={"and": [{"in_window": {"fact": "open_at"}, "window": win_dict()},
                              {"cmp": ["notice_minutes", "<", 240]}]},
                required_facts=["notice_minutes", "open_at"])
    assert (b.binding_id, b.binding_version) == binding_ids(b.model_dump())


def test_duplicate_overrides_hash_as_one():
    one = {**CORE, "effect": "basis", "overrides": ["a" * 64]}
    assert binding_ids({**one, "overrides": ["a" * 64, "a" * 64]}) == binding_ids(one)


def test_binding_status_is_the_envelope_literal():
    from adr_store.units.envelope import BindingStatus as EnvelopeStatus
    assert get_args(BindingStatus) == get_args(EnvelopeStatus)
    assert LANGUAGE == "adr-dsl@1"
