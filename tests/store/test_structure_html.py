import hashlib
from pathlib import Path

from adr_eval.corpora.extract import extract_text
from adr_store.structure import html as shtml
from adr_store.structure import parse_document
from tests.store.test_structure_text import conforms, slices

FIXTURES = Path(__file__).parents[1] / "fixtures"
NESTED = (FIXTURES / "store" / "nested.html").read_bytes()


def _parse(raw: bytes):
    text = extract_text(raw, "html")
    return text, shtml.parse_with_stats(raw, text, hashlib.sha256(raw).hexdigest())


def test_nested_headings_become_nested_sections():
    text, parsed = _parse(NESTED)
    assert conforms(parsed.elements, text, NESTED, "html") == []
    secs = [(e.level, e.title, e.section_path) for e in parsed.elements if e.type == "section"]
    assert secs == [
        (1, "Permit Handbook", []),
        (2, "Applying for a permit", ["Permit Handbook"]),
        (3, "Required documents", ["Permit Handbook", "Applying for a permit"]),
        (3, "Fees and payment", ["Permit Handbook", "Applying for a permit"]),
        (2, "Renewing a permit", ["Permit Handbook"]),
        (2, "Appeals", ["Permit Handbook"]),
    ]
    assert {e.confidence for e in parsed.elements} == {1.0}


def test_headings_trafilatura_dropped_are_counted_not_hidden():
    # "Share this page" sits in boilerplate the extractor removes; navigation, footer and
    # callout labels ("Note:") are not section headings and are not counted at all
    _, parsed = _parse(NESTED)
    assert (parsed.headings_found, parsed.headings_aligned) == (7, 6)


def test_leaves_are_lines_list_items_and_tables():
    text, parsed = _parse(NESTED)
    els = parsed.elements
    assert slices(els, text, "list_item") == [
        "- Proof of ownership, such as a bill of sale or registration certificate.",
        "- A safety inspection report dated within the last twelve months."]
    assert slices(els, text, "table") == [
        "| Permit | Fee | \n|---|---|\n| Standard | 120 | \n| Renewal | 80 |"]
    assert "Note:" in slices(els, text, "paragraph")
    assert "Renewing\na permit" in slices(els, text, "heading")
    fees = next(e for e in els if e.title == "Fees and payment")
    table = next(e for e in els if e.type == "table")
    assert table.parent_id == fees.element_id


def test_mini_html_through_the_dispatcher():
    raw = (FIXTURES / "mini" / "procedure.html").read_bytes()
    text = extract_text(raw, "html")
    parsed = parse_document("html", raw, text, hashlib.sha256(raw).hexdigest())
    assert [e.title for e in parsed.elements if e.type == "section"] == [
        "Filing a Change of Address"]
    assert len([e for e in parsed.elements if e.type == "list_item"]) == 4
    assert conforms(parsed.elements, text, raw, "html") == []


def test_no_heading_aligns_falls_back_to_paragraphs():
    raw = b"<html><body><h2>Gone</h2><article><p>" + b"Some words here. " * 20 + b"</p>" \
          b"<p>" + b"More text follows. " * 20 + b"</p></article></body></html>"
    text = extract_text(raw, "html")
    found = shtml.parse_with_stats(raw, text, hashlib.sha256(raw).hexdigest())
    assert (found.headings_found, found.headings_aligned) == (1, 0)
    assert [e.type for e in found.elements] == ["paragraph", "paragraph"]
    assert conforms(found.elements, text, raw, "html") == []


def test_empty_page():
    raw = b"<html><body></body></html>"
    parsed = shtml.parse_with_stats(raw, "", hashlib.sha256(raw).hexdigest())
    assert parsed.elements == [] and parsed.headings_found == 0
