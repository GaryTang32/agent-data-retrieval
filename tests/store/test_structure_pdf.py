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


# Lines seen in real papers that are sentence fragments, not headings: an appendix named in
# running text, wrapped so that it starts a line (review of the research corpus).
@pytest.mark.parametrize("line", [
    "Appendix A.8), balancing cost.Call 1",
    "Appendix D. These results emphasize the impor-",
    "appendix. A manual evaluation on a sam-",
    "Appendix F). This is due in part",
    "Appendix C.3. In addition to the overall",
    "Appendix A and filter out a subset",
    "Appendix F proves the bound. The",
    "Appendix E.2",
    "Appendix Results Of Everything",
    "Appendix A ), the next part",
    "APPENDIX A. A title broken by hyphen-",
])
def test_appendix_fragments_are_not_headings(line):
    text = f"Abstract\n{line}\n"
    assert slices(_parsed(text).elements, text, "heading") == ["Abstract"]


@pytest.mark.parametrize("line", [
    "Appendix", "APPENDIX", "Appendices", "Appendix A", "APPENDIX B",
    "Appendix B: Proof of Theorem 4", "Appendix C. Alternative Design", "Appendix A Related Work",
    "Appendix 1", "Appendix A1: Prompts",
])
def test_appendix_headings(line):
    text = f"Abstract\n{line}\nbody\n"
    assert slices(_parsed(text).elements, text, "heading") == ["Abstract", line]


@pytest.mark.parametrize("line", ["results", "abstract", "references", "discussion",
                                  "acknowledgements", "Abstract.", "Related work"])
def test_known_words_in_lower_or_sentence_case_are_not_headings(line):
    text = f"Title\n{line}\nbody\n"
    assert slices(_parsed(text).elements, text, "heading") == []


@pytest.mark.parametrize("line", ["Results", "RESULTS", "Related Work", "RELATED WORK",
                                  "Methods", "ACKNOWLEDGEMENTS"])
def test_known_words_in_title_or_upper_case_are_headings(line):
    text = f"Title\n{line}\nbody\n"
    assert slices(_parsed(text).elements, text, "heading") == [line]


def test_a_known_word_inside_numbered_section_n_before_n_plus_1_is_body_text():
    # a figure label "Discussion" between "3" and "3.1" must not take 3.1 to 3.2 from "3"
    text = ("ABSTRACT\nbody\n1 INTRODUCTION\nbody\n3 DATASET CONSTRUCTION\nbody\nDiscussion\n"
            "label\n3.1 Overview\nbody\n3.2 Grouping\nbody\n4 STUDY DESIGN\nbody\n")
    els = _parsed(text).elements
    assert slices(els, text, "heading") == [
        "ABSTRACT", "1 INTRODUCTION", "3 DATASET CONSTRUCTION", "3.1 Overview",
        "3.2 Grouping", "4 STUDY DESIGN"]
    sub = next(e for e in els if e.type == "section" and e.title == "3.2 Grouping")
    assert sub.section_path == ["3 DATASET CONSTRUCTION"]


def test_a_known_word_on_a_later_page_between_numbered_sections_is_body_text():
    text = "1. Introduction\nbody\n3. Overview\nbody\n\f\nABSTRACT\nbody\n4. The Framework\nbody\n"
    assert slices(_parsed(text).elements, text, "heading") == [
        "1. Introduction", "3. Overview", "4. The Framework"]


@pytest.mark.parametrize("word", ["Conclusion", "Conclusions", "Acknowledgments",
                                  "Acknowledgements", "Appendix", "Appendix A"])
def test_closing_words_may_still_end_a_numbered_section(word):
    text = f"1 Introduction\nbody\n{word}\nbody\n2 Method\nbody\n"
    assert slices(_parsed(text).elements, text, "heading") == [
        "1 Introduction", word, "2 Method"]


def test_known_words_after_the_last_numbered_or_across_a_gap_are_kept():
    text = "1 Introduction\nbody\nMethods\nbody\n3 Method Details\nbody\nResults\nbody\n"
    assert slices(_parsed(text).elements, text, "heading") == [
        "1 Introduction", "Methods", "3 Method Details", "Results"]


def test_a_later_known_word_counts_when_the_first_was_body_text():
    text = "1 Introduction\nbody\nResults\nlabel\n2 Method\nbody\nResults\nbody\n"
    els = _parsed(text).elements
    assert slices(els, text, "heading") == ["1 Introduction", "2 Method", "Results"]
    assert text.index("Results\nbody") == next(e.char_start for e in els if e.title == "Results")


def _digest(raw: bytes, text: str) -> tuple[str, int]:
    from adr_store.records import canonical_json

    els = spdf.parse(raw, text, hashlib.sha256(raw).hexdigest())
    return hashlib.sha256(b"".join(canonical_json(e) for e in els)).hexdigest(), len(els)


def test_parser_output_on_the_pdf_fixtures_is_pinned():
    # pinned before the dead hyphen and closing-mark checks were removed
    assert _digest(PAGES, TEXT) == (
        "f10284baa5afc8f5c4d40de2980f14c29e26be7bbc5ec7900160e10914493084", 25)
    raw = (FIXTURES / "mini" / "service_charter.pdf").read_bytes()
    assert _digest(raw, extract_text(raw, "pdf")) == (
        "0ce6e5ae48dfb6f6516240715c56eca837857b07908feaa577fa16bbe25db315", 2)


@pytest.mark.parametrize("line", [
    "3 Dense Retrie-", "Results-", "Appendix B Proof of the Bound-", "Appendix-",
    "REFERENCES-"])
def test_a_line_ending_in_a_hyphen_is_never_a_heading(line):
    text = f"Abstract\nbody\n{line}\nmore body"
    assert slices(_parsed(text).elements, text, "heading") == ["Abstract"]
