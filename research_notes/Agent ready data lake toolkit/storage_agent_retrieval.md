# Storage Architectures and Agent Retrieval Interfaces for an Agent-Retrievable Data Lake (as of Nov 2026)

Scope note: research conducted 2026-11-06 with a ~15-call budget. Many sources are vendor blogs or single-author preprints; this is flagged inline. Items marked [older] predate 2026. Items marked [vendor] are self-reported by an interested party. Items marked [secondary] were seen only via a search-engine summary or third-party write-up and not checked against the primary document.

## 1. Lakehouse / table formats for multimodal and AI data (Lance, Iceberg, Delta, DuckLake, Parquet) and query engines

### Takeaway
The 2026 stack has split into two layers. Iceberg (v3) and DuckLake 1.0 cover governed, SQL-first tabular data with deletion vectors and VARIANT. Lance covers embeddings, blobs and random access, and is the only one of these formats that also carries vector indexes. A common, vendor-promoted pattern is Lance next to Iceberg on the same object store. DuckDB has become a first-class engine for both Iceberg v3 and DuckLake.

### Cited Findings
**Lance / LanceDB**
- Lance calls itself an "open lakehouse format for multimodal AI". It claims "100x faster random access" than Parquet, built-in vector indexes and data versioning, and compatibility with Pandas, DuckDB, Polars, PyArrow and PyTorch. The 100x figure is [vendor] from the project's own tests — [lance-format/lance GitHub](https://github.com/lance-format/lance); [lance.org](https://lance.org/)
- Lance spans three layers (file format, table format and catalog spec). Iceberg spans two (table format and catalog spec) and typically uses Parquet as its file format [vendor] — [LanceDB: From BI to AI, Lance and Iceberg](https://www.lancedb.com/blog/from-bi-to-ai-lance-and-iceberg)
- Lance File format 2.1 was declared stable (LanceDB March 2026 newsletter). A later post benchmarks v2.2 against 2.1: storage is roughly halved and p50 blob-fetch latency drops from about 164 ms to 124 ms. LanceDB positions 2.2 as the default for multimodal pipelines [vendor] — [LanceDB newsletter Mar 2026](https://www.lancedb.com/blog/newsletter-march-2026); [Lance v2.2 benchmarks](https://www.lancedb.com/blog/lance-format-v2-2-benchmarks-half-the-storage-none-of-the-slowdown)
- Blob V2 adds four storage semantics: inline, packed, dedicated and external. Blobs over about 4 MB get their own file, and smaller blobs are packed into shared sidecar files. LanceDB argues that controlling both file and table layers (unlike Parquet+Iceberg) is what makes this possible [vendor] — [Lance Blob V2](https://www.lancedb.com/blog/lance-blob-v2)
- LanceDB's own benchmark post concedes that Parquet stays strong for narrow scalar scans on local storage [vendor, notable concession] — [Lance v2.2 benchmarks](https://www.lancedb.com/blog/lance-format-v2-2-benchmarks-half-the-storage-none-of-the-slowdown)
- The June 2026 LanceDB newsletter references a Rust benchmark of Lance, Delta and Iceberg on S3, but its numbers were not visible in what I retrieved — [LanceDB newsletter Jun 2026](https://www.lancedb.com/blog/newsletter-june-2026)
- A third-party Iceberg-community article describes the complementary pattern: Iceberg holds structured metadata and SQL analytics, Lance holds embeddings and blobs, and both sit side by side in S3 — [iceberglakehouse.com, May 2026](https://iceberglakehouse.com/posts/2026-05-24-lance-iceberg-multimodal/)
- Lance datasets can be uploaded to the Hugging Face Hub [vendor newsletter] — [LanceDB newsletter Mar 2026](https://www.lancedb.com/blog/newsletter-march-2026)

**Apache Iceberg v3**
- In v3, deletion vectors (roaring bitmaps stored in Puffin files) replace positional delete files. Writers must merge so that each data file has at most one deletion vector — [Iceberg spec](https://iceberg.apache.org/spec/)
- v3 features include deletion vectors, row lineage, the VARIANT type, default column values, geometry/geography types and nanosecond timestamps. Snowflake made all of these GA on May 7, 2026 [secondary] — [Atlan: Iceberg v3 + Snowflake](https://atlan.com/know/snowflake/apache-iceberg-v3/); [Google OSS blog, Aug 2025, older](https://opensource.googleblog.com/2025/08/whats-new-in-iceberg-v3.html)
- DuckDB-Iceberg v1.5.3 (May 29, 2026) adds Iceberg v3 read/write including binary deletion vectors, plus MERGE INTO and ALTER TABLE. It picks the format from the table's format-version — [DuckDB blog: New Iceberg features in v1.5.3](https://duckdb.org/2026/05/29/new-iceberg-features)

**DuckLake**
- DuckLake 1.0 was announced as production-ready on April 13, 2026, with a stable spec, a reference implementation and guaranteed backward compatibility. It shipped with DuckDB 1.5.2 [secondary for version] — [DuckLake 1.0 announcement](https://ducklake.select/2026/04/13/ducklake-10/); [dev.to: DuckLake 1.0 and Iceberg 1.11](https://dev.to/datadriven/ducklake-10-and-iceberg-111-what-a-data-engineer-should-know-jp4)
- DuckLake keeps all metadata in a SQL database. It has experimental deletion vectors stored as Iceberg-compatible Puffin files (one deletion vector per Puffin file in 1.0), and VARIANT support where shredded sub-fields get file statistics for skipping — [DuckLake 1.0 announcement](https://ducklake.select/2026/04/13/ducklake-10/)
- A practitioner migration write-up from Iceberg to DuckLake exists (anecdotal) — [Substack](https://thedataguygeorge.substack.com/p/i-migrated-an-iceberg-table-to-ducklake)

### Inferences
- For an agent-retrievable lake, a two-tier design follows from the above. Tier 1 is Lance tables for chunk text, embeddings (dense and multi-vector), page images and blobs, with Lance versions as snapshots. Tier 2 is Iceberg or DuckLake tables for extracted structured entities and relations, plus catalog/lineage metadata. All of it is queryable from DuckDB. DuckLake is the lowest-ops option for a single-node or OSS toolkit. Iceberg is the interoperability choice (Snowflake, Spark, Trino and others).
- Time travel and versioning exist in all of Lance, Iceberg, Delta and DuckLake, so retrieval results can be pinned to a snapshot ID for reproducible agent answers and evaluation. Snapshot pinning is a design recommendation, not a sourced finding.
- Lance's claims about random access and vector-index co-location are plausible but are vendor-only. Run independent benchmarks on your own workload before committing.

### Gaps
- No independent (non-LanceDB) benchmark of Lance vs Parquet/Iceberg/Delta on random access or blob fetch was found.
- Delta Lake's 2026 state (Delta 4.x, Unity Catalog OSS, deletion vectors, VARIANT, UniForm interop with Iceberg) was not researched in this pass due to budget. Treat it as a gap and do not assume feature parity.
- DataFusion and Spark specifics (for example, DataFusion as the engine inside Lance/LanceDB, and Spark connectors for Lance) were not verified this pass.
- One search snippet mentioned a DuckDB v2.0.0 release on Oct 21, 2026 (via Wikipedia). I could not verify it.

## 2. Vector stores and search engines: embedded vs server; licenses

### Takeaway
Licensing is mostly permissive: Milvus, Qdrant and Vespa are Apache-2.0, Weaviate is BSD-3, pgvector uses the PostgreSQL License, and Lance is Apache-2.0. turbopuffer is proprietary SaaS (object-storage-native). Every major engine now supports some form of BM25+vector hybrid search, but native fusion quality and expressiveness vary: Vespa is the most expressive, while pgvector relies on SQL-level fusion over Postgres full-text search.

### Cited Findings
- License summary from 2026 comparisons: Milvus Apache-2.0, Qdrant Apache-2.0, Vespa Apache-2.0, Weaviate BSD-3, pgvector PostgreSQL License, turbopuffer not open source [secondary, vendor-adjacent comparisons. Verify LICENSE files] — [Redis: best OSS vector DBs 2026](https://redis.io/blog/best-open-source-vector-databases-comparison/) (Redis is a competitor, so note the bias); [developersdigest vector DB comparison](https://www.developersdigest.tech/vector-databases); [aipromptshub 12-way comparison](https://aipromptshub.co/vs/all-vector-dbs-2026)
- Hybrid implementations differ by engine. Weaviate has built-in BM25 with alpha weighting. Qdrant uses sparse vectors plus Query API fusion. Vespa combines text and nearestNeighbor in one query with multi-phase ranking. pgvector depends on Postgres FTS plus SQL fusion. turbopuffer added full-text search recently [secondary] — [developersdigest](https://www.developersdigest.tech/vector-databases); [aipromptshub](https://aipromptshub.co/vs/all-vector-dbs-2026)
- turbopuffer is a managed, object-storage-native service with a $16/month minimum on its Launch plan [secondary] — [developersdigest](https://www.developersdigest.tech/vector-databases)
- LanceDB is an embedded (in-process) library over the Lance format with vector indexes and versioning, compatible with DuckDB, Polars and others [vendor] — [lance-format/lance](https://github.com/lance-format/lance); [LanceDB](https://www.lancedb.com/)
- LanceDB markets itself as an agent-memory store (for example "LanceDB for OpenClaw's Memory") [vendor] — [LanceDB newsletter Mar 2026](https://www.lancedb.com/blog/newsletter-march-2026)

### Inferences
- Embedded options (LanceDB, DuckDB with a VSS extension, pgvector in an existing Postgres) suit an OSS toolkit's default install. Server options (Qdrant, Milvus, Vespa, OpenSearch/Elasticsearch) suit multi-tenant deployments. A storage-abstraction interface with LanceDB as the default backend and pluggable server backends is a reasonable design.
- Elasticsearch's license history (SSPL/Elastic License, with AGPL re-added in 2024) and OpenSearch (Apache-2.0, Linux Foundation) are relevant for an OSS toolkit. These were not re-verified this pass; see Gaps.

### Gaps
- No independent, current (2026) vector DB benchmark (for example ANN-Benchmarks, VectorDBBench) was retrieved. Vendor benchmark claims were deliberately not included.
- Elasticsearch/OpenSearch license and hybrid/RRF feature status for 2026, and Milvus/Qdrant/Weaviate support for multi-vector (ColBERT-style) search, were not verified in this pass.

## 3. Hybrid retrieval: BM25 + dense, learned sparse, late interaction, rerankers; benchmark evidence

### Takeaway
Benchmarks consistently show that lexical BM25 is a strong and often underrated baseline. Reasoning-intensive retrieval (BRIGHT) is still hard: the original paper's best model scored 24.3 nDCG@10, while 2025-era multi-stage systems with LLM query expansion and reasoning rerankers reached about 47. Visual document retrieval (ViDoRe v3) is far from solved, with the best models around 57–59 nDCG@5, versus over 90 on v1. The 2026 evidence base favors multi-stage pipelines: hybrid first stage, then a strong (possibly reasoning) reranker.

### Cited Findings
**BRIGHT (reasoning-intensive retrieval)**
- Original BRIGHT (2024) results [older]:
  - The best retriever scored 24.3 nDCG@10.
  - An MS MARCO MiniLM cross-encoder got worse as more documents were reranked.
  - GPT-4 reranking added about 3.1 points over BM25.
  - BM25 with GPT-4 reasoning-expanded queries went from 14.3 to about 17.4 nDCG@10, and sparse models benefited most from expansion.
  - Source: [BRIGHT arXiv 2407.12883](https://arxiv.org/pdf/2407.12883)
- Rank1 (test-time-compute reranker, 2025): reranking BM25 top-100 with GPT-4o CoT queries, the 7B model scored 48.8 on Biology vs 24.3 for a ReasoningRank GPT-4o baseline [older] — [Rank1 arXiv 2502.18418](https://arxiv.org/pdf/2502.18418)
- DIVER reported 46.8 overall nDCG@10 on BRIGHT (31.9 with original queries) [older, self-reported SOTA claim] — [DIVER arXiv 2508.07995](https://arxiv.org/pdf/2508.07995)
- A reproducibility study (Anserini/Pyserini/RankLLM) found that a query-side BM25 variant (BM25Q) beats standard BM25 on long queries. Fusing it with reasoning retrievers usually hurts, and reasoning-focused retrievers clearly beat generic dense and sparse ones [independent, older] — [Lighting the Way for BRIGHT, arXiv 2509.02558](https://arxiv.org/html/2509.02558)
- RaDeR (reasoning-aware dense retrievers) reports beating GPT-4 by about 2–2.5 points in top-100 reranking [self-reported, older] — [RaDeR arXiv 2505.18405](https://arxiv.org/pdf/2505.18405)

**Visual document retrieval (ColPali / ColQwen / ViDoRe)**
- ViDoRe v3 launch post, English splits, nDCG@5: ColQwen2.5 0.592, ColQwen2 0.563, ColPali-v1.3 0.530. Multilingual: ColQwen2.5 0.519, ColPali-v1.3 0.431 — [HF blog: Introducing ViDoRe V3](https://huggingface.co/blog/QuentinJG/introducing-vidore-v3)
- The ViDoRe v3 RAG paper reports nDCG@10 averages of 51.9 for ColQwen2.5, 44.7 for ColQwen2 and 43.1 for ColPali. Splits and metric differ from the launch post, so the numbers are not directly comparable [secondary] — [ViDoRe V3 paper (ResearchGate)](https://www.researchgate.net/publication/399754833_ViDoRe_V3_A_Comprehensive_Evaluation_of_Retrieval_Augmented_Generation_in_Complex_Real-World_Scenarios)
- ViDoRe v3 has 8 public datasets across 6 languages. The best models score about 57–59 nDCG@5, compared with over 90 on v1, showing that v1 was saturated — [NanoVDR arXiv 2603.12824](https://arxiv.org/pdf/2603.12824)
- NanoVDR distills a 2B vision-language retriever into a 70M text-only query encoder for visual document retrieval, a cost-reduction direction — [NanoVDR arXiv 2603.12824](https://arxiv.org/pdf/2603.12824)
- Qwen3-VL-Embedding (single-vector) claims results comparable to ColPali-style multi-vector models on ViDoRe at lower compute, and ships a matching Qwen3-VL-Reranker [self-reported] — [Qwen3-VL-Embedding arXiv 2601.04720](https://arxiv.org/pdf/2601.04720)
- Multi-vector storage cost is an active research area. AnchorFold (Aug 2026) compresses multi-vector visual document representations — [AnchorFold arXiv 2608.08732](https://arxiv.org/pdf/2608.08732)
- ColPali original (ICLR 2025) introduced late-interaction retrieval over page images [older] — [ColPali ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/file/99e9e141aafc314f76b0ca3dd66898b3-Paper-Conference.pdf)

### Inferences
- The toolkit's storage schema should support, per chunk or page: (a) BM25/FTS text, (b) one or more dense vectors, (c) optional learned-sparse vectors, (d) optional multi-vector (token- or patch-level) embeddings for late interaction, and (e) the page image or blob reference. Lance's nested list-of-vectors support and blob storage fit this, but verify multi-vector index support in your chosen engine.
- Single-vector VLM embedders (Qwen3-VL-Embedding class) may be the pragmatic default, with ColQwen-style multi-vector search as an opt-in where storage cost is acceptable.
- Rerankers matter more than the choice of first stage for reasoning-heavy queries, based on the BRIGHT results above.

### Gaps
- Fresh 2026 numbers for BEIR and MTEB (v2) leaderboard leaders, and for SPLADE-v3 / learned-sparse, were not retrieved this pass. RRF itself (Cormack et al., 2009) is a standard technique but was not re-cited here.
- No single authoritative 2026 BRIGHT leaderboard was found. Cross-paper numbers are not comparable unless the setups (first stage, query rewriting, reranker inputs) match.

## 4. Agentic retrieval: grep/file tools vs vector search, iterative search, deep research

### Takeaway
2026 preprints converge on three points. (1) Lexical or grep tools in an iterative agent loop with a frontier model often match or beat dense RAG. (2) The harness and the result-delivery path matter as much as the retriever. (3) Cost and latency from many tool calls are under-measured. Evidence is mostly single-benchmark and from self-interested authors, so "grep is all you need" is not established in general.

### Cited Findings
- **"Is Grep All You Need?"** (PwC authors, arXiv 2605.15184, May 2026) — [arXiv](https://arxiv.org/html/2605.15184v1)
  - Setup: a 116-question LongMemEval-S subset, comparing grep vs vector (ANN plus reranking). Harnesses were a custom LangChain agent ("Chronos"), Claude Code, Codex CLI and Gemini CLI. Models were Opus 4.6, Haiku 4.5, GPT-5.4, Gemini 3.1 Pro and Flash-Lite.
  - Inline delivery (results appended to context): grep beat vector in every harness–model pair. Examples: Chronos/Opus 4.6 93.1 vs 83.6; Codex/GPT-5.4 93.1 vs 75.9; Chronos/Flash-Lite 86.2 vs 62.9.
  - Programmatic delivery (results written to a file the agent must read): vector won 5 of 10 pairs. For Codex/GPT-5.4, grep dropped from 93.1 to 55.2.
  - Harness effect: the same Opus 4.6 scored 93.1 in the custom harness vs 76.7 in Claude Code, a gap about as large as swapping retrievers.
  - Author caveats: the results apply to long-memory conversational QA, where answers sit in literal spans. Accuracy only (no tokens, latency or cost). Small sample, confounded factors.
- **Pi-Serini** (Hsu, Yang, Lin, arXiv 2605.10848, May 2026; Waterloo/Anserini lineage) [secondary for exact numbers] — [arXiv](https://arxiv.org/pdf/2605.10848); [EmergentMind summary](https://www.emergentmind.com/papers/2605.10848)
  - BM25 with gpt-5.5 in a ReAct loop reached 83.1% accuracy and 94.7% surfaced evidence recall on BrowseComp-Plus (830 queries, about 100k docs).
  - It was reported more accurate and cheaper than dense-retriever plus gpt-5.2 pipelines.
  - BM25 tuning added about 18.0% accuracy, and deep retrieval (caching 1,000 hits with paginated browsing) added about 25.3% surfaced recall. Earlier weak BM25 results are attributed to poor configuration.
  - Limitations: a single benchmark, and the gains may depend on frontier-model reasoning.
- **"Keyword search is all you need"** (Amazon, AAAI 2026, arXiv 2602.23368) [secondary, not verified]: a keyword-search tool agent reached about 94.5% of RAG's faithfulness and about 91.5% of its answer correctness without a vector store, and beat RAG on FinanceBench answer correctness (30.40% vs 24.24%) — via search summary; primary at arXiv 2602.23368 (not fetched).
- "Beyond Semantic Similarity: Rethinking Retrieval for Agentic Search via Direct Corpus Interaction" (arXiv 2605.05242) argues for letting agents interact with the corpus directly. It notes that Agentless showed a simple grep-and-read pipeline can match full agent frameworks on SWE tasks — [arXiv 2605.05242](https://arxiv.org/pdf/2605.05242)
- "Rethinking Agentic RAG: Toward LLM-Driven Logical Retrieval Beyond Embeddings" (arXiv 2605.27123) is another 2026 preprint in the same direction (not read in detail) — [arXiv 2605.27123](https://arxiv.org/pdf/2605.27123)
- Counterpoint (opinion): grep-style agentic search lacks governance and permissions. Enterprise settings need governed knowledge such as graphs and ACLs — [Medium: Grep vs Graph](https://medium.com/@yu-joshua/grep-vs-graph-agentic-search-is-powerful-but-enterprise-ai-needs-governed-knowledge-8de709c31451)
- Claims that "Anthropic's lead engineer said grep beat vector RAG by a lot" circulate only via social posts. I found no primary source.
- Anthropic's Programmatic Tool Calling (the model writes code that calls tools, so intermediate results stay out of context) cut average tokens on complex research tasks from 43,588 to 27,297 (37%). It raised internal knowledge-retrieval accuracy from 25.6% to 28.5% and GIA from 46.5% to 51.2% [vendor] — [Anthropic Engineering: Advanced tool use, Nov 24 2025](https://www.anthropic.com/engineering/advanced-tool-use)

### Inferences
- The toolkit should expose both lexical tools (grep/regex over materialized text, BM25 with pagination and deep result caching) and semantic search, and let the agent iterate. The Pi-Serini "search plus paginate cached hits" interface is a cheap, evidence-backed primitive.
- Materialize the lake as agent-browsable text and files (for example markdown renderings of documents and tables, laid out in a file tree) as well as indexes. File and grep access is what coding-agent harnesses are tuned for.
- Delivery format matters: return compact inline results by default, and offer file or handle-based delivery for large results. Measure end to end with the target harness.
- Evaluate cost (tool-call count, tokens) alongside accuracy. The current literature mostly does not.

### Gaps
- No independent study covers heterogeneous enterprise corpora (tables plus scans plus graphs) comparing agentic lexical vs hybrid vs graph retrieval with cost accounting.
- Deep-research agent benchmarks beyond BrowseComp-Plus (for example BrowseComp, HLE, and GAIA variants) were not surveyed this pass.

## 5. Agent interfaces: MCP (current spec and roadmap), A2A, OpenAPI; exposing SQL/search/graph/files as tools

### Takeaway
The current MCP spec is **2026-07-28**, released July 28, 2026 as the fifth spec release. It is stateless-first: no initialize handshake and no Mcp-Session-Id, with per-request `_meta` and plain round-robin load balancing. It adds Multi Round-Trip Requests, header-based routing, cacheable list results with TTLs, a formal extensions framework (Tasks, MCP Apps, Enterprise Managed Authorization), and deprecates Roots, Sampling, Logging, the legacy HTTP+SSE transport and DCR. A2A covers agent-to-agent delegation, not data access control.

### Cited Findings
- 2026-07-28 spec, core changes — [MCP blog: The 2026-07-28 Specification](https://blog.modelcontextprotocol.io/posts/2026-07-28/); [Anthropic: bringing MCP 2026-07-28 to Claude](https://claude.com/blog/bringing-mcp-2026-07-28-to-claude); [AAIF migration guide](https://aaif.io/blog/mcp-2026-07-28-whats-changing-and-how-to-migrate)
  - Stateless core: the `initialize`/`initialized` handshake and the `Mcp-Session-Id` header are retired. Each request carries protocol version, client identity and capabilities in `_meta`.
  - A new optional `server/discover` RPC lets clients learn server capabilities up front.
  - Any request can reach any server instance behind a plain round-robin load balancer.
  - Servers that need state return an explicit handle from a tool, and the model passes it back as an argument.
- Multi Round-Trip Requests (SEP-2322) replace server-initiated elicitation, sampling and roots requests. The server returns `resultType: "input_required"`, and the client retries with `inputResponses` — [MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- Streamable HTTP requests must carry `Mcp-Method` and `Mcp-Name` headers (SEP-2243), so gateways can route and meter without parsing JSON bodies — [MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- `tools/list`, `prompts/list`, `resources/list` and `resources/read` results carry `ttlMs` and `cacheScope` (SEP-2549), and list order is deterministic — [MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- Tasks moved out of the core into the `io.modelcontextprotocol/tasks` extension (SEP-2663), with poll-based `tasks/get` and `tasks/update`. Notifications go through an opt-in `subscriptions/listen` stream — [MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- Authorization changes:
  - RFC 9207 `iss` validation (SEP-2468).
  - `application_type` in DCR, so localhost redirects work for CLI apps (SEP-837).
  - Issuer-bound client credentials (SEP-2352).
  - DCR deprecated in favor of Client ID Metadata Documents (CIMD).
  - Source: [MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- Deprecations: Roots, Sampling and Logging (SEP-2577) and the legacy HTTP+SSE transport, each with at least 12 months of support. There is now a formal 12-month deprecation policy — [MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- SDKs: TypeScript, Python, Go and C# support 2026-07-28 at release, and Rust is in beta. C# SDK v2.0 is announced — [MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28/); [.NET blog: MCP C# SDK v2.0](https://devblogs.microsoft.com/dotnet/announcing-v20-of-the-official-mcp-csharp-sdk/)
- Google frames the stateless update as enabling horizontally scaled agent infrastructure [vendor] — [Google Developers Blog](https://developers.googleblog.com/scaling-ai-agent-infrastructure-with-the-mcp-stateless-updates/)
- MCP is now stewarded under the Agentic AI Foundation (AAIF), which publishes migration guidance — [AAIF blog](https://aaif.io/blog/mcp-2026-07-28-whats-changing-and-how-to-migrate)
- A2A: a June 2026 preprint characterizes A2A as delegation-centric rather than access-control-centric, and finds that none of its official example extensions address governance. The same analysis covers MCP and ACP — [Governance Gaps in Agent Interoperability Protocols, arXiv 2606.31498](https://arxiv.org/pdf/2606.31498)
- A2A was contributed by Google to the Linux Foundation. One search summary dated this to 2026, which conflicts with my background knowledge of a mid-2025 donation. The date is unverified; see Gaps.
- MCP registry status: a Speakeasy page says the official MCP Registry is still in preview, with possible breaking changes or resets before GA (page date unclear). Gateway vendors ship registry APIs, for example Zuplo's MCP Gateway read-only Server Registry API ("v0.1 freeze", changelog Aug 20, 2026). Workato's "MCP Registry GA" refers to its own product, not the official registry — [Speakeasy](https://www.speakeasy.com/resources/mcp-registry); [Zuplo changelog](https://zuplo.com/changelog/2026/08/20/mcp-server-registry.md); [Zuplo docs](https://zuplo.com/docs/mcp-gateway/server-registry); [Workato](https://www.workato.com/product-hub/changelog/mcp-registry-now-generally-available/)
- "Server cards" with `.well-known` metadata for discovery without connecting are mentioned only in a low-authority source — [dailyaiworld](https://dailyaiworld.com/public/mcp-directory/mcp-registry-server-cards-discovered)

### Inferences
- Design the toolkit's MCP server for the 2026-07-28 stateless model from day one:
  - Return explicit handles (query or cursor IDs, snapshot IDs) instead of relying on sessions.
  - Use `ttlMs`/`cacheScope` on tool and resource lists.
  - Use MRTR for clarifications such as ambiguous entities.
  - Use the Tasks extension for long-running ingestion and indexing jobs.
  - Avoid Sampling and Roots, which are deprecated.
- Suggested tool surface (design proposal, not sourced):
  - `search` (hybrid, with mode=lexical|semantic|hybrid, filters, snapshot) and `grep` (regex over materialized text with pagination).
  - `read` (fetch a document, chunk or page by ID or range, returning text and an optional image).
  - `sql` (read-only DuckDB over Iceberg/DuckLake/Lance with schema introspection via `describe_tables`).
  - `graph_query` (neighbors, paths, or Cypher-lite) and `list_sources`/`describe_schema`.
  - Expose stable documents and schemas as MCP resources and actions as tools. Header-based routing (`Mcp-Name`) lets a gateway apply per-tool ACLs and metering.
- Generate an OpenAPI description alongside MCP for non-MCP agents. A2A is relevant only if the toolkit exposes higher-level "research agent" endpoints.

### Gaps
- Official MCP roadmap items after 2026-07-28, and the official registry's GA status, could not be confirmed.
- Changes to the resources-vs-tools semantics in 2026-07-28 were not covered in the release post. Check the changelog at modelcontextprotocol.io/specification/2026-07-28/changelog.
- The A2A spec version and governance status in 2026 were not verified from primary sources, and the donation date conflicts as noted.
- Text-to-SQL tool benchmarks for 2026 (for example Spider 2.0 or BIRD leaders) were not researched this pass.

## 6. Tools as retrievable data: tool search over large catalogs

### Takeaway
Treating tool definitions as a retrievable corpus is validated by both a vendor (Anthropic Tool Search) and academic benchmarks (ToolRet). Deferred loading cuts context by about 85% in Anthropic's example and improved selection accuracy in Anthropic's internal evals. However, generic IR models are poor at tool retrieval (under 35% Completeness@10 on ToolRet). Tool-specific embedders, document expansion and LLM reranking give large gains, and semantically colliding tools are the main failure mode.

### Cited Findings
- Anthropic Tool Search Tool (Nov 24, 2025, beta `advanced-tool-use-2025-11-20`) [vendor, internal evals] — [Anthropic Engineering: Advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use)
  - Tool definitions consumed 134K tokens internally before optimization. In a 5-server example, 58 tools took about 55K tokens (GitHub about 26K, Slack about 21K), and Jira alone about 17K.
  - Tool Search loads about 500 tokens up front plus about 3K for 3–5 discovered tools, roughly 8.7K total vs about 77K, an 85% reduction.
  - Accuracy on internal MCP evals: Opus 4 went from 49% to 74%, and Opus 4.5 from 79.5% to 88.1%.
  - Variants: regex (`tool_search_tool_regex_20251119`), BM25, or a custom search such as embeddings.
  - Tool Use Examples (1–5 per tool) raised complex-parameter accuracy from 72% to 90%.
  - The post's "191,300 vs 122,800 tokens preserved" figure does not obviously reconcile with the 77K example. This is an internal inconsistency.
- Anthropic docs recommend tool search when definitions exceed 10K tokens or selection accuracy degrades as the toolset grows. `defer_loading: true` must not be set on the search tool itself, and at least one tool must stay non-deferred — [Claude Platform Docs: Tool search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
- Claude Code enables MCP Tool Search by default when tool definitions exceed about 10% of context [secondary] — [atcyrus guide](https://www.atcyrus.com/stories/mcp-tool-search-claude-code-context-pollution-guide); [MCP.Directory](https://mcp.directory/blog/mcp-context-bloat-fix-2026-tool-search-code-mode-progressive-disclosure)
- ToolRet (ACL Findings 2025) [older, independent academic] — [arXiv 2503.01763](https://arxiv.org/pdf/2503.01763); [ACL Anthology](https://aclanthology.org/2025.findings-acl.1258.pdf)
  - 7,615 retrieval tasks over 43,215 tools.
  - All retrievers scored under 35% Completeness@10.
  - Strong general IR models such as ColBERT can underperform BM25.
  - Instructions help instruction-tuned embedders (NV-Embed-v1 nDCG@10 from 33.83 to 42.71).
- "Tools Are Under-Documented" (ICLR 2026) [self-reported] — [arXiv 2510.22670](https://arxiv.org/pdf/2510.22670); [ICLR 2026 proceedings](https://proceedings.iclr.cc/paper_files/paper/2026/file/e54a9889f1048526365ed8fb56c8c8cd-Paper-Conference.pdf)
  - Applies LLM document expansion to tool docs.
  - Tool-Embed-4B scored N@10 52.23, R@10 63.13, C@10 51.61. Reranking with Tool-Rank-4B raised N@10 to 56.44.
  - Tool-Embed-0.6B beats baselines up to 8B parameters.
- "Tool Retrievers Are Underestimated" (arXiv 2609.08327, Sep 2026) argues that ToolRet annotations are incomplete, so expanding the annotations reveals higher true retriever capability (not read in detail) — [arXiv 2609.08327](https://arxiv.org/pdf/2609.08327)
- Multi-step tool retrieval via query planning beats single-shot retrieval for compositional tasks (arXiv 2601.07782, not read in detail) — [arXiv 2601.07782](https://arxiv.org/pdf/2601.07782)
- Vector-based MCP tool selection over 121 tools from 5 MCP servers retrieves 3–5 tools in under 91 ms — [arXiv 2603.20313](https://arxiv.org/html/2603.20313v1)
- RAG-MCP reported tool selection accuracy rising from 13.62% with the full catalog to 43.13% with retrieval filtering [secondary, not verified against the paper] — via [WRITER engineering](https://writer.com/engineering/rag-mcp/) and search summary
- Semantic collisions between similar tools hurt more than random noise in large catalogs — [MDPI Algorithms: Too Many Tools, Too Much Confusion?](https://doi.org/10.3390/a19060447)
- Dynamic ReAct proposes scalable tool selection for large MCP environments [older] — [arXiv 2509.20386](https://arxiv.org/html/2509.20386v1)
- Redis markets semantic tool routing for MCP overload [vendor] — [Redis blog](https://redis.io/blog/from-reasoning-to-retrieval-solving-the-mcp-tool-overload-problem/)
- Tool poisoning via malicious tool descriptions is a risk when tools are retrieved dynamically — [safeguard.sh](https://safeguard.sh/resources/blog/tool-selection-for-ai-agents-explained-large-tool-catalogs-tool-search-deferred-loading-and-poisoned-descriptions)

### Inferences
- Model tools as first-class lake records. Fields:
  - name, description, LLM-expanded description and synthetic example queries (document expansion);
  - JSON schema and usage examples;
  - source server, version, auth requirements and ACLs;
  - an embedding plus BM25 text;
  - graph edges (tool to the entities and tables it reads or writes, and tool-to-tool co-usage).
- Expose a `search_tools` tool, plus `load_tool` or deferred loading. MCP 2026-07-28 cacheable `tools/list` and header routing help gateways do this.
- Mitigate collisions with namespacing, deduplication and contrastive descriptions. Rerank top-K with an LLM or cross-encoder. Sign or verify tool descriptions against poisoning.

### Gaps
- No independent replication of Anthropic's Tool Search accuracy numbers was found.
- Gorilla/APIBench and Berkeley Function-Calling Leaderboard 2026 status were not researched this pass.
- No public MCP-gateway benchmark measures retrieval accuracy against context cost.

## 7. Access control at retrieval time, freshness/incremental indexing, retrieval evaluation

### Takeaway
The consensus is to enforce permissions as pre-filters inside every retrieval call, never only at the UI, and to propagate ACL changes to every derived vector or chunk. A 2026 Red Hat preprint formalizes policy-aware ingestion plus retrieval-time gating. Agent protocols (MCP, A2A) do not express document-level ACLs themselves, so the toolkit must carry them. Evaluation and freshness evidence was thin in this pass.

### Cited Findings
- Systems that enforce permissions only in the chat UI can leak content under adversarial prompts. Apply the user's permissions as pre-filters on every vector search. When a document's ACL changes, update the metadata on all its vectors [vendor guides] — [Onyx: Enterprise RAG platforms 2026](https://onyx.app/insights/enterprise-rag-platforms-2026); [app-lab: RAG document permissions](https://app-lab.ai/blog/rag-document-permissions/)
- Relevance-ranked retrieval ignores authorization, so cross-tenant leakage is possible. The paper proposes policy-aware ingestion, retrieval-time gating and server-side agentic orchestration for vendor-neutral multi-tenant retrieval and tool use — [Securing the Agent (Red Hat), arXiv 2605.05287](https://arxiv.org/pdf/2605.05287)
- An agentic RAG system that reuses existing enterprise search infrastructure and preserves document access controls — [AgenticRAG for Enterprise KBs, arXiv 2605.05538](https://arxiv.org/pdf/2605.05538)
- MCP, A2A and ACP cannot express several governance constraints. A2A is delegation-centric — [arXiv 2606.31498](https://arxiv.org/pdf/2606.31498)
- MCP 2026-07-28 tightened OAuth (issuer validation, issuer-bound credentials, CIMD) and added Enterprise Managed Authorization as an extension. Identity can therefore flow from client to server, but doc-level filtering stays server-side — [MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- Table-format support for freshness: Iceberg v3 and DuckLake deletion vectors enable cheap row-level deletes and updates (relevant for incremental re-index and tombstoning revoked or deleted documents) — [Iceberg spec](https://iceberg.apache.org/spec/); [DuckLake 1.0](https://ducklake.select/2026/04/13/ducklake-10/)

### Inferences
- Store ACL principals (users, groups, tenants) as indexed columns on every chunk, vector, graph-node and tool row. Resolve the caller's principals from the MCP auth token and inject a mandatory filter into every `search`, `grep`, `sql` (via row-level views), and `graph_query` call. Grep over materialized files needs per-principal views or post-filtering, which is a design challenge for "grep-first" agentic search.
- Use CDC or snapshot diffs (table-format snapshots) to drive incremental re-embedding. Version embeddings by model ID so that re-indexing can run side by side.
- For evaluation, combine component metrics (recall@k and nDCG on a labeled set, pinned to a snapshot) with end-to-end agent metrics (answer correctness, faithfulness, tool-call count and tokens). RAGAS (arXiv 2309.15217) and ARES (arXiv 2311.09476) are the established 2023 reference-free RAG eval frameworks [older; not re-verified this pass].

### Gaps
- No 2026 primary sources were retrieved on RAGAS/ARES updates, agentic-retrieval evaluation frameworks, or LLM-judge reliability for retrieval. This is a significant gap.
- No sources were found on ACL propagation in specific vector DBs (for example native RBAC or filter performance at scale in Qdrant, Milvus or turbopuffer), or on permission-aware grep.
- No sources were found on time-based or streaming freshness guarantees (index lag SLAs) in the surveyed engines.
