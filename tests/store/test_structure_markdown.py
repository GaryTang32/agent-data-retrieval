import hashlib
from pathlib import Path

import pytest

from adr_store.structure import markdown as smd
from adr_store.structure import parse_document
from tests.store.test_structure_text import conforms, slices

FIXTURES = Path(__file__).parents[1] / "fixtures"
GUIDE = (FIXTURES / "store" / "guide.md").read_bytes()


def _parse(raw: bytes):
    text = raw.decode("utf-8")
    return text, smd.parse_with_stats(raw, text, hashlib.sha256(raw).hexdigest())


def test_guide_conforms_and_counts_every_heading_as_aligned():
    text, parsed = _parse(GUIDE)
    assert conforms(parsed.elements, text, GUIDE, "md") == []
    assert (parsed.headings_found, parsed.headings_aligned) == (4, 4)


def test_guide_sections_nest_by_heading_depth():
    text, parsed = _parse(GUIDE)
    secs = [(e.level, e.title, e.section_path) for e in parsed.elements if e.type == "section"]
    assert secs == [(1, "Field Guide", []), (2, "Steps", ["Field Guide"]),
                    (3, "Detail", ["Field Guide", "Steps"]), (2, "Notes", ["Field Guide"])]
    assert {e.confidence for e in parsed.elements} == {1.0}


def test_guide_leaf_types():
    text, parsed = _parse(GUIDE)
    els = parsed.elements
    assert slices(els, text, "heading") == ["# Field Guide", "## Steps", "### Detail ###",
                                            "## Notes"]
    assert slices(els, text, "list_item") == [
        "1. First step.", "2. Second step\n   continues here.", "- Bullet one",
        "- Nested bullet"]
    assert slices(els, text, "table") == ["| Col | Val |\n|-----|-----|\n| a   | 1   |"]
    assert slices(els, text, "code") == ["```python\n# not a heading\nx = 1\n```"]
    assert slices(els, text, "paragraph") == [
        "Preamble line before any heading.", "Intro paragraph\nover two lines.",
        "Detail text.", "Closing paragraph.\n#hashtag is not a heading"]
    preamble = els[0]
    assert preamble.parent_id is None and preamble.section_path == []


def test_headings_inside_code_are_ignored_and_an_open_fence_runs_to_the_end():
    raw = b"# A\n\n~~~\n# no\n"
    text, parsed = _parse(raw)
    assert slices(parsed.elements, text, "code") == ["~~~\n# no"]
    assert parsed.headings_found == 1


def test_crlf_and_heading_right_after_text():
    raw = b"Lead\r\n## Two\r\nbody\r\n"
    text, parsed = _parse(raw)
    assert conforms(parsed.elements, text, raw, "md") == []
    assert slices(parsed.elements, text, "heading") == ["## Two"]
    assert slices(parsed.elements, text, "paragraph") == ["Lead", "body"]


@pytest.mark.parametrize("line", ["#", "#hashtag", "####### seven", "    # indented code"])
def test_lines_that_are_not_atx_headings(line):
    raw = line.encode()
    _, parsed = _parse(raw)
    assert parsed.headings_found == 0
    assert [e.type for e in parsed.elements] == ["paragraph"]


def test_mini_markdown_through_the_dispatcher():
    raw = (FIXTURES / "mini" / "refund_policy.md").read_bytes()
    text = raw.decode()
    parsed = parse_document("md", raw, text, hashlib.sha256(raw).hexdigest())
    titles = [e.title for e in parsed.elements if e.type == "section"]
    assert titles == ["Agency Refund Policy", "Eligibility", "Processing", "Exceptions"]
    assert conforms(parsed.elements, text, raw, "md") == []
