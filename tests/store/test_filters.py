"""Applicability filters in `StoreIndex` and the tools (Phase 2 spec §4.4, §6.1, §12
Applicability: "a missing overlay refuses `as_of`"). Gov-shaped fixtures from the applicability
tests, lexical-only indexes or the fake embedder; nothing reads `data/` or `.cache/`."""

import itertools
import json
from datetime import date, timedelta

import pytest

from adr_store import applicability as ap
from adr_store import tools
from adr_store.applicability import Filters, admits, exclusion_reason
from adr_store.cli import main
from adr_store.retrieval import Settings, StoreIndex
from tests.store.test_applicability import (
    FINAL,
    GOV_CONFIG,
    IRM,
    LOOSE,
    PROPOSED,
    V2024,
    V2025,
    V2026,
    doc_id,
    env,
    make_store,
)
from tests.store.test_retrieval import fake_cache

NO_OVERLAY = "no applicability overlay; run `adr applicability derive`"
QUERY = "vessels"
APPLIES = r"applies to \w+ vessels"
D2025, D2026 = date(2025, 6, 30), date(2026, 6, 30)


def derive(store) -> str:
    overlay, _ = ap.derive(store, GOV_CONFIG)
    oid, _ = ap.write_overlay(store.path, overlay)
    return oid


@pytest.fixture
def bare(tmp_path):
    """A gov-shaped store without an overlay, with an active lexical-only index."""
    s = make_store(tmp_path / "store")
    tools.Tools(s.path).index("p1-struct", lexical_only=True)
    return s


@pytest.fixture
def store(bare):
    """The same store with its applicability overlay."""
    derive(bare)
    return bare


def phase1_index(store) -> StoreIndex:
    return StoreIndex.build(store, Settings(w_bc=0), dense=False)


def hits(res) -> list[tuple[str, float]]:
    return [(h.chunk_id, h.score) for h in res.hits]


def log_lines(store) -> list[dict]:
    path = store.path / "log" / "retrieval.jsonl"
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]


def grep_words(res) -> list[str]:
    return [m.match.split()[2] for m in res.matches]


# -- the reason a document is excluded ----------------------------------------------------

ENVELOPES = [
    env(), env(superseded_by="e" * 64, valid_from=D2025, valid_to=D2026, status="codified",
               jurisdiction="US-federal", authority_tier=1),
    env(valid_from=D2025, status="proposed_rule", jurisdiction="US-federal", authority_tier=4),
    env(valid_from=D2025, valid_to=D2026, status="temporary_rule", authority_tier=2),
    env(valid_from=D2026, status="final_rule", jurisdiction="US-federal", authority_tier=2),
]
FILTERS = [Filters(), Filters(include_superseded=True), Filters(as_of=D2025),
           Filters(as_of=D2026 - timedelta(days=1)), Filters(as_of=D2026),
           Filters(as_of=D2025, status=("proposed_rule",)), Filters(status=("final_rule",)),
           Filters(jurisdiction=("US-federal",)), Filters(max_tier=2),
           Filters(as_of=D2026, status=("final_rule", "temporary_rule"), max_tier=1)]


@pytest.mark.parametrize("e,f", list(itertools.product(ENVELOPES, FILTERS)))
def test_a_reason_is_given_exactly_when_the_filters_exclude(e, f):
    reason = exclusion_reason(e, f)
    assert (reason is None) == admits(e, f)
    assert reason is None or (reason and "\n" not in reason)


def test_the_reasons_name_the_rule_that_excluded():
    old = ENVELOPES[1]
    assert exclusion_reason(old, Filters()) == f"superseded by {'e' * 12}…"
    assert "not in force on 2026-06-30" in exclusion_reason(old, Filters(as_of=D2026))
    assert "valid_from unknown" in exclusion_reason(env(), Filters(as_of=D2026))
    assert "proposed_rule" in exclusion_reason(ENVELOPES[2], Filters(as_of=D2025))
    assert "status unknown" in exclusion_reason(env(), Filters(status=("final_rule",)))
    assert "jurisdiction unknown" in exclusion_reason(env(), Filters(jurisdiction=("X",)))
    assert "authority tier 4" in exclusion_reason(ENVELOPES[2], Filters(max_tier=2))


# -- no overlay ----------------------------------------------------------------------------


@pytest.mark.parametrize("f", [{"as_of": "2025-06-30"}, {"status": ["final_rule"]},
                               {"jurisdiction": ["US-federal"]}, {"max_tier": 2}])
def test_a_missing_overlay_refuses_filters_that_read_envelopes(bare, f):
    t = tools.Tools(bare.path)
    for call in (lambda: t.search(QUERY, filters=f), lambda: t.grep(APPLIES, filters=f),
                 lambda: t.read(doc_id(V2024), filters=f)):
        with pytest.raises(tools.ToolError) as e:
            call()
        assert str(e.value) == NO_OVERLAY
    assert [ln["error"] for ln in log_lines(bare)[-3:]] == [NO_OVERLAY] * 3


@pytest.mark.parametrize("f", [None, {}, {"include_superseded": True},
                               {"include_superseded": False}, Filters()])
def test_without_an_overlay_the_default_is_the_phase1_view(bare, f):
    t = tools.Tools(bare.path)
    res = t.search(QUERY, top=10, filters=f)
    assert hits(res) == phase1_index(bare).retrieve(QUERY, top=10)
    assert res.applicability is None and res.excluded_by_filter == 0
    assert res.filters == Filters.parse(f).to_dict()
    gr = t.grep(APPLIES, filters=f)
    assert sorted(grep_words(gr)) == ["middle", "new", "old"]
    assert gr.applicability is None and gr.excluded_by_filter == 0
    rd = t.read(doc_id(V2024), filters=f)
    assert rd.applicability is None and rd.filters == Filters.parse(f).to_dict()


# -- search --------------------------------------------------------------------------------


def test_with_an_overlay_include_superseded_is_the_phase1_ranking(store):
    t = tools.Tools(store.path)
    idx = phase1_index(store)
    for q in (QUERY, "the draw opens on signal", "rule effective", "zzz"):
        for top in (1, 10, 100):
            res = t.search(q, top=top, filters={"include_superseded": True})
            assert hits(res) == idx.retrieve(q, top=top)
            assert res.excluded_by_filter == 0 and res.applicability is not None


def test_default_search_excludes_superseded_documents_before_the_cut(store, monkeypatch):
    oid = derive(store)  # the same bytes again: the same id
    t = tools.Tools(store.path)
    idx = phase1_index(store)
    allowed = frozenset(store.doc_ids()) - {doc_id(V2024), doc_id(V2025)}
    seen = []
    real = StoreIndex.retrieve

    def spy(self, *a, **kw):
        seen.append(kw.get("allowed_docs"))
        return real(self, *a, **kw)

    monkeypatch.setattr(StoreIndex, "retrieve", spy)
    res = t.search(QUERY, top=10)
    assert seen == [allowed]
    assert hits(res) == idx.retrieve(QUERY, top=10, allowed_docs=allowed)
    assert {h.doc_id for h in res.hits} & {doc_id(V2024), doc_id(V2025)} == set()
    assert doc_id(V2026) in {h.doc_id for h in res.hits}
    assert res.applicability == oid and res.excluded_by_filter == 2
    assert res.filters == Filters().to_dict()
    # nothing excluded: the Phase 1 call itself, no mask
    seen.clear()
    t.search(QUERY, filters={"include_superseded": True})
    assert seen == [None]


def test_as_of_boundaries_through_search(store):
    t = tools.Tools(store.path)
    ecfr = {doc_id(V2024): "old", doc_id(V2025): "middle", doc_id(V2026): "new"}

    def versions(as_of):
        res = t.search(QUERY, top=100, filters={"as_of": as_of.isoformat()})
        return sorted(ecfr[h.doc_id] for h in {h.doc_id: h for h in res.hits}.values()
                      if h.doc_id in ecfr), res

    assert versions(D2025)[0] == ["middle"]  # D = valid_from: in
    assert versions(D2025 - timedelta(days=1))[0] == ["old"]
    assert versions(D2026 - timedelta(days=1))[0] == ["middle"]
    assert versions(D2026)[0] == ["new"]  # D = valid_to of the middle version: out
    assert versions(date(2024, 6, 26))[0] == []  # before the first version
    _, res = versions(D2025)
    allowed, excluded = ap.load_overlay(store.path, store.snapshot_id).allowed_docs(
        store.doc_ids(), Filters(as_of=D2025))
    assert res.excluded_by_filter == excluded == len(store.doc_ids()) - len(allowed)
    assert {h.doc_id for h in res.hits} <= allowed


def test_status_jurisdiction_and_tier_filters_through_search(store):
    t = tools.Tools(store.path)
    a = ap.load_overlay(store.path, store.snapshot_id)
    idx = phase1_index(store)
    for f in ({"status": ["proposed_rule"]}, {"jurisdiction": ["US-federal"]},
              {"max_tier": 1}, {"max_tier": 3, "include_superseded": True},
              {"as_of": "2024-04-01", "status": ["proposed_rule", "final_rule"]}):
        allowed, excluded = a.allowed_docs(store.doc_ids(), Filters.parse(f))
        res = t.search("rule", top=20, filters=f)
        assert hits(res) == idx.retrieve("rule", top=20, allowed_docs=allowed)
        assert res.excluded_by_filter == excluded
    res = t.search("rule", filters={"max_tier": 1})
    assert doc_id(LOOSE) not in {h.doc_id for h in res.hits}  # unknown tier never matches


def test_bad_filters_are_refused_and_logged(store):
    t = tools.Tools(store.path)
    for bad in ({"as_of": "June 2025"}, {"colour": "red"}, {"max_tier": 9}, "default"):
        with pytest.raises(tools.ToolError, match="as_of|unknown key|max_tier|object"):
            t.search(QUERY, filters=bad)
    assert all("error" in ln for ln in log_lines(store)[-4:])


def test_filters_with_unknown_keys_of_mixed_types_are_named(store):
    t = tools.Tools(store.path)
    with pytest.raises(tools.ToolError) as e:
        t.search(QUERY, filters={1: True, "colour": "red", None: 0, "as_of": None})
    assert str(e.value) == ("bad filters: unknown key(s) 'colour', 1, None; known: "
                            "include_superseded, as_of, status, jurisdiction, max_tier")
    assert log_lines(store)[-1]["error"] == str(e.value)


def test_a_dense_search_masks_both_channels(store, monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "make_embedding_cache",
                        lambda path=None, *, threads=1: fake_cache(tmp_path / "emb"))
    t = tools.Tools(store.path)
    t.index("p1-struct", weight=0.4)
    idx = StoreIndex.build(store, Settings(w_bc=0), fake_cache(tmp_path / "emb"))
    a = ap.load_overlay(store.path, store.snapshot_id)
    for f in (None, {"as_of": "2025-07-01"}, {"include_superseded": True}):
        allowed, excluded = a.allowed_docs(store.doc_ids(), Filters.parse(f))
        res = tools.Tools(store.path).search(QUERY, top=10, filters=f)
        want = idx.retrieve(QUERY, w=0.4, top=10,
                            allowed_docs=None if excluded == 0 else allowed)
        assert hits(res) == want and res.excluded_by_filter == excluded


# -- grep ----------------------------------------------------------------------------------


def test_grep_scans_only_admitted_documents(store, monkeypatch):
    sent = []
    real = tools._GrepWorker.scan

    def spy(self, pattern, flags, limit, docs):
        sent.extend(d for d, _ in docs)
        return real(self, pattern, flags, limit, docs)

    monkeypatch.setattr(tools._GrepWorker, "scan", spy)
    t = tools.Tools(store.path)
    res = t.grep(APPLIES)
    assert grep_words(res) == ["new"] and res.excluded_by_filter == 2
    assert sent == sorted(set(store.doc_ids()) - {doc_id(V2024), doc_id(V2025)})
    assert sorted(grep_words(t.grep(APPLIES, filters={"include_superseded": True}))) == [
        "middle", "new", "old"]
    assert grep_words(t.grep(APPLIES, filters={"as_of": "2025-06-30"})) == ["middle"]
    assert grep_words(t.grep(APPLIES, filters={"as_of": "2026-06-30"})) == ["new"]
    assert grep_words(t.grep(APPLIES, filters={"as_of": "2024-06-26"})) == []


def test_a_doc_scoped_grep_of_an_excluded_document_is_refused_with_the_reason(store):
    t = tools.Tools(store.path)
    old = doc_id(V2024)
    with pytest.raises(tools.ToolError) as e:
        t.grep(APPLIES, doc=old[:10])
    assert str(e.value) == (f"document {old} is excluded by the filters (superseded by "
                            f"{doc_id(V2025)[:12]}…); pass include_superseded or another as_of")
    res = t.grep(APPLIES, doc=old, filters={"include_superseded": True})
    assert grep_words(res) == ["old"] and res.excluded_by_filter == 0


def test_a_doc_scoped_grep_counts_only_its_own_document(store, capsys):
    t = tools.Tools(store.path)
    assert t.grep(APPLIES).excluded_by_filter == 2  # the whole snapshot
    res = t.grep(APPLIES, doc=doc_id(V2026))
    assert grep_words(res) == ["new"] and res.excluded_by_filter == 0
    code, out, _ = run(capsys, "grep", APPLIES, "--store", store.path, "--doc",
                       doc_id(V2026))
    assert code == 0 and "0 document(s) excluded" in out


# -- read ----------------------------------------------------------------------------------


def test_read_refuses_an_excluded_document_with_the_reason(store):
    t = tools.Tools(store.path)
    old = doc_id(V2024)
    want = (f"document {old} is excluded by the filters (superseded by "
            f"{doc_id(V2025)[:12]}…); pass include_superseded or another as_of")
    el = store.elements(old)[0].element_id
    chunk = next(c for c in phase1_index(store).chunks.values() if c.doc_id == old).chunk_id
    for kw in ({}, {"start": 0, "end": 5}, {"element": el}, {"chunk": chunk}):
        with pytest.raises(tools.ToolError) as e:
            t.read(old[:9], **kw)
        assert str(e.value) == want
    ok = t.read(old, filters={"include_superseded": True})
    assert ok.text == store.text(old) and ok.applicability is not None
    assert t.read(doc_id(V2026)).text == store.text(doc_id(V2026))


def test_read_at_the_as_of_boundaries(store):
    t = tools.Tools(store.path)
    mid = doc_id(V2025)
    assert t.read(mid, filters={"as_of": "2025-06-30"}).doc_id == mid
    assert t.read(mid, filters={"as_of": "2026-06-29"}).doc_id == mid
    with pytest.raises(tools.ToolError, match="not in force on 2026-06-30"):
        t.read(mid, filters={"as_of": "2026-06-30"})
    with pytest.raises(tools.ToolError, match="not in force on 2025-06-29"):
        t.read(mid, filters={"as_of": "2025-06-29"})
    with pytest.raises(tools.ToolError, match="proposed_rule"):
        t.read(doc_id(PROPOSED), filters={"as_of": "2024-04-01"})
    assert t.read(doc_id(PROPOSED), filters={"as_of": "2024-04-01",
                                             "status": ["proposed_rule"]}).doc_id
    with pytest.raises(tools.ToolError, match="valid_from unknown"):
        t.read(doc_id(LOOSE), filters={"as_of": "2024-04-01"})
    assert t.read(doc_id(FINAL), filters={"as_of": "2024-03-01"}).char_start == 0
    with pytest.raises(tools.ToolError, match="authority tier 3"):
        t.read(doc_id(IRM), filters={"max_tier": 2})
    # a document that does not exist is still "no document", not a filter message
    with pytest.raises(tools.ToolError, match="no document"):
        t.read("0" * 64)


# -- results and log -----------------------------------------------------------------------


def test_results_and_log_lines_carry_the_filters_and_the_overlay(store):
    oid = derive(store)
    t = tools.Tools(store.path)
    f = {"as_of": "2025-06-30", "status": ["codified"]}
    t.search(QUERY, top=3, filters=f)
    t.grep(APPLIES, max=2, filters=f)
    t.read(doc_id(V2025), filters=f)
    with pytest.raises(tools.ToolError):
        t.read(doc_id(V2024), filters=f)
    norm = Filters.parse(f).to_dict()
    lines = log_lines(store)[-4:]
    for ln in lines:
        assert ln["args"]["filters"] == f
        assert ln["filters"] == norm and ln["applicability"] == oid
    assert "error" in lines[-1]
    t.search(QUERY)
    last = log_lines(store)[-1]
    assert last["args"]["filters"] is None and last["filters"] == Filters().to_dict()
    with pytest.raises(tools.ToolError):
        t.search(QUERY, filters={"as_of": "soon"})
    last = log_lines(store)[-1]
    assert last["args"]["filters"] == {"as_of": "soon"} and last["filters"] is None
    t.search(QUERY, filters=Filters(as_of=D2025))
    assert log_lines(store)[-1]["args"]["filters"] == Filters(as_of=D2025).to_dict()
    json.dumps(t.search(QUERY, filters=f).to_dict())


def test_two_runs_give_identical_results(store):
    f = {"as_of": "2025-06-30"}
    a = tools.Tools(store.path).search(QUERY, top=20, filters=f).to_dict()
    b = tools.Tools(store.path).search(QUERY, top=20, filters=f).to_dict()
    assert a == b


# -- the command line ----------------------------------------------------------------------


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out, err


def test_cli_filter_flags_on_search_grep_and_read(store, capsys):
    s = store.path
    t = tools.Tools(s)
    code, out, _ = run(capsys, "search", QUERY, "--store", s, "--as-of", "2025-06-30",
                       "--top", 50, "--json")
    got = json.loads(out)
    want = t.search(QUERY, top=50, filters={"as_of": "2025-06-30"}).to_dict()
    assert code == 0 and got["hits"] == want["hits"]
    assert got["filters"]["as_of"] == "2025-06-30" and got["excluded_by_filter"] > 0
    code, out, _ = run(capsys, "search", QUERY, "--store", s, "--include-superseded",
                       "--status", "codified", "--status", "final_rule", "--jurisdiction",
                       "US-federal", "--max-tier", 2, "--json")
    got = json.loads(out)
    assert code == 0 and got["filters"] == {
        "include_superseded": True, "as_of": None, "status": ["codified", "final_rule"],
        "jurisdiction": ["US-federal"], "max_tier": 2}
    code, out, _ = run(capsys, "grep", APPLIES, "--store", s, "--as-of", "2026-06-30",
                       "--json")
    assert code == 0 and [m["match"] for m in json.loads(out)["matches"]] == [
        "applies to new vessels"]
    code, _, err = run(capsys, "read", doc_id(V2024), "--store", s)
    assert code == 2 and "is excluded by the filters (superseded by" in err
    code, out, _ = run(capsys, "read", doc_id(V2024), "--store", s, "--include-superseded",
                       "--end", 20, "--json")
    assert code == 0 and json.loads(out)["text"] == store.text(doc_id(V2024))[:20]
    code, _, err = run(capsys, "search", QUERY, "--store", s, "--as-of", "30/06/2025")
    assert code == 2 and "as_of must be an ISO date" in err
    code, _, err = run(capsys, "search", QUERY, "--store", s, "--status", "repealed")
    assert code == 2 and "repealed" in err
    # the last log line of a flagless call records no filters given
    run(capsys, "search", QUERY, "--store", s)
    assert log_lines(store)[-1]["args"]["filters"] is None


def test_cli_tables_name_the_filters(store, capsys):
    s = store.path
    code, out, _ = run(capsys, "search", QUERY, "--store", s)
    assert code == 0 and "filters default" in out and "2 document(s) excluded" in out
    code, out, _ = run(capsys, "grep", APPLIES, "--store", s, "--as-of", "2025-06-30")
    assert code == 0 and "as_of 2025-06-30" in out and "excluded" in out


def test_cli_without_an_overlay_refuses_as_of(bare, capsys):
    code, _, err = run(capsys, "search", QUERY, "--store", bare.path, "--as-of", "2025-06-30")
    assert code == 2 and err.strip() == f"error: {NO_OVERLAY}"
    code, out, _ = run(capsys, "search", QUERY, "--store", bare.path)
    assert code == 0 and "filters" not in out  # the Phase 1 table
