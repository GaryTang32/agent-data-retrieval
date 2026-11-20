"""The semantic layer (Phase 3 spec §8, ruling P18): `describe_tables` generated from the
contracts, as an index of every table and a per-table detail, each at most 8 KB."""

import json

import pytest

from adr_store.tables.contracts import Column, Contract, Source, load_contracts
from adr_store.tables.semantic import (
    ALLOWED_MAX,
    DESCRIBE_MAX_BYTES,
    ERR_UNKNOWN_TABLE,
    UnknownTable,
    describe,
)

INDEX_BUDGET = 6144   # three quarters of the limit: room for the 3B tables and later contracts


def _size(d) -> int:
    return len(json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode())


def _tables(d) -> dict[str, dict]:
    return {t["name"]: t for t in d["tables"]}


def _type(col) -> str:
    return f"{col.type}{'?' if col.nullable else ''}"


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


def test_the_index_covers_every_table_and_column_under_8_kb():
    contracts = load_contracts()
    d = describe(list(contracts.values()))
    assert DESCRIBE_MAX_BYTES == 8192
    assert _size(d) <= INDEX_BUDGET < DESCRIBE_MAX_BYTES
    assert [t["name"] for t in d["tables"]] == sorted(contracts)
    for name, c in contracts.items():
        t = _tables(d)[name]
        assert (t["description"], t["key"], t["list_column"], t["corpus"]) == \
            (c.description, c.key, c.list_column, c.source.corpus)
        assert t["columns"] == [f"{col.name}: {_type(col)}" for col in c.columns]
    assert {m["name"] for m in d["metrics"]} == {"count", "count_distinct"}
    assert "column descriptions" in d["detail"]


def test_the_index_has_links_and_dimensions_but_no_descriptions_or_values():
    contracts = load_contracts()
    d = describe(list(contracts.values()))
    fr = _tables(d)["fr_documents"]
    assert fr["dimensions"] == ["type", "status"]
    assert "allowed" not in fr and "Publication year." not in json.dumps(d)
    agencies = _tables(d)["fr_agencies"]
    assert agencies["links"] == {"agency_id": "agencies.entity_id"}
    assert agencies["dimensions"] == ["specific", "agency_id"]
    assert _tables(d)["papers"]["links"] == {"venue_id": "venues.entity_id",
                                             "licence_id": "licences.entity_id"}
    assert "links" not in _tables(d)["agencies"]


def test_every_table_detail_has_its_descriptions_and_allowed_values_under_8_kb():
    contracts = load_contracts()
    every = list(contracts.values())
    for name, c in contracts.items():
        t = describe(every, table=name)
        assert _size(t) <= DESCRIBE_MAX_BYTES
        assert t["name"] == name and t["description"] == c.description
        assert t["columns"] == {f"{col.name}: {_type(col)}": col.description
                                for col in c.columns}
        allowed = {col.name: col.allowed for col in c.columns if col.allowed is not None}
        assert t.get("allowed", {}) == allowed   # every committed set has at most 25 values
        assert {m["name"] for m in t["metrics"]} == {"count", "count_distinct"}
        assert "_prov_" in t["sql"]
    fr = describe(every, table="fr_documents")
    assert fr["columns"]["publication_date: date"].startswith("Date the document was published")
    assert fr["allowed"]["type"] == ["Rule", "Proposed Rule", "Notice", "Presidential Document"]
    assert fr["dimensions"] == ["type", "status"]


@pytest.mark.parametrize("table", ["nosuch", "FR_DOCUMENTS", "", 7, ["papers"]])
def test_an_unknown_table_is_a_fixed_message_error(table):
    with pytest.raises(UnknownTable) as e:
        describe(list(load_contracts().values()), table=table)
    assert str(e.value) == ERR_UNKNOWN_TABLE
    assert "nosuch" not in ERR_UNKNOWN_TABLE


def test_allowed_values_are_listed_up_to_25():
    listed = describe([_contract(allowed=[f"v{i}" for i in range(ALLOWED_MAX)])], table="t")
    assert ALLOWED_MAX == 25
    assert listed["allowed"] == {"kind": [f"v{i}" for i in range(25)]}
    unlisted = describe([_contract(allowed=[f"v{i}" for i in range(26)])], table="t")
    assert "allowed" not in unlisted
    assert unlisted["dimensions"] == ["kind", "flag"]   # still a categorical dimension


def test_metrics_are_a_query_table_count_and_an_sql_count_distinct():
    m = {x["name"]: x for x in describe([_contract()])["metrics"]}
    assert m["count"]["tool"] == "query_table" and m["count"]["args"]["op"] == "count"
    assert m["count_distinct"]["tool"] == "sql"
    assert m["count_distinct"]["sql"] == "SELECT count(DISTINCT <column>) FROM <table>"


def test_entity_links_name_the_entity_table_key():
    d = describe([_contract("a"), _contract("c", entities={"other_id": "a"})])
    assert _tables(d)["c"]["links"] == {"other_id": "a.entity_id"}
    assert _tables(d)["c"]["dimensions"] == ["flag", "other_id"]
    assert describe([_contract("c", entities={"other_id": "a"})], table="c")["links"] == \
        {"other_id": "a.entity_id"}


def test_describe_is_deterministic():
    contracts = list(load_contracts().values())
    assert json.dumps(describe(contracts)) == json.dumps(describe(contracts[::-1]))
    assert json.dumps(describe(contracts, table="papers")) == \
        json.dumps(describe(contracts[::-1], table="papers"))


def test_the_sql_note_names_the_hidden_columns():
    note = describe([_contract()])["sql"]
    assert "_doc_id" in note and "_prov_" in note and "json_each" in note
    assert "DISTINCT" in note and "subquery" in note   # the wide DISTINCT limit and its fix
    assert "group_concat is not a window function" in note
