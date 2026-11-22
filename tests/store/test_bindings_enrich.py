"""Rule enrichment for the binding sections (Phase 4 spec §6.2–§6.4, §4.5; Task 15): the pool,
one cached call per section, the checks of §6.3 (Phase 3 P21/P22), the window grammar read on
the whole sentence, the write-once enrichment file, the build's rules pass and
`adr units compile --rules`. Stub clients only: no test calls a model or needs the model CLI."""

from __future__ import annotations

import json

import pytest

from adr_eval import llm
from adr_eval.cache import Cache
from adr_eval.llm import CachedStubClient
from adr_eval.pipeline import BudgetExceeded
from adr_store.bindings import enrich
from adr_store.bindings.dsl import DAYS, Window
from adr_store.bindings.enrich import (
    MAX_TOKENS,
    POOL,
    PROMPT_VERSION,
    SEED4,
    binding_sections,
    enrich_all,
    enrich_section,
    load_enrichment,
    missing_qualifiers,
    read_sentence,
    write_enrichment,
)
from adr_store.store import Store
from adr_store.tables import extract as ex
from adr_store.tables.contracts import load_contracts
from adr_store.tables.overlay import TablesError, read_head
from adr_store.units.build import build_units
from adr_store.units.contracts import load_unit_contracts
from adr_store.units.ecfr import rule_cards
from adr_store.units.grounding import load_pass_config
from adr_store.units.overlay import UNITS_DIR, UnitsError, load_units, load_units_manifest
from tests.store.units_fixtures import (  # noqa: F401
    DOC_117_NEW,
    ENRICH_ABSENT,
    ENRICH_TIMES_A,
    ENRICH_WEEKDAYS,
    enrich_cell,
    enrich_closed_period,
    enrich_reply_821,
    enrich_reply_901,
    make_units_store_with_tables,
    overlay_of,
    units_enrich_reply,
    units_fixture_numbered,
    units_store,
)

WEEKDAYS = ENRICH_WEEKDAYS
TIMES_A = ENRICH_TIMES_A
cell, ABSENT, closed_period = enrich_cell, ENRICH_ABSENT, enrich_closed_period
reply_821, reply_901, replies = enrich_reply_821, enrich_reply_901, units_enrich_reply


def stub(tmp_path, fn, name: str = "llm", cls=CachedStubClient) -> CachedStubClient:
    return cls("stub-sonnet", Cache(tmp_path / name), fn)


def cards_of(store: Store):
    return rule_cards(store, DOC_117_NEW, overlay_of(store))[0]


@pytest.fixture
def enrich_821(units_store, tmp_path):  # noqa: F811
    """`enrich_821(reply_dict_or_text, section="117.821")`: the enrichment of the section when
    the model replies that."""
    cards = cards_of(units_store)
    made = []

    def run(reply, section: str = "117.821"):
        text = reply if isinstance(reply, str) else json.dumps(reply)
        client = stub(tmp_path, lambda s, u, r: text, name=f"llm{len(made)}")
        made.append(client)
        return enrich_section(section, units_store, cards, client)

    return run


def first_period(item):
    return item.draws[0].periods[0]


# -- the pool (§6.2, §4.5) ------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tables_store(tmp_path_factory) -> Store:
    """The units fixture with its Phase 3 tables on `tables/HEAD` (built once per module)."""
    return make_units_store_with_tables(tmp_path_factory.mktemp("enrich") / "s")


def test_pool_is_subpart_a_plus_seeded_disjoint_draws(tables_store, monkeypatch):
    store = tables_store
    monkeypatch.setattr(enrich, "POOL", {"closed_window": 1, "notice": 1})   # the fixture's size
    secs = binding_sections(store, read_head(store.path), SEED4)
    assert secs[:4] == ["117.4", "117.5", "117.31", "117.40"] and len(secs) == 6 == len(set(secs))
    assert secs == binding_sections(store, read_head(store.path), SEED4)
    # § 117.821 is the one section with a crisp closed window, so the notice draw cannot take
    # it and takes § 117.901; § 117.1081 is not crisp (its signal value is unknown)
    assert secs[4:] == ["117.821", "117.901"]
    pools = enrich.pools(store, read_head(store.path), SEED4)
    assert pools["closed_window_candidates"] == ["117.821"]
    assert pools["notice_candidates"] == ["117.821", "117.901"]
    assert "117.1081" not in secs
    # a short pool gives what it has, never a section twice
    monkeypatch.setattr(enrich, "POOL", {"closed_window": 3, "notice": 3})
    assert binding_sections(store, read_head(store.path), SEED4)[4:] == ["117.821", "117.901"]
    with pytest.raises(TablesError):
        binding_sections(store, "0" * 64, SEED4)


def test_the_pool_order_follows_the_seed(monkeypatch):
    ranked = enrich._ranked(["117.9", "117.1", "117.5", "117.7"], SEED4)
    assert ranked == enrich._ranked(list(reversed(["117.9", "117.1", "117.5", "117.7"])), SEED4)
    assert sorted(ranked) == ["117.1", "117.5", "117.7", "117.9"]
    assert any(enrich._ranked(ranked, s) != ranked for s in range(1, 6))
    assert POOL == {"closed_window": 15, "notice": 15}


# -- the call -------------------------------------------------------------------------------------

def test_one_call_per_section_with_its_text_and_card_ids(units_store, tmp_path):  # noqa: F811
    seen = []

    def record(system, user, repeat):
        seen.append((system, user))
        return json.dumps(reply_821())

    item = enrich_section("117.821", units_store, cards_of(units_store), stub(tmp_path, record))
    assert len(seen) == 1 and item.outcome == "reply"
    system, user = seen[0]
    section_text, ids = user.split("\n\nRULE CARDS:\n")
    assert section_text.startswith("§ 117.821 Smith River.\n(a) The draw of the Main Street")
    assert "(d) The Main Street drawbridge" in section_text and "117.901" not in section_text
    assert ids.splitlines() == ["33 CFR 117.821(a)", "33 CFR 117.821(b)"]
    assert system.startswith(f"Prompt version: {PROMPT_VERSION}\nSpecs: rule_card.subject@1, "
                             "rule_card.conditions@1, rule_card.thresholds@1, "
                             "rule_card.exceptions@1\n")
    assert item.section == "117.821" and item.doc_id == DOC_117_NEW
    full = units_store.text(DOC_117_NEW)
    assert item.section_sha256 == next(u.text_sha256 for u in ex.units(units_store)
                                       if u.text == section_text)
    assert section_text in full


def test_the_call_passes_max_tokens_4000_and_caches_it(units_store, tmp_path,  # noqa: F811
                                                       monkeypatch):
    sizes = []

    class Sized(CachedStubClient):
        def complete(self, system, user, *, max_tokens, repeat=0, cache_failures=False):
            sizes.append(max_tokens)
            return super().complete(system, user, max_tokens=max_tokens, repeat=repeat,
                                    cache_failures=cache_failures)

    client = Sized("stub-sonnet", Cache(tmp_path / "llm"), replies)
    enrich_section("117.821", units_store, cards_of(units_store), client)
    assert sizes == [MAX_TOKENS] == [4000]                    # preflight C3
    again = ex.metered_client(0, client=client)
    enrich_section("117.821", units_store, cards_of(units_store), again)
    assert again.budget.calls == 0
    # the pass's own value is what is sent (the extractor's default is also 4000)
    monkeypatch.setattr(enrich, "MAX_TOKENS", 1234)
    enrich_section("117.821", units_store, cards_of(units_store), client)
    assert sizes[-1] == 1234


def test_the_prompt_states_the_reply_shape_and_phase3_p22():
    system = enrich.pass_prompt(load_pass_config("rules"))
    assert "at all other times" in system and "wherever none of the draw's periods" in system
    for needle in ('"cards"', '"draws"', '"periods"', "need_not_open", "notice_required",
                   "on_signal", "advance_notice", "closed_to_navigation",
                   "A negative or false value needs a quote", '"null_reason": "absent"'):
        assert needle in system, needle


def test_the_committed_config_has_one_rules_group_and_the_contract_spec_ids():
    cfg = load_pass_config("rules")
    assert cfg.prompt_version == PROMPT_VERSION == "rule-enrich@1"
    assert list(cfg.groups) == ["main"]
    fields = ("subject", "conditions", "thresholds", "exceptions")
    contract = load_unit_contracts()["rule_card"]
    assert cfg.specs == {f.name: f.spec_id for f in contract.fields if f.name in fields}


# -- the checks (§6.3) ----------------------------------------------------------------------------

def test_enrichment_values_are_grounded_and_coerced(enrich_821, units_store):  # noqa: F811
    item = enrich_821(reply_821(start=cell("7 a.m.", TIMES_A)))
    p = first_period(item)
    assert p.start.value == 420 and p.start.status == "verified"
    assert p.end.value == 540 and p.end.status == "verified"
    assert p.days.value == list(DAYS[:5]) and p.except_federal_holidays.value is True
    assert p.effect.value == "need_not_open" and p.date_from.null_reason == "absent"
    # the stored quote is the located slice, at document offsets
    full = units_store.text(DOC_117_NEW)
    for g in (p.start, p.days, item.draws[1].notice_hours, item.draws[0].mile):
        assert full[g.start:g.end] == g.quote
    d2 = item.draws[1]
    assert (d2.draw, d2.opening_basis.value, d2.notice_hours.value) == (2, "advance_notice", 4)
    assert d2.notice_hours.status == "verified"                  # "four" states 4
    assert item.draws[0].mile.value == 3.4 and item.draws[0].bridge.value == \
        "Main Street drawbridge"


def test_dates_coerce_to_month_days(enrich_821):
    p = first_period(enrich_821(reply_901(), "117.901"))
    assert (p.date_from.value, p.date_to.value) == ("11-01", "03-31")
    assert p.date_from.status == p.date_to.status == "verified"
    assert p.start.null_reason == p.end.null_reason == "absent"
    bad = reply_901()
    bad["draws"][0]["periods"][0]["date_from"] = cell("February 30", "From November 1")
    assert first_period(enrich_821(bad, "117.901")).date_from.null_reason == "unparseable"
    moved = reply_901()
    moved["draws"][0]["periods"][0]["date_to"] = cell("04-30", "From November 1 through March 31")
    assert first_period(enrich_821(moved, "117.901")).date_to.status == "auto-accepted"


@pytest.mark.parametrize(("raw", "days"), [
    (WEEKDAYS, DAYS[:5]), (["Mon", "Tue", "Wed", "Thu", "Fri"], DAYS[:5]),
    ("Monday through Friday", DAYS[:5]), (["Saturday", "Sunday"], DAYS[5:]),
    ("Saturdays and Sundays", DAYS[5:]), ("weekdays", DAYS[:5]), ("daily", DAYS),
    ("Friday through Monday", ("Mon", "Fri", "Sat", "Sun")), (["Sunday", "Monday"], ("Mon", "Sun")),
])
def test_weekdays_coerce_to_days(enrich_821, raw, days):
    p = first_period(enrich_821(reply_821(days=cell(raw, "Monday through Friday"))))
    assert p.days.value == list(days)


@pytest.mark.parametrize("raw", [[], ["Moonday"], 5, "on the hour", [1, 2]])
def test_unreadable_weekdays_are_unparseable(enrich_821, raw):
    p = first_period(enrich_821(reply_821(days=cell(raw, "Monday through Friday"))))
    assert p.days.value is None and p.days.null_reason in ("unparseable", "absent")
    if raw != []:
        assert p.days.null_reason == "unparseable"


def test_an_end_written_59_runs_through_that_minute_and_midnight_ends_the_day(enrich_821):
    p = first_period(enrich_821(reply_821(end=cell("8:59 a.m.", "from 7 a.m. to 9 a.m."))))
    assert p.end.value == 540 and p.end.status == "auto-accepted"   # P45; 8:59 is not quoted
    p = first_period(enrich_821(reply_821(end=cell("midnight", "from 7 a.m. to 9 a.m."))))
    assert p.end.value == 1440
    p = first_period(enrich_821(reply_821(start=cell("midnight", TIMES_A))))
    assert p.start.value == 0


def test_no_holiday_exception_needs_a_quote(enrich_821):                  # Phase 3 P22
    p = first_period(enrich_821(reply_821(except_federal_holidays=cell(False, None))))
    assert p.except_federal_holidays.value is None
    assert p.except_federal_holidays.null_reason == "absent"
    # stated, it is kept
    p = first_period(enrich_821(reply_821(except_federal_holidays=cell(
        False, "Monday through Friday"))))
    assert p.except_federal_holidays.value is False
    # a positive value without a quote fails grounding instead
    p = first_period(enrich_821(reply_821(except_federal_holidays=cell(True, None))))
    assert p.except_federal_holidays.null_reason == "ungrounded"
    # no notice and a closed draw are negatives too
    r = reply_821()
    r["draws"][1]["notice_hours"] = cell(0, None)
    r["draws"][1]["opening_basis"] = cell("closed_to_navigation", "")
    d = enrich_821(r).draws[1]
    assert d.notice_hours.null_reason == d.opening_basis.null_reason == "absent"
    r["draws"][1]["opening_basis"] = cell("on_signal", None)
    assert enrich_821(r).draws[1].opening_basis.null_reason == "ungrounded"


def test_a_time_not_in_its_quote_is_auto_accepted(enrich_821):
    p = first_period(enrich_821(reply_821(start=cell("7:30 a.m.", TIMES_A))))
    assert p.start.value == 450 and p.start.status == "auto-accepted"
    r = reply_821()
    r["draws"][1]["notice_hours"] = cell(5, "four hours notice")
    r["draws"][0]["mile"] = cell(3.5, "mile 3.4")
    d1, d2 = enrich_821(r).draws
    assert (d2.notice_hours.value, d2.notice_hours.status) == (5, "auto-accepted")
    assert (d1.mile.value, d1.mile.status) == (3.5, "auto-accepted")


def test_an_ungrounded_quote_is_null_ungrounded(enrich_821):
    p = first_period(enrich_821(reply_821(start=cell("7 a.m.", "from 7 a.m. to 10 a.m."))))
    assert p.start.value is None and p.start.null_reason == "ungrounded"


@pytest.mark.parametrize(("changes", "field"), [
    ({"effect": cell("closed", "need not open")}, "effect"),
    ({"start": cell("7.am", TIMES_A)}, "start"),
    ({"start": cell(420, TIMES_A)}, "start"),
    ({"except_federal_holidays": cell("yes", "except Federal holidays")},
     "except_federal_holidays"),
])
def test_values_of_the_wrong_type_or_outside_their_values_are_unparseable(enrich_821, changes,
                                                                        field):
    p = first_period(enrich_821(reply_821(**changes)))
    assert getattr(p, field).null_reason == "unparseable"


def test_a_model_reason_is_kept_and_silence_is_absent(enrich_821):
    p = first_period(enrich_821(reply_821(date_from=cell(None, None, "not_applicable"))))
    assert p.date_from.null_reason == "not_applicable"
    p = first_period(enrich_821(reply_821(date_from=cell(None, None, "made up"))))
    assert p.date_from.null_reason == "absent"
    r = reply_821()
    del r["draws"][0]["periods"][0]["days"]
    assert first_period(enrich_821(r)).days.null_reason == "absent"


def test_card_fields_are_grounded_per_card_and_unknown_cards_are_ignored(enrich_821,
                                                                         units_store):  # noqa: F811,E501
    r = reply_821()
    r["cards"]["33 CFR 117.999(a)"] = r["cards"]["33 CFR 117.821(a)"]      # not of the section
    del r["cards"]["33 CFR 117.821(b)"]
    r["cards"]["33 CFR 117.821(a)"]["exceptions"] = cell(["Federal holidays"], "every holiday")
    item = enrich_821(r)
    assert sorted(item.cards) == ["33 CFR 117.821(a)", "33 CFR 117.821(b)"]
    a, b = item.cards["33 CFR 117.821(a)"], item.cards["33 CFR 117.821(b)"]
    assert a["subject"].value == "the draw of the Main Street drawbridge"
    assert a["conditions"].value[0] == "from 7 a.m. to 9 a.m." and \
        a["conditions"].status == "verified"
    assert a["thresholds"].null_reason == "absent"
    assert a["exceptions"].null_reason == "ungrounded"
    assert all(v.null_reason == "absent" for v in b.values())          # left out of the reply
    full = units_store.text(DOC_117_NEW)
    assert full[a["conditions"].start:a["conditions"].end] == a["conditions"].quote


def test_a_threshold_number_must_be_in_its_quote(enrich_821):
    r = reply_821()
    r["cards"]["33 CFR 117.821(b)"]["thresholds"] = cell(["6 hours notice"],
                                                         "at least four hours notice")
    assert enrich_821(r).cards["33 CFR 117.821(b)"]["thresholds"].status == "auto-accepted"


def test_unparseable_is_retried_once_at_repeat_1(units_store, tmp_path):  # noqa: F811
    repeats = []

    def once_bad(system, user, repeat):
        repeats.append(repeat)
        return "not json" if repeat == 0 else json.dumps(reply_821())

    item = enrich_section("117.821", units_store, cards_of(units_store),
                          stub(tmp_path, once_bad, "a"))
    assert repeats == [0, 1] and item.outcome == "reply_repeat_1" and len(item.draws) == 2
    repeats.clear()

    def wrong_shape(system, user, repeat):
        repeats.append(repeat)
        return json.dumps({"cards": [], "draws": {}})

    item = enrich_section("117.821", units_store, cards_of(units_store),
                          stub(tmp_path, wrong_shape, "b"))
    assert repeats == [0, 1] and item.outcome == "unparseable" and item.draws == []
    assert all(g.null_reason == "unparseable" for c in item.cards.values() for g in c.values())


def test_input_rejection_cached_other_failures_stop(units_store, tmp_path):  # noqa: F811
    """Phase 3 P21: an input rejection is stored and gives null `model_error`, then and on
    every rerun with no call; any other failure stops the run uncached, and a rerun resumes
    from the cache; a budget stop is never cached."""
    cards = cards_of(units_store)

    def reject(system, user, repeat):
        raise llm.InputRejected("HTTP 400: prompt is too long")

    client = stub(tmp_path, reject)
    item = enrich_section("117.821", units_store, cards, client)
    assert item.outcome == "model_error" and item.draws == []
    assert all(g.null_reason == "model_error" for c in item.cards.values() for g in c.values())
    meter = ex.metered_client(0, client=client)
    assert enrich_section("117.821", units_store, cards, meter) == item
    assert meter.budget.calls == 0
    for error in (llm.ModelError("HTTP 401: authentication"),
                  llm.RateLimitedError("usage limit: resets at 5pm")):
        def fail(system, user, repeat, error=error):
            raise error

        cache_dir = f"llm-{type(error).__name__}"
        with pytest.raises((llm.ModelError, llm.RetriesExhausted)):
            enrich_section("117.821", units_store, cards, stub(tmp_path, fail, cache_dir))
        resumed = stub(tmp_path, replies, cache_dir)
        assert enrich_section("117.821", units_store, cards, resumed).outcome == "reply"
        assert resumed.calls == 1                                  # nothing was cached
    meter = ex.metered_client(0, client=stub(tmp_path, replies, "llm-empty"))
    with pytest.raises(BudgetExceeded):
        enrich_section("117.821", units_store, cards, meter)
    assert meter.budget.calls == 0


# -- the window grammar on the whole sentence (§6.3 check 5; Task 14 carried rulings) -------------

def test_window_grammar_agreement_is_read_on_the_whole_sentence(enrich_821):
    item = enrich_821(reply_821())
    p1, p2 = item.draws[0].periods
    assert p1.window_readable is p2.window_readable is True
    assert p1.window_quote == TIMES_A
    assert p1.window_grammar_agrees is p2.window_grammar_agrees is True
    assert p1.sentence_qualifiers == [] and p1.sentence_conditions == []
    # the model leaves out the days and the holiday exception the sentence states: the quote
    # alone reads, but the whole sentence disagrees and the qualifiers are flagged
    p = first_period(enrich_821(reply_821(days=ABSENT, except_federal_holidays=ABSENT)))
    assert p.window_readable is True and p.window_grammar_agrees is False
    assert p.sentence_qualifiers == ["days", "holidays"]
    # a window the sentence does not state disagrees, with no qualifier missing
    p = first_period(enrich_821(reply_821(start=cell("8 a.m.", TIMES_A))))
    assert p.window_grammar_agrees is False and p.sentence_qualifiers == []


def test_agreement_is_never_used_to_reject(enrich_821):
    p = first_period(enrich_821(reply_821(days=ABSENT, except_federal_holidays=ABSENT)))
    assert p.start.value == 420 and p.start.status == "verified"


def test_an_unreadable_window_quote_is_recorded(enrich_821):
    quote = "The draw of the Main Street drawbridge, mile 3.4, at Smithfield, need not open " \
        "from 7 a.m. to 9 a.m."
    p = first_period(enrich_821(reply_821(start=cell("7 a.m.", quote), end=cell("9 a.m.",
                                                                                quote))))
    assert p.window_readable is False and p.start.value == 420
    assert p.window_grammar_agrees is True        # the sentence still reads around it


def test_a_period_less_notice_is_flagged_with_what_its_sentence_states(enrich_821):
    # the notice of § 117.901(b) holds from November 1 through March 31; given with no period,
    # the compiler would apply it all year, so the draw is flagged
    r = reply_901()
    r["draws"][0]["periods"] = []
    r["draws"][0]["notice_hours"] = cell(24, "24 hours notice")
    d = enrich_821(r, "117.901").draws[0]
    assert d.sentence_qualifiers == ["dates"]
    assert enrich_821(reply_901(), "117.901").draws[0].sentence_qualifiers == []
    # the on-signal basis of § 117.901(a) states nothing more
    r["draws"][0]["notice_hours"] = ABSENT
    assert enrich_821(r, "117.901").draws[0].sentence_qualifiers == []


def test_stated_kinds_of_a_clause():
    text = ("(a) From December 1 through March 31, from 8 p.m. to 4 a.m., the draw shall open on "
            "signal if at least six-hours notice is given.")
    i = text.index("six-hours notice")
    assert enrich.stated_kinds(read_sentence(text, i, i + 16)) == ["dates", "times"]


def test_a_notice_period_has_no_window_reading(enrich_821):
    p = first_period(enrich_821(reply_901(), "117.901"))
    assert p.window_readable is None and p.window_grammar_agrees is None


SECTION = ("§ 117.9 Test River.\n"
           "(a) The draw of the S342 bridge, mile 0.1 at Cambridge, shall open on signal from "
           "6 a.m. to 8 p.m.; except that, from 12 noon to 1 p.m. Monday through Friday, the "
           "draw need not be opened. The draw need not be opened from 8 p.m. to 6 a.m.\n"
           "(1) From April 1 through October 31, Monday through Friday, the bridges need not "
           "open from 6:50 a.m. to 7 a.m., 7:50 a.m. to 8 a.m., and 12:45 p.m. to 1 p.m., "
           "except federal holidays.\n"
           "(b) The draw of the Maryland 331 bridge shall remain closed from 6 p.m. to 6 a.m., "
           "year-round, unless 24 hours advance notice is given.\n"
           "(c) The draw of the St. Claude Avenue bridge, mile 0.5 at N.W. 27th Avenue, need "
           "not open from 7 a.m. to 9 a.m. Monday through Friday. The draw shall open on "
           "signal at all other times.\n")


def at(quote: str) -> tuple[int, int]:
    i = SECTION.index(quote)
    return i, i + len(quote)


def test_read_sentence_finds_the_sentence_past_clock_abbreviations():
    r = read_sentence(SECTION, *at("from 12 noon to 1 p.m."))
    assert r.sentence.startswith("The draw of the S342 bridge") and \
        r.sentence.endswith("the draw need not be opened.")
    assert r.windows == [Window(start=720, end=780, days=DAYS[:5], except_federal_holidays=False,
                                date_from=None, date_to=None)]
    # the clause after "; except that" is the quote's, so the opening hours are not its days
    assert r.stated["days"] == [DAYS[:5]] and r.stated["times"] == [(720, 780)]
    r = read_sentence(SECTION, *at("from 8 p.m. to 6 a.m."))
    assert r.sentence == "The draw need not be opened from 8 p.m. to 6 a.m."
    assert r.readable is True                       # the whole sentence reads
    r = read_sentence(SECTION, *at("from 7 a.m. to 9 a.m."))
    assert r.sentence.startswith("The draw of the St. Claude Avenue bridge, mile 0.5 at N.W. "
                                 "27th Avenue,") and r.sentence.endswith("Monday through Friday.")
    assert r.readable is False and r.windows[0].days == DAYS[:5]


def test_read_sentence_reads_qualifiers_stated_before_the_quote():
    r = read_sentence(SECTION, *at("6:50 a.m. to 7 a.m."))
    assert r.readable is True and r.sentence.startswith("From April 1")   # marker dropped
    assert len(r.windows) == 3 and all(w.date_from == "04-01" and w.except_federal_holidays
                                       for w in r.windows)
    quote_only = Window(start=410, end=420, days=DAYS, except_federal_holidays=False,
                        date_from=None, date_to=None)
    assert missing_qualifiers(quote_only, r) == ["dates", "days", "holidays"]
    assert missing_qualifiers(r.windows[0], r) == []


def test_only_unless_or_notice_around_the_range_is_not_a_plain_closure():
    r = read_sentence(SECTION, *at("from 6 p.m. to 6 a.m., year-round"))
    assert r.conditions == ("unless", "notice")
    assert read_sentence(SECTION, *at("from 12 noon to 1 p.m.")).conditions == ()


def test_an_unconditioned_reading_agrees_and_a_conditioned_one_is_not_compared():
    w = Window(start=1080, end=360, days=DAYS, except_federal_holidays=False, date_from=None,
               date_to=None)
    r = read_sentence(SECTION, *at("from 6 p.m. to 6 a.m., year-round"))
    assert enrich.grammar_agrees(w, r) is None
    r = read_sentence(SECTION, *at("from 8 p.m. to 6 a.m."))
    assert enrich.grammar_agrees(w.model_copy(update={"start": 1200}), r) is True
    assert enrich.grammar_agrees(w, r) is False


def test_agreement_holds_a_date_range_written_before_the_subject():           # Minor 3
    text = ("(d) From April 1 through October 31, the draw of the Main Street bridge, mile 1.0, "
            "need not open from 7 a.m. to 9 a.m., Monday through Friday, except Federal "
            "holidays.\n")
    i = text.index("7 a.m. to 9 a.m.")
    r = read_sentence(text, i, i + 16)
    right = Window(start=420, end=540, days=DAYS[:5], except_federal_holidays=True,
                   date_from="04-01", date_to="10-31")
    assert enrich.grammar_agrees(right, r) is True
    no_dates = right.model_copy(update={"date_from": None, "date_to": None})
    assert enrich.grammar_agrees(no_dates, r) is False
    assert missing_qualifiers(no_dates, r) == ["dates"]
    other_dates = right.model_copy(update={"date_to": "09-30"})
    assert enrich.grammar_agrees(other_dates, r) is False
    no_days = right.model_copy(update={"days": DAYS})
    assert enrich.grammar_agrees(no_days, r) is False


def test_a_qualifier_the_clause_does_not_state_disagrees():
    text = "(a) The draw need not open from 7 a.m. to 9 a.m.\n"
    i = text.index("from 7")
    r = read_sentence(text, i, len(text) - 1)
    w = Window(start=420, end=540, days=DAYS, except_federal_holidays=False, date_from=None,
               date_to=None)
    assert enrich.grammar_agrees(w, r) is True
    assert enrich.grammar_agrees(w.model_copy(update={"except_federal_holidays": True}), r) \
        is False
    assert enrich.extra_qualifiers(w.model_copy(update={"days": DAYS[:5]}), r) == ["days"]


def _first_row(quote: str):
    from adr_store.tables.provenance import RowRecord, ValueProv

    return RowRecord(doc_id=DOC_117_NEW, row={
        "section": "117.821", "draw": 1, "bridge": "Main Street drawbridge", "mile": 3.4,
        "notice_hours": None, "opens_on_signal": False, "closed_periods": [quote]},
        prov={"closed_periods": [ValueProv(doc_id=DOC_117_NEW, start=0, end=len(quote),
                                           spec_id="bridge.closed_periods@1",
                                           status="verified", quote=quote)]})


def _facts(unit: str, quote: str):
    v = lambda value, q="q": ex.Value(value, q, 0, len(q), "verified", None, (), None)  # noqa: E731
    return ex.Facts(unit, {}, [{"bridge": v("Main Street drawbridge"), "mile": v(3.4),
                                "closed_periods": v([quote], quote)}])


def test_e2_compares_the_compilers_windows_of_real_enrichment_output(enrich_821):   # I1
    """E2 on what `enrich_section` produces: the window quotes hold the time ranges only
    (`rule_enrich.txt`), so E2 must compare the parameters the compiler uses."""
    item = enrich_821(reply_821())
    assert [p.window_quote for p in item.draws[0].periods] == [TIMES_A, "from 4 p.m. to 6 p.m."]
    full = ("need not open from 7 a.m. to 9 a.m. and from 4 p.m. to 6 p.m. Monday through "
            "Friday except Federal holidays")
    short = "need not open from 7 a.m. to 9 a.m. and from 4 p.m. to 6 p.m. Monday through Friday"
    e2 = enrich.e2_agreement([item], [_first_row(full)], [_facts(item.section_sha256, short)])
    assert e2["first"]["closed_windows"] == {"compared": 1, "agree": 1, "share": 1.0,
                                             "unread": 0}
    assert e2["second"]["closed_windows"] == {"compared": 1, "agree": 0, "share": 0.0,
                                              "unread": 0}       # the quote drops holidays
    # a reply that leaves the days and holidays out disagrees with the full quote
    lax = enrich_821(reply_821(days=ABSENT, except_federal_holidays=ABSENT))
    e2 = enrich.e2_agreement([lax], [_first_row(full)], [])
    assert e2["first"]["closed_windows"]["agree"] == 0


# -- the enrichment file --------------------------------------------------------------------------

def test_write_enrichment_is_write_once_and_loads_back(enrich_821, units_store, tmp_path):  # noqa: F811,E501
    items = [enrich_821(reply_901(), "117.901"), enrich_821(reply_821())]
    eid, path = write_enrichment(units_store.path, units_store.snapshot_id, items)
    assert path.name == f"enrichment-{eid[:16]}.jsonl" and path.parent.name == \
        units_store.snapshot_id and path.parent.parent.name == UNITS_DIR
    lines = path.read_text().splitlines()
    assert [json.loads(x)["section"] for x in lines] == ["117.821", "117.901"]   # sorted
    assert write_enrichment(units_store.path, units_store.snapshot_id,
                            list(reversed(items))) == (eid, path)            # same bytes: no-op
    assert load_enrichment(units_store.path, eid) == sorted(items, key=lambda i: i.section)
    path.write_text(lines[0] + "\n")
    with pytest.raises(Exception, match="enrichment"):
        load_enrichment(units_store.path, eid)
    with pytest.raises(Exception, match="enrichment"):
        load_enrichment(units_store.path, "f" * 64)


# -- the whole pass, the build and the CLI ---------------------------------------------------------

def test_enrich_all_runs_the_pool_and_reports(tables_store, tmp_path, monkeypatch):
    monkeypatch.setattr(enrich, "POOL", {"closed_window": 1, "notice": 1})
    client = stub(tmp_path, replies)
    items, report = enrich_all(tables_store, client)
    assert [i.section for i in items] == ["117.4", "117.5", "117.31", "117.40", "117.821",
                                          "117.901"]
    assert client.calls == 6 and report["calls"] == {"made": 6, "cached": 0, "failed": 0}
    assert report["sections"] == {"subpart_a": 4, "closed_window": 1, "notice": 1, "run": 6}
    assert report["outcomes"] == {"reply": 6}
    assert report["window_grammar"] == {"windows": 2, "readable": 2, "agree": 2, "disagree": 0,
                                        "not_compared": 0, "conditioned": 0,
                                        "sentence_qualifiers": 0}
    assert report["draws"] == {"draws": 3, "periods": 3}
    assert report["fields"]["start"]["verified"] == 2
    assert report["fields"]["notice_hours"]["quotes_given"] == 2
    assert report["fields"]["subject"]["nulls"] == {"absent": 7}   # subpart A and § 117.901
    items2, report2 = enrich_all(tables_store, client, limit=2)          # the canary
    assert [i.section for i in items2] == ["117.4", "117.5"] and client.calls == 6
    assert report2["calls"] == {"made": 0, "cached": 2, "failed": 0}


def test_build_with_the_rules_pass_fills_in_scope_newest_cards_only(tables_store, tmp_path,
                                                                    monkeypatch):
    monkeypatch.setattr(enrich, "POOL", {"closed_window": 1, "notice": 1})
    client = stub(tmp_path, replies)
    enrich_all(tables_store, client)
    meter = ex.metered_client(0, client=client)
    res = build_units(tables_store.path, "gov", passes=("rules",), client=meter)
    assert meter.budget.calls == 0
    m = load_units_manifest(tables_store.path, res.units_id)
    assert m.passes["rules"]["prompt_version"] == PROMPT_VERSION
    assert m.passes["rules"]["sections"] == 6 and m.passes["rules"]["max_tokens"] == 4000
    cards = load_units(tables_store.path, m, "rule_card")
    a = next(c for c in cards if c.canonical_ref == "33 CFR 117.821(a)"
             and c.doc_id == DOC_117_NEW)
    assert a.body["subject"]["value"] == "the draw of the Main Street drawbridge"
    assert a.body["subject"]["status"] == "verified" and a.body["subject"]["null_reason"] is None
    q = a.body["conditions"]["quotes"][0]
    assert tables_store.text(DOC_117_NEW)[q["span"][0]:q["span"][1]] == q["text"]
    assert a.body["thresholds"]["null_reason"] == "absent"
    assert a.lineage.prompt_version == PROMPT_VERSION and a.lineage.cache_key_sha256
    assert client.cache.get(a.lineage.cache_key_sha256) is not None
    # older versions and out-of-scope sections keep the not-extracted form
    old = next(c for c in cards if c.canonical_ref == "33 CFR 117.821(a)"
               and c.doc_id != DOC_117_NEW)
    out = next(c for c in cards if c.canonical_ref == "33 CFR 117.1081(a)(2)")
    for c in (old, out):
        assert all(c.body[f]["null_reason"] == "not_extracted"
                   for f in ("subject", "conditions", "thresholds", "exceptions"))
        assert c.lineage.prompt_version is None
    # a cold cache stops at the cap before anything is written
    cold = ex.metered_client(0, client=stub(tmp_path, replies, "cold"))
    with pytest.raises(BudgetExceeded):
        build_units(tables_store.path, "gov", passes=("rules",), client=cold)


def test_the_rules_pass_needs_tables(units_store, tmp_path):  # noqa: F811
    with pytest.raises(UnitsError, match="tables/HEAD"):
        build_units(units_store.path, "gov", passes=("rules",),
                    client=ex.metered_client(0, client=stub(tmp_path, replies)))


def adr(argv, capsys) -> tuple[int, str, str]:
    from adr_store import cli as adr_cli

    code = adr_cli.main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out, out.err


class ServedStub(CachedStubClient):
    """A cached stub whose provider reports the model that answered."""

    def _attempt(self, system, user, max_tokens, repeat):
        from dataclasses import replace

        return replace(super()._attempt(system, user, max_tokens, repeat),
                       served_model="served-sonnet")


def _profiles(monkeypatch, tmp_path, cls=CachedStubClient) -> list[str]:
    from adr_eval import runner

    made = []

    def make_client(name, profiles, cache, max_retries=5):
        made.append(name)
        return cls(f"stub-{name}", Cache(tmp_path / "llm"), replies)

    monkeypatch.setattr(runner, "make_client", make_client)
    return made


def test_adr_units_compile_rules_list_calls_nothing(tables_store, tmp_path, capsys,
                                                    monkeypatch):
    made = _profiles(monkeypatch, tmp_path)
    monkeypatch.setattr(enrich, "POOL", {"closed_window": 1, "notice": 1})
    code, out, err = adr(["units", "compile", "--rules", "--store", tables_store.path,
                          "--list"], capsys)                          # N6: no --max-calls
    assert code == 0, err
    assert made == []
    lines = out.splitlines()
    assert lines[0] == "6 binding section(s): 4 subpart A, 1 closed window, 1 notice"
    assert lines[1:] == ["subpart_a 117.4", "subpart_a 117.5", "subpart_a 117.31",
                         "subpart_a 117.40", "closed_window 117.821", "notice 117.901"]
    # without --list the run needs --generator and --max-calls
    for argv in (["--generator", "claude_code_sonnet"], ["--max-calls", "0"]):
        with pytest.raises(SystemExit) as e:
            adr(["units", "compile", "--rules", "--store", tables_store.path, *argv], capsys)
        assert e.value.code == 2
    with pytest.raises(SystemExit):              # --list belongs to --rules
        adr(["units", "compile", "--procedures", "--store", tables_store.path, "--list"],
            capsys)


def test_adr_units_compile_rules_stops_at_the_cap_then_compiles(tables_store, tmp_path,
                                                                capsys, monkeypatch):
    made = _profiles(monkeypatch, tmp_path)
    monkeypatch.setattr(enrich, "POOL", {"closed_window": 1, "notice": 1})
    store = tables_store
    out_dir = store.path / UNITS_DIR / store.snapshot_id
    report = out_dir / "rules-pass-report.json"
    report.unlink(missing_ok=True)
    before = set(out_dir.glob("enrichment-*.jsonl")) if out_dir.exists() else set()
    base = ["units", "compile", "--rules", "--store", store.path, "--generator",
            "claude_code_sonnet"]
    code, out, err = adr([*base, "--max-calls", 0], capsys)
    assert code == 1, err
    assert "stopped at --max-calls 0 (0 budget unit(s) used)" in out
    assert not report.exists() and set(out_dir.glob("enrichment-*.jsonl")) == before
    assert made == ["claude_code_sonnet"]
    # a second-pass facts file for E2 (preflight C5)
    numbered = CachedStubClient("stub-numbered", Cache(tmp_path / "numbered"),
                                units_fixture_numbered)
    facts, _ = ex.second_pass_all(store, numbered, load_contracts())
    facts_id, _ = ex.write_facts(store.path, store.snapshot_id, facts)
    code, out, err = adr([*base, "--max-calls", 6, "--facts", facts_id], capsys)
    assert code == 0, err
    assert "6 model call(s) made, 0 cached, 0 failed; 6 budget unit(s) of 6 used" in out
    assert "rules pass complete" in out
    data = json.loads(report.read_text())
    assert data["generator"] == "claude_code_sonnet" and data["budget_units"] == 6
    assert data["served_model_mismatch"] is False
    assert data["enrichment_id"] and data["facts_id"] == facts_id
    assert data["compile"]["draws"] == {"total": 3, "compiled": 3, "failed": 0}
    assert data["e2"]["second"]["notice_hours"]["share"] == 1.0
    assert data["e2"]["first"]["draws"]["matched"] == 3
    assert (out_dir / f"enrichment-{data['enrichment_id'][:16]}.jsonl").exists()
    # a rerun reads the cache
    code, out, err = adr([*base, "--max-calls", 0], capsys)
    assert code == 0 and "0 model call(s) made, 6 cached" in out


def test_a_served_model_other_than_the_profile_fails_the_rules_run(tables_store, tmp_path,
                                                                    capsys, monkeypatch):
    _profiles(monkeypatch, tmp_path / "served", ServedStub)
    monkeypatch.setattr(enrich, "POOL", {"closed_window": 1, "notice": 1})
    store = tables_store
    report = store.path / UNITS_DIR / store.snapshot_id / "rules-pass-report.json"
    report.unlink(missing_ok=True)
    code, out, err = adr(["units", "compile", "--rules", "--store", store.path, "--generator",
                          "claude_code_sonnet", "--max-calls", 6, "--limit", 2], capsys)
    assert code == 1, err                     # the outputs are written, the run has failed
    assert "status: served model mismatch: served-sonnet != stub-claude_code_sonnet;" in out
    data = json.loads(report.read_text())
    assert data["served_model_mismatch"] is True and data["served_models"] == ["served-sonnet"]
    assert data["limit"] == 2


def test_rules_needs_one_store(tables_store, tmp_path, capsys):
    code, _, err = adr(["units", "compile", "--rules", "--store", tables_store.path, "--store",
                        tmp_path, "--list"], capsys)
    assert code == 2 and "one --store" in err
