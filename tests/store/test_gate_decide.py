"""The gate's decision (Phase 4 spec §12.6 steps 1-6, §13.6; P15, P31, P32, P34, P37; Task 18):
`adr_store.bindings.decide` on the synthetic § 117.821 draw of `bindings_fixtures` (on signal,
4 hours notice at all other times, closed 7-9 a.m. on weekdays except federal holidays, and
§ 117.31(b) overriding both forbids). Store-free; no model call."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from adr_store import applicability as ap
from adr_store.bindings import decide as dm
from adr_store.bindings.decide import (
    SYSTEM_RULES,
    Enforcement,
    cited_sections,
    decide,
    judge,
    next_allowed,
    select,
)
from adr_store.bindings.dsl import Binding, Tri, evaluate
from adr_store.bindings.facts import derive_facts
from adr_store.bindings.reference import ref_next_allowed
from tests.store.bindings_fixtures import (
    BINDINGS_821,
    BINDINGS_821_GROUPED,
    REF_821,
    by_rule,
    rebuild,
    record,
    shift,
)
from tests.store.test_bindings_compile import CARD_A, EMERGENCY_CARD, draw, run
from tests.store.units_fixtures import D1, D2

DOC_NEW, DOC_OLD = D1, D2
FRI_0730 = "2026-08-14T07:30:00"            # a Friday inside the 7-9 a.m. closure
FRI_0730_DT = datetime(2026, 8, 14, 7, 30)
FORBID = by_rule(BINDINGS_821, CARD_A.canonical_ref, "forbid")
EMERGENCY = by_rule(BINDINGS_821, EMERGENCY_CARD.canonical_ref, "basis")


def OPEN(section: str = "117.821", draw: int = 1, open_at: str = FRI_0730) -> dict:
    return {"request": "r1", "section": section, "draw": draw, "open_at": open_at}


def DENY(rule_id: str, reason: str, at: str = FRI_0730, **kw) -> dict:
    return {"request": "r1", "section": "117.821", "draw": 1, "requested_open_at": at,
            "rule_id": rule_id, "reason": reason, **kw}


REC_OK = record(FRI_0730_DT, notice=600, vessel="commercial", conflict=False)
REC_EMERGENCY = record(FRI_0730_DT, notice=600, vessel="public_safety", conflict=False)
REC_NO_CLASS = record(FRI_0730_DT, notice=600, conflict=False)
REC_NO_NOTICE = record(FRI_0730_DT, vessel="commercial", conflict=False)


def test_forbid_true_denies_with_sections_and_next_allowed():
    d = decide("schedule_opening", OPEN(section="117.821", draw=1, open_at=FRI_0730), REC_OK,
               BINDINGS_821, DOC_NEW)
    assert (d.outcome, d.deciding_sections, d.next_allowed) == ("deny", ["117.821"],
                                                                "2026-08-14T09:00:00")
    assert d.rule_ids == [(FORBID.rule_id, FORBID.rule_version)]
    assert {e.binding_id: e.value for e in d.evaluated}[FORBID.binding_id] == "T"
    assert len(d.evaluated) == len(BINDINGS_821)


def test_true_emergency_basis_allows_inside_the_closed_window():                    # P32
    d = decide("schedule_opening", OPEN(open_at=FRI_0730), REC_EMERGENCY, BINDINGS_821, DOC_NEW)
    assert d.outcome == "allow"
    assert d.rule_ids == [(EMERGENCY.rule_id, EMERGENCY.rule_version)]


def test_unknown_emergency_basis_listing_a_true_forbid_escalates():                 # P37
    d = decide("schedule_opening", OPEN(), REC_NO_CLASS, BINDINGS_821, DOC_NEW)
    # the closure is True, but § 117.31(b) is Unknown and lists it: escalate, and only the
    # emergency basis's absent fact is missing (a True forbid's absent facts never count)
    assert (d.outcome, d.missing_facts, d.deciding_sections) == ("escalate", ["vessel_class"],
                                                                 [])
    assert (EMERGENCY.rule_id, EMERGENCY.rule_version) in d.rule_ids
    assert (FORBID.rule_id, FORBID.rule_version) in d.rule_ids
    # the grouped shape: the forbid `or(window, not window and notice short)` is True inside
    # the window with the notice absent; its absent notice is not missing (Task 16's rule)
    rec = record(conflict=False)
    d = decide("schedule_opening", OPEN(), rec, BINDINGS_821_GROUPED, DOC_NEW)
    assert (d.outcome, d.missing_facts) == ("escalate", ["vessel_class"])


def test_unknown_notice_escalates_with_missing_facts():
    noon = "2026-08-14T12:00:00"
    d = decide("schedule_opening", OPEN(open_at=noon), REC_NO_NOTICE, BINDINGS_821, DOC_NEW)
    assert (d.outcome, d.missing_facts) == ("escalate", ["notice_minutes"])
    assert d.next_allowed is None
    # with the notice known and short, the notice complement denies
    short = record(datetime(2026, 8, 14, 12), notice=60, vessel="commercial", conflict=False)
    d = decide("schedule_opening", OPEN(open_at=noon), short, BINDINGS_821, DOC_NEW)
    assert (d.outcome, d.deciding_sections) == ("deny", ["117.821"])
    # notice grows as the requested time moves later: four hours after receipt at 11:00
    assert d.next_allowed == "2026-08-14T15:00:00"


def test_no_basis_escalates_no_rule_binding_covers_this_call():                     # P15
    noon = "2026-08-14T12:00:00"
    d = decide("schedule_opening", OPEN(open_at=noon), REC_OK, [FORBID], DOC_NEW)
    assert d.outcome == "escalate" and d.missing_facts == []
    assert "no rule binding covers this call" in d.message
    # no binding was True or Unknown: the system rule, never the False forbid (Minor 5)
    assert d.rule_ids == [SYSTEM_RULES["no_binding"]]
    assert [e.value for e in d.evaluated] == ["F"]
    # a draw with no binding at all escalates under the no-binding system rule (`decide` does
    # not know which draws exist: `judge` denies an unknown draw first, P49)
    d = decide("schedule_opening", OPEN(draw=9, open_at=noon), REC_OK, BINDINGS_821, DOC_NEW)
    assert (d.outcome, d.rule_ids, d.evaluated) == ("escalate", [SYSTEM_RULES["no_binding"]],
                                                    [])


def _for_doc(bs: list[Binding], doc_id: str) -> list[Binding]:
    return [rebuild(b, doc_id=doc_id, overrides=[]) for b in bs]


def test_bindings_of_another_version_are_never_selected():                           # P31
    old = _for_doc(shift(BINDINGS_821, minutes=120), DOC_OLD)   # the old version: 9-11 a.m.
    every = [*BINDINGS_821, *old]
    assert {b.doc_id for b in select(every, "schedule_opening", OPEN(), DOC_NEW)} == {DOC_NEW}
    assert {b.doc_id for b in select(every, "schedule_opening", OPEN(), DOC_OLD)} == {DOC_OLD}
    d = decide("schedule_opening", OPEN(), REC_OK, every, DOC_NEW)
    assert d.outcome == "deny" and {e.doc_id for e in d.evaluated} == {DOC_NEW}
    # under the old version 7:30 is outside its (shifted) closure: no deny
    d = decide("schedule_opening", OPEN(), REC_OK, every, DOC_OLD)
    assert d.outcome != "deny" and {e.doc_id for e in d.evaluated} == {DOC_OLD}
    # no binding of the version in force: escalate for lack of a binding, nothing evaluated
    d = decide("schedule_opening", OPEN(), REC_OK, BINDINGS_821, DOC_OLD)
    assert d.outcome == "escalate" and d.evaluated == []


@pytest.mark.parametrize("text,keys", [
    ("33 CFR 117.1081(a)", {"117.1081"}), ("§ 117.5", {"117.5"}),
    ("§§117.5 and 117.31", {"117.5", "117.31"}),
    ("closed at mile 117.5", set()), ("117.1081", {"117.1081"}), ("version 1.117.5", set()),
])
def test_cited_sections(text, keys):
    assert cited_sections(text) == keys


def test_cited_sections_normalises_and_collapses_whitespace():
    assert cited_sections("33 C.F.R.\n§ 117.821(a)(1)") == {"117.821"}
    assert cited_sections("Ｓ117.821".replace("Ｓ", "§")) == {"117.821"}
    assert cited_sections("mile 117.821 of the waterway") == set()


def test_deny_request_needs_a_deny_and_a_deciding_citation():                       # P34
    # a deny at a closed time, citing the deciding section: allowed
    d = decide("deny_request", DENY("33 CFR 117.821(a)", "closed 7-9 a.m."), REC_OK,
               BINDINGS_821, DOC_NEW)
    assert (d.outcome, d.deciding_sections) == ("allow", ["117.821"])
    assert d.rule_ids == [(FORBID.rule_id, FORBID.rule_version)]
    # the reason alone may carry the citation
    d = decide("deny_request", DENY("closure", "see § 117.821"), REC_OK, BINDINGS_821, DOC_NEW)
    assert d.outcome == "allow"
    # the right outcome but no deciding section cited (a mile number is no citation): denied,
    # with the evaluation's sections
    for rule_id, reason in (("33 CFR 117.5", "general duty"), ("closure", "at mile 117.821")):
        d = decide("deny_request", DENY(rule_id, reason), REC_OK, BINDINGS_821, DOC_NEW)
        assert (d.outcome, d.deciding_sections) == ("deny", ["117.821"])
    # a correct citation of an opening the rules allow: denied under the allowing basis
    noon = "2026-08-14T12:00:00"
    ok = record(datetime(2026, 8, 14, 12), notice=600, vessel="commercial", conflict=False)
    d = decide("deny_request", DENY("33 CFR 117.821(a)", "closed", at=noon), ok, BINDINGS_821,
               DOC_NEW)
    assert (d.outcome, d.deciding_sections) == ("deny", [])
    true_bases = {e.binding_id for e in d.evaluated if e.value == "T"}
    assert d.rule_ids == sorted({(b.rule_id, b.rule_version) for b in BINDINGS_821
                                 if b.binding_id in true_bases and b.effect == "basis"})
    assert (FORBID.binding_id not in true_bases) and d.rule_ids
    # an emergency the gate would allow cannot be denied either
    d = decide("deny_request", DENY("33 CFR 117.821(a)", "closed"), REC_EMERGENCY, BINDINGS_821,
               DOC_NEW)
    assert d.outcome == "deny"


def test_escalate_and_cancel_are_allowed_under_system_rules():
    esc = {"request": "r1", "section": "117.821", "draw": 1, "missing": ["vessel_class"],
           "reason": "unknown class"}
    d = decide("escalate_request", esc, {}, BINDINGS_821, DOC_NEW)
    assert (d.outcome, d.rule_ids) == ("allow", [SYSTEM_RULES["escalate"]])
    can = {"opening_id": "o1", "section": "117.821", "draw": 1}
    d = decide("cancel_opening", can, {}, BINDINGS_821, DOC_NEW)
    assert (d.outcome, d.rule_ids) == ("allow", [SYSTEM_RULES["cancel"]])
    assert SYSTEM_RULES["escalate"] == ("adr.desk.escalate@1", "1")
    assert SYSTEM_RULES["cancel"] == ("adr.desk.cancel@1", "1")
    assert SYSTEM_RULES["fail_closed"] == ("adr.gate.fail-closed@1", "1")


@pytest.mark.parametrize("tool,args", [
    ("schedule_opening", {**OPEN(), "draw": 0}),
    ("schedule_opening", {**OPEN(), "draw": True}),
    ("schedule_opening", {**OPEN(), "open_at": "2026-08-14"}),
    ("schedule_opening", {**OPEN(), "notice_received_at": "2026-08-14T01:00:00"}),   # P13
    ("deny_request", {k: v for k, v in DENY("x", "y").items() if k != "requested_open_at"}),
    ("escalate_request", {"section": "117.821", "draw": 1, "missing": "x", "reason": "r"}),
    ("cancel_opening", {"section": "117.821", "draw": 1}),
])
def test_malformed_arguments_are_refused(tool, args):
    with pytest.raises(ValueError):
        decide(tool, args, REC_OK, BINDINGS_821, DOC_NEW)


# -- next_allowed: §12.6's definition --------------------------------------------------------------

def _definition(bs: list[Binding], open_at: datetime, rec: dict) -> datetime | None:
    """§12.6 read literally: the first later minute in seven days with no forbid True (once
    the forbids a True overriding basis lists are set aside) and a basis True."""
    at = open_at.replace(second=0)
    for _ in range(7 * 1440):
        at += timedelta(minutes=1)
        f = derive_facts(at, rec)
        v = {b.binding_id: evaluate(b.when, f) for b in bs}
        gone = {x for b in bs if b.overrides and v[b.binding_id] is Tri.T for x in b.overrides}
        if not any(b.effect == "forbid" and b.binding_id not in gone and v[b.binding_id] is Tri.T
                   for b in bs) and any(b.effect == "basis" and v[b.binding_id] is Tri.T
                                        for b in bs):
            return at
    return None


@pytest.mark.parametrize("at,rec", [
    (FRI_0730_DT, REC_OK), (FRI_0730_DT, REC_NO_NOTICE), (FRI_0730_DT, REC_NO_CLASS),
    (datetime(2026, 8, 14, 12, 0), record(datetime(2026, 8, 14, 12), notice=30)),
    (datetime(2026, 9, 7, 7, 30), REC_OK),               # Labor Day: no closure
    (datetime(2026, 8, 14, 8, 59, 40), REC_OK),
])
def test_next_allowed_follows_the_definition_and_the_reference(at, rec):
    got = next_allowed(BINDINGS_821, at, rec)
    assert got == _definition(BINDINGS_821, at, rec)
    # an on-signal draw: the reference evaluator shares the definition
    assert got == ref_next_allowed(REF_821, at, rec)


def test_next_allowed_on_an_advance_notice_draw_follows_the_definition():
    """An advance-notice draw is tested against §12.6 directly, not the reference (the two
    differ there by construction)."""
    bs = run(draw(opening_basis="advance_notice", notice_hours=4))[0]
    at = datetime(2026, 8, 12, 7, 0)
    rec = record(at, notice=60, vessel="commercial", conflict=False)
    assert next_allowed(bs, at, rec) == datetime(2026, 8, 12, 10, 0) == _definition(bs, at, rec)
    # notice unknown: the basis is never True, so nothing is allowed within the week
    assert next_allowed(bs, at, record(vessel="commercial")) is None
    # an emergency class is allowed at once
    em = record(at, vessel="distress", conflict=False)
    assert next_allowed(bs, at, em) == at + timedelta(minutes=1) == _definition(bs, at, em)


def test_next_allowed_catches_a_scan_that_ignores_overrides(monkeypatch):
    """A planted fault: forbids set aside by a True overriding basis still block."""
    def no_overrides(bindings, values):
        if any(b.effect == "forbid" and values[b.binding_id] is Tri.T for b in bindings):
            return False
        return any(b.effect == "basis" and values[b.binding_id] is Tri.T for b in bindings)

    rec = record(FRI_0730_DT, vessel="distress", conflict=False)
    right = next_allowed(BINDINGS_821, FRI_0730_DT, rec)
    monkeypatch.setattr(dm, "_next_ok", no_overrides)
    assert next_allowed(BINDINGS_821, FRI_0730_DT, rec) != right == _definition(
        BINDINGS_821, FRI_0730_DT, rec)


# -- judge: fail closed (P15) ----------------------------------------------------------------------

def _env(doc_id: str, valid_from: date, valid_to: date | None, superseded_by=None):
    return ap.Envelope(doc_id=doc_id, chain_id="ecfr:33:117", version_label="v",
                       supersedes=None, superseded_by=superseded_by, valid_from=valid_from,
                       valid_to=valid_to, validity_basis="ecfr_snapshot", status="codified",
                       jurisdiction="US-federal", issuer="Coast Guard", authority_tier=1,
                       provenance=[])


def signed(bs: list[Binding]) -> tuple[Binding, ...]:
    return tuple(Binding.model_validate({**b.model_dump(), "status": "signed_off"}) for b in bs)


ENF = Enforcement(
    bindings_id="b" * 64, units_id="u" * 64, snapshot="s" * 64, bindings=signed(BINDINGS_821),
    envelopes={DOC_OLD: _env(DOC_OLD, date(2025, 6, 27), date(2026, 6, 26), DOC_NEW),
               DOC_NEW: _env(DOC_NEW, date(2026, 6, 26), None)},
    known={DOC_NEW: frozenset({("117.821", 1), ("117.821", 2)}),     # draw 2 has no binding
           DOC_OLD: frozenset({("117.821", 1)})},
    texts={})
FC = SYSTEM_RULES["fail_closed"]


def test_judge_equals_decide_on_a_well_formed_call():
    d = judge(ENF, "schedule_opening", OPEN(), REC_OK, "2026-08-14T05:30:00")
    assert d == decide("schedule_opening", OPEN(), REC_OK, list(ENF.bindings), DOC_NEW)
    assert d.fail_closed is None and d.outcome == "deny"
    # no as_of: the version not superseded
    assert judge(ENF, "schedule_opening", OPEN(), REC_OK, None) == d


@pytest.mark.parametrize("tool,args,rec,as_of,why", [
    ("open_bridge", OPEN(), REC_OK, "2026-08-14", "unknown tool"),
    ("schedule_opening", {**OPEN(), "draw": "1"}, REC_OK, "2026-08-14", "malformed"),
    ("schedule_opening", OPEN(), {"vessel_class": "commercial"}, "2026-08-14", "malformed"),
    ("schedule_opening", OPEN(), {"vessel_class": {"value": "tanker"}}, "2026-08-14",
     "malformed"),
    ("schedule_opening", OPEN(), REC_OK, "14 Aug 2026", "malformed"),
    ("schedule_opening", OPEN(), REC_OK, "2020-01-01", "no single version"),
    ("schedule_opening", OPEN(section="117.9999"), REC_OK, "2026-08-14", "unknown target"),
    ("cancel_opening", {"opening_id": "o", "section": "117.9999", "draw": 1}, {},
     "2026-08-14", "unknown target"),
    ("schedule_opening", OPEN(open_at="1970-01-02T07:30:00"), REC_OK, "2026-08-14",
     "malformed"),                                     # a date outside the holiday rules
])
def test_judge_fails_closed(tool, args, rec, as_of, why):
    d = judge(ENF, tool, args, rec, as_of)
    assert (d.outcome, d.rule_ids) == ("deny", [FC]) and why in d.fail_closed


@pytest.mark.parametrize("tool,extra", [
    ("schedule_opening", {"open_at": "2026-08-14T12:00:00"}),
    ("deny_request", {"requested_open_at": "2026-08-14T07:30:00", "rule_id": "§ 117.821",
                      "reason": "closed"}),
    ("escalate_request", {"missing": [], "reason": "?"}),
    ("cancel_opening", {"opening_id": "o1"}),
])
def test_an_unknown_draw_denies_and_a_known_draw_without_bindings_escalates(tool, extra):
    """P49: a (section, draw) absent from the known draws of the version in force is an
    unknown target for every gated tool (fail closed); a known draw with no binding escalates
    (P15), and the desk rules still allow its escalation or cancellation."""
    for section, n in (("117.821", 3), ("117.821", 99999), ("117.5", 1), ("117.31", 1)):
        d = judge(ENF, tool, {"section": section, "draw": n, **extra}, REC_OK, "2026-08-14")
        assert (d.outcome, d.rule_ids) == ("deny", [FC]) and "unknown target" in d.fail_closed
    # § 117.821 draw 2 is known under the newest version only
    d = judge(ENF, tool, {"section": "117.821", "draw": 2, **extra}, REC_OK, "2025-08-14")
    assert d.rule_ids == [FC] and "unknown target" in d.fail_closed
    d = judge(ENF, tool, {"section": "117.821", "draw": 2, **extra}, REC_OK, "2026-08-14")
    assert d.fail_closed is None
    if tool == "schedule_opening":
        assert (d.outcome, d.rule_ids) == ("escalate", [SYSTEM_RULES["no_binding"]])
    elif tool == "deny_request":
        assert (d.outcome, d.evaluated_outcome) == ("deny", "escalate")
    else:
        assert d.outcome == "allow"


def test_a_denied_deny_request_carries_the_evaluated_outcome():                     # Minor 6
    noon = "2026-08-14T12:00:00"
    ok = record(datetime(2026, 8, 14, 12), notice=600, vessel="commercial", conflict=False)
    d = decide("deny_request", DENY("§ 117.821", "closed", at=noon), ok, BINDINGS_821, DOC_NEW)
    assert (d.outcome, d.evaluated_outcome) == ("deny", "allow")
    d = decide("deny_request", DENY("§ 117.821", "closed"), REC_NO_CLASS, BINDINGS_821, DOC_NEW)
    assert (d.outcome, d.evaluated_outcome) == ("deny", "escalate")
    d = decide("deny_request", DENY("§ 117.821", "closed"), REC_OK, BINDINGS_821, DOC_NEW)
    assert (d.outcome, d.evaluated_outcome) == ("allow", "deny")
    d = decide("schedule_opening", OPEN(), REC_OK, BINDINGS_821, DOC_NEW)
    assert d.evaluated_outcome is None


def test_judge_fails_closed_on_any_exception_and_on_unsigned_bindings(monkeypatch):
    unsigned = Enforcement(**{**ENF.__dict__, "bindings": tuple(BINDINGS_821)})
    d = judge(unsigned, "schedule_opening", OPEN(), REC_OK, "2026-08-14")
    assert d.rule_ids == [FC] and "sign-off" in d.fail_closed

    def boom(*a, **k):
        raise RuntimeError("evaluator crashed")

    monkeypatch.setattr(dm, "evaluate", boom)
    d = judge(ENF, "schedule_opening", OPEN(), REC_OK, "2026-08-14")
    assert (d.outcome, d.rule_ids) == ("deny", [FC]) and "RuntimeError" in d.fail_closed


def test_every_decision_carries_a_rule_id_and_version():                            # G1
    cases = [("schedule_opening", OPEN(), r) for r in (REC_OK, REC_EMERGENCY, REC_NO_CLASS,
                                                       REC_NO_NOTICE, {})]
    cases += [("schedule_opening", OPEN(draw=7), REC_OK),
              ("deny_request", DENY("33 CFR 117.821", "x"), REC_OK),
              ("open_bridge", {}, {})]
    for tool, args, rec in cases:
        d = judge(ENF, tool, args, rec, "2026-08-14")
        assert d.rule_ids and all(r and v for r, v in d.rule_ids)
