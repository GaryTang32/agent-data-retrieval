"""The semantic layer (Phase 3 spec §8): `describe_tables` generated from the contracts, at most
8 KB over every committed contract."""

import json

from adr_store.tables.contracts import Column, Contract, Source, load_contracts
from adr_store.tables.semantic import ALLOWED_MAX, DESCRIBE_MAX_BYTES, describe


def _size(d) -> int:
    return len(json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode())


def _tables(d) -> dict[str, dict]:
    return {t["name"]: t for t in d["tables"]}


def _columns(d, table: str) -> dict[str, str]:
    """The columns of `table` as `name: type[?]` -> description, following a shared set."""
    t = _tables(d)[table]
    return t["columns"] if "columns" in t else _tables(d)[t["columns_as"]]["columns"]


def _contract(table="t", allowed=None, **extra) -> Contract:
    cols = [Column(name="id", type="text", nullable=False, description="Id.", spec_id="t.id@1"),
            Column(name="kind", type="text", nullable=True, description="Kind.",
                   spec_id="t.kind@1", allowed=allowed),
            Column(name="flag", type="bool", nullable=False, description="Flag.",
                   spec_id="t.flag@1"),
            Column(name="other_id", type="text", nullable=True, description="Entity id.",
                   spec_id="t.other_id@1")]
    return Contract(table=table, version=1, kind="data", description="A table.", columns=cols,
                    key=["id"], order=["id"], list_column="id",
                    source=Source(corpus="gov", selector="fr", loader="metadata"), **extra)


def test_describe_covers_every_column_under_8_kb():
    contracts = load_contracts()
    d = describe(list(contracts.values()))
    assert DESCRIBE_MAX_BYTES == 8192
    assert _size(d) <= DESCRIBE_MAX_BYTES
    assert all(col.name in json.dumps(d) for c in contracts.values() for col in c.columns)
    assert {m["name"] for m in d["metrics"]} == {"count", "count_distinct"}


def test_every_table_lists_every_column_with_its_type_and_description():
    contracts = load_contracts()
    d = describe(list(contracts.values()))
    assert [t["name"] for t in d["tables"]] == sorted(contracts)
    for name, c in contracts.items():
        t = _tables(d)[name]
        assert (t["description"], t["key"], t["list_column"], t["corpus"]) == \
            (c.description, c.key, c.list_column, c.source.corpus)
        cols = _columns(d, name)
        assert cols == {f"{col.name}: {col.type}{'?' if col.nullable else ''}": col.description
                        for col in c.columns}
    fr = _columns(d, "fr_documents")
    assert fr["publication_date: date"].startswith("Date the document was published")
    assert "agency: text?" in fr and "cfr_parts: text[]" in fr


def test_allowed_values_entity_links_and_dimensions():
    contracts = load_contracts()
    d = describe(list(contracts.values()))
    fr = _tables(d)["fr_documents"]
    assert fr["allowed"] == {"type": contracts["fr_documents"].columns[1].allowed,
                             "status": [c for c in contracts["fr_documents"].columns
                                        if c.name == "status"][0].allowed}
    assert fr["dimensions"] == ["type", "status"]
    agencies = _tables(d)["fr_agencies"]
    assert agencies["links"] == {"agency_id": "agencies.entity_id"}
    assert agencies["dimensions"] == ["specific", "agency_id"]
    papers = _tables(d)["papers"]
    assert papers["links"] == {"venue_id": "venues.entity_id", "licence_id": "licences.entity_id"}
    assert "allowed" not in papers and "links" not in _tables(d)["agencies"]


def test_allowed_values_are_listed_up_to_25():
    listed = describe([_contract(allowed=[f"v{i}" for i in range(ALLOWED_MAX)])])
    assert ALLOWED_MAX == 25
    assert listed["tables"][0]["allowed"] == {"kind": [f"v{i}" for i in range(25)]}
    unlisted = describe([_contract(allowed=[f"v{i}" for i in range(26)])])["tables"][0]
    assert "allowed" not in unlisted
    assert unlisted["dimensions"] == ["kind", "flag"]   # still a categorical dimension


def test_metrics_are_a_query_table_count_and_an_sql_count_distinct():
    m = {x["name"]: x for x in describe([_contract()])["metrics"]}
    assert m["count"]["tool"] == "query_table" and m["count"]["args"]["op"] == "count"
    assert m["count_distinct"]["tool"] == "sql"
    assert m["count_distinct"]["sql"] == "SELECT count(DISTINCT <column>) FROM <table>"


def test_shared_column_sets_are_given_once():
    a, b = _contract("a"), _contract("b")
    c = _contract("c", entities={"other_id": "a"})
    d = describe([c, b, a])
    assert [t["name"] for t in d["tables"]] == ["a", "b", "c"]
    assert "columns" in _tables(d)["a"] and _tables(d)["b"]["columns_as"] == "a"
    assert _tables(d)["c"]["columns_as"] == "a"   # the same columns; its links are its own
    assert _tables(d)["c"]["links"] == {"other_id": "a.entity_id"}
    assert "links" not in _tables(d)["a"]
    assert _columns(d, "b") == _columns(d, "a") == _columns(d, "c")
    cols = [a.columns[0].model_copy(update={"description": "Another id."}), *a.columns[1:]]
    other = _contract("d").model_copy(update={"table": "d", "columns": cols})
    assert "columns" in _tables(describe([a, other]))["d"]   # different columns: its own set
    # allowed values are listed per table, so they do not split a column set
    e = _contract("e", allowed=["x"])
    shared = _tables(describe([a, e]))["e"]
    assert shared["columns_as"] == "a" and shared["allowed"] == {"kind": ["x"]}


def test_describe_is_deterministic():
    contracts = list(load_contracts().values())
    assert json.dumps(describe(contracts)) == json.dumps(describe(contracts[::-1]))


def test_the_sql_note_names_the_hidden_columns():
    note = describe([_contract()])["sql"]
    assert "_doc_id" in note and "_prov_" in note and "json_each" in note
