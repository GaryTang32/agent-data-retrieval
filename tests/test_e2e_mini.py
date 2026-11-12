"""End to end over the mini fixture corpus with the stub model: no network, no keys."""

import json
from pathlib import Path

import pytest

from adr_eval.cli import main
from adr_eval.corpora import REPO_ROOT

MINI = Path(__file__).parent / "fixtures" / "mini"
# Writable repo state that tests must leave alone (the fastembed model store is read-only).
GUARDED = [REPO_ROOT / ".cache" / d for d in ("index", "llm", "emb")] + [
    REPO_ROOT / d for d in ("runs", "golden", "results")]


def _state() -> dict[str, int]:
    return {str(p): p.stat().st_mtime_ns for root in GUARDED if root.exists()
            for p in [root, *root.rglob("*")]}


@pytest.mark.slow
def test_e2e_mini_with_stub_model(tmp_path):
    rc = main(["run", "mini", "--system", "baseline-rrf", "--split", "test", "--repeats", "2",
               "--out", str(tmp_path), "--stub"])
    run_dir = next(tmp_path.iterdir())
    rep = json.loads((run_dir / "report.json").read_text())
    assert rc == 0 and rep["determinism"]["retrieval_identity_rate"] == 1.0
    assert set(rep["end_to_end"]["penalised"]) == {"0.5", "0.75", "0.9"}
    assert rep["judge"]["human_kappa"] is None
    assert (run_dir / "report.md").read_text().startswith("# ")
    assert json.loads((run_dir / "config.json").read_text())["stub"] is True


@pytest.mark.slow
def test_e2e_leaves_repo_state_untouched(tmp_path):
    before = _state()
    assert main(["run", "mini", "--system", "baseline-rrf", "--split", "test", "--repeats", "1",
                 "--out", str(tmp_path), "--stub"]) == 0
    assert main(["index", "mini", "--rebuild"]) == 0  # always writes: must not be the repo's
    assert _state() == before


@pytest.mark.slow
def test_cli_report_compare(tmp_path, capsys):
    for system in ("baseline-rrf", "baseline-linear"):
        assert main(["run", "mini", "--system", system, "--split", "test", "--repeats", "1",
                     "--out", str(tmp_path), "--stub"]) == 0
    a, b = sorted(p.name for p in tmp_path.iterdir())
    capsys.readouterr()
    assert main(["report", a, "--compare", b, "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "McNemar" in out
    cmp = json.loads((tmp_path / a / f"compare-{b}.json").read_text())
    assert 0.0 <= cmp["mcnemar"]["p"] <= 1.0


@pytest.mark.slow
def test_cli_index_reports_fingerprint(capsys):
    assert main(["index", "mini"]) == 0
    assert "fingerprint" in capsys.readouterr().out


def test_cli_fetch_mini_is_noop():
    assert main(["fetch", "mini"]) == 0


def test_cli_golden_verify_mini(capsys):
    assert main(["golden", "mini", "--verify"]) == 0
    assert "0 failed" in capsys.readouterr().out


def test_cli_golden_verify_reports_schema_violation(tmp_path, monkeypatch, capsys):
    lines = (MINI / "golden.jsonl").read_text().splitlines()
    bad = json.loads(lines[0])
    bad["qtype"] = "nonsense"
    path = tmp_path / "items.jsonl"
    path.write_text("\n".join([json.dumps(bad), *lines[1:]]) + "\n")
    monkeypatch.setattr("adr_eval.runner.golden_items_path", lambda corpus: path)
    assert main(["golden", "mini", "--verify"]) == 1
    assert bad["id"] in capsys.readouterr().err


def test_cli_golden_gen_writes_items_and_rejected(tmp_path, monkeypatch):
    from adr_eval.llm import StubClient

    monkeypatch.setattr("adr_eval.runner.make_client",
                        lambda name, profiles, cache: StubClient(lambda s, u, r: "not json"))
    monkeypatch.setattr("adr_eval.runner.golden_dir", lambda corpus: tmp_path / corpus)
    assert main(["golden", "mini", "--gen"]) == 0
    assert (tmp_path / "mini" / "items.jsonl").is_file()
    assert (tmp_path / "mini" / "rejected.jsonl").is_file()


def test_cli_requires_a_golden_mode():
    with pytest.raises(SystemExit):
        main(["golden", "mini"])


def test_cli_golden_verify_reads_unicode_line_separators(tmp_path, monkeypatch, capsys):
    """An item whose text holds U+2028 is one JSONL line, not a schema violation."""
    lines = (MINI / "golden.jsonl").read_text(encoding="utf-8").splitlines()
    item = json.loads(lines[0])
    item["question"] += " \u2028(second line)"
    path = tmp_path / "items.jsonl"
    path.write_text("\n".join([json.dumps(item, ensure_ascii=False), *lines[1:]]) + "\n",
                    encoding="utf-8")
    monkeypatch.setattr("adr_eval.runner.golden_items_path", lambda corpus: path)
    assert main(["golden", "mini", "--verify"]) == 0
    assert "0 failed" in capsys.readouterr().out
