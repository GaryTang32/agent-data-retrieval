"""The reference evaluator (Phase 4 spec §12.3, P12, P32, P34, P37, P44, P46; Task 16): the
desk's decision for draws of the simple shape, read from the Phase 3 second-pass facts and
the window grammar on the closed-period quote's full sentence, never from the DSL or the
enrichment; and the agreement set, paired by bridge key then mile. Store-free; no model
call."""

from __future__ import annotations

import ast
import inspect
from datetime import date, datetime

import pytest

from adr_store.bindings import reference
from adr_store.bindings.dsl import DAYS, Window
from adr_store.bindings.enrich import SectionEnrichment
from adr_store.bindings.facts import EMERGENCY_CLASSES
from adr_store.bindings.reference import (
    RefDecision,
    RefDraw,
    agreement_set,
    paired_refs,
    ref_census,
    ref_decide,
    ref_draws,
    ref_next_allowed,
)
from adr_store.tables import extract as ex
from adr_store.tables.ecfr import SectionUnit
from tests.store.bindings_fixtures import BINDINGS_821, W_821, record
from tests.store.test_bindings_compile import WEEKDAYS, closed, draw, g, on_signal

REF_CLOSED = RefDraw(section="117.821", draw=1, bridge="Main Street drawbridge",
                     opens_on_signal=True, notice_hours=4, closed=(W_821,))
REF_PLAIN = RefDraw(section="117.821", draw=2, bridge="Oak bridge", opens_on_signal=True,
                    notice_hours=None, closed=())
FRI = datetime(2026, 8, 14, 7, 30)          # a Friday inside the 7-9 window
REC_NOTICE_OK = {"notice_received_at": {"value": "2026-08-13T12:00:00", "source": "record"},
                 "vessel_class": {"value": "commercial", "source": "record"},
                 "local_procedure_conflict": {"value": False, "source": "record"}}


def decide(d: RefDraw, at: datetime, **kw) -> RefDecision:
    return ref_decide(d, at, record(at, **kw))


# -- ref_decide (§12.3, P32, P34, P37) -------------------------------------------------------------

def test_reference_denies_in_a_closed_window_at_section_level():
    d = ref_decide(REF_CLOSED, datetime(2026, 8, 14, 7, 30), REC_NOTICE_OK)
    assert d.outcome == "deny" and d.denying_sections == {"117.821"}
    assert d.missing == ()


def test_reference_allows_emergency_without_conflict_and_escalates_unknown_notice():
    for cls in EMERGENCY_CLASSES:        # inside the window and with no notice at all (P32)
        d = decide(REF_CLOSED, FRI, vessel=cls, conflict=False)
        assert d == RefDecision("allow", frozenset(), ())
    # a conflicting local procedure: the schedule stands
    assert decide(REF_CLOSED, FRI, vessel="distress", conflict=True).outcome == "deny"
    # outside the window a threshold with no notice escalates, naming the notice
    noon = datetime(2026, 8, 14, 12, 0)
    d = decide(REF_CLOSED, noon, vessel="commercial", conflict=False)
    assert d == RefDecision("escalate", frozenset(), ("notice_minutes",))
    # and a draw without a threshold needs none
    assert decide(REF_PLAIN, noon, vessel="commercial", conflict=False).outcome == "allow"


def test_reference_notice_short_denies_and_enough_allows():
    noon = datetime(2026, 8, 14, 12, 0)
    kw = {"vessel": "recreational", "conflict": False}
    assert decide(REF_CLOSED, noon, notice=239, **kw) == RefDecision(
        "deny", frozenset({"117.821"}), ())
    assert decide(REF_CLOSED, noon, notice=240, **kw).outcome == "allow"
    assert decide(REF_CLOSED, noon, notice=2880, **kw).outcome == "allow"
    # notice that came after the requested time is short
    assert decide(REF_CLOSED, noon, notice=-5, **kw).outcome == "deny"


def test_reference_mirrors_the_gate_on_unknown_vessel_class():
    """P37: where a closed window or short notice would deny and the vessel class is unknown,
    or an emergency class has an unknown conflict, the reference escalates with those facts
    missing; where they could not change the outcome it does not."""
    noon = datetime(2026, 8, 14, 12, 0)
    cases = [
        (FRI, {"conflict": False}, "escalate", ("vessel_class",)),
        (FRI, {}, "escalate", ("local_procedure_conflict", "vessel_class")),
        (FRI, {"conflict": True}, "deny", ()),          # no override can apply
        (FRI, {"vessel": "public_safety"}, "escalate", ("local_procedure_conflict",)),
        (FRI, {"vessel": "commercial"}, "deny", ()),
        (noon, {"notice": 10, "conflict": False}, "escalate", ("vessel_class",)),
        (noon, {"notice": 10, "vessel": "rescue_salvage"}, "escalate",
         ("local_procedure_conflict",)),
        (noon, {"conflict": False}, "escalate", ("notice_minutes", "vessel_class")),
        (noon, {"vessel": "commercial"}, "escalate", ("notice_minutes",)),
        # enough notice outside the window: the outcome is allow whatever the class
        (noon, {"notice": 300}, "allow", ()),
        (noon, {"notice": 300, "vessel": "distress"}, "allow", ()),
    ]
    for at, kw, outcome, missing in cases:
        d = decide(REF_CLOSED, at, **kw)
        assert (d.outcome, d.missing) == (outcome, missing), (at, kw, d)
        assert d.denying_sections == (frozenset({"117.821"}) if outcome == "deny" else set())


def test_reference_windows_follow_holidays_and_p44_crossing():
    labor_day = datetime(2026, 9, 7, 7, 30)         # the window excepts federal holidays
    assert decide(REF_CLOSED, labor_day, notice=300, vessel="commercial",
                  conflict=False).outcome == "allow"
    assert decide(REF_CLOSED, datetime(2026, 9, 8, 7, 30), notice=300, vessel="commercial",
                  conflict=False).outcome == "deny"
    night = Window(start=1380, end=360, days=("Mon",), except_federal_holidays=False,
                   date_from=None, date_to=None)
    d = RefDraw(section="117.900", draw=1, bridge=None, opens_on_signal=True, notice_hours=None,
                closed=(night,))
    kw = {"vessel": "commercial", "conflict": False}
    assert decide(d, datetime(2026, 8, 10, 23, 30), **kw).outcome == "deny"   # Monday night
    assert decide(d, datetime(2026, 8, 11, 1, 0), **kw).outcome == "deny"     # its Tuesday hours
    assert decide(d, datetime(2026, 8, 10, 1, 0), **kw).outcome == "allow"    # Sunday's night
    assert decide(d, datetime(2026, 8, 11, 6, 0), **kw).outcome == "allow"


def test_reference_next_allowed_is_the_first_minute_after_the_window():
    assert ref_next_allowed(REF_CLOSED, FRI, REC_NOTICE_OK) == datetime(2026, 8, 14, 9, 0)
    # the scan starts after the requested minute, even when that minute is allowed
    assert ref_next_allowed(REF_CLOSED, datetime(2026, 8, 14, 10, 0),
                            REC_NOTICE_OK) == datetime(2026, 8, 14, 10, 1)
    # whatever its seconds
    assert ref_next_allowed(REF_CLOSED, datetime(2026, 8, 14, 8, 59, 30),
                            REC_NOTICE_OK) == datetime(2026, 8, 14, 9, 0)
    # an unknown class escalates inside the window and is allowed after it
    rec = record(FRI, notice=600, conflict=False)
    assert ref_decide(REF_CLOSED, FRI, rec).outcome == "escalate"
    assert ref_next_allowed(REF_CLOSED, FRI, rec) == datetime(2026, 8, 14, 9, 0)
    # short notice waits for enough notice: received at 07:00, 4 hours later
    rec = record(datetime(2026, 8, 14, 7, 0), notice=0, vessel="commercial", conflict=False)
    assert ref_next_allowed(REF_CLOSED, datetime(2026, 8, 14, 9, 30), rec) == \
        datetime(2026, 8, 14, 11, 0)
    # a draw closed at all times never opens within seven days
    shut = RefDraw(section="117.900", draw=1, bridge=None, opens_on_signal=True,
                   notice_hours=None, closed=(Window(start=0, end=1440, days=DAYS,
                                                     except_federal_holidays=False,
                                                     date_from=None, date_to=None),))
    assert ref_next_allowed(shut, FRI, REC_NOTICE_OK) is None


def test_reference_never_reads_bindings_or_the_dsl_evaluator():
    """The evaluator reads the Phase 3 facts and the window grammar only (P12): it imports
    no binding, no `evaluate`, no compiler and no enrichment parameters."""
    tree = ast.parse(inspect.getsource(reference))
    imported = {(n.module, a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                for a in n.names}
    names = {name for _, name in imported}
    assert not names & {"Binding", "evaluate", "Tri", "compile_draw", "compile_bindings"}
    assert not any(m and m.endswith(("bindings.compile", "bindings.checks", "analysis"))
                   for m, _ in imported)
    for fn in (reference.ref_decide, reference.ref_next_allowed, reference.read_closed):
        src = inspect.getsource(fn)
        assert "SectionEnrichment" not in src and "DrawParams" not in src


# -- ref_draws: the Phase 3 facts read into the simple shape ---------------------------------------

SECTION = "117.821"
TEXT = (
    "§ 117.821 Example River.\n"
    "(a) The draw of the Main Street bridge, mile 3.4, shall open on signal; except that, the "
    "draw need not be opened from 7 a.m. to 9 a.m. Monday through Friday except Federal "
    "holidays.\n"
    "(b) The draw of the Oak bridge, mile 5.0, shall open on signal if at least 4 hours notice "
    "is given.\n"
    "(c) The draw of the Elm bridge, mile 7.0, need not be opened from 6 p.m. to 6 a.m. unless "
    "2 hours notice is given.\n"
    "(d) The draw of the Rail bridge, mile 8.0, need not be opened during rail traffic.\n"
    "(e) From June 1 through September 30, the draw of the Pine bridge, mile 9.0, need not be "
    "opened from 4 p.m. to 6 p.m.\n"
    "(f) The draw of the Ash bridge, mile 10.0, shall open on signal; except that, the draw "
    "need not be opened from 5 p.m. to 7 p.m.\n"
    "(g) The draw of the Fir bridge, mile 11.0, shall open on signal if at least 0 hours "
    "notice is given.\n")
TEXT_901 = (
    "§ 117.901 Other River.\n"
    "(a) The draw of the Cedar bridge, mile 1.0, shall open on signal from April 1 through "
    "October 31.\n"
    "(b) The draw of the Birch bridge, mile 2.0, shall open on signal; except that, from June 1 "
    "through September 30 the draw need not be opened from 4 p.m. to 6 p.m.\n")
D_OLD, D_NEW = "1" * 64, "2" * 64


def unit(text: str, section: str, docs=(D_NEW,)) -> ex.Unit:
    sha = __import__("hashlib").sha256(text.encode()).hexdigest()
    occ = tuple(SectionUnit(doc_id=d, version="2026-06-26", section=section, heading="h",
                            state=None, start=0, end=len(text), heading_span=(0, 1),
                            state_span=None, text=text) for d in docs)
    return ex.Unit(sha, text, occ)


def val(value, text: str | None = None, quote: str | None = None, *, null: str | None = None,
        occurrence: int = 0) -> ex.Value:
    if value is None:
        return ex.Value(None, None, None, None, "rejected" if null and null != "absent" else None,
                        null or "absent", (), None)
    if quote is None:
        return ex.Value(value, None, None, None, "verified", None, (), None)
    at = -1
    for _ in range(occurrence + 1):
        at = text.index(quote, at + 1)
    return ex.Value(value, quote, at, at + len(quote), "verified", None, (), None)


def p3_draw(text: str, bridge: str, mile: float, *, signal=True, notice=None, closed_quote=None,
            closed_value=None, notice_null=None, closed_null=None) -> dict:
    out = {"bridge": val(bridge, text, bridge if bridge in text else None), "mile": val(mile),
           "opens_on_signal": val(signal, text, "shall open on signal") if signal is not None
           else val(None),
           "notice_hours": val(notice) if notice_null is None else val(None, null=notice_null),
           "closed_periods": val(None)}
    if closed_quote is not None:
        out["closed_periods"] = val(closed_value or [closed_quote], text, closed_quote)
    if closed_null is not None:
        out["closed_periods"] = val(None, null=closed_null)
    return out


def facts_821() -> ex.Facts:
    t = TEXT
    return ex.Facts(unit(t, SECTION).text_sha256, {"seasonal": val(None)}, [
        p3_draw(t, "Main Street bridge", 3.4, closed_quote="from 7 a.m. to 9 a.m."),
        p3_draw(t, "Oak bridge", 5.0, notice=4),
        p3_draw(t, "Elm bridge", 7.0, signal=False, notice=2,
                closed_quote="from 6 p.m. to 6 a.m."),
        p3_draw(t, "Rail bridge", 8.0, closed_quote="need not be opened during rail traffic"),
        p3_draw(t, "Pine bridge", 9.0, closed_quote="from 4 p.m. to 6 p.m."),
        p3_draw(t, "Ash bridge", 10.0,
                closed_quote="the draw need not be opened from 5 p.m. to 7 p.m."),
        p3_draw(t, "Fir bridge", 11.0, notice=0),
        p3_draw(t, "Unknown bridge", 12.0, signal=None),
        p3_draw(t, "Shut bridge", 13.0, signal=False),
        p3_draw(t, "Garbled bridge", 14.0, notice_null="unparseable"),
        p3_draw(t, "Ungrounded bridge", 15.0, closed_null="ungrounded"),
    ])


def facts_901() -> ex.Facts:
    t = TEXT_901
    return ex.Facts(unit(t, "117.901").text_sha256, {"seasonal": val(True, t, "April 1")}, [
        p3_draw(t, "Cedar bridge", 1.0),
        p3_draw(t, "Birch bridge", 2.0, closed_quote="from 4 p.m. to 6 p.m."),
    ])


UNITS = [unit(TEXT, SECTION), unit(TEXT_901, "117.901")]
FACTS = [facts_821(), facts_901()]
W_ASH = Window(start=1020, end=1140, days=DAYS, except_federal_holidays=False, date_from=None,
               date_to=None)


def test_ref_draws_reads_closed_windows_from_the_full_sentence():
    refs = ref_draws(FACTS, UNITS)
    # the quote alone reads 7-9 every day; its sentence adds the days and the holiday exception
    main = refs[(SECTION, 1)]
    assert main.closed == (W_821,) and main.opens_on_signal is True and main.notice_hours is None
    assert main.bridge == "Main Street bridge" and main.unit == UNITS[0].text_sha256
    # a quote that already holds the whole closure reads the same either way
    assert refs[(SECTION, 6)].closed == (W_ASH,)
    # a season stated beside the closure, in the grammar's words, is read in
    birch = refs[("117.901", 2)]
    assert birch.closed == (Window(start=960, end=1080, days=DAYS, except_federal_holidays=False,
                                   date_from="06-01", date_to="09-30"),)
    census = ref_census(FACTS, UNITS)
    assert census["closed"]["same_as_quote"] == 1             # Ash
    assert census["closed"]["sentence_differs"] == 2          # Main Street, Birch (dates)
    assert census["windows"] == {"same_as_quote": 1, "from_sentence": 2}


def test_ref_draws_leaves_out_conditioned_unreadable_and_incomplete_closures():
    refs = ref_draws(FACTS, UNITS)
    census = ref_census(FACTS, UNITS)
    for n in (3, 4, 5, 11):
        assert (SECTION, n) not in refs
    excluded = census["excluded"]
    assert excluded["closed_conditioned"] == 1     # Elm: "unless ... notice"
    assert excluded["closed_unreadable"] == 1      # Rail: no window in the grammar's words
    assert excluded["closed_qualifiers"] == 1      # Pine: the season before the subject
    assert excluded["closed_failed"] == 1          # an ungrounded closed-period answer
    assert census["closed"]["conditioned"] == 1 and census["closed"]["unreadable"] == 1
    assert census["closed"]["qualifiers"] == 1


def test_ref_draws_simple_shape_and_its_exclusions():
    refs = ref_draws(FACTS, UNITS)
    census = ref_census(FACTS, UNITS)
    # on signal with a threshold and no closed window: one threshold at all times (the
    # enrichment side of the agreement set leaves out period-specific readings, P46)
    assert refs[(SECTION, 2)].notice_hours == 4 and refs[(SECTION, 2)].closed == ()
    # 0 hours of notice is no threshold
    assert refs[(SECTION, 7)].notice_hours is None
    # signal unknown, no basis stated, a failed notice answer
    for n in (8, 9, 10):
        assert (SECTION, n) not in refs
    excluded = census["excluded"]
    assert excluded["signal_unknown"] == 1 and excluded["no_basis"] == 1
    assert excluded["notice_failed"] == 1
    # a seasonal section: a draw whose closed windows carry no dates implies a period-specific
    # rule and is left out; one whose closed window is dated is simple
    assert ("117.901", 1) not in refs and excluded["seasonal"] == 1
    assert ("117.901", 2) in refs
    assert census["draws"] == 13 and census["simple"] == len(refs) == 5
    assert sum(excluded.values()) == census["draws"] - census["simple"]


def test_ref_draws_keys_are_phase3_draw_numbers_of_the_requested_document():
    refs = ref_draws(FACTS, UNITS)
    assert sorted(refs) == [(SECTION, 1), (SECTION, 2), (SECTION, 6), (SECTION, 7),
                            ("117.901", 2)]
    assert all(r.section == k[0] and r.draw == k[1] for k, r in refs.items())
    assert refs[(SECTION, 2)].section_draws[:2] == (("Main Street bridge", 3.4),
                                                     ("Oak bridge", 5.0))
    # only the units of the requested document
    old_only = unit(TEXT_901, "117.901", docs=(D_OLD,))
    refs = ref_draws(FACTS, [UNITS[0], old_only], doc_id=D_NEW)
    assert {k[0] for k in refs} == {SECTION}
    # two texts of one section are refused unless a document is named
    other = unit(TEXT.replace("Oak", "Maple"), SECTION, docs=(D_OLD,))
    extra = ex.Facts(other.text_sha256, {}, [p3_draw(other.text, "Maple bridge", 5.0)])
    with pytest.raises(ValueError, match="117.821"):
        ref_draws(FACTS + [extra], UNITS + [other])
    assert set(ref_draws(FACTS + [extra], UNITS + [other], doc_id=D_NEW)) == \
        set(ref_draws(FACTS, UNITS))


# -- the agreement set (§12.3), paired by bridge key then mile -------------------------------------

def enrichment(draws, sha: str | None = None) -> SectionEnrichment:
    return SectionEnrichment(section=SECTION, doc_id=D_NEW,
                             section_sha256=sha or UNITS[0].text_sha256, cards={}, draws=draws,
                             outcome="reply")


def main_draw(n: int, **kw):
    return draw(n=n, bridge="Main Street drawbridge", opening_basis="on_signal",
                periods=[closed(420, 540, days=WEEKDAYS, holidays=True)], **kw)


def oak_draw(n: int, notice: int = 4):
    return draw(n=n, bridge="Oak bridge", opening_basis="on_signal",
                notice_hours=notice).model_copy(update={"mile": g(5.0)})


def test_agreement_set_pairs_by_bridge_key_then_mile_not_by_number():
    refs = ref_draws(FACTS, UNITS)
    # the enrichment names the draws in another order than Phase 3 does
    items = [enrichment([oak_draw(1), main_draw(2)])]
    by = {(SECTION, 1): BINDINGS_821, (SECTION, 2): BINDINGS_821}
    assert paired_refs(items, refs) == {(SECTION, 1): (SECTION, 2), (SECTION, 2): (SECTION, 1)}
    assert agreement_set(by, items, refs) == [(SECTION, 1), (SECTION, 2)]
    # a draw the enrichment names differently pairs by mile
    unnamed = main_draw(2).model_copy(update={"bridge": g("Bridge at mile 3.4")})
    items = [enrichment([oak_draw(1), unnamed])]
    assert paired_refs(items, refs)[(SECTION, 2)] == (SECTION, 1)
    assert agreement_set(by, items, refs) == [(SECTION, 1), (SECTION, 2)]


def test_agreement_set_needs_the_simple_shape_equal_parameters_bindings_and_the_same_text():
    refs = ref_draws(FACTS, UNITS)
    by = {(SECTION, 1): BINDINGS_821, (SECTION, 2): BINDINGS_821}
    # another notice threshold
    assert agreement_set(by, [enrichment([oak_draw(1, notice=5), main_draw(2)])], refs) == \
        [(SECTION, 2)]
    # a period-specific opening rule is no simple shape (P46)
    seasonal = main_draw(2).model_copy(update={"periods": [
        *main_draw(2).periods, on_signal("04-01", "10-31")]})
    assert agreement_set(by, [enrichment([oak_draw(1), seasonal])], refs) == [(SECTION, 1)]
    # even an on-signal period whose window adds nothing to the closed set
    twin = main_draw(2).model_copy(update={"periods": [
        *main_draw(2).periods, on_signal(start=420, end=540, days=WEEKDAYS, holidays=True)]})
    assert agreement_set(by, [enrichment([oak_draw(1), twin])], refs) == [(SECTION, 1)]
    # another closed window, an unreadable one, a missing opening basis
    shifted = main_draw(2).model_copy(update={"periods": [closed(420, 600, days=WEEKDAYS,
                                                                   holidays=True)]})
    unread = main_draw(2).model_copy(update={"periods": [closed(420, 540, days=WEEKDAYS,
                                                                holidays=True, readable=False)]})
    no_basis = main_draw(2).model_copy(update={"opening_basis": g(None)})
    for bad in (shifted, unread, no_basis):
        assert agreement_set(by, [enrichment([oak_draw(1), bad])], refs) == [(SECTION, 1)]
    # a draw without bindings, and a section text other than the one Phase 3 read
    assert agreement_set({(SECTION, 2): BINDINGS_821},
                         [enrichment([oak_draw(1), main_draw(2)])], refs) == [(SECTION, 2)]
    assert agreement_set(by, [enrichment([oak_draw(1), main_draw(2)], sha="f" * 64)],
                         refs) == []


def test_reference_grid_weeks_are_the_specified_ones():
    assert date(2026, 8, 10).weekday() == 0 and date(2026, 9, 7).weekday() == 0
