"""The gov-rules, gov-procedures and bench-procedures golden generators (Phase 4 spec §14, P22,
P30, P36; Task 11): the draws are code over the source structure, the phrasing is a stub model
behind the reply cache. No test calls a model; the fixture stores sit under `tmp_path` and the
three golden directories are fresh per test (conftest)."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
import shutil
import subprocess
from collections import Counter
from datetime import date

import pytest

from adr_eval import runner
from adr_eval.cache import Cache
from adr_eval.cli import main
from adr_eval.golden import units as gu
from adr_eval.golden.units import (
    MIN_CHARS,
    SEED4,
    ProcedureItem,
    RuleItem,
    draw_rules,
    generate_procedures,
    generate_rules,
    leak_reason,
    load_procedure_items,
    load_rule_items,
    rule_universe,
)
from adr_eval.golden.verify import assign_split
from adr_eval.llm import CachedStubClient
from adr_store import applicability as ap
from adr_store.store import Store
from adr_store.tables.ecfr import chain_docs
from adr_store.units.ecfr import provisions
from tests.store import units_fixtures as uf
from tests.store.tables_fixtures import ECFR_NEW, REPO, _doc
from tests.store.units_fixtures import (
    DOC_117_NEW,
    DOC_117_OLD,
    DOC_IRM,
    DOC_RUNBOOK,
    ECFR_117_UNITS,
    make_units_store,
)

units_store = uf.units_store

UNIT_ID = re.compile(r"\b(?:rule_card|procedure|concept|faq|table_record)/")
SOURCE = ("(b) The draw of the Smith River Railroad Bridge, mile 5.1, at Smithfield, shall "
          "open on signal; the draw shall open on signal if at least four hours notice is given.")


def clean_reply(system: str, user: str, repeat: int) -> str:
    """A phrasing that leaks nothing: no number, heading or source wording."""
    tag = hashlib.sha256(f"{user}|{repeat}".encode()).hexdigest()[:6]
    return json.dumps({"question": f"What happens in situation {tag}?"})


def source_of(user: str) -> str:
    return user.split("Source text:\n", 1)[1]


def leaking(user: str) -> str:
    """A phrasing that copies the first eight words of the source text."""
    return json.dumps({"question": " ".join(source_of(user).split()[:8]) + "?"})


def stub(tmp_path, fn=clean_reply, name: str = "stub-sonnet") -> CachedStubClient:
    return CachedStubClient(name, Cache(tmp_path / "llm"), fn)


def counts(monkeypatch, rules: dict[str, int], older: float) -> None:
    """Size the draw to the fixture store (preflight ruling C2)."""
    monkeypatch.setattr(gu, "RULE_COUNTS", rules)
    monkeypatch.setattr(gu, "OLDER_SHARE", older)


def text_differs_from_newest(store: Store, p) -> bool:
    """Whether the newest version of `p`'s part holds `p`'s provision id with another text."""
    newest = chain_docs(store, ap.chain_of(store.source(p.doc_id)))[-1]
    texts = {" ".join(q.text.split()) for q in provisions(store, newest)
             if q.provision_id == p.provision_id}
    return p.doc_id != newest and bool(texts) and " ".join(p.text.split()) not in texts


def valid_from(store: Store, doc_id: str) -> date:
    return ap.load_overlay(store.path, store.snapshot_id).records[doc_id].valid_from


# -- the rule universe and the draw ----------------------------------------------------------------


def test_rule_universe_holds_modal_paragraphs_of_every_version(units_store):
    store = units_store
    universe = rule_universe(store)
    assert set(universe) == {"33 CFR 117", "33 CFR 165", "47 CFR 73"}
    assert universe["47 CFR 73"] == []                       # no 47 CFR 73 in the fixture
    rules = universe["33 CFR 117"]
    assert {p.doc_id for p in rules} == {DOC_117_OLD, DOC_117_NEW}
    assert all(p.modality is not None and len(p.text) >= MIN_CHARS for p in rules)
    newest = {p.provision_id for p in rules if p.doc_id == DOC_117_NEW}
    assert "33 CFR 117.821(c)" not in newest                 # no modal word
    assert {"33 CFR 117.5(p1)", "33 CFR 117.821(a)", "33 CFR 117.901(c)"} <= newest
    assert [p.provision_id for p in universe["33 CFR 165"]] == [
        "33 CFR 165.13(a)", "33 CFR 165.13(b)", "33 CFR 165.T01(c)"]


def test_boilerplate_and_short_provisions_are_excluded(units_store, tmp_path):
    store = units_store
    newest = {p.provision_id for p in rule_universe(store)["33 CFR 117"]
              if p.doc_id == DOC_117_NEW}
    # (1) "The draw shall open as required by §§ 117.5 and 117.31." is modal but 59 characters
    assert "33 CFR 117.1081(a)(1)" not in newest
    assert "33 CFR 117.901(a)" in newest
    # the same paragraph under another marker in another section is boilerplate: both go
    copy = b"<P>(d) The draw of the Harbor Avenue Bridge, mile 0.8, at Bristol, shall open " \
        b"on signal.</P>"
    anchor = b"<P>(c) The owner of the Coast Channel Bridge"
    assert ECFR_117_UNITS.count(anchor) == 1
    raw = ECFR_117_UNITS.replace(anchor, copy + b"\n" + anchor)
    from adr_eval.corpora.gov import ecfr_url

    doctored = make_units_store(tmp_path / "doctored",
                                [_doc(raw, "xml", ECFR_NEW, ecfr_url(33, "117", ECFR_NEW))])
    ids = {p.provision_id for p in rule_universe(doctored)["33 CFR 117"]}
    assert "33 CFR 117.901(a)" not in ids and "33 CFR 117.1081(d)" not in ids
    assert "33 CFR 117.901(b)" in ids


def test_draw_counts_and_older_share(units_store, monkeypatch):
    store = units_store
    counts(monkeypatch, {"33 CFR 117": 5, "33 CFR 165": 2}, 0.20)
    draws = draw_rules(store, SEED4)
    assert Counter(p.part for p, _ in draws) == {"33 CFR 117": 5, "33 CFR 165": 2}
    older = [(p, a) for p, a in draws if a is not None]
    assert len(older) == 1 and all(text_differs_from_newest(store, p) for p, _ in older)
    p, as_of = older[0]
    assert p.provision_id == "33 CFR 117.821(b)" and p.doc_id == DOC_117_OLD
    assert as_of == valid_from(store, DOC_117_OLD) == date(2025, 6, 27)
    assert all(p.doc_id != DOC_117_OLD for p, a in draws if a is None)
    assert len({(p.doc_id, p.start) for p, _ in draws}) == len(draws)
    assert draw_rules(store, SEED4) == draws                 # by seed, no other state


def test_a_short_universe_is_drawn_whole_not_padded(units_store, monkeypatch):
    store = units_store
    counts(monkeypatch, {"33 CFR 165": 5}, 0.20)      # 4 newest wanted of 3, 1 older of none
    draws = draw_rules(store, SEED4)
    assert sorted(p.provision_id for p, _ in draws) == [
        "33 CFR 165.13(a)", "33 CFR 165.13(b)", "33 CFR 165.T01(c)"]
    assert all(a is None for _, a in draws)
    report: dict = {}
    items, _ = generate_rules(store.path, stub(store.path.parent), report=report)
    assert len(items) == 3
    assert report["short"] == {"33 CFR 165": {"newest": 1, "older": 1}}


# -- leaks -------------------------------------------------------------------------------------


@pytest.mark.parametrize("q,why", [
    ("What does 117.821 require?", "number"),
    ("What does § 117.821(b) require?", "number"),
    ("When must the Main Street drawbridge open?", "heading 3-gram"),
    ("Does the draw at Main Street, drawbridge side, open?", "heading 3-gram"),  # stop words
    ("Is it true that the draw shall open on signal if at least?", "source 6-gram"),
    ("When does a boat get an opening at night?", None),
    ("Does the Main Street bridge open at night?", None),            # two heading words only
    ("What does 117.8210 require?", None),                           # another number
])
def test_leak_reason(q, why):
    assert leak_reason(q, SOURCE, "Main Street drawbridge, Smith River", ["117.821"]) == why


# -- rule items --------------------------------------------------------------------------------


def _all_rules(monkeypatch) -> None:
    """Every eligible newest provision of the fixture's 117 (13) and 165 (3), and its one
    older provision that differs from the newest."""
    counts(monkeypatch, {"33 CFR 117": 14, "33 CFR 165": 3}, 0.07)


def test_generate_with_a_stub_ids_splits_and_reslices(units_store, monkeypatch, tmp_path):
    store = units_store
    _all_rules(monkeypatch)
    client = stub(tmp_path)
    items, rejected = generate_rules(store.path, client)
    assert rejected == [] and client.calls == 17
    assert [i.id for i in items] == [f"gov-rules-{k:03d}" for k in range(1, 18)]
    assert Counter(i.part for i in items) == {"33 CFR 117": 14, "33 CFR 165": 3}
    for i in items:
        assert i.split == assign_split(i.id) and i.corpus == "gov-rules"
        assert i.snapshot == store.snapshot_id and i.status == "auto_verified"
        assert i.provenance.seed == SEED4 and i.provenance.model == client.model
        (ev,) = i.evidence
        full = store.text(ev.doc_id)
        assert full[ev.char_start:ev.char_end] == ev.quote
        (gold,) = i.gold_rules
        drawn = [p for p in provisions(store, ev.doc_id)
                 if (p.start, p.end) == (ev.char_start, ev.char_end)]
        assert [p.provision_id for p in drawn] == [gold] and drawn[0].text == ev.quote
        assert i.as_of == (None if ev.doc_id != DOC_117_OLD else date(2025, 6, 27))
        assert len(i.closure_rules) == len(i.closure_evidence)
    (older,) = [i for i in items if i.as_of is not None]
    assert older.gold_rules == ["33 CFR 117.821(b)"] and older.evidence[0].doc_id == DOC_117_OLD
    assert "two hours notice" in older.evidence[0].quote
    # determinism: a second run reads every reply from the cache and gives the same items
    again, _ = generate_rules(store.path, client)
    assert client.calls == 17
    assert [i.model_dump_json() for i in again] == [i.model_dump_json() for i in items]


def test_closure_evidence_reslices_to_its_provision_text(units_store, monkeypatch, tmp_path):
    store = units_store
    _all_rules(monkeypatch)
    items, _ = generate_rules(store.path, stub(tmp_path))
    by_gold = {(i.gold_rules[0], i.evidence[0].doc_id): i for i in items}
    item = by_gold[("33 CFR 117.901(c)", DOC_117_NEW)]   # "paragraph (b) of this section"
    assert item.closure_rules == ["33 CFR 117.901(b)"]
    (ev,) = item.closure_evidence
    provs = provisions(store, DOC_117_NEW)
    (target,) = [p for p in provs if p.provision_id == "33 CFR 117.901(b)"]
    assert ev.doc_id == DOC_117_NEW and (ev.char_start, ev.char_end) == (target.start, target.end)
    assert ev.quote == target.text == store.text(DOC_117_NEW)[ev.char_start:ev.char_end]
    # a reference to a whole part ("33 CFR part 165") and a dangling one (§ 117.999) are no
    # closure rules
    assert by_gold[("33 CFR 117.1081(b)", DOC_117_NEW)].closure_rules == []
    assert by_gold[("33 CFR 117.1081(c)", DOC_117_NEW)].closure_rules == []
    for i in items:                     # every closure span re-slices in the drawn version
        for rule, ev in zip(i.closure_rules, i.closure_evidence, strict=True):
            full = store.text(ev.doc_id)
            assert ev.doc_id == i.evidence[0].doc_id
            assert full[ev.char_start:ev.char_end] == ev.quote
            under = [p for p in provisions(store, ev.doc_id)
                     if p.provision_id == rule or p.provision_id.startswith(rule + "(")]
            assert ev.char_start == min(p.start for p in under)
            assert ev.char_end == max(p.end for p in under)


def test_a_leaking_phrasing_is_redrawn_once_at_repeat_1(units_store, monkeypatch, tmp_path):
    store = units_store
    counts(monkeypatch, {"33 CFR 117": 2}, 0.0)
    first, second, third = [p for p, _ in gu._rule_pools(store, SEED4)["33 CFR 117"]["newest"]
                            ][:3]

    def fn(system, user, repeat):
        if first.text in user:              # leaks on both tries: the provision is replaced
            return leaking(user)
        if second.text in user and repeat == 0:
            return "not json"               # malformed once: redrawn at repeat 1
        return clean_reply(system, user, repeat)

    client = stub(tmp_path, fn)
    items, rejected = generate_rules(store.path, client)
    assert [i.gold_rules[0] for i in items] == [second.provision_id, third.provision_id]
    assert [(r["source"], r["repeat"], r["reason"]) for r in rejected] == [
        (first.provision_id, 0, "source 6-gram"), (first.provision_id, 1, "source 6-gram"),
        (second.provision_id, 0, "malformed phrasing")]
    assert client.calls == 5
    assert items[0].question == json.loads(clean_reply("", gu.rule_message(second), 1))[
        "question"]


def test_an_input_rejection_replaces_the_provision_without_a_redraw(units_store, monkeypatch,
                                                                  tmp_path):
    from adr_eval import llm

    store = units_store
    counts(monkeypatch, {"33 CFR 165": 1}, 0.0)
    first = gu._rule_pools(store, SEED4)["33 CFR 165"]["newest"][0][0]

    def fn(system, user, repeat):
        if first.text in user:
            raise llm.InputRejected("prompt rejected")
        return clean_reply(system, user, repeat)

    items, rejected = generate_rules(store.path, stub(tmp_path, fn))
    assert len(items) == 1 and items[0].gold_rules != [first.provision_id]
    assert [(r["source"], r["repeat"], r["reason"]) for r in rejected] == [
        (first.provision_id, 0, "input rejected")]


def test_a_limit_gives_the_first_items_of_the_full_run(units_store, monkeypatch, tmp_path):
    store = units_store
    _all_rules(monkeypatch)
    client = stub(tmp_path)
    full, _ = generate_rules(store.path, client)
    some, _ = generate_rules(store.path, client, limit=4)
    assert [i.model_dump_json() for i in some] == [i.model_dump_json() for i in full[:4]]


# -- procedure items ---------------------------------------------------------------------------


def test_generate_procedures_with_a_stub(units_store, monkeypatch, tmp_path):
    store = units_store
    monkeypatch.setattr(gu, "N_PROCEDURES", 2)
    client = stub(tmp_path)
    report: dict = {}
    out = generate_procedures([store.path], client, report=report)
    gov, gov_rejected = out["gov-procedures"]
    bench, bench_rejected = out["bench-procedures"]
    assert gov_rejected == bench_rejected == []
    assert sorted(i.gold for i in gov) == ["IRM 21.4.1.3.1", "IRM 21.4.1.3.2"]
    assert [i.id for i in gov] == ["gov-procedures-001", "gov-procedures-002"]
    assert [(i.id, i.gold) for i in bench] == [("bench-procedures-001", DOC_RUNBOOK)]
    assert report["short"] == {"bench-procedures": 1}
    assert report["universe"] == {"gov-procedures": 2, "bench-procedures": 1}
    for i in gov + bench:
        assert i.split == assign_split(i.id) and i.snapshot == store.snapshot_id
        (ev,) = i.evidence
        assert store.text(ev.doc_id)[ev.char_start:ev.char_end] == ev.quote
    assert all(i.corpus == "gov-procedures" and i.evidence[0].doc_id == DOC_IRM for i in gov)
    (b,) = bench
    assert b.corpus == "bench-procedures"
    assert (b.evidence[0].char_start, b.evidence[0].char_end) == (
        0, len(store.text(DOC_RUNBOOK)))


def test_a_procedure_question_holding_the_irm_number_is_redrawn(units_store, monkeypatch,
                                                               tmp_path):
    store = units_store
    monkeypatch.setattr(gu, "N_PROCEDURES", 2)

    def fn(system, user, repeat):
        if "Missing Refund Research" in user and repeat == 0:
            return json.dumps({"question": "What does IRM 21.4.1.3.1 tell me to do?"})
        return clean_reply(system, user, repeat)

    gov, rejected = generate_procedures([store.path], stub(tmp_path, fn))["gov-procedures"]
    assert len(gov) == 2
    assert [(r["source"], r["repeat"], r["reason"]) for r in rejected] == [
        ("IRM 21.4.1.3.1", 0, "number")]


def test_a_corpus_found_in_two_stores_is_refused(units_store, monkeypatch, tmp_path):
    store = units_store
    with pytest.raises(gu.GoldenError, match="more than one store"):
        generate_procedures([store.path, store.path], stub(tmp_path))


# -- independence from the system under test (P22) -----------------------------------------------


def test_items_hold_no_unit_ids(units_store, monkeypatch, tmp_path):
    """Gold comes from the source structure, not from the system under test: no item holds a
    unit id, and the generator imports no unit builder, index, tool or overlay."""
    store = units_store
    _all_rules(monkeypatch)
    monkeypatch.setattr(gu, "N_PROCEDURES", 2)
    client = stub(tmp_path)
    rules, _ = generate_rules(store.path, client)
    procs = generate_procedures([store.path], client)
    dumped = [i.model_dump_json() for i in rules] + [
        i.model_dump_json() for items, _ in procs.values() for i in items]
    assert dumped and not any(UNIT_ID.search(d) or "unit_id" in d for d in dumped)
    imported = set()
    for node in ast.walk(ast.parse(inspect.getsource(gu))):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert {m for m in imported if m.startswith("adr_store.units")} == {
        "adr_store.units.ecfr", "adr_store.units.procedures"}
    for name in ("rule_cards", "procedure_units", "make_unit", "build_units", "Tools"):
        assert name not in vars(gu)


# -- files and the command -----------------------------------------------------------------------


def _stub_profiles(monkeypatch, tmp_path, fn=clean_reply):
    made = []

    def make_client(name, profiles, cache, max_retries=5):
        made.append(name)
        return CachedStubClient(f"stub-{name}", Cache(tmp_path / "llm"), fn)

    monkeypatch.setattr(runner, "make_client", make_client)
    return made


def golden(capsys, *args) -> tuple[int, str, str]:
    code = main(["golden", *map(str, args)])
    out, err = capsys.readouterr()
    return code, out, err


def test_gov_items_are_written_and_bench_items_are_gitignored(units_store, monkeypatch,
                                                             tmp_path, capsys):
    store = units_store
    counts(monkeypatch, {"33 CFR 117": 3, "33 CFR 165": 2}, 0.0)
    monkeypatch.setattr(gu, "N_PROCEDURES", 2)
    _stub_profiles(monkeypatch, tmp_path)
    for d in (gu.RULES_DIR, gu.GOV_PROCEDURES_DIR, gu.BENCH_PROCEDURES_DIR):
        assert not str(d).startswith(str(REPO / "golden"))   # fresh per test (conftest)
    code, out, err = golden(capsys, "rules", "--gen", "--store", store.path, "--generator",
                            "claude_code_sonnet", "--max-calls", 10)
    assert code == 0, err
    assert len(load_rule_items(gu.RULES_DIR / "items.jsonl")) == 5
    assert (gu.RULES_DIR / "rejected.jsonl").is_file()
    code, out, err = golden(capsys, "procedures", "--gen", "--store", store.path,
                            "--generator", "claude_code_sonnet", "--max-calls", 10)
    assert code == 0, err
    assert [i.gold for i in load_procedure_items("bench-procedures")] == [DOC_RUNBOOK]
    assert len(load_procedure_items("gov-procedures")) == 2
    for d in (gu.GOV_PROCEDURES_DIR, gu.BENCH_PROCEDURES_DIR):
        assert (d / "items.jsonl").is_file() and (d / "rejected.jsonl").is_file()
    if shutil.which("git") is None:
        pytest.skip("git is not installed")

    def ignored(rel: str) -> bool:
        r = subprocess.run(["git", "check-ignore", "--no-index", "-q", rel], cwd=REPO,
                           capture_output=True)
        assert r.returncode in (0, 1), r.stderr
        return r.returncode == 0

    for name in ("items.jsonl", "rejected.jsonl"):
        assert ignored(f"golden/bench-procedures/v0.1/{name}")
        assert not ignored(f"golden/gov-rules/v0.1/{name}")
        assert not ignored(f"golden/gov-procedures/v0.1/{name}")
    assert gu.BENCH_PROCEDURES_DIR.parts[-2:] == ("bench-procedures", "v0.1")


def test_golden_rules_gen_stops_at_its_cap_then_writes(units_store, monkeypatch, tmp_path,
                                                       capsys):
    store = units_store
    counts(monkeypatch, {"33 CFR 117": 5, "33 CFR 165": 2}, 0.20)
    made = _stub_profiles(monkeypatch, tmp_path)
    args = ("rules", "--gen", "--store", store.path, "--generator", "claude_code_sonnet")
    code, out, err = golden(capsys, *args, "--max-calls", 0)
    assert code == 1, err
    assert "33 CFR 117: eligible per version 2025-06-27 13, 2026-06-26 13 (newest); 1 older " \
        "provision(s) differ from the newest; draw 4 newest + 1 older" in out
    assert "status: stopped at --max-calls 0 (0 budget unit(s) used); nothing written" in out
    assert not gu.RULES_DIR.exists() and made == ["claude_code_sonnet"]
    code, out, err = golden(capsys, *args, "--max-calls", 3)
    assert code == 1 and "stopped at --max-calls 3" in out
    code, out, err = golden(capsys, *args, "--max-calls", 4, "--limit", 6)
    assert code == 0, err
    assert "6 items (" in out and "3 model call(s) made, 3 cached" in out
    code, out, err = golden(capsys, *args, "--max-calls", 1)
    assert code == 2 and "--overwrite" in err                  # frozen
    code, out, err = golden(capsys, *args, "--max-calls", 1, "--overwrite")
    assert code == 0, err
    assert "7 items (" in out and "1 model call(s) made, 6 cached" in out
    data = (gu.RULES_DIR / "items.jsonl").read_bytes()
    code, out, err = golden(capsys, *args, "--max-calls", 0, "--overwrite")
    assert code == 0 and (gu.RULES_DIR / "items.jsonl").read_bytes() == data


@pytest.mark.parametrize("args,message", [
    (("rules", "--gen", "--generator", "p", "--max-calls", "1"), "needs --store"),
    (("rules", "--gen", "--store", "s", "--generator", "p"), "needs --max-calls"),
    (("procedures", "--gen", "--store", "s", "--max-calls", "1"), "needs --generator"),
    (("rules", "--gen", "--store", "s", "--store", "t", "--generator", "p", "--max-calls", "1"),
     "one --store"),
    (("rules", "--verify"), "--gen only"),
    (("rules", "--gen", "--store", "s", "--generator", "p", "--max-calls", "-1"),
     "must not be negative"),
    (("procedures", "--gen", "--store", "s", "--generator", "p", "--max-calls", "1",
      "--facts", "x"), "--facts"),
    (("tables", "--gen", "--store", "s", "--facts", "f", "--generator", "p", "--max-calls",
      "1", "--limit", "2"), "--limit"),
    (("mini", "--verify", "--limit", "2"), "--limit"),
])
def test_golden_units_arguments_are_checked(args, message, capsys):
    with pytest.raises(SystemExit) as e:
        main(["golden", *args])
    assert e.value.code == 2 and message in capsys.readouterr().err


def test_load_items_read_what_the_generators_wrote(units_store, monkeypatch, tmp_path):
    store = units_store
    counts(monkeypatch, {"33 CFR 165": 3}, 0.0)
    items, rejected = generate_rules(store.path, stub(tmp_path))
    gu.write_items(tmp_path / "out", items, [{"source": "x", "reason": "number"}])
    assert load_rule_items(tmp_path / "out" / "items.jsonl") == items
    assert all(isinstance(i, RuleItem) for i in items)
    assert json.loads((tmp_path / "out" / "rejected.jsonl").read_text()) == {
        "source": "x", "reason": "number"}
    monkeypatch.setattr(gu, "N_PROCEDURES", 1)
    procs = generate_procedures([store.path], stub(tmp_path))
    gu.write_items(gu.GOV_PROCEDURES_DIR, *procs["gov-procedures"])
    assert load_procedure_items("gov-procedures") == procs["gov-procedures"][0]
    assert all(isinstance(i, ProcedureItem) for i in procs["gov-procedures"][0])
