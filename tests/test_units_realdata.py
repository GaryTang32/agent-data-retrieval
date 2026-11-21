"""The units of the real corpora's scratch stores (`.cache/store-p2/<corpus>`): two builds give
the same units id and files, every unit carries one document and its envelope, and every stored
span re-slices (T1 for the metadata build, T3, T4). Writes unit overlays into the scratch stores
(never `.cache/store` or `.cache/index`), never moves `units/HEAD` or `tables/HEAD`; skipped
where the scratch stores are absent."""

from pathlib import Path

import pytest

from adr_store.store import Store
from adr_store.tables.overlay import read_head
from adr_store.units.build import CORPUS_TYPES, build_units
from adr_store.units.overlay import load_units, load_units_manifest, read_units_head
from tests.store.test_units_build import check_units

SCRATCH = Path(__file__).parents[1] / ".cache" / "store-p2"

pytestmark = pytest.mark.realdata


def store_of(corpus: str) -> Store:
    path = SCRATCH / corpus
    if not (path / "HEAD").is_file():
        pytest.skip(f"no scratch store at {path}")
    return Store.open(path)


@pytest.mark.parametrize("corpus", ["gov", "research", "bench"])
def test_real_units_build_twice_identical(corpus):
    store = store_of(corpus)
    tables, head = read_head(store.path), read_units_head(store.path)
    a = build_units(store.path, corpus)
    b = build_units(store.path, corpus)
    assert a.units_id == b.units_id and [f.sha256 for f in a.files] == [f.sha256 for f in b.files]
    m = load_units_manifest(store.path, a.units_id)
    assert tuple(f.type for f in m.units) == CORPUS_TYPES[corpus]
    assert m.tables_id == tables and m.passes == {}
    units = load_units(store.path, m)
    assert check_units(store, units) > len(units)
    assert all(f.rejected == 0 for f in m.units)
    assert read_head(store.path) == tables and read_units_head(store.path) == head
