"""Snapshot handles and cursors in the Python API (Phase 2 spec §9.2, §9.3, §5.4; Task 12):
every result of the five tool calls carries a handle, a replay with it is identical, a part
that no longer exists fails explicitly, a handle never bypasses the ACL (an old content
snapshot is judged against the current ACL, ruling R15), `search` and `grep` page with a
cursor, and ids of the wrong type are refused cleanly. The fixture store is the gov-shaped
permissions fixture plus the mini corpus and the fixture tool catalog, lexical-only indexes,
everything under `tmp_path`."""

import json
import shutil
from pathlib import Path

import pytest

from adr_eval.corpora.base import load_corpus
from adr_store import acl, handles, tool_catalog, tools
from adr_store.store import Store
from tests.store.test_permissions import (
    ACME1,
    DOCS,
    GLOBEX,
    PUBLIC,
    RULES,
    T0,
    absent_like,
    did,
    fixed,
    log_lines,
    make,
    write_config,
)
from tests.store.test_tool_index import fixture_records
from tests.store.test_tool_search import TOOL_RULES

MINI = Path(__file__).parents[1] / "fixtures" / "mini"
ALL_RULES = [*TOOL_RULES, *RULES]
CALLER = "user:acme-4"  # groups acme/0 and acme/1
HEX = "0" * 64


def mini_docs() -> list[tuple]:
    corpus = load_corpus(MINI / "manifest.json", MINI)
    return [(corpus.docs[d.doc_id], (corpus.root / d.path).read_bytes())
            for d in sorted(corpus.manifest.documents, key=lambda d: d.doc_id)]


def build(path: Path, config_dir: Path, *, clock=None, docs=None):
    """The fixture store (content with an applicability and a dedup overlay, a tool catalog,
    lexical-only indexes) synced at `clock` (default: T0); returns (store, config)."""
    config = write_config(config_dir, ALL_RULES)
    s = make(path, config, docs=[*DOCS, *mini_docs()] if docs is None else docs,
             with_dedup=True, sync=False)
    tool_catalog.ingest(s.path, fixture_records())
    tools.Tools(s.path).tools_index(1, lexical_only=True)
    acl.sync(s.path, *config, clock=clock or fixed(T0))
    return s, config


@pytest.fixture
def built(tmp_path):
    return build(tmp_path / "store", tmp_path / "config")


@pytest.fixture
def store(built):
    return built[0]


def as_(store, caller=CALLER) -> tools.Tools:
    return tools.Tools(store.path, acl=True, caller=caller, clock=fixed())


def every_call(t: tools.Tools, store, **kw) -> dict:
    """One call of each of the five tools (with `kw`, e.g. a handle), as dicts."""
    tid = t.search_tools("git").hits[0].tool_id  # a tool the caller sees
    return {"search": t.search("vessel harbour refund", **kw).to_dict(),
            "read": t.read(did(PUBLIC), **kw).to_dict(),
            "grep": t.grep("vessel", **kw).to_dict(),
            "search_tools": t.search_tools("git", **kw).to_dict(),
            "load_tool": t.load_tool(tid, **kw).to_dict()}


# -- every result carries a handle ------------------------------------------------------------

@pytest.mark.parametrize("acl_on", [False, True])
def test_every_result_carries_the_handle_of_the_store_now(store, acl_on):
    t = as_(store) if acl_on else tools.Tools(store.path)
    now = handles.resolve(store.path, None).handle.model_dump()
    assert set(now) == set(handles.COMPONENTS)
    assert all(v is not None for v in now.values())  # the fixture has every part
    assert now["snapshot"] == store.snapshot_id
    for name, d in every_call(t, store).items():
        assert d["handle"] == now, name


@pytest.mark.parametrize("acl_on", [False, True])
def test_a_replay_with_the_handle_is_identical(store, acl_on):
    t = as_(store) if acl_on else tools.Tools(store.path)
    first = every_call(t, store)
    for name, d in first.items():
        h = d["handle"]
        again = every_call(t, store, handle=h)[name]
        assert again == d, name
        # a Handle object works as well as the dict
        assert every_call(t, store, handle=handles.Handle(**h))[name] == d


def test_a_handle_is_logged_and_args_are_unchanged_without_one(store):
    t = tools.Tools(store.path)
    res = t.search("vessel", top=3)
    ln = log_lines(store)[-1]
    assert ln["args"] == {"query": "vessel", "top": 3, "filters": None, "dedup": None}
    assert ln["handle"] == res.handle
    t.search("vessel", top=3, handle=res.handle)
    ln = log_lines(store)[-1]
    assert ln["args"]["handle"] == res.handle and ln["handle"] == res.handle


# -- a handle runs on exactly its parts ---------------------------------------------------------

def _second_snapshot(store, config, docs, clock=None):
    """A new content snapshot of `docs` (applicability overlay, index, dedup overlay), then
    one sync: the store's HEAD moves on, the old snapshot stays readable by handle."""
    from tests.store.test_permissions import build_dedup, derive

    s = Store.create(store.path)
    for document, raw in docs:
        s.add(document, raw)
    s.commit()
    s = Store.open(store.path)
    derive(s)
    tools.Tools(s.path).index("p1-struct", lexical_only=True)
    build_dedup(s)
    acl.sync(s.path, *config, clock=clock or fixed(T0))
    return s


def test_a_handle_keeps_reading_its_own_snapshot_after_head_moves(built):
    store, config = built
    t = tools.Tools(store.path)
    old = t.read(did(GLOBEX))
    old_search = t.search("globex brief")
    s2 = _second_snapshot(store, config, [d for d in [*DOCS, *mini_docs()] if d is not GLOBEX])
    assert s2.snapshot_id != store.snapshot_id
    # without a handle: HEAD, where GLOBEX is gone
    assert "no document" in str(pytest.raises(tools.ToolError, t.read, did(GLOBEX)).value)
    # with the old handle (no ACL layer): the old snapshot, exactly
    assert t.read(did(GLOBEX), handle=old.handle).to_dict() == old.to_dict()
    assert t.search("globex brief", handle=old_search.handle).to_dict() == old_search.to_dict()


def test_an_old_snapshot_handle_is_judged_against_the_current_acl(built):
    """globex-0 read GLOBEX at the first snapshot. A new snapshot without GLOBEX and a sync
    later, the old handle still names a snapshot holding GLOBEX, but the current ACL has no
    entry for it: "not found", byte for byte as an id that never existed (R15). A document in
    both snapshots whose rule is changed (a revocation) is invisible through the old handle
    too."""
    store, config = built
    g = as_(store, "user:globex-0")
    old = g.read(did(GLOBEX))
    a = as_(store)
    old_a = a.read(did(ACME1))
    _second_snapshot(store, config, [d for d in [*DOCS, *mini_docs()] if d is not GLOBEX],
                     clock=fixed(T0))
    none = absent_like(did(GLOBEX), [did(d) for d in DOCS])
    for t, doc, h in ((g, did(GLOBEX), old.handle), (as_(store, "user:auditor"), did(GLOBEX),
                                                       old.handle)):
        missing = str(pytest.raises(tools.ToolError, t.read, none, handle=h).value)
        hidden = str(pytest.raises(tools.ToolError, t.read, doc, handle=h).value)
        assert hidden == missing.replace(none[:12], doc[:12])
        assert doc not in {m.doc_id for m in t.grep("globex", handle=h).matches}
        assert doc not in {x.doc_id for x in t.search("globex brief", handle=h).hits}
        assert log_lines(store)[-3]["not_visible"] == [doc]
    # the same old handle, after a revocation of ACME1 for the caller
    pol = json.loads(config[1].read_text())
    pol["rules"].insert(0, {"match": {"uri_prefix": "file://acl/acme-1/"},
                            "access": ["group:globex/0"]})
    config[1].write_text(json.dumps(pol))
    acl.sync(store.path, *config, clock=fixed(T0))
    none = absent_like(did(ACME1), [did(d) for d in DOCS])
    missing = str(pytest.raises(tools.ToolError, a.read, none, handle=old_a.handle).value)
    hidden = str(pytest.raises(tools.ToolError, a.read, did(ACME1), handle=old_a.handle).value)
    assert hidden == missing.replace(none[:12], did(ACME1)[:12])


def test_a_handle_never_bypasses_the_acl(built):
    store, config = built
    h = tools.Tools(store.path).search("vessel").handle
    ghost = as_(store, "user:ghost")  # not in the directory: F4, before the handle is read
    for kw in ({"handle": h}, {"handle": {**h, "index": None, "extra": 1}},
               {"handle": {**h, "snapshot": HEX}}):
        with pytest.raises(tools.AccessDenied) as e:
            ghost.search("vessel", **kw)
        assert e.value.code == "F4"
    # a content snapshot newer than the ACL denies all (F2), handle or not
    s = Store.open(store.path)
    from tests.store.test_permissions import md
    s.add(*md("public/later.md", "Later", "A later vessel note."))
    s.commit()
    with pytest.raises(tools.AccessDenied) as e:
        as_(store).read(did(PUBLIC), handle=h)
    assert e.value.code == "F2"


def test_an_old_snapshot_whose_chain_the_current_acl_splits_is_denied_f1(built):
    """An old snapshot holding an eCFR version that the new snapshot dropped: the current ACL
    has no entry for it, so a view of the old snapshot holds part of its chain only (F1, as
    for HEAD: all versions of a source share access)."""
    from tests.store.test_applicability import V2024
    store, config = built
    h = as_(store).search("vessel").handle
    _second_snapshot(store, config, [d for d in [*DOCS, *mini_docs()] if d is not V2024])
    with pytest.raises(tools.AccessDenied) as e:
        as_(store).search("vessel", handle=h)
    assert e.value.code == "F1" and "chain" in str(e.value)
    assert as_(store).search("vessel").hits  # HEAD itself is fine


# -- parts that are gone, and bad handles -------------------------------------------------------

def _all_fail(store, h, message):
    for t in (tools.Tools(store.path), as_(store)):
        for fn, a in ((t.search, ("vessel",)), (t.read, (did(PUBLIC),)), (t.grep, ("vessel",)),
                      (t.search_tools, ("time",)), (t.load_tool, (HEX,))):
            with pytest.raises(tools.ToolError) as e:
                fn(*a, handle=h)
            assert str(e.value) == message


def test_a_handle_whose_index_directory_was_deleted_fails_explicitly(store):
    h = tools.Tools(store.path).search("vessel").handle
    shutil.rmtree(store.path / "index" / h["index"].split(":")[0])
    _all_fail(store, h, "handle no longer available: index")


@pytest.mark.parametrize("component", ["snapshot", "applicability", "dedup", "tools",
                                       "tool_index"])
def test_every_part_that_is_gone_fails_explicitly(store, component):
    h = tools.Tools(store.path).search("vessel").handle
    if component == "tool_index":
        shutil.rmtree(store.path / "tools" / "index" / h["tool_index"].split(":")[0])
    elif component == "applicability":
        p = handles.ap.overlay_path(store.path, h["snapshot"])
        p.write_bytes(p.read_bytes() + b" ")  # no longer hashes to the id
    else:  # a part of another store: never existed here
        h = {**h, component: "a" * 64}
    _all_fail(store, h, f"handle no longer available: {component}")


@pytest.mark.parametrize("change,needle", [
    (lambda h: {**h, "extra": 1}, "extra"),
    (lambda h: {k: v for k, v in h.items() if k != "dedup"}, "dedup"),
    (lambda h: {**h, "snapshot": "x"}, "snapshot"),
    (lambda h: {**h, "index": "nonsense"}, "index"),
    (lambda h: {**h, "index": h["index"].rsplit(":", 1)[0] + ":0.5"}, "lexical-only"),
    (lambda h: {**h, "index": None}, "a dedup overlay without an index"),
    (lambda h: {**h, "tools": None}, "a tool index without a tool snapshot"),
    (lambda h: "a string", "expected an object"),
])
def test_a_bad_handle_is_refused(store, change, needle):
    h = change(tools.Tools(store.path).search("vessel").handle)
    for t in (tools.Tools(store.path), as_(store)):
        e = pytest.raises(tools.ToolError, t.read, did(PUBLIC), handle=h).value
        assert str(e).startswith("bad handle: ") and needle in str(e)
        assert log_lines(store)[-1]["error"] == str(e)


def test_a_handle_without_an_index_refuses_search_but_reads(store):
    h = {**tools.Tools(store.path).read(did(PUBLIC)).handle, "index": None, "dedup": None}
    t = as_(store)
    assert "the handle names no index" in str(
        pytest.raises(tools.ToolError, t.search, "vessel", handle=h).value)
    assert t.read(did(PUBLIC), handle=h).handle == h


# -- cursors ------------------------------------------------------------------------------------

@pytest.mark.parametrize("acl_on", [False, True])
def test_search_pages_with_a_cursor(store, acl_on):
    t = as_(store) if acl_on else tools.Tools(store.path)
    q = "refund rule vessel harbour section part"
    whole = t.search(q, top=50)
    assert 12 < len(whole.hits) < 50
    first = t.search(q, top=5)
    assert first.next_cursor == "5" and first.cursor is None
    pages, cursor = [], None
    while True:
        p = t.search(q, top=5, cursor=cursor, handle=first.handle)
        assert p.cursor == cursor and len(p.hits) <= 5
        pages += p.hits
        cursor = p.next_cursor
        if cursor is None:
            break
    assert [h.to_dict() for h in pages] == [h.to_dict() for h in whole.hits]
    assert [h.rank for h in pages] == list(range(1, len(whole.hits) + 1))
    for bad_cursor in ("x", "-1", "1.5", 3, "199"):
        with pytest.raises(tools.ToolError, match="cursor"):
            t.search("vessel", top=5, cursor=bad_cursor)


@pytest.mark.parametrize("acl_on", [False, True])
def test_grep_pages_with_a_cursor(store, acl_on):
    t = as_(store) if acl_on else tools.Tools(store.path)
    whole = t.grep("vessel|harbour", max=100)
    assert not whole.truncated and len(whole.matches) > 7
    got, cursor = [], None
    while True:
        p = t.grep("vessel|harbour", max=3, cursor=cursor)
        got += p.matches
        assert (p.next_cursor is None) == (not p.truncated)
        cursor = p.next_cursor
        if cursor is None:
            break
        last = p.matches[-1]
        assert cursor == f"{last.doc_id}:{last.char_end}"
    assert [m.to_dict() for m in got] == [m.to_dict() for m in whole.matches]
    with pytest.raises(tools.ToolError, match="cursor"):
        t.grep("vessel", cursor="no-offset")


def test_a_grep_cursor_naming_a_hidden_document_is_one_naming_none(store):
    t = as_(store)  # acme-4 does not see GLOBEX
    none = absent_like(did(GLOBEX), [did(d) for d in DOCS])
    for off in (0, 5):
        a = t.grep("vessel", cursor=f"{did(GLOBEX)}:{off}").to_dict()
        b = t.grep("vessel", cursor=f"{none}:{off}").to_dict()
        assert {k: v for k, v in a.items() if k != "cursor"} == \
            {k: v for k, v in b.items() if k != "cursor"}


# -- ids of the wrong type ----------------------------------------------------------------------

@pytest.mark.parametrize("acl_on", [False, True])
def test_ids_of_the_wrong_type_are_refused_cleanly(store, acl_on):
    t = as_(store) if acl_on else tools.Tools(store.path)
    cases = [(t.read, (5,), {}, "doc_id"), (t.read, (["x"],), {}, "doc_id"),
             (t.read, (did(PUBLIC),), {"element": 5}, "element"),
             (t.read, (did(PUBLIC),), {"chunk": [1]}, "chunk"),
             (t.grep, ("vessel",), {"doc": 5}, "doc"), (t.grep, (5,), {}, "pattern"),
             (t.search, (5,), {}, "query"), (t.load_tool, (5,), {}, "tool_id"),
             (t.load_tool, (["a"],), {}, "tool_id"), (t.search_tools, (None,), {}, "query"),
             (t.search, ("vessel",), {"cursor": 5}, "cursor")]
    for fn, a, kw, name in cases:
        before = len(log_lines(store))
        with pytest.raises(tools.ToolError) as e:
            fn(*a, **kw)
        assert name in str(e.value) and "must be a string" in str(e.value)
        assert type(e.value) is tools.ToolError
        assert len(log_lines(store)) == before + 1
        assert log_lines(store)[-1]["error"] == str(e.value)
