"""The `adr` tools: index, search, read, grep and the retrieval log (spec §9, §12 fifth
bullet). Fake embedder and reranker, or lexical-only indexes; nothing reads `data/` or
`.cache/`."""

import json
import re
import threading
from datetime import datetime
from pathlib import Path

import pytest

from adr_eval import runner, systems
from adr_eval.corpora.base import load_corpus
from adr_store import tools
from adr_store.cli import main
from adr_store.records import sha256_text
from adr_store.retrieval import Settings, StoreIndex
from adr_store.store import Store
from tests.store.test_chunking import doc
from tests.store.test_retrieval import fake_cache, fake_reranker

FIXTURES = Path(__file__).parents[1] / "fixtures"
MINI = FIXTURES / "mini"
QUERY = "refund deadline"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def make_mini_store(path: Path) -> Store:
    corpus = load_corpus(MINI / "manifest.json", MINI)
    s = Store.create(path)
    for d in sorted(corpus.manifest.documents, key=lambda d: d.doc_id):
        s.add(corpus.docs[d.doc_id], (corpus.root / d.path).read_bytes())
    s.commit()
    return Store.open(path)


@pytest.fixture
def store(tmp_path) -> Store:
    return make_mini_store(tmp_path / "store")


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    """Fake embedding cache and cross-encoder behind the tools' factories."""
    made = {"caches": [], "rerankers": []}

    def cache(path=None):
        c = fake_cache(tmp_path / "emb")
        made["caches"].append(c)
        return c

    def reranker():
        r = fake_reranker()
        made["rerankers"].append(r)
        return r

    monkeypatch.setattr(tools, "make_embedding_cache", cache)
    monkeypatch.setattr(tools, "make_reranker", reranker)
    return made


def log_lines(store: Store) -> list[dict]:
    path = store.path / "log" / "retrieval.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def lexical(store: Store, system: str = "p1-struct", **kw) -> tools.Tools:
    t = tools.Tools(store.path)
    t.index(system, lexical_only=True, **kw)
    return t


# -- the system table ---------------------------------------------------------------------


def test_the_tools_know_the_registry_systems_with_the_registrys_settings():
    assert set(tools.SYSTEMS) == set(systems.SPECS)
    for name, spec in systems.SPECS.items():
        mine = tools.SYSTEMS[name]
        assert (mine.prefix, mine.tune_w_bc, mine.rerank) == (spec.prefix, spec.tune_w_bc,
                                                              spec.rerank)


# -- index ---------------------------------------------------------------------------------


def test_index_builds_then_loads_the_same_index_for_the_head_snapshot(store):
    t = tools.Tools(store.path)
    first = t.index("p1-struct", lexical_only=True)
    want = StoreIndex.build(store, Settings(w_bc=0, prefix=False), dense=False)
    assert first.fingerprint == want.fingerprint
    assert first.snapshot == store.snapshot_id and first.source == "built"
    assert first.n_chunks == len(want.chunks) and first.w is None and first.lexical_only
    assert (store.path / "index" / first.fingerprint / "meta.json").is_file()
    again = tools.Tools(store.path).index("p1-struct", lexical_only=True)
    assert again.fingerprint == first.fingerprint and again.source == "loaded"
    active = json.loads((store.path / "index" / "active.json").read_text())
    assert active["fingerprint"] == first.fingerprint and active["system"] == "p1-struct"


def test_a_dense_index_uses_the_embedding_cache_and_needs_a_weight(store, fakes, tmp_path):
    t = tools.Tools(store.path)
    with pytest.raises(tools.ToolError, match="fusion weight"):
        t.index("p1-struct")
    info = t.index("p1-struct", weight=0.4)
    want = StoreIndex.build(store, Settings(w_bc=0, prefix=False), fake_cache(tmp_path / "emb"))
    assert info.fingerprint == want.fingerprint and info.w == 0.4 and not info.lexical_only
    assert fakes["caches"]


def test_breadcrumb_systems_need_a_w_bc(store):
    t = tools.Tools(store.path)
    with pytest.raises(tools.ToolError, match="w_bc"):
        t.index("p1-struct-bc", lexical_only=True)
    info = t.index("p1-struct-bc", lexical_only=True, w_bc=2)
    want = StoreIndex.build(store, Settings(w_bc=2, prefix=True), dense=False)
    assert info.fingerprint == want.fingerprint and info.w_bc == 2
    assert info.w_bc_from == "override"


@pytest.mark.parametrize("kw, match", [
    ({"system": "p1-struct", "w_bc": 1}, "p1-struct.*w_bc 0"),
    ({"system": "p1-struct-bc", "w_bc": -1}, "w_bc"),
    ({"system": "p1-struct-bc", "w_bc": 1, "weight": 0.5}, "lexical-only"),
    ({"system": "baseline-linear"}, "unknown system"),
])
def test_bad_index_arguments_are_refused(store, kw, match):
    with pytest.raises(tools.ToolError, match=match):
        tools.Tools(store.path).index(lexical_only=True, **kw)


def test_a_weight_outside_zero_to_one_is_refused(store, fakes):
    with pytest.raises(tools.ToolError, match="weight"):
        tools.Tools(store.path).index("p1-struct", weight=1.5)


def test_the_reranked_system_gets_the_reranker_unless_lexical_only(store, fakes):
    t = tools.Tools(store.path)
    info = t.index("p1-struct-bc-rr", w_bc=1, weight=0.5)
    assert info.rerank and info.prefix
    lex = t.index("p1-struct-bc-rr", lexical_only=True, w_bc=1)
    assert not lex.rerank
    res = tools.Tools(store.path).search(QUERY)
    assert res.fingerprint == lex.fingerprint


def test_a_missing_store_is_a_tool_error(tmp_path):
    with pytest.raises(tools.ToolError, match="no store"):
        tools.Tools(tmp_path / "nowhere")


# -- tuning records from the harness ----------------------------------------------------------


def write_record(path: Path, system: str, snapshot: str, w_bc: int, w, lexical_only: bool,
                 fingerprint: str = "0" * 64) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    data = {"config": {"track": "retrieval", "system": system, "lexical_only": lexical_only,
                       "fingerprint": fingerprint, "w": w, "corpus": "mini",
                       "settings": {"w_bc": w_bc, "store_snapshot": snapshot,
                                    "linear_w": w}}}
    (path / "retrieval.json").write_text(json.dumps(data))
    return path


def test_tuned_settings_come_from_a_harness_run_record(store, tmp_path, fakes):
    rec = write_record(tmp_path / "run", "p1-struct-bc", store.snapshot_id, 3, 0.35, False)
    t = tools.Tools(store.path)
    info = t.index("p1-struct-bc", tuning=rec)  # a run directory
    assert (info.w_bc, info.w) == (3, 0.35)
    assert info.w_bc_from == info.w_from == "tuning"
    assert info.tuning["path"] == str(rec / "retrieval.json")
    over = t.index("p1-struct-bc", tuning=rec / "retrieval.json", w_bc=1)
    assert (over.w_bc, over.w, over.w_bc_from, over.w_from) == (1, 0.35, "override", "tuning")


@pytest.mark.parametrize("change, match", [
    ({"system": "p1-struct"}, "p1-struct.*not p1-struct-bc"),
    ({"snapshot": "f" * 64}, "snapshot ffffffffffff.*--w-bc 3"),
])
def test_a_tuning_record_for_another_system_or_snapshot_is_refused(store, tmp_path, change,
                                                                   match):
    args = {"system": "p1-struct-bc", "snapshot": store.snapshot_id, **change}
    rec = write_record(tmp_path / "run", args["system"], args["snapshot"], 3, None, True)
    with pytest.raises(tools.ToolError, match=match):
        tools.Tools(store.path).index("p1-struct-bc", lexical_only=True, tuning=rec)


def test_a_lexical_only_record_has_no_weight_for_a_dense_index(store, tmp_path, fakes):
    rec = write_record(tmp_path / "run", "p1-struct-bc", store.snapshot_id, 2, None, True)
    with pytest.raises(tools.ToolError, match="fusion weight"):
        tools.Tools(store.path).index("p1-struct-bc", tuning=rec)
    info = tools.Tools(store.path).index("p1-struct-bc", tuning=rec, weight=0.25)
    assert (info.w_bc, info.w, info.w_from) == (2, 0.25, "override")


@pytest.mark.parametrize("content", ["not json", "{}", '{"config": {"track": "answers"}}'])
def test_an_unreadable_tuning_record_is_refused(store, tmp_path, content):
    (tmp_path / "r.json").write_text(content)
    with pytest.raises(tools.ToolError, match="tuning record"):
        tools.Tools(store.path).index("p1-struct-bc", lexical_only=True,
                                      tuning=tmp_path / "r.json")


@pytest.mark.parametrize("lexical_only", [True, False])
def test_the_tools_reproduce_a_harness_retrieval_run(tmp_path, monkeypatch, fakes,
                                                     lexical_only):
    """A real `adr-eval retrieval` run on mini: the tools load its tuning, get its
    fingerprint and return its ranked lists."""
    monkeypatch.setattr(systems, "make_embedding_cache",
                        lambda config: fake_cache(tmp_path / "emb"))
    monkeypatch.setattr(systems, "make_reranker", lambda config: fake_reranker())
    cfg = runner.load_config()
    cfg.update(index_dir=str(tmp_path / "index"), store_dir=str(tmp_path / "stores"),
               embedding_cache_dir=str(tmp_path / "emb"), cache_dir=str(tmp_path / "llm"))
    run_id = runner.run_retrieval("mini", "p1-struct-bc-rr", "dev", cfg, tmp_path / "runs",
                                  lexical_only=lexical_only)
    run = json.loads((tmp_path / "runs" / run_id / "retrieval.json").read_text())
    t = tools.Tools(tmp_path / "stores" / "mini")
    info = t.index("p1-struct-bc-rr", lexical_only=lexical_only,
                   tuning=tmp_path / "runs" / run_id)
    assert info.fingerprint == run["config"]["fingerprint"] and info.tuning["fingerprint_match"]
    items = {i.id: i for i in runner.load_golden("mini", runner.load_checked_corpus("mini"))}
    for row in run["rows"]:
        got = t.search(items[row["item_id"]].question)
        assert [h.chunk_id for h in got.hits] == row["ranked"]
        assert [h.score for h in got.hits] == row["scores"]


# -- search -------------------------------------------------------------------------------


def test_search_needs_an_index_for_the_head_snapshot(store):
    with pytest.raises(tools.ToolError, match="adr index"):
        tools.Tools(store.path).search(QUERY)
    lexical(store)
    extra = doc(b"# Extra\n\nA refund note added later.\n", "md", "file://extra.md")
    s = Store.open(store.path)
    s.add(*extra)
    s.commit()
    with pytest.raises(tools.ToolError, match="snapshot.*adr index"):
        tools.Tools(store.path).search(QUERY)


def test_search_returns_the_index_ranking_with_the_snapshot_on_every_hit(store):
    t = lexical(store, "p1-struct-bc", w_bc=1)
    idx = StoreIndex.build(store, Settings(w_bc=1, prefix=True), dense=False)
    for top in (1, 3, 10):
        res = t.search(QUERY, top=top)
        assert [(h.chunk_id, h.score) for h in res.hits] == idx.retrieve(QUERY, top=top)
        assert len(res.hits) == min(top, len(idx.retrieve(QUERY, top=100)))
    res = t.search(QUERY)
    assert res.snapshot == store.snapshot_id and res.fingerprint == idx.fingerprint
    keys = [(-h.score, h.chunk_id) for h in res.hits]
    assert keys == sorted(keys) and [h.rank for h in res.hits] == list(range(1, len(keys) + 1))
    for h in res.hits:
        c = idx.chunks[h.chunk_id]
        assert h.snapshot == store.snapshot_id
        assert (h.doc_id, h.char_start, h.char_end, h.breadcrumb) == (
            c.doc_id, c.char_start, c.char_end, c.breadcrumb)


def test_search_json_shape(store):
    d = lexical(store).search(QUERY, top=2).to_dict()
    assert set(d) == {"query", "top", "snapshot", "system", "lexical_only", "fingerprint", "w",
                      "hits"}
    assert set(d["hits"][0]) == {"rank", "chunk_id", "doc_id", "char_start", "char_end",
                                 "breadcrumb", "score", "snapshot"}
    json.dumps(d)


def test_a_dense_search_fuses_with_the_recorded_weight(store, fakes, tmp_path):
    t = tools.Tools(store.path)
    t.index("p1-struct", weight=0.3)
    idx = StoreIndex.build(store, Settings(w_bc=0), fake_cache(tmp_path / "emb"))
    got = tools.Tools(store.path).search(QUERY, top=5)
    assert [(h.chunk_id, h.score) for h in got.hits] == idx.retrieve(QUERY, w=0.3, top=5)


@pytest.mark.parametrize("top", [0, -1, 101])
def test_search_top_is_bounded(store, top):
    with pytest.raises(tools.ToolError, match="top"):
        lexical(store).search(QUERY, top=top)


def test_search_with_no_matching_words_returns_no_hits(store):
    assert lexical(store).search("zzz-unknown-word").hits == []


# -- read ---------------------------------------------------------------------------------


def a_doc(store: Store) -> str:
    return next(d for d in store.doc_ids() if store.source(d).format == "md")


def test_read_returns_the_exact_text_of_the_range(store):
    t = tools.Tools(store.path)
    d = a_doc(store)
    text = store.text(d)
    whole = t.read(d)
    assert (whole.text, whole.char_start, whole.char_end) == (text, 0, len(text))
    part = t.read(d, start=5, end=40)
    assert part.text == text[5:40] and part.text_sha256 == sha256_text(text[5:40])
    assert part.snapshot == store.snapshot_id and part.doc_id == d
    assert t.read(d, start=len(text) - 3).text == text[-3:]
    assert t.read(d, end=4).text == text[:4]


def test_read_an_element_and_a_chunk(store):
    t = lexical(store)
    d = a_doc(store)
    text = store.text(d)
    el = next(e for e in store.elements(d) if e.type == "section")
    r = t.read(d, element=el.element_id)
    assert r.text == text[el.char_start:el.char_end] and r.element_id == el.element_id
    hit = t.search(QUERY).hits[0]
    r = t.read(hit.doc_id, chunk=hit.chunk_id)
    assert r.text == store.text(hit.doc_id)[hit.char_start:hit.char_end]
    assert (r.chunk_id, r.char_start, r.char_end) == (hit.chunk_id, hit.char_start, hit.char_end)


def test_read_accepts_a_unique_id_prefix(store):
    t = tools.Tools(store.path)
    d = a_doc(store)
    assert t.read(d[:12], start=0, end=3).doc_id == d
    with pytest.raises(tools.ToolError, match="at least 8"):
        t.read(d[:4])


@pytest.mark.parametrize("kw, match", [
    ({"start": -1}, "out of range"),
    ({"start": 5, "end": 4}, "out of range"),
    ({"end": 10**9}, "out of range"),
    ({"element": "0" * 64}, "no element"),
    ({"start": 1, "element": "0" * 64}, "one of"),
    ({"chunk": "0" * 64, "element": "0" * 64}, "one of"),
])
def test_read_errors(store, kw, match):
    with pytest.raises(tools.ToolError, match=match):
        tools.Tools(store.path).read(a_doc(store), **kw)


def test_read_an_unknown_document_or_a_chunk_of_another(store):
    t = lexical(store)
    with pytest.raises(tools.ToolError, match="no document"):
        t.read("0" * 64)
    hit = t.search(QUERY).hits[0]
    other = next(d for d in store.doc_ids() if d != hit.doc_id)
    with pytest.raises(tools.ToolError, match="belongs to"):
        t.read(other, chunk=hit.chunk_id)
    with pytest.raises(tools.ToolError, match="no chunk"):
        t.read(hit.doc_id, chunk="0" * 64)
    el = store.elements(hit.doc_id)[0]
    with pytest.raises(tools.ToolError, match="no element"):
        t.read(other, element=el.element_id)


# -- grep ---------------------------------------------------------------------------------


def all_matches(store: Store, pattern: str, flags=re.MULTILINE):
    rx = re.compile(pattern, flags)
    return [(d, m.start(), m.end()) for d in store.doc_ids()
            for m in rx.finditer(store.text(d))]


def test_grep_orders_by_document_then_offset_and_re_slices(store):
    res = tools.Tools(store.path).grep(r"refund\w*")
    want = all_matches(store, r"refund\w*")
    assert [(m.doc_id, m.char_start, m.char_end) for m in res.matches] == want
    assert len(want) > 3 and not res.truncated
    for m in res.matches:
        text = store.text(m.doc_id)
        assert m.match == text[m.char_start:m.char_end] and m.snapshot == store.snapshot_id
        assert m.match in m.context and "\n" not in m.context
        assert m.line == text.count("\n", 0, m.char_start) + 1
    assert res.snapshot == store.snapshot_id


def test_grep_is_capped_by_max(store):
    want = all_matches(store, r"\bthe\b", re.MULTILINE | re.IGNORECASE)
    res = tools.Tools(store.path).grep(r"\bthe\b", max=3, ignore_case=True)
    assert [(m.doc_id, m.char_start, m.char_end) for m in res.matches] == want[:3]
    assert res.truncated
    full = tools.Tools(store.path).grep(r"\bthe\b", max=len(want), ignore_case=True)
    assert len(full.matches) == len(want) and not full.truncated


def test_grep_default_cap_is_100():
    assert tools.GREP_MAX == 100


def test_grep_in_one_document(store):
    d = a_doc(store)
    res = tools.Tools(store.path).grep("e", doc=d[:12], max=1000)
    assert {m.doc_id for m in res.matches} == {d} and res.doc == d
    assert len(res.matches) == store.text(d).count("e")


def test_grep_context_is_clipped_around_the_match(tmp_path):
    long_line = ("word " * 200 + "NEEDLE" + " word" * 200).encode()
    s = Store.create(tmp_path / "s")
    s.add(*doc(long_line, "txt", "file://long.txt"))
    s.commit()
    m = tools.Tools(tmp_path / "s").grep("NEEDLE").matches[0]
    assert "NEEDLE" in m.context and len(m.context) <= 2 * tools.CONTEXT_CHARS + 6 + 2
    assert m.context.startswith("…") and m.context.endswith("…")


@pytest.mark.parametrize("pattern, match", [
    ("(", "bad regular expression"),
    ("", "empty"),
    ("a*", "empty string"),
    ("x|", "empty string"),
    ("^", "empty string"),
    (r"\b", "empty string"),
    (r"(?=refund)", "empty string"),
])
def test_grep_refuses_bad_and_empty_matching_patterns(store, pattern, match):
    with pytest.raises(tools.ToolError, match=match):
        tools.Tools(store.path).grep(pattern)


@pytest.mark.parametrize("kw, match", [({"max": 0}, "max"), ({"doc": "0" * 64}, "no document")])
def test_grep_argument_errors(store, kw, match):
    with pytest.raises(tools.ToolError, match=match):
        tools.Tools(store.path).grep("refund", **kw)


# -- the retrieval log --------------------------------------------------------------------


def test_every_call_appends_exactly_one_log_line(store):
    t = tools.Tools(store.path)
    d = a_doc(store)
    info = t.index("p1-struct", lexical_only=True)
    res = t.search(QUERY, top=3)
    rd = t.read(d, start=2, end=9)
    gr = t.grep("refund", max=2)
    lines = log_lines(store)
    assert [ln["tool"] for ln in lines] == ["index", "search", "read", "grep"]
    for ln in lines:
        assert set(ln) >= {"time", "tool", "args", "snapshot", "results"}
        assert ln["snapshot"] == store.snapshot_id
        assert datetime.fromisoformat(ln["time"]).utcoffset().total_seconds() == 0
        assert "error" not in ln
    idx, srch, rdl, grl = lines
    assert idx["args"] == {"system": "p1-struct", "lexical_only": True, "w_bc": None,
                           "weight": None, "tuning": None}
    assert idx["results"] == [info.fingerprint]
    assert srch["args"] == {"query": QUERY, "top": 3}
    assert srch["results"] == [h.chunk_id for h in res.hits]
    assert srch["index"] == info.fingerprint
    assert rdl["args"] == {"doc_id": d, "start": 2, "end": 9, "element": None, "chunk": None}
    assert rdl["results"] == [[d, rd.char_start, rd.char_end]]
    assert grl["args"] == {"pattern": "refund", "doc": None, "max": 2, "ignore_case": False}
    assert grl["results"] == [[m.doc_id, m.char_start, m.char_end] for m in gr.matches]


def test_a_failed_call_logs_one_line_with_the_error(store):
    t = tools.Tools(store.path)
    with pytest.raises(tools.ToolError):
        t.grep("(")
    with pytest.raises(tools.ToolError):
        t.read("0" * 64)
    lines = log_lines(store)
    assert [ln["tool"] for ln in lines] == ["grep", "read"]
    assert all(ln["results"] == [] and ln["error"] for ln in lines)


def test_the_log_does_not_change_results(store):
    t = lexical(store)
    first = t.search(QUERY).to_dict()
    (store.path / "log" / "retrieval.jsonl").write_text("garbage\n" * 3)
    assert tools.Tools(store.path).search(QUERY).to_dict() == first
    assert t.grep("refund").to_dict() == tools.Tools(store.path).grep("refund").to_dict()


def test_concurrent_calls_write_whole_lines(store):
    def work():
        t = tools.Tools(store.path)
        for _ in range(25):
            t.grep("refund", max=50)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    lines = log_lines(store)
    assert len(lines) == 100 and all(ln["tool"] == "grep" for ln in lines)


# -- the command line ---------------------------------------------------------------------


def run(capsys, *argv) -> tuple[int, str, str]:
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out, err


def test_cli_index_search_read_grep_json(store, capsys):
    s = store.path
    code, out, _ = run(capsys, "index", s, "--system", "p1-struct-bc", "--w-bc", 2,
                       "--lexical-only", "--json")
    assert code == 0
    info = json.loads(out)
    assert info["snapshot"] == store.snapshot_id and HEX64.match(info["fingerprint"])
    code, out, _ = run(capsys, "search", QUERY, "--store", s, "--top", 2, "--json")
    res = json.loads(out)
    assert code == 0 and len(res["hits"]) == 2 and res["fingerprint"] == info["fingerprint"]
    top = res["hits"][0]
    code, out, _ = run(capsys, "read", top["doc_id"], "--store", s, "--chunk", top["chunk_id"],
                       "--json")
    rd = json.loads(out)
    assert code == 0 and rd["text"] == store.text(top["doc_id"])[top["char_start"]:
                                                                  top["char_end"]]
    code, out, _ = run(capsys, "grep", "Refund", "--store", s, "--ignore-case", "--max", 4,
                       "--json")
    gr = json.loads(out)
    assert code == 0 and len(gr["matches"]) == 4 and gr["truncated"]
    assert len(log_lines(store)) == 4


def test_cli_tables_are_short(store, capsys):
    s = store.path
    code, out, _ = run(capsys, "index", s, "--system", "p1-struct", "--lexical-only")
    assert code == 0 and store.snapshot_id[:12] in out
    code, out, _ = run(capsys, "search", QUERY, "--store", s)
    assert code == 0 and store.snapshot_id[:12] in out
    assert all(len(line) <= 160 for line in out.splitlines())
    d = a_doc(store)
    code, out, _ = run(capsys, "read", d, "--store", s, "--start", 0, "--end", 21)
    assert code == 0 and store.text(d)[:21] in out and store.snapshot_id[:12] in out
    code, out, _ = run(capsys, "grep", "refund", "--store", s)
    assert code == 0 and "refund" in out and store.snapshot_id[:12] in out


def test_cli_store_defaults_from_the_corpus_name(store, capsys, monkeypatch, tmp_path):
    (tmp_path / ".cache" / "store").mkdir(parents=True)
    store.path.rename(tmp_path / ".cache" / "store" / "mini")
    monkeypatch.chdir(tmp_path)
    code, out, _ = run(capsys, "index", "mini", "--system", "p1-struct", "--lexical-only",
                       "--json")
    assert code == 0 and json.loads(out)["snapshot"] == store.snapshot_id
    code, out, _ = run(capsys, "grep", "refund", "--corpus", "mini", "--json")
    assert code == 0 and json.loads(out)["matches"]


@pytest.mark.parametrize("argv, match", [
    (["read", "0" * 64], "no document"),
    (["read", "DOC", "--start", "5", "--end", "1"], "out of range"),
    (["grep", "("], "bad regular expression"),
    (["grep", "a*"], "empty string"),
    (["search", QUERY], "adr index"),
    (["index", "STORE", "--system", "p1-struct-bc", "--lexical-only"], "w_bc"),
])
def test_cli_errors_exit_2_with_a_clear_message(store, capsys, argv, match):
    argv = [a.replace("DOC", a_doc(store)).replace("STORE", str(store.path)) for a in argv]
    if argv[0] != "index":
        argv += ["--store", str(store.path)]
    code, out, err = run(capsys, *argv)
    assert code == 2 and out == "" and re.search(match, err) and err.startswith("error:")


def test_cli_without_a_store_exits_2(tmp_path, capsys):
    code, _, err = run(capsys, "grep", "x", "--store", tmp_path / "none")
    assert code == 2 and "no store" in err
