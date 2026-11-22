"""The binding compiler (Phase 4 spec §12.2, P14, P32, P37, P44; builder note 13; Task 15):
bindings from the enrichment's typed parameters, one set per draw, `covers_all` at critical
points, the derivation sentence and E2 against both Phase 3 passes. Store-free: the cards are
synthetic units whose spans hold the parameter quotes; no model call."""

from __future__ import annotations

import itertools
import random
from datetime import date, datetime, timedelta

import pytest

from adr_store.bindings.compile import (
    EMERGENCY,
    GENERAL_DUTY,
    compile_bindings,
    compile_draw,
    covers_all,
    sentence,
)
from adr_store.bindings.dsl import DAYS, Binding, Tri, Window, evaluate, in_window
from adr_store.bindings.enrich import (
    DrawParams,
    Grounded,
    Period,
    SectionEnrichment,
    e2_agreement,
)
from adr_store.bindings.facts import EMERGENCY_CLASSES, derive_facts, is_federal_holiday
from adr_store.tables.extract import ABSENT, Facts, Value
from adr_store.tables.provenance import RowRecord, ValueProv
from tests.store.units_fixtures import D1, sample_unit

WEEKDAYS = DAYS[:5]
OPEN_AT = datetime(2026, 8, 12, 10, 0)          # a Wednesday, no holiday


def card(ref: str, start: int, end: int, text: str | None = None, doc_id: str = D1):
    """A rule card unit of `doc_id` whose source span is [start, end)."""
    text = text or f"The provision {ref} need not open."
    u = sample_unit(ref=ref, text=text, doc_id=doc_id)
    ref0 = u.source_refs[0].model_copy(update={"start": start, "end": end})
    return u.model_copy(update={"source_refs": [ref0]})


GENERAL_CARD = card("33 CFR 117.5(p1)", 100, 300, "Except as otherwise authorized, drawbridges "
                    "must open promptly.")
EMERGENCY_CARD = card("33 CFR 117.31(b)", 400, 700, "When a drawtender receives notice, the "
                      "drawtender shall take all reasonable measures to have the draw opened.")
CARD_A = card("33 CFR 117.821(a)", 1000, 1200)
CARD_B = card("33 CFR 117.821(b)", 1200, 1400)
CARDS = [CARD_A, CARD_B]
IN_A, IN_B = 1010, 1210         # offsets inside the spans of (a) and (b)


def g(value, at: int = IN_A, *, quote: str = "q", status: str = "verified",
      null_reason: str | None = None) -> Grounded:
    if value is None:
        return Grounded(value=None, quote=None, start=None, end=None, status=None,
                        null_reason=null_reason or "absent")
    return Grounded(value=value, quote=quote, start=at, end=at + len(quote), status=status,
                    null_reason=None)


NONE = g(None)


def period(effect: str, start=None, end=None, *, days=None, holidays=None, date_from=None,
           date_to=None, at: int = IN_A, readable: bool | None = True, qualifiers=(),
           conditions=()) -> Period:
    def opt(v):
        return NONE if v is None else g(v, at)

    return Period(effect=g(effect, at), start=opt(start), end=opt(end),
                  days=NONE if days is None else g(list(days), at),
                  except_federal_holidays=opt(holidays), date_from=opt(date_from),
                  date_to=opt(date_to), window_grammar_agrees=None,
                  window_readable=readable if effect == "need_not_open" else None,
                  window_quote=None,
                  sentence_qualifiers=list(qualifiers), sentence_conditions=list(conditions))


def closed(start, end, **kw) -> Period:
    return period("need_not_open", start, end, **kw)


def on_signal(date_from=None, date_to=None, start=None, end=None, **kw) -> Period:
    return period("on_signal", start, end, date_from=date_from, date_to=date_to, **kw)


def notice_period(start=None, end=None, **kw) -> Period:
    return period("notice_required", start, end, **kw)


def draw(*, n: int = 1, bridge: str = "Main Street drawbridge", notice_hours=None,
         opening_basis=None, periods=(), notice_at: int = IN_B, **kw) -> DrawParams:
    return DrawParams(draw=n, bridge=g(bridge), mile=g(3.4),
                      opening_basis=NONE if opening_basis is None else g(opening_basis),
                      notice_hours=NONE if notice_hours is None else g(notice_hours, notice_at),
                      periods=list(periods), sentence_qualifiers=list(kw.get("qualifiers", ())))


def facts(at: datetime = OPEN_AT, *, notice: int | None = None, vessel: str | None = None,
          conflict: bool | None = None) -> dict:
    record = {}
    if notice is not None:
        record["notice_received_at"] = {"value": (at - timedelta(minutes=notice)).isoformat()}
    if vessel is not None:
        record["vessel_class"] = {"value": vessel}
    if conflict is not None:
        record["local_procedure_conflict"] = {"value": conflict}
    return derive_facts(at, record)


def run(d: DrawParams, section: str = "117.821"):
    return compile_draw(section, d, CARDS, GENERAL_CARD, EMERGENCY_CARD)


def specific(bs: list[Binding]) -> list[Binding]:
    return [b for b in bs if b.rule_id not in (GENERAL_CARD.canonical_ref,
                                               EMERGENCY_CARD.canonical_ref)]


# -- the compiler, per rule shape (§12.2) ----------------------------------------------------------

def test_notice_rule_compiles_basis_and_its_complement():
    bs = run(draw(notice_hours=4, periods=[]))[0]
    whens = {b.effect: b.when for b in bs if b.rule_id != EMERGENCY_CARD.canonical_ref}
    assert set(whens) == {"basis", "forbid"}
    assert evaluate(whens["basis"], facts(notice=240)) is Tri.T
    assert evaluate(whens["forbid"], facts(notice=239)) is Tri.T
    # the complement, written out: exactly one of them holds at every notice
    assert evaluate(whens["basis"], facts(notice=239)) is Tri.F
    assert evaluate(whens["forbid"], facts(notice=240)) is Tri.F
    # an unknown notice is unknown for both, never a default (P37)
    assert evaluate(whens["basis"], facts()) is Tri.U
    assert evaluate(whens["forbid"], facts()) is Tri.U
    # the notice rule comes from the card that holds the notice quote
    assert {b.rule_id for b in specific(bs)} == {CARD_B.canonical_ref}


def test_notice_in_a_period_holds_only_in_the_period():
    bs = run(draw(notice_hours=24, periods=[
        notice_period(1200, 360, at=IN_B)]))[0]         # 8 p.m. to 6 a.m., crossing midnight
    whens = {b.effect: b.when for b in specific(bs)}
    night, day = datetime(2026, 8, 12, 23, 0), datetime(2026, 8, 12, 12, 0)
    assert evaluate(whens["forbid"], facts(night, notice=60)) is Tri.T
    assert evaluate(whens["forbid"], facts(day, notice=60)) is Tri.F
    assert evaluate(whens["basis"], facts(night, notice=24 * 60)) is Tri.T
    # the period leaves the day open, so § 117.5 is the basis there and only there
    general = next(b for b in bs if b.rule_id == GENERAL_CARD.canonical_ref)
    assert evaluate(general.when, facts(day)) is Tri.T
    assert evaluate(general.when, facts(night)) is Tri.F


def test_a_closed_window_compiles_a_forbid_and_its_period_less_rest_is_general_duty():
    bs, problems = run(draw(periods=[closed(420, 540, days=WEEKDAYS, holidays=True)]))
    assert problems == []
    (forbid,) = [b for b in bs if b.effect == "forbid"]
    assert forbid.rule_id == CARD_A.canonical_ref and forbid.status == "proposed"
    assert forbid.target == {"tool": "schedule_opening",
                             "selector": {"section": "117.821", "draw": 1}}
    assert evaluate(forbid.when, facts(datetime(2026, 8, 12, 8, 59))) is Tri.T
    assert evaluate(forbid.when, facts(datetime(2026, 8, 12, 9, 0))) is Tri.F     # half-open
    assert evaluate(forbid.when, facts(datetime(2026, 8, 15, 8, 0))) is Tri.F     # Saturday
    assert evaluate(forbid.when, facts(datetime(2026, 9, 7, 8, 0))) is Tri.F      # Labor Day
    assert forbid.required_facts == ["open_at"]


def test_on_signal_period_compiles_a_basis_in_the_period():
    bs = run(draw(opening_basis="on_signal", periods=[
        on_signal(start=360, end=1200)]))[0]
    (basis,) = [b for b in specific(bs) if b.effect == "basis"]
    assert evaluate(basis.when, facts(datetime(2026, 8, 12, 6, 0))) is Tri.T
    assert evaluate(basis.when, facts(datetime(2026, 8, 12, 20, 0))) is Tri.F


def test_a_period_less_on_signal_basis_holds_at_all_times_and_needs_no_general_duty():
    bs = run(draw(opening_basis="on_signal"))[0]
    (basis,) = specific(bs)
    assert basis.effect == "basis"
    assert evaluate(basis.when, facts(datetime(2026, 12, 25, 3, 0))) is Tri.T
    assert not any(b.rule_id == GENERAL_CARD.canonical_ref for b in bs)


def test_two_windows_of_one_paragraph_and_effect_are_one_binding():
    bs = run(draw(periods=[closed(420, 540, days=WEEKDAYS), closed(960, 1080, days=WEEKDAYS)]))[0]
    (forbid,) = [b for b in bs if b.effect == "forbid"]
    assert "or" in forbid.when
    for hour, want in ((8, Tri.T), (12, Tri.F), (17, Tri.T)):
        assert evaluate(forbid.when, facts(datetime(2026, 8, 12, hour))) is want
    identities = [(b.rule_id, b.rule_version, b.doc_id, str(b.target), b.effect) for b in bs]
    assert len(identities) == len(set(identities)) == len({b.binding_id for b in bs})


def test_emergency_basis_overrides_every_forbid_of_the_draw():
    bs, _ = run(draw(notice_hours=4, periods=[closed(420, 540)]))
    em = next(b for b in bs if b.rule_id == EMERGENCY_CARD.canonical_ref)
    forbids = {b.binding_id for b in bs if b.effect == "forbid"}
    assert len(forbids) == 2                         # the window and the notice complement
    assert em.effect == "basis" and set(em.overrides) == forbids
    assert em.rule_version == EMERGENCY_CARD.version and em.doc_id == EMERGENCY_CARD.doc_id
    # P32 and P37: true only for an emergency class with no conflict; unknown stays unknown
    for vessel in EMERGENCY_CLASSES:
        assert evaluate(em.when, facts(vessel=vessel, conflict=False)) is Tri.T
        assert evaluate(em.when, facts(vessel=vessel, conflict=True)) is Tri.F
        assert evaluate(em.when, facts(vessel=vessel)) is Tri.U
    assert evaluate(em.when, facts(vessel="commercial", conflict=False)) is Tri.F
    assert evaluate(em.when, facts(conflict=False)) is Tri.U
    assert em.required_facts == ["local_procedure_conflict", "vessel_class"]


def test_general_duty_only_where_specific_periods_leave_a_gap():
    gen = GENERAL_CARD.canonical_ref
    assert not any(b.rule_id == gen for b in compile_draw(
        "117.1", draw(notice_hours=24, periods=[]), CARDS, GENERAL_CARD, EMERGENCY_CARD)[0])
    bs = compile_draw("117.1", draw(periods=[on_signal("04-01", "10-31")]), CARDS,
                      GENERAL_CARD, EMERGENCY_CARD)[0]
    general = next(b for b in bs if b.rule_id == gen)
    assert general.effect == "basis" and general.rule_version == GENERAL_CARD.version
    assert evaluate(general.when, facts(datetime(2026, 12, 1, 10))) is Tri.T
    assert evaluate(general.when, facts(datetime(2026, 6, 1, 10))) is Tri.F
    # periods that together cover all times leave no gap
    assert not any(b.rule_id == gen for b in run(draw(periods=[
        on_signal("04-01", "10-31"), notice_period(date_from="11-01", date_to="03-31",
                                                   at=IN_B)], notice_hours=24))[0])


def test_a_closed_to_navigation_draw_gets_no_bindings():
    bs, problems = run(draw(opening_basis="closed_to_navigation"))
    assert bs == [] and problems and "closed to navigation" in problems[0]


def test_unreadable_window_gives_no_bindings_and_is_listed():
    bs, problems = run(draw(periods=[closed(420, 540), closed(960, 1080, readable=False)]))
    assert bs == [] and problems == ["periods[1]: the window grammar cannot read its quote"]
    # and the compile report lists the draw
    item = section_item("117.821", [draw(periods=[closed(420, 540, readable=False)]),
                                    draw(n=2, notice_hours=4)])
    bindings, report = compile_bindings([item], [*CARDS, GENERAL_CARD, EMERGENCY_CARD])
    assert report["failed"] == [{"section": "117.821", "draw": 1, "problems": [
        "periods[0]: the window grammar cannot read its quote"]}]
    assert report["draws"] == {"total": 2, "compiled": 1, "failed": 1}
    assert {b.target["selector"]["draw"] for b in bindings} == {2}


@pytest.mark.parametrize(("change", "problem"), [
    (lambda d: d.model_copy(update={"notice_hours": g(None, null_reason="ungrounded")}),
     "notice_hours: ungrounded"),
    (lambda d: d.model_copy(update={"opening_basis": g(None, null_reason="unparseable")}),
     "opening_basis: unparseable"),
    (lambda d: d.model_copy(update={"periods": [d.periods[0].model_copy(
        update={"start": g(None, null_reason="model_error")})]}),
     "periods[0].start: model_error"),
    (lambda d: d.model_copy(update={"periods": [d.periods[0].model_copy(
        update={"end": NONE})]}), "periods[0]: a start with no end"),
    (lambda d: d.model_copy(update={"periods": [d.periods[0].model_copy(
        update={"date_to": NONE, "date_from": g("04-01")})]}),
     "periods[0]: a date range with one end"),
    (lambda d: d.model_copy(update={"periods": [d.periods[0].model_copy(
        update={"effect": NONE})]}), "periods[0].effect: absent"),
    (lambda d: d.model_copy(update={"periods": [notice_period(420, 540)]}),
     "periods[0]: a notice period with no notice hours"),
    (lambda d: d.model_copy(update={"periods": [closed(420, 420)]}),
     "periods[0]: start 420 equals end 420"),
])
def test_a_draw_with_a_failed_parameter_gets_no_bindings(change, problem):
    bs, problems = run(change(draw(periods=[closed(420, 540)])))
    assert bs == [] and problems == [problem]


def test_an_auto_accepted_value_compiles_and_is_flagged_for_review():
    p = closed(420, 540)
    p = p.model_copy(update={"start": g(420, status="auto-accepted")})
    bs, _ = run(draw(periods=[p]))
    forbid = next(b for b in bs if b.effect == "forbid")
    assert forbid.review["auto_accepted"] == ["periods[0].start"]
    assert forbid.params_prov["periods[0].start"]["status"] == "auto-accepted"


def test_sentence_qualifiers_are_flagged_on_their_bindings_and_reported():
    flagged = closed(420, 540, qualifiers=["days", "holidays"])
    item = section_item("117.821", [draw(periods=[flagged]), draw(n=2, notice_hours=4)])
    bindings, report = compile_bindings([item], [*CARDS, GENERAL_CARD, EMERGENCY_CARD])
    forbid = next(b for b in bindings if b.effect == "forbid"
                  and b.target["selector"]["draw"] == 1)
    assert forbid.review["sentence_qualifiers"] == ["days", "holidays"]
    general = next(b for b in bindings if b.rule_id == GENERAL_CARD.canonical_ref
                   and b.target["selector"]["draw"] == 1)
    assert general.review["sentence_qualifiers"] == ["days", "holidays"]
    assert all("sentence_qualifiers" not in b.review for b in bindings
               if b.target["selector"]["draw"] == 2)
    assert report["sentence_qualifiers"] == [
        {"section": "117.821", "draw": 1, "qualifiers": ["days", "holidays"]}]


def test_a_period_less_notice_with_sentence_qualifiers_is_flagged():
    d = draw(notice_hours=4, qualifiers=["dates", "times"])
    bs, _ = run(d)
    assert all(b.review.get("sentence_qualifiers") == ["dates", "times"]
               for b in specific(bs))


def test_rule_id_comes_from_the_card_whose_span_holds_the_quote():
    bs = run(draw(periods=[closed(420, 540, at=IN_B)]))[0]
    assert next(b for b in bs if b.effect == "forbid").rule_id == CARD_B.canonical_ref
    bs, problems = run(draw(periods=[closed(420, 540, at=5000)]))       # in no card
    assert bs == [] and problems == ["periods[0]: no rule card holds its quote"]


def test_binding_ids_are_stable_and_rule_identity_is_split():
    d = draw(notice_hours=4, periods=[closed(420, 540)])
    first, second = run(d)[0], run(d)[0]
    assert [b.model_dump() for b in first] == [b.model_dump() for b in second]
    forbid = next(b for b in first if b.effect == "forbid" and b.rule_id == CARD_A.canonical_ref)
    assert forbid.rule_id == "33 CFR 117.821(a)" and forbid.rule_version == CARD_A.version
    assert forbid.doc_id == CARD_A.doc_id and len(forbid.rule_version) == 12
    # a changed window is a new version of the same binding
    moved = next(b for b in run(draw(notice_hours=4, periods=[closed(420, 600)]))[0]
                 if b.effect == "forbid" and b.rule_id == CARD_A.canonical_ref)
    assert moved.binding_id == forbid.binding_id
    assert moved.binding_version != forbid.binding_version
    # a changed card text (another rule version) is another binding
    other_a = card("33 CFR 117.821(a)", 1000, 1200, "The draw need not open at all.")
    again = compile_draw("117.821", d, [other_a, CARD_B], GENERAL_CARD, EMERGENCY_CARD)[0]
    moved = next(b for b in again if b.effect == "forbid" and b.rule_id == CARD_A.canonical_ref)
    assert moved.binding_id != forbid.binding_id
    # another draw is another target, so another binding
    two = compile_draw("117.821", d.model_copy(update={"draw": 2}), CARDS, GENERAL_CARD,
                       EMERGENCY_CARD)[0]
    assert not {b.binding_id for b in two} & {b.binding_id for b in first}
    # every binding passes its own validation (ids and required facts of its content)
    for b in first:
        assert Binding.model_validate(b.model_dump()) == b


def test_params_prov_records_the_quotes_and_the_derivation_is_the_sentence():
    bs = run(draw(periods=[closed(420, 540, days=WEEKDAYS)]))[0]
    forbid = next(b for b in bs if b.effect == "forbid")
    prov = forbid.params_prov
    assert prov["periods[0].start"] == {"value": 420, "quote": "q", "span": [IN_A, IN_A + 1],
                                        "status": "verified"}
    assert set(prov) >= {"periods[0].effect", "periods[0].start", "periods[0].end",
                         "periods[0].days"}
    assert forbid.derivation == sentence(forbid, "Main Street drawbridge")


def test_compile_bindings_finds_general_and_emergency_cards_by_rule_id():
    item = section_item("117.821", [draw(notice_hours=4)])
    # cards of another document are never used
    stray = card("33 CFR 117.5(p1)", 100, 300, doc_id="9" * 64)
    bindings, report = compile_bindings([item], [stray, *CARDS, GENERAL_CARD, EMERGENCY_CARD])
    assert {b.rule_id for b in bindings} == {CARD_B.canonical_ref, EMERGENCY_CARD.canonical_ref}
    assert all(b.doc_id == D1 for b in bindings)
    assert report["bindings"] == len(bindings) == 3
    assert (GENERAL_DUTY, EMERGENCY) == ("33 CFR 117.5", "33 CFR 117.31(b)")
    with pytest.raises(ValueError, match="117.31"):
        compile_bindings([item], [*CARDS, GENERAL_CARD])
    # subpart A sections enrich cards but compile no binding
    assert compile_bindings([section_item("117.40", [])], [GENERAL_CARD, EMERGENCY_CARD])[0] == []


def section_item(section: str, draws: list[DrawParams]) -> SectionEnrichment:
    return SectionEnrichment(section=section, doc_id=D1, section_sha256="5" * 64, cards={},
                             draws=draws, outcome="reply")


# -- covers_all, exact under P44 (builder note 13) -----------------------------------------------

def W(start, end, days=DAYS, hol=False, date_from=None, date_to=None) -> Window:
    return Window(start=start, end=end, days=tuple(days), except_federal_holidays=hol,
                  date_from=date_from, date_to=date_to)


@pytest.mark.parametrize(("windows", "covered"), [
    ([W(0, 1440)], True),
    ([], False),
    ([W(0, 1439)], False),
    ([W(0, 720), W(720, 1440)], True),
    ([W(0, 1440, WEEKDAYS), W(0, 1440, DAYS[5:])], True),
    ([W(0, 1440, WEEKDAYS, hol=True), W(0, 1440, DAYS[5:])], False),      # holiday weekdays
    ([W(0, 1440, hol=True)], False),
    ([W(1320, 360), W(360, 1320)], True),                                 # crossing midnight
    ([W(1320, 360, WEEKDAYS), W(360, 1320), W(1320, 360, DAYS[5:])], True),
    # P44: Monday 01:00 belongs to Sunday's night, which the Monday-to-Friday night misses
    ([W(1320, 360, WEEKDAYS), W(360, 1320), W(0, 360, DAYS[5:]), W(1320, 1440, DAYS[5:])],
     False),
    # ... and Saturday 01:00 belongs to Friday's night, which it holds
    ([W(1320, 360, WEEKDAYS), W(360, 1320), W(0, 360, ("Mon", "Sun")),
      W(1320, 1440, DAYS[5:])], True),
    # a crossing window with a holiday exception: the morning after a holiday is open
    ([W(1320, 360, hol=True), W(360, 1320)], False),
    ([W(1320, 360, hol=True), W(360, 1320), W(1320, 360, hol=False)], True),
    ([W(0, 1440, date_from="04-01", date_to="10-31"),
      W(0, 1440, date_from="11-01", date_to="03-31")], True),
    ([W(0, 1440, date_from="04-01", date_to="10-31"),
      W(0, 1440, date_from="11-02", date_to="03-31")], False),           # 11-01
    ([W(0, 1440, date_from="01-01", date_to="02-28"),
      W(0, 1440, date_from="03-01", date_to="12-31")], False),           # 02-29
    # a night from 1 December through 28 February misses 1 March 01:00 of a leap year only
    # (it belongs to 29 February's night), ...
    ([W(1200, 240, date_from="12-01", date_to="02-28"), W(240, 1200),
      W(0, 1440, date_from="03-02", date_to="11-30"),
      W(1200, 1440, date_from="03-01", date_to="03-01"),
      W(1200, 1440, date_from="02-29", date_to="02-29"),
      W(0, 240, date_from="12-01", date_to="12-01")], False),
    # ... which a night through 29 February holds
    ([W(1200, 240, date_from="12-01", date_to="02-29"), W(240, 1200),
      W(0, 1440, date_from="03-02", date_to="11-30"),
      W(1200, 1440, date_from="03-01", date_to="03-01"),
      W(0, 240, date_from="12-01", date_to="12-01")], True),
    # "December 1 through March 31, 8 p.m. to 4 a.m." holds 04-01 02:00, not 12-01 02:00
    ([W(1200, 240, date_from="12-01", date_to="03-31"), W(240, 1200),
      W(0, 1440, date_from="04-01", date_to="11-30")], False),
    ([W(1200, 240, date_from="12-01", date_to="03-31"), W(240, 1200),
      W(0, 1440, date_from="04-01", date_to="11-30"),
      W(0, 240, date_from="12-01", date_to="12-01")], True),
    ([W(1200, 240, date_from="12-01", date_to="03-31"), W(240, 1200),
      W(0, 1440, date_from="04-02", date_to="11-30"),
      W(1200, 1440, date_from="04-01", date_to="04-01"),
      W(0, 240, date_from="12-01", date_to="12-01")], True),
])
def test_covers_all_is_exact_at_critical_points(windows, covered):
    assert covers_all(windows) is covered
    assert covers_all(list(reversed(windows))) is covered


def _brute_force_covers(windows: list[Window], days: list[date]) -> bool:
    """Every minute of every day in `days` lies in some window (the evaluator itself)."""
    return all(any(in_window(w, m, d) for w in windows) for d in days for m in range(1440))


def _random_windows(rng: random.Random, *, days: bool, dates: bool, holidays: bool):
    ws = []
    for _ in range(rng.randint(1, 4)):
        start, end = rng.sample([0, 360, 420, 540, 720, 1080, 1200, 1320], 2)
        ds = (tuple(d for d in DAYS if rng.random() < 0.75) or DAYS) if days else DAYS
        df, dt = (rng.choice(["04-01", "11-01", "12-01", "03-01"]),
                  rng.choice(["10-31", "03-31", "02-28", "11-30"])) \
            if dates and rng.random() < 0.5 else (None, None)
        ws.append(W(start, end or 1440, ds, holidays and rng.random() < 0.3, df, dt))
    if rng.random() < 0.5:          # often add a complement, so that some sets do cover
        ws.append(W(0, 1440, DAYS, False, None, None) if rng.random() < 0.2 else
                  W(ws[0].end % 1440, ws[0].start or 1440, DAYS, False, None, None))
    return ws


def test_covers_all_equals_the_evaluator_on_weekday_windows():
    """Weekday windows, crossing ones included, no dates or holidays: a week and the day
    before it, minute by minute, is every case there is."""
    rng = random.Random(20261121)
    week = [date(2026, 8, 9) + timedelta(days=k) for k in range(8)]
    seen = set()
    for _ in range(60):
        ws = _random_windows(rng, days=True, dates=False, holidays=False)
        got = covers_all(ws)
        seen.add(got)
        assert got is _brute_force_covers(ws, week), ws
    assert seen == {True, False}


def test_covers_all_equals_the_evaluator_on_date_ranges():
    """Every-day windows with date ranges (wrapping, crossing midnight): a leap year and the
    day before it, minute by minute, holds every month-day and both days before 1 March."""
    rng = random.Random(20261122)
    year = [date(2027, 12, 31) + timedelta(days=k) for k in range(367)] + [date(2027, 3, 1)]
    seen = set()
    for _ in range(6):
        ws = _random_windows(rng, days=False, dates=True, holidays=False)
        got = covers_all(ws)
        seen.add(got)
        assert got is _brute_force_covers(ws, year), ws
    assert seen == {True, False}


def test_covers_all_is_sound_on_the_real_calendar_with_holidays():
    """With holiday exceptions `covers_all` may find a gap that no real date shows (holidays
    are free in it, as in the analysis), but never misses one a real date shows."""
    rng = random.Random(20261123)
    days = [date(2026, 8, 9) + timedelta(days=k) for k in range(8)] + [
        date(2026, 9, 6), date(2026, 9, 7), date(2026, 9, 8), date(2026, 7, 3),
        date(2027, 12, 30), date(2027, 12, 31), date(2028, 1, 1), date(2028, 1, 2)]
    assert sum(is_federal_holiday(d) for d in days) >= 3
    covered = 0
    for _ in range(40):
        ws = _random_windows(rng, days=True, dates=False, holidays=True)
        if covers_all(ws):
            covered += 1
            assert _brute_force_covers(ws, days), ws
    assert covered >= 3


def test_covers_all_holds_holidays_free_of_the_calendar():
    """A weekday holiday exception leaves a gap even on a weekday no holiday falls on in a
    given year: the analysis (Z3) treats `federal_holiday` as free, so must `covers_all`,
    or § 117.5 would be left out where Z3 finds a gap."""
    assert not covers_all([W(0, 1440, ("Tue",), hol=True), W(0, 1440, DAYS[:1] + DAYS[2:])])


# -- the sentence --------------------------------------------------------------------------------

def test_sentence_renders_the_window():
    bs = run(draw(periods=[closed(420, 540, days=WEEKDAYS, holidays=True)]))[0]
    forbid = next(b for b in bs if b.effect == "forbid")
    assert sentence(forbid, "Main Street drawbridge") == (
        "Forbid scheduling an opening of the Main Street draw from 7:00 to 9:00, Monday to "
        "Friday, except federal holidays")
    assert sentence(forbid, "Main Street") == sentence(forbid, "Main Street drawbridge")


def test_sentence_renders_notice_dates_general_duty_and_emergency():
    bs = run(draw(notice_hours=4, periods=[closed(420, 540, days=("Sat", "Sun")),
                                           closed(960, 1080, days=("Sat", "Sun"))]))[0]
    by = {(b.rule_id, b.effect): b for b in bs}
    assert sentence(by[(CARD_B.canonical_ref, "basis")], "Main Street drawbridge") == (
        "Allow scheduling an opening of the Main Street draw at any time with at least 4 hours "
        "notice")
    assert sentence(by[(CARD_B.canonical_ref, "forbid")], "Main Street drawbridge") == (
        "Forbid scheduling an opening of the Main Street draw at any time with less than 4 "
        "hours notice")
    assert sentence(by[(CARD_A.canonical_ref, "forbid")], "Railroad Bridge") == (
        "Forbid scheduling an opening of the Railroad draw from 7:00 to 9:00 or from 16:00 to "
        "18:00, Saturday and Sunday")
    em = by[(EMERGENCY_CARD.canonical_ref, "basis")]
    assert sentence(em, "Main Street drawbridge") == (
        "Allow scheduling an opening of the Main Street draw for a public-safety, distress, "
        "rescue or salvage, or severe-weather-shelter vessel when no approved local emergency "
        "procedure conflicts, overriding 2 forbids")
    bs = run(draw(periods=[on_signal("04-01", "10-31", 360, 1200)]))[0]
    general = next(b for b in bs if b.rule_id == GENERAL_CARD.canonical_ref)
    assert sentence(general, "Main Street drawbridge") == (
        "Allow scheduling an opening of the Main Street draw at any time except from 6:00 to "
        "20:00, April 1 to October 31")


# -- E2 against both Phase 3 passes (§6.3 check 5) --------------------------------------------

def _prov(quote: str | None, spec: str = "bridge.closed_periods@1") -> ValueProv:
    if quote is None:
        return ValueProv(doc_id=D1, spec_id=spec, null_reason="absent")
    return ValueProv(doc_id=D1, start=0, end=len(quote), spec_id=spec, status="verified",
                     quote=quote)


def first_row(section, draw_no, bridge, mile, notice, signal, closed_quotes) -> RowRecord:
    row = {"section": section, "draw": draw_no, "bridge": bridge, "mile": mile,
           "notice_hours": notice, "opens_on_signal": signal,
           "closed_periods": list(closed_quotes)}
    return RowRecord(doc_id=D1, row=row, prov={
        "closed_periods": [_prov(q) for q in closed_quotes]})


def _v(value, quote="q") -> Value:
    if value is None:
        return ABSENT
    return Value(value, quote, 0, len(quote), "verified", None, (), None)


def fact_draw(bridge, mile, notice, signal, closed_quote) -> dict:
    return {"bridge": _v(bridge), "mile": _v(mile), "notice_hours": _v(notice),
            "opens_on_signal": _v(signal),
            "closed_periods": _v(None if closed_quote is None else [closed_quote], closed_quote)}


def enriched(n, bridge, mile, *, notice=None, basis=None, periods=()) -> DrawParams:
    return DrawParams(draw=n, bridge=g(bridge), mile=g(mile),
                      opening_basis=NONE if basis is None else g(basis),
                      notice_hours=NONE if notice is None else g(notice),
                      periods=list(periods), sentence_qualifiers=[])


def window_quote(p: Period, quote: str) -> Period:
    return p.model_copy(update={"window_quote": quote})


def test_e2_agreement_matches_draws_as_phase3():
    # the enrichment names the draws in another order and one by another spelling
    item = SectionEnrichment(section="117.821", doc_id=D1, section_sha256="a" * 64, cards={},
                             outcome="reply", draws=[
        enriched(1, "Smith River Railroad Bridge", 5.1, notice=4, basis="advance_notice"),
        enriched(2, "Main Street Bridge", 3.4, basis="on_signal", periods=[window_quote(
            closed(420, 540, days=WEEKDAYS, holidays=True),
            "need not open from 7 a.m. to 9 a.m. Monday through Friday except Federal "
            "holidays")]),
        enriched(3, "Unnamed draw", 9.9, notice=2)])
    first = [first_row("117.821", 1, "Main Street drawbridge", 3.4, None, True,
                       ["7 a.m. to 9 a.m. Monday through Friday except Federal holidays"]),
             first_row("117.821", 2, "Smith River Railroad Bridge", 5.1, 6, True, []),
             first_row("117.999", 1, "Elsewhere Bridge", 1.0, 4, True, [])]
    facts_ = [Facts("a" * 64, {}, [
        fact_draw("Main Street drawbridge", 3.4, None, True,
                  "need not open from 7 a.m. to 9 a.m. Monday through Friday"),
        fact_draw("The Smith River Railroad Bridge", 5.1, 4, True, None)]),
        Facts("b" * 64, {}, [fact_draw("Other", 1.0, 1, True, None)])]
    e2 = e2_agreement([item], first, facts_)
    f, s = e2["first"], e2["second"]
    assert f["draws"] == {"matched": 2, "enrichment_only": 1, "pass_only": 0}
    assert s["draws"] == {"matched": 2, "enrichment_only": 1, "pass_only": 0}
    assert f["notice_hours"] == {"compared": 2, "agree": 1, "share": 0.5}       # 4 != 6
    assert s["notice_hours"] == {"compared": 2, "agree": 2, "share": 1.0}
    assert f["opens_on_signal"] == {"compared": 2, "agree": 2, "share": 1.0}
    # the second pass's quote drops the holiday exception: the grammar reads another window
    assert f["closed_windows"] == {"compared": 2, "agree": 2, "share": 1.0, "unread": 0}
    assert s["closed_windows"] == {"compared": 2, "agree": 1, "share": 0.5, "unread": 0}
    assert e2["sections"] == {"compared": 1, "no_first_pass": 0, "no_second_pass": 0}


def test_e2_counts_unreadable_closed_quotes_apart():
    item = SectionEnrichment(section="117.1", doc_id=D1, section_sha256="c" * 64, cards={},
                             outcome="reply", draws=[enriched(1, "A Bridge", 1.0, periods=[
                                 window_quote(closed(420, 540), "from 7 a.m. to 9 a.m.")])])
    first = [first_row("117.1", 1, "A Bridge", 1.0, None, None,
                       ["need not be opened for the passage of vessels"])]
    e2 = e2_agreement([item], first, [])
    assert e2["first"]["closed_windows"] == {"compared": 0, "agree": 0, "share": None,
                                             "unread": 1}
    assert e2["second"]["draws"] == {"matched": 0, "enrichment_only": 1, "pass_only": 0}
    assert e2["sections"] == {"compared": 1, "no_first_pass": 0, "no_second_pass": 1}


def test_window_grammar_agreement_counts_in_the_report():
    agree = closed(420, 540).model_copy(update={"window_grammar_agrees": True})
    differ = closed(960, 1080).model_copy(update={"window_grammar_agrees": False})
    cond = closed(1200, 1320, conditions=["unless", "notice"])
    item = section_item("117.821", [draw(periods=[agree, differ, cond])])
    _, report = compile_bindings([item], [*CARDS, GENERAL_CARD, EMERGENCY_CARD])
    assert report["window_grammar"] == {"agree": 1, "disagree": 1, "not_compared": 1,
                                        "conditioned": 1}


def test_a_large_draw_compiles_quickly_and_identically():
    ps = [closed(s, s + 30, days=ds) for s, ds in itertools.product(
        range(0, 1380, 120), (WEEKDAYS, DAYS[5:]))]
    a, b = run(draw(periods=ps))[0], run(draw(periods=ps))[0]
    assert [x.binding_id for x in a] == [x.binding_id for x in b]
