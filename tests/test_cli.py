"""CLI refusals: clear messages and exit code 2 instead of tracebacks."""

import json
import logging
from pathlib import Path

import pytest

from adr_eval.cli import main

MINI = Path(__file__).parent / "fixtures" / "mini"


@pytest.fixture
def no_research_files(tmp_path, monkeypatch):
    """The research manifest resolved against an empty checkout (no PDFs, no reports)."""
    monkeypatch.setattr("adr_eval.corpora.registry.corpus_root", lambda name: tmp_path)
    return tmp_path


@pytest.mark.parametrize("argv", [
    ["fetch", "research"],
    ["index", "research"],
    ["run", "research", "--system", "baseline-rrf", "--stub", "--dry-run"],
    ["golden", "research", "--verify"],
])
def test_research_without_local_files_is_a_clear_refusal(no_research_files, argv, capsys):
    assert main(argv) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "missing locally" in err and "papers/" in err
    assert "scripts/download_papers.py" in err
    assert "git checkout papers/manifest.csv" in err


@pytest.mark.parametrize("corpus,hint", [
    ("bench", "local only"),
    ("research", "local only"),
    ("gov", "adr-eval golden gov --gen"),
])
def test_verify_without_items_names_the_path(tmp_path, monkeypatch, capsys, corpus, hint):
    path = tmp_path / corpus / "items.jsonl"
    monkeypatch.setattr("adr_eval.runner.golden_items_path", lambda c: path)
    monkeypatch.setattr("adr_eval.cli.check_local_files", lambda name: None)
    assert main(["golden", corpus, "--verify"]) == 2
    err = capsys.readouterr().err
    assert str(path) in err and hint in err
    assert f"adr-eval golden {corpus} --gen" in err


@pytest.mark.parametrize("flag", [["--generator", "x"], ["--judge", "x"], ["--max-calls", "3"],
                                  ["--overwrite"]])
def test_verify_rejects_generation_options(flag, capsys):
    with pytest.raises(SystemExit) as e:
        main(["golden", "mini", "--verify", *flag])
    assert e.value.code == 2
    assert flag[0] in capsys.readouterr().err


def test_verify_reports_whole_set_failures(tmp_path, monkeypatch, capsys):
    lines = (MINI / "golden.jsonl").read_text(encoding="utf-8").splitlines()
    path = tmp_path / "items.jsonl"
    path.write_text("\n".join([*lines, lines[-1]]) + "\n", encoding="utf-8")
    monkeypatch.setattr("adr_eval.runner.golden_items_path", lambda corpus: path)
    assert main(["golden", "mini", "--verify"]) == 1
    dup = json.loads(lines[-1])["id"]
    assert f"{dup}: duplicate_id" in capsys.readouterr().err


def test_verify_refuses_excluded_items(tmp_path, monkeypatch, capsys):
    (tmp_path / "review_exclusions.json").write_text('{"mini-id-1": "answerable"}')
    monkeypatch.setattr("adr_eval.runner.golden_dir", lambda corpus: tmp_path)
    assert main(["golden", "mini", "--verify"]) == 1
    assert "mini-id-1: review_excluded" in capsys.readouterr().err


def _stub_gen(tmp_path, monkeypatch):
    from adr_eval.llm import StubClient

    monkeypatch.setattr("adr_eval.runner.make_client",
                        lambda name, profiles, cache: StubClient(lambda s, u, r: "not json"))
    monkeypatch.setattr("adr_eval.runner.golden_dir", lambda corpus: tmp_path / corpus)


def test_gen_shows_the_per_type_tally_on_stderr(tmp_path, monkeypatch, capsys):
    _stub_gen(tmp_path, monkeypatch)
    assert main(["golden", "mini", "--gen"]) == 0
    err = capsys.readouterr().err
    assert "mini factoid: requested=50" in err and "generation_errors=" in err
    assert not logging.getLogger("adr_eval.golden.generate").handlers  # removed afterwards


def test_gen_passes_the_review_exclusions_file(tmp_path, monkeypatch):
    _stub_gen(tmp_path, monkeypatch)
    seen = {}

    def fake(corpus, client, **kw):
        seen.update(kw)
        return [], []

    monkeypatch.setattr("adr_eval.golden.generate.generate_corpus", fake)
    assert main(["golden", "mini", "--gen"]) == 0
    assert seen["exclusions"] == {}  # no file, no exclusions
    (tmp_path / "mini" / "review_exclusions.json").write_text('{"mini-x-1": "reviewed"}')
    assert main(["golden", "mini", "--gen", "--overwrite"]) == 0
    assert seen["exclusions"] == {"mini-x-1": "reviewed"}


def test_gen_refuses_to_overwrite_a_frozen_set(tmp_path, monkeypatch, capsys):
    made = []
    monkeypatch.setattr("adr_eval.runner.make_client",
                        lambda name, profiles, cache: made.append(name))
    monkeypatch.setattr("adr_eval.runner.golden_dir", lambda corpus: tmp_path / corpus)
    d = tmp_path / "mini"
    d.mkdir()
    (d / "items.jsonl").write_text("frozen\n")
    assert main(["golden", "mini", "--gen"]) == 2
    err = capsys.readouterr().err.strip()
    assert len(err.splitlines()) == 1
    assert "frozen" in err and "--overwrite" in err and str(d / "items.jsonl") in err
    assert made == []  # refused before any client was made or call sent
    assert (d / "items.jsonl").read_text() == "frozen\n" and not (d / "rejected.jsonl").exists()


def test_gen_overwrite_replaces_an_existing_set(tmp_path, monkeypatch):
    _stub_gen(tmp_path, monkeypatch)
    d = tmp_path / "mini"
    d.mkdir()
    (d / "items.jsonl").write_text("frozen\n")
    assert main(["golden", "mini", "--gen", "--overwrite"]) == 0
    assert (d / "items.jsonl").read_text() != "frozen\n" and (d / "rejected.jsonl").is_file()


def test_extraction_failure_names_the_file(tmp_path, monkeypatch, capsys):
    import adr_eval.corpora.base as base
    from adr_eval.corpora.base import ExtractionError, load_corpus

    def broken(data, fmt):
        raise ValueError("bad bytes")

    monkeypatch.setattr(base, "extract_text", broken)
    with pytest.raises(ExtractionError, match=r"escalation_guide\.md"):
        load_corpus(MINI / "manifest.json", MINI)
    assert main(["index", "mini"]) == 2
    err = capsys.readouterr().err
    assert "extract" in err and "bad bytes" in err and "Traceback" not in err


# -- `adr tables build|show|gate`, `adr query`, `adr sql` (Phase 3, Task 6) ----------------------
# fixture stores under tmp_path (the gov table fixture of tests/store/test_tables_tools.py)

def adr(argv, capsys) -> tuple[int, str, str]:
    from adr_store import cli as adr_cli

    code = adr_cli.main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def tables_store(tmp_path):
    from adr_store import acl
    from tests.store.test_tables_tools import make

    s = make(tmp_path / "s", tables=False)
    config = s.path.parent / f"{s.path.name}-acl"   # synced again with the real clock
    acl.sync(s.path, config / "directory.json", config / "policy.json", clock=acl.utc_now)
    return s.path


def gold_dir(path, items):
    from adr_eval.models import write_items

    path.mkdir()
    write_items(path / "items.jsonl", items)
    return path


FR_IDS = [f"2024-0000{i}" for i in range(1, 8)]


def test_adr_tables_build_gate_show(tables_store, tmp_path, capsys):
    from adr_store.tables.overlay import read_head
    from tests.store.test_tables_gate import item

    code, out, err = adr(["tables", "build", "--store", tables_store], capsys)
    assert code == 0, err
    cand = out.splitlines()[0]
    assert len(cand) == 64 and "gov" in out and "adr tables gate" in out
    assert read_head(tables_store) is None                      # a build is only a candidate
    a = gold_dir(tmp_path / "a", [item("g1", value=5.0)])
    b = gold_dir(tmp_path / "b", [item("g2", op="list", kind="set", value=FR_IDS,
                                       filters={"year": 2024})])
    code, out, err = adr(["tables", "gate", "--store", tables_store, "--candidate", cand,
                          "--gold", a, "--gold", b, "--max-flips", 0], capsys)
    assert code == 0, err
    assert "promoted" in out and "2 of 2" in out and read_head(tables_store) == cand
    code, out, _ = adr(["tables", "show", "--store", tables_store], capsys)
    assert code == 0 and cand[:12] in out and "fr_documents" in out
    code, out, _ = adr(["tables", "show", "--store", tables_store, "--json"], capsys)
    shown = json.loads(out)
    assert shown["tables_id"] == cand and shown["head"] == cand
    assert shown["manifest"]["corpus"] == "gov"
    assert [t["name"] for t in shown["semantic"]["tables"]][0] == "agencies"
    assert "report" not in out                                   # reports are not shown


def test_adr_tables_gate_refuses_flips_and_keeps_head(tables_store, tmp_path, capsys):
    from adr_store.tables.overlay import read_head
    from tests.store.test_tables_gate import derived, item, retype

    gold = gold_dir(tmp_path / "g", [item("g1", value=5.0)])
    _, out, _ = adr(["tables", "build", "--store", tables_store], capsys)
    head = out.splitlines()[0]
    assert adr(["tables", "gate", "--store", tables_store, "--candidate", head, "--gold", gold,
                "--max-flips", 0], capsys)[0] == 0
    worse = derived(tables_store, head, retype(1))
    code, out, err = adr(["tables", "gate", "--store", tables_store, "--candidate", worse,
                          "--gold", gold, "--max-flips", 0, "--json"], capsys)
    assert code == 1 and json.loads(out)["flips"] == ["g1"] and read_head(tables_store) == head


def test_adr_tables_build_options(tables_store, tmp_path, capsys, monkeypatch):
    from adr_eval import runner
    from adr_store.tables import build as tables_build
    from tests.store.tables_fixtures import FR_DOCS, MANIFEST, make_tables_store

    seen = []
    real = tables_build.build_tables

    def spy(path, corpus, **kw):
        seen.append((corpus, kw))
        return real(path, corpus, **kw)

    monkeypatch.setattr(tables_build, "build_tables", spy)
    generator = runner.load_config()["generator"]
    real_config = runner.load_config

    def no_config():
        raise AssertionError("the generator profile is resolved only for --with-extraction")

    # a metadata build resolves no generator profile (it calls no model)
    monkeypatch.setattr(runner, "load_config", no_config)
    assert adr(["tables", "build", "--store", tables_store], capsys)[0] == 0
    assert seen[-1] == ("gov", {"with_extraction": False, "generator_profile": None,
                                "max_calls": 0})
    assert adr(["tables", "build", "--store", tables_store, "--generator", "claude_code_opus",
                "--max-calls", 3, "--tables-for", "gov"], capsys)[0] == 0
    assert seen[-1] == ("gov", {"with_extraction": False,
                                "generator_profile": "claude_code_opus", "max_calls": 3})
    monkeypatch.setattr(runner, "load_config", real_config)
    code, _, err = adr(["tables", "build", "--store", tables_store, "--with-extraction"], capsys)
    assert code == 2 and "extraction tables are not built yet" in err
    assert seen[-1] == ("gov", {"with_extraction": True, "generator_profile": generator,
                                "max_calls": 0})
    # the corpus comes from the store's documents, or --tables-for when both are there
    research = make_tables_store(tmp_path / "r", [MANIFEST])
    assert adr(["tables", "build", "--store", research.path], capsys)[0] == 0
    assert seen[-1][0] == "research"
    both = make_tables_store(tmp_path / "both", [*FR_DOCS, MANIFEST])
    code, _, err = adr(["tables", "build", "--store", both.path], capsys)
    assert code == 2 and "--tables-for" in err
    assert adr(["tables", "build", "--store", both.path, "--tables-for", "research"],
               capsys)[0] == 0
    # --corpus keeps its meaning (the real store); it is not a tables option here
    with pytest.raises(SystemExit):
        adr(["tables", "build", "--store", tables_store, "--corpus", "gov"], capsys)


def test_adr_query_and_sql(tables_store, capsys):
    _, out, _ = adr(["tables", "build", "--store", tables_store], capsys)
    from adr_store.tables.gate import gate

    assert gate(tables_store, out.splitlines()[0], [], 0).promoted
    code, out, err = adr(["query", "--store", tables_store, "--table", "fr_documents", "--op",
                          "count_by", "--fields", "type", "--as", "user:auditor"], capsys)
    assert code == 0, err
    assert "Proposed Rule" in out and "Rule" in out
    code, out, _ = adr(["query", "--store", tables_store, "--table", "fr_documents", "--op",
                        "count_by", "--fields", "type", "--as", "user:auditor", "--json"], capsys)
    assert json.loads(out)["groups"] == [{"value": "Proposed Rule", "count": 2},
                                         {"value": "Rule", "count": 4}]
    code, out, _ = adr(["query", "--store", tables_store, "--table", "fr_documents",
                        "--filters", '{"type": "Rule"}', "--op", "lookup", "--fields", "id",
                        "--order=-id", "--limit", 2, "--include-superseded", "--json"], capsys)
    got = json.loads(out)
    assert code == 0 and [r["row"]["id"] for r in got["rows"]] == ["2024-00007", "2024-00006"]
    assert got["truncated"] and got["applicability_filters"]["include_superseded"]
    code, out, _ = adr(["query", "--store", tables_store, "--table", "fr_documents", "--op",
                        "list", "--as-of", "2024-06-01"], capsys)
    assert code == 0 and "2024-00001" in out and "2024-00002" not in out
    code, out, err = adr(["sql", "--store", tables_store,
                          "SELECT type, count(*) FROM fr_documents GROUP BY type",
                          "--as", "user:acme-0", "--json"], capsys)
    assert code == 0, err
    assert json.loads(out)["rows"] == [["Proposed Rule", 2], ["Rule", 1]]
    code, out, _ = adr(["sql", "--store", tables_store, "SELECT count(*) FROM fr_documents"],
                       capsys)
    assert code == 0 and "6" in out
    code, _, err = adr(["sql", "--store", tables_store, "DELETE FROM fr_documents"], capsys)
    assert code == 2 and err.strip() == "error: sql refused (syntax): one SELECT statement over " \
                                        "the listed tables"
    code, _, err = adr(["query", "--store", tables_store, "--table", "fr_documents",
                        "--filters", "{nope"], capsys)
    assert code == 2 and "--filters" in err
    code, _, err = adr(["query", "--store", tables_store, "--table", "fr_documents", "--as",
                        "user:ghost"], capsys)
    assert code == 2 and "access denied (F4)" in err


def test_adr_query_without_tables_names_the_commands(tables_store, capsys):
    code, _, err = adr(["query", "--store", tables_store, "--table", "fr_documents"], capsys)
    assert code == 2 and "run `adr tables build` and `adr tables gate`" in err
    code, _, err = adr(["tables", "show", "--store", tables_store], capsys)
    assert code == 2 and "adr tables gate" in err
