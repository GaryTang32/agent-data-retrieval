import hashlib
from pathlib import Path

import pytest

from adr_eval.corpora.extract import extract_text
from adr_store.structure import parse_document
from adr_store.structure import pdf as spdf
from tests.store.test_structure_text import conforms, slices

FIXTURES = Path(__file__).parents[1] / "fixtures"
# pypdf-like page texts joined by "\n\f\n", as the harness extractor joins them
PAGES = (FIXTURES / "store" / "paper_pages.txt").read_bytes()
TEXT = PAGES.decode("utf-8")


def _parsed(text: str = TEXT):
    raw = text.encode("utf-8")
    return spdf.parse_with_stats(raw, text, hashlib.sha256(raw).hexdigest())


def test_fixture_has_form_feed_page_breaks():
    assert TEXT.count("\n\f\n") == 2


def test_paper_conforms():
    assert conforms(_parsed().elements, TEXT, PAGES, "pdf") == []


def test_headings_are_conservative():
    parsed = _parsed()
    assert slices(parsed.elements, TEXT, "heading") == [
        "Abstract", "1 Introduction", "2 Related Work", "2.1 Sparse Methods",
        "2.2 Dense Methods", "4 Method", "Results", "References"]
    assert (parsed.headings_found, parsed.headings_aligned) == (8, 8)


def test_sections_nest_by_number_depth_with_heuristic_confidence():
    els = _parsed().elements
    secs = [(e.level, e.title, e.page) for e in els if e.type == "section"]
    assert secs == [(1, "Abstract", 1), (1, "1 Introduction", 1), (1, "2 Related Work", 2),
                    (2, "2.1 Sparse Methods", 2), (2, "2.2 Dense Methods", 2),
                    (1, "4 Method", 3), (1, "Results", 3), (1, "References", 3)]
    assert {e.confidence for e in els if e.type in ("section", "heading")} == {0.6}
    assert {e.confidence for e in els if e.type == "paragraph"} == {1.0}


def test_every_leaf_has_its_page_and_a_form_feed_ends_a_paragraph():
    els = _parsed().elements
    for e in els:
        assert e.page == 1 + TEXT.count("\f", 0, e.char_start)
        assert "\f" not in TEXT[e.char_start:e.char_end]
    intro = next(e for e in els if TEXT[e.char_start:e.char_end].startswith("Retrieval"))
    assert TEXT[intro.char_start:intro.char_end].endswith("reviews prior work.")
    assert intro.section_path == ["1 Introduction"]


def test_text_before_the_first_heading_has_no_section():
    first = _parsed().elements[0]
    assert first.type == "paragraph" and first.parent_id is None
    assert TEXT[first.char_start:first.char_end].endswith("2 Institute of Things")


@pytest.mark.parametrize("line", [
    "2019. A year is not a heading",
    "3 A sentence that ends with a full stop.",
    "1 University of Somewhere, London",
    "12 lowercase title",
    "1 A heading with far too many words to be a real section heading in a paper",
    "1 Japan 7 10 24",
    "1 A title broken across lines by hyphen-",
])
def test_numbered_lines_that_are_not_headings(line):
    text = f"Abstract\n{line}\n"
    assert slices(_parsed(text).elements, text, "heading") == ["Abstract"]


def test_numbered_headings_without_an_anchor_still_count():
    text = "Title page\n1 Overview\nbody\n2 Scope\nmore\n2.1 Limits\nend"
    assert slices(_parsed(text).elements, text, "heading") == [
        "1 Overview", "2 Scope", "2.1 Limits"]


def test_mini_pdf_through_the_dispatcher():
    raw = (FIXTURES / "mini" / "service_charter.pdf").read_bytes()
    text = extract_text(raw, "pdf")
    parsed = parse_document("pdf", raw, text, hashlib.sha256(raw).hexdigest())
    assert conforms(parsed.elements, text, raw, "pdf") == []
    assert [e.page for e in parsed.elements] == [1, 2]


def test_top_level_numbering_keeps_one_style():
    text = "1 Introduction\nbody\n2. Do this step first\nbody\n2 Method\nbody\n3. And this"
    assert slices(_parsed(text).elements, text, "heading") == ["1 Introduction", "2 Method"]


def test_no_numbered_headings_after_the_references():
    text = "1 Introduction\nbody\nReferences\n[1] A paper.\n2 Appendix Material\nAppendix A"
    assert slices(_parsed(text).elements, text, "heading") == [
        "1 Introduction", "References", "Appendix A"]
