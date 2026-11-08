# Surveys and Foundations: Converting Unstructured Data into Databases for Deterministic Retrieval

Scope of this track: (a) surveys and vision papers that map how LLMs and databases are being combined for unstructured data, which together give a taxonomy of conversion methods; (b) what makes retrieval deterministic or not, end to end (LLM inference, ANN/vector search, embedding drift, index rebuilds, tie-breaking, data freshness), and the database machinery (snapshots, MVCC, versioned tables, provenance) that gives reproducibility. Unless marked "independent", accuracy and cost figures are **author-reported**. Research cut-off: early November 2026.

Working definition used in these notes: *deterministic retrieval* = same query + same data snapshot gives the same exact result set (and order, if ordered), computed by exact predicates over typed records (SQL / Cypher / key lookup), with each answer traceable to source spans.

---

## 1. Which surveys and vision papers map the field, and what taxonomy of conversion approaches do they propose?

### Takeaway
No single survey yet covers "unstructured documents to database for deterministic retrieval" end to end. Taken together, the surveys, benchmarks and vision papers show three families. (1) **Extract-then-query (ETL / materialized structured views):** an LLM or extraction code fills a schema once, and queries run later over typed tables (EVAPORATE, ZenDB, ReDD, DeepDive, SystemT, Text-to-Table). (2) **Query-time LLM operators (semantic operators / "unbound databases"):** the LLM runs inside the query plan on every query (LOTUS, Palimpzest, DocETL, UQE, Aryn/Luna, Galois, CAESURA, BigQuery AI functions). (3) **Hybrids:** SQL extended with free-text primitives, or table-augmented generation (SUQL, TAG, ThalamusDB, iPDB), plus agentic runtimes that write semantic-operator programs. The benchmarks (UDA-Bench, SemBench, LROBench) are the first to give these families a shared vocabulary of building blocks and operators. Only family (1) can give bit-for-bit determinism at query time, because there the LLM's randomness is paid once at ingestion and fixed into a snapshot.

### Cited Findings

**Broad surveys (map the space)**
- *A Survey of LLM × DATA* (Zhou, He, … Guoliang Li, … 2025) splits the field into DATA4LLM (data processing, storage and serving for LLMs, including RAG and agentic workflows) and LLM4DATA. It groups LLM4DATA into three areas: (i) data manipulation (cleaning, integration, discovery), (ii) data analysis (reasoning over structured, semi-structured and **unstructured** data), and (iii) system optimization (configuration tuning, query rewriting, anomaly diagnosis). The enabling techniques it names are retrieval-augmented prompting, task-specific fine-tuning and multi-agent collaboration. — [arXiv 2505.18458](https://arxiv.org/abs/2505.18458)
- *LLM/Agent-as-Data-Analyst: A Survey* (Tang et al. 2025) organizes techniques by **modality**: (i) structured (NL2SQL, NL2GQL, ModelQA), (ii) semi-structured (markup understanding, semi-structured table QA), (iii) unstructured (chart understanding, text/image document understanding), and (iv) heterogeneous (data retrieval and modality alignment in **data lakes**). It treats semantic operators as an opportunity area. — [arXiv 2509.23988](https://arxiv.org/abs/2509.23988)
- *Large Language Model-Enhanced Relational Operators: Taxonomy, Benchmark, and Analysis* (Su et al. 2026) defines LLM-enhanced relational operators (LROs) as components that call LLMs but keep a relational input/output interface. It sorts them into **Select, Match, Impute, Cluster, Order** and evaluates them in LROBench: 290 single-LRO and 60 multi-LRO queries over 27 databases in more than 10 domains. — [arXiv 2603.02537](https://arxiv.org/abs/2603.02537)
- *Can LLMs Clean Up Your Mess?* (Zhou et al. 2026), a survey of LLM data preparation, uses a task taxonomy: cleaning (standardization, error processing, imputation), integration (entity and schema matching) and enrichment (annotation, profiling). It lists persistent hallucination "even in advanced agents" and weak evaluation as the main limitations. — [arXiv 2601.17058](https://arxiv.org/abs/2601.17058)
- *Large Language Models for Generative Information Extraction: A Survey* (Xu et al. 2023) is the IE-side survey of LLM-based extraction of "structural knowledge from plain natural language texts" under a generative paradigm. It is the upstream literature for the extract-then-query family. — [arXiv 2312.17617](https://arxiv.org/abs/2312.17617)
- *Data Lakes: A Survey of Functions and Systems* (Hai, Koutras, Quix, Jarke; TKDE 2023) frames a data lake as a "schema-on-read" repository that stores raw data in its original format, in contrast to "schema-on-write" warehouses. It classifies systems by the functions they provide. — [arXiv 2106.09592](https://arxiv.org/abs/2106.09592)
- *Survey of Vector Database Management Systems* (Pan, Wang, Li 2023) notes there were "over 20 commercial" VDBMSs, all built in the preceding five years, and reviews similarity search as a half-century-old problem. — [arXiv 2310.14021](https://arxiv.org/abs/2310.14021)
- *Retrieval-Augmented Generation for LLMs: A Survey* (Gao et al. 2023) is the standard map of the vector-RAG alternative. It motivates RAG by hallucination, outdated knowledge and "non-transparent, untraceable reasoning processes". — [arXiv 2312.10997](https://arxiv.org/abs/2312.10997)
- *A Survey of Text-to-SQL in the Era of LLMs* (Liu et al.; TKDE 2025) covers the NL-to-exact-query route: model (ambiguity, under-specification, schema and instance mapping), data, evaluation and error analysis. — [arXiv 2408.05109](https://arxiv.org/abs/2408.05109)

**Benchmarks that double as taxonomies of the conversion space**
- **UDA-Bench** (Deng et al. 2025) describes building a relational ground-truth view over 5 domains: 30 graduate students spent more than 10,000 hours of manual annotation. It splits unstructured-data-analysis (UDA) systems into four building blocks: query interface, query optimization, operator design and data processing. — [arXiv 2510.27119](https://arxiv.org/abs/2510.27119)
  - Two axes separate the 7 systems it evaluates. **Extract-then-evaluate** (Palimpzest, QUEST, ZenDB) extracts a value and then applies the predicate; **direct LLM filtering** (LOTUS, DocETL, UQE) asks the LLM for the boolean. The second axis is **full-document** input (LOTUS, UQE, Palimpzest) versus **chunk-based** input (QUEST, ZenDB). Evaporate generates extraction code and then runs SQL. — [UDA-Bench HTML](https://arxiv.org/html/2510.27119v1)
  - Findings (benchmark authors, independent of the systems' authors). Extraction F1 is around 0.85 on the simple datasets (WikiArt, NBA) but only about 0.66 / 0.52 / 0.51 on Legal / Finance / Healthcare for the best systems. Extracting first and then filtering is **more accurate** than a direct LLM boolean. Chunk-based systems are cheaper but miss information. Cost on Finance ranges from 818 K tokens per document per query (DocETL) to 3.5 K (Evaporate code synthesis). "Currently, there is no system supporting end-to-end query optimization." — [UDA-Bench HTML](https://arxiv.org/html/2510.27119v1)
- **SemBench** (Lao et al.; PVLDB 19, 2026) evaluates LOTUS, Palimpzest, ThalamusDB and Google BigQuery on semantic filters, joins, maps, ranking and classification over text, image and audio, all with the same model (gemini-2.5-flash). On the Movie scenario, average quality / cost was LOTUS 0.68 / $0.62, Palimpzest 0.73 / $0.82, ThalamusDB 0.82 / $0.02 and BigQuery 0.75 / $0.55. Costs for one join query differed by about 2,000x across systems. Runs were repeated 5 times "for reproducibility" at temperature 0, and the authors attribute the remaining variance to "randomness in LLM outputs". The scalability study alone cost $9,935.80 in LLM calls. — [arXiv 2511.01716](https://arxiv.org/abs/2511.01716); [SemBench HTML](https://arxiv.org/html/2511.01716v2); [PVLDB PDF](https://www.vldb.org/pvldb/vol19/p1754-trummer.pdf)

**Family 1 — Extract-then-query / materialized structured views**
- **EVAPORATE** (Arora et al.; PVLDB 2023) ingests heterogeneous semi-structured documents and outputs queryable tables. It compares two strategies: (a) the LLM extracts values directly from every document, and (b) the LLM **synthesizes code** that performs the extraction. Code synthesis is "cheap, but far less accurate". EVAPORATE-CODE+ generates many candidate functions and ensembles them with weak supervision, beating the state of the art with a **110x reduction in LLM tokens** (averaged over 16 settings of 10k documents each). — [arXiv 2304.09433](https://arxiv.org/abs/2304.09433)
- **ZenDB** (Lin, Hulsebos, … Parameswaran et al. 2024) exploits the shared template structure of document collections. It extracts "semantic hierarchical structures", lets users impose a schema, and answers **ad-hoc SQL**. It reports up to 30% cost savings over LLM baselines and **up to 61% higher precision and 80% higher recall than RAG** baselines, "at a marginally higher cost". — [arXiv 2405.04674](https://arxiv.org/abs/2405.04674)
- **ReDD — Relational Deep Dive** (Chao, Chen, Guan, Koudas 2025) discovers query-specific minimal joinable schemas, populates relational tables, and detects extraction errors with **SCAPE**, a statistically calibrated method with coverage guarantees that uses classifiers on LLM hidden states. It reports cutting extraction errors "from up to 30% to below 1%" while keeping 100% schema recall. — [arXiv 2511.02711](https://arxiv.org/abs/2511.02711)
- **DeepDive** (Shin, Wu, … Ré; PVLDB 2015, classic) was the pre-LLM knowledge-base construction system: "populating a database with unstructured information … extraction, cleaning, and integration". It treated KBC as iterative and reported up to two orders of magnitude faster incremental inference "with negligible impact on quality". — [arXiv 1502.00731](https://arxiv.org/abs/1502.00731)
- **SystemT** (Chiticariu et al.; ACL 2010, classic) applies the database lesson (an algebra plus an optimizer) to rule-based IE. Its stated motivation is that grammar-based cascades like CPSL lack expressivity and impose a rigid evaluation order. The rules are fully deterministic. — [ACL Anthology P10-1014](https://aclanthology.org/P10-1014.pdf)
- **Text-to-Table** (Wu et al.; ACL 2022) frames IE as seq2seq generation of one or more tables from long text, "entirely data-driven" with no need to explicitly define schemas. — [arXiv 2109.02707](https://arxiv.org/abs/2109.02707)
- *Can Foundation Models Wrangle Your Data?* (Narayan et al.; PVLDB 2022) was an early proof of concept that prompting FMs works for entity matching, imputation and other cleaning and integration tasks. — [arXiv 2205.09911](https://arxiv.org/abs/2205.09911)

**Family 2 — Query-time LLM operators ("semantic operators")**
- **LOTUS / Semantic Operators** (Patel et al. 2024) define semantic filter, join, group-by, top-k and aggregate using natural-language criteria. Each operator's expected behavior is specified by a "gold algorithm", and the optimizations carry **statistical accuracy guarantees relative to that gold algorithm**. The authors report up to 1,000x speedups for some operators and up to 170% higher quality than prior LLM analytics systems. — [arXiv 2407.11418](https://arxiv.org/abs/2407.11418)
- **Palimpzest** (Liu, Russo, Cafarella, … Madden et al.; CIDR 2025) is a declarative system with a cost-based optimizer over models, prompts and hardware. It reports a plan 3.3x faster and 2.9x cheaper than baseline, and with parallelism up to a 90.3x speedup at 9.1x lower cost, with F1 "within 83.5%" of a GPT-4 baseline. — [arXiv 2405.14696](https://arxiv.org/abs/2405.14696)
- **Abacus** (Russo et al.; PVLDB 19(5), 2026) is a cost-based optimizer for semantic-operator systems that optimizes quality, cost or latency under constraints. — [arXiv 2505.14661](https://arxiv.org/abs/2505.14661)
- **DocETL** (Shankar et al. 2024) observes that single LLM calls are inaccurate on complex documents (for example, finding *all* force-majeure clauses). It uses agent-based rewrite directives and synthesized validation prompts, and reports outputs **25–80% more accurate** than engineered baselines. — [arXiv 2410.12189](https://arxiv.org/abs/2410.12189)
- **Aryn / Sycamore / Luna** (Anderson et al.; CIDR 2025): DocParse converts PDFs into "DocSets", Luna plans NL queries into Sycamore scripts, and the system shows "better accuracy than RAG on analytics queries" over NTSB reports. The paper argues that "an analytics system must provide explainability to be practical". — [arXiv 2409.00847](https://arxiv.org/abs/2409.00847)
- **UQE** (Dai et al.; NeurIPS 2024) is a SQL dialect (UQL) with natural-language conditions executed directly over unstructured collections, using sampling and compiler-style orchestration. — [arXiv 2407.09522](https://arxiv.org/abs/2407.09522)
- **Galois** (Saeed, De Cao, Papotti 2023) executes SQL operators by prompting the LLM itself as the data source. It notes that "extracting data from natural language text to precisely fit a schema … is a challenging task". — [arXiv 2304.00472](https://arxiv.org/abs/2304.00472)
- **CAESURA** (Urban & Binnig; CIDR 2024) uses LLMs as multi-modal query planners that turn NL into executable plans over data lakes containing text, images and tables. — [arXiv 2308.03424](https://arxiv.org/abs/2308.03424)
- **Cost and accuracy guarantees for LLM operators:** model cascades with guarantees (Zeighami, Shankar, Parameswaran 2025) — [arXiv 2509.02896](https://arxiv.org/abs/2509.02896); task cascades that use document fragments and surrogate operations (Shankar et al. 2026) — [arXiv 2601.05536](https://arxiv.org/abs/2601.05536); KV-cache-aware serving of semantic query plans (Kalypso, up to 4.57x faster) — [arXiv 2607.23815](https://arxiv.org/abs/2607.23815); in-database LLM inference in SQL (iPDB) — [arXiv 2601.16432](https://arxiv.org/abs/2601.16432).

**Family 3 — Hybrids and vision papers**
- **SUQL** (Liu, … Lam 2023) extends SQL with free-text primitives `SUMMARY` and `ANSWER`, so retrieval composes with structured access "in a formal, succinct, precise, and interpretable notation". On Yelp it found an entity satisfying all requirements **90.3%** of the time, against 63.4% for a linearization baseline. — [arXiv 2311.09818](https://arxiv.org/abs/2311.09818)
- **TAG — "Text2SQL is Not Enough"** (Biswal, Patel, … Zaharia, Gonzalez et al. 2024) argues that Text2SQL covers only questions expressible in relational algebra, while RAG covers only "point lookups to one or a few data records". It proposes Table-Augmented Generation and reports that standard methods answer **≤20%** of TAG-Bench queries correctly. — [arXiv 2408.14717](https://arxiv.org/abs/2408.14717)
- Data-lake visions: an end-to-end declarative system with "multi-modal operators" that extend relational operations with AI-composed ones (Wang et al. 2025) — [arXiv 2504.02059](https://arxiv.org/abs/2504.02059); TAIJI, MCP-based multi-modal analytics on data lakes that names "accuracy, efficiency, and freshness" as the gaps (Zhang … Fan 2025) — [arXiv 2505.11270](https://arxiv.org/abs/2505.11270).
- *Deep Research is the New Analytics System* (Russo & Kraska; CIDR 2026) proposes a runtime in which Deep Research agents write and run optimized semantic-operator programs. It reports up to 1.95x better F1 than an open Deep Research agent and up to 76.8% cost savings even when the agent has semantic operators as tools. — [arXiv 2509.02751](https://arxiv.org/abs/2509.02751); [CIDR 2026 page](https://vldb.org/cidrdb/2026/deep-research-is-the-new-analytics-system-towards-building-the-runtime-for-ai-driven-analytics.html)

### Inferences
- **Taxonomy for the user's toolkit.** The literature supports a three-way split by *where the LLM runs relative to the query*:
  - **Ingest-time (ETL)**: EVAPORATE, ZenDB, ReDD, DeepDive, SystemT, Text-to-Table.
  - **Query-time (semantic operators)**: LOTUS, Palimpzest, DocETL, UQE, Luna, Galois, BigQuery.
  - **Plan-time only**: an LLM writes a deterministic query or extraction program that is then executed (EVAPORATE code synthesis, Text-to-SQL, CAESURA, Deep Research runtime).

  Determinism decreases from ingest-time, to plan-time with frozen artifacts, to query-time.
- **Method comparison through the determinism lens** (derived from the cited findings above):

| Method family | How it works | Determinism / reproducibility | Accuracy evidence | Cost profile | Main failure modes |
|---|---|---|---|---|---|
| LLM direct extraction to tables (ZenDB, ReDD, Palimpzest-style convert) | LLM fills a schema once per document; SQL afterwards | Query-time fully deterministic over the materialized snapshot; ingestion non-deterministic unless outputs are versioned | ZenDB +61% precision / +80% recall vs RAG (author); ReDD errors 30% to under 1% (author); UDA-Bench F1 0.5–0.66 on hard domains (independent) | One LLM pass per document × attribute, amortized over all queries | Schema coverage (attributes not anticipated), extraction errors, chunking misses |
| LLM-synthesized extraction code (EVAPORATE-CODE+) | LLM writes functions; functions run over all docs | Code is deterministic once frozen; re-synthesis is not | Beats SOTA with 110x fewer tokens (author); Evaporate worst F1 in UDA-Bench (independent) | Sublinear LLM use; cheapest (3.5 K tokens/doc in UDA-Bench) | Brittle on heterogeneous or free text |
| Rule/algebraic IE (SystemT) | Declarative rules + optimizer | Fully deterministic | Domain-specific | Engineering-heavy | Low recall on informal text |
| Query-time semantic operators (LOTUS, Palimpzest, DocETL, UQE, BigQuery AI) | LLM evaluated inside the plan per query | Non-deterministic per query (LLM nondeterminism + sampling-based optimizers); statistical guarantees at best | SemBench quality 0.68–0.82 avg; join/rank queries 0.21–0.78 (independent) | Paid on every query; ~2,000x spread across systems | Cost, latency, variance, no exact counts |
| Hybrid SQL+text (SUQL, TAG, ThalamusDB) | Exact SQL over structured part + LLM primitives for text | Structured part deterministic; text primitives not | SUQL 90.3% vs 63.4% (author); TAG baselines ≤20% (author) | Medium | Boundary between exact and LLM parts leaks nondeterminism |

- The finding that **extract-then-evaluate beats direct LLM filtering** (UDA-Bench) is independent evidence that materializing typed attributes is good for accuracy as well as for determinism.

### Gaps
- No survey I found is dedicated to "unstructured data to database for agent retrieval" or explicitly compares ETL and query-time approaches on determinism. The taxonomy above is my synthesis.
- I could not find a head-to-head study measuring **run-to-run result-set stability** (as opposed to averaged accuracy) of the semantic-operator systems. SemBench reports only means ± std over 5 runs.
- Venue status of several 2025–2026 arXiv items (Agent-first, LOTUS journal version, ZenDB) was not verified.

---

## 2. Sources of nondeterminism, end to end

### Takeaway
Nondeterminism enters at four layers:
- **LLM inference.** Temperature 0 is not deterministic, mainly because kernels are not batch-invariant under dynamic batching, plus TP size, GPU type and precision. It can be fixed at a 24–100%+ throughput cost.
- **Approximate vector search.** ANN is approximate by design, filtered ANN can silently drop rows, and multi-threaded HNSW builds produce different graphs.
- **Representation drift.** Embedding-model upgrades and hosted-model drift change the stored representation.
- **Exact systems with unspecified order.** Score ties broken by internal IDs, and SQL without a total `ORDER BY`.

Freshness (changing data) breaks "same answer" unless queries are pinned to a snapshot.

### Cited Findings

**LLM inference**
- Thinking Machines (Horace He et al., Sept 10 2025) argues that the "concurrency + floating point" explanation is incomplete. LLM forward passes generally avoid atomic adds and are run-to-run deterministic for a fixed batch; the real culprit is the lack of **batch invariance**, because server load changes batch size, which changes reduction order. Three kernels need batch-invariant versions: RMSNorm, matmul (no Split-K; a single kernel config, about 20% slower than cuBLAS) and attention (fixed-size split-KV; KV cache updated before attention). — [Thinking Machines blog](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)
  - Experiment: Qwen3-235B-A22B at temperature 0 gave **80 unique completions out of 1,000**, diverging at token 103. With batch-invariant kernels all 1,000 were identical. On Qwen-3-8B, vLLM took 26 s by default, 55 s deterministic unoptimized and 42 s with improved attention (≈1.6x). — [Thinking Machines blog](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)
- SGLang deterministic mode (LMSYS, Sept 22 2025) builds on those kernels and is compatible with chunked prefill, CUDA graphs and radix cache. It averages a **34.35% slowdown** (24–55% by workload), versus 61.5% reported by Thinking Machines. Normal mode gave 3–4 unique outputs over 50 trials (up to 18 on prefix-cache cases); deterministic mode gave 1. With temperature > 0, determinism comes from a per-request seed (seeded Gumbel noise). — [LMSYS blog](https://lmsys.org/blog/2025-09-22-sglang-deterministic/)
- Atil et al. (2024) tested 5 LLMs "configured to be deterministic" on 8 tasks × 10 runs. Accuracy varied **up to 15%** across runs, with up to a 70% gap between best and worst possible. None was consistently repeatable. They propose the TARr@N and TARa@N agreement metrics. — [arXiv 2408.04667](https://arxiv.org/abs/2408.04667)
- Yuan et al. (2025): under BF16 greedy decoding, DeepSeek-R1-Distill-Qwen-7B showed **up to 9% accuracy variation** and a 9,000-token difference in response length depending on GPU count, GPU type and batch size. The proposed fix, LayerCast, keeps weights in 16-bit and computes in FP32. — [arXiv 2506.09501](https://arxiv.org/abs/2506.09501)
- Determinism across tensor-parallel sizes needs TP-invariant kernels (TBIK, a tree-structured reduction), which give bit-wise identical results regardless of TP size. — [arXiv 2511.17826](https://arxiv.org/abs/2511.17826)
- Scheduler-based alternatives:
  - **LLM-42** decodes on a non-deterministic fast path and verifies and rolls back under a fixed-shape reduction schedule, so overhead is paid only for traffic that needs determinism. — [arXiv 2601.17768](https://arxiv.org/abs/2601.17768)
  - **CoRun** relies on position invariance plus fixed-shape decode. It reports that batch-invariant kernels cost more than 2x latency and up to 74% throughput, and that CoRun is 15–324% faster than them. — [arXiv 2608.14376](https://arxiv.org/abs/2608.14376)
- **Vosti** (Sept 2026) formalizes deterministic inference as "bitwise-identical logits" for the same prompt and sampler state under a fixed model and deployment configuration. Its tests found that **vLLM's batch-invariant mode and SGLang's deterministic mode still produced different logits under some execution variations**. Vosti is formally verified (Verus plus a Triton analyzer) and runs at speed comparable to vLLM's BI mode on decode-heavy work. — [arXiv 2609.38981](https://arxiv.org/abs/2609.38981)
- Token-probability analysis: nondeterminism mostly perturbs tokens with probability between 0.1 and 0.9 and barely affects those near 0 or 1. Any temperature > 0 therefore amplifies it. — [arXiv 2601.06118](https://arxiv.org/abs/2601.06118)
- Hosted API caveat: OpenAI's seed parameter is best-effort. Outputs are "mostly identical" only if the seed, the parameters and `system_fingerprint` all match, and the fingerprint changes when OpenAI updates its serving configuration. — [OpenAI Cookbook](https://cookbook.openai.com/examples/reproducible_outputs_with_the_seed_parameter)
- **Model drift over time**: GPT-4 classification of genetic-variant evidence showed "substantial differences in intraday (nondeterminism) and across day (drift) results" over Dec 2023 to Feb 2024. — [arXiv 2312.13521](https://arxiv.org/abs/2312.13521)

**ANN / vector search**
- pgvector: exact search is the default and "provides perfect recall". Adding an approximate index trades recall for speed, and "you will see different results for queries after adding an approximate index". Filtering happens **after** the index scan: with HNSW at the default `ef_search` = 40, a condition matching 10% of rows returns about 4 rows on average. Iterative scans (0.8.0+) offer a `strict_order` mode and a `relaxed_order` mode, where results may be "slightly out of order". — [pgvector README](https://github.com/pgvector/pgvector)
- Faiss: by default seeds are fixed and multi-threaded computations use static scheduling, so "several runs of the same operation with the same number of threads give the same result bitwise". The exceptions are PCA/OPQ training (LAPACK eigen-decomposition, machine-precision differences) and **HNSW `add`, which "is performed in an unspecified order"**. "Search is deterministic." — [Faiss wiki](https://github.com/facebookresearch/faiss/wiki/Threads-and-asynchronous-calls)
- HNSW builds its multi-layer graph incrementally, so the graph depends on insertion order. — [arXiv 1603.09320](https://arxiv.org/abs/1603.09320). The Faiss library paper describes the accuracy/speed/memory trade-off space of vector indexes. — [arXiv 2401.08281](https://arxiv.org/abs/2401.08281). ANN-Benchmarks evaluates algorithms by recall at speed across parameter settings, which presumes sub-1.0 recall. — [arXiv 1807.05614](https://arxiv.org/abs/1807.05614)
- Hybrid vector + structured predicate search is a recognized hard problem: existing methods "suffer from poor performance or support a severely restricted set of search predicates" (ACORN). — [arXiv 2403.04871](https://arxiv.org/abs/2403.04871)
- **Embedding model upgrades:** these typically require "re-encoding the entire corpus and rebuilding the ANN index". Drift-Adapter maps new queries into the old space and recovers 95–99% of re-embedding recall. That is close, but by construction not identical results. — [arXiv 2509.23471](https://arxiv.org/abs/2509.23471). Backward-compatible representation learning addresses the same "backfilling" problem. — [arXiv 2003.11942](https://arxiv.org/abs/2003.11942)
- Theoretical ceiling: the number of distinct top-k subsets that single-vector embeddings can return is bounded by the embedding dimension. State-of-the-art models fail on the simple LIMIT dataset. — [arXiv 2508.21038](https://arxiv.org/abs/2508.21038)

**Exact systems are not automatically deterministic either**
- Lucene breaks score ties by internal doc IDs. Multi-threaded indexing assigns IDs inconsistently, so "score ties are broken unpredictably" and rankings differ between index instances of the same collection (Lin & Yang, SIGIR 2019). — [arXiv 1807.05798](https://arxiv.org/abs/1807.05798)
- PostgreSQL: "If sorting is not chosen, the rows will be returned in an unspecified order." With `LIMIT`/`OFFSET` but no `ORDER BY` that constrains rows "into a unique order", "you will get an unpredictable subset", because the planner picks different plans for different LIMIT values. "This is not a bug." — [PostgreSQL docs: LIMIT](https://www.postgresql.org/docs/current/queries-limit.html); [PostgreSQL docs: ORDER BY](https://www.postgresql.org/docs/current/queries-order.html)

**LLM-generated queries (the plan-time layer)**
- In a BIRD text-to-SQL study with 50 independent attempts per problem, success rose 14–70% with more attempts, and distinct sub-plans were "less than 10–20% of the total". Repeated LLM query generation is both variable and highly redundant. — [arXiv 2509.00997](https://arxiv.org/html/2509.00997v2)

### Inferences
- In a deterministic-retrieval stack, an LLM can be confined to two places: (a) **ingestion**, whose outputs are persisted and versioned, and (b) **query synthesis**, whose generated SQL/Cypher should be logged and replayable. Inference-level determinism (batch-invariant kernels) is now feasible for self-hosted models at roughly 1.3–2x cost, but Vosti shows that even "deterministic modes" are not guaranteed. Hosted APIs give only best-effort seeds. Persisting the LLM's *outputs* is therefore more robust than relying on bit-reproducible inference.
- Determinism checklist derived from the sources:
  - exact scans or exact indexes for predicates;
  - a total order (`ORDER BY` on a unique key) for every ordered or `LIMIT` query;
  - stable doc IDs assigned deterministically, not by thread order;
  - pinned snapshot or version;
  - pinned embedding-model version if vectors are used at all;
  - single-threaded or recorded-order HNSW builds if ANN is used for candidate generation;
  - recorded model, prompt and `system_fingerprint` for every extraction.

### Gaps
- No peer-reviewed measurement of run-to-run nondeterminism of **hosted embedding APIs** (as opposed to generation) was found.
- No academic study found that quantifies how often ANN results change across *index rebuilds* in production vector DBs. Evidence is the Faiss documentation plus project issue reports (not cited, low quality).

---

## 3. How databases achieve determinism and reproducibility (snapshots, time travel, MVCC, versioned tables, provenance)

### Takeaway
Databases make answers reproducible through three layers of guarantees:
- **Exact semantics**: relational algebra over typed tuples, with a total order when one is requested.
- **Snapshot semantics**: MVCC or snapshot isolation within a transaction, and time travel or versioned tables across time (Delta Lake, Iceberg, SQL:2011 system-versioned tables, OrpheusDB, Decibel).
- **Provenance semantics**: lineage/why-provenance (which input tuples witness an output), where-provenance (where a value was copied from) and how-provenance (provenance semirings: how inputs combined).

Together they let the same query on the same snapshot return the same result and explain it, which is exactly the property the user wants to extend to document-derived data.

### Cited Findings
- **MVCC foundations:** Bernstein & Goodman (TODS 1983) give the theory for multiversion databases, where "each write on a data item produces a new copy (or version)", and analyze the correctness of multiversion concurrency control. — [ACM DOI 10.1145/319996.319998](https://doi.org/10.1145/319996.319998)
- **Snapshot Isolation defined:** Berenson et al. (SIGMOD 1995) show that the ANSI SQL-92 phenomena fail to characterize popular isolation levels, and they define **Snapshot Isolation** as a multiversion isolation type. — [arXiv cs/0701157](https://arxiv.org/abs/cs/0701157)
- **MVCC in practice:** MVCC dates to a 1979 dissertation and InterBase (1981). It is used by Oracle (since 1984), Postgres (since 1985) and InnoDB (2001), and by almost every new transactional DBMS, although there is no standard implementation. — [Wu et al., PVLDB 2017](https://www.vldb.org/pvldb/vol10/p781-Wu.pdf)
- PostgreSQL Repeatable Read "only sees data committed before the transaction began; it never sees … changes committed by concurrent transactions during the transaction's execution". — [PostgreSQL docs: isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
- **Temporal tables:** SQL:2011's headline feature is temporal tables, "tables whose rows are associated with one or more temporal periods" (system-versioned and application-time). — [Kulkarni & Michels, SIGMOD Record 2012](https://sigmodrecord.org/publications/sigmodRecord/1209/pdfs/07.industry.kulkarni.pdf)
- **Lakehouse table formats:**
  - Delta Lake provides ACID transactions on object stores and "time travel to let users query point-in-time snapshots or roll back". Time travel is "useful for reproducible data science and machine learning", and is integrated with MLflow to "automatically record which version of a dataset was used to train an ML model". — [Armbrust et al., PVLDB 2020](https://www.vldb.org/pvldb/vol13/p3411-armbrust.pdf)
  - The Lakehouse paper (CIDR 2021) argues for open direct-access formats (Parquet) plus warehouse management features, addressing "data staleness, reliability…". — [Armbrust et al., CIDR 2021](https://www.cidrdb.org/cidr2021/papers/cidr2021_paper17.pdf)
  - Apache Iceberg's spec goal is **serializable isolation**: "Reads will be isolated from concurrent writes and always use a committed snapshot of a table's data". All changes "create a new metadata file and replace the old metadata with an atomic swap". "A snapshot represents the state of a table at some time." Time-travel queries such as `SELECT … TIMESTAMP AS OF …` resolve through the snapshot-log. — [Iceberg Table Spec](https://iceberg.apache.org/spec/)
- **Dataset versioning in relational systems:**
  - OrpheusDB "bolts on" version control to a relational DB, with version retrieval up to 20x faster via LYRESPLIT partitioning. — [Huang et al., PVLDB 2017](https://www.vldb.org/pvldb/vol10/p1130-huang.pdf)
  - Decibel provides git-like branching for relational datasets. It is motivated by teams having "no systematic way to record which version of a dataset was used for an experiment". — [Maddox et al., PVLDB 2016](https://www.vldb.org/pvldb/vol9/p624-maddox.pdf)
- **Provenance theory:**
  - **Lineage** (Cui, Widom, Wiener, TODS 2000): for a tuple in a materialized warehouse view, identify the set of source tuples that produced it, including for views with aggregation. — [dblp/ACM 10.1145/357775.357777](https://dblp.org/rec/journals/tods/CuiWW00.html)
  - **Why- vs where-provenance** (Buneman, Khanna, Tan, ICDT 2001): why-provenance is the source data that justifies whether a result exists; where-provenance is the source locations a result value was copied from. The paper covers relational and hierarchical (XML) data. — [UPenn repository](https://repository.upenn.edu/cis_papers/210)
  - **Provenance semirings** (Green, Karvounarakis, Tannen, PODS 2007): K-relations annotated with elements of a commutative semiring unify bag semantics, incomplete and probabilistic databases, and why-provenance. The polynomial semiring N[X] is the most general (how-)provenance, and the approach extends to Datalog. — [PODS 2007 PDF](https://web.cs.ucdavis.edu/~green/papers/pods07.pdf)
  - **Survey** (Cheney, Chiticariu, Tan, FnT 2009): unifies why-, how- and where-provenance. Lineage is defined via "witnesses": a subset of input records "sufficient to ensure that a given output tuple appears in the result". — [FnT survey PDF](https://homepages.inf.ed.ac.uk/jcheney/publications/provdbsurvey.pdf)
- **DB-community proposals for confining LLM nondeterminism:**
  - Kim & Ailamaki (2026, vision) put the project in "a deterministic, versioned dataflow engine (in effect, a query plan over materialized views)". The LLM is "a stochastic compiler that may only edit that plan", and "the executor never calls the LLM". Their rules: D1 determinism (runtime is a function of pinned inputs; re-materialization is byte-identical), D2 append-only versioned log, D3 confinement (edit is the only stochastic relation), D4 idempotence (cache keyed by signature) and D5 evidence gate ("a claim becomes part of the record only by running"). — [arXiv 2607.10508](https://arxiv.org/abs/2607.10508); [HTML](https://arxiv.org/html/2607.10508v1)
  - Agent-first data systems call for "multi-world isolation" and branching ("MVCC on steroids"). They cite Neon, where agents created 20x more branches and performed 50x more rollbacks than humans. — [arXiv 2509.00997](https://arxiv.org/html/2509.00997v2)
  - Madden et al. raise the open problem that derived data (summaries, extractions) needs tracked relationships to base data: "Similar issues arise in data provenance, versioning, and materialized views". A system "might provide a transaction-like guarantee that the set of documents considered throughout the transaction would not change". — [PVLDB 2024 PDF](https://vldb.org/pvldb/vol17/p4546-madden.pdf)

### Inferences
- Map to the toolkit:
  - Treat each extraction run as producing an **immutable, versioned table snapshot** (Iceberg/Delta snapshot or SQL:2011 system-versioned table) keyed by (source-file hash, parser version, model id/fingerprint, prompt hash).
  - Store **where-provenance** per cell: document id, page, character or bbox span.
  - Store **why-provenance** per derived row (the set of source spans that witness it).
  - Answer agent queries `AS OF` a snapshot id.

  This reuses 25–40 years of settled theory rather than inventing new guarantees. Semiring (how-)provenance is the natural fit for aggregates and joins over extracted facts: it says which spans contributed to a count.

### Gaps
- I found no paper that applies provenance semirings or where-provenance specifically to **LLM-extracted cell values with character-span sources**. Kim & Ailamaki and Madden et al. raise the need but do not give a formal model. Other tracks (document parsing, grounding) may cover span-level grounding tools.
- The Bernstein & Goodman and Buneman et al. full texts were not read. Claims rely on abstracts and repository summaries.

---

## 4. Arguments and evidence for structured/deterministic retrieval vs vector RAG, and the limits

### Takeaway
Evidence from several groups, mostly author-reported but corroborated by independent long-context benchmarks, shows that RAG and plain LLMs fail at aggregation, counting, exhaustive filtering and cross-document alignment. Materializing typed records and querying them exactly gives large precision and recall gains on analytical questions. The limits are equally clear. Extraction error on hard domains is still large (independent F1 about 0.5–0.66 on Legal, Finance and Healthcare), schemas must anticipate the question, and NL-to-query translation reintroduces ambiguity and nondeterminism.

### Cited Findings
- **Against RAG / long-context for analytics:**
  - ZenDB is up to 61% / 80% better than RAG on precision / recall (author). — [arXiv 2405.04674](https://arxiv.org/abs/2405.04674)
  - Aryn shows "better accuracy than RAG on analytics queries" over NTSB (author). — [arXiv 2409.00847](https://arxiv.org/abs/2409.00847)
  - ReDD: "RAG lack[s] schema awareness and struggle[s] with cross-document alignment, leading to high error rates". — [arXiv 2511.02711](https://arxiv.org/abs/2511.02711)
  - TAG: RAG handles only "point lookups to one or a few data records", and baselines answer ≤20% of queries (author). — [arXiv 2408.14717](https://arxiv.org/abs/2408.14717)
- **Independent long-context evidence:**
  - HoloBench (database operations rendered as text): RAG struggles with aggregation across documents, and LCLM performance depends more on the *amount of information* than on context length. Aggregation tasks degrade noticeably, while max/min queries are easier for LCLMs (and hard for RAG). — [arXiv 2410.11996](https://arxiv.org/abs/2410.11996)
  - Oolong (classification + counting over many chunks): GPT-5, Claude-Sonnet-4 and Gemini-2.5-Pro all score **<50%** at 128K. — [arXiv 2511.02817](https://arxiv.org/abs/2511.02817)
  - "Lost in the Middle": accuracy drops when the relevant information sits in the middle of long contexts. — [arXiv 2307.03172](https://arxiv.org/abs/2307.03172)
- **Embedding expressivity ceiling:** top-k subsets are bounded by dimension, and SOTA embedders fail LIMIT (independent of the RAG vendors). — [arXiv 2508.21038](https://arxiv.org/abs/2508.21038)
- **Auditability / traceability:**
  - ALCE: "even the best models lack complete citation support 50% of the time" on ELI5. — [arXiv 2305.14627](https://arxiv.org/abs/2305.14627)
  - The RAG survey itself lists "untraceable reasoning processes" as a core LLM problem that RAG only partially fixes. — [arXiv 2312.10997](https://arxiv.org/abs/2312.10997)
- **Hybrid wins:**
  - SUQL 90.3% vs 63.4% for a linearization baseline. — [arXiv 2311.09818](https://arxiv.org/abs/2311.09818)
  - StructRAG argues that knowledge-intensive reasoning needs "inference-time hybrid information structurization" (tables, graphs, etc.) because the needed information is "badly scattered". — [arXiv 2410.08815](https://arxiv.org/abs/2410.08815)
- **Limits of structuring:**
  - UDA-Bench (independent): best F1 about 0.66 / 0.52 / 0.51 on Legal / Finance / Healthcare. Chunk-based extraction misses information. Clustering-based aggregation has "very high" relative error. Search-based joins wrongly prune joinable documents. — [UDA-Bench](https://arxiv.org/html/2510.27119v1)
  - EVAPORATE: code-based extraction is "far less accurate" than direct LLM extraction unless ensembled. — [arXiv 2304.09433](https://arxiv.org/abs/2304.09433)
  - Galois: precisely fitting text to a schema "is a challenging task". — [arXiv 2304.00472](https://arxiv.org/abs/2304.00472)
  - Fernandez et al.: "What the person who produced a dataset meant when they designed the schema is not necessarily aligned with what the consumer believes that schema means." Semantic ambiguity makes integration hard, and the "tails" remain manual. — [PVLDB 2023 PDF](https://www.vldb.org/pvldb/vol16/p3302-fernandez.pdf)
  - TAG: Text2SQL covers only questions expressible in relational algebra. — [arXiv 2408.14717](https://arxiv.org/abs/2408.14717)
  - Text-to-SQL must handle "NL ambiguity and under-specification". — [arXiv 2408.05109](https://arxiv.org/abs/2408.05109)
- **Controlling extraction error:**
  - ReDD's calibrated error detection with coverage guarantees reduces errors to <1% with human correction in the loop (author). — [arXiv 2511.02711](https://arxiv.org/abs/2511.02711)
  - LOTUS gives accuracy guarantees relative to a gold algorithm (author). — [arXiv 2407.11418](https://arxiv.org/abs/2407.11418)

### Inferences
- The evidence supports a **two-tier design**:
  - **Tier 1:** deterministic exact queries over materialized, provenance-annotated typed records for the questions the schema covers (counts, filters, joins, aggregates, lookups).
  - **Tier 2:** an explicit, logged fallback (semantic operator or RAG over source spans) for questions outside the schema. The fallback is labeled non-deterministic, and its outputs can be *promoted* into the schema (new attribute extraction, versioned) once a question recurs.

  This pairs the precision of ETL with the coverage of query-time operators.
- Extraction error is the dominant risk. A deterministic query over wrong extracted values is reproducibly wrong, so calibrated error detection (ReDD-style), extract-then-evaluate filtering and per-cell provenance for audit matter more than inference determinism.

### Gaps
- Few independent head-to-head studies compare "ETL + SQL" with "vector RAG" on the same corpus and questions. Most RAG-vs-structured numbers come from the authors of the structured systems.
- No study found that quantifies schema-coverage failure rates (the share of real agent questions answerable from a pre-built schema).

---

## 5. Positions from the database research community (CIDR/VLDB/SIGMOD 2023–2026)

### Takeaway
The DB community's consensus position, across UChicago, MIT, Berkeley, CMU, EPFL and Stanford, is to bring **declarativity, optimization, versioning and provenance** to LLM-era data. Its members disagree on *where* the LLM sits. MIT and Berkeley mostly build query-time semantic-operator systems and accept statistical rather than exact guarantees. Stonebraker and Pavlo argue that vector search is just an index feature that RDBMSs absorb. Kim and Ailamaki argue for confining all stochasticity to a compiler that edits a deterministic, versioned plan.

### Cited Findings
- **Fernandez, Elmore, Franklin, Krishnan, Tan (PVLDB 2023):** LLMs will push past the "automation ceiling" in entity resolution, schema matching, data discovery and query synthesis, and they "blur the line between predictive models and information retrieval systems". Classical DBs "represent data through symbols … associated with their meaning", whereas LLMs evaluate queries via "algebraic operations on the numerical representations". The authors call LLMs "highly complex and unpredictable tools" (citing GPT-4 behavior changes) and propose provenance as an enabling mechanism for attribution. — [PVLDB PDF](https://www.vldb.org/pvldb/vol16/p3302-fernandez.pdf)
- **Madden, Cafarella, Franklin, Kraska, "Databases Unbound" (PVLDB 2024):**
  - Desiderata: scale to millions of documents, efficiency, and being "consistent and correct in their answers".
  - "A declarative interface – inspired by relational languages like SQL – is the answer". The optimizer chooses models, prompts and thresholds.
  - "Users of database systems expect answers to be correct, but new AI systems are unreliable." They propose verification operators, majority voting, a "recipe box" that reuses generated prompts or programs "helping to maintain consistency", and code generation that replaces LLM calls.
  - "It's unclear what consistency even means in an AI world".
  - — [PVLDB PDF](https://vldb.org/pvldb/vol17/p4546-madden.pdf)
- **Stonebraker & Pavlo, "What Goes Around Comes Around… And Around…" (SIGMOD Record 2024):** vector DBMSs are document-model systems with ANN indexes. Most vendors "integrated an open-source library (e.g., pgVector, DiskANN, FAISS)". The authors predict that vector DBMSs will become "more relational-like (e.g., SQL, transactions, extensibility)" while "relational incumbents will have added vector indexes to their already long list of features". — [CMU PDF](https://db.cs.cmu.edu/papers/2024/whatgoesaround-sigmodrec2024.pdf)
- **Berkeley:**
  - **"LLM-Powered Proactive Data Systems"** (Zeighami, Lin, Shankar, Parameswaran; IEEE Data Eng. Bull. 2025) criticizes systems that treat LLMs as opaque "approximate, expensive UDFs" and argues that systems should understand the operations, the data and the user intent to "ensure correctness". — [arXiv 2502.13016](https://arxiv.org/abs/2502.13016)
  - **"Supporting Our AI Overlords"** (Liu et al. 2025) predicts that agents will be the dominant workload ("agentic speculation": scale, heterogeneity, redundancy, steerability). It calls for satisficing or approximate answers during exploration but "more accurate answers during solution formulation", plus branching with multi-world isolation. — [arXiv 2509.00997](https://arxiv.org/abs/2509.00997)
  - **TAG** (CIDR 2025, Berkeley/Stanford): "Text2SQL is not enough". — [arXiv 2408.14717](https://arxiv.org/abs/2408.14717)
- **MIT:**
  - Palimpzest (CIDR 2025) — [arXiv 2405.14696](https://arxiv.org/abs/2405.14696)
  - Abacus (PVLDB 2026) — [arXiv 2505.14661](https://arxiv.org/abs/2505.14661)
  - Deep Research runtime (CIDR 2026) — [arXiv 2509.02751](https://arxiv.org/abs/2509.02751)
- **Industry (CIDR 2025):** Aryn argues for explainability as a requirement for trust. — [arXiv 2409.00847](https://arxiv.org/abs/2409.00847)
- **EPFL (2026 vision):** Kim & Ailamaki, "Confining Nondeterminism": databases "earn trust without being watched, because deterministic operators over well-defined state make their guarantees hold by construction". The paper reports no experiments yet (prototype deferred). — [arXiv 2607.10508](https://arxiv.org/abs/2607.10508)
- **TU Darmstadt:** CAESURA (CIDR 2024), LLMs as query planners over multi-modal lakes. — [arXiv 2308.03424](https://arxiv.org/abs/2308.03424)
- **Earlier Stanford line (Ré group):** FMs for wrangling (PVLDB 2022) — [arXiv 2205.09911](https://arxiv.org/abs/2205.09911); EVAPORATE (PVLDB 2023) — [arXiv 2304.09433](https://arxiv.org/abs/2304.09433); DeepDive (2015) — [arXiv 1502.00731](https://arxiv.org/abs/1502.00731).

### Inferences
- For an agent-retrievable data lake, the community's strongest positions converge on:
  - declarative, typed interfaces, with natural language as a front end that compiles to SQL;
  - LLM output treated as versioned data or code, not as a live oracle;
  - vector search as one index type inside a relational/lakehouse engine;
  - provenance and versioning as first-class.

  The user's "convert first, query exactly" goal sits closest to EVAPORATE / ZenDB / ReDD plus Kim–Ailamaki-style confinement, while semantic operators serve as the coverage fallback.

### Gaps
- I did not find a 2023–2026 SIGMOD or VLDB *keynote* transcript specifically on deterministic retrieval. Positions above come from papers.
- Whether "Supporting Our AI Overlords" and ZenDB appeared at a peer-reviewed venue was not verified here.
