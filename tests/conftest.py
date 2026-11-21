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
    --gen` writes and gov-tables runs read) is a fresh empty directory per test.
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


@pytest.fixture
def make_item():
    def make(**overrides) -> GoldenItem:
        return GoldenItem(**{**_base(), **overrides})

    return make
