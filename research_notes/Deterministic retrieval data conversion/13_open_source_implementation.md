# Practical Implementation: Open-Source Frameworks and Engineering Case Studies for Document-to-Database Pipelines that Agents Query Deterministically

Scope note: this track covers open-source building blocks, reference architectures and company engineering write-ups. "Deterministic retrieval" = same query + same data snapshot -> same exact rows, via exact predicates over typed records, with each value traceable to source spans. Research date: 2026-11-06. Older items are marked with their year. Vendor and marketing claims are flagged as such. Some primary sources could not be fetched (Medium-hosted Pinterest and Alan posts, DoorDash careers blog, Instacart tech blog, Swiggy Bytes, all returned 403/503). In those cases a secondary summary was read and is labelled as secondary.

Main finding across all sections: LLM extraction is not deterministic even at temperature 0, so determinism cannot come from the extractor. It has to come from freezing extraction outputs. That means content-addressed caching keyed on (document hash, schema, prompt, model) and materializing results into typed, versioned tables. Agents then query a pinned snapshot through parameterized or read-only tools. The teams with the most reliable results (Uber Finch, Grab Data-Arks, dbt's semantic-layer benchmark) narrowed what the agent can express at query time rather than trusting free-form generation.

## 1. Open-source frameworks for extraction-to-database: maturity, license, determinism features

### Takeaway
A practical open-source stack splits into three layers:
- **Parsing.** Docling (MIT, LF AI & Data) is the strongest default. Its typed document model carries page/bbox/charspan provenance and a source binary hash. Unstructured (Apache-2.0) has deterministic SHA-256 element IDs. Marker and MinerU are capable but carry licence strings: Marker's model weights are OpenRAIL-M, and MinerU adds commercial thresholds on top of Apache-2.0.
- **Schema-constrained extraction.** Use provider strict structured outputs, or Outlines/vLLM for self-hosted models. Wrap them with Instructor, Pydantic AI or BAML for validation and retries. LangExtract (Apache-2.0) is the clearest option for character-level source grounding.
- **Declarative and batch pipelines.** DocETL (MIT), Sycamore (Apache-2.0) and CocoIndex (Apache-2.0) cover this layer. CocoIndex has the most rigorous incremental memoization.

None of these make the LLM itself deterministic. Their determinism features are caches, versioned schemas, stable IDs and provenance.

### Cited Findings

**Parsing layer**
- Docling is "an easy to use, self-contained, MIT-licensed open-source package for PDF document conversion" powered by DocLayNet layout analysis and TableFormer table-structure models, and it runs on commodity hardware (2024 tech report). — [Docling Technical Report (arXiv 2408.09869)](https://arxiv.org/abs/2408.09869)
- Docling 2026 docs list:
  - inputs: PDF, DOCX/PPTX/XLSX, HTML, EPUB, audio, email, images, LaTeX, XBRL, JATS and USPTO XML;
  - exports: Markdown, HTML, DocTags and lossless JSON;
  - deployment: OCR, VLM support (GraniteDocling), local/air-gapped running, a CLI, docling-serve, and an MCP server for agents;
  - integrations: LangChain, LlamaIndex, CrewAI and Haystack;
  - status: hosted by LF AI & Data, MIT licence. — [Docling docs](https://docling-project.github.io/docling/); license file — [docling repo](https://github.com/docling-project/docling)
- DoclingDocument (Docling v2) is a Pydantic type:
  - content lists: `texts`, `tables`, `pictures` and `key_value_items`;
  - tree roots: `body` (reading order) and `furniture` (headers and footers);
  - references: JSON-pointer refs such as `#/texts/1`. — [DoclingDocument concept](https://docling-project.github.io/docling/concepts/docling_document/)
- Verified in docling-core source:
  - `ProvenanceItem` has `page_no`, `bbox` and `charspan` ("a lightweight pointer back into the original document");
  - `DocumentOrigin` carries `mimetype`, `binary_hash`, `filename` and `uri`;
  - the document has `schema_name="DoclingDocument"` and a `version` field validated against the SDK's `CURRENT_VERSION`. — [docling-core reference.py](https://github.com/docling-project/docling-core/blob/main/docling_core/types/doc/common/reference.py)
- Granite-Docling is an ~258M-parameter Apache-2.0 VLM. It emits DocTags (layout and content markup, convertible via docling-core) and can be run by Docling automatically or via transformers, vLLM, ONNX or MLX. IBM gives no benchmark numbers on that page. — [IBM Granite-Docling docs](https://www.ibm.com/granite/docs/models/docling)
- Unstructured (Apache-2.0):
  - element types include Title, NarrativeText, ListItem, Table, Header, Footer and more;
  - metadata includes `coordinates`, `page_number`, `parent_id`, `languages` and `text_as_html` (tables);
  - **default `element_id` is deterministic**, a SHA-256 of text, position, page number and filename. `unique_element_ids=True` switches to non-deterministic UUIDs. Because the filename is in the hash, the same content in a renamed file gets a different ID. — [Unstructured document elements](https://docs.unstructured.io/open-source/concepts/document-elements); license — [unstructured repo](https://github.com/Unstructured-IO/unstructured)
- Unstructured partition strategies: `auto`, `fast` (rule-based; the page says "~100x faster" than image-to-text models; not for scanned files), `hi_res` (model-based layout, use when element classification matters) and `ocr_only`. — [Unstructured partitioning strategies](https://docs.unstructured.io/open-source/concepts/partitioning-strategies)
- Marker's code is Apache-2.0. Its model weights use a modified OpenRAIL-M licence: free for research, personal use and startups under $5M funding or revenue, with paid licensing beyond that. — [Marker README](https://github.com/datalab-to/marker)
- MinerU is now Apache-2.0 plus additional terms:
  - a separate commercial licence is required above 100M MAU or USD 20M monthly revenue;
  - online services must attribute MinerU;
  - rights terminate automatically on breach. — [MinerU LICENSE.md](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md)
- A survey of document parsing groups the field into modular pipeline systems (layout, OCR, table and formula recognition) and end-to-end VLM parsers. It flags VLM reliability and inference efficiency as open challenges (2024). — [Document Parsing Unveiled (arXiv 2410.21169)](https://arxiv.org/abs/2410.21169)
- OmniDocBench evaluates pipeline and end-to-end VLM parsers across 9 document sources, 19 layout categories and 15 attribute labels. It is the standard harness for choosing a parser per corpus (2024). — [OmniDocBench (arXiv 2412.07626)](https://arxiv.org/abs/2412.07626)

**Schema-constrained extraction layer**
- LangExtract (Google, Apache-2.0, July 2025):
  - maps every extraction to exact character offsets in the source;
  - uses few-shot examples as the schema, with controlled generation on Gemini;
  - handles long documents with chunking, parallel processing and multiple passes for recall;
  - produces a self-contained HTML review UI;
  - supports Ollama and OpenAI providers. — [Google Developers Blog](https://developers.googleblog.com/en/introducing-langextract-a-gemini-powered-information-extraction-library/)
- LangExtract README: "extractions that cannot be located in the source text will have `char_interval = None`. Filter these out ... to keep only grounded results." This is a built-in hallucination filter for span-grounded records. `output_schema` with enums is supported for Gemini and OpenAI. — [LangExtract README](https://github.com/google/langextract)
- LangExtract's approach was first applied to medical extraction: "LLMs Accelerate Annotation for Medical Information Extraction" (2023). — [arXiv 2312.02296](https://arxiv.org/abs/2312.02296)
- Hacker News reaction to LangExtract (166 points, July 2025):
  - one commenter called sub-page citations plus the HTML UI "the holy grail of deterministic text extraction";
  - Simon Willison pointed to his `llm --schema` tool for multi-provider schema extraction;
  - others recommended Unstract (AGPL-3.0) and asked how LangExtract compares with DocETL. — [HN thread 44735059](https://news.ycombinator.com/item?id=44735059); Unstract license — [Unstract repo](https://github.com/Zipstack/unstract)
- Instructor (MIT) has a built-in `cache=` (v1.9.1+) with `AutoCache` (in-memory) or `DiskCache`, plus an optional TTL and namespaces.
  - The cache key is a SHA-256 over client identity, namespace, validation context, strictness, model, messages, mode **and the full `model_json_schema()`**, so any schema change invalidates the cache.
  - A plain `functools.cache` would return stale results after a model change.
  - Cached objects are re-validated on every hit. — [Instructor caching docs](https://python.useinstructor.com/concepts/caching/); license — [instructor repo](https://github.com/567-labs/instructor)
- Pydantic AI (MIT) has three output modes:
  - Tool Output (default): the schema becomes a tool;
  - Native Output: provider structured outputs;
  - Prompted Output: the least reliable mode.
  - Output validators can raise `ModelRetry`. The output retry budget defaults to 1 and is configurable. — [Pydantic AI output docs](https://pydantic.dev/docs/ai/core-concepts/output/); license — [pydantic-ai repo](https://github.com/pydantic/pydantic-ai)
- BAML (Apache-2.0) is a DSL: typed `.baml` functions generate a `baml_client` for Python, TypeScript, Go and Ruby, with JSON repair, retries and a VS Code playground for tests. Note that the page fetched documents "legacy BAML v0", and Schema-Aligned Parsing internals were not described there. — [BAML docs](https://docs.boundaryml.com/guide/introduction/what-is-baml); license — [baml repo](https://github.com/BoundaryML/baml)
- Outlines (Apache-2.0) reformulates generation as finite-state-machine transitions. It guarantees regex, JSON-Schema and CFG conformance with an index over the vocabulary and "little overhead" (2023). — [Efficient Guided Generation (arXiv 2307.09702)](https://arxiv.org/abs/2307.09702)
- Outlines docs claim "guaranteed schema compliance" and list backends: vLLM, Transformers, llama.cpp, OpenAI, Ollama, MLX-LM, SGLang, TGI, Anthropic and Gemini. — [Outlines docs](https://dottxt-ai.github.io/outlines/latest/); license — [outlines repo](https://github.com/dottxt-ai/outlines)
- JSONSchemaBench (10K real-world schemas, 2025) evaluated Guidance, Outlines, llama.cpp, XGrammar, OpenAI and Gemini constrained decoding on efficiency, coverage of schema features and output quality. It found coverage of schema constraint types varies, so "guaranteed compliance" holds only for the supported subset. — [JSONSchemaBench (arXiv 2501.10868)](https://arxiv.org/abs/2501.10868)
- OpenAI Structured Outputs "ensures the model will always generate responses that adhere to your supplied JSON Schema." Refusals and `max_output_tokens` truncation are the edge cases to handle. The first request with a new schema has extra latency. — [OpenAI Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)
- Claude structured outputs (GA) cover JSON outputs via `output_config.format` and strict tool use.
  - Unsupported: recursive schemas, numeric min/max, string length limits, and `additionalProperties` other than false.
  - Caveats: enum casing may differ, so compare case-insensitively; required properties are emitted first; grammars are cached for 24h; changing the schema invalidates the prompt cache; limits of 20 strict tools, 24 optional params and 16 union params; refusals may not match the schema. — [Claude structured outputs docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)

**Declarative and batch pipeline layer**
- DSPy (MIT) compiles declarative LM pipelines and optimizes prompts and demonstrations against a metric (2023). — [DSPy (arXiv 2310.03714)](https://arxiv.org/abs/2310.03714)
- DSPy has two caches on by default: in-memory LRU and on-disk `diskcache.FanoutCache`. Keys combine the canonical request with execution identity such as `rollout_id`, and exclude API keys. `dspy.configure_cache()` controls them, and pickling is restricted by default. — [DSPy cache tutorial](https://dspy.ai/current/tutorials/cache/); license — [dspy repo](https://github.com/stanfordnlp/dspy)
- DocETL (MIT, UC Berkeley):
  - declarative YAML/Python pipelines; an agent-based optimizer rewrites them;
  - outputs were 25–80% more accurate than "well-engineered baselines" on 4 tasks;
  - 1.7k GitHub stars as of March 2025 (2024 paper). — [DocETL (arXiv 2410.12189)](https://arxiv.org/abs/2410.12189); license — [docetl repo](https://github.com/ucbepic/docetl)
- DocETL operators:
  - LLM operators: map, resolve, reduce, filter, equijoin, rank, extract, cluster, link-resolve. Auxiliary: split, gather, unnest, sample, topk, code;
  - typed `output` schemas, Python `validate` expressions and `num_retries_on_validate_failure`;
  - "gleaning" is iterative validator-driven refinement that at least doubles LLM calls;
  - **all LLM calls are cached** under `~/.cache/docetl/llm`;
  - per-operator model choice via LiteLLM. — [DocETL operators](https://ucbepic.github.io/docetl/concepts/operators/)
- DocETL `resolve` performs LLM entity resolution with code-based and embedding blocking:
  - the default blocking threshold is auto-computed to hit `blocking_target_recall` 0.95;
  - Union-Find clustering, with a `compare_batch_size` of 500;
  - an optional cascade sends all pairs to a cheap proxy model and escalates only uncertain ones (label_budget 400). — [DocETL resolve operator](https://ucbepic.github.io/docetl/operators/resolve/)
- Sycamore (Apache-2.0) is a DocSet dataflow engine (Spark/Pandas-like) with lineage and sinks to OpenSearch, Elasticsearch, Weaviate, Pinecone, DuckDB and Qdrant. It uses Aryn DocParse by default, which needs an API key. — [Sycamore docs](https://sycamore.readthedocs.io/en/stable/)
- The Aryn paper describes Sycamore DocSets plus the Luna natural-language planner. It argues an analytics system "must provide explainability to be practical" and reports better accuracy than RAG on NTSB report analytics (2024). — [Aryn design paper (arXiv 2409.00847)](https://arxiv.org/abs/2409.00847)
- Evaporate (Stanford, 2023) generated queryable tables from heterogeneous data lakes in two ways: direct LLM extraction (accurate but costly) and LLM-synthesized extraction code (cheap but less accurate). EVAPORATE-CODE+ ensembles many candidate functions with weak supervision and beat state of the art with **110x fewer LLM tokens** across 16 settings of 10k documents each. — [Evaporate (arXiv 2304.09433)](https://arxiv.org/abs/2304.09433)
- Semantic operators (LOTUS, 2024) formalize LLM filter/join/group-by/top-k with accuracy guarantees relative to a gold algorithm, and report optimizations up to 1,000x. — [Semantic Operators (arXiv 2407.11418)](https://arxiv.org/abs/2407.11418)
- Palimpzest (MIT CSAIL, 2024) cost-optimizes declarative AI queries. It reports plans 3.3x faster and 2.9x cheaper than baseline with better quality, and up to 90.3x speedup at 9.1x lower cost with F1 within 83.5% of a GPT-4 baseline. — [Palimpzest (arXiv 2405.14696)](https://arxiv.org/abs/2405.14696)
- OntoGPT/SPIRES (BSD-style licence) does zero-shot recursive extraction into LinkML schemas and grounds entities to ontology identifiers. Accuracy is "comparable to the mid-range" of relation-extraction methods (2023). — [SPIRES (arXiv 2304.02711)](https://arxiv.org/abs/2304.02711); license — [ontogpt repo](https://github.com/monarch-initiative/ontogpt)
- LlamaExtract is a **proprietary cloud service** on the LlamaParse platform, with tiers Agentic Plus, Agentic, Cost Effective and Turbo, and schema-validated output. The fetched page did not say whether any part is open source. The LlamaIndex core library is MIT. — [LlamaExtract docs](https://developers.llamaindex.ai/python/cloud/llamaextract/getting_started); [llama_index repo](https://github.com/run-llama/llama_index)
- Neo4j GraphRAG KG Builder (`SimpleKGPipeline`, labelled "still experimental"):
  - schema of node, relationship and pattern triplets, with enforcement flags and a pruner;
  - a **lexical graph** of Document and Chunk nodes linked to each extracted entity, which gives provenance;
  - exact, spaCy and RapidFuzz entity resolvers. — [Neo4j KG builder guide](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_kg_builder.html); Neo4j LLM Graph Builder license Apache-2.0 — [llm-graph-builder repo](https://github.com/neo4j-labs/llm-graph-builder)
- Kor (MIT) now warns: "If you're using a chat model that supports a tool calling API, you should probably be using the chat models' tool calling API instead of Kor." It is effectively legacy. — [Kor README](https://github.com/eyurtsev/kor)
- Marvin (Apache-2.0, Prefect) is now built on Pydantic AI for model access. — [Marvin README](https://github.com/PrefectHQ/marvin)
- Other licences verified from LICENSE files: LangChain MIT ([repo](https://github.com/langchain-ai/langchain)); Haystack Apache-2.0 ([repo](https://github.com/deepset-ai/haystack)); dlt Apache-2.0 ([repo](https://github.com/dlt-hub/dlt)); Vanna (text-to-SQL) MIT ([repo](https://github.com/vanna-ai/vanna)); WrenAI multi-licence, with core and sdk Apache-2.0 and other paths CC-BY-4.0/AGPL-3.0 ([repo](https://github.com/Canner/WrenAI)).
- Airbyte's S3 source has a "Document File Type Format" that uses open-source Unstructured to emit **one record per document**: Markdown `content` plus a `document_key` primary key, for md, pdf, docx and pptx. Large files can produce records too large for some destinations. It was added as "experimental" in v4.0.5 (Oct 2023). — [Airbyte S3 source docs](https://docs.airbyte.com/integrations/sources/s3)

### Inferences
- For a deterministic data lake, the parser's most important property is a stable, versioned, provenance-bearing intermediate representation. Docling's `DocumentOrigin.binary_hash` plus `ProvenanceItem(page_no,bbox,charspan)` and Unstructured's hash-based `element_id` satisfy this. Accuracy differences between parsers should be decided per corpus with OmniDocBench-style evaluation.
- Grounding should be double-checked. Constrained decoding guarantees shape, not truth. LangExtract's `char_interval` check, which exact-matches the extracted text back to the source, is a cheap, deterministic post-hoc verifier that any pipeline can replicate: verify `source_text[start:end] == value`.
- Licences matter for an open-source toolkit. MIT/Apache choices (Docling, Unstructured, LangExtract, Instructor, Pydantic AI, Outlines, DocETL, CocoIndex, dlt) avoid the commercial thresholds of Marker weights and MinerU and the AGPL of Unstract.
- Evaporate-style code synthesis (LLM writes an extractor function, which then runs deterministically) is underused. For templated document families it turns a stochastic per-document step into a deterministic, versionable function.

### Gaps
- BAML's Schema-Aligned Parsing internals and accuracy claims were not verifiable from the fetched page, which was the legacy v0 docs.
- LlamaExtract citation and confidence features were not described on the page read.
- GitHub API access was blocked, so star counts and release cadence (maturity metrics) were not collected. Maturity is inferred from docs status labels such as "experimental" and "beta".
- Haystack and LangChain extraction modules were checked for licence only; their extraction docs were not read in this track.

## 2. Orchestration and incremental processing: assets, incremental recompute, CDC for documents, idempotency, LLM-call caching, batch APIs

### Takeaway
- **Incremental engine.** Use content hashing plus memoization that also fingerprints code, prompt and model. CocoIndex does this natively: logic changes propagate transitively, and failures never poison the cache.
- **Loading.** Use idempotent merge semantics: dlt merge/SCD2, keyed on document hash and record IDs.
- **Orchestration.** Use an orchestrator with partitions and caching (Dagster dynamic partitions, or Prefect `INPUTS + TASK_SOURCE` cache policies with SERIALIZABLE locks).
- **Cost.** Run bulk backfills through provider batch APIs (50% discount, 24h window, `custom_id` mapping).
- **Determinism.** Temperature 0 is not enough. Determinism must be engineered with caching, or with batch-invariant inference when self-hosting.

### Cited Findings

**Incremental recompute (CocoIndex)**
- CocoIndex (Apache-2.0, Rust core) memoizes `@coco.fn(memo=True)` results "by hash(input) + hash(code)". It reprocesses only changed files and reconciles target state, creating, updating and retiring stale rows. — [CocoIndex README](https://github.com/cocoindex-io/cocoindex)
- CocoIndex v1 change-detection semantics:
  - logic changes (source code, `deps` such as a prompt string or model name, or an explicit `version`) propagate transitively along *runtime* invocations; input changes do not;
  - hidden dependencies such as globals or files are not detected unless declared via `deps` or `use_context(detect_change=True)`;
  - exceptions never write a cache entry. — [CocoIndex function docs](https://cocoindex.io/docs/programming_guide/function/)
- CocoIndex recovers automatically after a crash or `kill -9` by reconciling desired state. Writes are atomic per target backend where supported, but **not transactional across different targets**, such as Postgres plus files. — [CocoIndex FAQ](https://cocoindex.io/docs/faq/)
- CocoIndex docs describe the product as "only the data that actually changed is reprocessed, lineage is observable end to end, and the schema is known up front". v1 is a ground-up redesign of v0. — [CocoIndex docs index](https://cocoindex.io/docs/llms.txt)

**Loading and orchestration**
- dlt write dispositions are append, replace and merge (via `primary_key`/`merge_key`). Merge strategies are delete-insert, scd2, upsert, insert-only and cdc, plus cursor-based incremental loading and state tracking. Refresh modes (`drop_data`, `drop_resources`, `drop_sources`) apply at load, so a failed extract doesn't touch destination data. — [dlt incremental loading](https://dlthub.com/docs/general-usage/incremental-loading)
- Dagster dynamic partitions (`DynamicPartitionsDefinition`) let a sensor add partition keys at runtime, for example one per new file, and launch runs. Dagster recommends **≤100,000 partitions per asset** for UI performance. — [Dagster partitioning docs](https://dagster.io/docs/guides/build/partitions-and-backfills/partitioning-assets)
- Prefect 3 caching:
  - policies are `DEFAULT` (inputs + code + flow run id), `INPUTS`, `TASK_SOURCE`, `FLOW_PARAMETERS` and `NO_CACHE`, composable with `+`/`-`;
  - result persistence is required and off by default;
  - `SERIALIZABLE` isolation with Memory, FileSystem or Redis lock managers prevents duplicate concurrent execution;
  - transactions give idempotent all-or-nothing task groups. — [Prefect caching docs](https://www.prefect.io/docs/v3/concepts/caching)

**Batch APIs and cost**
- Anthropic Message Batches:
  - 50% cost reduction; up to 100,000 requests or 256 MB per batch;
  - most batches finish within 1h, and they expire after 24h; results are kept 29 days;
  - stacks with prompt caching, but batch cache hits are best-effort ("30 percent to 98 percent");
  - use the 1-hour cache TTL for shared context. — [Claude batch processing docs](https://platform.claude.com/docs/en/build-with-claude/batch-processing)
- OpenAI Batch API: 50% cheaper, 24h window, up to 50,000 requests and 200 MB input. Output order is not guaranteed, so map results by `custom_id`. — [OpenAI Batch guide](https://developers.openai.com/api/docs/guides/batch)

**Non-determinism at temperature 0**
- Thinking Machines (Sept 2025): Qwen3-235B at temperature 0 produced **80 unique completions out of 1,000**, diverging at token 103. The root cause is lack of batch invariance, not just floating-point concurrency. Batch-invariant kernels made all 1,000 identical at about 1.6x runtime (26s → 42s on Qwen3-8B). — [Defeating Nondeterminism in LLM Inference](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)
- vLLM now ships batch invariance in **beta**, enabled with `VLLM_BATCH_INVARIANT=1`.
  - Hardware: NVIDIA compute capability ≥8.0, AMD MI-series and Intel XPU.
  - It uses deterministic kernels and fixed reduction orders, with a performance cost.
  - Caveat: tensor-parallel all-reduces whose size is not a multiple of 16 bytes are not yet guaranteed. — [vLLM batch invariance docs](https://docs.vllm.ai/en/latest/features/batch_invariance.html)
- Atil et al. (2024) measured five "deterministic" LLMs on 8 tasks over 10 runs. Accuracy varied by up to 15% across runs, with up to a 70% best-to-worst gap. None gave repeatable output strings. They propose the TARr@N and TARa@N agreement metrics. — [Non-Determinism of "Deterministic" LLM Settings (arXiv 2408.04667)](https://arxiv.org/abs/2408.04667)

**Production architecture**
- A production Document AI microservice architecture (2026) processes "thousands of multi-page documents per hour". It separates GPU inference from CPU orchestration and uses async IO. It found that **OCR, not LLM parsing, dominates end-to-end latency**, and that throughput saturates at shared GPU-inference capacity rather than worker count. — [Operationalizing Document AI (arXiv 2605.18818)](https://arxiv.org/abs/2605.18818)
- Uber orchestrates its TextSense invoice pipeline on Cadence, Uber's workflow engine, to handle "nonlinear and verbose" document workflows. — [Uber invoice processing blog (2025)](https://www.uber.com/blog/advancing-invoice-document-processing-using-genai)
- Grab's metadata classification service batches requests through a message queue at fixed intervals. A workflow-level rate limiter respects a shared Azure OpenAI quota of 240K tokens per minute, and predictions are published to Kafka (2023, updated 2024). — [Grab LLM data classification](https://engineering.grab.com/llm-powered-data-classification)

### Inferences
- A safe cache key for an extraction call is: `sha256(document bytes or canonical parsed JSON) + schema hash + prompt-template hash + model id/version + decoding params + extractor-code version`. Instructor's built-in key covers schema, model and messages. CocoIndex adds code and `deps`. Use one of these rather than ad-hoc `functools.cache`, which Instructor's own docs warn returns stale results after a model change.
- **CDC for documents** is best modelled as content-hash-keyed upserts:
  - a new hash triggers new extraction;
  - an unchanged hash with a changed prompt or model triggers re-extraction only where the memo is invalidated;
  - a deleted source retires the downstream rows (CocoIndex's target-state reconciliation, or dlt merge/SCD2 for history).
- Re-running extraction over an unchanged snapshot should produce zero LLM calls. This is a testable invariant for "deterministic rebuilds".
- Per-document dynamic partitions in Dagster collide with the ≤100k guidance on large corpora. Partition by source and batch, and handle per-document granularity inside the asset with a cache. Alternatively use CocoIndex, whose processing components are per-item by design.

### Gaps
- No primary engineering write-up was found describing Airflow 3 asset-aware scheduling specifically for document LLM pipelines. Airflow docs were not read in this track.
- No published production numbers were found on cache hit rates for LLM extraction caches, beyond Anthropic's batch prompt-cache range of 30–98%.

## 3. Engineering case studies with numbers

### Takeaway
Two families of case studies exist.

1. **Document/attribute extraction into structured stores**: Uber TextSense invoices, Instacart PARSE, Shopify Global Catalogue, DoorDash product knowledge graph, Grab metadata tagging, Ramp receipts. These share four patterns:
   - config-driven, schema-first onboarding;
   - cascades from cheap to expensive methods;
   - self-verification or confidence scores routing low-confidence values to humans;
   - deterministic business-rule validation after the LLM.
2. **Agents querying structured data**: Uber QueryGPT and Finch, LinkedIn SQL Bot, Pinterest, Swiggy Hermes, Grab Data-Arks. These converge on:
   - curated or simplified tables (data marts, workspaces);
   - metadata and value-alias retrieval;
   - EXPLAIN/existence validators;
   - golden-set regression;
   - and, for the most deterministic setups, pre-written SQL exposed as APIs (Grab) or a semantic layer (dbt benchmark).

### Cited Findings

**Extraction into databases**
- **Uber TextSense invoices (Apr 2025):**
  - inputs: invoices in 25+ languages, each with 15–20 header attributes plus line items;
  - LLM choice: GPT-4 was chosen over fine-tuned Llama 2 and Flan-T5, because fine-tuning "caused hallucinations, especially in line items";
  - results: 90% overall accuracy, with 35% of invoices at 99.5% accuracy and 65% above 80%; 70% less handling time; 25–30% cost savings versus manual; 2x reduction in manual invoicing;
  - validation: a post-processing business-rule layer with exact match for invoice numbers and fuzzy match for descriptions, plus a side-by-side PDF-vs-extraction review UI;
  - labelling priority: high-volume suppliers with field accuracy below threshold. — [Uber invoice processing blog](https://www.uber.com/blog/advancing-invoice-document-processing-using-genai)
- **Instacart PARSE (Aug 2025):**
  - self-serve UI where an attribute definition, input SQL, few-shot examples, LLM and prompt template are versioned configs; scale is millions of SKUs;
  - the "organic" attribute reached 95% accuracy in 1 day versus 1 week traditionally;
  - a cheaper LLM matched strong models on simple attributes at 70% lower cost but lost 60% accuracy on hard ones;
  - multimodal input raised recall 10% on sheet count;
  - confidence comes from a self-verification prompt whose first-token "yes" probability is the score; low-confidence values go to human auditors;
  - planned cost work: prompt batching and similarity-based extraction caching. — [Instacart PARSE blog](https://company.instacart.com/tech-innovation/scaling-catalog-attribute-extraction-with-multi-modal-llms)
- **Shopify Global Catalogue (Jul 2025, ICLR 2025 Expo talk):**
  - scale: ~40M LLM calls and ~16B tokens per day; over 10M product updates per day;
  - models: fine-tuned open vision LLMs (LLaVA 1.5 7B → Llama 3.2 11B → Qwen2-VL 7B), with taxonomy-constrained outputs;
  - serving: median latency 2s → 500ms, and 40% less GPU via selective field prompting;
  - labelling: multi-LLM annotation with an arbitrator, and human consensus for test labels;
  - matching: products form bipartite graph clusters with Universal Product IDs. Lesson: "a single incorrect edge can create a large cluster of mismatched products";
  - lesson: commercial APIs became "prohibitively expensive" at that scale. — [Shopify Engineering](https://shopify.engineering/leveraging-multimodal-llms)
- **DoorDash product knowledge graph** (originally 2024; secondary summary read because the primary returned 403):
  - brand pipeline: a classifier runs first, an LLM extracts brands, and a second LLM de-duplicates them against the graph taxonomy;
  - "organic" labelling is a 3-stage waterfall: string match → LLM reasoning/OCR → LLM agent with web search;
  - generalized attribute extraction uses RAG over golden annotations to pick 3–5 few-shot examples for GPT-4, whose labels then fine-tune a smaller model;
  - annotation generation took about 1 week versus months. — [Aktagon summary of DoorDash post](https://signals.aktagon.com/articles/2025/12/building-doordashs-product-knowledge-graph-with-large-language-models/) (primary: careersatdoordash.com, not fetchable)
- **Grab metadata classification (2023, updated Jul 2024):**
  - prompt: GPT-3.5 tags columns with one tag each from a curated tag library, a default `<None>` tag "to allow for confusion", and a JSON output schema;
  - volume: >20,000 entities in the first month, ~300–400 per day, ~360 man-days per year saved;
  - quality: users change fewer than 1 tag per table on average; 80% of data owners found it helpful;
  - planned: prompt-version performance pipelines. — [Grab Engineering](https://engineering.grab.com/llm-powered-data-classification)
- **Ramp receipts (Mar 2024, vendor case study by Modal):** an LLM converts OCR text into structured JSON using fine-tuned models hosted on Modal. Claims: 34% fewer receipts needing manual intervention, and infrastructure "79% cheaper" than major providers. Both are self-reported marketing claims. — [Modal Ramp case study](https://modal.com/blog/ramp-case-study)
- **Karnataka fiscal documents (2025):** multi-stage LLM extraction from 200+ page fiscal PDFs uses the hierarchical totals in fiscal tables as multi-level **algorithmic validation** of extracted numbers. — [Information Extraction From Fiscal Documents (arXiv 2511.10659)](https://arxiv.org/abs/2511.10659)
- **Neurosymbolic extraction from transactional documents (2025):** LLM candidate extractions are filtered through syntactic, task and domain (arithmetic) validation, with significant F1 gains reported. — [arXiv 2512.09666](https://arxiv.org/abs/2512.09666)

**Agents querying structured data**
- **Uber QueryGPT (Sept 2024):**
  - context: 1.2M interactive queries per month on the data platform;
  - impact: query authoring time 10 → ~3 minutes; ~300 daily active users in limited release, 78% of whom said it saved time;
  - architecture: 12 system "workspaces" plus Intent, Table and Column-Prune agents; some Tier-1 schemas were 40–60K tokens with more than 200 columns;
  - evaluation: a golden set from real logs, scored on intent accuracy, table overlap, successful run, non-empty output and LLM-scored similarity;
  - noise: **~5% run-to-run variation is treated as noise**;
  - open problem: hallucinated tables and columns. — [Uber QueryGPT](https://www.uber.com/blog/query-gpt/)
- **Uber Finch (Jul 2025):**
  - LangGraph supervisor and SQL-writer agents over **curated single-table data marts**;
  - OpenSearch index of natural-language aliases for columns *and values*, to fix WHERE clauses;
  - RBAC checks before execution;
  - evaluation compares the **results** of generated SQL with a golden query's results (not SQL text), and historical queries are rerun before any prompt or model change;
  - Uber notes Finch is not 100% reliable and plans a "Request validation" path. — [Uber Finch](https://www.uber.com/en-US/blog/unlocking-financial-insights-with-finch/)
- **LinkedIn SQL Bot (Dec 2024):**
  - knowledge graph of users, table clusters, tables and fields, built from DataHub, query logs and certified notebooks;
  - retrieval: embedding retrieval of the top 20 tables → LLM re-rank to 7;
  - validators check table and field existence and run EXPLAIN, with a self-correction agent;
  - benchmark: 130+ questions across 10 areas, ~60% with multiple accepted answers (without them, recall was under-reported by 10–15%); the LLM judge is within 1 point of humans ~75% of the time;
  - outcomes: ~95% rate accuracy "Passes" or better; "Fix with AI" accounts for ~80% of sessions; embedding the bot in the DARWIN platform raised adoption 5–10x. — [LinkedIn Engineering](https://www.linkedin.com/blog/engineering/ai/practical-text-to-sql-for-data-analytics)
- **Pinterest (2024, secondary summary):**
  - first-shot SQL acceptance rose from 20% to over 40%;
  - task completion 35% faster;
  - table-search hit rate was 40% without table documentation in the embeddings;
  - RAG over table and query summaries in OpenSearch, then an LLM picks the top-K tables for the user to confirm. — [ZenML summary of Pinterest](https://www.zenml.io/llmops-database/text-to-sql-system-with-rag-enhanced-table-selection)
- **Pinterest 2026 Analytics Agent** (republished summary): unified context-intent embeddings, governance-aware ranking, EXPLAIN validation before execution, AI-generated docs and glossary propagation; reached 40% of the analyst population within 2 months. — [Engineered.at republication](https://engineered.at/articles/unified-context-intent-embeddings-for-scalable-text-to-sql)
- **Swiggy Hermes V3 (InfoQ, Jan 2026):**
  - SQL generation accuracy rose from 54% to 93%;
  - historical Snowflake SQL is converted to natural language and indexed as few-shot examples;
  - a ReAct orchestrator; an explanation layer with confidence scores; RBAC, SSO and audit logs. — [InfoQ on Swiggy Hermes](https://www.infoq.com/news/2026/01/swiggy-hermes-conversational-ai) (original Swiggy Bytes post returned 503)
- **Grab Data-Arks (Oct 2024):** frequently used SQL queries and Python functions are **uploaded and exposed as individual APIs**. The LLM, through Spellvault RAG, *selects* which pre-written query to run rather than writing SQL. Report generation saves an estimated 3–4 hours per report, and fraud investigations take "minutes". — [Grab Engineering](https://engineering.grab.com/transforming-the-analytics-landscape-with-RAG-powered-LLM)
- **dbt Labs semantic layer vs text-to-SQL (Apr 2026):**
  - setup: ACME Insurance (15 tables), 11 questions × 20 runs;
  - in-scope accuracy: semantic layer 98.2% (Sonnet 4.6) and 100% (GPT-5.3 Codex) versus text-to-SQL 90.0% and 84.1%;
  - overall accuracy across all 11 questions: 72.7% versus 64.5%;
  - in 2023 with GPT-4: 60.5% versus 32.7%;
  - the semantic layer generates SQL deterministically and returns an **error rather than wrong data** when a question is out of scope;
  - higher reasoning effort did not help. — [dbt Labs benchmark post](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026)
- **Sequeda et al. (2023):** GPT-4 zero-shot over enterprise SQL scored 16% accuracy, rising to 54% when questions were posed over a knowledge-graph (ontology plus mappings) representation. — [KG benchmark (arXiv 2311.07509)](https://arxiv.org/abs/2311.07509)

### Inferences
- Every extraction case study keeps a deterministic layer after the LLM: business rules (Uber), arithmetic or hierarchy checks (fiscal, neurosymbolic), taxonomy constraints (Shopify) and graph de-duplication (DoorDash). This is where data-lake determinism is actually enforced.
- On the query side, determinism rises as the agent's freedom shrinks:
  - free text-to-SQL (QueryGPT, ~5% run-to-run noise);
  - curated marts and aliases (Finch);
  - semantic layer (dbt: errors instead of wrong data);
  - pre-registered parameterized queries (Grab Data-Arks).
  
  For an agent-retrievable lake, start at the deterministic end and keep text-to-SQL as a fallback.
- Cost lessons converge across Instacart, DoorDash and Shopify: cascade cheap → expensive and fine-tune small or open models once labels exist. Uber is the counterexample: fine-tuned open models hallucinated line items, so GPT-4 was used.

### Gaps
- No relevant primary engineering posts were found for Airbnb, Netflix, Stripe, Brex or Vimeo on document extraction or deterministic agent querying. Searches did not surface them, and they may not exist.
- Primary sources for Pinterest (2024), DoorDash and Swiggy could not be fetched. Their numbers come from secondary summaries; the Swiggy 54%→93% figure is quoted from InfoQ.
- Shopify did not disclose accuracy. Uber Finch disclosed no accuracy or adoption numbers.
- The Alan (insurance) post "Lessons from Running an LLM Document Processing Pipeline in Production" returned 403 and was not read.

## 4. Agent access to the resulting database: MCP servers, read-only roles, RLS, query allowlists, snapshot pinning

### Takeaway
Expose the lake through four layers:
1. **Parameterized, pre-registered tools** as the primary path. MCP Toolbox's `tools.yaml` SQL statements with typed parameters act as a query allowlist, as do semantic-layer tools.
2. **Read-only free-form SQL** as a fallback, enforced at the database: a read-only role, single-statement prepared execution, RLS and statement timeouts.
3. **Snapshot pinning** at the storage layer (DuckLake/Iceberg-style `AT (VERSION => n)`), so identical queries return identical rows.
4. **Provenance columns** in every result.

Do not rely on application-level "read-only transactions" alone. Anthropic's archived reference Postgres MCP server shows why.

### Cited Findings
- **Datadog Security Labs (Aug 2025):** Anthropic's reference `@modelcontextprotocol/server-postgres` (v0.6.2, ~21k weekly npm downloads, archived in July 2025) wrapped queries in `BEGIN TRANSACTION READ ONLY`. It still accepted multi-statement strings, so `COMMIT; DROP SCHEMA public CASCADE;` escaped the read-only transaction. Pooled connections also allowed session-state tampering such as `statement_timeout`. Fixes: restricted-privilege roles, single prepared statements, and destroying the connection after each call. — [Datadog Security Labs](https://securitylabs.datadoghq.com/articles/mcp-vulnerability-case-study-SQL-injection-in-the-postgresql-mcp-server/)
- **Postgres MCP Pro (crystaldba, MIT)** has two access modes. Unrestricted is read/write. **Restricted** limits the server to read-only transactions with execution-time limits and "safe SQL parsing", for production. Tools include `execute_sql`, `explain_query` (including hypothetical indexes) and workload index analysis. — [postgres-mcp README](https://github.com/crystaldba/postgres-mcp)
- **MCP Toolbox for Databases (Google, Apache-2.0)**, renamed from genai-toolbox to mcp-toolbox:
  - prebuilt generic tools (`list_tables`, `execute_sql`) for development;
  - a custom-tools framework for production, where `tools.yaml` declares sources, **parameterized SQL statements** (`$1` parameters with types and descriptions) and toolsets per agent;
  - connection pooling, IAM auth and OpenTelemetry;
  - supports Postgres, MySQL, BigQuery, Spanner, Snowflake, Neo4j, ClickHouse, Trino and more. — [MCP Toolbox README](https://github.com/googleapis/genai-toolbox)
- **DuckDB/MotherDuck MCP server (MIT)** connects to a local DuckDB file **read-only by default**, without holding the file lock so a writer can coexist. `--read-write` and `--allow-switch-databases` must be opted into, and the README has a "Securing for Production" section. — [mcp-server-motherduck README](https://github.com/motherduckdb/mcp-server-motherduck)
- **DuckLake time travel:**
  - `SELECT ... AT (VERSION => 3)` or `AT (TIMESTAMP => ...)`, plus `ATTACH ... (SNAPSHOT_VERSION 3)`, pin a whole session to a snapshot;
  - snapshots persist until explicitly expired;
  - the `snapshots()` function lists them;
  - inside a transaction, time travel cannot see snapshots newer than the transaction's own. — [DuckLake time travel docs](https://ducklake.select/docs/stable/duckdb/usage/time_travel)
- **Postgres RLS:**
  - `ENABLE ROW LEVEL SECURITY` with no policy means default-deny;
  - `USING` filters visible rows and `WITH CHECK` filters writes;
  - restrictive policies AND together;
  - superusers, `BYPASSRLS` roles and (by default) table owners bypass RLS, unless `FORCE ROW LEVEL SECURITY` is set;
  - referential-integrity checks bypass RLS, which is a covert-channel risk. — [PostgreSQL RLS docs](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- **Anthropic "Writing effective tools for agents" (Sept 2025):**
  - prefer consolidated, task-shaped tools over list-everything tools;
  - namespace tools by service and resource;
  - return human-readable names rather than opaque UUIDs;
  - offer a `response_format` (concise/detailed) enum; the concise mode used about 1/3 of the tokens;
  - paginate and truncate (Claude Code caps tool responses at 25,000 tokens by default);
  - return actionable error messages;
  - evaluate tools on realistic multi-step tasks with held-out sets. — [Anthropic Engineering](https://www.anthropic.com/engineering/writing-tools-for-agents)
- **Uber Finch** checks user permissions (RBAC) before running SQL and governs access by financial dimension. **Swiggy Hermes** uses RBAC, SSO and audit logs. — [Uber Finch](https://www.uber.com/en-US/blog/unlocking-financial-insights-with-finch/); [InfoQ on Swiggy](https://www.infoq.com/news/2026/01/swiggy-hermes-conversational-ai)
- **Grab** tags drive downstream sensitivity tiers, attribute-based access control and dynamic data masking. This suggests extraction should populate the access-control metadata, not only the payload. — [Grab Engineering](https://engineering.grab.com/llm-powered-data-classification)
- **dbt Labs:** the semantic layer "returns an error" for out-of-scope questions and "never returns invalid data". dbt's MCP server is Apache-2.0. — [dbt benchmark](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026); [dbt-mcp repo](https://github.com/dbt-labs/dbt-mcp)
- Docling ships its own MCP server for agents, but that serves document conversion, not database querying. — [Docling docs](https://docling-project.github.io/docling/)

### Inferences
- The query allowlist is the deterministic core. Each MCP tool equals one SQL template with typed parameters, which gives the same arguments and the same rows on a pinned snapshot.
- Free-form `execute_sql` should run in this configuration:
  - under a dedicated `NOLOGIN` read-only role that has `SELECT` only on the published schema;
  - with `default_transaction_read_only=on`, `statement_timeout` and a row limit;
  - through a single-statement prepared protocol;
  - against a pinned snapshot (DuckLake `SNAPSHOT_VERSION`, Iceberg snapshot id, or a Postgres schema-per-release/view swap).
- Every result row should carry `source_doc_id`, `doc_sha256`, `page_no`, `char_start`/`char_end` (or bbox), `extraction_run_id` and `snapshot_id`. This makes "traceable to source spans" an exact predicate the agent can follow up on.

### Gaps
- No published production numbers were found on MCP database-server usage, injection incidents or allowlist coverage beyond the Datadog case.
- BigQuery-specific MCP policy features (authorized views, column-level security) were not researched in this track.
- Apache Iceberg/Nessie/lakeFS snapshot semantics were not read here. DuckLake was used as the representative.

## 5. Testing and evaluation in practice: golden datasets, regression suites, eval tooling, cost tracking

### Takeaway
Production teams build application-specific golden sets from real logs or documents and evaluate at component level (intent, table, field) as well as end-to-end.
- For SQL, compare results rather than SQL text, and allow multiple accepted answers.
- Calibrate LLM judges against humans.
- Treat ~5% run-to-run variance as noise.
- Rerun regression suites on every prompt or model change.

Tooling: promptfoo (MIT, now owned by OpenAI) for deterministic schema, regex, Python, cost and latency asserts in CI; LangSmith or Braintrust for dataset versioning and experiments; autoevals (MIT) for scorers. The extraction pipeline's own validators (schema, grounding, arithmetic) double as always-on evals.

### Cited Findings
- Uber QueryGPT has two eval flows. "Vanilla" runs end-to-end. "Decoupled" supplies intent and tables from humans to isolate components. Signals: intent accuracy, table-overlap score, run success, non-empty result and LLM similarity. "~5%" run-to-run variation is treated as noise, and the team looks for patterns over longer periods. — [Uber QueryGPT](https://www.uber.com/blog/query-gpt/)
- LinkedIn SQL Bot benchmark:
  - 130+ expert-built questions; experts review additions every 3 months;
  - ~60% of questions have multiple accepted answers, without which recall is under-reported by 10–15%;
  - metrics: table/field recall, hallucination rate, syntax correctness, latency;
  - an LLM judge is within 1 point of humans ~75% of the time. — [LinkedIn Engineering](https://www.linkedin.com/blog/engineering/ai/practical-text-to-sql-for-data-analytics)
- Uber Finch evaluates each sub-agent, the supervisor's routing ("intent collisions") and end-to-end behaviour. It compares SQL **results** against golden queries and reruns historical queries before deploys. — [Uber Finch](https://www.uber.com/en-US/blog/unlocking-financial-insights-with-finch/)
- Instacart PARSE evaluation:
  - development: human auditors label gold values in an eval UI, and an LLM judge speeds this up;
  - production: periodic sampling, plus routing of low-confidence values to auditors. — [Instacart PARSE](https://company.instacart.com/tech-innovation/scaling-catalog-attribute-extraction-with-multi-modal-llms)
- Shopify evaluation:
  - human consensus labels for test sets, with randomization to measure annotation bias;
  - "instruction metrics" for field compliance and field invariance;
  - LLM judges flag low-quality production outputs, and low-token-probability outputs feed active learning. — [Shopify Engineering](https://shopify.engineering/leveraging-multimodal-llms)
- Uber invoice accuracy is measured separately at header and line levels and tracked over time, on a 90/10 train/test split of the last year of invoices. — [Uber invoice blog](https://www.uber.com/blog/advancing-invoice-document-processing-using-genai)
- Hamel Husain (Mar 2024) describes three levels: (1) fast assertion unit tests run on every change, (2) human and model evaluation over logged traces, measuring LLM-judge agreement with humans via precision and recall, (3) A/B tests. His key line: "You can never stop looking at data." — [Your AI Product Needs Evals](https://hamel.dev/blog/posts/evals/)
- promptfoo assertions:
  - deterministic: `equals`, `contains`, `regex`, `is-json`/`contains-json` with JSON-Schema validation, `is-sql`, `javascript`/`python` custom code, `levenshtein`, and `cost` and `latency` thresholds;
  - model-graded: `llm-rubric`, `factuality`, `context-faithfulness`, among others. — [promptfoo assertions docs](https://www.promptfoo.dev/docs/configuration/expected-outputs/); license MIT — [promptfoo repo](https://github.com/promptfoo/promptfoo)
- OpenAI announced the Promptfoo acquisition on Mar 9, 2026 (price undisclosed; PitchBook valued Promptfoo at $86M in July 2025). Promptfoo claims use by over 25% of the Fortune 500. TechCrunch reports OpenAI "expects to continue building out" the open-source offering. — [TechCrunch](https://techcrunch.com/2026/03/09/openai-acquires-promptfoo-to-secure-its-ai-agents/)
- LangSmith evaluation:
  - datasets with splits; automatic **dataset versions** that can be tagged and pinned in CI;
  - code, LLM-judge, pairwise and human evaluators;
  - offline (regression, backtesting) and online evaluation;
  - experiments compared side by side. The open-source status was not stated on the page. — [LangSmith evaluation concepts](https://docs.langchain.com/langsmith/evaluation-concepts)
- Braintrust's autoevals (MIT) bundles LLM-as-judge (Factuality and others, adapted from OpenAI evals), heuristic (Levenshtein) and statistical (BLEU) scorers for Python and TypeScript. — [autoevals repo](https://github.com/braintrustdata/autoevals)
- Atil et al. propose TARr@N (raw-output agreement) and TARa@N (parsed-answer agreement) across N runs as determinism metrics. — [arXiv 2408.04667](https://arxiv.org/abs/2408.04667)
- DocETL's optimizer synthesizes task-specific validation prompts for plan evaluation. Gleaning uses a validator model per operator, which at least doubles cost. — [DocETL paper](https://arxiv.org/abs/2410.12189); [DocETL operators](https://ucbepic.github.io/docetl/concepts/operators/)
- Grab planned "pipelines to measure the performance of each prompt version", which amounts to prompt-version regression tracking. — [Grab Engineering](https://engineering.grab.com/llm-powered-data-classification)
- Cost tracking in practice:
  - Instacart chooses the model per attribute difficulty (70% saving on easy attributes);
  - Shopify cut GPU use 40% with selective field prompting;
  - promptfoo `cost` assertions make cost a CI gate. — [Instacart](https://company.instacart.com/tech-innovation/scaling-catalog-attribute-extraction-with-multi-modal-llms); [Shopify](https://shopify.engineering/leveraging-multimodal-llms); [promptfoo](https://www.promptfoo.dev/docs/configuration/expected-outputs/)

### Inferences
- For a document-to-DB lake, the golden set should be (document → expected typed records + expected evidence spans). Score at several levels:
  - field-level exact match for IDs, dates and amounts;
  - normalized or fuzzy match for free text;
  - record-level precision and recall for list extraction;
  - grounding rate (share of values whose span verifies against the source);
  - downstream **query-result equality** for a fixed set of agent questions run against the pinned snapshot.
- Two determinism regressions are cheap to automate:
  1. Rebuild the lake from cache and assert byte-identical tables (via table checksums).
  2. Run the agent question set twice on the same snapshot and assert identical result sets.

### Gaps
- No public numbers were found comparing promptfoo, Braintrust and LangSmith on extraction-specific evaluation.
- No case study published per-document LLM extraction cost figures, apart from Ramp's vendor-reported PII job (~$100 for 25,000 invoices on 256 workers, about 20 minutes). — [Modal Ramp case study](https://modal.com/blog/ramp-case-study)

## 6. Recommended end-to-end implementation blueprint (component choices and rationale)

### Takeaway
Build a content-addressed, versioned "extract-once, query-many" pipeline:
- Docling (or Unstructured) produces a provenance-rich intermediate representation.
- Pydantic schemas are the single source of truth for both the extraction contract and the DB DDL.
- Extraction uses strict structured outputs, plus span grounding (LangExtract-style) and deterministic validators.
- Every LLM call is memoized by (document hash, schema, prompt, model, code version) through CocoIndex or an Instructor/DSPy-style cache, with batch APIs for backfills.
- dlt or CocoIndex loads idempotently into typed Postgres or DuckLake tables, with SCD2 history, entity resolution and evidence tables.
- The lake is published as immutable snapshots.
- Agents get MCP Toolbox-style parameterized tools and a semantic layer first, and restricted read-only SQL with RLS second.
- promptfoo/pytest golden-set gates run on every schema, prompt or model change.

Every component recommended below is MIT or Apache-2.0.

### Cited Findings (evidence behind each blueprint choice)

**1. Ingest and registry**
- Hash every file (SHA-256) and store a `documents` registry: `doc_id = sha256(bytes)`, plus uri, mimetype, first_seen and source system. Docling already records `binary_hash`, `mimetype`, `filename` and `uri` in `DocumentOrigin`. — [docling-core](https://github.com/docling-project/docling-core/blob/main/docling_core/types/doc/common/reference.py)
- Use dlt (Apache-2.0) for API and SaaS sources with merge/SCD2. The Airbyte S3 "Document File Type Format" is a one-record-per-document alternative. — [dlt](https://dlthub.com/docs/general-usage/incremental-loading); [Airbyte S3](https://docs.airbyte.com/integrations/sources/s3)

**2. Parse into a versioned intermediate representation**
- Use Docling as the default, persisting lossless DoclingDocument JSON keyed by `doc_id` together with the docling version. Use Unstructured `hi_res` when its deterministic element IDs and element taxonomy are preferred.
- Benchmark on a sample with OmniDocBench-style metrics before choosing.
- Avoid Marker weights and MinerU in a permissive open-source toolkit unless their licence thresholds are acceptable. — [Docling](https://docling-project.github.io/docling/); [Unstructured](https://docs.unstructured.io/open-source/concepts/document-elements); [OmniDocBench](https://arxiv.org/abs/2412.07626); [Marker](https://github.com/datalab-to/marker); [MinerU license](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md)
- OCR will dominate latency. Scale GPU OCR separately from CPU orchestration. — [arXiv 2605.18818](https://arxiv.org/abs/2605.18818)

**3. Schema-first extraction**
- Define Pydantic models per document type, with a version string in each. Generate the JSON Schema for the LLM and the DDL from them.
- Use provider strict structured outputs (OpenAI or Claude), or Outlines with vLLM for local models.
- Wrap calls with Instructor or Pydantic AI for validators and `ModelRetry`.
- Respect provider schema limits; for example, Claude has no numeric min/max, so enforce ranges in Pydantic validators instead. — [Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs); [OpenAI](https://developers.openai.com/api/docs/guides/structured-outputs); [Outlines](https://dottxt-ai.github.io/outlines/latest/); [Pydantic AI](https://pydantic.dev/docs/ai/core-concepts/output/); [Instructor](https://python.useinstructor.com/concepts/caching/)
- Require evidence for every extracted value: return `extraction_text` plus a char interval, verify that it exact-matches the source (LangExtract's `char_interval=None` filter), and map it to Docling `ProvenanceItem` page and bbox. — [LangExtract README](https://github.com/google/langextract)
- Add a `None`/unknown option to enums so the model isn't forced to guess (Grab). Add a self-verification confidence score (Instacart first-token "yes" probability) and route low-confidence values to review. — [Grab](https://engineering.grab.com/llm-powered-data-classification); [Instacart](https://company.instacart.com/tech-innovation/scaling-catalog-attribute-extraction-with-multi-modal-llms)
- Run deterministic validators after the LLM:
  - business rules and lookups (Uber);
  - arithmetic and hierarchy totals (fiscal, neurosymbolic);
  - taxonomy membership (Shopify). — [Uber](https://www.uber.com/blog/advancing-invoice-document-processing-using-genai); [arXiv 2511.10659](https://arxiv.org/abs/2511.10659); [arXiv 2512.09666](https://arxiv.org/abs/2512.09666); [Shopify](https://shopify.engineering/leveraging-multimodal-llms)
- For high-volume templated families, consider Evaporate-style synthesized extractor functions validated against LLM outputs. These run deterministically at about 110x fewer tokens. — [Evaporate](https://arxiv.org/abs/2304.09433)

**4. Determinism and caching**
- Memoize every LLM call on `hash(doc_ir) + schema_hash + prompt_hash + model_id + params + code_version`, using CocoIndex `@coco.fn(memo=True)` with prompt and model declared in `deps`, or Instructor `DiskCache`. Persist the raw response alongside the parsed record.
- Never rely on temperature 0. 1,000 runs gave 80 distinct outputs, and accuracy varied up to 15% between runs.
- If self-hosting, enable vLLM `VLLM_BATCH_INVARIANT=1` (beta, ~1.6x slower in Thinking Machines' tests). — [CocoIndex](https://cocoindex.io/docs/programming_guide/function/); [Thinking Machines](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/); [Atil et al.](https://arxiv.org/abs/2408.04667); [vLLM](https://docs.vllm.ai/en/latest/features/batch_invariance.html)
- Run backfills through the Batch APIs (50% off; map results by `custom_id`, because order is not guaranteed). Use a 1-hour prompt-cache TTL for shared instructions. — [Claude batch](https://platform.claude.com/docs/en/build-with-claude/batch-processing); [OpenAI batch](https://developers.openai.com/api/docs/guides/batch)

**5. Entity resolution and graph**
- Use DocETL `resolve` (blocking plus cascade) or neo4j-graphrag resolvers (exact, then fuzzy). Write canonical-entity tables plus `entity_mentions` (mention → span) so merges stay auditable.
- Favour precision in merges, because one bad edge can collapse clusters (Shopify).
- For Cypher access, use the Neo4j KG Builder's lexical graph (Document → Chunk → Entity) for provenance. — [DocETL resolve](https://ucbepic.github.io/docetl/operators/resolve/); [Neo4j KG builder](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_kg_builder.html); [Shopify](https://shopify.engineering/leveraging-multimodal-llms)

**6. Load and storage**
- Use typed relational tables per schema: one row per record, with primary key `record_id = hash(doc_id, schema_version, path)`. Add an `evidence` table (`record_id, field, doc_id, page_no, bbox, char_start, char_end, quote`) and an `extraction_runs` table (`run_id, model, prompt_hash, schema_version, code_version, cost_tokens`).
- Load idempotently with dlt merge/SCD2 or CocoIndex target-state reconciliation, which also retires rows when a source is deleted. — [dlt](https://dlthub.com/docs/general-usage/incremental-loading); [CocoIndex FAQ](https://cocoindex.io/docs/faq/)
- Choose the storage engine: DuckDB with DuckLake for embedded or open-format deployments with built-in snapshots and time travel; Postgres for multi-user access with RLS. — [DuckLake](https://ducklake.select/docs/stable/duckdb/usage/time_travel); [Postgres RLS](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)

**7. Orchestration**
- Use Dagster assets (parse → extract → validate → resolve → publish), partitioned by source and batch to stay within ~100k partitions, with sensors for new files. Prefect is an alternative with `INPUTS + TASK_SOURCE` cache policies and SERIALIZABLE locks. CocoIndex can serve as the incremental engine inside an asset. — [Dagster](https://dagster.io/docs/guides/build/partitions-and-backfills/partitioning-assets); [Prefect](https://www.prefect.io/docs/v3/concepts/caching)
- Use a workflow engine for long, branching document flows with human review, as Uber does with Cadence. — [Uber invoice blog](https://www.uber.com/blog/advancing-invoice-document-processing-using-genai)

**8. Publish and agent access**
- Publish an immutable snapshot ID per release. Agents must query `AT (VERSION => n)` or attach with `SNAPSHOT_VERSION`.
- The primary interface is MCP Toolbox `tools.yaml` parameterized statements and/or a dbt semantic layer through dbt-mcp.
- The fallback is restricted read-only SQL (postgres-mcp restricted mode, or DuckDB MCP read-only by default) under a SELECT-only role with RLS.
- Do not use the archived reference Postgres MCP server.
- Follow Anthropic's tool-design guidance: namespaced, concise or detailed responses, paginated, actionable errors. — [MCP Toolbox](https://github.com/googleapis/genai-toolbox); [dbt benchmark](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026); [postgres-mcp](https://github.com/crystaldba/postgres-mcp); [MotherDuck MCP](https://github.com/motherduckdb/mcp-server-motherduck); [Datadog](https://securitylabs.datadoghq.com/articles/mcp-vulnerability-case-study-SQL-injection-in-the-postgresql-mcp-server/); [Anthropic tools](https://www.anthropic.com/engineering/writing-tools-for-agents)
- Copy what works from industry: curated single-table marts plus value-alias indexes (Finch); pre-registered queries as APIs (Grab); EXPLAIN plus existence validators for free SQL (LinkedIn, Pinterest). — [Finch](https://www.uber.com/en-US/blog/unlocking-financial-insights-with-finch/); [Grab Data-Arks](https://engineering.grab.com/transforming-the-analytics-landscape-with-RAG-powered-LLM); [LinkedIn](https://www.linkedin.com/blog/engineering/ai/practical-text-to-sql-for-data-analytics)

**9. Evaluation gates**
- Golden documents with expected records and spans; promptfoo `is-json` + schema / `python` asserts and `cost` thresholds in CI.
- A LangSmith or Braintrust dataset version pinned per release.
- An LLM judge only for free-text fields, calibrated against humans (as LinkedIn and Hamel describe).
- An agent question set evaluated by result equality on a pinned snapshot (as in Finch). — [promptfoo](https://www.promptfoo.dev/docs/configuration/expected-outputs/); [LangSmith](https://docs.langchain.com/langsmith/evaluation-concepts); [Hamel](https://hamel.dev/blog/posts/evals/); [LinkedIn](https://www.linkedin.com/blog/engineering/ai/practical-text-to-sql-for-data-analytics); [Finch](https://www.uber.com/en-US/blog/unlocking-financial-insights-with-finch/)

### Inferences
- **Most effective overall approach (synthesis):**
  - treat the LLM as a non-deterministic compiler from documents to typed records;
  - make its output deterministic by memoizing and versioning it;
  - make the query path deterministic by restricting agents to exact predicates over a pinned snapshot (parameterized tools or semantic layer first, read-only SQL second);
  - make it auditable by storing span-level evidence and run metadata with every row.
- A minimal open-source reference stack, all permissive licences: Docling + Pydantic + Instructor or Pydantic AI + LangExtract-style grounding + CocoIndex (or Dagster with an Instructor DiskCache) + DuckDB/DuckLake or Postgres + MCP Toolbox / postgres-mcp (restricted) + promptfoo.
- Build order follows the risk profile in the case studies: start with one document type, mandatory human review at launch and a golden set; then add cascades, cheaper models and fine-tuning once labels accumulate (as Instacart, DoorDash and Shopify did).

### Gaps
- No single open-source project was found that already packages this whole blueprint end to end with snapshot-pinned agent access. Sycamore/Aryn and DocETL come closest on the extraction side, and MCP Toolbox on the access side.
- No independent benchmark compares Docling and Unstructured on provenance fidelity (bbox and charspan accuracy) specifically.
- No measured evidence was found that provider-side structured outputs are bitwise-reproducible across runs. The caching layer is therefore assumed necessary rather than proven sufficient alone.
