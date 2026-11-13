# Phase 1: Evidence Store — Implementation Plan

Spec: `docs/superpowers/specs/2026-11-13-phase1-evidence-store-design.md`. Read it first; section
numbers below refer to it. Work test-first. `pytest -q -W error` and `ruff check .` must pass
after every task. No model calls except where Task 5 says so. Do not edit golden item files,
`results/v1` or `results/v2`.

Shared rules for every task:

- New toolkit code goes in `src/adr_store/`; harness code stays in `src/adr_eval/`. `adr_store`
  may import the harness's text extraction, tokenizer and corpus loading; the harness imports
  `adr_store` only through the system registry (Task 3).
- The canonical text of a document is exactly what `adr_eval.corpora.base.load_corpus` returns
  as `Document.text` (spec §3). Never change it.
- Everything is deterministic: sorted iteration, no wall-clock or random input in any record,
  id or fingerprint.

## Task 1: Record format, structure parsers, store

**Files:** `src/adr_store/__init__.py`, `records.py`, `conformance.py`, `store.py`,
`structure/__init__.py`, `structure/{markdown,xml,html,pdf,records,text}.py`,
`schema/*.json` (generated), `cli.py` (`adr ingest` only), `pyproject.toml` (package list and
the `adr` script); tests `tests/store/test_records.py`, `test_conformance.py`,
`test_structure_*.py`, `test_store.py`.

- Pydantic models for the source and element records (spec §4.1, §4.2) and a function that
  writes their JSON Schema to `src/adr_store/schema/`; a test fails if the committed schema
  files are stale.
- `conformance.check(source, elements, text, raw) -> list[str]` implementing rules 1 to 4 of
  spec §4.3; rule 5 is a test.
- Parsers per spec §6, each `parse(raw: bytes, text: str, doc_id: str) -> list[Element]`, plus a
  dispatcher by format. Alignment searches forward from the previous heading's end; a heading
  that does not align is dropped and counted in the returned stats.
- `Store` per spec §5: `Store.create(path)`, `add(document, raw, license=None)`,
  `commit() -> snapshot_id`, `Store.open(path, snapshot=None)`, `source(doc_id)`,
  `elements(doc_id)`, `text(doc_id)`, `doc_ids()`. Atomic writes; existing files with the same id
  are untouched.
- `adr ingest <corpus> --store <dir>` ingests a pinned corpus (through
  `runner.load_checked_corpus`), fails with a clear message on any conformance violation, and
  prints the compile figures of spec §10.3 (also written to `<store>/compile/<snapshot>.json`).
- Tests: spec §12 first two bullets, on the mini fixture and on small hand-written fixtures per
  format (including a heading that cannot be aligned, a PDF-like text with form feeds, and an
  HTML page with nested headings).
- Real-data check (report the figures): ingest gov, research and bench into
  `.cache/store/<corpus>`; all documents must conform.

## Task 2: Structure-led chunks and the embedding cache

**Files:** `src/adr_store/chunking.py`, `src/adr_store/embedding.py`; tests
`tests/store/test_chunking.py`, `test_embedding.py`.

- `chunk_store(store, max_tokens=400, min_tokens=40) -> list[StoreChunk]` per spec §7, where
  `StoreChunk` has the baseline `Chunk` fields plus `breadcrumb` and `element_ids`.
- An embedding cache keyed by SHA-256 of the embedded text and the model hash, stored under the
  cache directory; `embed_texts(texts) -> (vectors, n_new)` reports how many were computed.
- Tests: spec §12 third bullet. Also: every chunk's range re-slices to its text; chunks tile
  each section's leaves; total tokens equal the baseline chunker's within the split rule.
- Real-data check: chunk counts and mean tokens per corpus beside the baseline's; span
  containment of golden evidence in one chunk for both chunkers.

## Task 3: Retrieval systems and harness integration

**Files:** `src/adr_store/retrieval/{__init__,lexical,dense,rerank,index}.py`,
`src/adr_eval/systems.py` (registry), `src/adr_eval/runner.py`, `src/adr_eval/cli.py`,
`src/adr_eval/report.py` (only what the new command needs); tests
`tests/store/test_retrieval.py`, `tests/test_systems.py`.

- `StoreIndex` per spec §8 with settings `w_bc`, `prefix`, `rerank`; fingerprint, save and load;
  tuning of `w_bc` and the fusion weight on dev.
- The system registry maps a name to a builder returning an object with
  `retrieve(question) -> list[(chunk_id, score)]` and `chunks`. `baseline-rrf` and
  `baseline-linear` move behind it unchanged (their recorded results must reproduce exactly).
  The three Phase 1 systems of spec §8.1 are registered.
- `adr-eval retrieval <corpus> --system <name> --split <dev|test>`: retrieval track only, no
  model client is created; writes `runs/<run_id>/retrieval.json` and `.md`; `--compare` between
  two retrieval runs gives paired differences with Holm-corrected p-values.
- Tests: spec §12 fourth bullet; a regression test that `baseline-linear` through the registry
  returns the same ranked lists as before on the mini fixture.

## Task 4: Tools

**Files:** `src/adr_store/tools.py`, `src/adr_store/cli.py`; tests `tests/store/test_tools.py`.

- `adr index`, `adr search`, `adr read`, `adr grep` and the retrieval log per spec §9.
- Tests: spec §12 fifth bullet.

## Task 5: Measure and report

- Build the three Phase 1 indexes for gov, research and bench (embedding is slow on CPU: run in
  the background, single-threaded unless Task 2 showed threads give identical vectors).
- Retrieval-only runs for all four systems on dev and test; pick the best Phase 1 system by the
  acceptance rule of spec §10.5.
- One end-to-end run (test split, one repeat) for that system and a paired comparison with
  `baseline-linear` under metrics version 2. This is the only step that calls a model.
- The exit-criteria checks of spec §10.4: the edit test and the 100-PDF timing.
- Write `results/phase1/README.md` with the tables, what each component added, the exit
  criteria and the limits; update the README and the status page.

## Review

Each task gets an independent review against the spec before the next starts. After Task 5 a
reviewer checks every number in `results/phase1/README.md` against the run files.
