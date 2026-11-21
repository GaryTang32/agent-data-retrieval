"""The four unit tools (Phase 4 spec §7, §8.3, §9.2, §11.2, §11.3; Task 8): `define`,
`rule_lookup`, `procedure_lookup` and `unit_search` in `adr_store.tools.Tools`, under the ACL
layer, the applicability filters and snapshot handles.

The store is `units_fixtures.make_units_built`: the gov units of `UNITS_DOCS` (two versions of a
33 CFR 117 excerpt, a 33 CFR 165 excerpt, an IRM chapter excerpt; the bench documents hold no gov
units) built and promoted to units/HEAD, with per-document access (`UNITS_ACL_RULES`: acme-0 sees
117, 165 and bench; acme-1 117 and bench; globex-0 the IRM only; the outsider nothing; the auditor
everything). Reference stores hold one caller's documents alone. Every unit index is lexical-only
(C8): nothing loads an embedding model. Everything under `tmp_path`."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta

import pytest

from adr_store import acl, handles, tools
from adr_store.store import Store
from adr_store.tools import (
    NO_HANDLE_UNITS,
    NO_UNITS,
    UNIT_LIMIT_MAX,
    UNKNOWN_PROCEDURE,
    UNKNOWN_RULE,
    AccessDenied,
    ToolError,
)
from adr_store.units import overlay as units_overlay
from adr_store.units.procedures import ProcedureBody, validate_ir
from adr_store.units.render import ir_graph, parse_mermaid, parse_skill
from tests.store import units_fixtures as uf
from tests.store.tables_fixtures import T0
from tests.store.units_fixtures import (
    DOC_117_NEW,
    DOC_117_OLD,
    DOC_165,
    DOC_IRM,
    UNITS_DOCS,
    UNITS_USERS,
    ecfr_117_doc,
    make_units_built,
    make_units_store,
    promote_units,
)

units_built = uf.units_built
NOW = T0 + timedelta(minutes=1)
NEW16, OLD16, D165, IRM16 = DOC_117_NEW[:16], DOC_117_OLD[:16], DOC_165[:16], DOC_IRM[:16]


def card(ref: str, sha12: str, doc16: str = NEW16) -> str:
    return f"rule_card/{ref}/{sha12}/{doc16}"


A_2 = card("33 CFR 117.1081(a)(2)", "943c774389f8")
SECTION_1081 = [card("33 CFR 117.1081(a)", "82d83454aed5"),
                card("33 CFR 117.1081(a)(1)", "46f8b1e75876"), A_2,
                card("33 CFR 117.1081(b)", "43f3ef61bfc0"),
                card("33 CFR 117.1081(c)", "27b64adf5055")]
HIDDEN_RULE = "33 CFR 165.13(a)"      # in 33 CFR 165: hidden from acme-1, globex-0, outsider
PROC_1 = f"procedure/IRM 21.4.1.3.1/6ab6c77c239d/{IRM16}"
PROC_2 = f"procedure/IRM 21.4.1.3.2/094d42ccc694/{IRM16}"


@pytest.fixture(scope="module")
def store(tmp_path_factory) -> Store:
    """One promoted units store for the read-only tests of this module."""
    return make_units_built(tmp_path_factory.mktemp("units-tools") / "store")


def as_(store, caller: str = "user:auditor") -> tools.Tools:
    return tools.Tools(store.path, acl=True, caller=caller, clock=lambda: NOW)


def ids(res) -> list[str]:
    return [c.unit_id for c in res.cards]


def visible(store, caller) -> set[str]:
    snap = acl.read_head(store.path)[1]
    ps = set(snap.directory[caller])
    return {d for d, v in snap.docs.items() if ps & set(v)}


def log_lines(store) -> list[dict]:
    path = store.path / "log" / "retrieval.jsonl"
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]


STORE_SPECIFIC = ("snapshot", "units", "handle")


def strip(outcome):
    """A result as a dict without the fields naming store versions, or an error's text."""
    if isinstance(outcome, Exception):
        return ("error", str(outcome))
    return {k: v for k, v in outcome.to_dict().items() if k not in STORE_SPECIFIC}


def outcome(call, t):
    try:
        return call(t)
    except ToolError as e:
        return e


UNIT_CALLS = [
    lambda t: t.define("Drawtender"),
    lambda t: t.define("drawtenders", include_superseded=True),
    lambda t: t.define("designated representative", context="33 CFR 165.T01(b)"),
    lambda t: t.define("RNA"),
    lambda t: t.define("refund inquiry unit", context="IRM 21.4.1.3"),
    lambda t: t.define("drawtendr"),                                  # unknown: nearest labels
    lambda t: t.rule_lookup(rule_id="33 CFR 117.821(a)"),
    lambda t: t.rule_lookup(rule_id="33 CFR 117.1081"),
    lambda t: t.rule_lookup(rule_id=HIDDEN_RULE),
    lambda t: t.rule_lookup(rule_id="33 CFR 117.9999(z)"),
    lambda t: t.rule_lookup(rule_id="33 CFR 117.821(b)", include_superseded=True),
    lambda t: t.rule_lookup("drawbridge open"),
    lambda t: t.rule_lookup("regulated navigation area anchor"),
    lambda t: t.rule_lookup("designated representative", closure=False),
    lambda t: t.rule_lookup("drawbridge", part="33 CFR 165"),
    lambda t: t.rule_lookup("drawbridge open", as_of="2025-07-01", limit=3),
    lambda t: t.procedure_lookup("refund research"),
    lambda t: t.procedure_lookup(id="IRM 21.4.1.3.1", view="skill"),
    lambda t: t.procedure_lookup(id=PROC_2, view="ir"),
    lambda t: t.procedure_lookup(id="IRM 21.4.1.3.2", view="mermaid"),
    lambda t: t.unit_search("refund"),
    lambda t: t.unit_search("drawbridge notice", ["rule_card", "concept"]),
    lambda t: t.unit_search("RNA vessel"),
    lambda t: t.unit_search("table", ["table_record"], limit=2),
]


# -- access ------------------------------------------------------------------------------------

def test_unit_tools_follow_document_access(store, tmp_path_factory):
    """Every call as each caller equals the same call on a store built from that caller's
    documents alone (S1): results, counts and errors, store versions aside."""
    compared = 0
    for user in UNITS_USERS:
        seen = visible(store, user)
        if not seen:
            continue                          # the outsider: below
        docs = [(d, raw) for d, raw in UNITS_DOCS if d.doc_id in seen]
        ref_path = tmp_path_factory.mktemp("units-ref") / "store"
        make_units_store(ref_path, docs)
        promote_units(ref_path)
        ref = tools.Tools(ref_path)
        t = as_(store, user)
        for call in UNIT_CALLS:
            assert strip(outcome(call, t)) == strip(outcome(call, ref)), (user, call)
            compared += 1
    assert compared == 4 * len(UNIT_CALLS)
    # the views differ, so the comparison is not vacuous
    assert as_(store, "user:acme-0").define("RNA").senses
    assert not as_(store, "user:acme-1").define("RNA").senses
    assert as_(store, "user:globex-0").procedure_lookup("refund research").catalog
    assert not as_(store, "user:acme-0").procedure_lookup("refund research").catalog


def test_unit_tools_load_no_embedding_model(tmp_path, monkeypatch):
    """C8: at the committed tuning (`w = 1.0`) the unit tools serve a lexical-only unit index;
    no call embeds or loads a model, and the index is built in memory: `units-index/` holds
    only the pinned tuning entry (P42), no index directory."""
    import fastembed

    from adr_store.embedding import EmbeddingCache

    def no_model(*a, **kw):
        raise AssertionError("no embedding model may load")

    for target, name in ((EmbeddingCache, "model"), (EmbeddingCache, "embed_texts"),
                         (fastembed, "TextEmbedding"), (tools, "make_embedding_cache")):
        monkeypatch.setattr(target, name, no_model)
    s = make_units_built(tmp_path / "store")
    t = as_(s)
    for call in UNIT_CALLS:
        outcome(call, t)
    head = units_overlay.read_units_head(s.path)
    us = next(v for k, v in tools._UNIT_SETS.items() if k[:2] == (str(s.path.resolve()), head))
    assert us.index.lexical_only
    written = sorted(p.relative_to(s.path).as_posix() for p in (s.path / "units-index").rglob("*"))
    assert len(written) == 2 and written[0] == f"units-index/{head}"
    assert re.fullmatch(rf"units-index/{head}/tuning-[0-9a-f]{{64}}\.json", written[1])


def test_a_unit_call_never_writes_into_the_store(tmp_path, monkeypatch):
    """M7: the unit tools build their index in memory: with the index writer refusing, every
    call still runs, and nothing in the store but the retrieval log changes, except the pinned
    tuning entry the first unit call writes once (P42, Task 12); later calls write nothing."""
    from adr_store.units import index as units_index

    def no_write(*a, **kw):
        raise AssertionError("a read call wrote into the store")

    monkeypatch.setattr(units_index, "_install", no_write)
    s = make_units_built(tmp_path / "store")

    def tree() -> dict:
        return {str(p.relative_to(s.path)): p.read_bytes() for p in s.path.rglob("*")
                if p.is_file() and p.relative_to(s.path).parts[0] != "log"}

    before = tree()
    t = as_(s)
    results = [outcome(call, t) for call in UNIT_CALLS]
    assert sum(not isinstance(r, Exception) for r in results) > 20
    after = tree()
    added = sorted(set(after) - set(before))
    head = units_overlay.read_units_head(s.path)
    assert {k: v for k, v in after.items() if k in before} == before and len(added) == 1
    assert re.fullmatch(rf"units-index/{head}/tuning-[0-9a-f]{{64}}\.json", added[0])
    assert hashlib.sha256(after[added[0]]).hexdigest() == added[0][-69:-5]
    [outcome(call, as_(s)) for call in UNIT_CALLS]
    assert tree() == after                                   # the pin is written once
    with pytest.raises(ValueError, match="install=False needs emb=None"):
        units_index.UnitIndex.build(s.path, "x", [], object(), {}, install=False)


def test_the_outsider_sees_no_unit(store):
    t = as_(store, "user:outsider")
    for call in UNIT_CALLS:
        res = outcome(call, t)
        if isinstance(res, Exception):
            assert str(res) in (UNKNOWN_RULE, UNKNOWN_PROCEDURE), call
        elif isinstance(res, tools.DefineResult):
            assert res.senses == [] and res.nearest == []
        elif isinstance(res, tools.RuleLookupResult):
            assert res.cards == []
        elif isinstance(res, tools.ProcedureLookupResult):
            assert res.catalog == []
        else:
            assert res.hits == []


def test_a_hidden_rule_id_equals_a_nonexistent_one(store):
    for user in ("user:outsider", "user:acme-1", "user:globex-0"):
        for rid in (HIDDEN_RULE, "33 CFR 165.13", "33 CFR 117.9999(z)", "not a rule"):
            with pytest.raises(ToolError) as e:
                as_(store, user).rule_lookup(rule_id=rid)
            assert str(e.value) == UNKNOWN_RULE
    assert ids(as_(store, "user:acme-0").rule_lookup(rule_id=HIDDEN_RULE)) == [
        card(HIDDEN_RULE, "8f62ccff1056", D165)]
    # the hidden ids named are logged for audit, never returned
    lines = [ln for ln in log_lines(store) if ln["tool"] == "rule_lookup"
             and ln["caller"] == "user:acme-1" and ln["args"]["rule_id"] == HIDDEN_RULE]
    assert lines and lines[-1]["not_visible"] == [card(HIDDEN_RULE, "8f62ccff1056", D165)]
    assert lines[-1]["error"] == UNKNOWN_RULE


def test_hidden_procedures_terms_and_labels_do_not_exist(store):
    for pid in (PROC_1, "IRM 21.4.1.3.1", "IRM 99.9", PROC_1.replace("6ab6", "0000")):
        with pytest.raises(ToolError) as e:
            as_(store, "user:acme-1").procedure_lookup(id=pid, view="skill")
        assert str(e.value) == UNKNOWN_PROCEDURE
    r = as_(store, "user:acme-1").define("designated representative")
    assert r.senses == []
    hidden_labels = {"Designated representative", "designated representative",
                     "Regulated navigation area", "RNA", "Direct Deposit Indicator Account",
                     "DDIA", "Refund Inquiry Unit", "RIU", "Routing Transit Number", "RTN"}
    assert r.nearest and not hidden_labels & set(r.nearest)
    assert set(r.nearest) <= {"Drawbridge", "Drawtender"}
    for hit in as_(store, "user:acme-1").unit_search("refund RNA designated", limit=50).hits:
        assert hit["doc_id"] in (DOC_117_NEW, DOC_117_OLD)
    assert not as_(store, "user:acme-1").unit_search("refund RNA designated").hits


# -- rule ids ----------------------------------------------------------------------------------

@pytest.mark.parametrize("given", ["§117.1081(a)(2)", "§ 117.1081(a)(2)", "33 CFR 117.1081 (a)(2)",
                                   "117.1081(a)(2)", "33 C.F.R. § 117.1081(a)(2)",
                                   " 33 CFR 117.1081(a)(2) "])
def test_rule_id_forms_return_the_same_card(store, given):                   # Review Focus 1
    assert ids(as_(store).rule_lookup(rule_id=given)) == [A_2]
    assert ids(as_(store).rule_lookup(rule_id="33 CFR 117.1081(a)(2)")) == [A_2]


@pytest.mark.parametrize("given", ["§117.821(a)", "33 CFR 117.821 (a)", "117.821(a)"])
def test_the_plan_forms_of_117_821_a(store, given):
    assert ids(as_(store).rule_lookup(rule_id=given)) == ids(
        as_(store).rule_lookup(rule_id="33 CFR 117.821(a)")) == [
        card("33 CFR 117.821(a)", "92e3368ef6da")]


def test_a_section_rule_id_returns_every_card_under_it(store):
    for given in ("33 CFR 117.1081", "§ 117.1081", "117.1081", "33 CFR 117.1081 "):
        r = as_(store).rule_lookup(rule_id=given)
        assert ids(r) == SECTION_1081 and not r.truncated      # document order, newest only
    assert ids(as_(store).rule_lookup(rule_id="33 CFR 117.1081(a)")) == SECTION_1081[:3]
    # "117.5" is the unmarked paragraph's section (builder note 6)
    assert ids(as_(store).rule_lookup(rule_id="117.5")) == [card("33 CFR 117.5(p1)",
                                                                  "033f795bb179")]
    r = as_(store).rule_lookup(rule_id="33 CFR 117.1081", limit=2)
    assert ids(r) == SECTION_1081[:2] and r.truncated
    # a prefix of a section number is not the section; a malformed id is unknown
    for bad in ("33 CFR 117.108", "33 CFR 117.10", "117.1081(a)(2", "117", "33 CFR part 117",
                ""):
        with pytest.raises(ToolError, match=f"^{re.escape(UNKNOWN_RULE)}$"):
            as_(store).rule_lookup(rule_id=bad)


def test_version_in_force_by_default_and_as_of(store):
    assert {c.doc_id for c in as_(store).rule_lookup("drawbridge open").cards} == {DOC_117_NEW}
    assert {c.doc_id for c in as_(store).rule_lookup("drawbridge open",
                                                     as_of="2025-07-01").cards} == {DOC_117_OLD}
    both = as_(store).rule_lookup("drawbridge open", include_superseded=True, limit=50)
    assert {c.doc_id for c in both.cards} == {DOC_117_NEW, DOC_117_OLD}
    old = as_(store).rule_lookup(rule_id="33 CFR 117.821(b)", as_of="2025-07-01")
    assert [c.doc_id for c in old.cards] == [DOC_117_OLD]
    assert "two hours notice" in old.cards[0].text
    new = as_(store).rule_lookup(rule_id="33 CFR 117.821(b)")
    assert [c.doc_id for c in new.cards] == [DOC_117_NEW] and "four hours" in new.cards[0].text
    # every version, newest first
    r = as_(store).rule_lookup(rule_id="33 CFR 117.821(b)", include_superseded=True)
    assert [c.doc_id for c in r.cards] == [DOC_117_NEW, DOC_117_OLD]
    assert r.cards[0].rule_version != r.cards[1].rule_version
    assert r.applicability_filters["include_superseded"]
    # the default excludes the superseded version: it is counted, never shown
    assert as_(store).rule_lookup("drawbridge").excluded_by_filter == 1
    assert as_(store, "user:globex-0").rule_lookup("drawbridge").excluded_by_filter == 0
    # 165 is not in force before 2026-06-26
    with pytest.raises(ToolError, match=re.escape(UNKNOWN_RULE)):
        as_(store).rule_lookup(rule_id=HIDDEN_RULE, as_of="2025-07-01")


def test_a_rule_card_carries_its_fields(store):
    c = as_(store).rule_lookup(rule_id="117.1081(a)(2)").cards[0]
    text = Store.open(store.path).text(DOC_117_NEW)
    assert (c.rule_id, c.rule_version, c.doc_id, c.modality) == (
        "33 CFR 117.1081(a)(2)", "943c774389f8", DOC_117_NEW, "exemption")
    assert text[c.start:c.end] == c.text and "need not open from 6:30 a.m." in c.text
    assert c.conditions is None and c.bindings == []      # not enriched; no bindings yet


def test_closure_one_level_ordered_and_deduped(store):
    text = Store.open(store.path).text(DOC_117_NEW)
    c = as_(store).rule_lookup(rule_id="33 CFR 117.821(a)").cards[0]
    assert [(e["relation"], e["ref"]) for e in c.closure] == [
        ("defines", "concept:33 CFR part 117:drawbridge"),
        ("exception_of", "33 CFR 117.5(p1)"), ("exception_of", "33 CFR 117.31(b)"),
        *[("exception_of", f"33 CFR 117.31(b)({k})") for k in range(1, 5)],
        ("context", "33 CFR 117.821(c)"), ("context", "33 CFR 117.821(d)")]
    for e in c.closure:                  # every entry re-sliced from its document
        assert e["doc_id"] == DOC_117_NEW and text[e["start"]:e["end"]] == e["text"]
    assert c.closure[0]["text"].startswith("Drawbridge means")
    assert c.closure[-1]["unit_id"] is None and c.closure[-1]["text"].startswith("(d) The Main")
    # one level: the closure of § 117.5(p1) (its defines entry) is not added
    assert [e["relation"] for e in c.closure].count("defines") == 1
    # deduped across hits: an entry shown under an earlier card is not repeated
    cards = as_(store).rule_lookup(rule_id="33 CFR 117.1081").cards
    assert [(e["relation"], e["ref"]) for e in cards[0].closure] == [
        ("exception_of", "33 CFR 117.5(p1)"), ("exception_of", "33 CFR 117.31(b)"),
        *[("exception_of", f"33 CFR 117.31(b)({k})") for k in range(1, 5)]]
    assert [(e["relation"], e["ref"]) for e in cards[1].closure] == [
        ("cites", "33 CFR 117.31(a)")]
    assert all(c.closure == [] for c in cards[2:])
    alone = as_(store).rule_lookup(rule_id="33 CFR 117.1081(a)(1)").cards[0]
    assert [e["ref"] for e in alone.closure][:3] == ["33 CFR 117.5(p1)", "33 CFR 117.31(a)",
                                                     "33 CFR 117.31(b)"]
    assert all(c.closure == [] for c in as_(store).rule_lookup(rule_id="33 CFR 117.1081",
                                                                closure=False).cards)


def test_query_ranking_masks_before_the_cut(store):
    """The filters and the part are masks on the view's ranking: a query ranks the same
    cards in the same order whatever is masked out."""
    t = as_(store)
    every = t.rule_lookup("designated representative area vessel", include_superseded=True,
                          limit=UNIT_LIMIT_MAX)
    part165 = t.rule_lookup("designated representative area vessel", include_superseded=True,
                            part="165", limit=UNIT_LIMIT_MAX)
    assert ids(part165) == [i for i in ids(every) if f"/{D165}" in i] and ids(part165)
    for form in ("33 CFR 165", "33 CFR part 165", "part 165", "165"):
        assert ids(t.rule_lookup("designated representative area vessel",
                                 include_superseded=True, part=form,
                                 limit=UNIT_LIMIT_MAX)) == ids(part165)
    assert t.rule_lookup("drawbridge", part="47 CFR 73").cards == []
    # M3: the excluded count covers the part's documents only
    assert t.rule_lookup("drawbridge").excluded_by_filter == 1         # the old 117 version
    assert t.rule_lookup("drawbridge", part="117").excluded_by_filter == 1
    assert t.rule_lookup("drawbridge", part="165").excluded_by_filter == 0
    assert t.rule_lookup("drawbridge", part="47 CFR 73").excluded_by_filter == 0
    assert t.rule_lookup("drawbridge", part="117", include_superseded=True
                         ).excluded_by_filter == 0
    r = as_(store, "user:acme-1").rule_lookup("designated representative", part="33 CFR 165")
    assert r.cards == [] and r.excluded_by_filter == 0
    assert as_(store, "user:acme-1").rule_lookup(rule_id="117.5", part="117"
                                                 ).excluded_by_filter == 1
    with pytest.raises(ToolError, match="bad part"):
        t.rule_lookup("drawbridge", part="IRM 21")
    one = t.rule_lookup("designated representative area vessel", include_superseded=True,
                        limit=1)
    assert ids(one) == ids(every)[:1]


# -- define ------------------------------------------------------------------------------------

def test_define_ranks_by_context_then_narrowest(store):
    t = as_(store)
    r = t.define("designated representative", context="33 CFR 165.T01(b)")
    assert [s.scope["ref"] for s in r.senses] == ["33 CFR 165.T01", "33 CFR part 165"]
    # a context only the part sense holds puts it first
    r = t.define("designated representative", context="33 CFR 165.13(b)")
    assert [s.scope["ref"] for s in r.senses] == ["33 CFR part 165", "33 CFR 165.T01"]
    r = t.define("designated representative", context="§ 165.13(b)")
    assert [s.scope["ref"] for s in r.senses] == ["33 CFR part 165", "33 CFR 165.T01"]
    # a unit id as context; no context: narrowest first
    r = t.define("designated representative",
                 context=card("33 CFR 165.T01(c)", "67b9d94242a0", D165))
    assert [s.scope["ref"] for s in r.senses] == ["33 CFR 165.T01", "33 CFR part 165"]
    assert [s.scope["ref"] for s in t.define("Designated Representative").senses] == [
        "33 CFR 165.T01", "33 CFR part 165"]
    s = r.senses[0]
    text = Store.open(store.path).text(DOC_165)
    assert (s.term, s.doc_id, s.scope["kind"]) == ("designated representative", DOC_165,
                                                    "section")
    assert text[s.start:s.end] == s.definition and r.nearest == []


def test_define_reads_a_unit_id_context_of_every_type(store, tmp_path):
    """§7: a unit id as context stands for where that unit sits: a rule card its provision, a
    concept its scope, any other unit its document (and its eCFR section, IRM chapter or
    Phase 3 table section where it has one); a sense whose scope holds it ranks first."""
    t = as_(store)
    part, section = (f"concept/concept:33 CFR part 165:designated representative/"
                     f"0240f9d8899e/{D165}",
                     f"concept/concept:33 CFR 165.T01:designated representative/"
                     f"438ce2d7ef91/{D165}")
    refs = [s.scope["ref"] for s in t.define("designated representative", context=part).senses]
    assert refs == ["33 CFR part 165", "33 CFR 165.T01"]   # the part sense holds its own unit
    refs = [s.scope["ref"] for s in t.define("designated representative",
                                             context=section).senses]
    assert refs == ["33 CFR 165.T01", "33 CFR part 165"]
    # an IRM procedure and table record sit in the chapter the IRM senses are scoped to
    for unit in (PROC_1, f"table_record/IRM 21.4.1.3 table 1/d26298dd2b40/{IRM16}"):
        assert t.define("RIU", context=unit).senses[0].scope["ref"] == "IRM 21.4.1"
    # bench: two documents define "regulated navigation area"; a unit of either document as
    # context puts that document's sense first
    from tests.store.tables_fixtures import _doc
    from tests.store.units_fixtures import BENCH_CONFIG, FIXTURES, UNITS_DOCS

    raw = (FIXTURES / "bench_runbook.md").read_bytes() + (
        b"\nDo not drain a gateway inside a Regulated Navigation Area (RNA) window.\n")
    uri = f"{BENCH_CONFIG['documents']['url']}#row=1&doc_id=dsid_fixture_runbook"
    runbook = _doc(raw, "md", BENCH_CONFIG["revision"], uri)
    docs = [runbook if d.uri == uri else (d, r) for d, r in UNITS_DOCS]
    bench = make_units_built(tmp_path / "bench", docs, corpus="bench")
    b = as_(bench)
    senses = b.define("RNA").senses
    assert sorted(s.doc_id for s in senses) == sorted([runbook[0].doc_id, DOC_165])
    us = {u.unit_id: u for u in units_overlay.load_units(
        bench.path, units_overlay.load_units_manifest(
            bench.path, units_overlay.read_units_head(bench.path)))}
    proc = next(i for i, u in us.items() if u.type == "procedure"
                and u.doc_id == runbook[0].doc_id)
    assert b.define("RNA", context=proc).senses[0].doc_id == runbook[0].doc_id
    other = next(i for i, u in us.items() if u.type == "concept" and u.doc_id == DOC_165)
    assert b.define("RNA", context=other).senses[0].doc_id == DOC_165
    faq = next(i for i, u in us.items() if u.type == "faq")   # a third document: no sense
    assert [s.unit_id for s in b.define("RNA", context=faq).senses] == sorted(
        s.unit_id for s in senses)


def test_define_matches_labels_then_hidden_labels(store):
    t = as_(store)
    assert [s.term for s in t.define("RNA").senses] == ["Regulated navigation area"]
    assert [s.term for s in t.define("  regulated   NAVIGATION area. ").senses] == [
        "Regulated navigation area"]
    assert [s.term for s in t.define("RNAs").senses] == ["Regulated navigation area"]
    assert [s.term for s in t.define("regulated-navigation-areas").senses] == [
        "Regulated navigation area"]
    # in force by default; every version with include_superseded (same scope: by unit id)
    assert [s.doc_id for s in t.define("drawtender").senses] == [DOC_117_NEW]
    both = t.define("drawtenders", include_superseded=True).senses
    assert sorted(s.doc_id for s in both) == sorted([DOC_117_NEW, DOC_117_OLD])
    assert [s.unit_id for s in both] == sorted(s.unit_id for s in both)
    assert [s.doc_id for s in t.define("drawtender", as_of="2025-07-01").senses] == [
        DOC_117_OLD]


def _subpart_doc(date: str):
    """The 33 CFR 117 excerpt with "harbor tender" defined for the part (§ 117.4) and again
    for subpart B (§ 117.901(d))."""
    doc, raw = ecfr_117_doc(date)
    raw = raw.replace(b"<P><I>Drawtender.</I>",
                      b"<P><I>Harbor tender</I> means any tender of a drawbridge.</P>\n"
                      b"<P><I>Drawtender.</I>")
    raw = raw.replace(b"on signs visible to approaching vessels.</P>",
                      b"on signs visible to approaching vessels.</P>\n<P>(d) For the "
                      b"purposes of this subpart, <I>Harbor tender</I> means the person who "
                      b"attends the Harbor Avenue Bridge.</P>")
    from tests.store.tables_fixtures import _doc

    return _doc(raw, "xml", date, doc.uri)


def test_define_resolves_a_subpart_from_the_unit_in_force(tmp_path):
    """A bare canonical ref as context: the subpart comes from the visible card of that
    section in force, so a subpart-scoped sense holds a subpart B paragraph (Task 3 carry)."""
    store = make_units_store(tmp_path / "store", [_subpart_doc(uf.ECFR_NEW)])
    promote_units(store.path)
    t = tools.Tools(store.path)
    scopes = [s.scope["ref"] for s in t.define("harbor tender").senses]
    assert scopes == ["33 CFR part 117, subpart B", "33 CFR part 117"]      # narrowest first
    for ctx in ("33 CFR 117.901(a)", "117.901", "33 CFR 117.821(b)"):        # subpart B
        assert [s.scope["ref"] for s in t.define("harbor tender", context=ctx).senses] == scopes
    for ctx in ("33 CFR 117.5", "33 CFR 117.31(b)(2)"):                      # subpart A
        assert [s.scope["ref"] for s in t.define("harbor tender", context=ctx).senses] == \
            scopes[::-1]
    unit = t.rule_lookup(rule_id="33 CFR 117.901(a)").cards[0].unit_id
    assert [s.scope["ref"] for s in t.define("harbor tender", context=unit).senses] == scopes


def test_unknown_term_returns_nearest_visible_labels(store):
    r = as_(store).define("drawtendr")
    assert r.senses == [] and r.nearest == ["Drawtender", "Drawbridge", "RTN", "RNA", "DDIA"]
    # ties by label: RTN, RNA and DDIA are all far; the order is (distance, label)
    from adr_store.tables.parse import base_key
    from adr_store.tools import _edit_distance

    d = [_edit_distance("drawtendr", base_key(x)) for x in r.nearest]
    assert d == sorted(d) and d[0] == 1
    riu = as_(store, "user:globex-0").define("RIUs")              # a hidden label: a sense
    assert [s.term for s in riu.senses] == ["Refund Inquiry Unit"] and riu.nearest == []
    g = as_(store, "user:globex-0").define("drawtendr")
    assert g.senses == [] and set(g.nearest) <= {
        "Direct Deposit Indicator Account", "DDIA", "Refund Inquiry Unit", "RIU",
        "Routing Transit Number", "RTN"} and len(g.nearest) == 5
    assert as_(store).define("").nearest and as_(store).define("").senses == []


# -- procedures ----------------------------------------------------------------------------------

def test_procedure_lookup_catalog_and_views(store):
    t = as_(store)
    cat = t.procedure_lookup("refund research")
    assert [e["unit_id"] for e in cat.catalog] == [PROC_1, PROC_2]
    assert [e["rank"] for e in cat.catalog] == [1, 2] and cat.rendering is None
    e = cat.catalog[0]
    assert (e["canonical_ref"], e["title"], e["when_to_use"], e["doc_id"]) == (
        "IRM 21.4.1.3.1", "Missing Refund Research", None, DOC_IRM)
    assert e["score"] > cat.catalog[1]["score"] > 0
    assert [x["unit_id"] for x in t.procedure_lookup("refund research", limit=1).catalog] == [
        PROC_1]
    units = units_overlay.load_units(store.path, units_overlay.load_units_manifest(
        store.path, units_overlay.read_units_head(store.path)), "procedure")
    unit = next(u for u in units if u.unit_id == PROC_1)
    body = ProcedureBody.model_validate(unit.body)
    for given in (PROC_1, "IRM 21.4.1.3.1"):
        skill = t.procedure_lookup(id=given, view="skill")
        assert skill.catalog is None and skill.id == given and skill.view == "skill"
        meta, steps = parse_skill(skill.rendering)                     # SKILL.md parses
        assert steps == len(body.steps) and meta["description"] == "Missing Refund Research"
        mermaid = t.procedure_lookup(id=given, view="mermaid").rendering
        assert parse_mermaid(mermaid) == ir_graph(body)                 # Mermaid round-trips
        ir = t.procedure_lookup(id=given, view="ir").rendering
        assert ir == unit.body and validate_ir(ProcedureBody.model_validate(ir)) == []
        one = t.procedure_lookup(id=given)
        assert one.catalog == [{**cat.catalog[0], "score": None}] and one.rendering is None
    for bad in (dict(), dict(task="x", id=PROC_1), dict(task="refund", view="skill")):
        with pytest.raises(ToolError, match="give|renders one procedure"):
            t.procedure_lookup(**bad)
    with pytest.raises(ToolError, match="view must be one of catalog, skill, mermaid, ir"):
        t.procedure_lookup(id=PROC_1, view="pdf")
    # a unit of another type is no procedure
    with pytest.raises(ToolError, match=f"^{UNKNOWN_PROCEDURE}$"):
        t.procedure_lookup(id=A_2, view="ir")


# -- unit_search ----------------------------------------------------------------------------------

def test_unit_search_types_hits_and_text(store, monkeypatch):
    t = as_(store)
    r = t.unit_search("refund")
    assert r.types == ["concept", "procedure", "rule_card", "table_record"]
    assert {h["type"] for h in r.hits} == {"concept", "procedure", "table_record"}
    assert [h["rank"] for h in r.hits] == list(range(1, len(r.hits) + 1))
    scores = [h["score"] for h in r.hits]
    assert scores == sorted(scores, reverse=True)
    text = Store.open(store.path).text(DOC_IRM)
    for h in r.hits:
        assert h["doc_id"] == DOC_IRM and 0 <= h["start"] < h["end"] <= len(text)
        assert h["status"] == "validated" and not h["truncated"]
        if h["type"] == "table_record":
            assert h["pointer"]["kind"] == "span" and h["pointer"]["doc_id"] == DOC_IRM
        else:
            assert h["pointer"] is None
    concept = next(h for h in r.hits if h["type"] == "concept")
    assert concept["text"] == text[concept["start"]:concept["end"]]
    tr = t.unit_search("refund", ["table_record", "table_record"])
    assert tr.types == ["table_record"] and {h["type"] for h in tr.hits} == {"table_record"}
    cards = t.unit_search("drawbridge notice", ["rule_card"], limit=3)
    assert len(cards.hits) == 3 and all(h["doc_id"] == DOC_117_NEW for h in cards.hits)
    assert cards.hits[0]["text"] == text_of(store, cards.hits[0])
    assert t.unit_search("drawbridge", ["faq"]).hits == []          # no such type in gov
    for bad in ([], ["rules"], "rule_card", [1]):
        with pytest.raises(ToolError, match="types must be a non-empty list of unit types"):
            t.unit_search("x", bad)
    # a long reader text is cut, and the hit says so
    monkeypatch.setattr(tools, "HIT_TEXT_MAX", 20)
    long = t.unit_search("drawbridge notice", ["rule_card"], limit=1).hits[0]
    assert long["truncated"] and len(long["text"]) == 20
    assert text_of(store, long).startswith(long["text"])


def text_of(store, hit) -> str:
    return Store.open(store.path).text(hit["doc_id"])[hit["start"]:hit["end"]]


def test_large_procedures_are_rendered_whole(store, monkeypatch):
    """A procedure body of 45-50 KB (the largest real IRM units) is returned whole as IR, and
    its SKILL.md body stays within the spec's 500 lines (§9.2): no silent cut."""
    from adr_store.units.render import SKILL_BODY_MAX_LINES

    t = as_(store)
    t.unit_search("refund")                                  # load the build
    head = units_overlay.read_units_head(store.path)
    us = next(v for k, v in tools._UNIT_SETS.items() if k[:2] == (str(store.path.resolve()), head))
    unit = us.units[PROC_1]
    step = unit.body["steps"][0]
    big_steps = [{**step, "id": f"b{k}", "text": "Research the account and record " * 8,
                  "next": [{"to": f"b{k + 1}", "guard": None}]} for k in range(180)]
    big_steps.append({**unit.body["steps"][-1], "id": "b180", "next": []})
    big = unit.model_copy(update={"body": {**unit.body, "steps": big_steps,
                                           "tests": [{"condition": None, "edge": None,
                                                      "steps": [s["id"] for s in big_steps]}]}})
    assert len(json.dumps(big.body)) > 45_000
    monkeypatch.setitem(us.units, PROC_1, big)
    ir = t.procedure_lookup(id=PROC_1, view="ir").rendering
    assert ir == big.body and validate_ir(ProcedureBody.model_validate(ir)) == []
    skill = t.procedure_lookup(id=PROC_1, view="skill").rendering
    assert parse_skill(skill)[1] == 181
    assert len(skill.split("\n")) < SKILL_BODY_MAX_LINES


# -- handles ------------------------------------------------------------------------------------

def test_a_phase3_handle_without_units(units_built):                        # Review Focus 4
    current = as_(units_built).search("drawbridge").handle
    assert current["units"] == units_overlay.read_units_head(units_built.path)
    old = {k: v for k, v in current.items() if k not in ("units", "unit_index")}
    assert as_(units_built).search("drawbridge", handle=old).hits
    assert as_(units_built).search("drawbridge", handle=old).handle == {
        **old, "units": None, "unit_index": None}
    calls = (lambda t: t.rule_lookup("drawbridge", handle=old),
             lambda t: t.rule_lookup(rule_id="117.5", handle=old),
             lambda t: t.define("drawtender", handle=old),
             lambda t: t.procedure_lookup("refund", handle=old),
             lambda t: t.unit_search("refund", handle=old))
    for call in calls:
        with pytest.raises(ToolError) as e:
            call(as_(units_built))
        assert str(e.value) == NO_HANDLE_UNITS
    # a Phase 2 handle (neither tables nor units) validates too
    older = {k: v for k, v in old.items() if k != "tables"}
    assert as_(units_built).read(DOC_117_NEW, 0, 10, handle=older).handle == {
        **older, "tables": None, "units": None, "unit_index": None}


def test_units_of_an_older_snapshot_are_refused(units_built):
    """A new content snapshot: units/HEAD names a build of the old one, so the unit tools
    refuse (NO_UNITS) and never serve it; a handle of the old snapshot still replays."""
    t = as_(units_built)
    before = t.rule_lookup(rule_id="117.5")
    head = units_overlay.read_units_head(units_built.path)
    s = Store.create(units_built.path)
    for document, raw in UNITS_DOCS[:3]:                     # 165 and IRM dropped
        s.add(document, raw)
    s.commit()
    config = units_built.path.parent / f"{units_built.path.name}-acl"
    acl.sync(units_built.path, config / "directory.json", config / "policy.json",
             clock=lambda: T0)
    new = Store.open(units_built.path).snapshot_id
    assert new != before.snapshot
    assert (units_built.path / "units" / "HEAD").read_text().strip() == head   # HEAD unmoved
    for call in (lambda: t.rule_lookup(rule_id="117.5"), lambda: t.define("drawtender"),
                 lambda: t.procedure_lookup("refund"), lambda: t.unit_search("x")):
        with pytest.raises(ToolError) as e:
            call()
        assert str(e.value) == NO_UNITS.format(new[:12])
    assert t.read(DOC_117_NEW, 0, 5).handle["units"] is None      # the earlier tools: no units
    assert t.rule_lookup(rule_id="117.5", handle=before.handle) == before


def test_every_result_carries_a_handle_with_units_and_replays(units_built):
    t = as_(units_built)
    head = units_overlay.read_units_head(units_built.path)
    results = [t.define("designated representative", context="33 CFR 165.T01(b)"),
               t.rule_lookup("drawbridge open"), t.rule_lookup(rule_id="33 CFR 117.1081"),
               t.procedure_lookup("refund research"),
               t.procedure_lookup(id=PROC_1, view="skill"), t.unit_search("refund")]
    calls = [lambda h: t.define("designated representative", context="33 CFR 165.T01(b)",
                                handle=h),
             lambda h: t.rule_lookup("drawbridge open", handle=h),
             lambda h: t.rule_lookup(rule_id="33 CFR 117.1081", handle=h),
             lambda h: t.procedure_lookup("refund research", handle=h),
             lambda h: t.procedure_lookup(id=PROC_1, view="skill", handle=h),
             lambda h: t.unit_search("refund", handle=h)]
    now = handles.resolve(units_built.path, None).handle.model_dump()
    assert now["units"] == head and set(now) == set(handles.COMPONENTS)
    for res, call in zip(results, calls, strict=True):
        assert res.units == head and res.handle == now
        assert call(res.handle) == res
        assert call(handles.Handle(**res.handle)) == res
    # the earlier tools carry the same handle
    assert t.search("drawbridge").handle == now and t.read(DOC_117_NEW).handle == now
    units_overlay.units_manifest_path(units_built.path, head).unlink()
    for call in calls:
        with pytest.raises(ToolError, match="^handle no longer available: units$"):
            call(results[0].handle)
    with pytest.raises(ToolError, match="^handle no longer available: units$"):
        t.search("drawbridge", handle=results[0].handle)
    with pytest.raises(ToolError) as e:            # without a handle: no current units
        t.unit_search("refund")
    assert str(e.value) == NO_UNITS.format(results[0].snapshot[:12])


def test_a_handle_naming_units_of_another_snapshot_is_bad(units_built, tmp_path):
    other = make_units_built(tmp_path / "other", UNITS_DOCS[:2])
    uid = units_overlay.read_units_head(other.path)
    m = units_overlay.units_manifest_path(other.path, uid)
    dst = units_built.path / "units" / m.parent.name
    dst.mkdir(parents=True)
    for f in m.parent.iterdir():
        (dst / f.name).write_bytes(f.read_bytes())
    h = {**as_(units_built).unit_search("x").handle, "units": uid}
    with pytest.raises(ToolError, match=rf"^bad handle: units {uid[:12]} is for snapshot "
                                        rf"{m.parent.name[:12]}$"):
        as_(units_built).unit_search("x", handle=h)


# -- the eight earlier tools --------------------------------------------------------------------

def earlier_calls():
    return [lambda t: t.search("drawbridge"), lambda t: t.search("refund", top=3),
            lambda t: t.read(DOC_117_NEW), lambda t: t.read(DOC_165, 0, 40),
            lambda t: t.read(DOC_117_OLD, filters={"include_superseded": True}),
            lambda t: t.grep("Coast"), lambda t: t.grep("bridge", doc=DOC_117_NEW),
            lambda t: t.search_tools("x"), lambda t: t.load_tool("abcdefgh"),
            lambda t: t.describe_tables(), lambda t: t.query_table("fr_documents"),
            lambda t: t.sql("SELECT 1"), lambda t: t.read("0" * 64)]


def test_the_eight_earlier_tools_are_unchanged(tmp_path):
    """Before and after a units build and its promotion, the eight earlier tools give the same
    results for every caller, except the handle's new `units` part."""
    path = tmp_path / "store"
    make_units_store(path, rules=uf.UNITS_ACL_RULES)
    tools.Tools(path).index("p1-struct", lexical_only=True)
    store = Store.open(path)

    def run():
        out = []
        for user in UNITS_USERS:
            for call in earlier_calls():
                res = outcome(call, as_(store, user))
                out.append(("error", str(res)) if isinstance(res, Exception) else res.to_dict())
        return out

    before = run()
    head = promote_units(path)
    after = run()
    assert len(before) == len(after) == len(UNITS_USERS) * len(earlier_calls())
    assert sum(isinstance(r, dict) for r in before) > 20
    for b, a in zip(before, after, strict=True):
        if isinstance(b, dict):
            assert b["handle"]["units"] is None and a["handle"]["units"] == head
            assert {**b, "handle": None} == {**a, "handle": None}
        else:
            assert a == b


# -- logs, denial and arguments -----------------------------------------------------------------

def test_log_lines_carry_units(units_built):
    t = as_(units_built, "user:acme-0")
    head = units_overlay.read_units_head(units_built.path)
    t.define("drawtender")
    t.rule_lookup(rule_id="117.5", as_of="2026-07-01")
    t.procedure_lookup("refund")
    t.unit_search("drawbridge", ["rule_card"])
    with pytest.raises(ToolError):
        t.rule_lookup(rule_id="nope")
    lines = log_lines(units_built)[-5:]
    assert [ln["tool"] for ln in lines] == ["define", "rule_lookup", "procedure_lookup",
                                            "unit_search", "rule_lookup"]
    for ln in lines:
        assert ln["units"] == head and ln["acl_decision"] == "allowed"
        assert ln["caller"] == "user:acme-0" and ln["principals"] and ln["view"]
        assert ln["applicability"] is not None and ln["filters"]["include_superseded"] is False
        assert ln["handle"] is None or ln["handle"]["units"] == head
    assert lines[1]["filters"]["as_of"] == "2026-07-01"
    assert lines[1]["args"] == {"query": None, "rule_id": "117.5", "part": None,
                                "as_of": "2026-07-01", "include_superseded": False,
                                "closure": True, "limit": 10}
    assert lines[1]["results"] == [card("33 CFR 117.5(p1)", "033f795bb179")]
    assert lines[3]["args"]["types"] == ["rule_card"]
    assert lines[4]["error"] == UNKNOWN_RULE and lines[4]["results"] == []
    # a denied call logs its decision and no units
    with pytest.raises(AccessDenied):
        as_(units_built, "user:ghost").define("drawtender")
    ln = log_lines(units_built)[-1]
    assert ln["acl_decision"] == "denied:F4" and ln["units"] is None and ln["results"] == []


def test_denied_callers_get_nothing(units_built):
    calls = [lambda t: t.define("drawtender"), lambda t: t.rule_lookup(rule_id="117.5"),
             lambda t: t.rule_lookup("drawbridge"), lambda t: t.procedure_lookup("refund"),
             lambda t: t.procedure_lookup(id=PROC_1, view="ir"),
             lambda t: t.unit_search("refund")]
    for call in calls:
        with pytest.raises(AccessDenied) as e:
            call(as_(units_built, "user:ghost"))
        assert e.value.code == "F4"
    stale = tools.Tools(units_built.path, acl=True, caller="user:auditor",
                        clock=lambda: T0 + timedelta(days=2))
    for call in calls:
        with pytest.raises(AccessDenied) as e:
            call(stale)
        assert e.value.code == "F3"


def test_arguments_are_checked(store):
    t = as_(store)
    refusals = [
        (lambda: t.define(3), "term must be a string, got int"),
        (lambda: t.define("x", context=["a"]), "context must be a string, got list"),
        (lambda: t.define("x", include_superseded="yes"), "bad filters"),
        (lambda: t.define("x", as_of="last year"), "bad filters"),
        (lambda: t.rule_lookup(), "give a query or a rule_id, not both"),
        (lambda: t.rule_lookup("x", rule_id="117.5"), "give a query or a rule_id, not both"),
        (lambda: t.rule_lookup(rule_id=5), "rule_id must be a string, got int"),
        (lambda: t.rule_lookup("x", closure="no"), "closure must be true or false"),
        (lambda: t.rule_lookup("x", limit=0), f"limit must be between 1 and {UNIT_LIMIT_MAX}"),
        (lambda: t.rule_lookup("x", limit=UNIT_LIMIT_MAX + 1), "limit must be between"),
        (lambda: t.rule_lookup("x", limit=True), "limit must be between"),
        (lambda: t.procedure_lookup("x", limit="5"), "limit must be between"),
        (lambda: t.procedure_lookup(id=7), "id must be a string, got int"),
        (lambda: t.unit_search(None), "query must be a string, got NoneType"),
        (lambda: t.unit_search("x", limit=1.5), "limit must be between"),
    ]
    for call, message in refusals:
        with pytest.raises(ToolError, match=re.escape(message)):
            call()


def test_table_record_pointers_are_accepted_by_query_table(built_units):
    """A Phase 3 table record found by `unit_search` points at rows `query_table` reads."""
    store, gov, _ = built_units
    from adr_store.units.gate import units_gate

    assert units_gate(store.path, gov.units_id, [], 0, hit=None).promoted
    t = uf.as_auditor(store)
    hits = t.unit_search("drawbridge bridges Smith River", ["table_record"], limit=50).hits
    tables_hits = [h for h in hits if h["pointer"]["kind"] == "tables"]
    assert tables_hits
    for h in tables_hits:
        p = h["pointer"]
        assert p["tables_id"] == t.describe_tables().tables
        assert t.query_table(p["table"], p["filters"], "count").count > 0


built_units = uf.built_units
units_store_with_tables = uf.units_store_with_tables


# -- the pinned unit-index tuning (spec P42; Task 12 carry A) ------------------------------------

def _tuning_file(tmp_path, monkeypatch, gov: dict, name: str = "tuning.json"):
    """Point the tuning file at a copy of the committed one with `gov` as the gov entry."""
    from adr_store.units import index as ui

    path = tmp_path / name
    data = json.loads(ui.TUNING_PATH.read_text(encoding="utf-8"))
    data["gov"] = gov
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(ui, "TUNING_PATH", path)
    return path


def _gov(w: float = 1.0, **rule_card_fields) -> dict:
    from adr_store.units import index as ui

    entry = ui.default_tuning("gov")
    entry["weights"]["rule_card"].update(rule_card_fields)
    return {**entry, "w": w}


RANKING_QUERY = "drawbridge open notice signal"


def test_a_retune_changes_the_handle_and_pins_each_entry(units_built, tmp_path, monkeypatch):
    from adr_store.units import index as ui

    head = units_overlay.read_units_head(units_built.path)
    first, second = _gov(), _gov(body=3, title=2)
    _tuning_file(tmp_path, monkeypatch, first)
    a = as_(units_built).rule_lookup(RANKING_QUERY)
    _tuning_file(tmp_path, monkeypatch, second, "tuning-2.json")
    b = as_(units_built).rule_lookup(RANKING_QUERY)
    assert a.handle["unit_index"] == ui.tuning_id(first)
    assert b.handle["unit_index"] == ui.tuning_id(second) != a.handle["unit_index"]
    assert a.handle["units"] == b.handle["units"] == head
    for entry in (first, second):           # each pinned, content-addressed, under its units id
        pin = units_built.path / "units-index" / head / f"tuning-{ui.tuning_id(entry)}.json"
        assert hashlib.sha256(pin.read_bytes()).hexdigest() == ui.tuning_id(entry)
        assert json.loads(pin.read_bytes()) == ui.check_tuning(entry)
    # a Phase 2 call names the tuning in force once it is pinned
    assert as_(units_built).search("drawbridge").handle == b.handle


def test_an_old_handle_replays_with_its_pinned_weights(units_built, tmp_path, monkeypatch):
    from adr_store.units import index as ui
    from adr_store.units.overlay import load_units, load_units_manifest

    head = units_overlay.read_units_head(units_built.path)
    m = load_units_manifest(units_built.path, head)
    units = load_units(units_built.path, m)
    docs = ui.unit_docs(units, [u for u in units if u.type == "concept"])
    view = frozenset(visible(units_built, "user:auditor"))
    old_doc = {u.doc_id for u in units if u.applicability.status == "superseded"}

    def ranking(entry):  # the unit index itself, with this tuning: the oracle
        idx = ui.UnitIndex.build(units_built.path, head, docs, None, entry, install=False)
        return [i for i, _ in idx.search(RANKING_QUERY, types=("rule_card",), view=view,
                                         admitted=view - old_doc, k=10)]

    first, second = _gov(), _gov(body=3, title=3, ref=2)
    assert ranking(first) != ranking(second)              # the re-tune changes the ranking
    _tuning_file(tmp_path, monkeypatch, first)
    a = as_(units_built).rule_lookup(RANKING_QUERY)
    assert ids(a) == ranking(first)
    _tuning_file(tmp_path, monkeypatch, second, "tuning-2.json")
    assert ids(as_(units_built).rule_lookup(RANKING_QUERY)) == ranking(second)
    again = as_(units_built).rule_lookup(RANKING_QUERY, handle=a.handle)
    assert again == a and ids(again) == ranking(first)
    # a handle with a null unit_index (saved before Task 12) runs the uniform lexical index
    older = {**a.handle, "unit_index": None}
    assert ids(as_(units_built).rule_lookup(RANKING_QUERY, handle=older)) == \
        ranking(ui.default_tuning("gov"))


def test_a_missing_pinned_entry_refuses(units_built, tmp_path, monkeypatch):
    from adr_store.units import index as ui

    _tuning_file(tmp_path, monkeypatch, _gov(body=2))
    a = as_(units_built).rule_lookup(RANKING_QUERY)
    pin = ui.pin_path(units_built.path, a.handle["units"], a.handle["unit_index"])
    pin.write_bytes(pin.read_bytes() + b" ")                       # damaged: not its hash
    for call in (lambda h: as_(units_built).rule_lookup(RANKING_QUERY, handle=h),
                 lambda h: as_(units_built).unit_search("refund", handle=h),
                 lambda h: as_(units_built).search("drawbridge", handle=h)):
        with pytest.raises(ToolError, match="^handle no longer available: unit_index$"):
            call(a.handle)
    pin.unlink()
    with pytest.raises(ToolError, match="^handle no longer available: unit_index$"):
        as_(units_built).define("drawtender", handle=a.handle)
    # a unit index without units is a bad handle; an unknown one is gone
    with pytest.raises(ToolError, match="^bad handle: a unit index without units"):
        as_(units_built).search("drawbridge", handle={**a.handle, "units": None})
    with pytest.raises(ToolError, match="^handle no longer available: unit_index$"):
        as_(units_built).search("drawbridge", handle={**a.handle, "unit_index": "0" * 64})
    # without a handle the current tuning is pinned again
    assert as_(units_built).rule_lookup(RANKING_QUERY).handle == a.handle and pin.is_file()


def test_dense_below_w1_and_lexical_at_w1(units_built, tmp_path, monkeypatch):
    """The unit tools build dense vectors through the embedding cache when the pinned `w` is
    below 1 (the fake model here, C8), and never make an embedding cache at `w = 1.0`."""
    from adr_store.units import index as ui
    from tests.store.test_retrieval import fake_cache

    made: list = []

    def no_cache(*a, **kw):
        raise AssertionError("an embedding cache was made at w = 1.0")

    monkeypatch.setattr(tools, "make_embedding_cache", no_cache)
    _tuning_file(tmp_path, monkeypatch, _gov(1.0))
    lex = as_(units_built).rule_lookup(RANKING_QUERY)
    head = lex.handle["units"]
    assert not any((units_built.path / "units-index" / head).glob("dense-*"))

    def cache(*a, **kw):
        made.append(fake_cache(tmp_path / "emb"))
        return made[-1]

    monkeypatch.setattr(tools, "make_embedding_cache", cache)
    _tuning_file(tmp_path, monkeypatch, _gov(0.5), "tuning-2.json")
    dense = as_(units_built).rule_lookup(RANKING_QUERY)
    assert made and made[-1].model().passage.calls                # documents embedded
    assert any((units_built.path / "units-index" / head).glob("dense-*/vectors.npy"))
    # the ranking is the P41 fusion of BM25 and the fake vectors at w = 0.5
    from adr_store.units.overlay import load_units, load_units_manifest

    units = load_units(units_built.path, load_units_manifest(units_built.path, head))
    docs = ui.unit_docs(units, [u for u in units if u.type == "concept"])
    view = frozenset(visible(units_built, "user:auditor"))
    old_doc = {u.doc_id for u in units if u.applicability.status == "superseded"}
    idx = ui.UnitIndex.build(units_built.path, head, docs, fake_cache(tmp_path / "emb2"),
                             _gov(0.5))
    want = [i for i, _ in idx.search(RANKING_QUERY, types=("rule_card",), view=view,
                                     admitted=view - old_doc, k=10)]
    assert ids(dense) == want and dense.handle["unit_index"] == ui.tuning_id(_gov(0.5))
