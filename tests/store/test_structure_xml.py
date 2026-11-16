import hashlib
from pathlib import Path

from adr_eval.corpora.extract import extract_text
from adr_store.structure import parse_document
from adr_store.structure import xml as sxml
from tests.store.test_structure_text import conforms, slices

FIXTURES = Path(__file__).parents[1] / "fixtures"
ECFR = (FIXTURES / "store" / "ecfr_part.xml").read_bytes()


def _parse(raw: bytes):
    text = extract_text(raw, "xml")
    return text, sxml.parse_with_stats(raw, text, hashlib.sha256(raw).hexdigest())


def test_ecfr_divisions_become_nested_sections():
    text, parsed = _parse(ECFR)
    assert conforms(parsed.elements, text, ECFR, "xml") == []
    assert (parsed.headings_found, parsed.headings_aligned) == (9, 9)
    secs = [(e.level, e.title) for e in parsed.elements if e.type == "section"]
    assert secs == [
        (1, "PART 99—TEST RULES"),
        (2, "Subpart A—General"),
        (3, "§ 99.1 Scope."),
        (3, "§ 99.2 Definitions with emphasis."),
        (3, "§ 99.3 Long title."),
        (2, "Subpart B—Drawbridges"),
        (3, "Specific Requirements"),
        (4, "§ 99.10 Alpha River."),
        (2, "Appendix A to Part 99—Figures"),
    ]


def test_ecfr_section_ranges_and_paragraph_leaves():
    text, parsed = _parse(ECFR)
    by_title = {e.title: e for e in parsed.elements if e.type == "section"}
    s991 = by_title["§ 99.1 Scope."]
    assert text[s991.char_start:s991.char_end] == (
        "§ 99.1 Scope.\nThis part applies to test vessels.\n(a) A second paragraph.\n"
        "[1 FR 1, Jan. 1, 2000]")
    kids = [e for e in parsed.elements if e.parent_id == s991.element_id]
    assert [(e.type, text[e.char_start:e.char_end]) for e in kids] == [
        ("heading", "§ 99.1 Scope."), ("paragraph", "This part applies to test vessels."),
        ("paragraph", "(a) A second paragraph."), ("paragraph", "[1 FR 1, Jan. 1, 2000]")]
    assert kids[1].section_path == ["PART 99—TEST RULES", "Subpart A—General",
                                    "§ 99.1 Scope."]
    # a heading split by a block element spans two lines of the canonical text
    assert "§ 99.3 Long\ntitle." in slices(parsed.elements, text, "heading")
    assert set(slices(parsed.elements, text, "paragraph")) >= {"Authority:", "1 U.S.C. 1."}


def test_mini_generic_xml_heading_element():
    raw = (FIXTURES / "mini" / "regulation_s12_2023-01-01.xml").read_bytes()
    text = extract_text(raw, "xml")
    parsed = parse_document("xml", raw, text, hashlib.sha256(raw).hexdigest())
    assert [e.title for e in parsed.elements if e.type == "section"] == ["Filing deadlines"]
    assert conforms(parsed.elements, text, raw, "xml") == []


def test_xml_without_headings_is_paragraphs():
    raw = b"<r><p>one</p><p>two <b>bold</b></p></r>"
    text, parsed = _parse(raw)
    assert slices(parsed.elements, text) == ["one", "two bold"]
    assert parsed.headings_found == 0
