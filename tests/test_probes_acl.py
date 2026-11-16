"""ACL and equivalence probes (Phase 2 spec §10.2, criteria B1, B2, B4, B5) on the gov-shaped
fixture of `tests/store/test_permissions.py` (markdown documents whose access attribute rules
fix, the fake embedder or lexical-only indexes): reference stores, B2 over every view, the
leak probe families and their six leak kinds (each shown to fire on a leaking tool), the 90
fail-closed probes, the log-field scan and the CLI. Nothing reads `data/` or `.cache/`."""

import dataclasses
import json
from datetime import date, timedelta

import pytest

from adr_eval.cli import main
from adr_eval.models import GoldenItem
from adr_eval.probes import acl as probes_acl
from adr_eval.probes import equivalence as eq
from adr_store import acl, tools
from adr_store.store import Store, StoreError
from tests.conftest import _base
from tests.store.test_permissions import (
    NOW,
    QUERIES,
    T0,
    as_,
    fixed,
    make,
    visible,
)
from tests.store.test_permissions import (
    write_config as write_acl_config,
)
from tests.store.test_retrieval import fake_cache

SMALL = {"search-rare": 12, "search-title": 8, "grep-literal": 8, "grep-doc": 6, "read": 12}


@pytest.fixture(autouse=True)
def _fresh_view_cache():
    tools._VIEW_LEXICAL.clear()
    yield
    tools._VIEW_LEXICAL.clear()


@pytest.fixture(autouse=True)
def fake_models(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "make_embedding_cache",
                        lambda path=None, *, threads=1: fake_cache(tmp_path / "emb"))


@pytest.fixture
def config(tmp_path):
    return write_acl_config(tmp_path / "config")


@pytest.fixture
def store(tmp_path, config):
    return make(tmp_path / "store", config, dense=True, with_dedup=True)


def ctx_of(store) -> probes_acl.Context:
    return probes_acl.context(store.path, tools.Tools(store.path).active_index().chunks)


def refs_of(store, config, tmp_path) -> dict:
    """caller -> reference store path, one per view."""
    out = {}
    for v in eq.views(acl.read_head(store.path)[1]):
        path = tmp_path / "views" / v.view[:12]
        eq.ensure_view_store(store, v.docs, path, emb_cache=tmp_path / "emb",
                             directory=config[0], policy=config[1], clock=fixed(T0))
        out.update(dict.fromkeys(v.users, path))
    return out


def item(i: int, question: str, **kw) -> GoldenItem:
    return GoldenItem(**{**_base(), "id": f"q{i:02d}", "corpus": "gov", "question": question,
                         **kw})


ITEMS = [item(i, q) for i, q in enumerate(QUERIES)] + [
    item(90, "harbour levy as of the older rule", qtype="policy_asof",
         as_of=date(2024, 6, 1))]


# -- reference stores ---------------------------------------------------------------------------


def test_a_view_store_holds_exactly_the_view_with_the_source_records(store, config, tmp_path):
    docs = visible(store, "user:acme-0")
    dst = tmp_path / "ref"
    ref = eq.view_store(store, docs, dst, emb_cache=tmp_path / "emb", directory=config[0],
                        policy=config[1], clock=fixed(T0))
    assert ref.doc_ids() == sorted(docs) and len(docs) < len(store.doc_ids())
    assert {d: ref._records[d] for d in docs} == {d: store._records[d] for d in docs}
    assert visible(ref, "user:acme-0") == set(docs)  # the caller sees all of it
    rec = json.loads((dst / eq.VIEW_FILE).read_text())
    assert rec["view"] == acl.view_id(docs) and rec["snapshot"] == ref.snapshot_id
    active = json.loads((dst / "index" / "active.json").read_text())
    src_active = json.loads((store.path / "index" / "active.json").read_text())
    assert {k: active[k] for k in ("system", "w", "w_bc", "lexical_only")} == \
        {k: src_active[k] for k in ("system", "w", "w_bc", "lexical_only")}
    assert any((dst / "applicability").iterdir()) and any((dst / "dedup").iterdir())
    d = eq.describe(dst)
    assert d["snapshot"] == ref.snapshot_id and d["acl_sequence"] == 1
    assert d["documents"] == len(docs)
    kw = dict(emb_cache=tmp_path / "emb", directory=config[0], policy=config[1])
    assert eq.ensure_view_store(store, docs, dst, clock=fixed(T0), **kw)[1] == "reused"
    later = fixed(T0 + timedelta(hours=2))
    assert eq.ensure_view_store(store, docs, dst, clock=later, **kw)[1] == "reused, synced"
    assert eq.describe(dst)["acl_sequence"] == 2
    with pytest.raises(StoreError, match="another view"):
        eq.ensure_view_store(store, list(docs)[1:], dst, clock=fixed(T0), **kw)
    with pytest.raises(StoreError, match="already holds"):
        eq.view_store(store, docs, dst, **kw)


def test_views_are_the_distinct_visible_sets_with_their_first_user(store):
    snap = acl.read_head(store.path)[1]
    vs = eq.views(snap)
    users = [u for v in vs for u in v.users]
    assert sorted(users) == sorted(snap.directory)
    assert len({v.docs for v in vs}) == len(vs)
    for v in vs:
        assert v.caller == min(v.users)
        assert all(visible(store, u) == set(v.docs) for u in v.users)


def test_questions_and_grep_patterns_are_seeded_and_deterministic():
    many = [item(i, f"question {i} about vessels") for i in range(80)]
    a, b = eq.questions(many), eq.questions(list(reversed(many)))
    assert [i.id for i in a] == [i.id for i in b] and len(a) == 50
    assert eq.grep_pattern("Which harbour levy applies to craft?") == "applies"  # 7 letters, first
    assert eq.grep_pattern("a b c") == "a\\ b\\ c"
    assert eq.filters_for(ITEMS[-1], "p2-default") == ({"as_of": "2024-06-01"}, True)
    assert eq.filters_for(ITEMS[0], "p2-default") == ({}, True)
    assert eq.filters_for(ITEMS[-1], "phase1") == ({"include_superseded": True}, False)


# -- B2 ------------------------------------------------------------------------------------------


def test_b2_every_view_equals_its_reference_store(store, config, tmp_path):
    refs = refs_of(store, config, tmp_path)
    vs = eq.views(acl.read_head(store.path)[1])
    checks = []
    for v in vs:
        checks += eq.compare_view(as_(store, v.caller), as_(Store.open(refs[v.caller]),
                                                             v.caller), v, ITEMS)
    s = eq.summarize(checks)
    assert s["n"] == len(vs) * len(ITEMS) * 2 * 2 == s["identical"], [
        c for c in checks if not c.identical][:3]
    assert s["views"] == len(vs) > 3
    assert s["by_tool_mode"]["search/phase1"]["hits"] > 0
    assert s["by_tool_mode"]["grep/p2-default"]["hits"] > 0


def test_b2_detects_a_reference_store_that_differs(store, config, tmp_path):
    """A reference store holding one more document than the view is not equivalent."""
    v = next(v for v in eq.views(acl.read_head(store.path)[1]) if v.caller == "user:acme-0")
    extra = next(d for d in store.doc_ids() if d not in v.docs)
    ref = eq.view_store(store, set(v.docs) | {extra}, tmp_path / "wrong",
                        emb_cache=tmp_path / "emb", directory=config[0], policy=config[1],
                        clock=fixed(T0))
    other = next(u for u in acl.read_head(ref.path)[1].directory
                 if visible(ref, u) == set(ref.doc_ids()))
    checks = eq.compare_view(as_(store, v.caller), as_(ref, other), v, ITEMS)
    assert sum(not c.identical for c in checks) > 0
    assert all(c.difference for c in checks if not c.identical)


# -- leak probes ---------------------------------------------------------------------------------


def test_leak_probes_have_the_spec_counts_and_are_deterministic(store):
    ctx = ctx_of(store)
    probes = probes_acl.leak_probes(ctx)
    counts = {f: sum(p.family == f for p in probes) for f in probes_acl.FAMILY_SIZES}
    assert counts == probes_acl.FAMILY_SIZES and len(probes) == 280
    again = probes_acl.leak_probes(ctx_of(store))
    assert json.dumps([p.to_dict() for p in again]) == json.dumps([p.to_dict() for p in probes])
    callers = {p.caller for p in probes}
    assert {"user:ghost", "user:outsider"} <= callers
    # the auditor sees every document but those with an empty list (the fixture has one)
    empty = {d for d, v in ctx.snap.docs.items() if not v}
    assert empty and {p.target["doc_id"] for p in probes if p.caller == "user:auditor"} <= empty
    for p in probes:
        assert p.target["doc_id"] not in ctx.visible(p.caller)
        assert p.tool == probes_acl.FAMILY_TOOL[p.family]
    rare = [p for p in probes if p.family == "search-rare"]
    assert all(len(p.call["query"].split()) <= 10 for p in rare)
    assert len({(p.caller, p.target["chunk_id"]) for p in rare}) == len(rare)
    for p in probes:
        if p.family == "grep-literal":
            secret = p.target["secret"]
            assert len(secret) == 30 and secret in ctx.text(p.target["doc_id"])
            assert sum(secret in ctx.text(d) for d in ctx.store.doc_ids()) == 1
    kinds = [p.target["kind"] for p in probes if p.family == "read"]
    assert {k: kinds.count(k) for k in probes_acl.READ_KINDS} == dict.fromkeys(
        probes_acl.READ_KINDS, 15)
    assert len({p.probe_id for p in probes}) == len(probes)


def run_leak(store, config, tmp_path, tools_for=None, sizes=SMALL):
    ctx = ctx_of(store)
    refs = refs_of(store, config, tmp_path)
    probes = probes_acl.leak_probes(ctx, sizes=sizes)
    tools_for = tools_for or (lambda c: as_(store, c))

    def reference_for(c):
        return None if c not in refs else as_(Store.open(refs[c]), c)

    return [probes_acl.check(p, tools_for, reference_for, ctx) for p in probes]


def test_no_leak_on_the_tools_and_every_kind_is_checked(store, config, tmp_path):
    results = run_leak(store, config, tmp_path)
    s = probes_acl.summarize(results)
    assert s["total"]["leaks"] == 0 and s["total"]["invalid"] == 0, [
        r for r in results if r.leak or not r.valid][:3]
    assert all(n > 0 for n in s["total"]["checked_kinds"].values()), s["total"]
    ghost = [r for r in results if r.caller == "user:ghost"]
    assert ghost and all(r.outcome == "denied:F4" for r in ghost)
    assert {r.outcome for r in results if r.family == "read"} >= {"refused"}


class Wrap:
    """Tools whose results (`ok`) or refusals (`err`) a function per tool rewrites."""

    def __init__(self, real, ok=None, err=None):
        self.real, self.ok, self.err = real, ok or {}, err or {}

    def _do(self, name, *a, **kw):
        try:
            res = getattr(self.real, name)(*a, **kw)
        except tools.ToolError as e:
            if name not in self.err:
                raise
            return self.err[name](e, a, kw)
        return self.ok[name](res) if name in self.ok else res

    def search(self, *a, **kw):
        return self._do("search", *a, **kw)

    def grep(self, *a, **kw):
        return self._do("grep", *a, **kw)

    def read(self, *a, **kw):
        return self._do("read", *a, **kw)


def leaks_by_kind(results) -> dict:
    return {k: sum(bool(r.kinds[k]) for r in results) for k in probes_acl.KINDS}


def test_a_tool_without_the_acl_layer_leaks_ids_and_text(store, config, tmp_path):
    off = tools.Tools(store.path)
    results = run_leak(store, config, tmp_path, tools_for=lambda c: off)
    k = leaks_by_kind(results)
    assert k["id_outside_view"] > 0 and k["hidden_text"] > 0
    assert k["score_differs"] > 0 and k["count_includes_hidden"] > 0
    assert any(r.leak for r in results if r.family == "grep-literal")
    assert any(r.leak for r in results if r.family == "read")


def test_each_remaining_leak_kind_is_detected(store, config, tmp_path):
    ctx = ctx_of(store)
    from adr_store.dedup import Alternate

    def alternate(caller):
        def fn(res):
            if not res.hits:
                return res
            cid = next(c for c, ch in ctx.chunks.items()
                       if ch.doc_id not in ctx.visible(caller))
            hit = dataclasses.replace(res.hits[0], alternates=[
                Alternate(cid, ctx.chunks[cid].doc_id, "exact", 1.0)])
            return dataclasses.replace(res, hits=[hit, *res.hits[1:]])
        return fn

    def louder(error, args, kwargs):
        given = kwargs.get("doc") or (args[0] if args else None)
        if given in ctx.store.doc_ids():  # a real (hidden) id: say a little more
            raise tools.ToolError(str(error) + " (hidden)")
        raise error

    def count(res):
        return dataclasses.replace(res, excluded_by_filter=res.excluded_by_filter + 1)

    def score(res):
        return dataclasses.replace(res, hits=[dataclasses.replace(h, score=h.score + 1e-9)
                                              for h in res.hits])

    def naming(caller):
        def fn(error, args, kwargs):
            raise tools.ToolError(f"{error} (did you mean {ctx.hidden(caller)[0]}?)")
        return fn

    cases = {
        "alternate_outside_view": lambda c: Wrap(as_(store, c), ok={"search": alternate(c)}),
        "not_found_differs": lambda c: Wrap(as_(store, c), err={"read": louder,
                                                                "grep": louder}),
        "count_includes_hidden": lambda c: Wrap(as_(store, c), ok={"search": count}),
        "score_differs": lambda c: Wrap(as_(store, c), ok={"search": score}),
        "hidden_text": lambda c: Wrap(as_(store, c), err={"read": naming(c)}),
    }
    for kind, tools_for in cases.items():
        results = run_leak(store, config, tmp_path, tools_for=tools_for)
        assert leaks_by_kind(results)[kind] > 0, kind


def test_a_caller_outside_the_directory_who_is_not_denied_is_invalid(store, config, tmp_path):
    off = tools.Tools(store.path)
    results = run_leak(store, config, tmp_path,
                       tools_for=lambda c: off if c == "user:ghost" else as_(store, c))
    ghost = [r for r in results if r.caller == "user:ghost"]
    assert ghost and not any(r.valid for r in ghost)


# -- fail closed ---------------------------------------------------------------------------------


def run_failclosed(store, config, tmp_path, make_tools=None):
    ctx = ctx_of(store)
    probes = probes_acl.failclosed_probes(ctx)
    make_tools = make_tools or (lambda path, caller: tools.Tools(
        path, acl=True, caller=caller, clock=fixed(NOW)))
    return probes, *probes_acl.run_failclosed(
        probes, store.path, tmp_path / "clones", ctx, make_tools=make_tools,
        directory=config[0], policy=config[1], clock=fixed(NOW))


def test_the_90_failclosed_probes_return_no_content(store, config, tmp_path):
    head = (store.path / "acl" / "HEAD").read_bytes()
    probes, results, logs = run_failclosed(store, config, tmp_path)
    assert len(probes) == 90 and len(results) == 90
    s = probes_acl.summarize_failclosed(results)
    assert s["total"] == {"n": 90, "passed": 90, "content": 0}, [
        r for r in results if not r["pass"]][:3]
    for cond in probes_acl.CONDITIONS:
        b = s["conditions"][cond]
        assert b["n"] == 15 and b["by_tool"] == {"grep": 5, "read": 5, "search": 5}
        if cond != "no_entry":
            assert b["outcomes"] == {f"denied:{cond}": 15}
    callers = {r["caller"] for r in results if r["family"] == "F1"}
    assert {"user:auditor", "user:outsider"} <= callers and len(callers) == 5
    assert {r["variant"] for r in results if r["family"] == "F1"} == set(
        probes_acl.F1_VARIANTS)
    assert (store.path / "acl" / "HEAD").read_bytes() == head  # the store itself unchanged
    assert not any((tmp_path / "clones").glob("failclosed-*"))
    total = probes_acl.total_scan(logs)
    assert total["lines"] == 95 and total["complete"]  # 90 calls and 5 read controls
    assert total["decisions"]["allowed"] == 20


def test_a_tool_that_fails_open_is_caught(store, config, tmp_path):
    _, results, _ = run_failclosed(store, config, tmp_path,
                                   make_tools=lambda path, caller: tools.Tools(path))
    s = probes_acl.summarize_failclosed(results)
    for cond in ("F1", "F2", "F3", "F4", "F5"):
        assert s["conditions"][cond]["passed"] == 0
        assert s["conditions"][cond]["content"] > 0
    assert s["conditions"]["no_entry"]["passed"] < 15


def test_scan_log_counts_lines_missing_a_field(tmp_path):
    log = tmp_path / "log" / "retrieval.jsonl"
    log.parent.mkdir()
    full = {"tool": "search", "caller": "user:a", "principals": [], "acl_snapshot": "x",
            "acl_decision": "allowed"}
    log.write_text(json.dumps(full) + "\n")
    offset = probes_acl.log_size(log)
    log.write_text(log.read_text() + json.dumps(full) + "\n"
                   + json.dumps({"tool": "grep", "caller": None, "acl_decision": "off"})
                   + "\n")
    s = probes_acl.scan_log(log, offset)
    assert (s["lines"], s["complete_lines"]) == (2, 1)
    assert s["missing"] == {"caller": 0, "principals": 1, "acl_snapshot": 1,
                            "acl_decision": 0}
    assert not probes_acl.total_scan({"a": s})["complete"]
    assert probes_acl.scan_log(tmp_path / "none.jsonl")["lines"] == 0


# -- the command line ----------------------------------------------------------------------------


def test_the_cli_runs_both_probe_sets_and_writes_deterministic_probe_files(
        tmp_path, config, capsys):
    s = make(tmp_path / "store", config, dense=True, with_dedup=True, sync=False)
    acl.sync(s.path, *config)  # the real clock: the CLI's tools read it
    out, views = tmp_path / "runs", tmp_path / "views"
    common = ["--store", str(s.path), "--allow-other-index", "--directory", str(config[0]),
              "--policy", str(config[1]), "--views", str(views), "--out", str(out)]
    assert main(["probes", "equivalence", "mini", *common, "--questions", "4",
                 "--keep-views"]) == 0
    assert "Identical" in capsys.readouterr().out
    assert any(views.iterdir())
    for _ in range(2):
        assert main(["probes", "acl", "mini", *common, "--per-family", "4",
                     "--clones", str(tmp_path / "clones")]) == 0
    assert not views.exists()  # removed after the acl run
    first, second = sorted(out.glob("probes-acl-mini-*"))
    (eq_dir,) = out.glob("probes-equivalence-mini-*")
    assert (first / "probes.json").read_bytes() == (second / "probes.json").read_bytes()
    summary = json.loads((first / "summary.json").read_text())
    assert summary["leak"]["total"] == {**summary["leak"]["total"], "n": 20, "leaks": 0,
                                        "invalid": 0}
    assert summary["failclosed"]["total"] == {"n": 90, "passed": 90, "content": 0}
    assert summary["logs"]["total"]["complete"]
    assert summary["config"]["views_removed"] and summary["config"]["views"][0]["how"] == \
        "reused"
    text = (first / "summary.json").read_text() + (eq_dir / "summary.json").read_text()
    assert not any(q in text for q in QUERIES)  # no corpus text in the summaries
    eq_summary = json.loads((eq_dir / "summary.json").read_text())
    assert eq_summary["summary"]["differing"] == 0 and eq_summary["config"]["questions"] == 4
    assert main(["probes", "temporal", "mini", "--store", str(s.path)]) == 2
    assert "for gov" in capsys.readouterr().err


def test_the_cli_refuses_a_store_whose_acl_snapshot_is_stale(tmp_path, config, capsys):
    s = make(tmp_path / "store", config)  # synced at T0, hours from the real clock
    assert main(["probes", "acl", "mini", "--store", str(s.path), "--allow-other-index",
                 "--out", str(tmp_path / "runs")]) == 2
    assert "adr acl sync" in capsys.readouterr().err

