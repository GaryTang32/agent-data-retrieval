import hashlib

import pytest

from adr_store.conformance import check
from adr_store.records import Element, SourceRecord, element_id, sha256_text

TEXT = "# T\n\nHello world.\n\n## S\n\nBody.\n"
RAW = TEXT.encode("utf-8")
DOC = hashlib.sha256(RAW).hexdigest()


def _source(**kw) -> SourceRecord:
    base = dict(doc_id=DOC, uri="file://t.md", format="md", source_version="1",
                byte_length=len(RAW), text_sha256=sha256_text(TEXT), text_length=len(TEXT),
                extractor="adr_eval.extract/2", parser="adr_store.structure/1", license=None)
    return SourceRecord(**{**base, **kw})


def _span(s: str) -> tuple[int, int]:
    i = TEXT.index(s)
    return i, i + len(s)


def _elements() -> list[Element]:
    """A valid tree: section T (heading, paragraph, section S (heading, paragraph))."""
    specs = [  # type, (start, end), parent index, level, title
        ("section", (0, len(TEXT) - 1), None, 1, "T"),
        ("heading", _span("# T"), 0, 1, None),
        ("paragraph", _span("Hello world."), 0, None, None),
        ("section", (_span("## S")[0], len(TEXT) - 1), 0, 2, "S"),
        ("heading", _span("## S"), 3, 2, None),
        ("paragraph", _span("Body."), 3, None, None),
    ]
    out: list[Element] = []
    for i, (type_, (a, b), parent, level, title) in enumerate(specs):
        path = []
        p = parent
        while p is not None:
            path.insert(0, specs[p][4])
            p = specs[p][2]
        out.append(Element(
            element_id=element_id(DOC, type_, a, b), doc_id=DOC, type=type_, char_start=a,
            char_end=b, parent_id=None if parent is None else out[parent].element_id, order=i,
            level=level, title=title, section_path=path, page=None, confidence=1.0,
            text_sha256=sha256_text(TEXT[a:b])))
    return out


def _with(elements: list[Element], i: int, **update) -> list[Element]:
    """Copy of `elements` with element i changed (without re-validation)."""
    return [e.model_copy(update=update) if k == i else e for k, e in enumerate(elements)]


def _fix_ids(elements: list[Element]) -> list[Element]:
    return [e.model_copy(update={
        "element_id": element_id(e.doc_id, e.type, e.char_start, e.char_end),
        "text_sha256": sha256_text(TEXT[e.char_start:e.char_end])}) for e in elements]


def _rules(problems: list[str]) -> set[str]:
    return {p.split(":", 1)[0] for p in problems}


def test_a_valid_document_conforms():
    assert check(_source(), _elements(), TEXT, RAW) == []


def test_no_elements_conform_only_for_whitespace_text():
    assert check(_source(), [], TEXT, RAW) and _rules(check(_source(), [], TEXT, RAW)) == {"rule 1"}
    blank = " \n"
    src = _source(doc_id=hashlib.sha256(blank.encode()).hexdigest(), byte_length=2,
                  text_sha256=sha256_text(blank), text_length=2)
    assert check(src, [], blank, blank.encode()) == []


def test_rule1_non_whitespace_gap():
    els = [e for k, e in enumerate(_elements()) if k != 2]  # drop "Hello world."
    els = [e.model_copy(update={"order": k}) for k, e in enumerate(els)]
    problems = check(_source(), els, TEXT, RAW)
    assert _rules(problems) == {"rule 1"}
    assert "Hello" in problems[0]


def test_rule1_overlapping_leaves():
    a, _ = _span("Hello world.")
    els = _fix_ids(_with(_elements(), 1, char_end=a + 3))  # heading runs into the paragraph
    assert "rule 1" in _rules(check(_source(), els, TEXT, RAW))


def test_rule1_leaf_past_the_end_and_empty_leaf():
    n = len(TEXT)
    els = _fix_ids(_with(_elements(), 5, char_end=n + 4))
    assert "rule 1" in _rules(check(_source(), els, TEXT, RAW))
    a, _ = _span("Body.")
    els = _fix_ids(_with(_elements(), 5, char_start=a, char_end=a))
    assert "rule 1" in _rules(check(_source(), els, TEXT, RAW))


def test_rule2_element_hash_mismatch():
    els = _with(_elements(), 2, text_sha256=sha256_text("other"))
    assert _rules(check(_source(), els, TEXT, RAW)) == {"rule 2"}


@pytest.mark.parametrize("update", [{"text_sha256": sha256_text("x")}, {"text_length": 3}])
def test_rule2_source_text_fields(update):
    assert _rules(check(_source(**update), _elements(), TEXT, RAW)) == {"rule 2"}


def test_rule3_missing_parent():
    els = _with(_elements(), 5, parent_id="f" * 64)
    assert "rule 3" in _rules(check(_source(), els, TEXT, RAW))


def test_rule3_parent_must_be_a_section():
    els = _elements()
    els = _with(els, 5, parent_id=els[4].element_id, section_path=["T", "S"])
    assert "rule 3" in _rules(check(_source(), els, TEXT, RAW))


def test_rule3_child_outside_parent():
    els = _elements()
    els = _fix_ids(_with(els, 3, char_end=_span("## S")[1]))  # section S ends before "Body."
    els = _with(els, 4, parent_id=els[3].element_id)
    els = _with(els, 5, parent_id=els[3].element_id)
    problems = check(_source(), els, TEXT, RAW)
    assert "rule 3" in _rules(problems)
    assert any("outside" in p for p in problems)


def test_rule3_overlapping_sibling_sections():
    els = _elements()
    # move section S to the top level, still starting inside T: siblings overlap
    els = _with(els, 3, parent_id=None, section_path=[])
    els = _with(els, 4, section_path=["S"])
    els = _with(els, 5, section_path=["S"])
    problems = check(_source(), els, TEXT, RAW)
    assert "rule 3" in _rules(problems)
    assert any("overlap" in p for p in problems)


def test_rule3_section_path_must_match_ancestors():
    els = _with(_elements(), 5, section_path=["T"])
    assert _rules(check(_source(), els, TEXT, RAW)) == {"rule 3"}


def test_rule4_doc_id_must_hash_the_raw_bytes():
    problems = check(_source(), _elements(), TEXT, RAW + b"x")
    assert "rule 4" in _rules(problems)


def test_rule4_byte_length():
    assert _rules(check(_source(byte_length=1), _elements(), TEXT, RAW)) == {"rule 4"}


def test_rule4_element_id_must_follow_the_spec():
    els = _with(_elements(), 2, element_id="0" * 64)
    assert "rule 4" in _rules(check(_source(), els, TEXT, RAW))


def test_rule4_duplicate_ids():
    els = _elements()
    els = els + [els[2].model_copy(update={"order": 6})]
    problems = check(_source(), els, TEXT, RAW)
    assert "rule 4" in _rules(problems)
    assert any(p.startswith("rule 4:") and "element_id is not unique" in p for p in problems)


def test_rule4_element_belongs_to_the_source():
    els = _with(_elements(), 2, doc_id="b" * 64)
    assert "rule 4" in _rules(check(_source(), els, TEXT, RAW))


def test_rule4_order_follows_start_then_longest_first():
    els = _elements()
    els = _with(_with(els, 1, order=2), 2, order=1)
    assert _rules(check(_source(), els, TEXT, RAW)) == {"rule 4"}


def test_rule2_every_element_range_lies_in_the_text():
    n = len(TEXT)
    # the slice is cut at the text's end, so the hash of the slice still matches
    els = _with(_elements(), 0, char_end=n + 5, text_sha256=sha256_text(TEXT))
    problems = check(_source(), els, TEXT, RAW)
    assert any(p.startswith("rule 2:") and "outside the text" in p for p in problems)


def test_rule2_start_after_end_is_reported():
    els = _with(_elements(), 3, char_start=20, char_end=19)
    assert any(p.startswith("rule 2:") and "outside the text" in p
               for p in check(_source(), els, TEXT, RAW))


def test_rule3_section_level_is_its_depth():
    els = _with(_elements(), 0, level=2)  # top-level section T
    problems = check(_source(), els, TEXT, RAW)
    assert _rules(problems) == {"rule 3"}
    assert any("level 2" in p and "depth 1" in p for p in problems)


def test_rule3_heading_level_is_its_section_level():
    els = _with(_elements(), 4, level=1)  # heading of section S (level 2)
    problems = check(_source(), els, TEXT, RAW)
    assert _rules(problems) == {"rule 3"}
    assert any("heading" in p and "level 1" in p for p in problems)


def test_rule3_a_heading_belongs_to_a_section():
    els = _with(_elements(), 1, parent_id=None, section_path=[])
    assert any(p.startswith("rule 3:") and "not inside a section" in p
               for p in check(_source(), els, TEXT, RAW))


@pytest.mark.parametrize("update", [{"level": 1}, {"title": "Hello"}])
def test_leaves_other_than_headings_have_no_level_or_title(update):
    els = _with(_elements(), 2, **update)  # the paragraph "Hello world."
    problems = check(_source(), els, TEXT, RAW)
    assert _rules(problems) == {"record"}


def test_page_is_null_outside_pdf():
    els = _with(_elements(), 2, page=1)
    assert _rules(check(_source(), els, TEXT, RAW)) == {"record"}
    assert check(_source(format="pdf"), els, TEXT, RAW) == []
