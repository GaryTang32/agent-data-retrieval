import hashlib
import json
from pathlib import Path

from adr_eval.corpora.extract import extract_text
from adr_store.structure import parse_document
from adr_store.structure import records as sr
from tests.store.test_structure_text import conforms, slices

MINI = Path(__file__).parents[1] / "fixtures" / "mini"


def _parse(raw: bytes, fmt: str):
    text = extract_text(raw, fmt)
    return text, sr.parse(raw, text, hashlib.sha256(raw).hexdigest(), fmt=fmt)


def test_json_is_one_record_per_document():
    raw = (MINI / "records.json").read_bytes()
    text, els = _parse(raw, "json")
    assert [e.type for e in els] == ["record"]
    assert slices(els, text) == [text.strip()]
    assert json.loads(slices(els, text)[0]) == json.loads(raw)
    assert conforms(els, text, raw, "json") == []


def test_csv_header_and_each_row_are_records():
    raw = b'id,title\r\n1,"Plain"\r\n\r\n2,"Two\nlines, ""quoted"""\n3,last'
    text, els = _parse(raw, "csv")
    assert {e.type for e in els} == {"record"}
    assert slices(els, text) == ['id,title', '1,"Plain"', '2,"Two\nlines, ""quoted"""',
                                 '3,last']
    assert conforms(els, text, raw, "csv") == []


def test_csv_unclosed_quote_runs_to_the_end():
    raw = b'a,b\n1,"open\n2,x\n'
    text, els = _parse(raw, "csv")
    assert slices(els, text) == ["a,b", '1,"open\n2,x']


def test_dispatcher_routes_records_formats():
    raw = b"x,y\n1,2\n"
    text = extract_text(raw, "csv")
    parsed = parse_document("csv", raw, text, hashlib.sha256(raw).hexdigest())
    assert len(parsed.elements) == 2 and parsed.headings_found == 0


def test_empty_json_text_gives_no_elements():
    raw = b"{}"
    text, els = _parse(raw, "json")
    assert slices(els, text) == ["{}"]
