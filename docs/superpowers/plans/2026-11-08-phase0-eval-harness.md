# Phase 0 Evaluation Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `adr-eval`, a standalone Python package that pins three corpora by hash, generates code-verified golden sets, runs a flat hybrid BM25+dense baseline with a Claude answerer, and scores five tracks (G1 compile, G2 query understanding, G3 retrieval, determinism, end-to-end).

**Architecture:** File-based and deterministic. Corpora are manifests of SHA-256-pinned documents; golden sets are JSONL; every model call goes through one content-addressed cache; retrieval is exact (no ANN) with fixed rounding and tie-breaks; runs write `runs/<run_id>/` and reports compare runs with paired statistics.

**Tech Stack:** Python ≥3.11 (dev box has 3.13), pydantic v2, bm25s, fastembed (ONNX, `BAAI/bge-small-en-v1.5`), numpy, anthropic, httpx, pypdf, trafilatura, lxml, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-11-08-phase0-eval-harness-design.md`

## Global Constraints

- Licence Apache-2.0; every dependency permissive (MIT/BSD/Apache-2.0).
- Python ≥3.11; package `adr_eval` under `src/`; console script `adr-eval`.
- No GPU; embeddings on CPU, single-threaded.
- Question types exactly: `factoid`, `count_filter`, `procedure`, `policy_asof`, `overview`, `id_lookup`, `insufficient`.
- Answer kinds exactly: `text`, `set`, `number`, `id`, `abstain`. Statuses: `auto_verified`, `human_vetted`, `rejected`.
- `gold_query.store` ∈ {`typed_db`, `knowledge`, `raw`}; `gold_query.op` ∈ {`lookup`, `count`, `list`, `explain`, `procedure`, `abstain`}.
- BM25: k1 = 1.2, b = 0.75. Chunks ~400 tokens, no overlap. RRF k = 60. Linear weight grid 0.0–1.0 step 0.05 on dev nDCG@10. Top 10.
- Scores rounded to 6 decimals before ranking; ties broken by `chunk_id` ascending.
- Splits: 20% `dev`, 80% `test`, by seeded hash of item `id`. Repeats R = 5.
- Penalised score: correct = 1, abstained = 0, wrong (incl. partial) = −t/(1−t), at t ∈ {0.5, 0.75, 0.9}.
- Bootstrap: 10,000 paired resamples, fixed seed; McNemar exact; Holm correction.
- Dedup threshold: normalized-token Jaccard ≥ 0.8. Rarity: tertiles of key-entity document frequency, per corpus. Target ≥30% `tail`.
- Up to 50 golden items per question type per corpus.
- No API keys in files; `ANTHROPIC_API_KEY` from environment; OpenAI-compatible key from a configurable env var name.
- Fetched documents, runs and caches are git-ignored (`data/`, `runs/`, `.cache/`); manifests, golden sets and `results/` are committed.
- Evidence offsets are character offsets into the **extracted text** produced by `extract_text` (Task 3), which is deterministic for a given document hash and extractor version.

## Review Focus

1. A quote that occurs more than once in a document: `find_quote` must return the first occurrence deterministically (test in Task 7), and generators must reject such ambiguous quotes rather than guess which occurrence was meant (test in Task 8).
2. A model reply that is not valid JSON or is truncated: the answerer and generators must raise `ModelOutputError`, and the runner must record `error` for that item, not crash (tests in Task 9 and Task 12).
3. A document with no extractable text (scanned PDF without a text layer, empty file): extraction returns `""`, chunking returns `[]`, the loader records it in `empty_docs`, and G1 reports it (tests in Task 3 and Task 5).
4. A query whose tokens are all stopwords or out-of-vocabulary: BM25 returns `[]` and fusion falls back to the dense list without error (test in Task 6).
5. Non-ASCII text (NBSP, `§`, ligature `ﬁ`, curly quotes) in sources and quotes: whitespace-normalized matching still finds the span and the tokenizer applies NFKC (tests in Task 5 and Task 7).

---

## File Structure

```
pyproject.toml                      # T1
.github/workflows/ci.yml            # T1
src/adr_eval/__init__.py            # T1
src/adr_eval/models.py              # T1  pydantic data model
src/adr_eval/cache.py               # T2  content-addressed cache
src/adr_eval/llm.py                 # T2  ModelClient protocol + adapters + cost
config/prices.json                  # T2
src/adr_eval/corpora/base.py        # T3  manifest fetch/verify, Document loading, adapter protocol
src/adr_eval/corpora/extract.py     # T3  extract_text per format
src/adr_eval/corpora/gov.py         # T4
src/adr_eval/corpora/research.py    # T4
src/adr_eval/corpora/bench.py       # T4
corpora/{gov,research,bench}/       # T4  config.json, manifest.json, README.md
src/adr_eval/retrieval/chunker.py   # T5
src/adr_eval/retrieval/lexical.py   # T5
src/adr_eval/retrieval/dense.py     # T6
src/adr_eval/retrieval/fusion.py    # T6
src/adr_eval/retrieval/index.py     # T6  HybridIndex + fingerprint
src/adr_eval/golden/verify.py       # T7
src/adr_eval/golden/records.py      # T8  structured-record filter grammar + gold_query execution
src/adr_eval/golden/generate.py     # T8
src/adr_eval/golden/prompts/*.txt   # T8
src/adr_eval/answer/answerer.py     # T9
src/adr_eval/answer/query_gen.py    # T9
src/adr_eval/answer/prompts/*.txt   # T9
src/adr_eval/scoring/exact.py       # T10
src/adr_eval/scoring/outcomes.py    # T10
src/adr_eval/scoring/retrieval_metrics.py # T10
src/adr_eval/scoring/compile_metrics.py   # T10
src/adr_eval/scoring/determinism.py # T10
src/adr_eval/scoring/judge.py       # T11
src/adr_eval/scoring/stats.py       # T11
src/adr_eval/runner.py              # T12
src/adr_eval/report.py              # T12
src/adr_eval/cli.py                 # T12
tests/fixtures/mini/                # T3 tiny committed corpus (+ golden in T7)
tests/...                           # per task
results/                            # T13
```

---

### Task 1: Package scaffold, data model and CI

**Files:**
- Create: `pyproject.toml`, `src/adr_eval/__init__.py`, `src/adr_eval/models.py`, `.github/workflows/ci.yml`
- Modify: `.gitignore` (append `data/`, `runs/`, `.cache/`, `*.egg-info/`, `__pycache__/`)
- Test: `tests/test_models.py`

**Interfaces:**
- Produces (in `adr_eval.models`):
  - `QType = Literal["factoid","count_filter","procedure","policy_asof","overview","id_lookup","insufficient"]`
  - `AnswerKind = Literal["text","set","number","id","abstain"]`
  - `class ManifestDoc(BaseModel)`: `doc_id: str, uri: str, format: Literal["xml","json","pdf","html","md","csv","txt"], source_version: str, bytes: int, license: str, path: str`
  - `class Manifest(BaseModel)`: `corpus: str, version: str, license_summary: str, documents: list[ManifestDoc]`; `def snapshot(self) -> str` (SHA-256 hex of `json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",",":"))`)
  - `class Evidence(BaseModel)`: `doc_id: str, char_start: int, char_end: int, quote: str`
  - `class Answer(BaseModel)`: `kind: AnswerKind, value: str | float | list[str] | None, accepted_variants: list[str] = []`
  - `class GoldQuery(BaseModel)`: `store: Literal["typed_db","knowledge","raw"], op: Literal["lookup","count","list","explain","procedure","abstain"], filters: dict[str, str | int | float | list[str]] = {}, entities: list[str] = [], as_of: date | None = None`
  - `class Checks(BaseModel)`: `span_ok, recompute_ok, evidence_only_ok, gold_query_exec_ok, dedup_ok: bool | None = None`
  - `class Provenance(BaseModel)`: `model: str, prompt_hash: str, seed: int, created: datetime`
  - `class GoldenItem(BaseModel)`: `id, corpus, snapshot: str; qtype: QType; question: str; as_of: date | None; answer: Answer; evidence: list[Evidence]; gold_query: GoldQuery; rarity: Literal["head","torso","tail"] | None; split: Literal["dev","test"] | None; provenance: Provenance; checks: Checks; status: Literal["auto_verified","human_vetted","rejected"]; reject_reason: str | None = None`; validator: `qtype == "policy_asof"` requires `as_of`; `answer.kind == "abstain"` requires `evidence == []`.
  - `def load_items(path: Path) -> list[GoldenItem]`, `def write_items(path: Path, items: list[GoldenItem]) -> None` (JSONL, one item per line, sorted by `id`, `sort_keys=True`)

- [ ] **Step 1: Write the failing tests**

```python
def test_snapshot_is_order_independent_of_key_order_and_stable():
    m1 = Manifest(corpus="mini", version="1", license_summary="pd", documents=[DOC_A])
    m2 = Manifest.model_validate(json.loads(json.dumps(m1.model_dump(mode="json"))[::-1][::-1]))
    assert m1.snapshot() == m2.snapshot() and len(m1.snapshot()) == 64

def test_policy_asof_requires_as_of():
    with pytest.raises(ValidationError): make_item(qtype="policy_asof", as_of=None)

def test_abstain_answer_forbids_evidence():
    with pytest.raises(ValidationError): make_item(answer=Answer(kind="abstain", value=None), evidence=[EV])

def test_write_then_load_roundtrip_sorted(tmp_path):
    write_items(tmp_path/"i.jsonl", [make_item(id="b"), make_item(id="a")])
    assert [i.id for i in load_items(tmp_path/"i.jsonl")] == ["a", "b"]
```

(`DOC_A`, `EV`, `make_item(**overrides)` are fixtures in `tests/conftest.py` building a valid minimal item.)

- [ ] **Step 2: Run** `pytest tests/test_models.py -v` → FAIL (module not found).
- [ ] **Step 3: Implement** `pyproject.toml` (hatchling build, deps from Tech Stack with `>=` floors pinned to current releases, `[project.scripts] adr-eval = "adr_eval.cli:main"`, `[tool.ruff] line-length = 100`), `models.py` as in Interfaces, and `ci.yml` (ubuntu-latest, Python 3.11 and 3.13, `pip install -e .[dev]`, `ruff check .`, `pytest -q`).
- [ ] **Step 4: Run** `pip install -e .[dev] && pytest tests/test_models.py -v && ruff check .` → PASS, no lint errors.
- [ ] **Step 5: Commit** `git add -A pyproject.toml src tests .github .gitignore && git commit -m "feat(eval): package scaffold, data model and CI"`

---

### Task 2: Cache and model adapters

**Files:**
- Create: `src/adr_eval/cache.py`, `src/adr_eval/llm.py`, `config/prices.json`
- Test: `tests/test_cache.py`, `tests/test_llm.py`

**Interfaces:**
- Produces:
  - `class Cache`: `__init__(self, root: Path)`; `@staticmethod key(*parts: object) -> str` (SHA-256 of `json.dumps(parts, sort_keys=True, default=str)`); `get(self, key: str) -> dict | None`; `put(self, key: str, value: dict) -> None` (writes `root/key[:2]/key.json` atomically via temp file + rename).
  - `@dataclass(frozen=True) class Completion`: `text: str, input_tokens: int, output_tokens: int, model: str, latency_s: float, cached: bool`
  - `class ModelError(Exception)`; `class ModelOutputError(ModelError)` (used by later tasks for unparseable output).
  - `class ModelClient(Protocol)`: attributes `name: str`, `family: str`; `complete(self, system: str, user: str, *, max_tokens: int, repeat: int = 0) -> Completion`
  - `class AnthropicClient(model: str, cache: Cache, max_retries: int = 5)` family `"anthropic"`; `class OpenAICompatibleClient(base_url: str, model: str, api_key_env: str, family: str, cache: Cache, max_retries: int = 5)`; `class StubClient(fn: Callable[[str, str, int], str], family: str = "stub")` (no cache, zero tokens counted as `len(text)//4`).
  - `def parse_json(text: str) -> dict` (strips ```json fences, raises `ModelOutputError` on failure).
  - `def load_prices(path: Path) -> dict` and `def cost_usd(c: Completion, prices: dict) -> float` (`prices[model] = {"input_per_mtok": float, "output_per_mtok": float, "as_of": "YYYY-MM-DD"}`; cached completions cost 0; unknown model raises `KeyError`).
- Retry policy: retry on HTTP 429, 5xx, timeouts and connection errors; sleep 1, 2, 4, 8, 16 s (no jitter); then raise `ModelError`. Cache key = `Cache.key(self.name, model, system, user, max_tokens, repeat)`; temperature fixed at 0.

- [ ] **Step 1: Write the failing tests**

```python
def test_cache_key_stable_and_roundtrip(tmp_path):
    c = Cache(tmp_path); k = Cache.key("a", 1, {"x": 2})
    assert k == Cache.key("a", 1, {"x": 2}); c.put(k, {"v": 1}); assert c.get(k) == {"v": 1}

def test_parse_json_strips_fences_and_rejects_garbage():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ModelOutputError): parse_json('{"a": ')

def test_cost_zero_when_cached_and_uses_price_table():
    p = {"m": {"input_per_mtok": 3.0, "output_per_mtok": 15.0, "as_of": "2026-11-08"}}
    assert cost_usd(Completion("x", 1_000_000, 0, "m", 0.1, False), p) == 3.0
    assert cost_usd(Completion("x", 1_000_000, 0, "m", 0.1, True), p) == 0.0

def test_openai_compatible_retries_then_succeeds(httpx_mock_429_then_200, tmp_path):
    cl = OpenAICompatibleClient("http://x/v1", "m", "K", "selfhost", Cache(tmp_path))
    assert cl.complete("s", "u", max_tokens=10).text == "ok"   # sleep patched to no-op

def test_repeat_index_changes_cache_key(tmp_path): ...  # same prompt, repeat 0 vs 1 → two upstream calls
```

(Use `respx` or a small `httpx.MockTransport` fixture; add `respx` to dev deps if used. Patch `time.sleep`.)

- [ ] **Step 2: Run** `pytest tests/test_cache.py tests/test_llm.py -v` → FAIL.
- [ ] **Step 3: Implement** `cache.py`, `llm.py` (Anthropic via the `anthropic` SDK `messages.create`, OpenAI-compatible via `httpx` POST `/chat/completions`), `config/prices.json` containing the pinned Claude model ID used in Task 13 with its published prices and `as_of`.
- [ ] **Step 4: Run** the same tests → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(eval): content-addressed cache and model adapters"`

---

### Task 3: Manifest fetch/verify, text extraction, Document loading, fixture corpus

**Files:**
- Create: `src/adr_eval/corpora/__init__.py`, `src/adr_eval/corpora/base.py`, `src/adr_eval/corpora/extract.py`, `tests/fixtures/mini/` (5–8 tiny public-domain files: 2 `.md`, 1 `.html`, 1 `.json` records file, 1 small text-layer `.pdf`, 1 `.xml`, plus two dated versions of one `.xml` section; `manifest.json`)
- Test: `tests/test_corpora_base.py`, `tests/test_extract.py`

**Interfaces:**
- Produces:
  - `EXTRACTOR_VERSION = "1"` (bump whenever extraction output can change; part of the index fingerprint).
  - `def extract_text(data: bytes, fmt: str) -> str`: `md`/`txt`/`csv` → UTF-8 decode (errors="strict"); `html` → `trafilatura.extract(data.decode(), output_format="txt", include_comments=False, favor_precision=True) or ""`; `pdf` → `pypdf` pages' `extract_text()` joined by `"\n\f\n"`; `xml` → `lxml` `itertext()` with block elements separated by `"\n"`; `json` → `json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)`.
  - `@dataclass(frozen=True) class Document`: `doc_id: str, text: str, format: str, source_version: str, uri: str`
  - `class HashMismatch(Exception)`
  - `def sha256_bytes(b: bytes) -> str`
  - `def fetch_manifest(m: Manifest, root: Path, fetcher: Callable[[str], bytes]) -> None` (skip files present with matching hash; download otherwise; raise `HashMismatch(path, expected, got)` without writing on mismatch)
  - `def verify_manifest(m: Manifest, root: Path) -> list[str]` (human-readable problems; empty list = OK)
  - `@dataclass class LoadedCorpus`: `manifest: Manifest, docs: dict[str, Document], empty_docs: list[str]`
  - `def load_corpus(manifest_path: Path, root: Path) -> LoadedCorpus` (raises `ValueError` listing problems if `verify_manifest` is non-empty; docs whose extracted text is empty after `.strip()` go to `empty_docs` and are still in `docs`)
  - `class CorpusAdapter(Protocol)`: `name: str`; `build_manifest(self, root: Path) -> Manifest`; `records(self, corpus: LoadedCorpus) -> list[dict]` (structured rows for count/filter; each row has `"_doc_id"` and an `id` field); `record_schema(self) -> dict[str, str]` (field → type and one-line description, used in G2 prompts); `version_pairs(self, corpus: LoadedCorpus) -> list[tuple[Document, Document]]` (same section, two dates; may be empty).

- [ ] **Step 1: Write the failing tests**

```python
def test_fetch_refuses_hash_mismatch(tmp_path):
    m = manifest_with(doc_id=sha256_bytes(b"good"))
    with pytest.raises(HashMismatch): fetch_manifest(m, tmp_path, lambda uri: b"evil")
    assert not (tmp_path / m.documents[0].path).exists()

def test_load_mini_corpus_verifies_and_extracts():
    lc = load_corpus(MINI/"manifest.json", MINI)
    assert len(lc.docs) == len(lc.manifest.documents) and lc.empty_docs == []

def test_extract_is_deterministic_for_each_format():
    for d in MINI_DOCS: assert extract_text(d.bytes, d.fmt) == extract_text(d.bytes, d.fmt)

def test_empty_pdf_yields_empty_text_and_is_flagged(tmp_path):   # Review Focus 3
    lc = load_corpus(*corpus_with_blank_pdf(tmp_path))
    assert lc.empty_docs == [BLANK_ID] and lc.docs[BLANK_ID].text.strip() == ""

def test_json_extraction_sorted_keys():
    assert extract_text(b'{"b":1,"a":2}', "json").index('"a"') < extract_text(b'{"b":1,"a":2}', "json").index('"b"')
```

- [ ] **Step 2: Run** `pytest tests/test_corpora_base.py tests/test_extract.py -v` → FAIL.
- [ ] **Step 3: Implement** `extract.py` and `base.py` as in Interfaces; build `tests/fixtures/mini/manifest.json` with real hashes (a tiny helper `scripts/make_manifest.py <dir>` that hashes files is acceptable and reused by Task 4).
- [ ] **Step 4: Run** the tests → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(eval): manifest fetch/verify, extraction and fixture corpus"`

---

### Task 4: Corpus adapters for gov, research and bench

**Files:**
- Create: `src/adr_eval/corpora/gov.py`, `src/adr_eval/corpora/research.py`, `src/adr_eval/corpora/bench.py`, `src/adr_eval/corpora/registry.py`, `corpora/gov/config.json`, `corpora/research/config.json`, `corpora/bench/config.json`, `corpora/*/README.md`, then generated `corpora/*/manifest.json`
- Test: `tests/test_adapters.py` (offline: recorded HTTP fixtures under `tests/fixtures/http/`)

**Interfaces:**
- Consumes: Task 3 `CorpusAdapter`, `Manifest`, `fetch_manifest`, `sha256_bytes`.
- Produces: `def get_adapter(name: Literal["gov","research","bench","mini"]) -> CorpusAdapter` in `registry.py` (`"mini"` is a fixture adapter over `tests/fixtures/mini`).
- `gov` sources (all public domain):
  - eCFR versioner API: `https://www.ecfr.gov/api/versioner/v1/versions/title-{T}.json?part={P}` to list amendment dates, and `https://www.ecfr.gov/api/versioner/v1/full/{YYYY-MM-DD}/title-{T}.xml?part={P}` for point-in-time XML. `config.json` pins `parts: [{title, part}]` and, per part, the exact `dates` fetched (≥2).
  - Internal Revenue Manual HTML chapters from `https://www.irs.gov/irm/...`, URLs pinned in `config.json`.
  - Federal Register API `https://www.federalregister.gov/api/v1/documents.json` filtered by the chosen CFR parts' agencies, pinned query and `per_page`; saved as one JSON file per document. `records()` returns rows `{id: document_number, type, agency, publication_date, year, title, cfr_parts: [..], _doc_id}`.
  - `version_pairs()`: for each eCFR part, consecutive dated versions split into sections by `<DIV8>`/section number; returns pairs whose section text differs.
- `research` sources: `reports/*.md`, `research_notes/**/*.md`, `papers/manifest.csv` (as one `csv` doc; `records()` returns its rows with `id` = `arxiv_id` or `doi` or a hash of `url`), plus a seeded sample (seed 20261108) of 200 rows of `papers/manifest.csv` with `status == "downloaded"` whose `local_file` exists; URIs are `file://` repo-relative paths. `version_pairs()` returns `[]`.
- `bench`: first candidate EnterpriseRAG-Bench (Onyx). `config.json` pins source URL, licence, revision and a seeded document subset (≤2,000 docs). Its native questions are exported by `bench.native_items() -> list[dict]` for Task 8 to convert.

- [ ] **Step 1: Check connectivity and licences.** Run `curl -sS -o /dev/null -w '%{http_code}\n' https://www.ecfr.gov/api/versioner/v1/titles.json`, the same for `https://www.federalregister.gov/api/v1/documents.json?per_page=1` and `https://www.irs.gov/irm`. Locate the EnterpriseRAG-Bench repository and read its LICENSE and data format. Record findings in `corpora/bench/README.md`. If the benchmark is not permissively licensed or not obtainable, choose a permissively licensed substitute with enterprise-style documents and native questions, and record the reason. If a gov host is blocked by the sandbox network, stop and report the blocked host to the user rather than switching sources.
- [ ] **Step 2: Choose gov parts.** Using the versions API, pick the 3 CFR parts (across at most 2 titles) with the most amendment dates since 2020-01-01 that are under 2 MB of XML each; pin them and 2–4 dates each in `corpora/gov/config.json`. Pin 3–5 IRM chapters that describe procedures for the same agencies' domain if one exists, else general taxpayer-procedure chapters.
- [ ] **Step 3: Write the failing offline tests**

```python
def test_gov_manifest_from_recorded_http(recorded_gov):
    m = get_adapter("gov").build_manifest(recorded_gov.root)
    assert {d.format for d in m.documents} >= {"xml", "json", "html"} and all(len(d.doc_id) == 64 for d in m.documents)

def test_gov_version_pairs_differ(recorded_gov_loaded):
    pairs = get_adapter("gov").version_pairs(recorded_gov_loaded)
    assert pairs and all(a.text != b.text and a.source_version < b.source_version for a, b in pairs)

def test_research_sample_is_seeded_and_stable(repo_root):
    a = get_adapter("research").build_manifest(repo_root); b = get_adapter("research").build_manifest(repo_root)
    assert a.snapshot() == b.snapshot()

def test_records_have_id_and_doc_id(recorded_gov_loaded):
    assert all({"id", "_doc_id"} <= r.keys() for r in get_adapter("gov").records(recorded_gov_loaded))
```

(`research` tests skip with a clear reason if local PDFs are absent; they only assert stability and schema.)

- [ ] **Step 4: Run** `pytest tests/test_adapters.py -v` → FAIL.
- [ ] **Step 5: Implement** the three adapters and `registry.py`; a polite fetcher (User-Agent `adr-eval/0.1`, 1 request/s per host, resumable).
- [ ] **Step 6: Run** the tests → PASS. Then build real manifests: `python -m adr_eval.corpora.registry build gov` (and `research`, `bench`) and confirm each `corpora/<c>/manifest.json` loads with `load_corpus` and an empty problem list.
- [ ] **Step 7: Commit** `git add corpora src/adr_eval/corpora tests && git commit -m "feat(eval): gov, research and bench corpus adapters and pinned manifests"`

---

### Task 5: Chunker and BM25 lexical index

**Files:**
- Create: `src/adr_eval/retrieval/__init__.py`, `src/adr_eval/retrieval/chunker.py`, `src/adr_eval/retrieval/lexical.py`
- Test: `tests/test_chunker.py`, `tests/test_lexical.py`

**Interfaces:**
- Consumes: Task 3 `Document`.
- Produces:
  - `@dataclass(frozen=True) class Chunk`: `chunk_id: str, doc_id: str, char_start: int, char_end: int, text: str`; `chunk_id = sha256(f"{doc_id}:{char_start}:{char_end}")`.
  - `CHUNKER_CONFIG = {"max_tokens": 400, "separators": ["\n\n", "\n", ". ", " "], "overlap": 0}`
  - `def chunk_document(doc: Document, max_tokens: int = 400) -> list[Chunk]`: recursive split on the separators in order until each piece has ≤ `max_tokens` tokens per `tokenize` (Task 5); adjacent small pieces are greedily merged up to the limit; spans are exact (`doc.text[s:e] == chunk.text`); whitespace-only text yields `[]`.
  - `TOKENIZER_CONFIG = {"normalize": "NFKC", "lower": True, "pattern": r"[a-z0-9]+", "stopwords": "adr_eval/retrieval/stopwords_en.txt"}` (ship a fixed ~180-word English list).
  - `def tokenize(text: str, drop_stopwords: bool = True) -> list[str]` (`chunk_document` counts with `drop_stopwords=False`).
  - `class BM25Index`: `__init__(self, k1: float = 1.2, b: float = 0.75)`; `build(self, chunks: list[Chunk]) -> None`; `search(self, query: str, k: int = 100) -> list[tuple[str, float]]` (chunk_id, score), scores rounded to 6 dp, sorted by `(-score, chunk_id)`, zero-score hits excluded; `config(self) -> dict` (for the fingerprint, includes the `bm25s` method name and version).

- [ ] **Step 1: Write the failing tests**

```python
def test_chunks_cover_text_exactly_without_overlap():
    cs = chunk_document(LONG_DOC)
    assert all(LONG_DOC.text[c.char_start:c.char_end] == c.text for c in cs)
    assert all(a.char_end <= b.char_start for a, b in zip(cs, cs[1:]))
    assert all(len(tokenize(c.text, drop_stopwords=False)) <= 400 for c in cs)

def test_whitespace_doc_has_no_chunks():                     # Review Focus 3
    assert chunk_document(Document("d", " \n\f\n ", "pdf", "v", "u")) == []

def test_tokenizer_applies_nfkc_and_ligatures():             # Review Focus 5
    assert tokenize("Speciﬁc § 1026.18 Rules") == ["specific", "1026", "18", "rules"]

def test_bm25_deterministic_and_tiebreak():
    idx = BM25Index(); idx.build(TWO_IDENTICAL_CHUNKS)
    r = idx.search("refund policy", k=10)
    assert r == idx.search("refund policy", k=10) and [c for c, _ in r] == sorted(c for c, _ in r)

def test_bm25_all_stopwords_returns_empty():                 # Review Focus 4
    idx = BM25Index(); idx.build(SOME_CHUNKS); assert idx.search("the of and", k=10) == []
```

- [ ] **Step 2: Run** `pytest tests/test_chunker.py tests/test_lexical.py -v` → FAIL.
- [ ] **Step 3: Implement** `chunker.py` and `lexical.py` (`bm25s.BM25(k1=1.2, b=0.75)` over pre-tokenized lists from `tokenize`).
- [ ] **Step 4: Run** the tests → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(eval): structure-free chunker and deterministic BM25 index"`

---

### Task 6: Dense index, fusion and the hybrid index with fingerprint

**Files:**
- Create: `src/adr_eval/retrieval/dense.py`, `src/adr_eval/retrieval/fusion.py`, `src/adr_eval/retrieval/index.py`
- Test: `tests/test_fusion.py`, `tests/test_dense.py` (marked `@pytest.mark.slow`, downloads the model once; CI runs it), `tests/test_index.py`

**Interfaces:**
- Consumes: Task 5 `Chunk`, `chunk_document`, `BM25Index`, `CHUNKER_CONFIG`, `TOKENIZER_CONFIG`; Task 3 `LoadedCorpus`, `EXTRACTOR_VERSION`; Task 2 `Cache` not used here (embeddings cached on disk as `.npy` keyed by chunk text SHA-256 under `.cache/emb/`).
- Produces:
  - `class DenseIndex`: `__init__(self, model_name: str = "BAAI/bge-small-en-v1.5", cache_dir: Path = Path(".cache/emb"))`; `build(self, chunks: list[Chunk]) -> None`; `search(self, query: str, k: int = 100) -> list[tuple[str, float]]` (exact cosine on L2-normalized float32 vectors, rounded 6 dp, sorted `(-score, chunk_id)`); `model_hash(self) -> str` (SHA-256 of the ONNX file). Use `fastembed.TextEmbedding(model_name, threads=1)`, `query_embed` for queries and `passage_embed` for chunks.
  - `def rank(scores: dict[str, float], top: int) -> list[tuple[str, float]]` (round 6 dp, sort `(-score, chunk_id)`).
  - `def rrf(lists: list[list[tuple[str, float]]], k: int = 60, top: int = 10) -> list[tuple[str, float]]` (score = Σ 1/(k + rank), rank from 1).
  - `def minmax(lst: list[tuple[str, float]]) -> dict[str, float]` (all 0.0 when max == min or list empty).
  - `def linear(lex: list[tuple[str, float]], dense: list[tuple[str, float]], w: float, top: int = 10) -> list[tuple[str, float]]` (score = w·lex + (1−w)·dense over the union; missing = 0).
  - `def tune_linear_weight(queries: list[tuple[list, list, Callable[[list[str]], float]]]) -> float` (grid 0.00..1.00 step 0.05; objective mean nDCG@10 via the per-query callable; ties → smallest w).
  - `class HybridIndex`: `@classmethod build(cls, corpus: LoadedCorpus) -> "HybridIndex"`; `chunks: dict[str, Chunk]`; `fingerprint: str` (SHA-256 of canonical JSON of `{snapshot, EXTRACTOR_VERSION, CHUNKER_CONFIG, TOKENIZER_CONFIG, bm25.config(), dense.model_hash(), sorted chunk_ids}`); `retrieve(self, query: str, system: Literal["baseline-rrf","baseline-linear"], w: float | None = None, top: int = 10) -> list[tuple[str, float]]` (each channel top 100, then fuse); `save(self, dir: Path)`, `@classmethod load(cls, dir: Path) -> "HybridIndex"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_rrf_known_values():
    assert rrf([[("a", 9), ("b", 1)], [("b", 5), ("c", 4)]], k=60, top=3)[0][0] == "b"

def test_linear_falls_back_to_dense_when_lexical_empty():   # Review Focus 4
    assert [c for c, _ in linear([], [("x", .9), ("y", .1)], w=0.5)] == ["x", "y"]

def test_rank_tiebreak_by_chunk_id():
    assert [c for c, _ in rank({"b": 0.3333334, "a": 0.3333333}, 2)] == ["a", "b"]  # equal after rounding

def test_tune_weight_picks_smallest_on_tie(): ...  # flat objective → 0.0

@pytest.mark.slow
def test_hybrid_rebuild_same_fingerprint_and_results(mini_loaded):
    a, b = HybridIndex.build(mini_loaded), HybridIndex.build(mini_loaded)
    assert a.fingerprint == b.fingerprint
    assert a.retrieve("refund deadline", "baseline-rrf") == b.retrieve("refund deadline", "baseline-rrf")

@pytest.mark.slow
def test_save_load_roundtrip(tmp_path, mini_loaded): ...  # loaded index returns identical results
```

- [ ] **Step 2: Run** `pytest tests/test_fusion.py tests/test_index.py -v` → FAIL.
- [ ] **Step 3: Implement** `dense.py`, `fusion.py`, `index.py` (save: `chunks.jsonl`, BM25 via `bm25s` save, `dense.npy`, `meta.json` with fingerprint).
- [ ] **Step 4: Run** `pytest tests/test_fusion.py tests/test_dense.py tests/test_index.py -v` → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(eval): exact dense index, RRF/linear fusion and fingerprinted hybrid index"`

---

### Task 7: Golden-set verifiers, splits and rarity

**Files:**
- Create: `src/adr_eval/golden/__init__.py`, `src/adr_eval/golden/verify.py`, `tests/fixtures/mini/golden.jsonl` (6–10 hand-checked items covering every qtype, including one `insufficient` and one `policy_asof`)
- Test: `tests/test_verify.py`

**Interfaces:**
- Consumes: Task 1 models; Task 3 `LoadedCorpus`, `Document`; Task 5 `tokenize`.
- Produces:
  - `def normalize_ws(s: str) -> str` (NFKC, curly quotes → straight, NBSP and all whitespace runs → single space, strip).
  - `def find_quote(text: str, quote: str) -> tuple[int, int] | None`: match after `normalize_ws` on both, mapping back to original offsets via a char index map built while normalizing; returns the **first** occurrence.
  - `def count_quote(text: str, quote: str) -> int`.
  - `def check_spans(item: GoldenItem, docs: dict[str, Document]) -> bool` (every evidence `normalize_ws(text[s:e]) == normalize_ws(quote)`).
  - `def jaccard(a: str, b: str) -> float` over `set(tokenize(...))`; `def dedup(items: list[GoldenItem], threshold: float = 0.8) -> tuple[list[GoldenItem], list[GoldenItem]]` (keep first by `id` order).
  - `def assign_split(item_id: str, seed: int = 20261108) -> Literal["dev","test"]` (`int(sha256(f"{seed}:{item_id}"), 16) % 100 < 20` → `dev`).
  - `def doc_frequency(term: str, docs: dict[str, Document]) -> int` (documents containing the normalized term as a token sequence).
  - `def assign_rarity(items: list[GoldenItem], dfs: dict[str, int]) -> list[GoldenItem]` (`dfs` maps item id → key-entity df; tertile cut points from the corpus's item dfs; ≤ lower third → `tail`, ≥ upper third → `head`).
  - `def verify_items(items: list[GoldenItem], corpus: LoadedCorpus) -> tuple[list[GoldenItem], list[GoldenItem]]` (re-runs span, snapshot match and schema checks; failing items get `status="rejected"`, `reject_reason`).

- [ ] **Step 1: Write the failing tests**

```python
def test_find_quote_with_nbsp_and_curly_quotes():          # Review Focus 5
    text = "The “refund” period is 30 days."
    s, e = find_quote(text, '"refund" period is 30 days')
    assert normalize_ws(text[s:e]) == normalize_ws('"refund" period is 30 days')

def test_find_quote_returns_first_of_duplicates():          # Review Focus 1
    text = "X applies. Y. X applies."
    assert find_quote(text, "X applies") == (0, 9) and count_quote(text, "X applies") == 2

def test_split_is_stable_and_about_20_percent():
    s = [assign_split(f"i{n}") for n in range(2000)]
    assert s == [assign_split(f"i{n}") for n in range(2000)] and 0.17 < s.count("dev") / 2000 < 0.23

def test_dedup_drops_near_duplicates():
    kept, dropped = dedup([q("What is the refund window?"), q("What is the refund window ?")])
    assert len(kept) == 1 and len(dropped) == 1

def test_mini_golden_all_verify(mini_loaded):
    ok, bad = verify_items(load_items(MINI/"golden.jsonl"), mini_loaded); assert bad == []

def test_snapshot_mismatch_rejects(mini_loaded): ...  # item.snapshot altered → rejected with reason "snapshot"
```

- [ ] **Step 2: Run** `pytest tests/test_verify.py -v` → FAIL.
- [ ] **Step 3: Implement** `verify.py`; write `tests/fixtures/mini/golden.jsonl` by hand with real offsets.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(eval): golden verifiers, deterministic splits and rarity tertiles"`

---

### Task 8: Golden-set generators and `gold_query` execution

**Files:**
- Create: `src/adr_eval/golden/records.py`, `src/adr_eval/golden/generate.py`, `src/adr_eval/golden/prompts/{extractive,count_filter,policy_asof,insufficient,evidence_only}.txt`
- Test: `tests/test_records.py`, `tests/test_generate.py` (all with `StubClient`)

**Interfaces:**
- Consumes: Task 1 models; Task 2 `ModelClient`, `parse_json`, `ModelOutputError`; Task 3 `LoadedCorpus`, `CorpusAdapter`; Task 7 verifiers.
- Produces:
  - Filter grammar in `records.py`: key `field` = equality; `field__in` (list), `field__gte`, `field__lte`, `field__contains` (case-insensitive substring; for list fields, membership).
  - `def filter_records(records: list[dict], filters: dict) -> list[dict]`
  - `def exec_gold_query(q: GoldQuery, records: list[dict]) -> int | list[str] | str | None`: `count` → `len(filtered)`; `list` → sorted unique `id`s; `lookup` → the single matching record's field named by `filters["_field"]` (None if 0 or >1 match); other ops → None.
  - `def prompt_hash(name: str) -> str` (SHA-256 of the prompt file bytes).
  - `def gen_extractive(qtype: Literal["factoid","id_lookup","procedure","overview"], corpus: LoadedCorpus, client: ModelClient, n: int, rng: random.Random) -> list[GoldenItem]`: sample sections (chunks from Task 5, ≥80 tokens, from non-empty docs) uniformly by seeded rng; prompt asks for JSON `{question, answer_kind, answer, accepted_variants, quote, key_entity, gold_query}`; locate quote with `find_quote`; skip when not found or when `count_quote(text, quote) > 1` (ambiguous span).
  - `def gen_count_filter(corpus: LoadedCorpus, adapter: CorpusAdapter, client: ModelClient, n: int, rng: random.Random) -> list[GoldenItem]`: code samples a filter (1–2 fields, values drawn from existing rows) and an op (`count` or `list`, list only if ≤ 25 results); computes the answer with `exec_gold_query`; LLM only phrases the question; evidence = the matching records' source spans (each row's `_doc_id` and the span of its serialized record in the extracted text).
  - `def gen_policy_asof(corpus: LoadedCorpus, adapter: CorpusAdapter, client: ModelClient, n: int, rng: random.Random) -> list[GoldenItem]`: from `version_pairs`, ask for one question whose answer differs between versions, returning `{question, answer_old, quote_old, answer_new, quote_new}`; emit **two** items (`as_of` = each version's date) sharing a stem id suffix `-a`/`-b`; each quote must be found in its own version and not in the other.
  - `def gen_insufficient(corpus: LoadedCorpus, client: ModelClient, n: int, rng: random.Random) -> list[GoldenItem]`: LLM proposes a plausible but absent entity/fact for a sampled section's topic (`{question, absent_term}`); keep only if `doc_frequency(absent_term) == 0`; answer `abstain`, `gold_query.op = "abstain"`.
  - `def evidence_only_check(item: GoldenItem, corpus: LoadedCorpus, client: ModelClient) -> bool`: answer the question from the cited evidence text only; compare with `scoring.exact` (Task 10) for non-text kinds and normalized containment for text.
  - `def generate_corpus(corpus_name: str, client: ModelClient, per_type: int = 50, seed: int = 20261108) -> tuple[list[GoldenItem], list[GoldenItem]]`: run all generators, assign ids `<corpus>-<qtype>-<NNN>`, run `dedup`, `evidence_only_check`, `exec_gold_query` where `store == "typed_db"`, `assign_split`, `assign_rarity` (dfs from `key_entity`), set `checks` and `status`; return (accepted, rejected). For `bench`, also convert `native_items()` into items with `provenance.model = "native"` and `qtype` mapped per `corpora/bench/README.md`.
- Note: `generate_corpus` imports `scoring.exact` from Task 10; implement Task 10 before running real generation (tests here stub the comparison through `client` responses that already match).

- [ ] **Step 1: Write the failing tests**

```python
def test_exec_count_and_list():
    rows = [{"id": "a", "year": 2024, "type": "Rule"}, {"id": "b", "year": 2025, "type": "Rule"}]
    assert exec_gold_query(GoldQuery(store="typed_db", op="count", filters={"type": "Rule", "year__gte": 2025}), rows) == 1
    assert exec_gold_query(GoldQuery(store="typed_db", op="list", filters={"type": "Rule"}), rows) == ["a", "b"]

def test_count_filter_answer_is_code_computed(mini_loaded):
    items = gen_count_filter(mini_loaded, MINI_ADAPTER, StubClient(lambda s, u, r: '{"question": "How many rules?"}'), 3, random.Random(1))
    assert all(i.answer.value == exec_gold_query(i.gold_query, MINI_ADAPTER.records(mini_loaded)) for i in items)

def test_extractive_rejects_unfound_quote(mini_loaded):
    stub = StubClient(lambda s, u, r: json.dumps({**GOOD, "quote": "not in the text"}))
    assert gen_extractive("factoid", mini_loaded, stub, 3, random.Random(1)) == []

def test_extractive_rejects_ambiguous_quote(mini_loaded):      # Review Focus 1
    stub = StubClient(lambda s, u, r: json.dumps({**GOOD, "quote": REPEATED_PHRASE}))
    assert gen_extractive("factoid", mini_loaded, stub, 3, random.Random(1)) == []

def test_policy_asof_emits_pair_with_dates(mini_loaded): ...   # two items, as_of differ, answers differ

def test_insufficient_requires_zero_df(mini_loaded): ...       # stub proposes a term present in corpus → no item

def test_generation_is_reproducible(mini_loaded):
    a = generate_corpus("mini", STUB, per_type=2); b = generate_corpus("mini", STUB, per_type=2)
    assert [i.model_dump() for i in a[0]] == [i.model_dump() for i in b[0]]  # created timestamp fixed from seed
```

(`Provenance.created` for generated items is the corpus manifest's `version` date at 00:00 UTC so regeneration is byte-identical.)

- [ ] **Step 2: Run** `pytest tests/test_records.py tests/test_generate.py -v` → FAIL.
- [ ] **Step 3: Implement** `records.py`, `generate.py` and the prompts (each prompt instructs JSON-only output with the exact keys above and verbatim quotes).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(eval): code-verified golden generators and gold_query execution"`

---

### Task 9: Answerer and zero-shot query generation (G2 baseline)

**Files:**
- Create: `src/adr_eval/answer/__init__.py`, `src/adr_eval/answer/answerer.py`, `src/adr_eval/answer/query_gen.py`, `src/adr_eval/answer/prompts/{answer,query_gen}.txt`
- Test: `tests/test_answerer.py`, `tests/test_query_gen.py`

**Interfaces:**
- Consumes: Task 2 `ModelClient`, `Completion`, `parse_json`, `ModelOutputError`; Task 5 `Chunk`; Task 1 `GoldQuery`.
- Produces:
  - `@dataclass class SystemAnswer`: `value: str | float | list[str] | None, kind: AnswerKind, citations: list[str], abstain: bool, confidence: float, completion: Completion`
  - `def answer_question(question: str, as_of: date | None, chunks: list[Chunk], client: ModelClient, repeat: int = 0) -> SystemAnswer`: passages formatted as `[<chunk_id>]\n<text>` in retrieval order; output JSON `{answer, kind, citations, abstain, confidence}`; citations not among the given chunk IDs are dropped; `abstain == True` forces `value = None`, `kind = "abstain"`; `max_tokens = 800`.
  - `def generate_query(question: str, as_of: date | None, record_schema: dict[str, str], client: ModelClient, repeat: int = 0) -> tuple[GoldQuery | None, Completion]` (invalid JSON or schema → `None`, completion still returned for cost accounting); `max_tokens = 400`.

- [ ] **Step 1: Write the failing tests**

```python
def test_answer_parses_and_filters_unknown_citations():
    stub = StubClient(lambda s, u, r: '{"answer": "30 days", "kind": "text", "citations": ["c1", "zz"], "abstain": false, "confidence": 0.8}')
    a = answer_question("q", None, [CHUNK_C1], stub); assert a.citations == ["c1"] and a.value == "30 days"

def test_abstain_forces_none():
    stub = StubClient(lambda s, u, r: '{"answer": "x", "kind": "text", "citations": [], "abstain": true, "confidence": 0.1}')
    a = answer_question("q", None, [], stub); assert a.value is None and a.kind == "abstain"

def test_invalid_json_raises_model_output_error():          # Review Focus 2
    with pytest.raises(ModelOutputError): answer_question("q", None, [], StubClient(lambda s, u, r: "Sure! The answer is"))

def test_query_gen_returns_none_on_bad_schema():
    q, c = generate_query("How many?", None, {"type": "str"}, StubClient(lambda s, u, r: '{"store": "nosuch"}'))
    assert q is None and c.output_tokens >= 0
```

- [ ] **Step 2: Run** `pytest tests/test_answerer.py tests/test_query_gen.py -v` → FAIL.
- [ ] **Step 3: Implement** both modules and prompts (answer prompt: answer only from passages, cite chunk IDs, abstain if the passages do not contain the answer, honour `as_of` when given).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(eval): passage-grounded answerer and zero-shot query generation"`

---

### Task 10: Exact scorers, outcomes, retrieval, compile and determinism metrics

**Files:**
- Create: `src/adr_eval/scoring/__init__.py`, `src/adr_eval/scoring/exact.py`, `src/adr_eval/scoring/outcomes.py`, `src/adr_eval/scoring/retrieval_metrics.py`, `src/adr_eval/scoring/compile_metrics.py`, `src/adr_eval/scoring/determinism.py`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Consumes: Task 1 models; Task 5 `Chunk`; Task 9 `SystemAnswer`.
- Produces:
  - `Outcome = Literal["correct","partial","wrong","abstained","error"]`
  - `def normalize_value(s: str) -> str` (NFKC, lowercase, strip punctuation at ends, collapse whitespace); `def parse_number(s: str | float) -> float | None` (strips thousands separators, `%`, `$`, and units from a small table: days, months, years, percent).
  - `def set_prf(gold: set[str], pred: set[str]) -> tuple[float, float, float]` (both empty → (1,1,1)).
  - `def exact_outcome(gold: Answer, pred: SystemAnswer) -> Outcome | None`: `None` for `text` (needs judge); `abstain` gold → `correct` iff `pred.abstain`; pred abstains on answerable → `abstained`; `number` equal within 1e-9 relative; `id` normalized equality against value or variants; `set` correct only on exact set match.
  - `def penalised_score(outcomes: list[Outcome], t: float) -> float` (mean; `partial` and `wrong` = −t/(1−t); `error` excluded from the mean and counted separately by the report).
  - `def overlap(chunk: Chunk, ev: Evidence) -> float` (|chunk∩ev| / |ev| on the same `doc_id`, else 0).
  - `def recall_at_k(ranked: list[Chunk], evidence: list[Evidence], k: int = 10) -> float` (share of evidence spans overlapped by any of top k); `def mrr(...) -> float` (first chunk with overlap > 0); `def ndcg_at_k(ranked, evidence, k=10) -> float` (gain = max overlap with any evidence span; ideal = sorted gains of the best possible chunks, capped at len(evidence) gains of 1.0); `def full_coverage(ranked, evidence, k=10) -> bool`.
  - `def citation_precision(cited: list[Chunk], evidence: list[Evidence]) -> float | None` (None if nothing cited); `def evidence_cited(cited, evidence) -> bool`.
  - `def span_containment(items: list[GoldenItem], chunks_by_doc: dict[str, list[Chunk]]) -> float` (share of evidence spans fully inside one chunk); `def text_fidelity(corpus: LoadedCorpus) -> dict` (for `md`/`txt`/`csv`: extracted text == decoded bytes → share; other formats reported as `"n/a"`).
  - `def retrieval_identity_rate(runs: dict[str, list[list[str]]]) -> float` (item → per-repeat ranked IDs; share of items with all repeats identical); `def answer_agreement(runs: dict[str, list[str]]) -> float` (mean pairwise agreement of normalized answers); `def pass_hat_k(outcomes: dict[str, list[Outcome]]) -> float` (share of items with all repeats `correct`).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("t,expected", [(0.5, (1 + 0 - 1) / 3), (0.75, (1 + 0 - 3) / 3), (0.9, (1 + 0 - 9) / 3)])
def test_penalised_score(t, expected):
    assert penalised_score(["correct", "abstained", "wrong"], t) == pytest.approx(expected)

def test_partial_counts_as_wrong_and_error_excluded():
    assert penalised_score(["correct", "partial", "error"], 0.5) == pytest.approx(0.0)

def test_number_parse_with_units():
    assert parse_number("1,234 days") == 1234.0 and parse_number("12.5%") == 12.5

def test_set_exact_and_prf():
    assert set_prf({"a", "b"}, {"a"}) == (1.0, 0.5, pytest.approx(2 / 3))

def test_abstain_gold_requires_abstention():
    assert exact_outcome(Answer(kind="abstain", value=None), sa(abstain=True)) == "correct"
    assert exact_outcome(Answer(kind="abstain", value=None), sa(value="x")) == "wrong"

def test_ndcg_perfect_is_one_and_recall_partial():
    assert ndcg_at_k([C_FULL], [EV], 10) == pytest.approx(1.0)
    assert recall_at_k([C_FULL], [EV, EV_OTHER], 10) == 0.5

def test_retrieval_identity_rate():
    assert retrieval_identity_rate({"i": [["a", "b"]] * 5, "j": [["a"], ["b"], ["a"], ["a"], ["a"]]}) == 0.5
```

- [ ] **Step 2: Run** `pytest tests/test_scoring.py -v` → FAIL.
- [ ] **Step 3: Implement** the five modules.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(eval): exact, abstention-aware, retrieval, compile and determinism metrics"`

---

### Task 11: Judge, agreement and paired statistics

**Files:**
- Create: `src/adr_eval/scoring/judge.py`, `src/adr_eval/scoring/stats.py`, `src/adr_eval/scoring/prompts/judge.txt`
- Test: `tests/test_judge.py`, `tests/test_stats.py`

**Interfaces:**
- Consumes: Task 2 `ModelClient`, `parse_json`, `ModelOutputError`; Task 1 `Answer`; Task 10 `Outcome`.
- Produces:
  - `JudgeLabel = Literal["correct","partial","incorrect"]`
  - `class Judge`: `__init__(self, client: ModelClient)`; `judge(self, question: str, gold: Answer, candidate: str, repeat: int = 0) -> tuple[JudgeLabel, str, Completion]` (JSON `{label, reason}`; invalid → `ModelOutputError`); `same_family_as(self, generator: ModelClient) -> bool`.
  - `def label_to_outcome(label: JudgeLabel) -> Outcome` (`incorrect` → `wrong`).
  - `def cohen_kappa(a: list[str], b: list[str]) -> float` (1.0 when both constant and equal; raises `ValueError` on length mismatch).
  - `def paired_bootstrap_ci(x: list[float], y: list[float], n: int = 10_000, seed: int = 20261108, alpha: float = 0.05) -> tuple[float, float, float]` (mean of y−x, lower, upper; percentile method; numpy `default_rng(seed)`).
  - `def mcnemar_exact(b: int, c: int) -> float` (two-sided exact binomial p with p=0.5 on b+c discordant pairs; 1.0 when b+c == 0).
  - `def holm(pvals: dict[str, float]) -> dict[str, float]` (adjusted, monotone, capped at 1).

- [ ] **Step 1: Write the failing tests**

```python
def test_kappa_known_value():
    assert cohen_kappa(list("ccwwc"), list("ccwcc")) == pytest.approx(0.5454545, rel=1e-6)

def test_bootstrap_reproducible_and_brackets_mean():
    x, y = [0, 0, 1, 1] * 25, [1, 0, 1, 1] * 25
    r1, r2 = paired_bootstrap_ci(x, y), paired_bootstrap_ci(x, y)
    assert r1 == r2 and r1[1] <= r1[0] <= r1[2] and r1[0] == pytest.approx(0.25)

def test_mcnemar_values():
    assert mcnemar_exact(0, 0) == 1.0 and mcnemar_exact(10, 0) == pytest.approx(2 * 0.5 ** 10)

def test_holm_adjusts_monotonically():
    assert holm({"a": 0.01, "b": 0.04, "c": 0.03}) == pytest.approx({"a": 0.03, "b": 0.06, "c": 0.06})

def test_judge_parses_label_and_flags_family():
    j = Judge(StubClient(lambda s, u, r: '{"label": "partial", "reason": "missing unit"}', family="anthropic"))
    assert j.judge("q", Answer(kind="text", value="30 days"), "30")[0] == "partial"
    assert j.same_family_as(StubClient(lambda *a: "", family="anthropic"))
```

- [ ] **Step 2: Run** `pytest tests/test_judge.py tests/test_stats.py -v` → FAIL.
- [ ] **Step 3: Implement** `judge.py` (judge sees question, gold value and accepted variants, candidate; not passages), `stats.py`, judge prompt.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(eval): pluggable judge, kappa and paired statistics"`

---

### Task 12: Runner, reports and CLI with an end-to-end fixture test

**Files:**
- Create: `src/adr_eval/runner.py`, `src/adr_eval/report.py`, `src/adr_eval/cli.py`, `config/eval.json` (generator model ID, judge adapter config, repeats 5, t values, seed, concurrency 4)
- Test: `tests/test_runner.py`, `tests/test_e2e_mini.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - Result row (one per item × repeat) written to `runs/<run_id>/results.jsonl`: `{item_id, repeat, qtype, rarity, retrieved: [[chunk_id, score]], generated_query, gold_query_field_hits: {store, op, filters, entities, as_of}, query_exact: bool, query_exec_match: bool | None, answer: {...SystemAnswer minus completion}, outcome, judge_label, judge_reason, tokens: {in, out}, cost_usd, latency_s, error: str | None}`
  - `def run(corpus: str, system: Literal["baseline-rrf","baseline-linear"], split: Literal["dev","test"], repeats: int, config: dict, out_root: Path = Path("runs"), max_dollars: float | None = None, dry_run: bool = False) -> str` (returns `run_id = f"{corpus}-{system}-{split}-{UTC %Y%m%dT%H%M%S}"`). Items are processed by a thread pool of `config["concurrency"]` workers (default 4); rows are written sorted by `(item_id, repeat)` so output order is deterministic. Steps: load corpus and golden items (refuse on snapshot mismatch), load or build the index (refuse if fingerprint differs from a saved one without `--rebuild`), for `baseline-linear` tune `w` on `dev` and record it, then for each item and repeat: retrieve → generate_query → answer → exact or judge outcome; also judge non-text items once each (for proxy κ) and text items twice (self-consistency). Writes `config.json` (model IDs, prompt hashes, snapshot, fingerprint, seed, price-table date, `w`, `same_family_judge` flag) before the first item.
  - Budget: before each model call, if `spent + estimate > max_dollars`, stop, write `status: "stopped_budget"` to `config.json`, and leave rows written so far. `dry_run` prints estimated calls, tokens and dollars (estimates: prompt length/4 tokens in, `max_tokens` out) and makes no calls.
  - Errors: `ModelError`/`ModelOutputError` on an item → row with `outcome: "error"`, `error: <message>`; the run continues.
  - `def build_report(run_dir: Path) -> dict` (all tracks: G1 span containment, text fidelity, empty docs, fingerprint; G2 per-field accuracy, exact, exec match; G3 Recall@10, nDCG@10, MRR, full coverage by rarity × qtype, excluding `insufficient` items; determinism identity rate, answer agreement, pass^5; end-to-end accuracy, error, abstention, partial rates, penalised score at each t, citation precision and evidence-cited rate, tokens, dollars, latency p50/p95, error count; judge proxy κ, self-consistency, `human_kappa: null`, same-family warning). Retrieval identity < 1.0 sets `determinism_violation: true`.
  - `def render_markdown(report: dict) -> str`; `def compare(run_a: Path, run_b: Path) -> dict` (paired over shared `(item_id, repeat=0)`: bootstrap CIs for penalised score at t = 0.75, nDCG@10 and Recall@10; McNemar on correct vs not; Holm across the reported metrics).
  - CLI `adr-eval` subcommands exactly as in the spec §9 plus `--rebuild` on `index`/`run`; `main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
def test_e2e_mini_with_stub_model(tmp_path):
    rc = main(["run", "mini", "--system", "baseline-rrf", "--split", "test", "--repeats", "2",
               "--out", str(tmp_path), "--stub"])
    run_dir = next(tmp_path.iterdir()); rep = json.loads((run_dir / "report.json").read_text())
    assert rc == 0 and rep["determinism"]["retrieval_identity_rate"] == 1.0
    assert set(rep["end_to_end"]["penalised"]) == {"0.5", "0.75", "0.9"} and rep["judge"]["human_kappa"] is None

def test_model_error_becomes_error_row(tmp_path):            # Review Focus 2
    run_dir = run_with_stub(tmp_path, fn=lambda s, u, r: "not json")
    rows = [json.loads(l) for l in (run_dir / "results.jsonl").read_text().splitlines()]
    assert rows and all(r["outcome"] == "error" for r in rows)

def test_budget_stop_writes_status(tmp_path):
    cfg = json.loads((run_with_stub(tmp_path, max_dollars=0.0, priced=True) / "config.json").read_text())
    assert cfg["status"] == "stopped_budget"

def test_snapshot_mismatch_refuses(tmp_path): ...            # golden snapshot altered → non-zero exit, message names the file
def test_compare_reports_ci_and_mcnemar(tmp_path): ...       # two stub runs → keys present, p in [0, 1]
```

(`--stub` swaps generator and judge for a deterministic `StubClient` that answers from the mini golden set; it exists for tests and demos and is labelled in `config.json`.)

- [ ] **Step 2: Run** `pytest tests/test_runner.py tests/test_e2e_mini.py -v` → FAIL.
- [ ] **Step 3: Implement** `runner.py`, `report.py`, `cli.py`, `config/eval.json`.
- [ ] **Step 4: Run** `pytest -q && ruff check .` → all PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(eval): runner, reports, comparisons and CLI"`

---

### Task 13: Build golden sets v0.1 and record the baseline

**Files:**
- Create: `golden/{gov,research,bench}/v0.1/items.jsonl`, `golden/*/v0.1/rejected.jsonl`, `results/<run_id>/{config.json,report.json,report.md}`, `results/README.md`
- Modify: `README.md` (add "Evaluation harness" section: install, fetch, golden, index, run, report commands and where results live)

**Interfaces:**
- Consumes: the CLI from Task 12.

- [ ] **Step 1: Request the API key.** Ask the user (via the secure credential form for host `api.anthropic.com`, header `x-api-key`) for the Anthropic key; never in chat. Confirm `config/eval.json` and `config/prices.json` name the pinned Claude model ID.
- [ ] **Step 2: Fetch and index.** Run `adr-eval fetch gov && adr-eval index gov` (then `research`, `bench`). Expected: no hash mismatches; index fingerprints printed; `empty_docs` counts printed.
- [ ] **Step 3: Generate and verify golden sets.** Run `adr-eval golden <corpus> --gen` then `--verify` for each corpus. Expected: `--verify` reports 0 failures on `items.jsonl`; per-type counts ≤ 50; tail share printed (shortfalls below 30% reported, not padded).
- [ ] **Step 4: Dry-run cost.** `adr-eval run gov --system baseline-rrf --split test --repeats 5 --dry-run` for each corpus and system; show the estimates to the user and agree a `--max-dollars` before spending.
- [ ] **Step 5: Record baselines.** Run both systems on `test` for all three corpora with `--repeats 5 --max-dollars <agreed>`. Expected: retrieval identity rate 1.0 on every run; reports written.
- [ ] **Step 6: Compare.** `adr-eval report <rrf_run> --compare <linear_run>` per corpus; copy `config.json`, `report.json`, `report.md` of each run into `results/` and summarise in `results/README.md` (headline numbers per track and the open exit items: human κ, cross-family judge, human-vetted items).
- [ ] **Step 7: Commit** `git add golden results README.md && git commit -m "eval: golden sets v0.1 and recorded flat hybrid baselines"`

---

### Task 14: Claude Code adapter, provider profiles and `doctor` (added 2026-11-09, runs before Task 13)

Added with the user's approval: no provider API key is available yet (expected in ~3 weeks); the user has a Claude subscription. Headless `claude -p` works in this environment and is billed to the subscription.

**Files:**
- Modify: `src/adr_eval/llm.py` (add `ClaudeCodeClient`, `RateLimitedError` handling), `src/adr_eval/runner.py` (profile-based client construction, `--max-calls`), `src/adr_eval/cli.py` (`--generator`, `--judge`, `--max-calls`, `doctor` subcommand), `config/eval.json` (generator/judge become profile names)
- Create: `config/models.json`, `docs/eval/providers.md`
- Test: `tests/test_claude_code_client.py`, `tests/test_profiles.py`, additions to `tests/test_runner.py`

**Interfaces:**
- `class ClaudeCodeClient(model: str, cache: Cache, max_retries: int = 5, binary: str = "claude", runner: Callable[[list[str], str, float], subprocess.CompletedProcess] | None = None)`, `family = "anthropic"`, `name = "claude_code"`. `complete(system, user, *, max_tokens, repeat=0) -> Completion`. Runs `[binary, "-p", "--model", model, "--output-format", "json", "--max-turns", "1", "--system-prompt", system, "--tools", ""]` (if the installed CLI rejects `--tools ""`, use the flag it supports for disabling all tools, verified with `claude --help`) with `user` on stdin, timeout 300 s. Parses the JSON envelope: text = `result`; `input_tokens`/`output_tokens` from `usage`; `latency_s` measured; `model` = the requested model string. Non-zero exit, `is_error: true`, missing `result`, or a timeout → retry per the existing policy; text matching a usage-limit message (case-insensitive "limit" together with "reset" or "usage") → wait with backoff 60, 120, 240, 480, 900 s (injectable sleep) then retry; after retries raise `ModelError`. Cache key = `Cache.key("claude_code", model, system, user, max_tokens, repeat)`. Cost: `cost_usd` returns 0.0 for completions whose model is billed by subscription (price-table entry `{"billing": "subscription"}` for `claude_code:*`); the CLI's `total_cost_usd` is stored on the row as `notional_cost_usd`.
- `config/models.json`: `{"profiles": {"claude_code_sonnet": {"adapter": "claude_code", "model": "sonnet"}, "claude_code_opus": {...,"model": "opus"}, "claude_code_haiku": {...}, "anthropic_sonnet": {"adapter": "anthropic", "model": "claude-sonnet-5-5", "api_key_env": "ANTHROPIC_API_KEY"}, "openai": {"adapter": "openai_compatible", "base_url": "https://api.openai.com/v1", "model": "<set when key arrives>", "api_key_env": "OPENAI_API_KEY", "family": "openai"}, "gemini": {"adapter": "openai_compatible", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "<set>", "api_key_env": "GEMINI_API_KEY", "family": "google"}, "deepseek": {...}, "openrouter": {...}, "selfhost": {"adapter": "openai_compatible", "base_url": "http://localhost:8000/v1", "model": "<set>", "api_key_env": "SELFHOST_API_KEY", "family": "selfhost"}}, "stub": {...}}`. A profile whose `model` is a `<set...>` placeholder is reported unconfigured.
- `def load_profiles(path: Path = Path("config/models.json")) -> dict[str, dict]`; `def make_client(profile_name: str, profiles: dict, cache: Cache) -> ModelClient` (raises `ValueError` naming the profile and the missing env var or placeholder model).
- `config/eval.json`: `"generator": "claude_code_sonnet"`, `"judge": "claude_code_opus"` (profile names).
- Runner records in `config.json`: generator/judge profile names, adapters, models, families, `"billing"` per client (`"subscription"` or `"api"`), and `same_family_judge`.
- CLI: `adr-eval run|golden ... --generator <profile> --judge <profile> --max-calls N`; `adr-eval doctor [--live]` prints one line per profile: `ok`, `missing key <ENV>`, `placeholder model`, or (with `--live`) the result of a 1-token test call.
- `--max-calls N`: stops before the call that would exceed N model calls (cache hits do not count), writing `status: "stopped_calls"`.

- [ ] **Step 1:** Write failing tests (all with an injected fake `runner`, no real `claude` process): JSON envelope parsing; retry on non-zero exit then success; usage-limit text triggers the long backoff (sleep patched) then success; cache hit avoids a second subprocess call; `repeat` changes the key; cost 0.0 with subscription billing; `make_client` errors for a missing env var and for a placeholder model; `doctor` output for a mix of profiles (env patched); runner `--max-calls` stop status; config.json billing/family fields.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the full suite and ruff → PASS. Then one live smoke check outside pytest: `adr-eval doctor --live` must report `claude_code_haiku: ok`.
- [ ] **Step 5:** Write `docs/eval/providers.md`: how each profile works; what to do when a key arrives (add it via the environment's secure credential form, set the profile's model, run `adr-eval doctor --live`, then re-judge an existing run with `--judge <profile>`; generator calls come from cache); usage-limit behaviour and resuming; why the same-family judge flag matters. Commit.
