"""Gate fail-closed probes (Phase 4 spec §15.4; criteria G1, G2, G3; Task 18): 12 conditions ×
the 4 gated tools × 3 seeded requests against a real gate process over a shadow of the fixture
store with promoted bindings (`make_units_built_with_bindings`), and the unwritable log
counted separately. No network, no model call."""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

import pytest

from adr_eval.probes import gate as pg
from adr_eval.probes.gate import gate_failclosed
from adr_store.gate import client as gate_client
from tests.store.units_fixtures import make_units_built_with_bindings


def _tree(path: Path) -> dict[str, str]:
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(path.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def probed(tmp_path_factory):
    root = tmp_path_factory.mktemp("gate-probes")
    store = make_units_built_with_bindings(root / "store")
    before = _tree(store.path)
    logs: dict = {}
    rows = gate_failclosed(store.path, root / "work", logs=logs)
    return store, root, rows, logs, before


def test_gate_failclosed_probes_144_all_deny(probed):
    store, root, rows, logs, before = probed
    main = [r for r in rows if not r["separate"]]
    assert len(main) == len(pg.CONDITIONS) * len(pg.TOOLS) * pg.SEEDS == 144 >= 120
    assert all(r["outcome"] != "allow" and not r["executed"] for r in rows)
    assert Counter(r["condition"] for r in main) == dict.fromkeys(pg.CONDITIONS, 12)
    assert Counter(r["tool"] for r in main) == dict.fromkeys(pg.TOOLS, 36)
    sep = [r for r in rows if r["separate"]]
    assert len(sep) == 12 and {r["condition"] for r in sep} == {"unwritable_log"}
    # every seeded request was an allow the environment executed, before any fault
    assert len(logs["baseline"]) == 12
    assert all(r["outcome"] == "allow" and r["executed"] for r in logs["baseline"])
    # the gate's own refusals carry the fail-closed rule; token faults are refused by the
    # environment on a genuine allow
    fc = [["adr.gate.fail-closed@1", "1"]]
    for r in main:
        if r["condition"] in ("forged_token", "replayed_token", "mismatched_token"):
            assert r["gate_decision"] == "allow" and "refused" in r["reason"]
        else:
            assert r["rule_ids"] == fc, r
    reasons = {c: {r["reason"] for r in main if r["condition"] == c} for c in pg.CONDITIONS}
    assert all("not running" in x for x in reasons["killed"])
    assert all("deadline" in x for x in reasons["timeout"])
    assert all("oversized" in x for x in reasons["oversized"])
    assert all("unknown tool" in x for x in reasons["unknown_tool"])
    assert all("unknown target" in x for x in reasons["unknown_target"])
    targets = {r["seed"]: r for r in main if r["condition"] == "unknown_target"}
    assert set(targets) == {0, 1, 2}         # an absent section, an absent draw, § 117.5
    assert all("no longer verifies" in x for x in reasons["manifest_altered"])
    assert all("refused to start" in x for x in reasons["unsigned_binding"])
    assert all("stale units" in x for x in reasons["stale_units"])
    assert all("cannot be written" in r["reason"] for r in sep)
    s = pg.summarize(rows)
    assert s["total"] == {"n": 144, "allowed": 0, "executed": 0, "passed": 144}
    assert s["separate"] == {"n": 12, "allowed": 0, "executed": 0, "passed": 12}
    # the store itself was never written: every fault was planted in the shadow
    assert _tree(store.path) == before


def test_the_probe_log_verifies_and_replays(probed):                              # G1, G3
    store, root, rows, logs, before = probed
    checks = pg.log_checks(logs["log"], root / "work" / "shadow", logs["expected_lines"])
    assert checks["g1"]["chain_ok"] and checks["g1"]["lines"] == logs["expected_lines"] > 100
    # a probe log missing its last line fails both checks once the count is known
    log = Path(logs["log"])
    raw = log.read_bytes()
    try:
        log.write_bytes(raw[:raw.rstrip(b"\n").rfind(b"\n") + 1])
        cut = pg.log_checks(log, root / "work" / "shadow", logs["expected_lines"])
        assert not cut["g1"]["chain_ok"] and cut["g3"]["differ"] == 1
    finally:
        log.write_bytes(raw)
    assert checks["g3"]["differ"] == 0 and checks["g3"]["identical"] == checks["g1"]["lines"]


def test_a_gate_that_fails_open_is_caught(tmp_path, monkeypatch):
    """A planted fault: a client that accepts any allow (no token check, no single use)."""
    store = make_units_built_with_bindings(tmp_path / "store")
    monkeypatch.setattr(gate_client.GateClient, "check_token",
                        lambda self, request, reply: reply.get("decision") == "allow")
    rows = gate_failclosed(store.path, tmp_path / "work")
    bad = {r["condition"] for r in rows if r["executed"]}
    assert {"forged_token", "replayed_token", "mismatched_token"} <= bad


def _overlay(tmp_path: Path, file: str, old: str, new: str) -> Path:
    """A copy of `adr_store` with one planted fault, put first on the gate subprocess's path
    (the editable install is a plain path entry, so PYTHONPATH wins); the repo is never
    edited."""
    import shutil

    import adr_store

    root = tmp_path / "overlay"
    shutil.copytree(Path(adr_store.__file__).parent, root / "adr_store",
                    ignore=shutil.ignore_patterns("__pycache__"))
    path = root / "adr_store" / file
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1
    path.write_text(text.replace(old, new), encoding="utf-8")
    return root


def test_a_gate_that_allows_a_malformed_request_is_reported(tmp_path, monkeypatch, capsys):
    """I3: with the extra-argument check removed from the gate, the request carrying a fact in
    its arguments is allowed; the probe records the gate's allow (and the environment executes
    it), so the summary and the CLI report the failure."""
    import json
    import os

    from adr_eval.cli import main

    store = make_units_built_with_bindings(tmp_path / "store")
    overlay = _overlay(tmp_path, "bindings/decide.py", "    if extra:\n",
                       "    if extra and False:\n")
    monkeypatch.setenv("PYTHONPATH", f"{overlay}{os.pathsep}{os.environ.get('PYTHONPATH', '')}")
    rows = gate_failclosed(store.path, tmp_path / "work")
    bad = [r for r in rows if r["outcome"] == "allow"]
    assert bad and {(r["condition"], r["seed"]) for r in bad} == {("malformed", 1)}
    assert all(r["gate_decision"] == "allow" and r["executed"] for r in bad)
    s = pg.summarize(rows)
    assert s["total"]["allowed"] == len(bad) == 4 and s["total"]["passed"] == 140
    assert s["conditions"]["malformed"]["allowed"] == 4
    out = tmp_path / "runs"
    assert main(["probes", "gate-failclosed", "gov", "--store", str(store.path), "--clones",
                 str(tmp_path / "w2"), "--out", str(out)]) == 1
    (run,) = out.glob("probes-gate-failclosed-gov-*")
    summary = json.loads((run / "summary.json").read_text())["summary"]
    assert summary["total"]["allowed"] == 4 and "4 allowed" in (run / "summary.md").read_text()
    capsys.readouterr()


def test_without_bindings_there_is_nothing_to_probe(tmp_path):
    from tests.store.units_fixtures import make_units_built

    store = make_units_built(tmp_path / "s")
    with pytest.raises(ValueError, match="no bindings/HEAD"):
        gate_failclosed(store.path, tmp_path / "work")


def test_the_cli_runs_the_gate_probes_and_writes_counts(probed, tmp_path, capsys):
    import json

    from adr_eval.cli import main

    store = probed[0]
    out = tmp_path / "runs"
    args = ["probes", "gate-failclosed", "gov", "--store", str(store.path), "--clones",
            str(tmp_path / "work"), "--out", str(out)]
    assert [main(args) for _ in range(2)] == [0, 0]
    a, b = sorted(out.glob("probes-gate-failclosed-gov-*"))
    assert (a / "results.json").read_bytes() == (b / "results.json").read_bytes()
    s = json.loads((a / "summary.json").read_text())["summary"]
    assert s["total"]["n"] == 144 and s["total"]["executed"] == 0
    assert s["g1"]["chain_ok"] and s["g3"]["differ"] == 0
    assert (a / "gate.jsonl").stat().st_size > 0 and not (tmp_path / "work").exists()
    text = (a / "summary.md").read_text()
    assert "G2: 144 probes" in text and "0 executed" in text
    assert main(["probes", "gate-failclosed", "gov", "--store", str(tmp_path / "nope"),
                 "--clones", str(tmp_path / "w2"), "--out", str(out)]) != 0
    capsys.readouterr()
