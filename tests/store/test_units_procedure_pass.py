"""The procedure pass (Phase 4 spec §6.2–6.5, Task 10): one cached call per procedure and field
group, the checks of §6.3, spec-group recompilation (T5) and the build that reads the replies
from the cache. Stub clients only: no test calls a model or needs the model CLI (C9)."""

from __future__ import annotations

import json
import shutil

import pytest

from adr_eval import llm
from adr_eval.cache import Cache
from adr_eval.llm import CachedStubClient
from adr_eval.pipeline import BudgetExceeded
from adr_store.store import Store
from adr_store.tables.extract import metered_client
from adr_store.units import procedure_pass as pp
from adr_store.units.build import build_units, unit_reports
from adr_store.units.contracts import UNIT_CONTRACT_DIR, load_unit_contracts
from adr_store.units.grounding import PassConfig, ground, load_pass_config, time_in_quote
from adr_store.units.overlay import UNITS_DIR, load_units_manifest
from adr_store.units.procedure_pass import (
    FIELDS,
    MAX_TOKENS,
    PROMPT_VERSION,
    check_field,
    compile_procedure,
    compile_procedures,
    pass_prompt,
    store_procedures,
)
from tests.store.units_fixtures import (  # noqa: F401
    DOC_IRM,
    UNITS_DOCS,
    make_units_store,
    units_store,
)

CFG = load_pass_config("procedure")
SPECS = dict(CFG.specs)
IRM_REF = "IRM 21.4.1.3.1"
REAL_QUOTE = "Research the account with Command Code IMFOLT to find the refund transaction."
NUMBER_QUOTE = "Request the refund trace with Command Code REQ77 when no TC 846 has posted after " \
    "21 days."


def n_procedures(store: Store) -> int:
    return len(store_procedures(store))


def _fields_of(system: str) -> list[str]:
    """The fields a pass prompt asks for (read from its "Specs:" line)."""
    line = next(x for x in system.splitlines() if x.startswith("Specs: "))
    return [s.split(".")[1].split("@")[0] for s in line.removeprefix("Specs: ").split(", ")]


def _first_line(user: str) -> str:
    section = user.split("\n\nSKELETON:\n")[0]
    return next(x for x in section.splitlines() if x.strip()).strip().lstrip("#").strip()


def replies(system: str, user: str, repeat: int) -> str:
    """A well-formed reply for every procedure: each asked field quotes the procedure's first
    line; `not_for` is absent; a trigger example names the field's spec version, so a spec
    bump changes the reply."""
    quote = _first_line(user)
    spec = dict(s.split(".", 1)[1].split("@") for s in
                next(x for x in system.splitlines() if x.startswith("Specs: "))
                .removeprefix("Specs: ").split(", "))
    out = {}
    for f in _fields_of(system):
        if f == "not_for":
            out[f] = {"value": None, "quotes": [], "null_reason": "absent"}
        elif f == "when_to_use":
            out[f] = {"value": f"Use when: {quote}", "quotes": [quote], "null_reason": None}
        else:
            out[f] = {"value": [f"example {spec[f]} one", f"example {spec[f]} two"],
                      "quotes": [quote], "null_reason": None}
    return json.dumps(out)


def reply(**fields) -> str:
    """A full reply (every field) with `fields` replacing the defaults."""
    base = {"when_to_use": {"value": "Use when a refund is missing.", "quotes": [REAL_QUOTE],
                            "null_reason": None},
            "not_for": {"value": None, "quotes": [], "null_reason": "absent"},
            "trigger_examples": {"value": ["Where is my refund?", "My refund never came"],
                                 "quotes": [REAL_QUOTE], "null_reason": None},
            "problem_abstractions": {"value": ["missing refund"], "quotes": [REAL_QUOTE],
                                     "null_reason": None}}
    return json.dumps({**base, **fields})


def stub(tmp_path, fn, name: str = "llm", **kw) -> CachedStubClient:
    return CachedStubClient("stub-sonnet", Cache(tmp_path / name), fn, **kw)


def irm_unit(store: Store):
    return next(u for u in store_procedures(store) if u.canonical_ref == IRM_REF)


@pytest.fixture
def one_field(units_store, tmp_path):  # noqa: F811
    """`one_field(reply_text, field="when_to_use")`: the checked value of `field` when the
    model replies `reply_text` for the IRM procedure."""
    unit = irm_unit(units_store)
    text = units_store.text(unit.doc_id)
    made = []

    def run(reply_text: str, field: str = "when_to_use"):
        client = stub(tmp_path, lambda s, u, r: reply_text, name=f"llm{len(made)}")
        made.append(client)
        return compile_procedure(unit, text, client, CFG)[field]

    return run


# -- grounding helpers ---------------------------------------------------------------------------

def test_ground_finds_a_quote_across_whitespace_and_refuses_what_is_not_there():
    text = "Use this  runbook\nwhen the gateway fails."
    assert ground(text, "this runbook when the") == (4, 26)
    assert text[slice(*ground(text, "runbook when"))] == "runbook\nwhen"
    assert ground(text, "not in the text") is None
    assert ground(text, "   ") is None and ground(text, None) is None


@pytest.mark.parametrize(("minutes", "quote", "found"), [
    (450, "from 7:30 a.m. to 9 a.m.", True),
    (540, "from 7:30 a.m. to 9 a.m.", True),
    (420, "need not open from 7 a.m.", True),
    (1140, "until 7 p.m. daily", True),
    (1170, "between 7:30 PM and", True),
    (720, "from noon to 2 p.m.", True),
    (0, "from midnight to 6 a.m.", True),
    (1440, "from 10 p.m. to midnight", True),
    (0, "12 a.m.", True),
    (720, "12 p.m.", True),
    (450, "from 7 a.m. to 9 a.m.", False),       # 7:30 is not stated
    (1170, "7:30 a.m.", False),                   # a.m., not p.m.
    (420, "7 days a week", False),               # a number is no clock time
    (600, "10 amendments", False),
])
def test_time_in_quote(minutes, quote, found):
    assert time_in_quote(minutes, quote) is found


def test_the_committed_config_has_one_procedure_group_and_the_contract_spec_ids():   # N7
    assert CFG.prompt_version == PROMPT_VERSION == "procedure-compile@1"
    assert len(CFG.groups) == 1 and sorted(*CFG.groups.values()) == sorted(FIELDS)
    contract = load_unit_contracts()["procedure"]
    assert SPECS == {f.name: f.spec_id for f in contract.fields if f.name in FIELDS}
    with pytest.raises(ValueError, match="rules"):
        load_pass_config("rules")


def test_a_pass_config_names_each_field_once():
    with pytest.raises(ValueError, match="once"):
        PassConfig(prompt_version=PROMPT_VERSION,
                   groups={"a": ["when_to_use", "not_for"], "b": ["not_for"]}, specs=SPECS)
    with pytest.raises(ValueError, match="specs"):
        PassConfig(prompt_version=PROMPT_VERSION, groups={"a": list(FIELDS)},
                   specs={**SPECS, "steps": "procedure.steps@1"})
    partial = PassConfig(prompt_version=PROMPT_VERSION, groups={"a": ["when_to_use"]},
                         specs={"when_to_use": SPECS["when_to_use"]})
    with pytest.raises(ValueError, match="field"):
        pp.check_config(partial)


def test_the_prompt_names_version_and_specs_and_the_rules_of_the_pass():
    p = pass_prompt("main", CFG)
    assert f"Prompt version: {PROMPT_VERSION}" in p
    assert ", ".join(SPECS[f] for f in FIELDS) in p
    low = p.lower()
    assert "at least one" in low and "verbatim" in low                   # every value quoted
    assert "not_for" in p and "states what the procedure is not for" in low   # Phase 3 P22
    assert "do not write steps, guards or edges" in low


# -- one call per procedure, and a rebuild makes none ---------------------------------------------

def test_one_call_per_procedure_and_a_rebuild_makes_none(units_store, tmp_path):  # noqa: F811
    client = stub(tmp_path, replies)
    first, report = compile_procedures([units_store], client, CFG)
    assert client.calls == n_procedures(units_store) == 3
    assert sorted(first) == sorted(u.unit_id for u in store_procedures(units_store))
    meter = metered_client(0, client=client)
    again, again_report = compile_procedures([units_store], meter, CFG)
    assert meter.budget.calls == 0 and again == first
    mine = report["stores"][str(units_store.path)]
    assert mine["calls"] == {"made": 3, "cached": 0, "failed": 0}
    assert again_report["stores"][str(units_store.path)]["calls"] == {
        "made": 0, "cached": 3, "failed": 0}
    assert mine["fields"]["when_to_use"] == {"quotes_given": 3, "quotes_grounded": 3,
                                             "values": 3, "verified": 3, "auto-accepted": 0,
                                             "nulls": {}}
    assert mine["fields"]["not_for"]["nulls"] == {"absent": 3}
    assert report["max_tokens"] == MAX_TOKENS == 1500


def test_each_call_sends_the_section_text_and_the_numbered_skeleton(units_store, tmp_path):  # noqa: F811
    seen = []

    def record(system, user, repeat):
        seen.append((system, user))
        return replies(system, user, repeat)

    unit = irm_unit(units_store)
    text = units_store.text(unit.doc_id)
    client = stub(tmp_path, record)
    compile_procedure(unit, text, client, CFG)
    (system, user), = seen
    ref = unit.source_refs[0]
    section, skeleton = user.split("\n\nSKELETON:\n")
    assert section == text[ref.start:ref.end]
    lines = skeleton.splitlines()
    steps = [s for s in unit.body["steps"] if s["text"]]
    assert len(lines) == len(steps)
    assert lines[0] == f"1. {' '.join(steps[0]['text'].split())}"
    assert system == pass_prompt("main", CFG)
    # the cache key holds the declared token limit (C3)
    assert client.is_cached(system, user, max_tokens=MAX_TOKENS)


class ServedStub(CachedStubClient):
    """A cached stub whose provider reports the model that answered."""

    def _attempt(self, system, user, max_tokens, repeat):
        from dataclasses import replace

        return replace(super()._attempt(system, user, max_tokens, repeat),
                       served_model="served-sonnet")


def test_served_models_are_reported_and_recorded_in_the_lineage(units_store, tmp_path):  # noqa: F811,E501
    client = ServedStub("stub-sonnet", Cache(tmp_path / "llm"), replies)
    _, report = compile_procedures([units_store], client, CFG)
    assert report["served_models"] == ["served-sonnet"]
    assert report["stores"][str(units_store.path)]["served_models"] == ["served-sonnet"]
    res = build_units(units_store.path, "bench", passes=("procedure",),
                      client=metered_client(0, client=client))      # from the cache
    m = load_units_manifest(units_store.path, res.units_id)
    proc = next(f for f in m.units if f.type == "procedure")
    path = units_store.path / UNITS_DIR / m.snapshot / proc.file
    assert {json.loads(x)["lineage"]["served_model"] for x in path.read_text().splitlines()} \
        == {"served-sonnet"}


def test_the_canary_limit_compiles_the_first_procedures(units_store, tmp_path):  # noqa: F811
    client = stub(tmp_path, replies)
    done, report = compile_procedures([units_store], client, CFG, limit=2)
    assert client.calls == 2 and len(done) == 2
    mine = report["stores"][str(units_store.path)]
    assert (mine["available"], mine["procedures"]) == (3, 2)


# -- the checks (§6.3) -----------------------------------------------------------------------------

def test_a_field_is_kept_if_one_quote_reslices(one_field):
    v = one_field(reply(when_to_use={"value": "Use when…", "quotes": ["not in text", REAL_QUOTE],
                                     "null_reason": None}))
    assert v.value == "Use when…" and v.quotes_given == 2 and v.quotes_grounded == 1
    assert v.null_reason is None and [q[0] for q in v.quotes] == [REAL_QUOTE]


def test_a_stored_quote_has_document_offsets(units_store, one_field):  # noqa: F811
    """Task 1 carry: offsets are in the document's canonical text, not in the section slice
    the model saw (the IRM section starts well inside its document)."""
    v = one_field(reply())
    (quote, start, end), = v.quotes
    unit = irm_unit(units_store)
    text = units_store.text(DOC_IRM)
    assert unit.source_refs[0].start > 0
    assert text[start:end] == quote == REAL_QUOTE
    assert unit.source_refs[0].start <= start < end <= unit.source_refs[0].end


def test_a_quote_is_located_across_whitespace_and_stored_as_the_slice(units_store, one_field):  # noqa: F811
    spaced = REAL_QUOTE.replace(" with ", "   with\n")
    v = one_field(reply(when_to_use={"value": "x", "quotes": [spaced], "null_reason": None}))
    (quote, start, end), = v.quotes
    assert quote == REAL_QUOTE == units_store.text(DOC_IRM)[start:end]


def test_an_ungrounded_field_is_null_ungrounded(one_field):
    v = one_field(reply(trigger_examples={"value": ["Where is my refund?", "Refund late"],
                                          "quotes": ["a quote the text never says"],
                                          "null_reason": None}), "trigger_examples")
    assert (v.value, v.quotes, v.null_reason) == (None, (), "ungrounded")
    assert (v.quotes_given, v.quotes_grounded) == (1, 0)
    for no_quote in ([], None):
        v = one_field(reply(when_to_use={"value": "Use when x", "quotes": no_quote,
                                         "null_reason": None}))
        assert (v.value, v.null_reason, v.quotes_given) == (None, "ungrounded", 0)


def test_not_for_without_a_quote_is_absent(one_field):                  # Phase 3 P22
    assert one_field(reply(not_for={"value": "Not for refunds", "quotes": []}),
                     "not_for").null_reason == "absent"
    v = one_field(reply(not_for={"value": "Not for refunds", "quotes": ["not in the text"]}),
                  "not_for")
    assert v.null_reason == "ungrounded"
    v = one_field(reply(not_for={"value": "Not for lost checks", "quotes": [REAL_QUOTE]}),
                  "not_for")
    assert v.value == "Not for lost checks" and v.null_reason is None


def test_silence_is_null_absent_and_a_model_reason_is_kept(one_field):
    v = one_field(reply(when_to_use={"value": None, "quotes": [], "null_reason": "absent"}))
    assert (v.value, v.null_reason) == (None, "absent")
    v = one_field(reply(when_to_use={"value": None, "quotes": [],
                                     "null_reason": "not_applicable"}))
    assert v.null_reason == "not_applicable"
    v = one_field(reply(trigger_examples={"value": [], "quotes": [], "null_reason": None}),
                  "trigger_examples")
    assert v.null_reason == "absent"


def test_over_long_when_to_use_is_unparseable(one_field):
    v = one_field(reply(when_to_use={"value": "x" * 1025, "quotes": [REAL_QUOTE],
                                     "null_reason": None}))
    assert (v.value, v.null_reason) == (None, "unparseable")
    assert one_field(reply(when_to_use={"value": "x" * 1024, "quotes": [REAL_QUOTE],
                                        "null_reason": None})).value == "x" * 1024


def test_values_of_the_wrong_type_or_over_their_limit_are_unparseable(one_field):
    four = ["a", "b", "c", "d"]
    assert one_field(reply(trigger_examples={"value": four, "quotes": [REAL_QUOTE]}),
                     "trigger_examples").null_reason == "unparseable"
    six = ["a", "b", "c", "d", "e", "f"]
    assert one_field(reply(problem_abstractions={"value": six, "quotes": [REAL_QUOTE]}),
                     "problem_abstractions").null_reason == "unparseable"
    five = one_field(reply(problem_abstractions={"value": six[:5], "quotes": [REAL_QUOTE]}),
                     "problem_abstractions")
    assert five.value == tuple(six[:5])
    assert one_field(reply(when_to_use={"value": ["a list"], "quotes": [REAL_QUOTE]})
                     ).null_reason == "unparseable"
    assert one_field(reply(when_to_use={"value": "x", "quotes": [3]})).null_reason == \
        "unparseable"
    assert one_field(reply(when_to_use="not an object")).null_reason == "unparseable"


def test_list_items_that_are_not_strings_or_are_blank_are_unparseable(one_field):     # M3
    for items in ([1, "Where is my refund?"], ["", "Where is my refund?"],
                  ["  ", "Where is my refund?"], [None, "x"], [["nested"], "x"]):
        assert one_field(reply(trigger_examples={"value": items, "quotes": [REAL_QUOTE]}),
                         "trigger_examples").null_reason == "unparseable", items
    assert one_field(reply(problem_abstractions={"value": ["missing refund", 7],
                                                 "quotes": [REAL_QUOTE]}),
                     "problem_abstractions").null_reason == "unparseable"


def test_fewer_than_two_trigger_examples_are_unparseable(one_field):                # M5a, §6.2
    for one in (["Where is my refund?"], "Where is my refund?"):
        assert one_field(reply(trigger_examples={"value": one, "quotes": [REAL_QUOTE]}),
                         "trigger_examples").null_reason == "unparseable"
    two = one_field(reply(trigger_examples={"value": ["Where is my refund?", "Refund late"],
                                            "quotes": [REAL_QUOTE]}), "trigger_examples")
    assert two.value == ("Where is my refund?", "Refund late") and two.status == "verified"
    one_abstraction = one_field(reply(problem_abstractions={"value": ["missing refund"],
                                                            "quotes": [REAL_QUOTE]}),
                                "problem_abstractions")
    assert one_abstraction.value == ("missing refund",)        # "up to five": one is enough


# -- value in quote (§6.3 check 4) -----------------------------------------------------------------

def test_a_number_missing_from_every_quote_is_auto_accepted(one_field):               # I1
    v = one_field(reply(when_to_use={"value": "Use when no refund has posted after 30 days",
                                     "quotes": [REAL_QUOTE, NUMBER_QUOTE]}))
    assert (v.value, v.status, v.null_reason) == (
        "Use when no refund has posted after 30 days", "auto-accepted", None)
    v = one_field(reply(trigger_examples={"value": ["Where is my refund?",
                                                    "No refund after 45 days"],
                                          "quotes": [NUMBER_QUOTE]}), "trigger_examples")
    assert v.status == "auto-accepted"                  # each list item is checked
    v = one_field(reply(when_to_use={"value": "Use when no TC 846 after 21 days",
                                     "quotes": [REAL_QUOTE,
                                                "no TC 846 after 21 days, never in the text"]}))
    assert v.status == "auto-accepted"                  # only grounded quotes count


def test_a_number_in_a_grounded_quote_is_verified(one_field):                        # I1
    v = one_field(reply(when_to_use={"value": "Use when no TC 846 has posted after 21 days",
                                     "quotes": [REAL_QUOTE, NUMBER_QUOTE]}))
    assert (v.status, v.null_reason) == ("verified", None)
    v = one_field(reply(when_to_use={"value": "Use when twenty-one days pass with no TC 846",
                                     "quotes": [NUMBER_QUOTE]}))
    assert v.status == "verified"                       # a number word reads as its number


def test_a_value_without_numbers_is_verified(one_field):                             # I1
    v = one_field(reply())
    assert (v.value, v.status) == ("Use when a refund is missing.", "verified")


DRAW = "The draw need not open from 7:30 a.m. to 9 a.m. and from noon to 1 p.m. daily."


@pytest.mark.parametrize(("value", "status"), [
    ("Closed 7:30 a.m. to 9 a.m.", "verified"),
    ("Closed from 12 p.m. to 1 p.m.", "verified"),        # 12 p.m. is the quote's noon
    ("Closed from noon", "verified"),
    ("Closed 7:30 a.m. to 10 a.m.", "auto-accepted"),
    ("Closed 7:30 p.m. to 9 p.m.", "auto-accepted"),
    ("Closed for 2 hours from 7:30 a.m.", "auto-accepted"),   # 2 is in no quote
])
def test_clock_times_must_be_in_a_grounded_quote(value, status):                    # I1
    section = "Header.\n" + DRAW
    v = check_field("when_to_use", {"value": value, "quotes": [DRAW]}, section, 100)
    assert v.status == status
    assert v.quotes == ((DRAW, 108, 108 + len(DRAW)),)


def test_an_auto_accepted_value_is_stored_and_counted_so(units_store, tmp_path):  # noqa: F811
    def far(system, user, repeat):
        out = json.loads(replies(system, user, repeat))
        out["when_to_use"]["value"] += " within 99 days"
        return json.dumps(out)

    client = stub(tmp_path, far)
    _, report = compile_procedures([units_store], client, CFG)
    w = report["stores"][str(units_store.path)]["fields"]["when_to_use"]
    assert (w["values"], w["verified"], w["auto-accepted"]) == (3, 0, 3)
    res = build_units(units_store.path, "bench", passes=("procedure",),
                      client=metered_client(0, client=client))
    m = load_units_manifest(units_store.path, res.units_id)
    proc = next(f for f in m.units if f.type == "procedure")
    path = units_store.path / UNITS_DIR / m.snapshot / proc.file
    unit, = map(json.loads, path.read_text().splitlines())
    assert unit["body"]["when_to_use"]["status"] == "auto-accepted"
    assert unit["body"]["not_for"]["status"] is None              # a null has no status
    report = unit_reports(units_store.path, res.units_id)["procedure"]
    assert report["grounding"]["when_to_use"] == {"auto-accepted": 1, "verified": 0}
    assert report["procedure_pass"]["fields"]["when_to_use"]["auto-accepted"] == 1


def test_unparseable_is_retried_once_at_repeat_1(units_store, tmp_path):  # noqa: F811
    unit = irm_unit(units_store)
    text = units_store.text(unit.doc_id)
    repeats = []

    def once_bad(system, user, repeat):
        repeats.append(repeat)
        return "not json at all" if repeat == 0 else reply()

    fields = compile_procedure(unit, text, stub(tmp_path, once_bad, "a"), CFG)
    assert repeats == [0, 1] and fields["when_to_use"].value == "Use when a refund is missing."
    repeats.clear()

    def missing_key(system, user, repeat):          # a reply without a field is unparseable
        repeats.append(repeat)
        return json.dumps({"when_to_use": json.loads(reply())["when_to_use"]})

    fields = compile_procedure(unit, text, stub(tmp_path, missing_key, "b"), CFG)
    assert repeats == [0, 1]
    assert {f: v.null_reason for f, v in fields.items()} == dict.fromkeys(FIELDS, "unparseable")
    assert all(v.quotes_given == 0 for v in fields.values())


def test_input_rejection_is_cached_as_model_error_other_failures_stop(units_store, tmp_path):  # noqa: F811,E501
    """Phase 3 P21: an input rejection is stored and gives null `model_error`, then and on
    every rerun, without a call; any other failure stops the run uncached, and a rerun
    resumes from the cache."""
    unit = irm_unit(units_store)

    def reject_irm(system, user, repeat):
        if REAL_QUOTE in user:
            raise llm.InputRejected("HTTP 400: prompt is too long")
        return replies(system, user, repeat)

    client = stub(tmp_path, reject_irm)
    done, report = compile_procedures([units_store], client, CFG)
    assert {f: v.null_reason for f, v in done[unit.unit_id].items()} == dict.fromkeys(
        FIELDS, "model_error")
    mine = report["stores"][str(units_store.path)]
    assert mine["calls"] == {"made": 2, "cached": 0, "failed": 1}
    assert mine["outcomes"] == {"main": {"model_error": 1, "reply": 2}}
    meter = metered_client(0, client=client)
    again, _ = compile_procedures([units_store], meter, CFG)
    assert again == done and meter.budget.calls == 0
    # M4: the lineage of the rejected unit names the failure entry the cache holds
    res = build_units(units_store.path, "gov", passes=("procedure",),
                      client=metered_client(0, client=client))
    m = load_units_manifest(units_store.path, res.units_id)
    proc = next(f for f in m.units if f.type == "procedure")
    path = units_store.path / UNITS_DIR / m.snapshot / proc.file
    lineage = {u["unit_id"]: u["lineage"] for u in map(json.loads, path.read_text().splitlines())}
    failed = client.cache.get(lineage[unit.unit_id]["cache_key_sha256"])
    assert failed is not None and "prompt is too long" in failed["error"]
    assert all(client.cache.get(x["cache_key_sha256"]) is not None for x in lineage.values())

    for error in (llm.ModelError("HTTP 401: authentication"),
                  llm.RateLimitedError("usage limit: resets at 5pm")):
        def fail(system, user, repeat, error=error):
            if REAL_QUOTE in user:
                raise error
            return replies(system, user, repeat)

        cache_dir = f"llm-{type(error).__name__}"
        failing = stub(tmp_path, fail, cache_dir)
        with pytest.raises((llm.ModelError, llm.RetriesExhausted)):
            compile_procedures([units_store], failing, CFG)
        resumed = stub(tmp_path, replies, cache_dir)
        done, _ = compile_procedures([units_store], resumed, CFG)
        assert done[unit.unit_id]["when_to_use"].value is not None   # nothing was cached
        assert resumed.calls >= 1

    meter = metered_client(0, client=stub(tmp_path, replies, "llm-empty"))
    with pytest.raises(BudgetExceeded):                     # a budget stop is never cached
        compile_procedures([units_store], meter, CFG)
    assert meter.budget.calls == 0


def test_a_spec_change_recompiles_only_its_group(units_store, tmp_path):  # noqa: F811   # T5
    client = stub(tmp_path, replies)
    two = PassConfig(prompt_version=PROMPT_VERSION,
                     groups={"A": ["when_to_use", "not_for"],
                             "B": ["trigger_examples", "problem_abstractions"]}, specs=SPECS)
    before, _ = compile_procedures([units_store], client, two)
    n = client.calls
    assert n == 2 * n_procedures(units_store)
    bumped = two.model_copy(update={"specs": {**SPECS,
                                              "trigger_examples": "procedure.trigger_examples@2"}})
    after, _ = compile_procedures([units_store], client, bumped)
    assert client.calls - n == n_procedures(units_store)
    assert pass_prompt("A", bumped) == pass_prompt("A", two)
    for uid in before:
        assert {f: after[uid][f] for f in two.groups["A"]} == \
            {f: before[uid][f] for f in two.groups["A"]}
        assert after[uid]["trigger_examples"] != before[uid]["trigger_examples"]
    # N8: built from the cache, the other units are byte-identical and only group B moved
    contracts = tmp_path / "contracts"
    shutil.copytree(UNIT_CONTRACT_DIR, contracts)

    def build(cfg: PassConfig):
        (contracts / "passes.json").write_text(json.dumps({"procedure": cfg.model_dump()}),
                                               encoding="utf-8")
        meter = metered_client(0, client=client)
        res = build_units(units_store.path, "gov", contracts_dir=contracts,
                          passes=("procedure",), client=meter)
        assert meter.budget.calls == 0
        return load_units_manifest(units_store.path, res.units_id)

    old, new = build(two), build(bumped)
    assert {f.type: f.sha256 for f in old.units if f.type != "procedure"} == \
        {f.type: f.sha256 for f in new.units if f.type != "procedure"}

    def bodies(m):
        f = next(f for f in m.units if f.type == "procedure")
        path = units_store.path / UNITS_DIR / m.snapshot / f.file
        return {u["unit_id"]: u["body"] for u in map(json.loads, path.read_text().splitlines())}

    a, b = bodies(old), bodies(new)
    assert a.keys() == b.keys() and a
    for uid in a:
        for f in ("when_to_use", "not_for", "steps", "tests"):
            assert json.dumps(a[uid][f]) == json.dumps(b[uid][f])
        assert a[uid]["trigger_examples"] != b[uid]["trigger_examples"]


# -- the build reads the replies from the cache ---------------------------------------------------

def test_build_with_passes_fills_model_fields_from_cache_only(units_store, tmp_path):  # noqa: F811
    client = stub(tmp_path, replies)
    compile_procedures([units_store], client, CFG)
    made = client.calls
    for corpus in ("gov", "bench"):
        meter = metered_client(0, client=client)
        res = build_units(units_store.path, corpus, passes=("procedure",), client=meter)
        assert meter.budget.calls == 0 and client.calls == made
        m = load_units_manifest(units_store.path, res.units_id)
        proc = next(f for f in m.units if f.type == "procedure")
        assert proc.rejected == 0 and proc.units >= 1
        assert m.passes == {"procedure": {
            "prompt_version": PROMPT_VERSION, "adapter": "stub", "model": "stub-sonnet",
            "max_tokens": MAX_TOKENS, "groups": CFG.groups, "specs": SPECS}}
        path = units_store.path / UNITS_DIR / m.snapshot / proc.file
        units = [json.loads(x) for x in path.read_text().splitlines()]
        for u in units:
            text = units_store.text(u["doc_id"])
            w = u["body"]["when_to_use"]
            assert w["status"] == "verified" and w["null_reason"] is None
            assert w["value"].startswith("Use when: ")
            for q in w["quotes"]:
                assert text[q["span"][0]:q["span"][1]] == q["text"]
            assert u["body"]["not_for"] == {"value": None, "quotes": [], "status": None,
                                            "null_reason": "absent"}
            assert len(u["body"]["trigger_examples"]["value"]) == 2
            assert u["lineage"]["prompt_version"] == PROMPT_VERSION
            assert client.cache.get(u["lineage"]["cache_key_sha256"]) is not None
            assert u["lineage"]["served_model"] is None       # the stub reports none
        report = unit_reports(units_store.path, res.units_id)["procedure"]
        assert report["procedure_pass"]["fields"]["when_to_use"]["quotes_grounded"] == len(units)
        assert report["grounding"]["when_to_use"] == {"auto-accepted": 0, "verified": len(units)}
    # a cold cache stops the build before anything is written
    empty = metered_client(0, client=stub(tmp_path, replies, "cold"))
    before = sorted((units_store.path / UNITS_DIR).rglob("*"))
    with pytest.raises(BudgetExceeded):
        build_units(units_store.path, "gov", passes=("procedure",), client=empty)
    assert sorted((units_store.path / UNITS_DIR).rglob("*")) == before


def test_the_procedure_pass_needs_procedure_units(units_store, tmp_path):  # noqa: F811
    meter = metered_client(0, client=stub(tmp_path, replies))
    with pytest.raises(ValueError, match="procedure"):
        build_units(units_store.path, "research", passes=("procedure",), client=meter)


# -- the command ---------------------------------------------------------------------------------

def adr(argv, capsys) -> tuple[int, str, str]:
    from adr_store import cli as adr_cli

    code = adr_cli.main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_compile_requires_max_calls(capsys, tmp_path):
    with pytest.raises(SystemExit) as e:
        adr(["units", "compile", "--procedures", "--store", tmp_path, "--generator",
             "claude_code_sonnet"], capsys)
    assert e.value.code == 2 and "--max-calls" in capsys.readouterr().err
    with pytest.raises(SystemExit):                     # and it names its pass
        adr(["units", "compile", "--store", tmp_path, "--generator", "claude_code_sonnet",
             "--max-calls", 0], capsys)


def test_adr_units_compile_stops_at_the_cap_then_compiles(tmp_path, capsys, monkeypatch):
    from adr_eval import runner

    made = []

    def make_client(name, profiles, cache, max_retries=5):
        made.append(name)
        return CachedStubClient(f"stub-{name}", Cache(tmp_path / "llm"), replies)

    monkeypatch.setattr(runner, "make_client", make_client)
    store = make_units_store(tmp_path / "s")
    report = store.path / UNITS_DIR / store.snapshot_id / "procedure-pass-report.json"
    base = ["units", "compile", "--procedures", "--store", store.path, "--generator",
            "claude_code_sonnet"]
    code, out, err = adr([*base, "--max-calls", 0], capsys)
    assert code == 1, err
    assert "3 procedure(s): 2 IRM, 1 bench" in out
    assert "stopped at --max-calls 0 (0 budget unit(s) used)" in out
    assert not report.exists() and made == ["claude_code_sonnet"]
    code, out, err = adr([*base, "--max-calls", 3, "--limit", 1], capsys)        # the canary
    assert code == 0, err
    assert "1 model call(s) made, 0 cached, 0 failed; 1 budget unit(s) of 3 used" in out
    code, out, err = adr([*base, "--max-calls", 2, "--concurrency", 2], capsys)
    assert code == 0, err
    assert "2 model call(s) made, 1 cached, 0 failed" in out
    data = json.loads(report.read_text())
    assert data["procedures"] == 3 and data["generator"] == "claude_code_sonnet"
    assert data["model"] == "stub-claude_code_sonnet" and data["budget_units"] == 2
    assert data["fields"]["when_to_use"]["quotes_grounded"] == 3
    assert data["served_model_mismatch"] is False and "warning" not in out     # M2
    # the build reads the same replies with no call (--max-calls 0 by default)
    code, out, err = adr(["units", "build", "--store", store.path, "--units-for", "gov",
                          "--with-passes", "procedure", "--generator", "claude_code_sonnet"],
                         capsys)
    assert code == 0, err
    m = load_units_manifest(store.path, out.splitlines()[0])
    assert "procedure" in m.passes


def _stub_profiles(monkeypatch, tmp_path, cls=CachedStubClient):
    from adr_eval import runner

    made = []

    def make_client(name, profiles, cache, max_retries=5):
        made.append(name)
        return cls(f"stub-{name}", Cache(tmp_path / "llm"), replies)

    monkeypatch.setattr(runner, "make_client", make_client)
    return made


def test_the_canary_limit_counts_across_stores_and_each_store_gets_a_report(
        tmp_path, capsys, monkeypatch):                                              # M1
    _stub_profiles(monkeypatch, tmp_path)
    first = make_units_store(tmp_path / "first")
    second = make_units_store(tmp_path / "second", docs=[UNITS_DOCS[3]])   # the IRM chapter
    reports = [s.path / UNITS_DIR / s.snapshot_id / "procedure-pass-report.json"
               for s in (first, second)]
    base = ["units", "compile", "--procedures", "--store", first.path, "--store", second.path,
            "--generator", "claude_code_sonnet", "--max-calls", 10]
    code, out, err = adr([*base, "--limit", 3], capsys)
    assert code == 0, err
    assert "3 model call(s) made, 0 cached, 0 failed; 3 budget unit(s)" in out
    a, b = (json.loads(r.read_text()) for r in reports)
    assert (a["available"], a["procedures"]) == (3, 3)
    assert (b["available"], b["procedures"]) == (2, 0)
    assert a["limit"] == b["limit"] == 3 and a["run_calls"] == b["run_calls"] == {
        "made": 3, "cached": 0, "failed": 0}
    code, out, err = adr([*base, "--limit", 4], capsys)
    assert code == 0, err
    b = json.loads(reports[1].read_text())
    assert (b["available"], b["procedures"]) == (2, 1)
    # the second store's IRM section is the first's (same document): its reply is cached
    assert "0 model call(s) made, 4 cached" in out


def test_a_served_model_other_than_the_profile_is_flagged_only(tmp_path, capsys,
                                                               monkeypatch):         # M2
    _stub_profiles(monkeypatch, tmp_path, ServedStub)
    store = make_units_store(tmp_path / "s")
    code, out, err = adr(["units", "compile", "--procedures", "--store", store.path,
                          "--generator", "claude_code_sonnet", "--max-calls", 3], capsys)
    assert code == 0, err                              # flag only: the run completes
    assert "served served-sonnet; warning: a served model differs from the profile's model" \
        in out
    data = json.loads((store.path / UNITS_DIR / store.snapshot_id /
                       "procedure-pass-report.json").read_text())
    assert data["served_model_mismatch"] is True and data["served_models"] == ["served-sonnet"]


def test_the_procedure_pass_on_research_is_a_usage_error(tmp_path, capsys, monkeypatch):  # M5b
    made = _stub_profiles(monkeypatch, tmp_path)
    store = make_units_store(tmp_path / "s")
    code, out, err = adr(["units", "build", "--store", store.path, "--units-for", "research",
                          "--with-passes", "procedure"], capsys)
    assert code == 2 and "unexpected" not in err
    assert err.startswith("error: --with-passes procedure:") and "'research'" in err
    assert made == []                                   # refused before a profile is resolved
