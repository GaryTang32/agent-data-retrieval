import hashlib
import json

import pytest
from pydantic import ValidationError

from adr_store import records
from adr_store.records import DocRecord, Element, SourceRecord, element_id, sha256_text

DOC = "a" * 64


def _source(**kw) -> SourceRecord:
    base = dict(doc_id=DOC, uri="file://x.md", format="md", source_version="1", byte_length=3,
                text_sha256=sha256_text("abc"), text_length=3, extractor="adr_eval.extract/2",
                parser="adr_store.structure/1", license=None)
    return SourceRecord(**{**base, **kw})


def _element(**kw) -> Element:
    base = dict(element_id=element_id(DOC, "paragraph", 0, 3), doc_id=DOC, type="paragraph",
                char_start=0, char_end=3, parent_id=None, order=0, level=None, title=None,
                section_path=[], page=None, confidence=1.0, text_sha256=sha256_text("abc"))
    return Element(**{**base, **kw})


def test_element_id_is_sha256_of_the_four_fields_joined_by_newlines():
    want = hashlib.sha256(f"{DOC}\nheading\n4\n9".encode()).hexdigest()
    assert element_id(DOC, "heading", 4, 9) == want


def test_sha256_text_hashes_utf8():
    assert sha256_text("é") == hashlib.sha256("é".encode()).hexdigest()


def test_doc_record_round_trips_through_json():
    rec = DocRecord(source=_source(), elements=[_element()])
    assert DocRecord.model_validate_json(rec.model_dump_json()) == rec


def test_canonical_json_is_sorted_and_stable():
    rec = DocRecord(source=_source(), elements=[_element()])
    data = records.canonical_json(rec)
    assert data == records.canonical_json(DocRecord.model_validate_json(data))
    parsed = json.loads(data)
    assert list(parsed) == sorted(parsed)
    assert data.endswith(b"\n")


@pytest.mark.parametrize("bad", [
    {"format": "docx"},
    {"doc_id": "XYZ"},
    {"byte_length": -1},
    {"text_length": -1},
    {"unknown_field": 1},
])
def test_source_record_rejects_bad_values(bad):
    with pytest.raises(ValidationError):
        _source(**bad)


@pytest.mark.parametrize("bad", [
    {"type": "figure"},
    {"char_start": -1},
    {"char_start": 4, "char_end": 3},
    {"confidence": 1.5},
    {"parent_id": "nothex"},
    {"level": 0},
    {"page": 0},
])
def test_element_rejects_bad_values(bad):
    with pytest.raises(ValidationError):
        _element(**bad)


def test_leaf_types_are_every_type_but_section():
    assert records.LEAF_TYPES == {"heading", "paragraph", "list_item", "table", "code", "record"}
    assert _element().is_leaf
    assert not _element(type="section").is_leaf


def test_committed_schema_files_are_current():
    """Regenerate with `python -m adr_store.records` when this fails."""
    for name, schema in records.schemas().items():
        path = records.SCHEMA_DIR / name
        assert path.is_file(), f"missing {path}; run python -m adr_store.records"
        assert path.read_text(encoding="utf-8") == records.render_schema(schema), (
            f"{path} is stale; run python -m adr_store.records")


def test_no_stray_schema_files():
    committed = {p.name for p in records.SCHEMA_DIR.glob("*.json")}
    assert committed == set(records.schemas())


def test_write_schemas_writes_every_schema(tmp_path):
    written = records.write_schemas(tmp_path)
    assert sorted(p.name for p in written) == sorted(records.schemas())
    for p in written:
        assert json.loads(p.read_text(encoding="utf-8"))["title"]
