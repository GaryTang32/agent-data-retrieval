"""Structure-led chunks (spec §7, §12 third bullet)."""

import hashlib
import json
from pathlib import Path

import pytest

from adr_eval.corpora.base import Document, load_corpus
from adr_eval.corpora.extract import extract_text
from adr_eval.retrieval.chunker import chunk_document, make_chunk_id, tokenize
from adr_store.chunking import StoreChunk, breadcrumb, chunk_store, document_title
from adr_store.store import Store

FIXTURES = Path(__file__).parents[1] / "fixtures"
MINI = FIXTURES / "mini"
GUIDE = (FIXTURES / "store" / "guide.md").read_bytes()
NESTED = (FIXTURES / "store" / "nested.html").read_bytes()
ECFR = (FIXTURES / "store" / "ecfr_part.xml").read_bytes()
PAGES = (FIXTURES / "store" / "paper_pages.txt").read_bytes()


def n_tokens(text: str) -> int:
    return len(tokenize(text, drop_stopwords=False))


def doc(raw: bytes, fmt: str, uri: str | None = None) -> tuple[Document, bytes]:
    """A document and its bytes; a "pdf" given as plain text is taken as its own extraction
    (PDF-like text with form feeds, as the PDF parser tests do)."""
    text = raw.decode("utf-8") if fmt == "pdf" else extract_text(raw, fmt)
    doc_id = hashlib.sha256(raw).hexdigest()
    return Document(doc_id, text, fmt, "1", uri or f"file://doc.{fmt}"), raw


def make_store(path: Path, *docs: tuple[Document, bytes]) -> Store:
    s = Store.create(path)
    for document, raw in docs:
        s.add(document, raw)
    s.commit()
    return Store.open(path)


def in_text_order(chunks: list[StoreChunk]) -> list[StoreChunk]:
    return sorted(chunks, key=lambda c: (c.doc_id, c.char_start))


def leaves(store: Store, doc_id: str):
    return sorted((e for e in store.elements(doc_id) if e.is_leaf), key=lambda e: e.char_start)


@pytest.fixture(scope="module")
def mini_store(tmp_path_factory):
    corpus = load_corpus(MINI / "manifest.json", MINI)
    path = tmp_path_factory.mktemp("mini") / "store"
    s = Store.create(path)
    for doc_id in sorted(corpus.docs):
        p = next(d.path for d in corpus.manifest.documents if d.doc_id == doc_id)
        s.add(corpus.docs[doc_id], (corpus.root / p).read_bytes())
    s.commit()
    return corpus, Store.open(path)


@pytest.fixture(scope="module")
def fixture_store(tmp_path_factory):
    """One document per hand-written fixture (the PDF one is PDF-like text)."""
    path = tmp_path_factory.mktemp("fixtures") / "store"
    return make_store(path, doc(GUIDE, "md"), doc(NESTED, "html"), doc(ECFR, "xml"),
                      doc(PAGES, "pdf", "file://papers/2024_a_study.pdf"))


def stores(mini_store, fixture_store):
    return [mini_store[1], fixture_store]


# --- ranges, ids, order -------------------------------------------------------------------


@pytest.mark.parametrize("max_tokens,min_tokens", [(400, 40), (12, 0), (12, 5), (5, 3)])
def test_every_chunk_reslices_and_has_the_baseline_id(mini_store, fixture_store, max_tokens,
                                                      min_tokens):
    for s in stores(mini_store, fixture_store):
        chunks = chunk_store(s, max_tokens=max_tokens, min_tokens=min_tokens)
        assert chunks
        for c in chunks:
            assert isinstance(c, StoreChunk)
            assert c.text == s.text(c.doc_id)[c.char_start:c.char_end]
            assert c.text == c.text.strip() and c.text
            assert c.chunk_id == make_chunk_id(c.doc_id, c.char_start, c.char_end)
            assert n_tokens(c.text) <= max_tokens
        assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_output_is_sorted_by_chunk_id_like_the_baseline_index(mini_store):
    chunks = chunk_store(mini_store[1])
    assert [c.chunk_id for c in chunks] == sorted(c.chunk_id for c in chunks)
    assert {c.doc_id for c in chunks} == set(mini_store[1].doc_ids())


@pytest.mark.parametrize("max_tokens,min_tokens", [(400, 40), (12, 0), (12, 5), (5, 3)])
def test_chunks_tile_the_leaves_without_overlap(mini_store, fixture_store, max_tokens,
                                                min_tokens):
    """Every non-whitespace character of a leaf is in exactly one chunk, and every chunk
    character is in a leaf or a whitespace gap between two of its leaves."""
    for s in stores(mini_store, fixture_store):
        chunks = chunk_store(s, max_tokens=max_tokens, min_tokens=min_tokens)
        for doc_id in s.doc_ids():
            text = s.text(doc_id)
            mine = in_text_order([c for c in chunks if c.doc_id == doc_id])
            assert all(a.char_end <= b.char_start for a, b in zip(mine, mine[1:], strict=False))
            covered = [0] * len(text)
            for c in mine:
                for i in range(c.char_start, c.char_end):
                    covered[i] += 1
            for leaf in leaves(s, doc_id):
                for i in range(leaf.char_start, leaf.char_end):
                    if not text[i].isspace():
                        assert covered[i] == 1, (doc_id, leaf.type, i)
            assert all(text[i].isspace() for i in range(len(text)) if covered[i] == 0)


@pytest.mark.parametrize("max_tokens", [400, 12, 5])
def test_total_tokens_equal_the_baseline_chunker(mini_store, fixture_store, max_tokens):
    """Neither chunker drops or repeats text, so their token totals agree (no fixture has a
    separator-free run long enough for a mid-token window cut)."""
    for s in stores(mini_store, fixture_store):
        ours = sum(n_tokens(c.text) for c in chunk_store(s, max_tokens=max_tokens))
        base = sum(n_tokens(c.text) for d in s.doc_ids()
                   for c in chunk_document(Document(d, s.text(d), "txt", "1", "u"),
                                           max_tokens=max_tokens))
        assert ours == base


def test_element_ids_are_the_leaves_each_chunk_covers(fixture_store):
    s = fixture_store
    for c in chunk_store(s, max_tokens=12, min_tokens=5):
        want = [e.element_id for e in leaves(s, c.doc_id)
                if e.char_start < c.char_end and c.char_start < e.char_end]
        assert c.element_ids == tuple(want) and want


# --- packing and sections ------------------------------------------------------------------

FIVE = "w1 w2 w3 w4 w5"


def test_leaves_pack_until_the_next_would_exceed_max_tokens(tmp_path):
    raw = ("# H\n\n" + "\n\n".join([FIVE] * 5) + "\n").encode()
    s = make_store(tmp_path / "s", doc(raw, "md"))
    chunks = in_text_order(chunk_store(s, max_tokens=12, min_tokens=0))
    assert [n_tokens(c.text) for c in chunks] == [11, 10, 5]  # heading 1 + 5 + 5, then 5 + 5


def test_a_chunk_never_crosses_a_section_boundary_without_merging(mini_store, fixture_store):
    for s in stores(mini_store, fixture_store):
        for c in chunk_store(s, max_tokens=400, min_tokens=0):
            parents = {e.parent_id for e in leaves(s, c.doc_id) if e.element_id in c.element_ids}
            assert len(parents) == 1, c.breadcrumb


def test_sections_start_new_chunks_and_carry_their_breadcrumb(tmp_path):
    raw = b"# Doc\n\nalpha beta gamma.\n\nDelta epsilon.\n\n## Part\n\nzeta eta.\n"
    s = make_store(tmp_path / "s", doc(raw, "md"))
    chunks = in_text_order(chunk_store(s, min_tokens=0))
    assert [(c.text, c.breadcrumb) for c in chunks] == [
        ("# Doc\n\nalpha beta gamma.\n\nDelta epsilon.", "Doc"),
        ("## Part\n\nzeta eta.", "Doc > Part"),
    ]


def test_tables_code_and_list_items_are_kept_whole_when_they_fit(fixture_store):
    """A leaf is kept whole when it fits together with the headings directly before it that
    travel with it (a heading moves with the start of its body; see the heading tests)."""
    s = fixture_store
    for max_tokens in (400, 12, 8):
        chunks = chunk_store(s, max_tokens=max_tokens, min_tokens=0)
        for doc_id in s.doc_ids():
            text = s.text(doc_id)
            ls = leaves(s, doc_id)
            for k, leaf in enumerate(ls):
                n = n_tokens(text[leaf.char_start:leaf.char_end])
                if leaf.type != "heading":
                    j = k
                    while j > 0 and ls[j - 1].type == "heading":
                        j -= 1
                    n += sum(n_tokens(text[h.char_start:h.char_end]) for h in ls[j:k])
                holders = [c for c in chunks if c.doc_id == doc_id
                           and c.char_start < leaf.char_end and leaf.char_start < c.char_end]
                if n <= max_tokens:
                    assert len(holders) == 1, (leaf.type, max_tokens)
                    c = holders[0]
                    assert c.char_start <= leaf.char_start and leaf.char_end <= c.char_end
    kinds = {e.type for d in s.doc_ids() for e in leaves(s, d)}
    assert {"table", "code", "list_item"} <= kinds


def test_an_oversized_leaf_is_split_like_the_baseline(tmp_path):
    para = " ".join(f"w{i}" for i in range(30)) + ". " + " ".join(f"v{i}" for i in range(30))
    s = make_store(tmp_path / "s", doc(para.encode(), "txt"))
    doc_id = s.doc_ids()[0]
    ours = in_text_order(chunk_store(s, max_tokens=20, min_tokens=0))
    base = chunk_document(Document(doc_id, s.text(doc_id), "txt", "1", "u"), max_tokens=20)
    assert [(c.char_start, c.char_end) for c in ours] == [(c.char_start, c.char_end)
                                                           for c in base]
    assert len(ours) > 2 and all(c.element_ids == ours[0].element_ids for c in ours)


def test_the_pieces_of_an_oversized_leaf_pack_with_its_heading(tmp_path):
    body = " ".join(f"w{i}" for i in range(30))
    s = make_store(tmp_path / "s", doc(f"# Title\n\n{body}\n".encode(), "md"))
    first = in_text_order(chunk_store(s, max_tokens=20, min_tokens=0))[0]
    assert first.text.startswith("# Title\n\nw0 ") and n_tokens(first.text) == 20


# --- short sections ------------------------------------------------------------------------


def chunk_texts(tmp_path, md: str, **kw) -> list[tuple[str, str]]:
    s = make_store(tmp_path / "s", doc(md.encode(), "md"))
    return [(c.text, c.breadcrumb) for c in in_text_order(chunk_store(s, **kw))]


def test_a_short_section_merges_into_the_next_siblings_first_chunk(tmp_path):
    md = ("# Doc\n\nIntro has enough words here.\n\n## Short\n\nTiny.\n\n"
          "## Long\n\nLong section body words.\n\n## Parent\n\n### Child\n\n"
          "Child body text here.\n\n## Last\n\nEnd.\n")
    assert chunk_texts(tmp_path, md, min_tokens=4) == [
        ("# Doc\n\nIntro has enough words here.", "Doc"),
        ("## Short\n\nTiny.\n\n## Long\n\nLong section body words.", "Doc > Long"),
        # a heading with no text of its own goes with its first subsection
        ("## Parent\n\n### Child\n\nChild body text here.", "Doc > Parent > Child"),
        ("## Last\n\nEnd.", "Doc > Last"),  # nothing follows: it stays on its own
    ]


def test_merging_cascades_down_but_not_to_a_section_with_another_parent(tmp_path):
    md = ("# Doc\n\n## A\n\n### A1\n\nBody of a1 enough words.\n\n### A2\n\nTiny.\n\n"
          "## B\n\nBody of b enough words.\n")
    assert chunk_texts(tmp_path, md, min_tokens=4) == [
        ("# Doc\n\n## A\n\n### A1\n\nBody of a1 enough words.", "Doc > A > A1"),
        ("### A2\n\nTiny.", "Doc > A > A2"),
        ("## B\n\nBody of b enough words.", "Doc > B"),
    ]


def test_a_merged_group_stops_once_it_reaches_min_tokens(tmp_path):
    md = ("# Doc\n\nIntro has enough words here.\n\n## S1\n\nOne.\n\n## S2\n\nTwo.\n\n"
          "## S3\n\nBody three enough words.\n")
    assert chunk_texts(tmp_path, md, min_tokens=4) == [
        ("# Doc\n\nIntro has enough words here.", "Doc"),
        ("## S1\n\nOne.\n\n## S2\n\nTwo.", "Doc > S2"),
        ("## S3\n\nBody three enough words.", "Doc > S3"),
    ]


def test_a_short_preamble_merges_into_the_first_section(tmp_path):
    md = "Preamble.\n\n# Doc\n\nIntro has enough words here.\n"
    assert chunk_texts(tmp_path, md, min_tokens=4) == [(md.strip(), "Doc")]
    assert len(chunk_texts(tmp_path, md, min_tokens=0)) == 2


def W(k: int, p: str = "w") -> str:
    return " ".join(f"{p}{i}" for i in range(k))


def test_a_heading_moves_to_the_next_chunk_with_its_body(tmp_path):
    """Review repro: `## S` (3 tokens with its body) carried into sibling `## L` whose body has
    18 tokens, at max 20: no chunk may end on "## L"."""
    md = f"# D\n\n{W(8, 'i')}.\n\n## S\n\ns1 s2\n\n## L\n\n{W(18, 'l')}\n"
    texts = [t for t, _ in chunk_texts(tmp_path, md, max_tokens=20, min_tokens=6)]
    assert not any(t.endswith("## L") for t in texts)
    assert texts == [f"# D\n\n{W(8, 'i')}.", "## S\n\ns1 s2", f"## L\n\n{W(18, 'l')}"]


def test_a_heading_whose_body_does_not_fit_takes_the_start_of_it(tmp_path):
    """Heading plus first unit over max: the unit is cut at max minus the heading's tokens."""
    md = f"# D\n\n{W(8, 'i')}.\n\n## L\n\n{W(25, 'l')}\n"
    chunks = chunk_texts(tmp_path, md, max_tokens=12, min_tokens=0)
    texts = [t for t, _ in chunks]
    assert texts[1] == f"## L\n\n{W(11, 'l')}"
    assert all(n_tokens(t) <= 12 for t in texts) and not any(t.endswith("## L") for t in texts)
    assert " ".join(texts[2:]) == " ".join(f"l{i}" for i in range(11, 25))


def test_a_chain_of_headings_travels_with_the_first_body(tmp_path):
    """`## S` is carried into `## A`; `## A` and `### A1` go with A1's body, not with S."""
    md = f"# D\n\n{W(5, 'i')}\n\n## S\n\ns1\n\n## A\n\n### A1\n\n{W(5, 'a')}\n"
    texts = [t for t, _ in chunk_texts(tmp_path, md, max_tokens=8, min_tokens=3)]
    assert texts == [f"# D\n\n{W(5, 'i')}", "## S\n\ns1", f"## A\n\n### A1\n\n{W(5, 'a')}"]


def test_a_heading_only_section_reaching_min_tokens_keeps_its_first_subsection(tmp_path):
    """Review repro: `## S1` (5 tokens with its body), `## S2`, `### S2a body` at min 6 must not
    give a chunk ending "## S2"."""
    md = (f"# D\n\n{W(8, 'i')}\n\n## S1\n\na1 a2 a3 a4\n\n## S2\n\n### S2a\n\n{W(8, 'z')}\n\n"
          f"## T\n\n{W(8, 't')}\n")
    chunks = chunk_texts(tmp_path, md, min_tokens=6)
    assert not any(t.endswith("## S2") for t, _ in chunks)
    assert chunks[1] == (f"## S1\n\na1 a2 a3 a4\n\n## S2\n\n### S2a\n\n{W(8, 'z')}",
                         "D > S2 > S2a")
    assert chunks[2] == (f"## T\n\n{W(8, 't')}", "D > T")


@pytest.mark.parametrize("max_tokens,min_tokens", [(400, 40), (12, 5), (8, 4), (5, 3)])
def test_no_chunk_ends_on_a_heading_whose_section_continues_in_the_next(mini_store, fixture_store,
                                                                       max_tokens, min_tokens):
    for s in stores(mini_store, fixture_store):
        chunks = chunk_store(s, max_tokens=max_tokens, min_tokens=min_tokens)
        for doc_id in s.doc_ids():
            els = {e.element_id: e for e in s.elements(doc_id)}
            mine = in_text_order([c for c in chunks if c.doc_id == doc_id])
            for c, nxt in zip(mine, mine[1:], strict=False):
                last = els[c.element_ids[-1]]
                if last.type != "heading":
                    continue
                up = els[nxt.element_ids[0]].parent_id
                while up is not None and up != last.parent_id:
                    up = els[up].parent_id
                # allowed only when the headings around the cut leave no room for any body
                text = s.text(doc_id)
                heads = 0
                for ids in (reversed(c.element_ids), nxt.element_ids):
                    for i in ids:
                        if els[i].type != "heading":
                            break
                        heads += n_tokens(text[els[i].char_start:els[i].char_end])
                assert up is None or heads >= max_tokens, (c.text, nxt.text)


def test_store_chunks_are_hashable(mini_store):
    chunks = chunk_store(mini_store[1])
    assert len(set(chunks)) == len(chunks) and isinstance(chunks[0].element_ids, tuple)


def _within(section_id, container, els) -> bool:
    while section_id is not None and section_id != container:
        section_id = els[section_id].parent_id
    return container is None or section_id == container


@pytest.mark.parametrize("max_tokens,min_tokens", [(400, 40), (12, 5), (8, 4)])
def test_a_chunk_spans_sections_only_to_carry_short_ones_forward(mini_store, fixture_store,
                                                                 max_tokens, min_tokens):
    """Leaves of other sections come before the last section's leaves, total fewer than
    `min_tokens`, and stay inside the parent of the first one's section; the breadcrumb is
    the last section's."""
    merged = 0
    for s in stores(mini_store, fixture_store):
        for c in chunk_store(s, max_tokens=max_tokens, min_tokens=min_tokens):
            els = {e.element_id: e for e in s.elements(c.doc_id)}
            text = s.text(c.doc_id)
            covered = [els[i] for i in c.element_ids]
            last = covered[-1].parent_id
            before = [e for e in covered if e.parent_id != last]
            assert all(e.parent_id == last for e in covered[len(before):])
            # headings of the sections that enclose the last one do not count: a group that
            # reaches min_tokens on a heading-only section takes its first subsection too
            carried = list(before)
            while carried and carried[-1].type == "heading" and _within(
                    last, carried[-1].parent_id, els):
                carried.pop()
            assert sum(n_tokens(text[e.char_start:e.char_end]) for e in carried) < min_tokens
            first = covered[0].parent_id
            container = els[first].parent_id if first else None
            assert all(_within(e.parent_id, container, els) for e in covered)
            title = document_title(s.source(c.doc_id), list(els.values()), text)
            path = covered[-1].section_path
            assert c.breadcrumb in (breadcrumb(title, path), breadcrumb(None, path))
            merged += bool(before)
    assert merged


# --- breadcrumbs ---------------------------------------------------------------------------


def test_breadcrumb_is_the_title_then_the_section_path_without_repeating_the_title(
        fixture_store):
    s = fixture_store
    guide = next(d for d in s.doc_ids() if s.source(d).format == "md")
    crumbs = {c.text.split("\n")[0]: c.breadcrumb
              for c in chunk_store(s, min_tokens=0) if c.doc_id == guide}
    assert crumbs == {
        "Preamble line before any heading.": "Field Guide",
        "# Field Guide": "Field Guide",
        "## Steps": "Field Guide > Steps",
        "### Detail ###": "Field Guide > Steps > Detail",
        "## Notes": "Field Guide > Notes",
    }


def test_document_title_rules(tmp_path):
    record = json.dumps({"title": "  Rule on\nFM allotments ", "abstract": "Text."}).encode()
    untitled = json.dumps({"abstract": "Other text."}).encode()
    s = make_store(
        tmp_path / "s",
        doc(record, "json", "https://x.org/api/documents/2026-1.json?fields=a"),
        doc(untitled, "json", "https://x.org/api/documents/2026-2.json?fields=a#frag"),
        doc(b"Plain text.\n", "txt", "file://papers/a%20b.txt"),
        doc(GUIDE, "md"),
    )
    titles = {s.source(d).uri: document_title(s.source(d), s.elements(d), s.text(d))
              for d in s.doc_ids()}
    assert titles == {
        "https://x.org/api/documents/2026-1.json?fields=a": "Rule on FM allotments",
        "https://x.org/api/documents/2026-2.json?fields=a#frag": "2026-2.json",
        "file://papers/a%20b.txt": "a b.txt",
        "file://doc.md": "Field Guide",
    }
    crumbs = {s.source(c.doc_id).uri: c.breadcrumb for c in chunk_store(s)}
    assert crumbs["https://x.org/api/documents/2026-1.json?fields=a"] == "Rule on FM allotments"


def test_heuristic_pdf_sections_do_not_give_the_title(fixture_store):
    """A PDF's first heuristic section is a heading such as "Abstract", not its title; the
    file name is used instead. Sections from markup (XML, HTML) give the title."""
    s = fixture_store
    titles = {s.source(d).format: document_title(s.source(d), s.elements(d), s.text(d))
              for d in s.doc_ids()}
    pdf = next(d for d in s.doc_ids() if s.source(d).format == "pdf")
    assert any(e.type == "section" and e.parent_id is None for e in s.elements(pdf))
    assert titles == {"pdf": "2024_a_study.pdf", "xml": "PART 99—TEST RULES",
                      "html": "Permit Handbook", "md": "Field Guide"}


def test_breadcrumb_parts_are_cut_at_a_word_boundary_to_80_characters(tmp_path):
    long_title = "T" * 50 + " " + "U" * 60
    raw = f"# {long_title}\n\nBody.\n\n## {'S' * 100}\n\nMore body.\n".encode()
    s = make_store(tmp_path / "s", doc(raw, "md"))
    crumbs = sorted(c.breadcrumb for c in chunk_store(s, min_tokens=0))
    title = "T" * 50 + "…"
    assert crumbs == [title, title + " > " + "S" * 79 + "…"]  # no space: a hard cut
    words = "alpha beta gamma delta " * 5  # 115 characters
    assert breadcrumb(words, []) == "alpha beta gamma delta alpha beta gamma delta alpha beta " \
                                    "gamma delta alpha beta…"
    assert all(len(p) <= 80 for p in breadcrumb(words, [words, "x" * 81]).split(" > "))
    assert breadcrumb("x" * 80, []) == "x" * 80  # 80 characters are not cut


def test_a_chunk_in_another_top_level_section_gets_no_title_prefix(tmp_path):
    """The title comes from the first top-level section; its siblings are not inside it."""
    md = ("Preamble words here.\n\n# First\n\nBody one.\n\n## Sub\n\nBody sub.\n\n"
          "# Second\n\nBody two.\n\n## Deeper\n\nBody deeper.\n")
    assert [b for _, b in chunk_texts(tmp_path, md, min_tokens=0)] == [
        "First", "First", "First > Sub", "Second", "Second > Deeper"]
    titled = "Body.\n"  # no sections: the title (here the URI) heads every chunk
    assert [b for _, b in chunk_texts(tmp_path / "t", titled, min_tokens=0)] == ["file://doc.md"]


# --- determinism ---------------------------------------------------------------------------


def test_chunking_is_deterministic(mini_store, fixture_store):
    for s in stores(mini_store, fixture_store):
        assert chunk_store(s) == chunk_store(s)


def test_ids_are_stable_under_an_unrelated_edit_elsewhere(tmp_path):
    other = b"# Other\n\nSome other text.\n"
    edited = b"# Other\n\nSome other text, edited.\n\nAnd a new paragraph.\n"
    a = make_store(tmp_path / "a", doc(GUIDE, "md"), doc(other, "md", "file://other.md"))
    b = make_store(tmp_path / "b", doc(GUIDE, "md"), doc(edited, "md", "file://other.md"))
    guide_id = hashlib.sha256(GUIDE).hexdigest()
    in_a = [c for c in chunk_store(a) if c.doc_id == guide_id]
    in_b = [c for c in chunk_store(b) if c.doc_id == guide_id]
    assert in_a == in_b and in_a
