"""Binding review, sign-off and the bindings manifest (Phase 4 spec §5.2, §12.5, P32, P46, P48;
builder notes 16, 17; preflight C3, C5, C6, N16; Task 17). Stub clients only: no model call.
The analysis is stamped by `bindings_fixtures.stamp_analysed` (CI has no z3); the real Z3
path runs only behind `pytest.importorskip("z3")`."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import types
from collections import Counter
from pathlib import Path

import pytest

from adr_eval.cache import Cache
from adr_eval.llm import CachedStubClient
from adr_store.bindings import build as bb
from adr_store.bindings import manifest as bm
from adr_store.bindings import review as br
from adr_store.bindings.checks import mark_tested
from adr_store.bindings.compile import compile_draw
from adr_store.bindings.dsl import Binding
from adr_store.bindings.manifest import (
    BINDINGS_DIR,
    BindingsError,
    BindingsManifest,
    load_bindings,
    promote_bindings,
    read_bindings_head,
    write_bindings,
)
from adr_store.bindings.review import (
    MAX_TOKENS,
    PROMPT_VERSION,
    VERIFIER,
    review_all,
    review_message,
    review_section,
)
from adr_store.records import canonical_json
from adr_store.tables import extract as ex
from adr_store.tables.contracts import load_contracts
from tests.store.bindings_fixtures import (
    BINDINGS_821,
    BINDINGS_SIGNAL,
    CARD_A,
    CARD_B,
    EMERGENCY_CARD,
    GENERAL_CARD,
    rebuild,
    shift,
    stamp_analysed,
)
from tests.store.test_bindings_compile import WEEKDAYS, card, closed, draw, run
from tests.store.units_fixtures import (  # noqa: F401
    D1,
    DOC_117_NEW,
    ENRICH_ABSENT,
    enrich_reply_821,
    enrich_reply_901,
    make_units_store_with_tables,
    overlay_of,
    review_reply,
    units_enrich_reply,
    units_fixture_numbered,
    units_store,
)

SNAP = "s" * 12
U = "a" * 64          # a units id
T = "b" * 64          # a tables id
CARD_901 = card("33 CFR 117.901(a)", 1400, 1600)
IN_901 = 1410                    # an offset inside the span of § 117.901(a)
CARDS = [CARD_A, CARD_B, CARD_901, GENERAL_CARD, EMERGENCY_CARD]


def candidates(*draws: list[Binding]) -> list[Binding]:
    """The bindings of `draws` tested (the real tests) and stamped analysed."""
    return stamp_analysed(mark_tested([b for d in draws for b in d]))


# § 117.901: a weekday closure and nothing else: the forbid, § 117.5 outside it and
# § 117.31(b)
BINDINGS_DUTY = compile_draw("117.901", draw(n=3, periods=[
    closed(420, 540, days=WEEKDAYS, at=IN_901)]), [CARD_901], GENERAL_CARD, EMERGENCY_CARD)[0]
# the same shape with every window moved half an hour off its parameters: fails its tests
BINDINGS_OFF = shift(run(draw(n=4, periods=[closed(420, 540, days=WEEKDAYS)]))[0], 30)
CANDIDATES = candidates(BINDINGS_821, BINDINGS_SIGNAL, BINDINGS_DUTY)
KNOWN = bm.draw_keys(CANDIDATES)          # every draw of the candidates is known (P49)
DRAW_821 = {b.binding_id for b in CANDIDATES if b.target["selector"]["draw"] == 1}
DRAW_SIGNAL = {b.binding_id for b in CANDIDATES if b.target["selector"]["draw"] == 2}
DRAW_DUTY = {b.binding_id for b in CANDIDATES if b.target["selector"]["draw"] == 3}
B1 = next(b.binding_id for b in CANDIDATES if b.binding_id in DRAW_821 and b.effect == "forbid")
B2 = next(b.binding_id for b in CANDIDATES if b.binding_id in DRAW_SIGNAL
          and b.effect == "forbid")


def stub_review(tmp_path, verdicts=None, *, name=None, default="approve", cls=None):
    """A review stub with its own cache per verdict map (or `name`)."""
    name = name or "review-" + hashlib.sha256(
        json.dumps([verdicts, default], sort_keys=True).encode()).hexdigest()[:12]
    return (cls or CachedStubClient)("stub-opus", Cache(tmp_path / name),
                                     review_reply(verdicts, default))


def reviewed(tmp_path, verdicts=None, bindings=CANDIDATES, **kw):
    return review_all(None, bindings, stub_review(tmp_path, verdicts), cards=CARDS, **kw)


def signed(tmp_path) -> Binding:
    out, _ = reviewed(tmp_path)
    return next(b for b in out if b.binding_id == B1)


def test_fixture_candidates_are_three_whole_analysed_draws():
    assert {b.status for b in CANDIDATES} == {"analysed"}
    assert DRAW_821 and DRAW_SIGNAL and DRAW_DUTY
    assert len(DRAW_821 | DRAW_SIGNAL | DRAW_DUTY) == len(CANDIDATES)
    assert B1 in DRAW_821 and B2 in DRAW_SIGNAL
    assert {b.rule_id for b in CANDIDATES if b.binding_id in DRAW_DUTY} >= {
        GENERAL_CARD.canonical_ref}
    assert {b.status for b in mark_tested(list(BINDINGS_OFF))} == {"rejected"}


# -- review and sign-off (§12.5, P48) --------------------------------------------------------------

def test_only_tested_analysed_approved_bindings_are_signed_off_and_written(tmp_path):
    out, _ = review_all(None, CANDIDATES, stub_review(tmp_path, {B1: "approve", B2: "reject"}),
                        cards=CARDS)
    st = {b.binding_id: b.status for b in out}
    assert st[B1] == "signed_off" and st[B2] == "rejected"
    # P48: the rejected binding's whole draw is rejected; the approved draw is signed off whole
    assert {st[x] for x in DRAW_821 | DRAW_DUTY} == {"signed_off"}
    assert {st[x] for x in DRAW_SIGNAL} == {"rejected"}
    bindings_id, _ = write_bindings(tmp_path, SNAP, U, T, out, known_draws=KNOWN)
    assert {b.binding_id for b in load_bindings(tmp_path, bindings_id)[1]} == \
        DRAW_821 | DRAW_DUTY
    # a tested binding that was never analysed is not reviewed nor signed off, even if the
    # reviewer would approve it: its draw is not wholly analysed, so it is rejected whole
    # (incomplete_draw); a draw wholly rejected stays as it is
    tested = mark_tested(list(BINDINGS_821))
    off = mark_tested(list(BINDINGS_OFF))
    assert {b.status for b in tested} == {"tested"} and {b.status for b in off} == {"rejected"}
    client = stub_review(tmp_path, name="tested")
    out2, report = review_all(None, tested + off, client, cards=CARDS)
    assert client.calls == 0 and report["calls"] == {"made": 0, "cached": 0, "failed": 0}
    assert out2[len(tested):] == off
    assert {b.status for b in out2[:len(tested)]} == {"rejected"}
    assert {b.review["reason"] for b in out2[:len(tested)]} == {"incomplete_draw"}
    assert report["incomplete_draws"] == {"draws": 1, "bindings": len(tested)}
    assert all(b.verifier is None and "verdict" not in b.review for b in out2)
    assert load_bindings(tmp_path, write_bindings(tmp_path, SNAP, U, T, out2,
                                                  known_draws=KNOWN)[0])[1] == []


DUTY_GENERAL = next(b.binding_id for b in CANDIDATES if b.binding_id in DRAW_DUTY
                    and b.rule_id == GENERAL_CARD.canonical_ref)


@pytest.mark.parametrize("status", ["rejected", "tested"])
def test_a_draw_with_a_binding_not_analysed_is_rejected_whole(tmp_path, status):     # I1
    # the reviewer's case: § 117.5 of DRAW_DUTY is not analysed, the rest of the draw is
    mixed = [Binding.model_validate({**b.model_dump(), "status": status})
             if b.binding_id == DUTY_GENERAL else b for b in CANDIDATES]
    client = stub_review(tmp_path)
    out, report = review_all(None, mixed, client, cards=CARDS)
    st = {b.binding_id: b for b in out}
    assert {st[x].status for x in DRAW_DUTY} == {"rejected"}
    assert {st[x].review["reason"] for x in DRAW_DUTY} == {"incomplete_draw"}
    assert all(st[x].verifier is None for x in DRAW_DUTY)
    assert report["incomplete_draws"] == {"draws": 1, "bindings": len(DRAW_DUTY)}
    assert client.calls == 1 and report["sections_reviewed"] == 1        # § 117.901 not sent
    assert {st[x].status for x in DRAW_821 | DRAW_SIGNAL} == {"signed_off"}
    bindings_id, _ = write_bindings(tmp_path, SNAP, U, T, out, known_draws=KNOWN,
                                    candidate_draws=bm.draw_sizes(CANDIDATES))
    loaded = {b.binding_id for b in load_bindings(tmp_path, bindings_id)[1]}
    assert loaded == DRAW_821 | DRAW_SIGNAL and not loaded & DRAW_DUTY
    promote_bindings(tmp_path, bindings_id)
    assert not {b.binding_id for b in load_bindings(
        tmp_path, read_bindings_head(tmp_path))[1]} & DRAW_DUTY


def test_a_draw_is_keyed_by_its_document_and_target(tmp_path):                  # M3, P31
    # the same section and draw in another document version is another draw
    doc = "e" * 64
    other = [rebuild(b, doc_id=doc) for b in BINDINGS_821 if b.effect == "forbid"]
    emergency = next(b for b in BINDINGS_821 if b.rule_id == EMERGENCY_CARD.canonical_ref)
    other += [rebuild(b, doc_id=doc) for b in BINDINGS_821
              if b.effect == "basis" and b.binding_id != emergency.binding_id]
    other.append(rebuild(emergency, doc_id=doc, overrides=sorted(
        b.binding_id for b in other if b.effect == "forbid")))
    cands = candidates(BINDINGS_821, other)
    assert {b.status for b in cands} == {"analysed"}
    sizes = bm.draw_sizes(cands)
    assert [(d[0], d[1], d[2]) for d in sizes] == [(D1, "117.821", 1), (doc, "117.821", 1)]
    assert [d[3] for d in sizes] == [len(BINDINGS_821)] * 2
    victim = next(b.binding_id for b in cands if b.doc_id == doc and b.effect == "forbid")
    out, _ = review_all(None, cands, stub_review(tmp_path, {victim: "reject"}), cards=CARDS)
    assert {b.status for b in out if b.doc_id == doc} == {"rejected"}
    assert {b.status for b in out if b.doc_id == D1} == {"signed_off"}


def test_write_bindings_refuses_an_incomplete_draw(tmp_path):                       # I1
    out, _ = reviewed(tmp_path)
    assert {b.status for b in out} == {"signed_off"}
    # signed off in part: one binding of the draw is not signed off
    part = [Binding.model_validate({**b.model_dump(), "status": "analysed"})
            if b.binding_id == DUTY_GENERAL else b for b in out]
    with pytest.raises(BindingsError, match="signed off in part"):
        write_bindings(tmp_path, SNAP, U, T, part, known_draws=KNOWN)
    # a binding the candidates list for the draw is missing from the input altogether
    short = [b for b in out if b.binding_id != DUTY_GENERAL]
    with pytest.raises(BindingsError, match="holds 2 binding.s., not the 3"):
        write_bindings(tmp_path, SNAP, U, T, short, known_draws=KNOWN,
                       candidate_draws=bm.draw_sizes(CANDIDATES))
    # a draw without its § 117.31(b) emergency basis
    emergency = next(b.binding_id for b in out if b.binding_id in DRAW_DUTY
                     and b.rule_id == EMERGENCY_CARD.canonical_ref)
    with pytest.raises(BindingsError, match="no § 117.31.b. emergency basis"):
        write_bindings(tmp_path, SNAP, U, T, [b for b in out if b.binding_id != emergency],
                       known_draws=KNOWN)


def test_review_record_is_labelled_model_review(tmp_path):
    b = signed(tmp_path)
    assert b.verifier == "model-review:claude_code_opus" == VERIFIER
    assert b.review["verdict"] == "approve" and b.review["reason"]
    assert b.review["prompt_version"] == PROMPT_VERSION == "binding-review@1"
    rejected = next(x for x in reviewed(tmp_path, {B2: "reject"})[0] if x.binding_id == B2)
    assert rejected.verifier == VERIFIER and rejected.review["verdict"] == "reject"
    # a sibling rejected by P48 keeps its own (approving) record and names what blocked it
    sibling = next(x for x in reviewed(tmp_path, {B2: "reject"})[0]
                   if x.binding_id in DRAW_SIGNAL and x.binding_id != B2)
    assert sibling.status == "rejected" and sibling.review["verdict"] == "approve"
    assert sibling.review["blocked_by"] == [B2]


def test_status_changes_are_validated_bindings(tmp_path):
    out, _ = reviewed(tmp_path, {B2: "reject"})
    for b in out:          # ids, versions and required facts are those of the content
        assert Binding.model_validate(b.model_dump()) == b
    # the review records leave identity and logic alone
    assert [(b.binding_id, b.binding_version) for b in out] == \
        [(b.binding_id, b.binding_version) for b in CANDIDATES]


def test_a_missing_or_unparseable_verdict_rejects_the_draw(tmp_path):
    def drop_b2(system, user, repeat):
        reply = json.loads(review_reply()(system, user, repeat))
        mine = {lab for lab, bid in re.findall(
            r"^\[(B\d+)\] binding ([0-9a-f]{64})$", user, re.M) if bid == B2}
        reply["verdicts"] = [v for v in reply["verdicts"] if v["binding"] not in mine]
        return json.dumps(reply)

    client = CachedStubClient("stub-opus", Cache(tmp_path / "drop"), drop_b2)
    out, _ = review_all(None, CANDIDATES, client, cards=CARDS)
    st = {b.binding_id: b for b in out}
    assert st[B2].status == "rejected" and st[B2].review["verdict"] is None
    assert "no verdict" in st[B2].review["reason"]
    assert {st[x].status for x in DRAW_SIGNAL} == {"rejected"}
    assert {st[x].status for x in DRAW_821 | DRAW_DUTY} == {"signed_off"}
    # a reply that never parses (retried once at repeat 1) rejects every binding it covers,
    # with the reason review_unparseable, counted in the report
    junk = CachedStubClient("stub-opus", Cache(tmp_path / "junk"), lambda s, u, r: "no json")
    out, report = review_all(None, CANDIDATES, junk, cards=CARDS)
    assert {b.status for b in out} == {"rejected"}
    assert {b.review["reason"] for b in out} == {"review_unparseable"} == {br.UNPARSEABLE}
    assert set(report["outcomes"]) == {"unparseable"}
    assert junk.calls == 2 * report["sections_reviewed"] == 4
    assert report["review_unparseable"] == {"sections": 2, "draws": 3,
                                            "bindings": len(CANDIDATES)}
    # verdicts that differ for one label are no verdict
    def twice(system, user, repeat):
        reply = json.loads(review_reply()(system, user, repeat))
        reply["verdicts"] += [{**v, "verdict": "reject"} for v in reply["verdicts"]]
        return json.dumps(reply)

    client = CachedStubClient("stub-opus", Cache(tmp_path / "twice"), twice)
    out = review_all(None, CANDIDATES, client, cards=CARDS)[0]
    assert {b.status for b in out} == {"rejected"}
    assert {b.review["reason"] for b in out if b.review["verdict"] is None} == \
        {"no verdict: the reply gave verdicts that differ"}
    # a verdict without a reason, or neither approve nor reject, is no verdict
    for bad in ({"verdict": "approve", "reason": ""}, {"verdict": "maybe", "reason": "x"}):
        def odd(system, user, repeat, bad=bad):
            reply = json.loads(review_reply()(system, user, repeat))
            for v in reply["verdicts"]:
                v.update(bad)
            return json.dumps(reply)
        client = CachedStubClient("stub-opus", Cache(tmp_path / f"odd{bad['verdict']}"), odd)
        assert {b.status for b in review_all(None, CANDIDATES, client, cards=CARDS)[0]} == \
            {"rejected"}


def test_a_limited_review_signs_off_whole_draws_only(tmp_path):        # --limit, P48
    sections = br.review_sections(CANDIDATES)
    assert sections == ["117.821", "117.901"]          # the draws' sections, never 117.5/31
    client = stub_review(tmp_path)
    out, report = review_all(None, CANDIDATES, client, cards=CARDS, limit=1)
    assert client.calls == 1 and report["sections_reviewed"] == 1 == \
        report["sections_total"] - 1
    st = {b.binding_id: b for b in out}
    # § 117.821's draws are reviewed whole (their § 117.5 and § 117.31(b) bindings too)
    assert {st[x].status for x in DRAW_821 | DRAW_SIGNAL} == {"signed_off"}
    # § 117.901's draw is not reviewed at all: no record, still analysed
    assert {st[x].status for x in DRAW_DUTY} == {"analysed"}
    assert all("verdict" not in st[x].review and st[x].verifier is None for x in DRAW_DUTY)
    assert report["bindings"]["not_reviewed"] == len(DRAW_DUTY)
    assert {b.binding_id for b in load_bindings(tmp_path, write_bindings(
        tmp_path, SNAP, U, T, out, known_draws=KNOWN)[0])[1]} == DRAW_821 | DRAW_SIGNAL


# -- one call per section, and what it holds (§12.5, builder note 16, C3) -------------------------

def test_one_review_call_per_section_with_bindings(tmp_path):
    seen = []

    def record(system, user, repeat):
        seen.append(user)
        return review_reply()(system, user, repeat)

    client = CachedStubClient("stub-opus", Cache(tmp_path / "calls"), record)
    # the § 117.821 bindings of a draw rejected by its tests need no call
    off = mark_tested([*BINDINGS_OFF])
    assert {b.status for b in off} == {"rejected"}
    out, report = review_all(None, CANDIDATES + off, client, cards=CARDS)
    # one call per pool section with bindings; none for § 117.5 or § 117.31 alone
    assert client.calls == 2 == report["sections_reviewed"]
    assert report["calls"] == {"made": 2, "cached": 0, "failed": 0}
    assert [m.split("\n", 1)[0] for m in seen] == ["SECTION § 117.821", "SECTION § 117.901"]
    for m in seen:
        section = m.split("\n", 1)[0].removeprefix("SECTION § ")
        # each call carries exactly the bindings of the draws of its section, their general
        # duty and emergency bindings included
        ids = set(re.findall(r"^\[B\d+\] binding ([0-9a-f]{64})$", m, re.M))
        assert ids == {b.binding_id for b in CANDIDATES
                       if b.target["selector"]["section"] == section}
        assert any(b.rule_id == EMERGENCY_CARD.canonical_ref for b in CANDIDATES
                   if b.binding_id in ids)
        # and the verbatim § 117.5 and § 117.31(b) cards, whatever the section
        for c in (GENERAL_CARD, EMERGENCY_CARD):
            assert f"[{c.canonical_ref}] {c.body['text']}" in m
    assert {b.status for b in out[len(CANDIDATES):]} == {"rejected"}
    # a rerun reads the cache: no call is made
    _, again = review_all(None, CANDIDATES, client, cards=CARDS)
    assert client.calls == 2 and again["calls"] == {"made": 0, "cached": 2, "failed": 0}


def test_an_emergency_binding_rejected_in_a_section_rejects_only_its_draw(tmp_path):
    e1 = next(b.binding_id for b in CANDIDATES if b.binding_id in DRAW_821
              and b.rule_id == EMERGENCY_CARD.canonical_ref)
    out, report = reviewed(tmp_path, {e1: "reject"})
    st = {b.binding_id: b.status for b in out}
    assert st[e1] == "rejected" and {st[x] for x in DRAW_821} == {"rejected"}
    # the other draw of the same section and the other section's draw are signed off
    assert {st[x] for x in DRAW_SIGNAL | DRAW_DUTY} == {"signed_off"}
    assert report["bindings"]["rejected_by_review"] == 1


def test_a_truncated_reply_is_retried_then_rejected_and_counted(tmp_path):
    from dataclasses import replace

    calls = []

    class Cut(CachedStubClient):
        """Replies cut at max_tokens: half a JSON object, output at the limit."""

        def _attempt(self, system, user, max_tokens, repeat):
            calls.append(repeat)
            c = super()._attempt(system, user, max_tokens, repeat)
            return replace(c, text=c.text[:len(c.text) // 2], output_tokens=max_tokens)

    client = Cut("stub-opus", Cache(tmp_path / "cut"), review_reply())
    out, report = review_all(None, CANDIDATES, client, cards=CARDS, limit=1)
    assert calls == [0, 1]                         # the retry at repeat 1, then no more
    st = {b.binding_id: b for b in out}
    assert {st[x].status for x in DRAW_821 | DRAW_SIGNAL} == {"rejected"}
    assert {st[x].review["reason"] for x in DRAW_821 | DRAW_SIGNAL} == {"review_unparseable"}
    assert report["review_unparseable"] == {"sections": 1, "draws": 2,
                                            "bindings": len(DRAW_821 | DRAW_SIGNAL)}
    assert report["replies_at_max_tokens"] == 2
    assert report["bindings"]["no_verdict"] == len(DRAW_821 | DRAW_SIGNAL)


def test_the_review_call_passes_max_tokens_2000_and_caches_it(tmp_path):
    sizes = []

    class Sized(CachedStubClient):
        def _attempt(self, system, user, max_tokens, repeat):
            sizes.append(max_tokens)
            return super()._attempt(system, user, max_tokens, repeat)

    client = stub_review(tmp_path, cls=Sized)
    verdicts = review_section("117.821", CARDS, [b for b in CANDIDATES
                                                 if b.rule_id.startswith("33 CFR 117.821")],
                              client)
    assert MAX_TOKENS == 2000 and sizes == [2000]
    assert {v["verdict"] for v in verdicts.values()} == {"approve"}
    assert set(verdicts) == {b.binding_id for b in CANDIDATES
                             if b.rule_id.startswith("33 CFR 117.821")}


def test_review_message_holds_verbatim_cards_quotes_and_rendered_sentences():
    bs = [b for b in CANDIDATES if b.rule_id.startswith("33 CFR 117.821")]
    msg = review_message("117.821", CARDS, bs)
    assert msg.startswith("SECTION § 117.821\n")
    for c in (CARD_A, CARD_B):        # the cards of the section, verbatim with their ids
        assert f"[{c.canonical_ref}] {c.body['text']}" in msg
    for b in bs:
        assert f"binding {b.binding_id}" in msg
        assert f"rule: {b.rule_id} version {b.rule_version}, effect {b.effect}" in msg
        assert f"sentence: {b.derivation}" in msg
        for key, prov in b.params_prov.items():
            assert f"{key} = {json.dumps(prov['value'])} quote: \"{prov['quote']}\"" in msg
    assert "FLAG" not in msg                     # these bindings carry no flags


def test_review_message_names_overrides_and_auto_accepted_values():          # F31, F33
    bs = [b for b in CANDIDATES if b.target["selector"]["draw"] == 1]
    emergency = next(b for b in bs if b.rule_id == EMERGENCY_CARD.canonical_ref)
    assert len(emergency.overrides) == 2
    auto = next(b for b in bs if b.effect == "forbid")
    auto = Binding.model_validate({**auto.model_dump(), "review": {
        "auto_accepted": ["periods[0].end", "periods[0].start"]}})
    bs = [auto if b.binding_id == auto.binding_id else b for b in bs]
    msg = review_message("117.821", CARDS, bs)
    labels = {bid: lab for lab, bid in re.findall(r"^\[(B\d+)\] binding ([0-9a-f]{64})$", msg,
                                                   re.M)}
    over = ", ".join(labels[x] for x in emergency.overrides)
    assert f"  overrides 2 forbid(s): {over}\n" in msg
    assert (f"  FLAG auto_accepted (periods[0].end, periods[0].start) on binding "
            f"{auto.binding_id}: a value code did not find in its quote; check it against the "
            f"quote\n") in msg


# -- the review surfaces the flags (Task 15 carried ruling) ---------------------------------------

FLAG_TEXT = ("(a) The draw of the Main Street drawbridge need not open from 7 a.m. to 9 a.m. "
             "unless a vessel in distress signals. The owner keeps a log of openings.")
_flag = card("33 CFR 117.821(a)", 1000, 1000 + len(FLAG_TEXT), FLAG_TEXT)
FLAG_CARD = _flag.model_copy(update={"body": {**_flag.body, "text": FLAG_TEXT}})
FLAG_SENTENCE = ("The draw of the Main Street drawbridge need not open from 7 a.m. to 9 a.m. "
                 "unless a vessel in distress signals.")


def flagged_bindings() -> list[Binding]:
    d = draw(periods=[closed(420, 540, conditions=["unless"], qualifiers=["days", "holidays"])])
    bs, problems = compile_draw("117.821", d, [FLAG_CARD, CARD_B], GENERAL_CARD,
                                EMERGENCY_CARD)
    assert not problems
    return bs


def test_flagged_bindings_name_the_flag_and_quote_the_full_sentence():
    bs = flagged_bindings()
    forbid = next(b for b in bs if b.effect == "forbid")
    assert forbid.review["sentence_qualifiers"] == ["days", "holidays"]
    assert forbid.review["sentence_conditions"] == ["unless"]
    msg = review_message("117.821", [FLAG_CARD, CARD_B],
                         [b for b in bs if b.rule_id.startswith("33 CFR 117.821")])
    q = f'FLAG sentence_qualifiers (days, holidays) on binding {forbid.binding_id}: '
    assert q in msg
    c = f'FLAG sentence_conditions (unless) on binding {forbid.binding_id}: '
    assert c in msg
    for line in msg.splitlines():
        if line.lstrip().startswith("FLAG sentence_"):
            assert line.endswith(f'full sentence: "{FLAG_SENTENCE}"')
    assert len(FLAG_TEXT) > 100 and f"[{FLAG_CARD.canonical_ref}] {FLAG_TEXT}\n" in msg  # F8
    assert "The owner keeps a log" not in msg.split("BINDINGS")[1]
    assert msg.count("FLAG sentence_qualifiers") == sum(
        "sentence_qualifiers" in b.review for b in bs if b.rule_id.startswith("33 CFR 117.821"))


def test_flags_of_general_duty_bindings_are_surfaced_in_the_draws_section():
    bs = flagged_bindings()
    duty = next(b for b in bs if b.rule_id == GENERAL_CARD.canonical_ref)
    assert duty.review["sentence_conditions"] == ["unless"]
    msg = review_message("117.821", br._cards_for("117.821", bs, [
        FLAG_CARD, CARD_B, GENERAL_CARD, EMERGENCY_CARD]), bs)
    assert f"[{GENERAL_CARD.canonical_ref}] {GENERAL_CARD.body['text']}" in msg
    assert f"FLAG sentence_conditions (unless) on binding {duty.binding_id}" in msg
    assert f'full sentence: "{FLAG_SENTENCE}"' in msg


def test_a_flag_on_real_section_text_quotes_its_sentence(units_store, tmp_path):  # noqa: F811
    from adr_store.bindings.compile import compile_bindings
    from adr_store.bindings.enrich import enrich_section
    from adr_store.units.ecfr import rule_cards

    cards = rule_cards(units_store, DOC_117_NEW, overlay_of(units_store))[0]
    reply = json.dumps(enrich_reply_821(days=ENRICH_ABSENT))      # the weekdays dropped
    client = CachedStubClient("stub-sonnet", Cache(tmp_path / "e"), lambda s, u, r: reply)
    bs, _ = compile_bindings([enrich_section("117.821", units_store, cards, client)], cards)
    forbid = next(b for b in bs if b.rule_id == "33 CFR 117.821(a)" and b.effect == "forbid")
    assert forbid.review["sentence_qualifiers"] == ["days"]
    own = [b for b in bs if b.rule_id.startswith("33 CFR 117.821")]
    msg = review_message("117.821", br._cards_for("117.821", own, cards), own)
    sentence = ("The draw of the Main Street drawbridge, mile 3.4, at Smithfield, need not open "
                "from 7 a.m. to 9 a.m. and from 4 p.m. to 6 p.m. Monday through Friday except "
                "Federal holidays.")
    assert (f"FLAG sentence_qualifiers (days) on binding {forbid.binding_id}: the sentence "
            f"states qualifiers the parameters lack; judge it against the full sentence: "
            f'"{sentence}"') in msg
    assert "FLAG sentence_conditions" not in msg
    a = next(c for c in cards if c.canonical_ref == "33 CFR 117.821(a)")
    assert a.body["text"].startswith("(a) The draw") and len(a.body["text"]) > 100
    assert f"[33 CFR 117.821(a)] {a.body['text']}\n" in msg                          # F8


def test_flagged_bindings_are_counted_per_review(tmp_path):
    bs = stamp_analysed(mark_tested(flagged_bindings()))
    assert {b.status for b in bs} == {"analysed"}
    out, report = review_all(None, bs, stub_review(tmp_path), cards=[FLAG_CARD, CARD_B,
                                                                      GENERAL_CARD,
                                                                      EMERGENCY_CARD])
    flagged = {b.binding_id for b in bs if {"sentence_qualifiers", "sentence_conditions"}
               & set(b.review)}
    assert len(flagged) == 2              # the closure's forbid and § 117.5 outside it
    assert report["flagged"] == len(flagged)
    per = {s["section"]: s["flagged"] for s in report["sections"]}
    assert per == {"117.821": 2}
    # the flags stay on the review record beside the verdict
    for b in out:
        if b.binding_id in flagged:
            assert b.review["verdict"] == "approve" and (
                "sentence_qualifiers" in b.review or "sentence_conditions" in b.review)


def test_the_prompt_asks_for_a_judgement_of_each_flag():
    text = br.system_prompt()
    assert text.splitlines()[0] == f"Prompt version: {PROMPT_VERSION}"
    for word in ("sentence_qualifiers", "sentence_conditions", "full sentence", "approve",
                 "reject", '"verdicts"', '"binding"', '"reason"'):
        assert word in text
    assert "judge" in text.lower()


# -- the manifest (§5.2, N16, C5, C6, builder note 17) -------------------------------------------

def written(tmp_path, verdicts=None, **kw) -> tuple[str, list[Binding]]:
    out, _ = reviewed(tmp_path, verdicts)
    return write_bindings(tmp_path, SNAP, U, T, out, **{"known_draws": KNOWN, **kw})[0], out


def manifest_path(store_path: Path, bindings_id: str) -> Path:
    (p,) = (store_path / BINDINGS_DIR / SNAP).glob(f"bindings-{bindings_id[:16]}.json")
    return p


def test_the_manifest_and_its_data_file_have_their_own_stems_and_hashes(tmp_path):     # N16
    facts_id, enrichment_id = "c" * 64, "d" * 64
    pairs = [["117.821", 3, 1], ["117.821", 4, 2]]
    bindings_id, out = written(tmp_path, {B2: "reject"}, facts_id=facts_id,
                               enrichment_id=enrichment_id, agreement_pairs=pairs)
    mpath = manifest_path(tmp_path, bindings_id)
    assert hashlib.sha256(mpath.read_bytes()).hexdigest() == bindings_id
    m = BindingsManifest.model_validate_json(mpath.read_bytes())
    data = (mpath.parent / m.file).read_bytes()
    assert m.file == f"bindings-data-{m.sha256[:16]}.jsonl" != mpath.name
    assert hashlib.sha256(data).hexdigest() == m.sha256 != bindings_id
    assert (m.snapshot, m.units_id, m.tables_id, m.language) == (SNAP, U, T, "adr-dsl@1")
    assert (m.facts_id, m.enrichment_id) == (facts_id, enrichment_id)
    # the agreement set keeps only draws whose bindings are all in the set (draw 2 was
    # rejected), as Phase 3 (section, draw) keys, with the bindings' draw beside it
    assert m.agreement_set == [("117.821", 3)] and m.agreement_pairs == [("117.821", 3, 1)]
    assert m.bindings == len(DRAW_821 | DRAW_DUTY) == data.count(b"\n")
    lines = data.splitlines()
    assert [json.loads(x)["binding_id"] for x in lines] == sorted(DRAW_821 | DRAW_DUTY)
    assert all(canonical_json(Binding.model_validate_json(x)) == x + b"\n" for x in lines)
    # write-once: the same set again is the same id; nothing else moved HEAD
    assert written(tmp_path, {B2: "reject"}, facts_id=facts_id, enrichment_id=enrichment_id,
                   agreement_pairs=pairs)[0] == bindings_id
    assert read_bindings_head(tmp_path) is None


def test_write_bindings_refuses_an_agreement_draw_or_override_it_cannot_hold(tmp_path):
    out, _ = reviewed(tmp_path)
    with pytest.raises(BindingsError, match="agreement"):
        write_bindings(tmp_path, SNAP, U, T, out, known_draws=KNOWN,
                       agreement_pairs=[["117.821", 1, 1], ["117.821", 2, 1]])
    # an emergency basis whose listed forbid is not in the set (a partial draw) is refused
    partial = [b for b in out if b.binding_id != B1]
    with pytest.raises(BindingsError, match="overrides"):
        write_bindings(tmp_path, SNAP, U, T, partial, known_draws=KNOWN)


def _draws_of(lines: list[bytes]) -> list[tuple]:
    """The manifest `draws` of raw binding lines (doc_id, section, draw, count), sorted."""
    from adr_store.bindings.enrich import section_key

    c = Counter()
    for x in lines:
        r = json.loads(x)
        c[(r["doc_id"], r["target"]["selector"]["section"], r["target"]["selector"]["draw"])] += 1
    return sorted(((*k, n) for k, n in c.items()), key=lambda d: (d[0], section_key(d[1]), d[2]))


def _rewrite(tmp_path, bindings_id: str, lines: list[bytes], draws=None) -> str:
    """Write `lines` as a data file with a matching manifest (`draws` counted from the lines
    unless given), bypassing every check but the format; the new bindings id."""
    m = BindingsManifest.model_validate_json(manifest_path(tmp_path, bindings_id).read_bytes())
    data = b"".join(x if x.endswith(b"\n") else x + b"\n" for x in lines)
    sha = hashlib.sha256(data).hexdigest()
    d = tmp_path / BINDINGS_DIR / SNAP
    (d / f"bindings-data-{sha[:16]}.jsonl").write_bytes(data)
    m2 = m.model_copy(update={"file": f"bindings-data-{sha[:16]}.jsonl", "sha256": sha,
                              "bindings": len(lines),
                              "draws": _draws_of(lines) if draws is None else draws})
    mb = canonical_json(m2)
    new_id = hashlib.sha256(mb).hexdigest()
    (d / f"bindings-{new_id[:16]}.json").write_bytes(mb)
    return new_id


def _line(b: Binding) -> bytes:
    return canonical_json(b).rstrip(b"\n")


def test_load_bindings_refuses_a_tampered_file_and_an_unsigned_binding(tmp_path):
    bindings_id, out = written(tmp_path)
    manifest, loaded = load_bindings(tmp_path, bindings_id)
    assert {b.binding_id for b in loaded} == DRAW_821 | DRAW_SIGNAL | DRAW_DUTY
    data_path = manifest_path(tmp_path, bindings_id).parent / manifest.file
    good = data_path.read_bytes()
    # a changed byte in the data file
    data_path.write_bytes(good.replace(b"Forbid", b"Allow!", 1))
    with pytest.raises(BindingsError, match="hash"):
        load_bindings(tmp_path, bindings_id)
    data_path.write_bytes(good)
    # a changed manifest: its hash is no longer the id
    mpath = manifest_path(tmp_path, bindings_id)
    mgood = mpath.read_bytes()
    mpath.write_bytes(mgood.replace(b'"bindings":', b'"bindings": ', 1))
    with pytest.raises(BindingsError):
        load_bindings(tmp_path, bindings_id)
    mpath.write_bytes(mgood)
    assert load_bindings(tmp_path, bindings_id)[0] == manifest
    lines = good.splitlines()
    signed_off = [Binding.model_validate_json(x) for x in lines]

    def swap(i: int, **update) -> str:
        b = Binding.model_validate({**signed_off[i].model_dump(), **update})
        return _rewrite(tmp_path, bindings_id, [*lines[:i], _line(b), *lines[i + 1:]])

    # an unsigned binding, under hashes that verify
    for status in ("analysed", "rejected", "tested", "proposed"):
        with pytest.raises(BindingsError, match="signed_off"):
            load_bindings(tmp_path, swap(0, status=status))
    # signed off without an approving model-review record
    with pytest.raises(BindingsError, match="model-review"):
        load_bindings(tmp_path, swap(0, verifier=None))
    with pytest.raises(BindingsError, match="model-review"):
        load_bindings(tmp_path, swap(0, verifier="human:alice"))
    with pytest.raises(BindingsError, match="approv"):
        load_bindings(tmp_path, swap(0, review={**signed_off[0].review, "verdict": "reject"}))
    # signed off without its tests or its analysis
    with pytest.raises(BindingsError, match="tests"):
        load_bindings(tmp_path, swap(0, tests=[]))
    with pytest.raises(BindingsError, match="analys"):
        load_bindings(tmp_path, swap(0, analysis={}))
    # content that does not match its ids is refused by the model's own validation
    raw = json.loads(lines[0])
    raw["when"] = {"const": False}
    with pytest.raises(BindingsError, match="binding 1"):
        load_bindings(tmp_path, _rewrite(tmp_path, bindings_id,
                                         [json.dumps(raw, sort_keys=True,
                                                     separators=(",", ":")).encode(),
                                          *lines[1:]]))
    # lines out of order, a duplicate, or not canonical
    with pytest.raises(BindingsError, match="sorted"):
        load_bindings(tmp_path, _rewrite(tmp_path, bindings_id, [lines[1], lines[0],
                                                                 *lines[2:]]))
    with pytest.raises(BindingsError, match="sorted"):
        load_bindings(tmp_path, _rewrite(tmp_path, bindings_id, [lines[0], *lines]))
    with pytest.raises(BindingsError, match="canonical"):
        load_bindings(tmp_path, _rewrite(tmp_path, bindings_id,
                                         [json.dumps(json.loads(lines[0]), indent=1).replace(
                                             "\n", " ").encode(), *lines[1:]]))
    # a count the manifest does not state, an unknown id
    m = BindingsManifest.model_validate_json(mgood)
    first = m.draws[0]
    bad = canonical_json(m.model_copy(update={"bindings": m.bindings + 1, "draws": [
        (*first[:3], first[3] + 1), *m.draws[1:]]}))
    bad_id = hashlib.sha256(bad).hexdigest()
    (mpath.parent / f"bindings-{bad_id[:16]}.json").write_bytes(bad)
    with pytest.raises(BindingsError, match="hold"):
        load_bindings(tmp_path, bad_id)
    # a valid, canonical manifest under another set's id is not that set
    mpath.write_bytes(bad)
    with pytest.raises(BindingsError, match="content hash is not the bindings id"):
        load_bindings(tmp_path, bindings_id)
    mpath.write_bytes(mgood)
    # F20: the data file missing (a store error, not an unexpected one)
    data_path.rename(data_path.with_suffix(".gone"))
    with pytest.raises(BindingsError, match="missing or unreadable"):
        load_bindings(tmp_path, bindings_id)
    data_path.with_suffix(".gone").rename(data_path)
    # F21: a manifest that is valid JSON of the right content but not canonical, under the
    # name and id of its own bytes
    loose = json.dumps(json.loads(mgood), indent=1).encode()
    loose_id = hashlib.sha256(loose).hexdigest()
    (mpath.parent / f"bindings-{loose_id[:16]}.json").write_bytes(loose)
    with pytest.raises(BindingsError, match="not canonical"):
        load_bindings(tmp_path, loose_id)
    # F12: the right manifest under another snapshot's directory
    other = tmp_path / BINDINGS_DIR / "other-snapshot"
    other.mkdir()
    (other / mpath.name).write_bytes(mgood)
    mpath.unlink()
    with pytest.raises(BindingsError, match="describes snapshot"):
        load_bindings(tmp_path, bindings_id)
    (other / mpath.name).rename(mpath)
    assert load_bindings(tmp_path, bindings_id)[0] == manifest
    # I1: a set whose draw lacks a binding its record lists (the counts kept as written,
    # another draw's binding in its place so the totals still agree)
    duty_general = next(x for x in lines if json.loads(x)["binding_id"] == DUTY_GENERAL)
    stray = rebuild(next(b for b in signed_off if b.binding_id in DRAW_SIGNAL
                         and b.rule_id == EMERGENCY_CARD.canonical_ref),
                    target={"tool": "schedule_opening",
                            "selector": {"section": "117.821", "draw": 9}})
    swapped = sorted([x for x in lines if x != duty_general] + [_line(stray)],
                     key=lambda x: json.loads(x)["binding_id"])
    with pytest.raises(BindingsError, match="incomplete draw"):
        load_bindings(tmp_path, _rewrite(tmp_path, bindings_id, swapped, draws=m.draws))
    # I2: a review record that names another served model
    with pytest.raises(BindingsError, match="reviewed by another model"):
        load_bindings(tmp_path, swap(0, review={**signed_off[0].review,
                                                "served_model": "claude-haiku-5-5"}))
    ok = swap(0, review={**signed_off[0].review, "served_model": br.review_model()})
    assert load_bindings(tmp_path, ok)[1][0].review["served_model"] == "claude-opus-5-5"
    with pytest.raises(BindingsError, match="no bindings manifest"):
        load_bindings(tmp_path, "e" * 64)


def test_promote_refuses_unless_all_signed_off(tmp_path):
    bindings_id, out = written(tmp_path)
    lines = (manifest_path(tmp_path, bindings_id).parent /
             load_bindings(tmp_path, bindings_id)[0].file).read_bytes().splitlines()
    b0 = Binding.model_validate_json(lines[0])
    unsigned = _rewrite(tmp_path, bindings_id, [
        _line(Binding.model_validate({**b0.model_dump(), "status": "analysed"})), *lines[1:]])
    with pytest.raises(BindingsError, match="signed_off"):
        promote_bindings(tmp_path, unsigned)
    assert read_bindings_head(tmp_path) is None
    assert not (tmp_path / BINDINGS_DIR / "HEAD").exists()
    # an empty set is no binding set to enforce
    empty, _ = write_bindings(tmp_path, SNAP, U, T, [], known_draws=[])
    with pytest.raises(BindingsError, match="no binding"):
        promote_bindings(tmp_path, empty)
    assert read_bindings_head(tmp_path) is None
    promote_bindings(tmp_path, bindings_id)
    assert read_bindings_head(tmp_path) == bindings_id
    # a refused promotion keeps HEAD where it was
    with pytest.raises(BindingsError):
        promote_bindings(tmp_path, unsigned)
    assert read_bindings_head(tmp_path) == bindings_id
    # HEAD names a manifest that no longer verifies: no current bindings
    data_path = manifest_path(tmp_path, bindings_id).parent / \
        load_bindings(tmp_path, bindings_id)[0].file
    data_path.write_bytes(data_path.read_bytes()[:-2] + b"\n")
    assert read_bindings_head(tmp_path) is None


# -- the commands ----------------------------------------------------------------------------------

def adr(argv, capsys) -> tuple[int, str, str]:
    from adr_store import cli as adr_cli

    code = adr_cli.main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out, out.err


INSTALL = "install the analysis extra: pip install -e '.[analysis]'"


def test_bindings_build_without_z3_says_how_to_install(monkeypatch, capsys, tmp_path):
    # a simulated ImportError, so this runs in CI (which has no z3) and with z3 installed
    monkeypatch.setitem(sys.modules, "adr_store.bindings.analysis", None)
    monkeypatch.setitem(sys.modules, "z3", None)
    store = tmp_path / "store"
    store.mkdir()
    code, out, err = adr(["bindings", "build", "--store", store, "--facts", "c" * 64,
                          "--max-calls", 0], capsys)
    assert code == 2
    assert INSTALL in err
    assert not (store / BINDINGS_DIR).exists()


def test_bindings_build_needs_max_calls_and_facts(capsys, tmp_path):
    for argv in (["--facts", "c" * 64], ["--max-calls", "0"]):
        with pytest.raises(SystemExit) as e:
            adr(["bindings", "build", "--store", tmp_path, *argv], capsys)
        assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        adr(["units", "review", "--store", tmp_path, "--candidates", "c" * 64,
             "--generator", "claude_code_opus"], capsys)
    assert e.value.code == 2


# -- end to end on the fixture store (stub replies, analysis stamped) -----------------------------

@pytest.fixture(scope="module")
def flow_store(tmp_path_factory):
    """The units fixture with its Phase 3 tables on tables/HEAD, a units build carrying the
    rules pass, and a second-pass facts file (all from stubs)."""
    from adr_store.bindings import enrich
    from adr_store.units.build import build_units

    root = tmp_path_factory.mktemp("review")
    store = make_units_store_with_tables(root / "s")
    mp = pytest.MonkeyPatch()
    mp.setattr(enrich, "POOL", {"closed_window": 1, "notice": 1})
    try:
        client = CachedStubClient("stub-claude_code_sonnet", Cache(root / "llm"),
                                  units_enrich_reply)
        enrich.enrich_all(store, client)
        units_id = build_units(store.path, "gov", passes=("rules",),
                               client=ex.metered_client(0, client=client)).units_id
    finally:
        mp.undo()
    numbered = CachedStubClient("stub-numbered", Cache(root / "numbered"),
                                units_fixture_numbered)
    facts, _ = ex.second_pass_all(store, numbered, load_contracts())
    facts_id, _ = ex.write_facts(store.path, store.snapshot_id, facts)
    return {"store": store, "units_id": units_id, "facts_id": facts_id, "llm": root / "llm"}


class ServedStub(CachedStubClient):
    """A cached stub whose provider reports the model that answered."""

    def _attempt(self, system, user, max_tokens, repeat):
        from dataclasses import replace

        return replace(super()._attempt(system, user, max_tokens, repeat),
                       served_model="served-other")


def profiles(monkeypatch, llm: Path, verdicts=None, *, served=False, review_cache=None):
    """Patch the model profiles: the enrichment profile answers from the flow's cache, the
    review profile with `review_reply(verdicts)` (its own cache); the profiles made."""
    from adr_eval import runner
    from adr_store.bindings import enrich

    monkeypatch.setattr(enrich, "POOL", {"closed_window": 1, "notice": 1})
    made = []

    def make_client(name, profiles, cache, max_retries=5):
        made.append(name)
        if name == "claude_code_opus":
            cls = ServedStub if served else CachedStubClient
            return cls(f"stub-{name}", Cache(review_cache or llm.parent / "opus"),
                       review_reply(verdicts))
        return CachedStubClient(f"stub-{name}", Cache(llm), units_enrich_reply)

    monkeypatch.setattr(runner, "make_client", make_client)
    return made


def fake_analysis(monkeypatch) -> list[int]:
    """Stand in for `adr_store.bindings.analysis` (CI has no z3): every draw stamped analysed
    with no finding. Returns the sizes of the draws analysed."""
    seen: list[int] = []
    mod = types.ModuleType("adr_store.bindings.analysis")

    def analyse_draw(bindings):
        seen.append(len(bindings))
        return None

    mod.analyse_draw = analyse_draw
    mod.mark_analysed = lambda bindings, analysis: stamp_analysed(bindings)
    monkeypatch.setitem(sys.modules, "adr_store.bindings.analysis", mod)
    return seen


def build(flow, capsys, *extra) -> tuple[int, str, str]:
    return adr(["bindings", "build", "--store", flow["store"].path, "--facts",
                flow["facts_id"], "--units", flow["units_id"], "--max-calls", 0, *extra], capsys)


def candidates_id(out: str) -> str:
    return next(x.split()[1] for x in out.splitlines() if x.startswith("candidates "))


def test_bindings_build_writes_candidates_with_statuses_and_prints_b1_b2(flow_store, capsys,
                                                                         monkeypatch):
    profiles(monkeypatch, flow_store["llm"])
    sizes = fake_analysis(monkeypatch)
    code, out, err = build(flow_store, capsys)
    assert code == 0, err
    cid = candidates_id(out)
    m, bs = bm.load_candidates(flow_store["store"].path, cid)
    assert m.units_id == flow_store["units_id"] and m.facts_id == flow_store["facts_id"]
    assert m.enrichment_id and m.tables_id and m.language == "adr-dsl@1"
    assert m.bindings == len(bs) > 0
    assert {b.status for b in bs} == {"analysed"}
    draws = {(b.target["selector"]["section"], b.target["selector"]["draw"]) for b in bs}
    assert draws == {("117.821", 1), ("117.821", 2), ("117.901", 1)}
    assert sorted(sizes) == sorted(sum(1 for b in bs if (b.target["selector"]["section"],
                                                         b.target["selector"]["draw"]) == d)
                                   for d in draws)
    # the agreement set (C5): the railroad bridge's notice draw, paired by bridge then mile;
    # the Main Street draw does not open on signal (no basis in the facts), § 117.901 is
    # seasonal; tested on the grid and kept
    assert m.agreement_pairs == [("117.821", 2, 2)]
    grid = [t for b in bs if b.target["selector"] == {"section": "117.821", "draw": 2}
            for t in b.tests if t["kind"] == "grid"]
    assert grid and all(t["mismatches"] == 0 and t["points"] > 0 for t in grid)
    assert (f"B1: {len(bs)} of {len(bs)} binding(s) passed their tests, 0 of 3 draw(s) "
            "rejected whole; grid equal on 1 of 1 agreement-set draw(s)") in out
    assert "B2: 0 conflict(s), 0 vacuous binding(s) over 3 analysed draw(s)" in out
    rep = json.loads((flow_store["store"].path / BINDINGS_DIR / flow_store["store"].snapshot_id
                      / f"bindings-candidates-{cid[:16]}.report.json").read_text())
    assert rep["b1"]["agreement_draws"] == 1 and rep["b2"]["conflicts"] == 0
    assert rep["b1"]["bindings_passed"] == rep["b1"]["bindings"] == len(bs)
    assert m.draws == bm.draw_sizes(bs) and sum(d[3] for d in m.draws) == len(bs)
    assert rep["candidates_id"] == cid and rep["calls"]["made"] == 0
    # the same inputs give the same candidates id (write-once, deterministic)
    code, out2, _ = build(flow_store, capsys)
    assert code == 0 and candidates_id(out2) == cid
    assert read_bindings_head(flow_store["store"].path) is None


def test_bindings_build_rejects_a_draw_whose_grid_disagrees(flow_store, capsys, monkeypatch):
    from adr_store.bindings import checks

    profiles(monkeypatch, flow_store["llm"])
    fake_analysis(monkeypatch)
    monkeypatch.setattr(checks, "grid_equivalence",
                        lambda bs, ref: [{"open_at": "2026-08-10T07:00:00"}])
    code, out, err = build(flow_store, capsys)
    assert code == 0, err
    m, bs = bm.load_candidates(flow_store["store"].path, candidates_id(out))
    st = {(b.target["selector"]["section"], b.target["selector"]["draw"], b.status) for b in bs}
    assert {s for sec, d, s in st if (sec, d) == ("117.821", 2)} == {"rejected"}
    assert {s for sec, d, s in st if (sec, d) != ("117.821", 2)} == {"analysed"}
    assert m.agreement_pairs == []
    assert "grid equal on 0 of 1 agreement-set draw(s)" in out


def test_period_specific_or_flagged_draws_leave_the_agreement_set(flow_store, capsys,
                                                                  monkeypatch):
    from tests.store.test_bindings_compile import notice_period, on_signal

    plain = draw(opening_basis="advance_notice", notice_hours=4)
    assert not bb._period_specific(plain)
    assert bb._period_specific(draw(opening_basis="advance_notice", notice_hours=4,
                                    qualifiers=["times"]))         # P46: a limited notice
    assert bb._period_specific(draw(periods=[closed(420, 540, conditions=["only"])]))
    assert bb._period_specific(draw(periods=[closed(420, 540, qualifiers=["days"])]))
    assert not bb._period_specific(draw(periods=[closed(420, 540), on_signal("04-01", "10-31"),
                                                 notice_period(0, 600)]))
    # the build drops them: with every draw period-specific the agreement set is empty
    profiles(monkeypatch, flow_store["llm"])
    fake_analysis(monkeypatch)
    monkeypatch.setattr(bb, "_period_specific", lambda d: True)
    code, out, err = build(flow_store, capsys)
    assert code == 0, err
    m, bs = bm.load_candidates(flow_store["store"].path, candidates_id(out))
    assert m.agreement_pairs == [] and {b.status for b in bs} == {"analysed"}
    assert not any(t["kind"] == "grid" for b in bs for t in b.tests)
    assert "grid equal on 0 of 0 agreement-set draw(s)" in out


def test_load_candidates_verifies_its_files(flow_store, capsys, monkeypatch):
    profiles(monkeypatch, flow_store["llm"])
    fake_analysis(monkeypatch)
    code, out, _ = build(flow_store, capsys)
    cid = candidates_id(out)
    path = flow_store["store"].path
    m, bs = bm.load_candidates(path, cid)
    data = path / BINDINGS_DIR / m.snapshot / m.file
    good = data.read_bytes()
    try:
        data.write_bytes(good.replace(b'"analysed"', b'"signed_off"', 1))
        with pytest.raises(BindingsError, match="hash"):
            bm.load_candidates(path, cid)
    finally:
        data.write_bytes(good)
    with pytest.raises(BindingsError, match="no candidates manifest"):
        bm.load_candidates(path, "f" * 64)
    # I1: a draw that mixes statuses (one binding rejected, its siblings analysed), under
    # hashes that verify, is refused; write_candidates refuses to write one
    lines = good.splitlines()
    b0 = Binding.model_validate_json(lines[0])
    mixed = [canonical_json(Binding.model_validate({**b0.model_dump(), "status": "rejected"})),
             *[x + b"\n" for x in lines[1:]]]
    raw = b"".join(mixed)
    sha = hashlib.sha256(raw).hexdigest()
    (data.parent / f"bindings-candidates-data-{sha[:16]}.jsonl").write_bytes(raw)
    mb = canonical_json(m.model_copy(update={
        "file": f"bindings-candidates-data-{sha[:16]}.jsonl", "sha256": sha}))
    mid = hashlib.sha256(mb).hexdigest()
    (data.parent / f"bindings-candidates-{mid[:16]}.json").write_bytes(mb)
    with pytest.raises(BindingsError, match="mixes statuses analysed, rejected"):
        bm.load_candidates(path, mid)
    with pytest.raises(BindingsError, match="mixes statuses"):
        bm.write_candidates(path, m.snapshot, m.units_id, m.tables_id,
                            [Binding.model_validate_json(x) for x in mixed], facts_id=None,
                            enrichment_id=None, agreement_pairs=[], report={},
                            known_draws=m.known_draws)
    # a bindings id is no candidates id
    with pytest.raises(BindingsError):
        load_bindings(path, cid)


def test_bindings_build_reads_units_head_without_units(flow_store, capsys, monkeypatch):
    from adr_store.units import overlay as units_overlay  # C6, F25

    path = flow_store["store"].path
    profiles(monkeypatch, flow_store["llm"])
    fake_analysis(monkeypatch)
    units_overlay._set_units_head(path, flow_store["units_id"])      # as the units gate does
    try:
        code, out, err = adr(["bindings", "build", "--store", path, "--facts",
                              flow_store["facts_id"], "--max-calls", 0], capsys)
    finally:
        (path / units_overlay.UNITS_DIR / "HEAD").unlink()
    assert code == 0, err
    m, _ = bm.load_candidates(path, candidates_id(out))
    assert m.units_id == flow_store["units_id"]
    assert f"units {flow_store['units_id'][:12]}" in out
    # P49: the known draws are every enriched draw (117.821 draws 1-2, 117.901 draw 1), and
    # cover every draw with bindings
    doc = {d[0] for d in m.draws}
    assert len(doc) == 1
    (doc,) = doc
    assert {("117.821", 1), ("117.821", 2), ("117.901", 1)} <= {
        (s, n) for d, s, n in m.known_draws if d == doc}
    assert {tuple(d[:3]) for d in m.draws} <= {tuple(k) for k in m.known_draws}


def test_known_draws_take_every_enriched_draw_and_the_table_count_of_empty_sections():
    from adr_store.bindings.build import known_draws
    from adr_store.bindings.enrich import SectionEnrichment
    from tests.store.test_bindings_compile import draw

    failed = draw(n=2).model_copy(update={"opening_basis": g_failed()})
    items = [SectionEnrichment.model_construct(section="117.821", doc_id=D1, draws=[
                 draw(n=1), failed]),
             SectionEnrichment.model_construct(section="117.1081", doc_id=D1, draws=[]),
             SectionEnrichment.model_construct(section="117.5", doc_id=D1, draws=[])]
    got = known_draws(items, {"117.1081": 3, "117.821": 9}, D1)
    # a failed draw is known; an empty pool section takes its table count; a section with
    # enriched draws ignores the fallback; subpart A sections get no draw
    assert got == [(D1, "117.821", 1), (D1, "117.821", 2), (D1, "117.1081", 1),
                   (D1, "117.1081", 2), (D1, "117.1081", 3)]


def g_failed():
    from tests.store.test_bindings_compile import g

    return g(None, null_reason="unparseable")


def reversed_821(system: str, user: str, repeat: int) -> str:
    """The enrichment of § 117.821 naming its draws in the other order (railroad first)."""
    if user.split(" ", 2)[1] == "117.821":
        reply = enrich_reply_821()
        return json.dumps({**reply, "draws": reply["draws"][::-1]})
    return units_enrich_reply(system, user, repeat)


def test_agreement_pairs_keep_the_phase3_and_the_bindings_draw_apart(flow_store, capsys,
                                                                     monkeypatch, tmp_path):
    from adr_eval import runner  # F23
    from adr_store.bindings import enrich

    monkeypatch.setattr(enrich, "POOL", {"closed_window": 1, "notice": 1})
    monkeypatch.setattr(runner, "make_client", lambda name, profiles, cache, max_retries=5:
                        CachedStubClient(f"stub-{name}", Cache(tmp_path / "rev"),
                                         reversed_821))
    fake_analysis(monkeypatch)
    code, out, err = build(flow_store, capsys, "--max-calls", 6)
    assert code == 0, err
    m, bs = bm.load_candidates(flow_store["store"].path, candidates_id(out))
    # the railroad bridge is the enrichment's draw 1 and the Phase 3 second pass's draw 2
    assert m.agreement_pairs == [("117.821", 2, 1)]
    grid = {t["phase3_draw"] for b in bs if b.target["selector"] == {"section": "117.821",
                                                                       "draw": 1}
            for t in b.tests if t["kind"] == "grid"}
    assert grid == {2}


def test_bindings_build_stops_at_the_cap_and_needs_units(flow_store, capsys, monkeypatch,
                                                         tmp_path):
    profiles(monkeypatch, tmp_path / "cold")          # an empty cache
    fake_analysis(monkeypatch)
    d = flow_store["store"].path / BINDINGS_DIR
    before = sorted(d.rglob("*")) if d.exists() else []
    code, out, err = build(flow_store, capsys)
    assert code == 1 and "stopped at --max-calls 0" in out
    assert (sorted(d.rglob("*")) if d.exists() else []) == before
    # without --units the build reads units/HEAD (C6), and there is none
    profiles(monkeypatch, flow_store["llm"])
    code, out, err = adr(["bindings", "build", "--store", flow_store["store"].path, "--facts",
                          flow_store["facts_id"], "--max-calls", 0], capsys)
    assert code == 2 and "units/HEAD" in err


def test_review_sign_off_and_promote_end_to_end(flow_store, capsys, monkeypatch, tmp_path):
    path = flow_store["store"].path
    profiles(monkeypatch, flow_store["llm"], review_cache=tmp_path / "opus")
    fake_analysis(monkeypatch)
    code, out, err = build(flow_store, capsys)
    cid = candidates_id(out)
    _, cands = bm.load_candidates(path, cid)
    base = ["units", "review", "--store", path, "--candidates", cid, "--generator",
            "claude_code_opus"]
    # the cap: nothing written, exit 1
    before = sorted((path / BINDINGS_DIR).rglob("bindings-[0-9a-f]*.json"))
    code, out, err = adr([*base, "--max-calls", 1], capsys)
    assert code == 1 and "stopped at --max-calls 1" in out
    assert sorted((path / BINDINGS_DIR).rglob("bindings-[0-9a-f]*.json")) == before
    # one call per pool section with bindings: §§ 117.821 and 117.901, each with its draws'
    # § 117.5 and § 117.31(b) bindings (builder note 16, amended after Task 17)
    code, out, err = adr([*base, "--max-calls", 2], capsys)
    assert code == 0, err
    assert "2 section(s) reviewed" in out
    assert "status: review complete; 1 model call(s) made, 1 cached" in out
    bindings_id = next(x.split()[1] for x in out.splitlines() if x.startswith("bindings "))
    assert f"adr bindings promote --store {path} --bindings {bindings_id}" in out
    manifest, loaded = load_bindings(path, bindings_id)
    assert {b.binding_id for b in loaded} == {b.binding_id for b in cands}
    assert {b.status for b in loaded} == {"signed_off"}
    assert all(b.verifier == VERIFIER for b in loaded)
    assert manifest.units_id == flow_store["units_id"]                       # C6
    assert manifest.facts_id == flow_store["facts_id"]                       # C5
    assert manifest.agreement_set == [("117.821", 2)]
    report = json.loads((path / BINDINGS_DIR / manifest.snapshot /
                         f"review-{bindings_id[:16]}.report.json").read_text())
    assert report["candidates_id"] == cid and report["served_model_mismatch"] is False
    assert report["sections_reviewed"] == 2 and report["bindings"]["signed_off"] == len(cands)
    assert report["review_unparseable"] == {"sections": 0, "draws": 0, "bindings": 0}
    assert "flagged binding(s)" in out
    records = [json.loads(x) for x in (path / BINDINGS_DIR / manifest.snapshot /
                                       report["verdicts_file"]).read_text().splitlines()]
    assert {r["binding_id"] for r in records} == {b.binding_id for b in cands}
    assert {(r["verdict"], r["status"]) for r in records} == {("approve", "signed_off")}
    assert all(r["reason"] for r in records)
    # show and promote
    code, out, err = adr(["bindings", "show", "--store", path, "--bindings", bindings_id],
                         capsys)
    assert code == 0 and bindings_id[:12] in out and "not HEAD" in out
    code, out, err = adr(["bindings", "promote", "--store", path, "--bindings", bindings_id],
                         capsys)
    assert code == 0, err
    assert read_bindings_head(path) == bindings_id
    code, out, err = adr(["bindings", "show", "--store", path, "--json"], capsys)
    data = json.loads(out)
    assert data["bindings_id"] == bindings_id and data["head"] == bindings_id
    assert data["manifest"]["bindings"] == len(cands)
    (path / BINDINGS_DIR / "HEAD").unlink()


def test_units_review_fails_on_a_served_model_mismatch_after_writing(flow_store, capsys,
                                                                     monkeypatch, tmp_path):
    path = flow_store["store"].path
    profiles(monkeypatch, flow_store["llm"], {}, served=True, review_cache=tmp_path / "srv")
    fake_analysis(monkeypatch)
    code, out, err = build(flow_store, capsys)
    cid = candidates_id(out)
    code, out, err = adr(["units", "review", "--store", path, "--candidates", cid,
                          "--generator", "claude_code_opus", "--max-calls", 4, "--limit", 1],
                         capsys)
    assert code == 1, err                     # the outputs are written, the run has failed
    assert ("status: served model mismatch: served-other != stub-claude_code_opus;"
            in out)
    bindings_id = next(x.split()[1] for x in out.splitlines() if x.startswith("bindings "))
    report = json.loads((path / BINDINGS_DIR / flow_store["store"].snapshot_id /
                         f"review-{bindings_id[:16]}.report.json").read_text())
    assert report["served_model_mismatch"] is True
    assert report["served_models"] == ["served-other"] and report["limit"] == 1
    # one section reviewed (§ 117.821), but served by another model than the review profile's:
    # no verdict counts, so nothing is signed off (the model's verdicts are kept)
    assert report["served_by_another_model"] == {"sections": 1, "bindings": report[
        "sections"][0]["bindings"]}
    assert load_bindings(path, bindings_id)[1] == []
    records = [json.loads(x) for x in (path / BINDINGS_DIR / flow_store["store"].snapshot_id /
                                       report["verdicts_file"]).read_text().splitlines()]
    assert records and {r["reason"] for r in records} == {"served_model_mismatch"}
    assert {r["model_verdict"] for r in records} == {"approve"}


def test_units_review_refuses_a_profile_other_than_opus(flow_store, capsys, monkeypatch,
                                                        tmp_path):                   # I2
    made = profiles(monkeypatch, flow_store["llm"], review_cache=tmp_path / "haiku")
    code, out, err = adr(["units", "review", "--store", flow_store["store"].path,
                          "--candidates", "c" * 64, "--generator", "claude_code_haiku",
                          "--max-calls", 4], capsys)
    assert code == 2 and made == []
    assert "--generator claude_code_haiku: the binding review runs only under the " \
           "claude_code_opus profile" in err


def test_a_review_served_by_another_model_signs_nothing_off(tmp_path):              # I2
    from dataclasses import replace

    class Served(CachedStubClient):
        served = "claude-haiku-5-5"

        def _attempt(self, system, user, max_tokens, repeat):
            return replace(super()._attempt(system, user, max_tokens, repeat),
                           served_model=self.served)

    client = Served("stub-opus", Cache(tmp_path / "haiku"), review_reply())
    out, report = review_all(None, CANDIDATES, client, cards=CARDS)
    assert {b.status for b in out} == {"rejected"}
    assert {b.review["reason"] for b in out} == {"served_model_mismatch"}
    assert {b.review["model_verdict"] for b in out} == {"approve"}
    assert report["served_by_another_model"] == {"sections": 2, "bindings": len(CANDIDATES)}
    Served.served = br.review_model()                  # the review profile's model
    client = Served("stub-opus", Cache(tmp_path / "opus"), review_reply())
    out, _ = review_all(None, CANDIDATES, client, cards=CARDS)
    assert {b.status for b in out} == {"signed_off"}
    assert {b.review["served_model"] for b in out} == {"claude-opus-5-5"}


# -- the real analysis (z3 only) ------------------------------------------------------------------

def test_bindings_build_with_z3_analyses_every_draw(flow_store, capsys, monkeypatch):
    pytest.importorskip("z3")
    profiles(monkeypatch, flow_store["llm"])
    code, out, err = build(flow_store, capsys)
    assert code == 0, err
    m, bs = bm.load_candidates(flow_store["store"].path, candidates_id(out))
    assert {b.status for b in bs} == {"analysed"}
    assert all("stamped" not in b.analysis and "conflicts" in b.analysis for b in bs)
    assert "B2: 0 conflict(s), 0 vacuous binding(s) over 3 analysed draw(s)" in out
    assert m.agreement_pairs == [("117.821", 2, 2)]


def test_a_recorded_draw_with_no_bindings_is_refused():          # re-review N7
    fields = dict(format_version="0.1", snapshot="s", units_id="a" * 64, tables_id="b" * 64,
                  facts_id=None, enrichment_id=None, agreement_set=[], agreement_pairs=[],
                  draws=[["d", "117.821", 1, 2], ["d", "117.821", 2, 0]], file="f",
                  sha256="c" * 64, bindings=2, language="adr-dsl@1",
                  known_draws=[["d", "117.821", 1], ["d", "117.821", 2]])
    with pytest.raises(ValueError, match="at least one binding"):
        bm.BindingsManifest.model_validate(fields)


def test_known_draws_are_sorted_distinct_and_cover_every_draw_with_bindings(tmp_path):  # P49
    fields = dict(format_version="0.1", snapshot="s", units_id="a" * 64, tables_id="b" * 64,
                  facts_id=None, enrichment_id=None, agreement_set=[], agreement_pairs=[],
                  draws=[["d", "117.821", 1, 2]], file="bindings-data-cccccccccccccccc.jsonl",
                  sha256="c" * 64, bindings=2, language="adr-dsl@1")
    known = [["d", "117.821", 1], ["d", "117.821", 2], ["d", "117.1081", 1]]
    ok = bm.BindingsManifest.model_validate({**fields, "known_draws": known})
    assert [list(k) for k in ok.known_draws] == known      # section order: 117.821 < 117.1081
    with pytest.raises(ValueError, match="known draw"):     # a draw with bindings missing
        bm.BindingsManifest.model_validate({**fields, "known_draws": [["d", "117.821", 2]]})
    with pytest.raises(ValueError, match="sorted and distinct"):
        bm.BindingsManifest.model_validate({**fields, "known_draws": known[::-1]})
    # write_bindings refuses a census without a written draw, records the one it is given
    # (sorted) and the bindings id covers it
    out, _ = reviewed(tmp_path)
    with pytest.raises(BindingsError, match="known draw"):
        write_bindings(tmp_path, SNAP, U, T, out, known_draws=KNOWN[1:])
    extra = [(KNOWN[0][0], "117.821", 9), *KNOWN]
    a, _ = write_bindings(tmp_path, SNAP, U, T, out, known_draws=extra)
    b, _ = write_bindings(tmp_path, SNAP, U, T, out, known_draws=KNOWN)
    assert a != b
    assert (KNOWN[0][0], "117.821", 9) in load_bindings(tmp_path, a)[0].known_draws
