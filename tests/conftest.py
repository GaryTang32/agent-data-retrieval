from datetime import UTC, datetime

import pytest

from adr_eval.models import (
    Answer,
    Checks,
    Evidence,
    GoldenItem,
    GoldQuery,
    ManifestDoc,
    Provenance,
)

DOC_A = ManifestDoc(
    doc_id="a",
    uri="https://example.org/a.xml",
    format="xml",
    source_version="1",
    bytes=10,
    license="pd",
    path="data/a.xml",
)
EV = Evidence(doc_id="a", char_start=0, char_end=5, quote="hello")


def _base() -> dict:
    return dict(
        id="x",
        corpus="mini",
        snapshot="0" * 64,
        qtype="factoid",
        question="What?",
        as_of=None,
        answer=Answer(kind="text", value="hello"),
        evidence=[EV],
        gold_query=GoldQuery(store="raw", op="lookup"),
        rarity=None,
        split=None,
        provenance=Provenance(
            model="m", prompt_hash="h", seed=1, created=datetime(2026, 1, 1, tzinfo=UTC)
        ),
        checks=Checks(),
        status="auto_verified",
    )


@pytest.fixture(scope="session")
def writable_state(tmp_path_factory):
    """One per-session directory for the caches and indexes tests write."""
    return tmp_path_factory.mktemp("adr_eval_state")


def _default_tuning_file(path):
    """A unit-index tuning file holding every corpus's default entry (`w = 1.0`)."""
    from adr_store.units import index as units_index

    for corpus in units_index.CORPUS_TYPES:
        units_index.write_tuning(corpus, units_index.default_tuning(corpus), path)
    return path


@pytest.fixture(scope="session", autouse=True)
def _default_unit_tuning(tmp_path_factory):
    """Every corpus's default unit-index tuning in force for the whole session, before any
    module- or session-scoped fixture builds or promotes units (C8, Task 12 fix round I2):
    whatever `config/units/tuning.json` commits, no test reads it unless it asks to."""
    from adr_store.units import index as units_index

    path = _default_tuning_file(tmp_path_factory.mktemp("units-tuning-session") / "tuning.json")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(units_index, "TUNING_PATH", path)
        mp.setenv(units_index.TUNING_ENV, str(path))
        yield path


@pytest.fixture(autouse=True)
def _isolate_writable_state(writable_state, monkeypatch, tmp_path_factory):
    """Keep tests from writing the repo's .cache/: the shipped config's index, LLM cache, store
    and embedding cache dirs and DenseIndex's default embedding cache point at the session
    directory instead.
    The Phase 2 harness's store copies (`p2_store_dir`) and the default output root of
    `adr-eval p2-compare` and `adr-eval probes` go there too, and the Phase 2 configurations
    search without a caller (`p2_caller` None; the shipped config measures `user:auditor`)
    unless a test opts in. The ACL probes' view stores and clones go there too.
    The `adr` tools' default embedding cache and `StoreIndex`'s default one point there too,
    and so does the store directory `adr --corpus <name>` and `adr index <name>` use.
    The default tools-only store of `adr tools ingest --toolret`, and the ToolRet data
    directory (`data/tools`) and manifest (`corpora/tools/manifest.json`) that
    `adr-eval tools-fetch` writes, go there too, and so does the default output root of
    `adr-eval tools-retrieval`.
    The gov-tables golden directory (`golden.tables.GOLDEN_DIR`, which `adr-eval golden tables
    --gen` writes and gov-tables runs read) is a fresh empty directory per test, and so are the
    gov-rules, gov-procedures and bench-procedures directories (`golden.units.RULES_DIR`,
    `GOV_PROCEDURES_DIR`, `BENCH_PROCEDURES_DIR`, which `adr-eval golden rules --gen` and
    `adr-eval golden procedures --gen` write), and so is the simulation tasks directory
    (`sim.tasks.TASKS_DIR`, which `adr-eval sim tasks --gen` writes and `load_tasks` reads),
    and the default output root of `adr-eval sim drawbridge` (`sim.agent.OUT_ROOT`) goes to the
    session directory's `runs` (N9).
    The default output root of `adr-eval p4-retrieval` (`phase4.OUT_ROOT`) goes there too, and
    the unit-index tuning file (`units.index.TUNING_PATH`, which `adr-eval p4-tune` writes and
    the unit tools read) is a fresh file per test holding every corpus's default entry
    (`w = 1.0`, lexical-only), whatever the committed file says, so no test loads an embedding
    model (C8). `$ADR_UNITS_TUNING` names it too, and `adr mcp` subprocesses inherit it
    (`mcp_client.server_parameters`); CLI subprocesses inherit the environment.
    The fastembed model store (.cache/fastembed) is only read."""
    from adr_eval import runner
    from adr_eval.retrieval.dense import DenseIndex
    from adr_store import cli, tools
    from adr_store.embedding import EmbeddingCache
    from adr_store.retrieval import index as store_index

    real_load_config = runner.load_config

    def load_config(path=runner.CONFIG_PATH):
        return {**real_load_config(path), "index_dir": str(writable_state / "index"),
                "cache_dir": str(writable_state / "llm"),
                "store_dir": str(writable_state / "store"),
                "p2_store_dir": str(writable_state / "store-p2"), "p2_caller": None,
                "embedding_cache_dir": str(writable_state / "emb-store")}

    monkeypatch.setattr(runner, "load_config", load_config)
    model_name, _, model_cache_dir = DenseIndex.__init__.__defaults__
    monkeypatch.setattr(DenseIndex.__init__, "__defaults__",
                        (model_name, writable_state / "emb", model_cache_dir))
    tools_emb = writable_state / "emb-tools"
    monkeypatch.setattr(tools, "DEFAULT_EMB_CACHE", tools_emb)
    monkeypatch.setattr(tools.Tools.__init__, "__kwdefaults__",
                        {**tools.Tools.__init__.__kwdefaults__, "emb_cache": tools_emb})
    monkeypatch.setattr(tools.make_embedding_cache, "__defaults__", (tools_emb,))
    monkeypatch.setattr(store_index, "_default_cache",
                        lambda: EmbeddingCache(writable_state / "emb-store-index"))
    monkeypatch.setattr(cli, "STORE_ROOT", writable_state / "cli-store")
    monkeypatch.setattr(cli, "TOOL_STORE", writable_state / "store-p2-toolret")
    from adr_eval.corpora import toolret

    monkeypatch.setattr(toolret, "DATA_DIR", writable_state / "data-tools")
    monkeypatch.setattr(toolret, "MANIFEST_PATH", writable_state / "tools-manifest.json")
    from adr_eval import phase2, probes

    monkeypatch.setattr(phase2, "OUT_ROOT", writable_state / "runs")
    monkeypatch.setattr(probes, "OUT_ROOT", writable_state / "runs")
    from adr_eval import tools_eval

    monkeypatch.setattr(tools_eval, "OUT_ROOT", writable_state / "runs")
    from adr_eval.golden import tables as golden_tables

    monkeypatch.setattr(golden_tables, "GOLDEN_DIR",
                        tmp_path_factory.mktemp("golden-gov-tables") / "v0.1")
    from adr_eval.golden import units as golden_units

    for name, d in (("RULES_DIR", "gov-rules"), ("GOV_PROCEDURES_DIR", "gov-procedures"),
                    ("BENCH_PROCEDURES_DIR", "bench-procedures")):
        monkeypatch.setattr(golden_units, name, tmp_path_factory.mktemp(f"golden-{d}") / d
                            / "v0.1")
    from adr_eval import phase4
    from adr_store.units import index as units_index

    monkeypatch.setattr(phase4, "OUT_ROOT", writable_state / "runs")
    from adr_eval.sim import agent as sim_agent
    from adr_eval.sim import tasks as sim_tasks

    monkeypatch.setattr(sim_agent, "OUT_ROOT", writable_state / "runs")
    monkeypatch.setattr(sim_tasks, "TASKS_DIR",
                        tmp_path_factory.mktemp("golden-sim-drawbridge") / "v0.1")
    tuning = _default_tuning_file(tmp_path_factory.mktemp("units-tuning") / "tuning.json")
    monkeypatch.setattr(units_index, "TUNING_PATH", tuning)
    monkeypatch.setenv(units_index.TUNING_ENV, str(tuning))


@pytest.fixture
def make_item():
    def make(**overrides) -> GoldenItem:
        return GoldenItem(**{**_base(), **overrides})

    return make
