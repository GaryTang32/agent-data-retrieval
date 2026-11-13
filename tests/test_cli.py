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
