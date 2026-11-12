# Phase 0: Golden Set and Evaluation Harness — Design

Status: draft for review · Date: 2026-11-08 · Repo: `garytang32/agent-data-retrieval`
Source of requirements: `reports/Agent data retrieval research summary.md` (roadmap Phase 0), `reports/agent-data-retrieval-brief.html` (Part 3), and the design conversation of 2026-11-08.

## 1. Purpose and context

### 1.1 The repository objective

One toolkit that compiles raw documents and tools of any form into versioned data products (raw evidence with hashes and spans, typed tables and typed relations, searchable knowledge units, tool records), turns each user question into the matching structured form, and retrieves deterministically from a pinned snapshot, with quality measured separately for rare, domain-specific knowledge.

This is stated as three goals:

| Goal | Meaning |
|---|---|
| G1 Compile | From raw documents in any form, produce data products that benefit subsequent search: a data lake, typed tables, relations, hashes and spans. |
| G2 Query understanding | From user input, produce the structured form that best matches the G1 data products. |
| G3 Retrieval | Deterministically retrieve the best related results from the data products, especially for domain-specific and rare knowledge. |

"Perfectly deterministic" is interpreted as: identical question + identical snapshot ⇒ identical results, guaranteed by construction and tested. "Best related result" cannot be proven, only measured; Phase 0 measures it.

### 1.2 What Phase 0 is

Phase 0 builds the yardstick before any toolkit code. It produces a golden set over three corpora, an evaluation harness with five tracks, and a recorded flat hybrid baseline. Every later phase is accepted only if it improves its track over this baseline without breaking determinism.

### 1.3 Decisions taken in the design conversation

| Decision | Choice |
|---|---|
| Corpora | All three: public US government corpus, the repo's research corpus, an open benchmark subset |
| Generator model | Claude family, pinned model ID in config |
| Judge model | Claude family for now, behind a pluggable interface with an adapter for any OpenAI-compatible endpoint (for the user's future self-hosted model) |
| Golden-set vetting | Automatic only for now: LLM-drafted, code-verified; no human review yet |
| Architecture | Standalone Python package in this repo (not Ragas/promptfoo/Inspect) |
| Embeddings | Small open model run locally on CPU |

Consequences recorded as open items: the judge shares a family with the generator (flagged on every report), and judge-vs-human κ cannot be measured until a human labels a sample.

### 1.4 Out of scope for Phase 0

Structure-led chunking, typed stores, knowledge units, query compilation beyond a zero-shot baseline, graph layers, permissions, MCP server, human review UI. These belong to Phases 1–6 and will be measured by this harness.

## 2. Evaluation tracks

| Track | Measures | Phase 0 baseline measurement |
|---|---|---|
| G1 Compile | Fidelity of raw → data products | Span containment (share of gold evidence spans fully inside one chunk); extracted-text fidelity against source characters where checkable; rebuild determinism (identical index fingerprint across two builds) |
| G2 Query understanding | User input → structured query | Zero-shot Claude conversion to `gold_query`; per-field accuracy, whole-query exact match, execution match where executable |
| G3 Retrieval | Best related results | Recall@10, nDCG@10, MRR, full-evidence coverage; stratified by rarity and question type |
| Determinism | Same input + snapshot ⇒ same output | Retrieval ranked-list identity over 5 repeats (must be 100%); LLM answer agreement and pass^5 |
| End-to-end | Final answers | Correct / wrong / abstained; abstention-penalised score; citation faithfulness; tokens, latency, dollars |

## 3. Package layout

```
pyproject.toml                    # Apache-2.0, Python ≥3.11, console script adr-eval
src/adr_eval/
  corpora/        # one adapter per corpus: fetch, pin, normalize to Document records
  golden/         # item schema, generators per question type, verifiers
  retrieval/      # chunker, BM25, dense, fusion, index fingerprint
  answer/         # model adapters (Anthropic, OpenAI-compatible, stub), answering prompt
  scoring/        # exact scorers, judge, abstention-aware metrics, retrieval metrics, stats
  cache.py        # content-addressed cache for all model calls
  runner.py       # executes a system over a split with repeats
  report.py       # markdown + JSON reports, comparisons
  cli.py
corpora/<corpus>/manifest.json    # committed
golden/<corpus>/v0.1/items.jsonl  # committed
golden/<corpus>/v0.1/rejected.jsonl
results/                          # committed baseline summaries + configs
tests/                            # unit tests + tiny fixture corpus
data/   runs/   .cache/           # git-ignored
.github/workflows/ci.yml          # pytest + ruff
```

Dependencies (all permissive): `bm25s` (MIT), `fastembed` (Apache-2.0, ONNX, no PyTorch) with `BAAI/bge-small-en-v1.5`, `numpy`, `pydantic`, `anthropic`, `httpx`, `pypdf` (BSD), `trafilatura` (Apache-2.0), `lxml` (BSD); dev: `pytest`, `ruff`. Exact versions pinned in `pyproject.toml` at implementation time.

## 4. Data model

### 4.1 Corpus manifest (`corpora/<corpus>/manifest.json`)

```json
{
  "corpus": "gov",
  "version": "2026-11-08",
  "license_summary": "US federal works, public domain",
  "documents": [
    {"doc_id": "<sha256 of bytes>", "uri": "...", "format": "xml|json|pdf|html|md|csv",
     "source_version": "<e.g. eCFR date or FR document number>", "bytes": 12345,
     "license": "public-domain", "path": "data/gov/<doc_id>.<ext>"}
  ]
}
```

`snapshot` = SHA-256 of the canonical (sorted-key) manifest JSON. Documents are fetched into `data/` and not committed (except tiny fixtures). `fetch` refuses any file whose hash differs from the manifest.

### 4.2 Golden item (`golden/<corpus>/v0.1/items.jsonl`)

| Field | Type | Notes |
|---|---|---|
| `id` | str | `<corpus>-<qtype>-<n>` |
| `corpus`, `snapshot` | str | snapshot must match the current manifest at run time |
| `qtype` | enum | `factoid`, `count_filter`, `procedure`, `policy_asof`, `overview`, `id_lookup`, `insufficient` |
| `question` | str | |
| `as_of` | date \| null | required for `policy_asof` |
| `answer` | object | `kind` ∈ {`text`, `set`, `number`, `id`, `abstain`}, `value`, `accepted_variants` |
| `evidence` | list | `{doc_id, char_start, char_end, quote}`; empty for `insufficient` |
| `gold_query` | object | `{store, op, filters, entities, as_of}`; `store` ∈ {`typed_db`, `knowledge`, `raw`}; `op` ∈ {`lookup`, `count`, `list`, `explain`, `procedure`, `abstain`} |
| `rarity` | enum | `head`, `torso`, `tail` by key-entity document frequency (tertiles computed per corpus) |
| `split` | enum | `dev` (20%) or `test` (80%), assigned once by seeded hash of `id` |
| `provenance` | object | generator model ID, prompt hash, seed, created timestamp |
| `checks` | object | `span_ok`, `recompute_ok`, `evidence_only_ok`, `gold_query_exec_ok`, `dedup_ok` |
| `status` | enum | `auto_verified`, `human_vetted`, `rejected` (`human_vetted` unused in v0.1) |

A Pydantic model enforces the schema; `golden --verify` re-runs every check from scratch.

## 5. Corpora

| Corpus | Contents | Supports | Notes |
|---|---|---|---|
| `gov` | Point-in-time eCFR XML for a few frequently amended CFR parts (≥2 dated versions each); selected Internal Revenue Manual chapters (procedures); Federal Register document metadata (JSON) for the same agencies | all 7 types; as-of policy; count/filter from metadata | Public domain; may be committed later if wanted. Parts chosen at implementation start by amendment frequency. |
| `research` | The repo's reports and notes (markdown), `papers/manifest.csv` as structured data, a fixed seeded sample of ~200 local PDFs | factoid, count/filter (manifest), overview, id_lookup (arXiv IDs), insufficient | PDFs remain local-only; the manifest pins their hashes; other users rebuild via `scripts/download_papers.py`. Thin on procedures and as-of policy, which is expected. |
| `bench` | Subset of an open enterprise benchmark; first candidate EnterpriseRAG-Bench (Onyx) | its own questions as a separate set, plus our 7 types where applicable | Licence and format verified before adoption; if unsuitable, choose a permissively licensed substitute and record why. Subset size fixed by seed. |

## 6. Golden-set generation (automatic, code-verified)

| Question type | Method |
|---|---|
| `count_filter` | Answer computed by code from structured fields (FR metadata, `papers/manifest.csv`, benchmark metadata). The LLM only phrases the question. `gold_query` is executable by construction. |
| `factoid`, `id_lookup`, `procedure`, `overview` | Claude reads a sampled section and returns question, answer and a verbatim quote. Code locates the quote in the source after whitespace normalization and records character offsets; no match ⇒ rejected. `factoid` and `id_lookup` cite the quote; `overview` and `procedure` answers span the section, so they cite the whole generating section, and their quote must also lie within it. `procedure` answers are ordered text (numbered steps). |
| `policy_asof` | Only from sections with ≥2 versions where the answer differs between versions; gold answer per `as_of`; each answer checked against its version's text. |
| `insufficient` | Questions about entities or facts code confirms have zero matches in the corpus (normalized term search across all documents); gold answer `abstain`. |

Checks applied to every candidate item:

1. Span re-slice: every `quote` equals `source[char_start:char_end]` after normalization.
2. Recompute: set and number answers recomputed by code where the data is structured.
3. Evidence-only answer: a second Claude call answers using only the cited evidence; mismatch ⇒ rejected.
4. `gold_query` execution: executed where executable; must reproduce the answer.
5. Dedup: near-duplicate questions removed (normalized-token Jaccard ≥ 0.8).
6. Balance: at least 30% of items per corpus are `tail` rarity where the corpus allows; shortfalls are reported, not padded.

Targets for v0.1: up to 50 items per question type per corpus (≤350 per corpus). All generation uses a fixed seed; every raw LLM output is cached by input hash, so regeneration is free and identical. Rejected items go to `rejected.jsonl` with the failed check.

## 7. Baseline system

The baseline is deliberately flat: a yardstick, not the toolkit.

### 7.1 Ingestion

Plain-text extraction per format (native XML for eCFR, JSON for FR metadata, `pypdf` for PDF, `trafilatura` for HTML, markdown and CSV as text). Recursive splitting to ~400 tokens, no overlap, no enrichment. Each chunk records `chunk_id` (SHA-256 of `doc_id` + offsets), `doc_id`, `char_start`, `char_end`.

### 7.2 Retrieval

| Component | Setting |
|---|---|
| BM25 | `bm25s`, fixed tokenizer (lowercase, Unicode NFKC, alphanumeric tokens, fixed English stopword list), k1 = 1.2, b = 0.75 |
| Dense | `bge-small-en-v1.5` via `fastembed`, single-threaded, model file hash recorded; exact cosine kNN in NumPy (no ANN index) |
| Fusion A | RRF, k = 60 (unlabelled default) |
| Fusion B | Linear combination of min-max-normalized scores, one weight tuned on the dev split by grid search (0.0–1.0, step 0.05), selected by dev nDCG@10 |
| Output | Top 10 chunks |

Determinism rules: scores rounded to 6 decimals before ranking; ties broken by `chunk_id`; index fingerprint = SHA-256 over snapshot hash, chunker config, tokenizer config, BM25 parameters, embedding model hash and chunk ID list.

### 7.3 Query side (G2 baseline)

A zero-shot Claude call converts the question into the `gold_query` JSON schema, given the schema description and the corpus's field list. Scored per field (`store`, `op`, filters, entities, `as_of`), whole-query exact match, and execution match where executable. The baseline answerer does not use the generated query; G2 is scored independently.

### 7.4 Answering

Claude with a pinned model ID (config), temperature 0, structured JSON output: `answer`, `kind`, `citations` (chunk IDs), `abstain` (bool), `confidence` (0–1). The prompt instructs answering only from the provided passages and abstaining when they do not contain the answer. Count/filter questions are answered from retrieved chunks; low scores there are expected and measure the gap G1 and G2 must close.

### 7.5 Splits and cost

Splits fixed per item (§4.2). Tokens from API usage fields; dollars from a dated price table in `config/prices.json`.

## 8. Scoring

### 8.1 End-to-end outcomes

Every item and repeat resolves to `correct`, `wrong`, `abstained` or `error`.

| Answer kind | Scorer |
|---|---|
| `number`, `id` | Exact after normalization (case, whitespace, thousands separators, units table) |
| `set` | Exact match plus precision, recall, F1; `correct` only on exact match |
| `abstain` (insufficient items) | `correct` iff the system abstains; any answer is `wrong` |
| `text` | Judge: `correct` / `partial` / `incorrect` + one-line reason; `partial` counted as `wrong` in the penalised score and reported separately |

Abstention by the system on an answerable item is `abstained`.

Penalised score per item: `correct` = 1, `abstained` = 0, `wrong` = −t/(1−t). Reported at t ∈ {0.5, 0.75, 0.9}, alongside accuracy, error rate, abstention rate and partial rate.

Citation faithfulness: (a) share of cited chunks overlapping any gold evidence span; (b) share of answered items whose gold evidence is covered by at least one cited chunk.

### 8.2 Judge

Pluggable `JudgeModel` interface with adapters: `anthropic`, `openai_compatible` (configurable base URL, model name and key environment variable), `stub` (deterministic, for tests). Temperature 0; prompt hash recorded; calls cached by input hash. The judge sees question, gold answer with accepted variants, and candidate answer; not the retrieved passages.

Validation until human labels exist:

- Judge-vs-exact proxy κ: the judge also grades `number`/`set`/`id` items; Cohen's κ against the exact scorer, labelled "proxy, not human κ".
- Self-consistency: each text item judged twice (cache bypassed by a repeat index); agreement rate reported.
- Every report carries "judge and generator share a model family" while that holds.
- `human_kappa` field present and empty; the Phase 0 exit item stays open.

### 8.3 Retrieval metrics (G3)

A chunk is relevant if it overlaps a gold evidence span (binary for Recall@10 and MRR; graded by overlap fraction for nDCG@10). Full-evidence coverage: share of multi-span items with every span overlapped in the top 10. All metrics stratified by `rarity` and `qtype`, per corpus and pooled. `insufficient` items are excluded from retrieval metrics.

### 8.4 Determinism

Each query is run R = 5 times. Retrieval: share of items whose ranked chunk-ID list is identical across all repeats (expected 100%; less is a bug and fails the run's determinism check). LLM: answer agreement across repeats, and pass^5 (all 5 repeats correct).

### 8.5 Statistics

Paired comparisons on identical items. Continuous metrics: paired bootstrap 95% CIs, 10,000 resamples, fixed seed. Binary correctness: McNemar's exact test. Multiple systems: Holm correction. Reported per corpus and pooled.

## 9. Runner, CLI and reports

```
adr-eval fetch   <corpus>
adr-eval golden  <corpus> --gen | --verify
adr-eval index   <corpus>
adr-eval run     <corpus> --system baseline-rrf|baseline-linear --repeats 5 --split test
                 [--max-dollars N] [--dry-run]
adr-eval report  <run_id> [--compare <run_id>]
```

`runs/<run_id>/` contains `config.json` (model IDs, prompt hashes, snapshot, index fingerprint, seed, price-table date), `results.jsonl` (one row per item × repeat: retrieved IDs and scores, generated query, answer, tokens, latency, outcome, judge label), `report.md` and `report.json` (all tracks with CIs, by corpus × qtype × rarity). Baseline summaries are copied to `results/` and committed.

Cost and reliability: `--dry-run` estimates tokens and dollars from item counts; `--max-dollars` stops before exceeding budget; one content-addressed cache for all model calls (key = SHA-256 of adapter, model ID, prompt hash, inputs, repeat index); bounded concurrency; retries with exponential backoff on 429/5xx.

## 10. Error handling

- A failed model call after retries marks that item/repeat `error`; reports count errors; nothing is dropped silently.
- Hash mismatch at fetch, missing corpus file, or golden-set snapshot ≠ current manifest snapshot stops the command with a message naming the file and the fix.
- Golden items failing any check move to `rejected.jsonl` with the failed check; never deleted.
- Schema violations in golden files fail `golden --verify` with item IDs.

## 11. Credentials

`ANTHROPIC_API_KEY` from the environment, requested through the secure credential form when the baseline is recorded (never pasted in chat). The OpenAI-compatible judge adapter reads its key from a configurable environment variable. No keys in config files or the repo.

## 12. Testing

Test-first with `pytest`:

- Scorers: normalization, set F1, penalised score maths at each t, κ computation, bootstrap CI reproducibility with fixed seed, McNemar.
- Golden: span re-slice, manifest verification, dedup, split assignment stability.
- Retrieval: identical index + query ⇒ identical ranked list; tie-breaking; index fingerprint stability across rebuilds.
- End-to-end: a tiny bundled fixture corpus (a few committed public-domain documents and hand-checked golden items) run through fetch → index → run → report with the `stub` model, no network or keys.
- CI: GitHub Actions runs `ruff` and `pytest` on push and pull request.

## 13. Phase 0 exit checklist

| Item | Status at end of Phase 0 (planned) |
|---|---|
| Golden sets v0.1 for `gov`, `research`, `bench` | Delivered (auto-verified) |
| Baseline recorded: RRF and linear, all five tracks, with tokens and dollars | Delivered |
| Paired tests chosen (bootstrap, McNemar, Holm) | Delivered |
| Judge-vs-exact proxy κ and self-consistency | Delivered |
| Judge-vs-human κ | Open: needs a human-labelled sample |
| Cross-family judge | Open: needs the user's hosted model or another provider |
| Human-vetted golden items | Open: `human_vetted` status reserved |

## 14. Risks

| Risk | Mitigation |
|---|---|
| Same-family judge inflates agreement with the generator | Warning on every report; proxy κ against exact scorers; swap-in adapter ready |
| LLM-drafted questions skew toward easy, extractive items | Code-computed count/filter and as-of items; rarity balance target; insufficient items |
| Benchmark licence or format unsuitable | Verify first; documented substitute |
| eCFR/IRM/FR endpoints change or rate-limit | Manifest pins bytes by hash; fetch is resumable and polite |
| CPU embedding too slow for large corpora | `bge-small` on ONNX; corpus subsets sized by seed; embeddings cached by chunk hash |
