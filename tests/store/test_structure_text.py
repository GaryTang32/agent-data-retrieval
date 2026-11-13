"""The shared layer every parser ends with: paragraphs, heading alignment, assembly; and txt."""

import hashlib

from adr_store.conformance import check
from adr_store.records import Element, SourceRecord, sha256_text
from adr_store.structure import text as st


def doc_id(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def conforms(elements: list[Element], text: str, raw: bytes, fmt: str = "txt") -> list[str]:
    src = SourceRecord(doc_id=doc_id(raw), uri="file://x", format=fmt, source_version="1",
                       byte_length=len(raw), text_sha256=sha256_text(text),
                       text_length=len(text), extractor="e", parser="p", license=None)
    return check(src, elements, text, raw)


def slices(elements, text, type_=None):
    return [text[e.char_start:e.char_end] for e in elements if type_ in (None, e.type)]


def test_paragraphs_split_on_blank_lines_and_keep_single_newlines():
    text = "  One line\nstill one.\n\n\nTwo.\n \nThree.  \n"
    spans = st.paragraphs(text, 0, len(text))
    assert [text[b.start:b.end] for b in spans] == ["One line\nstill one.", "Two.", "Three."]
    assert {b.type for b in spans} == {"paragraph"}


def test_paragraphs_break_at_a_form_feed_only_when_asked():
    text = "page one\f page two"
    assert len(st.paragraphs(text, 0, len(text))) == 1
    two = st.paragraphs(text, 0, len(text), page_breaks=True)
    assert [text[b.start:b.end] for b in two] == ["page one", "page two"]


def test_paragraphs_of_a_blank_region_are_empty():
    assert st.paragraphs("a \n\n b", 1, 4) == []


def test_txt_parse_tiles_the_text():
    text = "Alpha beta.\n\nGamma\ndelta.\n"
    raw = text.encode()
    els = st.parse(raw, text, doc_id(raw))
    assert slices(els, text) == ["Alpha beta.", "Gamma\ndelta."]
    assert all(e.parent_id is None and e.section_path == [] and e.page is None for e in els)
    assert all(e.confidence == 1.0 and e.level is None and e.title is None for e in els)
    assert [e.order for e in els] == [0, 1]
    assert conforms(els, text, raw) == []


def test_txt_parse_of_empty_text_gives_no_elements():
    assert st.parse(b"", "", doc_id(b"")) == []


DOC = "Intro text.\n\nA\n\nbody a\n\nA1\n\nbody a1\n\nB\n\nbody b\n"


def _headings(*titles_ranks):
    out = []
    pos = 0
    for title, rank in titles_ranks:
        i = DOC.index(f"\n{title}\n", pos) + 1
        out.append(st.Heading(i, i + len(title), rank, title))
        pos = i + len(title)
    return out


def test_assemble_nests_sections_by_rank_and_tiles():
    raw = DOC.encode()
    heads = _headings(("A", 2), ("A1", 3), ("B", 2))
    blocks = st.blocks_between(DOC, heads, st.paragraphs)
    els = st.assemble(doc_id(raw), DOC, heads, blocks)
    assert conforms(els, DOC, raw) == []
    secs = {e.title: e for e in els if e.type == "section"}
    assert [(t, s.level, s.section_path) for t, s in secs.items()] == [
        ("A", 1, []), ("A1", 2, ["A"]), ("B", 1, [])]
    # a section runs to the next heading of the same or a higher rank, minus trailing space
    assert DOC[secs["A"].char_start:secs["A"].char_end] == "A\n\nbody a\n\nA1\n\nbody a1"
    assert DOC[secs["A1"].char_start:secs["A1"].char_end] == "A1\n\nbody a1"
    assert DOC[secs["B"].char_start:secs["B"].char_end] == "B\n\nbody b"
    intro = next(e for e in els if DOC[e.char_start:e.char_end] == "Intro text.")
    assert intro.parent_id is None and intro.section_path == []
    a1_start = secs["A1"].char_start
    heading_a1 = next(e for e in els if e.type == "heading" and e.char_start == a1_start)
    assert heading_a1.parent_id == secs["A1"].element_id
    assert heading_a1.level == 2 and heading_a1.section_path == ["A", "A1"]
    body_a1 = next(e for e in els if DOC[e.char_start:e.char_end] == "body a1")
    assert body_a1.parent_id == secs["A1"].element_id and body_a1.level is None


def test_assemble_orders_by_start_then_longest_first():
    raw = DOC.encode()
    heads = _headings(("A", 1), ("A1", 2), ("B", 1))
    els = st.assemble(doc_id(raw), DOC, heads, st.blocks_between(DOC, heads, st.paragraphs))
    assert [e.order for e in els] == list(range(len(els)))
    keys = [(e.char_start, -e.char_end) for e in els]
    assert keys == sorted(keys)
    first_a = [e.type for e in els if e.char_start == heads[0].start]
    assert first_a == ["section", "heading"]


def test_assemble_confidence_for_sections_and_pages():
    text = "1 Intro\n\nfirst page\n\f\nsecond page\n\f\n2 Next\n\nthird"
    raw = text.encode()
    heads = [st.Heading(0, 7, 1, "1 Intro"), st.Heading(text.index("2 Next"),
                                                         text.index("2 Next") + 6, 1, "2 Next")]
    blocks = st.blocks_between(text, heads, lambda t, a, b: st.paragraphs(t, a, b, True))
    els = st.assemble(doc_id(raw), text, heads, blocks, section_confidence=0.6, pages=True)
    assert conforms(els, text, raw, "pdf") == []
    by_text = {text[e.char_start:e.char_end]: e for e in els if e.is_leaf}
    assert by_text["first page"].page == 1
    assert by_text["second page"].page == 2
    assert by_text["2 Next"].page == 3 and by_text["third"].page == 3
    assert by_text["first page"].confidence == 1.0
    assert {e.confidence for e in els if e.type in ("section", "heading")} == {0.6}


def test_align_searches_forward_and_drops_what_it_cannot_find():
    text = "Title\nIntro mentions Scope inline.\nScope\nbody\nMissing? no\nScope\nmore\nEnd\n"
    found, dropped = st.align(text, [
        st.Candidate(("Title",), 1, "Title"),
        st.Candidate(("Scope",), 2, "Scope"),
        st.Candidate(("Not here",), 2, "Not here"),
        st.Candidate(("Scope",), 2, "Scope"),
        st.Candidate(("Title",), 2, "Title"),  # only earlier in the text: dropped
        st.Candidate(("End",), 2, "End"),
    ])
    assert dropped == 2
    starts = [h.start for h in found]
    assert [text[h.start:h.end] for h in found] == ["Title", "Scope", "Scope", "End"]
    assert starts == sorted(starts) and starts[1] == text.index("\nScope\n") + 1
    assert starts[2] == text.index("\nScope\nmore") + 1


def test_align_matches_whole_lines_after_collapsing_whitespace():
    text = "intro\n  Part  1.   General \nrest\nPart 2\ncontinued\nafter\n"
    found, dropped = st.align(text, [
        st.Candidate(("Part 1. General",), 1, "Part 1. General"),
        st.Candidate(("Part 2", "continued"), 1, "Part 2 continued"),
    ])
    assert dropped == 0
    assert text[found[0].start:found[0].end] == "Part  1.   General"
    assert text[found[1].start:found[1].end] == "Part 2\ncontinued"
    assert found[1].title == "Part 2 continued"


def test_align_does_not_match_inside_a_line():
    found, dropped = st.align("- Background\nBackground of it\n",
                              [st.Candidate(("Background",), 1, "Background")])
    assert (found, dropped) == ([], 1)


def test_collapse():
    assert st.collapse("  a \t b \nc  ") == "a b c"
