"""The 3B extractor (Phase 3 spec §5.5, §7.1–7.5) on the fixture 33 CFR 117, with a cached stub
model: units, the checks, failure caching, spec changes, rows, the second pass, draw matching
and agreement. No model is called."""

import json

import pytest

from adr_eval.cache import Cache
from adr_eval.llm import CachedFailure, CachedStubClient, ModelError, ModelOutputError
from adr_eval.pipeline import Budget, BudgetExceeded, MeteredClient
from adr_store.tables import extract as ex
from adr_store.tables.build import build_tables
from adr_store.tables.contracts import CONTRACT_DIR, load_contracts, validate_row
from adr_store.tables.ecfr import chain_docs
from adr_store.tables.extract import (
    DRAW_COLUMNS,
    MAX_TOKENS,
    NUMERIC,
    PROMPT_VERSION,
    SECOND_PASS_VERSION,
    SECTION_COLUMNS,
    ExtractionConfig,
    Facts,
    Value,
    agreement,
    bridge_key,
    check_value,
    coerce,
    drawbridge_rows,
    extract_all,
    extract_unit,
    load_config,
    load_facts,
    match_draws,
    number_in_quote,
    parse_numbered,
    prompt,
    regex_value,
    second_pass_all,
    second_pass_prompt,
    units,
    write_facts,
)
from adr_store.tables.overlay import TablesError, load_manifest, load_rows
from adr_store.tables.provenance import reslice
from tests.store.tables_fixtures import (
    ECFR_NEW,
    ECFR_OLD,
    ECFR_SECTIONS,
    ecfr_store_at,
    fixture_numbered,
    fixture_reply,
)

N_SECTIONS = ECFR_SECTIONS
CFG = load_config()
SPECS = CFG.specs
CONTRACTS = load_contracts(corpus="gov")
SPLIT = ExtractionConfig(groups={"A": ["waterway", "bridge", "mile", "seasonal",
                                       "owner_or_agency", "vhf_channel"],
                                 "B": ["notice_hours", "opens_on_signal", "closed_periods"]},
                         specs=SPECS)     # B has draw columns but no bridge
TEXT = ("§ 117.821 Cape Fear River.\nThe draw of the Cape Fear Memorial Bridge, mile 26.8, at "
        "Wilmington: the draw shall open on signal if at least four hours notice is given.")


@pytest.fixture
def ecfr_store(tmp_path):
    return ecfr_store_at(tmp_path / "ecfr")


def stub_of(tmp_path, fn=fixture_reply, name="llm", model="stub-sonnet", **kw):
    return CachedStubClient(model, Cache(tmp_path / name), fn, **kw)


def unit_of(store, section: str, version: str = ECFR_NEW) -> ex.Unit:
    return next(u for u in units(store) if any(
        o.section == section and o.version == version for o in u.occurrences))


def reply_with_quote(quote: str):
    """A reply whose waterway quote is `quote`, the rest from the fixture."""
    def fn(system, user, repeat):
        reply = json.loads(fixture_reply(system, user, repeat))
        reply["section"]["waterway"] = {"value": "Cape Fear River", "quote": quote,
                                        "null_reason": None}
        return json.dumps(reply)
    return fn


# -- units and calls -------------------------------------------------------------------------------

def test_units_are_one_per_distinct_section_text(ecfr_store):
    us = units(ecfr_store)
    assert len(us) == N_SECTIONS + 1 and sum(len(u.occurrences) for u in us) == 2 * N_SECTIONS
    assert [u.text_sha256 for u in us] == sorted(u.text_sha256 for u in us)
    assert all(o.text == u.text for u in us for o in u.occurrences)
    changed = [u for u in us if u.occurrences[0].section == "117.821"]
    assert sorted(u.occurrences[0].version for u in changed) == [ECFR_OLD, ECFR_NEW]
    same = unit_of(ecfr_store, "117.823")
    assert [o.version for o in same.occurrences] == [ECFR_OLD, ECFR_NEW]


def test_one_call_per_unit_and_a_rebuild_makes_none(ecfr_store, tmp_path):
    stub = stub_of(tmp_path)
    first, report = extract_all(ecfr_store, stub, CFG, CONTRACTS)
    assert stub.calls == len(units(ecfr_store))
    assert report["calls"] == {"made": len(first), "cached": 0, "failed": 0}
    meter = MeteredClient(stub, Budget(None, 0), {})
    again, report = extract_all(ecfr_store, meter, CFG, CONTRACTS)
    assert meter.budget.calls == 0 and again == first
    assert report["calls"] == {"made": 0, "cached": len(first), "failed": 0}


def test_each_call_sends_the_group_prompt_and_the_section_text(ecfr_store, tmp_path):
    seen = []

    def fn(system, user, repeat):
        seen.append((system, user, repeat))
        return fixture_reply(system, user, repeat)

    u = unit_of(ecfr_store, "117.263")
    extract_unit(u, stub_of(tmp_path, fn), CFG, CONTRACTS)
    assert seen == [(prompt("main", CFG, CONTRACTS), u.text, 0)]
    system = seen[0][0]
    assert PROMPT_VERSION in system and all(SPECS[c] in system for c in SPECS)
    assert MAX_TOKENS == 4000


def test_extraction_values_carry_quotes_offsets_and_statuses(ecfr_store, tmp_path):
    u = unit_of(ecfr_store, "117.263")
    got = extract_unit(u, stub_of(tmp_path), CFG, CONTRACTS)
    vhf = got.section["vhf_channel"]
    assert (vhf.value, vhf.status, vhf.regex_agrees, vhf.checks_failed) == (9, "verified", True, ())
    assert u.text[vhf.start:vhf.end] == vhf.quote == "VHF-FM channel 9"
    assert got.section["seasonal"] == Value(None, None, None, None, None, "absent", (), None)
    [draw] = got.draws
    assert draw["mile"].value == 1088.5 and draw["mile"].regex_agrees is True
    assert draw["opens_on_signal"].value is True and draw["notice_hours"].null_reason == "absent"
    assert got.calls == {"main": "reply"}


# -- checks ----------------------------------------------------------------------------------------

def one_value(fn, tmp_path, section="117.821") -> Value:
    store = ecfr_store_at(tmp_path / "one")
    got = extract_unit(unit_of(store, section), stub_of(tmp_path, fn), CFG, CONTRACTS)
    return got.section["waterway"]


def test_an_unlocatable_quote_is_ungrounded(tmp_path):
    v = one_value(reply_with_quote("not in the text"), tmp_path)
    assert (v.value, v.null_reason, v.status) == (None, "ungrounded", "rejected")
    assert (v.quote, v.start, v.end) == (None, None, None)


def test_a_quote_is_located_after_whitespace_normalisation(tmp_path):
    v = one_value(reply_with_quote("Cape   Fear\nRiver"), tmp_path)
    assert (v.value, v.status, v.quote) == ("Cape Fear River", "verified", "Cape Fear River")


def test_number_words_pass_value_in_quote():
    assert number_in_quote(4, "at least four hours notice")
    assert number_in_quote(24, "twenty-four hours")
    assert number_in_quote(26.8, "mile 26.8") and number_in_quote(100, "one hundred feet")
    assert number_in_quote(12, "12 hours notice") and number_in_quote(30, "Thirty minutes")
    assert not number_in_quote(4, "fourteen hours") and not number_in_quote(4, "24 hours")
    assert not number_in_quote(4, "twenty-four hours") and not number_in_quote(3, "mile 3.1")
    v = check_value("notice_hours", "int",
                    {"value": 4, "quote": "the draw shall open on signal"}, TEXT)
    assert v.status == "auto-accepted" and v.checks_failed == ("value_in_quote",)
    assert v.value == 4 and TEXT[v.start:v.end] == v.quote == "the draw shall open on signal"
    ok = check_value("notice_hours", "int", {"value": 4, "quote": "four hours notice"}, TEXT)
    assert (ok.status, ok.checks_failed) == ("verified", ())


def test_coerce_checks_the_column_type():
    assert coerce("int", 4) == 4 and coerce("int", "12") == 12 and coerce("int", 4.0) == 4
    assert coerce("real", 3) == 3.0 and isinstance(coerce("real", 3), float)
    assert coerce("real", "26.8") == 26.8
    assert coerce("bool", True) is True and coerce("bool", "yes") is True
    assert coerce("bool", "NO") is False
    assert coerce("text", "Neuse River") == "Neuse River"
    assert coerce("text[]", ["a", "b"]) == ["a", "b"] and coerce("text[]", "a") == ["a"]
    for ctype, raw in [("int", True), ("int", 4.5), ("int", "four"), ("real", "x"),
                       ("bool", 1), ("bool", "maybe"), ("text", 5), ("text", "  "),
                       ("text[]", [1]), ("text[]", ["a", ""]), ("real", float("nan"))]:
        with pytest.raises(ValueError):
            coerce(ctype, raw)
    v = check_value("vhf_channel", "int", {"value": "nine", "quote": "channel 9"}, TEXT)
    assert (v.value, v.null_reason, v.status, v.checks_failed) == (
        None, "unparseable", "rejected", ("type",))


def test_a_null_value_keeps_the_models_reason():
    absent = check_value("mile", "real", {"value": None, "quote": None, "null_reason": "absent"},
                         TEXT)
    na = check_value("mile", "real", {"value": None, "null_reason": "not_applicable"}, TEXT)
    odd = check_value("mile", "real", {"value": None, "null_reason": "model_error"}, TEXT)
    empty = check_value("closed_periods", "text[]", {"value": [], "quote": None}, TEXT)
    assert [x.null_reason for x in (absent, na, odd, empty)] == [
        "absent", "not_applicable", "absent", "absent"]
    assert all(x.status is None and x.value is None for x in (absent, na, odd, empty))


def test_an_unparseable_reply_is_retried_once_at_repeat_1(ecfr_store, tmp_path):
    def flaky(system, user, repeat):
        return "Sorry, here it is:" if repeat == 0 else fixture_reply(system, user, repeat)

    stub = stub_of(tmp_path, flaky, "a")
    got = extract_unit(unit_of(ecfr_store, "117.263"), stub, CFG, CONTRACTS)
    assert stub.calls == 2 and got.section["vhf_channel"].value == 9
    assert got.calls == {"main": "reply_repeat_1"}

    stub = stub_of(tmp_path, lambda s, u, r: '{"section": {', "b")
    got = extract_unit(unit_of(ecfr_store, "117.263"), stub, CFG, CONTRACTS)
    assert stub.calls == 2 and got.calls == {"main": "unparseable"}
    assert got.draws == []
    assert {c: (v.value, v.null_reason, v.status) for c, v in got.section.items()} == {
        c: (None, "unparseable", "rejected") for c in SECTION_COLUMNS}


def test_a_reply_without_its_section_and_draws_is_unparseable(ecfr_store, tmp_path):
    stub = stub_of(tmp_path, lambda s, u, r: '{"section": {}, "draws": {}}')
    got = extract_unit(unit_of(ecfr_store, "117.263"), stub, CFG, CONTRACTS)
    assert got.calls == {"main": "unparseable"} and stub.calls == 2


def test_a_failed_call_is_cached_as_model_error(ecfr_store, tmp_path):
    def down(system, user, repeat):
        raise ModelError("HTTP 400: refused")

    stub = stub_of(tmp_path, down)
    first, report = extract_all(ecfr_store, stub, CFG, CONTRACTS)
    n = stub.calls
    assert n == len(units(ecfr_store)) and report["calls"]["failed"] == n
    for got in first:
        assert got.calls == {"main": "model_error"} and got.draws == []
        assert {v.null_reason for v in got.section.values()} == {"model_error"}
        assert {v.status for v in got.section.values()} == {"rejected"}
    assert report["columns"]["vhf_channel"]["model_error"] == n
    # a second run raises CachedFailure inside, with no call
    u = units(ecfr_store)[0]
    with pytest.raises(CachedFailure):
        stub.complete(prompt("main", CFG, CONTRACTS), u.text, max_tokens=MAX_TOKENS,
                      cache_failures=True)
    meter = MeteredClient(stub, Budget(None, 0, count_attempts=True), {})
    again, _ = extract_all(ecfr_store, meter, CFG, CONTRACTS)
    assert again == first and stub.calls == n and meter.budget.calls == 0


def test_a_budget_stop_is_no_model_error_and_is_not_cached(ecfr_store, tmp_path):
    stub = stub_of(tmp_path)
    meter = MeteredClient(stub, Budget(None, 3, count_attempts=True), {})
    with pytest.raises(BudgetExceeded):
        extract_all(ecfr_store, meter, CFG, CONTRACTS)
    assert stub.calls == 3
    full, _ = extract_all(ecfr_store, stub, CFG, CONTRACTS)
    assert all(g.calls == {"main": "reply"} for g in full)
    assert stub.calls == len(units(ecfr_store))


def test_regex_cross_check_records_agreement():
    assert regex_value("mile", "the draw, mile 12.5, shall open") == (12.5,)
    assert regex_value("mile", "no number here") is None
    assert regex_value("notice_hours", "if at least 12 hours notice is given") == (12,)
    assert regex_value("notice_hours", "if at least 12 hours advance notice") == (12,)
    assert regex_value("vhf_channel", "monitors VHF-FM channel 13") == (13,)
    assert regex_value("bridge", "the draw of the X bridge") is None     # no regex for text
    assert regex_value("mile", "mile 2.0 and mile 3.1 and Mile 2") == (2.0, 3.1)
    text = "The draw, mile 12.5, shall open."
    agree = check_value("mile", "real", {"value": 12.5, "quote": "mile 12.5"}, text)
    other = check_value("mile", "real", {"value": 13, "quote": "The draw"}, text)
    assert (agree.regex_agrees, other.regex_agrees) == (True, False)
    none = check_value("notice_hours", "int", {"value": 4, "quote": "four hours notice"},
                       "after four hours notice")
    assert none.regex_agrees is None and none.status == "verified"


def test_the_report_counts_per_column(ecfr_store, tmp_path):
    def mixed(system, user, repeat):
        reply = json.loads(fixture_reply(system, user, repeat))
        if "§ 117.263" in user:
            reply["section"]["owner_or_agency"]["quote"] = "a quote that is not there"
            reply["draws"][0]["mile"] = {"value": 1088.5, "quote": "shall open on signal"}
        return json.dumps(reply)

    _, report = extract_all(ecfr_store, stub_of(tmp_path, mixed), CFG, CONTRACTS)
    assert (report["units"], report["sections"], report["newest_version_sections"]) == (
        N_SECTIONS + 1, 2 * N_SECTIONS, N_SECTIONS)
    owner = report["columns"]["owner_or_agency"]
    assert (owner["non_null"], owner["grounded"], owner["ungrounded"]) == (1, 0, 1)
    mile = report["columns"]["mile"]
    assert mile["non_null"] == mile["grounded"] == 8 and mile["value_in_quote_failed"] == 1
    assert mile["regex"] == {"agree": 8, "disagree": 0, "none": 0}
    notice = report["columns"]["notice_hours"]
    assert notice["non_null"] == 3 and notice["regex"] == {"agree": 1, "disagree": 0, "none": 2}
    assert report["draws"] == 8 and report["draws_dropped"] == 0
    assert set(report["columns"]) == set(SECTION_COLUMNS + DRAW_COLUMNS)
    assert report["prompt_version"] == PROMPT_VERSION and report["max_tokens"] == MAX_TOKENS


# -- spec changes ----------------------------------------------------------------------------------

def test_a_spec_change_reextracts_only_its_group(ecfr_store, tmp_path):        # T5
    stub = stub_of(tmp_path)
    two = ExtractionConfig(groups={"A": ["waterway", *DRAW_COLUMNS],
                                   "B": ["seasonal", "owner_or_agency", "vhf_channel"]},
                           specs=SPECS)
    before, _ = extract_all(ecfr_store, stub, two, CONTRACTS)
    n = stub.calls
    assert n == 2 * len(units(ecfr_store))
    bumped = two.model_copy(update={"specs": {**SPECS, "vhf_channel": "bridge.vhf_channel@2"}})
    after, _ = extract_all(ecfr_store, stub, bumped, CONTRACTS)
    assert stub.calls - n == len(units(ecfr_store))                      # group B only
    assert prompt("A", bumped, CONTRACTS) == prompt("A", two, CONTRACTS)  # A's keys unchanged
    assert prompt("B", bumped, CONTRACTS) != prompt("B", two, CONTRACTS)
    assert [u.draws for u in after] == [u.draws for u in before]
    assert [u.section for u in after] == [u.section for u in before]


def test_a_group_without_bridge_is_matched_to_the_draws_of_the_bridge_group(ecfr_store,
                                                                             tmp_path):
    split = SPLIT
    one, _ = extract_all(ecfr_store, stub_of(tmp_path, name="a"), CFG, CONTRACTS)
    two, report = extract_all(ecfr_store, stub_of(tmp_path, name="b"), split, CONTRACTS)
    assert [u.draws for u in two] == [u.draws for u in one]
    assert report["draws_dropped"] == 0
    specs_b = prompt("B", split, CONTRACTS).split("Specs: ")[1].splitlines()[0]
    assert specs_b == "bridge.notice_hours@1, bridge.opens_on_signal@1, bridge.closed_periods@1"
    assert "- bridge (text):" in prompt("B", split, CONTRACTS)       # asked, to match draws


def test_a_failed_group_nulls_only_its_columns(ecfr_store, tmp_path):
    def b_down(system, user, repeat):
        if "Specs: bridge.notice_hours" in system:
            raise ModelError("down")
        return fixture_reply(system, user, repeat)

    got = extract_unit(unit_of(ecfr_store, "117.823"), stub_of(tmp_path, b_down), SPLIT,
                       CONTRACTS)
    assert got.calls == {"A": "reply", "B": "model_error"}
    assert [d["bridge"].value for d in got.draws] == [
        "US 17 Bridge", "Norfolk Southern Railroad Bridge", "NC 55 Bridge"]
    assert {d[c].null_reason for d in got.draws for c in SPLIT.groups["B"]} == {"model_error"}
    assert got.section["waterway"].value == "Neuse River"


def test_unmatched_draws_of_another_group_are_dropped_and_counted(ecfr_store, tmp_path):
    def extra(system, user, repeat):
        reply = json.loads(fixture_reply(system, user, repeat))
        if "Specs: bridge.notice_hours" in system and reply["draws"]:
            phantom = {c: {"value": None, "quote": None, "null_reason": "absent"}
                       for c in reply["draws"][0]}
            phantom["bridge"] = {"value": "Phantom Bridge", "quote": None, "null_reason": None}
            reply["draws"] = [phantom, *reply["draws"][1:]]     # the first draw is not named
        return json.dumps(reply)

    got, report = extract_all(ecfr_store, stub_of(tmp_path, extra), SPLIT, CONTRACTS)
    with_draws = [g for g in got if g.draws]
    assert report["draws_dropped"] == len(with_draws) == 6
    for g in with_draws:          # the bridge group's first draw got nothing from group B
        assert {g.draws[0][c] for c in SPLIT.groups["B"]} == {ex.ABSENT}


def test_the_config_names_every_model_column_once(tmp_path):
    assert CFG.groups == {"main": [*SECTION_COLUMNS, *DRAW_COLUMNS]}
    assert len(CFG.groups["main"]) == 9
    with pytest.raises(ValueError):
        ExtractionConfig(groups={"A": list(SECTION_COLUMNS)}, specs=SPECS)
    with pytest.raises(ValueError):
        ExtractionConfig(groups={"A": [*SECTION_COLUMNS, *DRAW_COLUMNS, "mile"]}, specs=SPECS)
    with pytest.raises(ValueError):
        ExtractionConfig(groups=CFG.groups, specs={**SPECS, "mile": "fr.mile@1"})


def test_contract_spec_ids_match_the_extraction_config():                     # N8
    cfg = json.loads((CONTRACT_DIR / "extraction.json").read_text(encoding="utf-8"))
    assert cfg["specs"] == SPECS
    seen = set()
    for table in ("drawbridge_sections", "drawbridge_bridges"):
        for col in CONTRACTS[table].columns:
            if col.name in SPECS:
                assert col.spec_id == SPECS[col.name], (table, col.name)
                seen.add(col.name)
            else:
                assert col.spec_id == f"structure.{col.name}@1", (table, col.name)
    assert seen == set(SPECS) == set(SECTION_COLUMNS + DRAW_COLUMNS)
    assert set(NUMERIC) <= seen


def test_the_drawbridge_contracts_have_the_spec_columns():
    s, b = CONTRACTS["drawbridge_sections"], CONTRACTS["drawbridge_bridges"]
    assert [(c.name, c.type, c.nullable) for c in s.columns] == [
        ("section", "text", False), ("version", "text", False), ("heading", "text", False),
        ("state", "text", True), ("waterway_key", "text", False), ("waterway", "text", True),
        ("seasonal", "bool", True), ("owner_or_agency", "text", True),
        ("vhf_channel", "int", True)]
    assert [(c.name, c.type, c.nullable) for c in b.columns] == [
        ("section", "text", False), ("version", "text", False), ("draw", "int", False),
        ("state", "text", True), ("waterway", "text", True), ("waterway_key", "text", False),
        ("bridge", "text", True), ("mile", "real", True), ("notice_hours", "int", True),
        ("opens_on_signal", "bool", True), ("closed_periods", "text[]", False)]
    assert (s.key, b.key) == (["section", "version"], ["section", "version", "draw"])
    assert s.source.loader == b.source.loader == "extraction"
    closed = next(c for c in b.columns if c.name == "closed_periods")
    assert "absent" in closed.description and "[]" in closed.description      # N14


# -- rows ------------------------------------------------------------------------------------------

@pytest.fixture
def rows(ecfr_store, tmp_path):
    results, _ = extract_all(ecfr_store, stub_of(tmp_path), CFG, CONTRACTS)
    return drawbridge_rows(results, units(ecfr_store))


def test_rows_validate_against_the_contracts(rows):
    assert len(rows["drawbridge_sections"]) == 2 * N_SECTIONS
    assert len(rows["drawbridge_bridges"]) == 14     # draws x occurrences
    for table, recs in rows.items():
        assert all(validate_row(CONTRACTS[table], r) == [] for r in recs), table


def test_rows_repeat_per_version_with_shifted_offsets(ecfr_store, rows):
    old, new = chain_docs(ecfr_store)
    by = {(r.row["section"], r.row["version"]): r for r in rows["drawbridge_sections"]}
    a, b = by[("117.823", ECFR_OLD)], by[("117.823", ECFR_NEW)]
    assert (a.doc_id, b.doc_id) == (old, new)
    pa, pb = a.prov["waterway"], b.prov["waterway"]
    assert pa.quote == pb.quote == "Neuse River" and pb.start - pa.start == 1   # "four"/"two"
    assert ecfr_store.text(old)[pa.start:pa.end] == ecfr_store.text(new)[pb.start:pb.end] \
        == "Neuse River"
    assert by[("117.821", ECFR_OLD)].row["heading"] == "§ 117.821 Cape Fear River."
    draws = [r for r in rows["drawbridge_bridges"] if r.row["section"] == "117.823"]
    assert sorted((r.row["version"], r.row["draw"], r.row["bridge"]) for r in draws) == [
        (v, d, b) for v in (ECFR_OLD, ECFR_NEW) for d, b in
        ((1, "US 17 Bridge"), (2, "Norfolk Southern Railroad Bridge"), (3, "NC 55 Bridge"))]
    # every span slices its version's document text to the quote and re-slices (T3)
    n = 0
    for recs in rows.values():
        for r in recs:
            text = ecfr_store.text(r.doc_id)
            for col, prov in r.prov.items():
                for p in prov if isinstance(prov, list) else [prov]:
                    if p.span is not None and r.row[col] is not None:
                        if p.quote is not None:
                            assert text[p.start:p.end] == p.quote
                        value = r.row[col]
                        assert reslice(text, p, value[0] if isinstance(value, list) else value), \
                            (col, p)
                        n += 1
    assert n > 100


def test_draw_rows_repeat_the_section_place_with_its_provenance(rows):
    sec = {(r.row["section"], r.row["version"]): r for r in rows["drawbridge_sections"]}
    for d in rows["drawbridge_bridges"]:
        s = sec[(d.row["section"], d.row["version"])]
        for col in ("state", "waterway", "waterway_key"):
            assert d.row[col] == s.row[col] and d.prov[col] == s.prov[col]
    nc = [d for d in rows["drawbridge_bridges"] if d.row["section"] == "117.823"]
    assert {d.row["state"] for d in nc} == {"North Carolina"}
    assert {d.row["waterway_key"] for d in nc} == {"neuse river"}


def test_structure_values_carry_structure_provenance(rows):
    r = next(r for r in rows["drawbridge_sections"] if r.row["section"] == "117.1")
    assert r.row["state"] is None and r.prov["state"].null_reason == "absent"
    assert r.prov["heading"].spec_id == "structure.heading@1"
    assert r.prov["version"].span is None and r.prov["version"].status == "verified"
    d = next(r for r in rows["drawbridge_bridges"] if r.row["section"] == "117.823")
    assert d.prov["draw"].spec_id == "structure.draw@1" and d.prov["draw"].span is None


def test_closed_periods_is_an_empty_list_when_absent(rows):
    draws = {(r.row["section"], r.row["draw"]): r for r in rows["drawbridge_bridges"]
             if r.row["version"] == ECFR_NEW}
    closed = draws[("117.823", 2)]
    assert closed.row["closed_periods"] == ["7 a.m. to 9 a.m."]
    assert len(closed.prov["closed_periods"]) == 1
    assert closed.prov["closed_periods"][0].quote == "need not open from 7 a.m. to 9 a.m."
    open_ = draws[("117.823", 1)]
    assert open_.row["closed_periods"] == [] and open_.prov["closed_periods"] == []


def test_a_rejected_value_is_null_with_its_reason_in_the_row(ecfr_store, tmp_path):
    results, _ = extract_all(ecfr_store, stub_of(tmp_path, reply_with_quote("nowhere")), CFG,
                             CONTRACTS)
    out = drawbridge_rows(results, units(ecfr_store))
    for r in out["drawbridge_sections"]:
        assert r.row["waterway"] is None
        p = r.prov["waterway"]
        assert (p.null_reason, p.status, p.checks_failed) == ("ungrounded", "rejected", ["span"])
        assert validate_row(CONTRACTS["drawbridge_sections"], r) == []


def test_extraction_rows_validate_and_build_lists_the_drawbridge_tables(ecfr_store, tmp_path):
    stub = stub_of(tmp_path)
    res = build_tables(ecfr_store.path, "gov", with_extraction=True, client=stub,
                       max_calls=len(units(ecfr_store)))
    assert stub.calls == len(units(ecfr_store))
    m = load_manifest(ecfr_store.path, res.tables_id)
    tables = {t.table: t for t in m.tables}
    assert {"drawbridge_sections", "drawbridge_bridges", "fr_documents", "waterways"} <= set(tables)
    assert (tables["drawbridge_sections"].rows, tables["drawbridge_bridges"].rows) == (14, 14)
    assert tables["drawbridge_sections"].rejected == tables["drawbridge_bridges"].rejected == 0
    assert m.extraction == {"prompt_version": PROMPT_VERSION, "adapter": "stub",
                            "model": "stub-sonnet", "max_tokens": MAX_TOKENS,
                            "groups": CFG.groups, "specs": SPECS}
    assert len(load_rows(ecfr_store.path, m, "drawbridge_bridges")) == 14
    # a zero-call rebuild reproduces the build byte for byte (Constraint 4)
    again = build_tables(ecfr_store.path, "gov", with_extraction=True, client=stub, max_calls=0)
    assert again.tables_id == res.tables_id and stub.calls == len(units(ecfr_store))
    # the 3A build is unchanged by the extraction contracts
    plain = build_tables(ecfr_store.path, "gov")
    assert "drawbridge_sections" not in {t.table for t in load_manifest(
        ecfr_store.path, plain.tables_id).tables}


def test_an_extraction_build_stops_at_its_call_cap(ecfr_store, tmp_path):
    stub = stub_of(tmp_path)
    with pytest.raises(BudgetExceeded):
        build_tables(ecfr_store.path, "gov", with_extraction=True, client=stub, max_calls=0)
    assert stub.calls == 0


def test_an_extraction_build_of_a_store_without_ecfr_has_empty_drawbridge_tables(tmp_path):
    from tests.store.tables_fixtures import make_tables_store

    store = make_tables_store(tmp_path / "s")
    stub = stub_of(tmp_path)
    res = build_tables(store.path, "gov", with_extraction=True, client=stub)
    tables = {t.table: t.rows for t in load_manifest(store.path, res.tables_id).tables}
    assert tables["drawbridge_sections"] == tables["drawbridge_bridges"] == 0
    assert stub.calls == 0


# -- the second pass -------------------------------------------------------------------------------

NUMBERED = """1. WATERWAY: Neuse River | "Neuse River"
2. SEASONAL: NO | ""
3. OWNER: NONE
4. VHF CHANNEL: NONE | ""
5. DRAWS: 2
5.1.a BRIDGE: US 17 Bridge | "US 17 Bridge"
5.1.b MILE: 2.0 | "mile 2.0"
5.1.c NOTICE HOURS: NONE
5.1.d OPENS ON SIGNAL: YES | "shall open on signal"
5.1.e CLOSED PERIODS: NONE
5.2.a BRIDGE: Norfolk Southern Railroad Bridge | "Norfolk Southern Railroad Bridge"
5.2.b MILE: 3.1 | "mile 3.1"
5.2.c NOTICE HOURS: 12 | "12 hours notice"
5.2.d OPENS ON SIGNAL: NO | "need not open"
5.2.e CLOSED PERIODS: 7 a.m. to 9 a.m.; 4 p.m. to 6 p.m. | "need not open from 7 a.m. to 9 a.m."
"""


def test_parse_numbered_reads_draws_and_quotes():
    got = parse_numbered("Here are the answers.\n\n" + NUMBERED)
    s = got["section"]
    assert s["waterway"] == {"value": "Neuse River", "quote": "Neuse River", "null_reason": None}
    assert s["seasonal"]["value"] is False
    assert s["owner_or_agency"] == {"value": None, "quote": None, "null_reason": "absent"}
    assert s["vhf_channel"]["value"] is None
    assert len(got["draws"]) == 2
    d1, d2 = got["draws"]
    assert d1["bridge"]["value"] == "US 17 Bridge" and d1["mile"]["value"] == "2.0"
    assert d1["opens_on_signal"]["value"] is True and d1["closed_periods"]["value"] is None
    assert d2["notice_hours"] == {"value": "12", "quote": "12 hours notice", "null_reason": None}
    assert d2["closed_periods"]["value"] == ["7 a.m. to 9 a.m.", "4 p.m. to 6 p.m."]
    assert d2["closed_periods"]["quote"] == "need not open from 7 a.m. to 9 a.m."
    assert set(d1) == set(DRAW_COLUMNS) and set(s) == set(SECTION_COLUMNS)
    assert parse_numbered(NUMBERED.split("5.1.a")[0].replace("DRAWS: 2", "DRAWS: 0"))[
        "draws"] == []


@pytest.mark.parametrize("broken", [
    NUMBERED.replace("2. SEASONAL", "3. SEASONAL"),                  # a number out of order
    NUMBERED.replace("3. OWNER: NONE\n", ""),                         # a question left out
    NUMBERED.replace("DRAWS: 2", "DRAWS: 3"),                         # fewer draws than said
    NUMBERED.replace("DRAWS: 2", "DRAWS: 1"),                         # more draws than said
    NUMBERED.replace("5.2.c NOTICE HOURS", "5.2.d NOTICE HOURS"),     # a letter out of order
    NUMBERED.replace("5.1.b MILE", "5.1.b BRIDGE"),                   # the wrong label
    NUMBERED.replace("DRAWS: 2", "DRAWS: two"),                       # no draw count
    NUMBERED + "5.3.a BRIDGE: X | \"X\"\n",                           # a draw beyond the count
    "",
])
def test_parse_numbered_refuses_broken_numbering(broken):
    with pytest.raises(ModelOutputError):
        parse_numbered(broken)


def test_second_pass_extracts_facts_through_the_same_checks(ecfr_store, tmp_path):
    seen = []

    def fn(system, user, repeat):
        seen.append(system)
        return fixture_numbered(system, user, repeat)

    stub = stub_of(tmp_path, fn, model="stub-opus")
    facts, report = second_pass_all(ecfr_store, stub, CONTRACTS)
    assert stub.calls == len(units(ecfr_store)) and set(seen) == {second_pass_prompt(CONTRACTS)}
    assert SECOND_PASS_VERSION in seen[0]
    assert [f.unit for f in facts] == [u.text_sha256 for u in units(ecfr_store)]
    first, _ = extract_all(ecfr_store, stub_of(tmp_path, name="first"), CFG, CONTRACTS)
    assert [(f.section, f.draws) for f in facts] == [(u.section, u.draws) for u in first]
    assert report["calls"]["made"] == len(facts)
    rows = drawbridge_rows(facts, units(ecfr_store))
    assert len(rows["drawbridge_bridges"]) == 14


def test_second_pass_unparseable_and_failed_calls(ecfr_store, tmp_path):
    stub = stub_of(tmp_path, lambda s, u, r: "1. WATERWAY: x")
    facts, report = second_pass_all(ecfr_store, stub, CONTRACTS)
    assert stub.calls == 2 * len(facts)
    assert all({v.null_reason for v in f.section.values()} == {"unparseable"} for f in facts)

    def down(system, user, repeat):
        raise ModelError("down")

    facts, report = second_pass_all(ecfr_store, stub_of(tmp_path, down, "d"), CONTRACTS)
    assert report["calls"]["failed"] == len(facts)
    assert all({v.null_reason for v in f.section.values()} == {"model_error"} for f in facts)


def test_facts_are_written_once_and_load_back(ecfr_store, tmp_path):            # C4
    facts, _ = second_pass_all(ecfr_store, stub_of(tmp_path, fixture_numbered), CONTRACTS)
    facts_id, path = write_facts(ecfr_store.path, ecfr_store.snapshot_id, facts)
    assert path.name == f"second-pass-{facts_id[:16]}.jsonl"
    assert path.parent.name == ecfr_store.snapshot_id
    assert load_facts(ecfr_store.path, facts_id) == facts
    assert write_facts(ecfr_store.path, ecfr_store.snapshot_id, facts) == (facts_id, path)
    assert all(isinstance(v.checks_failed, tuple) for f in facts for v in f.section.values())
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(TablesError):
        load_facts(ecfr_store.path, facts_id)
    with pytest.raises(TablesError):
        load_facts(ecfr_store.path, "0" * 64)


# -- matching and agreement ------------------------------------------------------------------------

def test_bridge_key_drops_the_article_and_the_word_bridge():
    assert bridge_key("The Main Street Bridge") == "main street"
    assert bridge_key("Rail Drawbridge") == "rail" == bridge_key("RAIL")
    assert bridge_key("  US 17  bridge. ") == "us 17"
    assert bridge_key("Bridge") == "bridge"


def test_match_draws_by_key_then_mile():
    a = [{"bridge": "Main Street Bridge", "mile": 3.0}, {"bridge": "Rail", "mile": 7.1}]
    b = [{"bridge": "Rail Drawbridge", "mile": 7.1}, {"bridge": "Main St.", "mile": 3.0}]
    assert match_draws(a, b) == [(0, 1), (1, 0)]
    c = [{"bridge": "Other", "mile": None}, {"bridge": None, "mile": 7.1}]
    assert match_draws(a, c) == [(0, None), (1, 1), (None, 0)]
    assert match_draws([], b) == [(None, 0), (None, 1)]
    twins = [{"bridge": "Railroad Bridge", "mile": 1.0}, {"bridge": "Railroad Bridge", "mile": 2.0}]
    assert match_draws(twins, list(reversed(twins))) == [(0, 0), (1, 1)]


def _val(value) -> Value:
    if value is None:
        return Value(None, None, None, None, None, "absent", (), None)
    return Value(value, "q", 0, 1, "verified", None, (), None)


def _facts(unit, section, draws) -> Facts:
    return Facts(unit, {c: _val(section.get(c)) for c in SECTION_COLUMNS},
                 [{c: _val(d.get(c)) for c in DRAW_COLUMNS} for d in draws])


def test_agreement_per_column():
    first = [_facts("u1", {"waterway": "Neuse River", "vhf_channel": 9},
                    [{"bridge": "US 17 Bridge", "mile": 2.0, "notice_hours": 4,
                      "closed_periods": ["7 a.m. to 9 a.m."], "opens_on_signal": True},
                     {"bridge": "Rail", "mile": 3.1, "opens_on_signal": False}]),
             _facts("u2", {"waterway": "Cape Fear River", "seasonal": True},
                    [{"bridge": "Memorial Bridge", "mile": 26.8}])]
    second = [_facts("u1", {"waterway": "the neuse river", "vhf_channel": 13},
                     [{"bridge": "Rail Drawbridge", "mile": 3.1, "opens_on_signal": True},
                      {"bridge": "US 17", "mile": 2.0, "notice_hours": 4,
                       "closed_periods": ["7 A.M. to 9 a.m."], "opens_on_signal": True}]),
              _facts("u2", {"waterway": "Cape Fear River", "seasonal": None},
                     [{"bridge": "Memorial", "mile": 26.8}, {"bridge": "Other", "mile": 1.0}])]
    got = agreement(first, second)
    assert got["columns"]["waterway"] == {"compared": 2, "agree": 2, "share": 1.0}  # by key
    assert got["columns"]["vhf_channel"]["agree"] == 1           # 9 vs 13 no; null-null yes
    assert got["columns"]["seasonal"]["agree"] == 1               # True vs null: disagree
    assert got["columns"]["owner_or_agency"] == {"compared": 2, "agree": 2, "share": 1.0}
    assert got["columns"]["mile"] == {"compared": 3, "agree": 3, "share": 1.0}
    assert got["columns"]["notice_hours"]["agree"] == 3
    assert got["columns"]["closed_periods"]["agree"] == 3          # case-folded key sets
    assert got["columns"]["opens_on_signal"] == {"compared": 3, "agree": 2, "share": 2 / 3}
    assert got["columns"]["bridge"] == {"compared": 2, "agree": 1, "share": 0.5}
    assert got["draws"] == {"matched": 3, "first_only": 0, "second_only": 1}
    assert got["units"] == {"compared": 2, "first_only": 0, "second_only": 0}
