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


@pytest.fixture(scope="session", autouse=True)
def _isolate_writable_state(writable_state):
    """Keep tests from writing the repo's .cache/: the shipped config's index and LLM cache
    dirs and DenseIndex's default embedding cache point at the session directory instead.
    The fastembed model store (.cache/fastembed) is only read.

    Session-scoped so the patches are in place before any module- or session-scoped
    fixture runs (pytest sets up higher-scoped autouse fixtures first); a function-scoped
    guard would come too late for e.g. a module-scoped HybridIndex.build()."""
    from adr_eval import runner
    from adr_eval.retrieval.dense import DenseIndex

    real_load_config = runner.load_config

    def load_config(path=runner.CONFIG_PATH):
        return {**real_load_config(path), "index_dir": str(writable_state / "index"),
                "cache_dir": str(writable_state / "llm")}

    model_name, _, model_cache_dir = DenseIndex.__init__.__defaults__
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(runner, "load_config", load_config)
        mp.setattr(DenseIndex.__init__, "__defaults__",
                   (model_name, writable_state / "emb", model_cache_dir))
        yield


@pytest.fixture
def make_item():
    def make(**overrides) -> GoldenItem:
        return GoldenItem(**{**_base(), **overrides})

    return make
