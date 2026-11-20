"""The 3A tables built from the real corpora's scratch stores (`.cache/store-p2/<corpus>`):
every v0.1 record is reproduced by id and row, every located span re-slices, and two builds give
the same tables id. Writes table overlays into the scratch stores (never `.cache/store` or
`.cache/index`); skipped where the scratch stores are absent."""

from collections import Counter
from pathlib import Path

import pytest

from adr_eval.corpora.gov import GovAdapter
from adr_eval.corpora.research import ResearchAdapter
from adr_store import applicability as ap
from adr_store.store import Store
from adr_store.tables import overlay as ov
from adr_store.tables.build import build_tables
from adr_store.tables.loaders import fr_tables, papers_tables, records_view
from adr_store.tables.provenance import MANIFEST_COLUMNS, reslice
from tests.store.tables_fixtures import loaded_of

SCRATCH = Path(__file__).parents[1] / ".cache" / "store-p2"
GOV_FIELDS = ["id", "type", "agency", "publication_date", "year", "title", "cfr_parts"]
RESEARCH_FIELDS = ["id", *MANIFEST_COLUMNS[:6], "year", *MANIFEST_COLUMNS[7:]]

pytestmark = pytest.mark.realdata


def as_list(x):
    return x if isinstance(x, list) else [x]


def store_of(corpus: str) -> Store:
    path = SCRATCH / corpus
    if not (path / "HEAD").is_file():
        pytest.skip(f"no scratch store at {path}")
    return Store.open(path)


def all_spans_reslice(store: Store, tables: dict) -> int:
    texts: dict[str, str] = {}
    checked = 0
    for rows in tables.values():
        for r in rows:
            if r.doc_id not in texts:
                texts[r.doc_id] = store.text(r.doc_id)
            text = texts[r.doc_id]
            for col, p in r.prov.items():
                for one, v in zip(as_list(p), as_list(r.row[col]), strict=True):
                    if one.start is not None:
                        assert reslice(text, one, v), (r.doc_id[:8], col, one.span, v)
                        checked += 1
    return checked


@pytest.mark.parametrize("corpus", ["gov", "research"])
def test_real_tables_reproduce_the_records(corpus):
    store = store_of(corpus)
    first = build_tables(store.path, corpus)
    second = build_tables(store.path, corpus)
    assert first.tables_id == second.tables_id
    assert all(t.rejected == 0 for t in first.tables)
    assert all(r["rejected"] == [] for r in first.reports.values())
    m = ov.load_manifest(store.path, first.tables_id)
    corpus_view = loaded_of(store)
    if corpus == "gov":
        want = [{k: v for k, v in r.items() if k != "_doc_id"}
                for r in GovAdapter().records(corpus_view)]
        got = records_view(ov.load_rows(store.path, m, "fr_documents"), GOV_FIELDS)
        assert got == want and len(got) == 167
        assert Counter(r["type"] for r in got) == {"Rule": 120, "Proposed Rule": 47}
        overlay = ap.load_overlay(store.path, store.snapshot_id)
        assert m.applicability == overlay.overlay_id
        assert {r.row["status"] for r in ov.load_rows(store.path, m, "fr_documents")} <= set(
            ap.STATUSES)
    else:
        want = [{k: v for k, v in r.items() if not k.startswith("_")}
                for r in ResearchAdapter().records(corpus_view)]
        rows = ov.load_rows(store.path, m, "papers")
        got = records_view(rows, RESEARCH_FIELDS)
        assert got == want and len(got) == 2570
        assert sum(1 for r in got if not r["also_in"]) == 2269
        assert sum(1 for r in got if r["year"] is None) == 19
        assert [r.row["row"] for r in rows] == list(range(1, 2571))


@pytest.mark.parametrize("corpus", ["gov", "research"])
def test_every_real_span_reslices(corpus):
    store = store_of(corpus)
    if corpus == "gov":
        tables = fr_tables(store, ap.load_overlay(store.path, store.snapshot_id))
    else:
        tables = papers_tables(store)
    assert all_spans_reslice(store, tables) > 1000


def test_real_federal_register_reference_and_docket_counts():
    store = store_of("gov")
    tables = fr_tables(store, ap.load_overlay(store.path, store.snapshot_id))
    refs = {(r.row["title"], r.row["part"]) for r in tables["fr_cfr_refs"]}
    assert len(refs) == 39 and len({r.row["cfr_part"] for r in tables["fr_cfr_refs"]}) == 39
    assert all(r.row["part"] is not None for r in tables["fr_cfr_refs"])
    assert len(tables["fr_dockets"]) == 171
    assert len({r.row["docket"] for r in tables["fr_dockets"]}) == 157
    assert sum(len(r.row["other_ids"]) for r in tables["fr_documents"]) == 140
    assert len(tables["fr_agencies"]) == 278
