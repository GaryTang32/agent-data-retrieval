# Phase 1: Evidence Store and Structure-Led Retrieval — Design

Date: 2026-11-13
Status: written by the assistant on the user's instruction to carry Phase 1 through without
stopping for approval at each stage. Every choice below that the user did not make is listed in
section 11 as a ruling, with what it costs if it is wrong.
Sources: `reports/Agent data retrieval research summary.md` (the three stores, the Phase 1 row of
the roadmap, "Consolidated design defaults", "Defaults to avoid"); `results/README.md` (the
version 2 baseline).

## 1. Purpose

Phase 1 builds the first part of the toolkit itself: Store 1, the raw evidence store, and the
search path over it. It serves goal G1 (turn raw documents into data products that help search)
and goal G3 (retrieve the best related result deterministically). Success is measured with the
Phase 0 harness against the version 2 baseline, on the same three corpora and golden sets.

A component is kept only if it beats the baseline on its track without breaking determinism.
Components are therefore built as separate, switchable steps and measured one at a time.

## 2. Scope

In scope:

1. A record format (v0.1) for sources and document elements, with conformance tests.
2. A content-addressed, immutable store on disk, with snapshots.
3. Structure parsing for the formats in the three corpora, as an overlay on the canonical text.
4. Structure-led chunks with a breadcrumb.
5. Retrieval over those chunks: field-weighted BM25, dense search with the breadcrumb as a
   prefix, tuned linear fusion, and an optional reranker.
6. Tools: `search`, `read` and `grep` from a command line, with a retrieval log.
7. Incremental updates: an edit re-embeds only the chunks that changed.
8. Harness support for more than two systems, and a retrieval-only evaluation that makes no
   model calls.

Out of scope, with the reason:

| Item from the roadmap's Phase 1 row | Why it is left out here |
|---|---|
| Per-page parse router with three or more backends; bounding boxes | Needs layout models or a GPU. This phase keeps the Phase 0 text extraction and records page and character span only |
| An MCP server | The command-line tools define the behaviour first; an MCP wrapper is thin and comes with Phase 2's snapshot handles |
| Approximate nearest-neighbour search | The corpora are small enough for exact search, which is deterministic |
| Permissions, validity filters, typed tables, knowledge units | Phases 2 to 4 |

## 3. Constraint: the canonical text does not change

Golden set v0.1 stores evidence as character offsets into the text that `adr_eval.corpora.extract`
produces (extractor version 2). Phase 1 keeps that text byte for byte as each document's
**canonical text**. Structure is an overlay: elements are character ranges over the canonical
text. This keeps every golden span valid and makes Phase 1 comparable with the baseline.

## 4. Record format v0.1

Package `src/adr_store/` (new; the harness stays in `src/adr_eval/`). Records are plain JSON,
validated by Pydantic models; `adr_store/schema/` holds the generated JSON Schema files.

### 4.1 Source record

| Field | Type | Meaning |
|---|---|---|
| `doc_id` | string | SHA-256 of the raw bytes, lower-case hex |
| `uri` | string | Where the bytes came from |
| `format` | string | `md`, `txt`, `html`, `xml`, `pdf`, `json`, `csv` |
| `source_version` | string | The source's own version label (a date for dated regulations) |
| `byte_length` | integer | Length of the raw bytes |
| `text_sha256` | string | SHA-256 of the canonical text (UTF-8) |
| `text_length` | integer | Length of the canonical text in characters |
| `extractor` | string | Name and version of the text extractor, for example `adr_eval.extract/2` |
| `parser` | string | Name and version of the structure parser, for example `adr_store.structure/1` |
| `license` | string or null | Licence label where the corpus manifest gives one |

### 4.2 Element record

| Field | Type | Meaning |
|---|---|---|
| `element_id` | string | SHA-256 of `doc_id`, `type`, `char_start`, `char_end` joined by newlines |
| `doc_id` | string | The source it belongs to |
| `type` | string | `section`, `heading`, `paragraph`, `list_item`, `table`, `code`, `record` |
| `char_start`, `char_end` | integer | Range in the canonical text, end exclusive |
| `parent_id` | string or null | The enclosing `section` (null at the top) |
| `order` | integer | Position among all elements of the document, by `(char_start, -char_end)` |
| `level` | integer or null | Heading depth for `section` and `heading`, 1 at the top |
| `title` | string or null | For a `section`: its heading text |
| `section_path` | list of strings | Titles of the enclosing sections, outermost first |
| `page` | integer or null | For PDF text, the 1-based page on which the element starts; null elsewhere |
| `confidence` | number | 1.0 when the structure comes from markup; lower for heuristics |
| `text_sha256` | string | SHA-256 of the element's slice of the canonical text |

`section` elements are containers. The others are **leaves**. Pages are an attribute, not a container, because a section can run across pages.

### 4.3 Conformance rules (tested for every document)

1. **Lossless.** The leaves, ordered by `char_start`, do not overlap, and with the gaps between
   them they tile the canonical text: joining leaf slices and gap slices in order reproduces the
   canonical text exactly. A gap contains only whitespace.
2. **Re-slice.** For every element, the SHA-256 of `text[char_start:char_end]` equals
   `text_sha256`.
3. **Nesting.** A section contains its children's ranges; siblings do not overlap; every
   `parent_id` exists; `section_path` equals the titles of the ancestors.
4. **Identity.** `doc_id` is the SHA-256 of the stored bytes; `element_id` follows 4.2; ids are
   unique within a snapshot.
5. **Determinism.** Parsing the same bytes twice gives identical records.

## 5. Store layout

A store is a directory:

```
<store>/blobs/<doc_id[:2]>/<doc_id>            raw bytes, never rewritten
<store>/text/<doc_id[:2]>/<doc_id>.txt         canonical text
<store>/docs/<doc_id[:2]>/<doc_id>.json        source record + element records
<store>/snapshots/<snapshot_id>.json           sorted doc_ids, per-document record hash, parser and extractor versions
<store>/HEAD                                   the current snapshot id
```

- A snapshot id is the SHA-256 of its canonical JSON. A snapshot is immutable; ingesting or
  removing documents writes a new snapshot and moves `HEAD`. A snapshot of loose files
  (`adr ingest --path`) also holds `paths`, each file's relative path (POSIX separators) to its
  `doc_id`, so the folder's layout is part of its id; corpus snapshots have no `paths`.
- Writes are atomic (temporary file, then rename). An existing blob or document file with the
  same id is left untouched; for loose files this includes a document file whose `uri` names
  an earlier path of the same bytes (the current path is in the snapshot's `paths`, and
  `adr read --json` shows it as `path`).
- `adr_store.Store.open(path, snapshot=None)` reads one snapshot. Every result a tool returns
  names the snapshot it came from.

## 6. Structure parsing

`adr_store/structure/` has one parser per format. Each takes the raw bytes and the canonical
text and returns elements. A parser reads the source's own markup to find headings and blocks,
then **aligns** them to the canonical text by searching forward for each heading's text; it never
changes the canonical text.

| Format | Sections from | Leaves | Confidence |
|---|---|---|---|
| `md` | `#` headings | paragraphs, list items, tables, fenced code | 1.0 |
| `xml` (eCFR) | the division hierarchy and its `HEAD` elements (part, subpart, section) | paragraphs | 1.0 |
| `html` | `h1` to `h6` | paragraphs, list items, tables | 1.0 where a heading aligns; the document falls back to paragraphs where none does |
| `pdf` | numbered headings ("3.2 Title") and short title-like lines give sections; form-feed page breaks give each leaf its `page` and always end a paragraph | paragraphs | 0.6 for heuristic sections |
| `json` | none | one `record` per document | 1.0 |
| `csv` | none | one `record` per row; the header row is its own record | 1.0 |
| `txt` | none | paragraphs | 1.0 |

A heading that cannot be aligned is dropped and counted; the document still conforms because
paragraphs alone tile the text. The compile report gives, per corpus and format, the share of
documents with at least one section and the share of headings aligned.

## 7. Chunks

`adr_store/chunking.py`, deterministic, no model calls:

- A chunk is a run of consecutive leaves inside one section (the innermost section that
  contains them). Leaves are packed until the next one would exceed `max_tokens` (400, the
  baseline's size, counted the same way). A chunk never crosses a section boundary.
- A leaf longer than `max_tokens` is split with the baseline's recursive splitter. Tables, code
  blocks and list items are kept whole when they fit.
- A section whose leaves total fewer than `min_tokens` (40) is merged with the following sibling
  section's first chunk when both share a parent, so headings do not become one-line chunks.
- Each chunk carries `breadcrumb`: the document title (first top-level section title, or the
  file name) followed by its `section_path`, joined with " > ".
- `chunk_id` is the SHA-256 of `doc_id`, `char_start`, `char_end`, as in the baseline.
- No overlap.

## 8. Retrieval

`adr_store/retrieval/`:

- **Lexical.** BM25 with field weighting: the indexed tokens of a chunk are its body tokens plus
  its breadcrumb tokens repeated `w_bc` times (`w_bc` in {0, 1, 2, 3}, tuned on dev). This is
  BM25F with one shared length normalisation. Same tokenizer, `k1` and `b` as the baseline.
- **Dense.** The same embedding model as the baseline. The embedded text is the breadcrumb, a
  newline, then the chunk body (the "breadcrumb prefix"), or the body alone when the prefix is
  switched off. Exact cosine search.
- **Fusion.** Linear, weight tuned on the dev split against nDCG@10 (version 2), as in the
  baseline.
- **Reranker (optional).** A small cross-encoder run on CPU over the top 50 fused candidates.
  It is kept only if it beats the same system without it on the dev split.
- **Determinism.** Scores rounded to six decimals, ties broken by `chunk_id`, single-threaded
  scoring, an index fingerprint that covers the snapshot id, chunker settings, field weights,
  model hashes and chunk ids.
- **Embedding cache.** Vectors are cached by the SHA-256 of the embedded text and the model
  hash. Re-indexing after an edit embeds only chunks whose embedded text is new.

### 8.1 Systems measured

Each adds one component to the one before it, so each component's effect is visible:

| System | Chunks | Lexical | Dense | Reranker |
|---|---|---|---|---|
| `baseline-linear` | fixed 400 tokens | BM25 | body | no |
| `p1-struct` | structure-led | BM25 | body | no |
| `p1-struct-bc` | structure-led | BM25 with breadcrumb field | breadcrumb prefix | no |
| `p1-struct-bc-rr` | structure-led | as above | as above | yes |

## 9. Tools

A console script `adr` over one store and one index:

- `adr ingest <corpus>`: read a pinned corpus into a store (bytes, canonical text, elements),
  write a snapshot. `adr ingest --path <dir>` ingests loose files: recursive, hidden names
  skipped, symlinks not followed (counted), a store inside the folder not read; every file is
  read and extracted before the first write, and any failure is reported and writes nothing.
- `adr index <store> --system <name>`: build or load the index for a snapshot.
- `adr search <query> [--top 10]`: ranked chunks with `chunk_id`, `doc_id`, character range,
  breadcrumb, score and the snapshot id.
- `adr read <doc_id> [--start N --end M | --element ID]`: the exact text of a range.
- `adr grep <pattern> [--doc ID]`: regular-expression matches with their ranges, in a fixed
  order (`doc_id`, then offset), capped by `--max`.
- Every call appends one line to `<store>/log/retrieval.jsonl`: time, tool, arguments, snapshot
  id, result ids. Output is JSON with `--json`, otherwise a short table.

## 10. Measurement

1. **Harness.** `adr-eval` gets a system registry so a run can name any system in 8.1, and a new
   command `adr-eval retrieval <corpus> --system <name> --split <dev|test>` that computes the
   retrieval track (Recall@10, nDCG@10, MRR, coverage@10, tokens@10, with intervals) and writes
   a report without calling a model.
2. **Order of work.** Retrieval-only results for every system on dev (to tune) and on test, on
   all three corpora. Then one end-to-end run (answers and judge) on the test split for the best
   Phase 1 system and a paired comparison with `baseline-linear`.
3. **Compile track.** Per corpus: conformance pass rate, share of leaves with a character span
   (must be 100%) and with a page (PDF only), share of documents with sections, heading
   alignment rate, span containment of golden evidence in one chunk.
4. **Exit criteria of the roadmap, as measured here.**

| Criterion | How it is checked | Expected status |
|---|---|---|
| Lossless round trip on a mixed corpus of at least 1,000 documents | Conformance rule 1 on all three corpora (about 2,400 documents) | Measured |
| At least 95% of born-digital elements carry page, bounding box and character span | Character span on all leaves; page on PDF leaves; no bounding boxes | Partly met; boxes need a layout parser |
| A 1% edit re-embeds at most 2% of chunks | Edit 1% of the documents of each corpus (insert a paragraph mid-document), re-index, count new embeddings | Measured |
| Install to 100 queryable PDFs in under ten minutes | Time `adr ingest` and `adr index` on 100 research PDFs on this machine | Measured |
| Routed parse within two points of the best backend | Not measurable without layout models | Deferred |
| Approximate search recall against exact search | Exact search is used | Not applicable |

5. **Acceptance.** A Phase 1 system replaces the baseline as the reference only if, on the test
   split, its nDCG@10 and Recall@10 are not lower than `baseline-linear` on any corpus and are
   significantly higher (paired bootstrap, Holm-corrected) on at least one, with retrieval
   identity intact. Otherwise the write-up says which component failed and it is switched off.

## 11. Rulings made without the user

| # | Ruling | Why | Cost if wrong |
|---|---|---|---|
| 1 | Keep the Phase 0 canonical text; structure is an overlay | Keeps golden v0.1 valid and Phase 1 comparable | Structure quality is limited by what can be aligned to the existing text |
| 2 | Files on disk (JSON), no database engine | The typed database is Phase 3; files are inspectable and deterministic | Slower listing at large scale; a later migration |
| 3 | Leave out the parse router, bounding boxes and the MCP server | No GPU or layout models here; the CLI fixes behaviour first | Two roadmap exit criteria stay open |
| 4 | Field weighting by repeating breadcrumb tokens | Simple, deterministic, uses the existing BM25 library | Not full BM25F with per-field length normalisation |
| 5 | One embedding model, the baseline's | Isolates the effect of chunks and breadcrumbs | A better model might change the picture |
| 6 | End-to-end answers only for the best Phase 1 system | Each end-to-end run costs about 3,000 subscription calls | The other systems have retrieval figures only |
| 7 | PDF sections by heuristics, confidence 0.6 | No layout model; numbered headings are common in the research PDFs | Wrong section boundaries on some PDFs |
| 8 | New package `adr_store` in the same distribution | One install, one CI; split later if needed | A later rename |

## 12. Testing

- Conformance rules 1 to 5 as property tests on the mini fixture for every format, and as a
  corpus-level check (`adr ingest` fails on any violation).
- Parsers: one fixture per format with known headings; alignment failures are counted, not
  hidden.
- Chunker: never crosses a section; atomic leaves; breadcrumb content; determinism; ids stable
  under an unrelated edit elsewhere in the document set.
- Retrieval: field weight 0 equals plain BM25 on the same chunks; fingerprint changes when any
  input changes; save and load give identical ranked lists; the reranker is a pure function of
  its inputs.
- Tools: output shape, ordering, snapshot id on every result, one log line per call.
- Incremental: the edit test of section 10.
