# Hybrid structured/unstructured retrieval: when database retrieval beats vector RAG, and how systems combine them (Track 08)

Scope: head-to-head evidence on structured retrieval (SQL / graph / key lookups over typed records) vs. vector (chunk-similarity) RAG by question type, plus hybrid architectures and routers. Text-to-SQL internals are out of scope (another track). Labels: **[author]** = a paper's claim about its own method; **[indep]** = a paper evaluating methods it did not build (or a benchmark paper evaluating others). Years are first arXiv versions unless a venue is given. Numbers are copied from the papers' tables; none were re-run here.

---

## Q1. Structured RAG and restructuring at query time or index time: methods, how they work, determinism, accuracy, cost, failure modes

### Takeaway
There are three families. (a) **Query-time restructuring** (StructRAG, SRAG/DocSage, Chain-of-Table, Dater, TabSQLify, Binder) has an LLM build a table, graph or sub-table per question. It improves accuracy but is not deterministic, because the structure is rebuilt by an LLM on every query. (b) **Index-time conversion into typed stores** (ZenDB, Evaporate, TableRAG-heterogeneous, NeuSym-RAG, IE→SQL in QO-Bench, DualGraph's symbolic KG, Aryn/Sycamore) moves the LLM work to ingestion. Once the extracted store is frozen, the retrieval step is exact SQL/SPARQL/Cypher. (c) **Unified-text approaches** (UniK-QA, UDT-QA) go the other way and verbalize tables and KBs into text for a single dense retriever. That works well for point lookups but gives up SQL operators. For a toolkit whose goal is deterministic retrieval, family (b) is the relevant design. Families (a) and (c) are useful mainly as baselines and as fallbacks.

### Cited Findings

**Query-time restructuring (LLM builds a structure per question)**
- **StructRAG (2024)**. A DPO-trained "hybrid structure router" picks one of five structure types (table, graph, algorithm, catalogue, chunk). A "structurizer" LLM rewrites the retrieved documents into that structure, and a "utilizer" answers from it. Router: Qwen2-7B trained on 900 preference pairs; structurizer and utilizer: Qwen2-72B. [author] — [StructRAG](https://arxiv.org/abs/2410.08815)
- StructRAG accuracy on the Loong benchmark (LLM-judge score) [author, but baselines re-run by the authors]. Set 1 (10K–50K tokens): StructRAG 69.43 vs long-context 60.11, chunk RAG 46.11, GraphRAG 40.82. Set 4 (200K–250K tokens): 51.42 vs 28.92 / 29.29 / 23.47. Exact-match rates stay low, though (0.35 on Set 1, 0.10 on Set 4). — [StructRAG](https://arxiv.org/abs/2410.08815)
- StructRAG routing matters a lot. Replacing the router with random routing drops the overall score from 60.38 to 45.33. Forcing "only table" for every task gives 49.66. Router accuracy: 94.38% for the DPO-trained 7B router, vs 90.06% for Qwen2-72B few-shot, 80.56% for 72B zero-shot and 54.25% for 7B zero-shot. [author] — [StructRAG](https://arxiv.org/abs/2410.08815)
- **SRAG (2025)**. Generates a SPARQL query over Wikidata to find the entity set, has GPT-4 propose a table schema, has an LLM fill one row per entity from retrieved pages, then has GPT-4 write SQL over that table. On the MEBench test set (1,374 questions) overall accuracy is 0.889 vs 0.593 for GPT-4+RAG. On "statistics" questions it is 0.908 vs 0.410; on comparison, 0.934 vs 0.763. [author; MEBench comes from the same group] — [SRAG](https://arxiv.org/abs/2503.01346); [MEBench](https://arxiv.org/abs/2502.18993)
- SRAG failure modes. Table-filling omissions occur in about 0.1% of more than 2,000 fill instances. Synonyms in the same column ("US" vs "America") break SQL `SELECT` predicates. The SPARQL step sometimes picks the wrong relation ("instance of" instead of "position held"). — [SRAG](https://arxiv.org/abs/2503.01346)
- **DocSage (2026)**, from the same group as SRAG. Adds dynamic discovery of a "minimal joinable schema", error-aware extraction into relational tables, and SQL-based reasoning. Reports more than 27% accuracy improvement over baselines on two multi-document multi-entity QA benchmarks. [author] — [DocSage](https://arxiv.org/abs/2603.11798)
- **Table-reasoning lineage (single given table)**:
  - Binder (2022) binds LM calls inside SQL/Python. It reached SOTA on WikiTQ and TabFact using only dozens of exemplars, and its outputs are inspectable programs. — [Binder](https://arxiv.org/abs/2210.02875)
  - Dater (SIGIR 2023) decomposes a huge table into sub-evidence and uses "parsing-execution-filling" to separate logic from numerical computation. — [Dater](https://arxiv.org/abs/2301.13808)
  - Chain-of-Table (ICLR 2024) evolves the table through chained operations. SOTA on WikiTQ, FeTaQA and TabFact at the time. — [Chain-of-Table](https://arxiv.org/abs/2401.04398)
  - TabSQLify (NAACL 2024) uses text-to-SQL to cut the table down to a relevant sub-table before reasoning: 64.7% on WikiTQ and 79.5% on TabFact with gpt-3.5-turbo. — [TabSQLify](https://arxiv.org/abs/2404.10150)
  - ReAcTable: 68.0% on WikiTQ using SQL/Python executors. — [ReAcTable](https://arxiv.org/abs/2310.00815)
  - H-STAR (NAACL 2025) picks semantic vs symbolic reasoning by question type. — [H-STAR](https://arxiv.org/abs/2407.05952)
  - Weaver (2025) interleaves SQL steps with LLM steps for tables that contain text. — [Weaver](https://arxiv.org/abs/2505.18961)
  - StructGPT (EMNLP 2023) uses an iterative "reading-then-reasoning" loop over KG, table and DB interfaces. — [StructGPT](https://arxiv.org/abs/2305.09645)
- **TableRAG (Google, NeurIPS 2024)**. For million-token tables it retrieves at the schema and cell level (with query expansion) instead of feeding the whole table. It reports SOTA on two new million-token benchmarks built from Arcade and BIRD-SQL. [author] — [TableRAG (Chen et al.)](https://arxiv.org/abs/2410.04739)

**Index-time conversion into typed stores (LLM at ingestion, exact query at retrieval)**
- **TableRAG (heterogeneous, EMNLP 2025)**. Keeps tables as MySQL tables instead of flattening them into chunks, with a text knowledge base alongside. It loops over query decomposition → text retrieval → SQL programming and execution → intermediate answer. On HeteQA (304 multi-hop heterogeneous questions), overall LLM-judge accuracy is 44.19 vs NaiveRAG 34.54 and ReAct 29.60 (Claude-3.5). On HybridQA it is 47.87 vs NaiveRAG 20.28 and ReAct 43.38. [author] — [TableRAG (Yu et al.)](https://arxiv.org/abs/2506.10380)
- **ZenDB (2024)**. Extracts "semantic hierarchical trees" from templated documents and answers ad-hoc SQL over them. Average precision across three datasets: 0.72 / 0.73 / 0.73, vs 0.51 / 0.12 / 0.36 for embedding-chunk RAG. Recall: 0.53 / 0.84 / 0.74 vs 0.38 / 0.13 / 0.38. Cost is roughly $0.03 per query per document (vs $0.02 for RAG). It is 29× / 10× / 4× cheaper than whole-document GPT-4. [author] — [ZenDB](https://arxiv.org/abs/2405.04674)
- **Evaporate (2023)**. Builds queryable tables from heterogeneous data lakes. Direct LLM extraction is accurate but expensive. Synthesizing extraction code is cheap but less accurate. The EVAPORATE-CODE+ variant ensembles many candidate functions with weak supervision and averages 110× fewer LLM tokens across 16 settings of 10k documents. [author] — [Evaporate](https://arxiv.org/abs/2304.09433)
- **NeuSym-RAG (ACL 2025)**. Parses PDFs into both a DuckDB relational database (metadata, sections, tables) and a multi-view vectorstore. An agent then picks `RetrieveFromDatabase` (SQL) or `RetrieveFromVectorstore` actions, iterating. On AirQA-REAL the average is 39.6 vs 10.5 for classic RAG, 15.6 for Graph-RAG and 11.8 for HybridRAG. On metadata-retrieval-type questions: 58.2 vs 9.4. The improvement over classic RAG is at least 17.3 points across LLMs. [author] — [NeuSym-RAG](https://arxiv.org/abs/2505.19754)
- **Aryn / Sycamore / Luna (CIDR 2025)**. Pipeline: DocParse turns PDFs into structured documents, `llmExtract` produces a schema loaded into OpenSearch, and an LLM planner runs semantic plans combining metadata filters and LLM filters. On 100 NTSB PDFs with 30 analytics questions: 20/30 correct vs 2/30 for RAG (RAG refused 8/30). [author/vendor] — [Aryn](https://arxiv.org/abs/2409.00847)
- **Declarative semantic-operator engines** (adjacent to this track). These turn unstructured data into relational-style plans whose operators are LLM calls:
  - LOTUS semantic operators: optimized with accuracy guarantees relative to a gold algorithm. — [LOTUS](https://arxiv.org/abs/2407.11418)
  - DocETL: agentic rewrites for accuracy. — [DocETL](https://arxiv.org/abs/2410.12189)
  - Palimpzest: cost-optimized declarative AI queries. — [Palimpzest](https://arxiv.org/abs/2405.14696)
  - UQE: an SQL dialect with natural-language conditions, executed by sampling. — [UQE](https://arxiv.org/abs/2407.09522)
  - FlockMTL (PVLDB 2025): LLM scalar/aggregate functions and RAG inside DuckDB, with `PROMPT`/`MODEL` as schema objects. — [FlockMTL](https://arxiv.org/abs/2504.01157)
  - BlendSQL: a SQLite superset with LLM "ingredients"; 35% fewer tokens on hybrid QA. — [BlendSQL](https://arxiv.org/abs/2402.17882)
  - SUQL: SQL plus `answer()`/`summary()` free-text primitives. — [SUQL](https://arxiv.org/abs/2311.09818)
- **SUQL results** [author]. HybridQA test: 59.0 EM / 68.4 F1 with in-context learning only, within 8.9 EM of a SOTA system trained on 62K examples. On a Yelp restaurant knowledge base it finds an entity satisfying all user requirements 90.3% of the time vs 63.4% for a baseline that linearizes the structured data into text. — [SUQL](https://arxiv.org/abs/2311.09818)
- **TAG (Table-Augmented Generation, 2024)** generalizes Text2SQL and RAG into query synthesis → execution → LM generation. On a benchmark of BIRD queries modified to need world knowledge or reasoning (match-based, comparison, ranking and aggregation types), with Llama-3.1-70B: hand-written TAG pipelines score 0.55 exact match, vs 0.17 for Text2SQL, 0.00 for RAG (E5 embeddings), 0.02 for retrieval + LM rerank and 0.13 for Text2SQL+LM. TAG is also fastest at 2.94 s average. — [TAG](https://arxiv.org/abs/2408.14717)
- **SWAN (CIDR 2025)**: "beyond-database" hybrid SQL+LLM querying. Best is GPT-4 Turbo at 40.0% execution accuracy and 48.2% data factuality. — [SWAN](https://arxiv.org/abs/2408.00884)

**Unified-text (verbalize structure, then dense retrieval)**
- UniK-QA (NAACL 2022 Findings) reduces text, tables, lists and KB triples all to text for one retriever-reader. It gains 11 points on KBQA over graph-based methods, and +3.5 / +2.6 on NQ / WebQuestions. — [UniK-QA](https://arxiv.org/abs/2012.14610)
- UDT-QA (ACL 2022) uses a data-to-text verbalizer to index tables and Wikidata. It found that verbalized knowledge is preferred for answer reasoning. — [UDT-QA](https://arxiv.org/abs/2110.08417)
- SUQL's Yelp result (90.3% vs 63.4% for linearization) is direct evidence that verbalizing structured data loses the precision of SQL filters on multi-constraint requests. — [SUQL](https://arxiv.org/abs/2311.09818)

**Hybrid-data QA benchmarks that define the problem (foundational)**
- HybridQA (2020): table-only and text-only baselines score under 20% EM; a hybrid model scores over 40%. — [HybridQA](https://arxiv.org/abs/2004.07347)
- OTT-QA (ICLR 2021): open-domain table+text, iterative-retriever baseline under 10% EM; introduced "early fusion" blocks. — [OTT-QA](https://arxiv.org/abs/2010.10439)
- TAT-QA (ACL 2021): TAGOP tags cells and spans and applies symbolic aggregation operators. 58.0 F1 vs 90.8 for human experts. — [TAT-QA](https://arxiv.org/abs/2105.07624)
- FinQA (EMNLP 2021): gold reasoning programs. — [FinQA](https://arxiv.org/abs/2109.00122)
- MultiHiertt (ACL 2022): multiple hierarchical tables plus long text. — [MultiHiertt](https://arxiv.org/abs/2206.01347)
- DocFinQA: FinQA questions placed in full filings averaging 123k words. — [DocFinQA](https://arxiv.org/abs/2401.06915)

**Retrieving among many tables (index-level)**
- Join-Aware Retrieval (ACL 2024) re-ranks tables with a mixed-integer program that includes table-table join relevance. +9.3% F1 retrieval, +5.4% QA accuracy. — [JAR](https://arxiv.org/abs/2404.09889)
- ARM (2025) aligns question decomposition with the data's organization (joins among tables and passages) and outperforms agentic RAG on Bird and OTT-QA retrieval. — [ARM](https://arxiv.org/abs/2501.18539)
- T-RAG / MultiTableQA: 57,193 tables and 23,758 questions. — [RAG over Tables](https://arxiv.org/abs/2504.01346)
- OpenTab (ICLR 2024): table retriever followed by SQL over the retrieved tables, up to 21.5% higher accuracy. — [OpenTab](https://arxiv.org/abs/2402.14361)
- TARGET (2025): for table retrieval, dense retrievers far outperform BM25, which is less effective than it is for unstructured text. [indep] — [TARGET](https://arxiv.org/abs/2505.11545)

### Inferences
- **Determinism split.** Query-time restructuring (StructRAG, SRAG) produces a fresh, LLM-generated structure on every query. Two runs over the same snapshot can therefore produce different tables, and so different answers, which violates the deterministic-retrieval requirement even if the final SQL is exact. Index-time conversion confines the stochastic step to ingestion. That step can be versioned and frozen, after which the same compiled query over the same snapshot returns the same rows. The remaining nondeterminism is the NL→query step, covered by the text-to-SQL track.
- The strongest gains in every family come from **pushing set operations (filter, count, group, intersect, join) into an executor** rather than into LLM generation. This holds for TAG, SUQL, TableRAG-hetero, SRAG and NeuSym-RAG.
- **Main failure modes of index-time conversion:**
  - schema coverage (a question needs a field that was never extracted; QO-Bench shows this concretely, see Q2);
  - entity/value normalization (SRAG's "US"/"America");
  - extraction omissions (conservative extractors skip brief mentions).
  
  All three are fixable or auditable offline, unlike query-time hallucination.

### Gaps
- No paper reports run-to-run variance of StructRAG- or SRAG-style query-time structurization. The determinism cost above is inferred from the design, not measured.
- Most index-time systems (ZenDB, Aryn, NeuSym-RAG, TableRAG-hetero) report only their own evaluation. Apart from QO-Bench and DualGraph (Q2), independent replications are scarce.
- I found no source for a benchmark named "Hamlet" in this area; it may not exist under that name.

---

## Q2. Benchmarks where vector RAG fails on aggregation/counting, and how converting to tables or typed records fixes it (head-to-head by question type)

### Takeaway
The evidence is consistent across independent benchmarks. Chunk-similarity RAG is competitive on **lookup/filter/single-hop** questions. It collapses on **counting, intersection, set-completeness ("find all") and grouping**, because a fixed top-k caps the evidence set and the LLM must count from prose. Systems that materialize typed records and execute SQL win on exactly those operators. They lose where the needed attribute was never extracted, and on some ordering and temporal operators. QO-Bench (EMNLP 2026 Findings) is the cleanest head-to-head with deterministic, exact-match scoring.

### Cited Findings

**QO-Bench: the most rigorous independent head-to-head** [indep: RAG, ReAct-RAG, GraphRAG and IE→SQL compared under the same answer LLM]
- Setup: 22,984 news articles, 614 corporate events, 18 templates, 785 questions. Gold answers are computed deterministically from typed event tuples and matched by exact match, not by an LLM judge. — [QO-Bench](https://arxiv.org/abs/2606.04646)
- Overall recall: long-context oracle 52.2; IE→SQL 37.9; RAG 25.2; ReAct-RAG 23.9; GraphRAG-global 3.8; GraphRAG-local 0.9; no context 0.6. — [QO-Bench](https://arxiv.org/abs/2606.04646)
- Recall by operator:

  | Operator | RAG | ReAct-RAG | IE→SQL | LC oracle |
  |---|---|---|---|---|
  | Filter/project | 53.6 | 55.4 | 50.6 | 77.6 |
  | Intersection | 6.0 | 9.5 | 50.9 | 3.9 |
  | Count/group | 30.0 | 3.4 | 51.2 | 56.2 |
  | Temporal join | 11.1 | — | 21.1 | — |
  | Ordering | 29.8 | — | 17.8 | — |

  — [QO-Bench](https://arxiv.org/abs/2606.04646)
- Mechanisms behind these numbers. RAG and ReAct reach only 32.4% and 38.4% of gold articles: the fixed top-k cutoff "imposes a hard cap on the candidate set", so set completeness is unattainable by construction. GraphRAG keeps dates through extraction (94.8%), but only 30.9% survive into community summaries ("organization is not preservation"). — [QO-Bench](https://arxiv.org/abs/2606.04646)
- IE→SQL's own ceiling. Event-level extraction recall peaks at 75.8%. Half of its residual misses are the extractor declining to emit a record from a brief mention. It scores 0% on joins whose linking key was populated for only about 4% of completion records. The ceiling is set by the schema, not by SQL. — [QO-Bench](https://arxiv.org/abs/2606.04646)

**Counting and aggregation specifically**
- **AGGBench (2026)**, "find all" entity-level aggregation over text [indep for baselines]. Evidence-chunk recall:
  - Naive RAG: 0.008
  - HippoRAG: 0.092
  - agentic frameworks: about 0.026–0.044
  - the authors' Disambiguation–Filtering–Aggregation (DFA) pipeline: 0.211 on AGGBench and 0.623 on AGGBench-Core.
  
  Raising top-k increases chunk recall (sometimes by more than 0.9) but does not improve count error. The authors conclude "existing RAG methods cannot solve aggregation problems by enlarging Top-k". Evidence density falls from 6.18% to 1.09% as the corpus grows. — [AGGBench](https://arxiv.org/abs/2602.01355)
- **Aryn/Luna on NTSB** [author/vendor]. RAG answered "How many incidents involved substantial damage?" with 10; the correct answer is 94. The authors say RAG "does not yield the correct answer in any case where the number of matching incidents exceeds a modest threshold". Luna's own errors included 6/30 counting errors (double-counting multi-aircraft incidents, which needs a dedup step) and 3 over-generous LLM filters. — [Aryn](https://arxiv.org/abs/2409.00847)
- **MEBench / SRAG**. GPT-4+RAG reaches 0.410 on statistics/aggregation questions, vs 0.908 for the table-then-SQL SRAG pipeline. [author] — [SRAG](https://arxiv.org/abs/2503.01346); [MEBench](https://arxiv.org/abs/2502.18993)
- **TAG benchmark**. Vanilla RAG scores 0.00 exact match on match-based, comparison and ranking queries over BIRD databases, vs 0.55 overall for hand-written TAG (SQL plus LM). — [TAG](https://arxiv.org/abs/2408.14717)
- **DualGraph / SpecsQA (2026)**, semi-structured product specifications needing exact filtering and exhaustive listing [indep for baselines]. Factual-correctness / list-match F1:

  | System | FC F1 | List-match F1 | Indexing tokens |
  |---|---|---|---|
  | Vector RAG | 0.092 | 0.118 | — |
  | Microsoft GraphRAG | 0.153 | 0.203 | 181M |
  | TableRAG | 0.091 | 0.118 | — |
  | Symbolic-KG-only (SPARQL over typed triples) | 0.273 | 0.321 | — |
  | Text-KG-only | 0.140 | 0.136 | — |
  | DualGraph (Router + text fallback) | 0.298 | 0.357 | 16M |

  — [DualGraph](https://arxiv.org/abs/2605.27164)

**Long context does not remove the need for executors**
- LOFT (2024). At 128k context on Spider, text-to-SQL-style compositional QA scores 0.40 for Gemini 1.5 Pro, 0.14 for GPT-4o and 0.19 for Claude 3 Opus, vs 0.74 for a DAIL-SQL pipeline. Averaging was the hardest operator; counting was relatively easy; inequality was harder than equality. [indep] — [LOFT](https://arxiv.org/abs/2406.13121)
- HoloBench (ICLR 2025). Database-style operations over text in context: max/min queries are easier, aggregation is harder, and the amount of relevant information matters more than context length. RAG beats long-context only at 4k tokens. [indep] — [HoloBench](https://arxiv.org/abs/2410.11996)
- Oolong (COLM 2026): "most models score below 50%" at 128K on counting and distributional aggregation. — [Oolong](https://arxiv.org/abs/2511.02817)
- Loong (EMNLP 2024): RAG "achieves poor performance" on extended multi-document comparison, clustering and chain-of-reasoning tasks. — [Loong](https://arxiv.org/abs/2406.17419)

**Broader RAG benchmarks with question-type breakdowns**
- CRAG (NeurIPS 2024 D&B):
  - LLM-only ≤34% accuracy; straightforward RAG up to 44%; the best industry systems answer 63% without hallucination.
  - Accuracy is lower for set, post-processing and aggregation-style questions.
  - Adding KG mock-API data (Task 2) improves truthfulness "because the KG knowledge is typically brief but precise", but the gain is "mediocre".
  - For over 30% of questions the answer was in the retrieved pages but did not fit in the prompt.
  
  [indep] — [CRAG](https://arxiv.org/abs/2406.04744)
- FinanceBench: GPT-4-Turbo with a vector-store retrieval system answered incorrectly or refused on 81% of 150 cases. [indep] — [FinanceBench](https://arxiv.org/abs/2311.11944)
- FRAMES (NAACL 2025): multi-hop accuracy 0.40 without retrieval and 0.66 with a multi-step retrieval pipeline. — [FRAMES](https://arxiv.org/abs/2409.12941)
- QAMPARI (list answers across many paragraphs): best retrieve-and-read F1 32.8. — [QAMPARI](https://arxiv.org/abs/2205.12665)
- UDA (2,965 real documents, 29,590 expert QA pairs) highlights that parsing tables correctly from PDF/HTML is critical. — [UDA](https://arxiv.org/abs/2406.15187)

**Graph vs vector by question type**
- RAG vs GraphRAG (systematic evaluation): RAG wins on single-hop and detail-oriented queries; GraphRAG (HippoRAG2, local community search) wins on multi-hop; global community search "often struggles on QA". [indep] — [RAG vs GraphRAG](https://arxiv.org/abs/2502.11371)
- GraphRAG-Bench notes "GraphRAG frequently underperforms vanilla RAG on many real-world tasks" and characterizes when graphs help (hierarchical, multi-hop reasoning). [indep] — [GraphRAG-Bench](https://arxiv.org/abs/2506.05690)
- Microsoft GraphRAG was designed for global sense-making ("main themes") rather than precise QA. — [GraphRAG](https://arxiv.org/abs/2404.16130)
- SEC EDGAR head-to-head (single author, 20 questions × 3 runs; preliminary) [indep across three architectures]:
  - All three runs correct: KG-based GraphRAG on 16/20 questions, text-to-SQL on 10/20, vector RAG (pgvector HNSW) on 3/20.
  - Vector RAG passed only 3/15 single-document attempts, because "belongs to company X" is not recoverable from cosine similarity.
  - All six confident falsehoods came from text-to-SQL conflating people who share a surname. Resolving entities to IDs first prevents this.
  
  — [EDGAR KG enrichment](https://arxiv.org/abs/2610.37728)
- Enterprise SQL: zero-shot GPT-4 text-to-SQL scored 16.7% on an insurance schema vs 54.2% when queried through a KG/ontology layer; on high-schema-complexity questions SQL scored 0%. [indep, 2023] — [Sequeda et al.](https://arxiv.org/abs/2311.07509)

**Head-to-head matrix (synthesized from the above; each cell cites its evidence)**

| Question type | Chunk/vector RAG | Typed store + SQL/graph executor | Evidence |
|---|---|---|---|
| Point lookup / single-hop fact | Competitive or best | Competitive if the field was extracted | [RAG vs GraphRAG](https://arxiv.org/abs/2502.11371); [QO-Bench](https://arxiv.org/abs/2606.04646) filter 53.6 vs 50.6 |
| Filter / multi-constraint selection | Moderate; degrades when a constraint is an exact attribute | Strong (SQL filters) | [SUQL](https://arxiv.org/abs/2311.09818) 90.3 vs 63.4; [DualGraph](https://arxiv.org/abs/2605.27164); [NeuSym-RAG](https://arxiv.org/abs/2505.19754) 58.2 vs 9.4 on metadata questions |
| Counting / group-by | Fails above top-k size | Strong | [QO-Bench](https://arxiv.org/abs/2606.04646) 51.2 vs 30.0; [Aryn](https://arxiv.org/abs/2409.00847) 94 vs 10; [AGGBench](https://arxiv.org/abs/2602.01355) |
| Intersection / set completeness | Near zero | Strong | [QO-Bench](https://arxiv.org/abs/2606.04646) 50.9 vs 6.0 |
| Comparison across entities | Moderate | Strong | [SRAG](https://arxiv.org/abs/2503.01346) 0.934 vs 0.763; [TAG](https://arxiv.org/abs/2408.14717) 0.65 vs 0.00 |
| Ordering / superlatives | Mixed | Mixed (depends on extracted dates) | [QO-Bench](https://arxiv.org/abs/2606.04646) RAG 29.8 > IE→SQL 17.8 |
| Multi-hop / relational | Weak | Graph traversal helps; text+relation hybrids best | [HybGRAG](https://arxiv.org/abs/2412.16311); [RAG vs GraphRAG](https://arxiv.org/abs/2502.11371); [TableRAG-hetero](https://arxiv.org/abs/2506.10380) |
| Open-ended / summarization / "themes" | Good for local; GraphRAG-global for corpus-wide | Poor (no schema for it) | [GraphRAG](https://arxiv.org/abs/2404.16130); [StructRAG](https://arxiv.org/abs/2410.08815) win rates |

### Inferences
- The fix is not "tables" as such. It is a **materialized typed value plus an executor that runs the operator**. QO-Bench separates the two axes (index-time preservation vs query-time execution) and shows GraphRAG fails the first and the long-context oracle fails the second. Its 3.9% on intersection with gold evidence in context means even unlimited context does not substitute for an executor.
- Vector retrieval's counting failure is structural, not a tuning issue. Top-k is a cardinality cap: Aryn's 94 vs 10, AGGBench's flat count error as top-k grows, and QO-Bench's coverage analysis all show this. A deterministic data lake should answer COUNT/GROUP/INTERSECT from records, never from retrieved chunks.
- Typed extraction has a coverage ceiling (QO-Bench: extraction recall at most 75.8%; joins fail when linking keys are not extracted). Chunk retrieval should therefore stay available as a fallback and for attributes outside the schema.

### Gaps
- Few benchmarks report all seven question types (lookup, filter, aggregation, counting, comparison, multi-hop, open-ended) for both paradigms under one answer model. QO-Bench covers operators but has no open-ended questions. CRAG covers question types but has no SQL-over-extracted-records baseline.
- Most "structured wins" numbers (SRAG, Aryn, ZenDB, NeuSym-RAG, TableRAG-hetero) are author-reported on the authors' own benchmarks.

---

## Q3. Routers and agents that choose between SQL, graph and vector tools: evidence on routing accuracy

### Takeaway
Routing has large headroom. Oracle routing between text and graph retrievers on STaRK-MAG gives Hit@1 of 0.452 vs 0.291 for the best single retriever, and the two retrievers' strengths barely overlap. But off-the-shelf routers capture only part of that headroom. Trained routers (StructRAG: 94% vs 80% zero-shot for a 72B model) and **fallback cascades** (DualGraph: route to symbolic, fall back to text on failure; Coverage Illusion: cheapest-first, escalate on empty result) are the most effective and robust patterns. Pre-retrieval routing from the query text alone is provably limited when the need only shows up after searching.

### Cited Findings
- **HybGRAG (ACL 2025)**. On STaRK-MAG, text vector search scores Hit@1 0.2908 and graph PPR 0.2533, but an oracle that always picks the right retriever scores 0.4522. LLM topic-entity/subgraph extraction hits the target 67.7% of the time, rising to 92.3% after two iterations with corrective critic feedback. HybGRAG reports an average 51% relative Hit@1 gain on STaRK. [author] — [HybGRAG](https://arxiv.org/abs/2412.16311); [STaRK](https://arxiv.org/abs/2404.13207)
- **StructRAG router accuracy**: 94.38% for the DPO-trained 7B router vs 90.06% for few-shot 72B and 54.25% for zero-shot 7B. Final quality tracks router accuracy closely (random routing: 60.38 → 45.33). [author] — [StructRAG](https://arxiv.org/abs/2410.08815)
- **mmRAG (2025)** is the first benchmark with dataset-level relevance labels for directly measuring query routing across text (NQ, TriviaQA), tables (OTT-QA, TAT-QA) and KGs (CWQ, WebQSP).
  - An LLM router beats an embedding "semantic router" at small k, with clear gaps to an oracle router.
  - Searching all modalities at once instead of the right source hurts: BM25 drops from 0.5210 to 0.4162 on CWQ, BGE from 0.3720 to 0.2705 on WebQSP.
  
  [indep] — [mmRAG](https://arxiv.org/abs/2505.11180)
- **DualGraph ablation (SpecsQA)**: LLM binary router 0.268 FC / 0.303 LM; router + text fallback 0.298 / 0.357 at 7.7k query tokens; agentic multi-step 0.240 / 0.341 at 55.5k tokens. Fallback beats pure routing, and agentic loops cost about 7× more tokens for no factual-correctness gain. [author] — [DualGraph](https://arxiv.org/abs/2605.27164)
- **NeuSym-RAG**: an iterative agent with both SQL and vector actions (39.6) beats two-stage fixed pipelines (Neu-RAG 10.7, Sym-RAG 9.1). Iterative single-paradigm agents reach 37.3 (neural) and 28.0 (symbolic). [author] — [NeuSym-RAG](https://arxiv.org/abs/2505.19754)
- **Coverage Illusion (production, Danish National Encyclopedia, 20,000 query-workflow pairs)**.
  - Synthetic queries suggested more than 90% need LLM query augmentation; only 27.8% of real queries did.
  - Four ML pre-retrieval routing paradigms could not close the gap, because the need shows up only after searching.
  - A cheapest-first cascade that escalates when a step returns no documents improved quality by +0.140 and cut latency 31.8%.
  
  [indep, production] — [Coverage Illusion](https://arxiv.org/abs/2605.27220)
- **RAG vs long-context routing**:
  - Self-Route (EMNLP 2024 industry) routes via model self-reflection. Cost falls 65% (Gemini-1.5-Pro) and 39% (GPT-4o) at comparable quality; RAG and long-context give identical predictions on over 60% of queries. — [Self-Route](https://arxiv.org/abs/2407.16833)
  - LaRA finds "no silver bullet" for long-context vs RAG routing. — [LaRA](https://arxiv.org/abs/2502.09977)
  - RAGRouter-Bench finds no one-size-fits-all paradigm, with adaptive routing giving better effectiveness/efficiency trade-offs. — [RAGRouter-Bench](https://arxiv.org/abs/2602.00296)
- **Complexity and retriever routers**:
  - Adaptive-RAG trains a small classifier to pick no-retrieval / single-step / multi-step strategies. — [Adaptive-RAG](https://arxiv.org/abs/2403.14403)
  - RouterRetriever routes over domain-expert embedders: +2.1 nDCG@10 vs MSMARCO-trained, +3.2 vs multi-task. — [RouterRetriever](https://arxiv.org/abs/2409.02685)
  - R³AG learns retriever routing from both retrieval quality and generation utility, beating the best single retriever. — [R3AG](https://arxiv.org/abs/2604.22849)
- **Intent-typed routing in finance**. HC-RAG builds a typed evidence graph (documents/sections/text units/table units/metadata) and routes by four intents (calculation, trend, fact, comparison). +6.6 F1 over RAPTOR on DocFinQA and +10.9 F1 over GraphRAG on Multi-Doc-2025 (2,327 QA pairs from 179 10-Ks). [author] — [HC-RAG](https://arxiv.org/abs/2608.12335)
- **Mixture of structural and textual retrieval**:
  - MoR plans a textual planning graph, interleaves structural traversal with textual matching, and reports "uneven retrieving performance across different query logics". — [MoR](https://arxiv.org/abs/2502.20317)
  - HybridRAG (KG + vector) beats either alone on earnings-call Q&A. [author] — [HybridRAG](https://arxiv.org/abs/2408.04948)
- **Plan-level orchestration with determinism features**:
  - A.DOT compiles NL questions into DAG plans spanning SQL stores and document stores, with structural and semantic validation before execution. It caches plans with paraphrase-aware template matching so equivalent queries re-execute the same plan, and it emits evidence trails and lineage. [author, no numbers in abstract] — [A.DOT](https://arxiv.org/abs/2603.14229)
  - SANA (data-lake QA agents): data analysis is the consistent bottleneck; search is a major limitation at LakeQA's million-scale data lake. [indep] — [SANA](https://arxiv.org/abs/2606.13904)
  - LakeQA: GPT-5.2 reaches only 18.37% EM over a 9.5 TB lake. — [LakeQA](https://arxiv.org/abs/2606.10460)
  - KramaBench: 104 data-lake-to-insight pipelines. — [KramaBench](https://arxiv.org/abs/2506.06541)

### Inferences
- **Best-supported router design:**
  1. A cheap classifier or LLM decides "operator query vs semantic query".
  2. Operator queries go to the typed store.
  3. Empty, failed or low-coverage results fall back to text retrieval.
  
  DualGraph, Coverage Illusion and HybGRAG's critic loop all support "route plus verified fallback" over "route once" or open-ended agent loops, which cost about 7× more tokens in DualGraph's measurements.
- For determinism, routing decisions should be logged and cached, as A.DOT does with plan caching. Otherwise LLM router nondeterminism (see Q4) adds a source of run-to-run variation on top of query translation.

### Gaps
- No standard metric or benchmark specifically measures **SQL vs graph vs vector tool-choice accuracy** on one corpus. mmRAG measures source (dataset) routing, StructRAG measures structure-type routing, and DualGraph measures a binary router only through end-to-end QA.
- None of the router papers report run-to-run consistency of routing decisions.

---

## Q4. Exact-match and lexical retrieval as deterministic baselines; nondeterminism in approximate vector search

### Takeaway
Exact predicates (SQL `WHERE`, key lookup, inverted-index term match) are deterministic given a fixed snapshot, with ties broken explicitly. BM25 is deterministic given fixed index statistics and implementation, but scores move with corpus statistics, shard and replica state, and the BM25 variant used. Approximate vector search adds three sources of nondeterminism or incompleteness: recall below 1, build-order dependence under multithreaded HNSW construction, and post-filtering that silently returns fewer rows. LLM inference at "temperature 0" is itself not deterministic. Any LLM in the retrieval loop (router, query writer) must be pinned or its outputs cached.

### Cited Findings
- **pgvector**:
  - Exact nearest-neighbor search is the default and "provides perfect recall".
  - With an approximate index, "you will see different results for queries after adding an approximate index".
  - Filtering is applied after the index scan: "If a condition matches 10% of rows, with HNSW and the default hnsw.ef_search of 40, only 4 rows will match on average." Version 0.8.0 added iterative index scans with `strict_order` / `relaxed_order` modes.
  
  — [pgvector README](https://github.com/pgvector/pgvector)
- **FAISS**:
  - Random seeds are fixed, and multithreaded runs with the same thread count are bitwise reproducible, with exceptions.
  - The HNSW `add` "is performed in an unspecified order", so several build runs give different results; search itself is deterministic.
  - PCA/OPQ training depends on non-reproducible LAPACK.
  - MKL matrix multiplication can differ by processor.
  
  — [FAISS wiki: threads and reproducibility](https://github.com/facebookresearch/faiss/wiki/Threads-and-asynchronous-calls)
- **ParlayANN (2023)**: existing parallel graph-ANN builds "suffer from... heavy use of locks... which results in nondeterminism". The authors provide deterministic parallel graph-ANN algorithms that scale to billion-scale data. — [ParlayANN](https://arxiv.org/abs/2305.04359)
- **Elasticsearch/Lucene BM25**:
  - "Scores are not reproducible" across replicas, because index statistics include not-yet-merged deleted documents and requests go round-robin to shard copies.
  - Ties are broken by internal Lucene doc ids that differ across copies.
  - Recommended mitigation: a `preference` string, or `dfs_query_then_fetch` for skewed shard statistics.
  
  — [Elasticsearch: Getting consistent scoring](https://www.elastic.co/guide/en/elasticsearch/reference/current/consistent-scoring.html)
- "Which BM25 do you mean?" (ECIR 2020) is a large-scale reproducibility study of BM25 scoring variants across implementations: "BM25" is not a single function. — [Kamphuis et al.](https://doi.org/10.1007/978-3-030-45442-5_4)
- Pyserini provides replicable BM25, dense and hybrid baselines with prebuilt indexes and automated regression testing. — [Pyserini](https://arxiv.org/abs/2102.10073)
- BEIR: BM25 is "a robust baseline" in zero-shot retrieval across 18 datasets. — [BEIR](https://arxiv.org/abs/2104.08663)
- But for **table retrieval**, dense retrievers far outperform BM25. — [TARGET](https://arxiv.org/abs/2505.11545)
- Lexical matching catches exact identifiers that embeddings miss (the example "Error code TS-999"). Contextual BM25 plus contextual embeddings cut failed retrievals by 49%, and by 67% with reranking. [vendor] — [Anthropic: Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)
- Blended RAG reports gains from combining dense and sparse indexes with hybrid query strategies on NQ and TREC-COVID. [author] — [Blended RAG](https://arxiv.org/abs/2404.07220)
- **Filtered ANN (structured predicate plus vector)**:
  - ACORN achieves 2–1,000× higher throughput at fixed recall for arbitrary predicates on HNSW. — [ACORN](https://arxiv.org/abs/2403.04871)
  - A unified filtered-ANN benchmark classifies methods as filter-then-search, search-then-filter or hybrid, and shows robustness depends on filter selectivity. — [FANNS benchmark](https://arxiv.org/abs/2509.07789)
  - CHASE (native hybrid relational/vector engine) reports 13%–7,500× speedups over plugin designs. — [CHASE](https://arxiv.org/abs/2501.05006)
- **LLM nondeterminism**:
  - Five LLMs at "deterministic" settings showed accuracy variation up to 15% across runs, and up to 70% between best and worst possible runs. — [Atil et al.](https://arxiv.org/abs/2408.04667)
  - Qwen3-235B at temperature 0 produced 80 unique completions out of 1,000, diverging at token 103. The cause is lack of batch invariance; batch-invariant kernels fix it. — [Thinking Machines: Defeating Nondeterminism](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)
- Exact-match scoring is itself a design choice for reproducible evaluation. QO-Bench scores against typed tuples by exact match "rather than an LLM judge". — [QO-Bench](https://arxiv.org/abs/2606.04646)

### Inferences
- **Determinism ladder for the toolkit**, from most to least deterministic:
  1. SQL/key lookup over a versioned snapshot with explicit `ORDER BY` tie-breaks;
  2. inverted-index term/phrase match;
  3. BM25 with a pinned implementation and frozen statistics (a single segment, or after a forced merge, or with DFS);
  4. exact (brute-force) vector kNN;
  5. ANN (recall < 1, build-order effects, post-filter shortfall).
  
  Vector search can stay in the system but should be labelled "approximate". For reproducibility, run it in exact mode over the candidate set already narrowed by structured predicates (filter-then-search), which is cheap once SQL has shrunk the candidates.
- Snapshot pinning must cover index statistics as well as rows. Deleted-but-unmerged documents change BM25 scores (Elasticsearch docs).

### Gaps
- I found no peer-reviewed study measuring **end-to-end answer variance** caused by ANN nondeterminism specifically (as opposed to LLM nondeterminism) in a RAG pipeline.
- The Kamphuis et al. effect sizes were not extracted; only the title and the study's framing were verified.

---

## Q5. The most effective hybrid design, and the cost of maintaining both representations

### Takeaway
The best-supported design is **"typed records first, text as fallback, both linked by provenance"**:
1. At ingestion, extract typed records (entities, events, attributes) into SQL and/or a property graph, with source-span pointers, resolving entities to stable IDs.
2. Keep a chunk index (BM25 plus dense) over the same documents, keyed by the same document and entity IDs.
3. At query time, route operator queries (filter, count, group, intersect, join, compare) to the executor and semantic or open-ended queries to text retrieval. Fall back to text when the executor returns nothing or the schema lacks the field.

The extra cost is mainly one-off ingestion tokens plus schema maintenance. Measured index-time costs are moderate (DualGraph: 16M tokens vs 181M for GraphRAG). Query-time costs are lower than agentic or long-context alternatives.

### Cited Findings
- **Hybrid views beat single views in controlled ablations:**
  - DualGraph: symbolic-only 0.273 FC, text-only 0.140, combined 0.293–0.306. — [DualGraph](https://arxiv.org/abs/2605.27164)
  - NeuSym-RAG: database plus vectorstore 39.6 vs neural-only 37.3 and symbolic-only 28.0 (iterative variants). — [NeuSym-RAG](https://arxiv.org/abs/2505.19754)
  - TableRAG-hetero: removing SQL execution hurts most on HeteQA. — [TableRAG (Yu et al.)](https://arxiv.org/abs/2506.10380)
  - HybGRAG: oracle text/graph routing gives +55% relative Hit@1 over the best single retriever. — [HybGRAG](https://arxiv.org/abs/2412.16311)
- **Entity resolution to IDs is a key ingredient.** In the EDGAR study all six confident falsehoods were text-to-SQL surname conflations, which the ID-resolved graph design avoided "structurally rather than probabilistically" (small study). — [EDGAR KG enrichment](https://arxiv.org/abs/2610.37728)
- SRAG's errors came from unnormalized synonyms in columns. — [SRAG](https://arxiv.org/abs/2503.01346)
- **Index-time cost evidence:**
  - DualGraph indexing used 16.1M tokens vs 181.2M for Microsoft GraphRAG and 420.3M for Wikontic, with query cost of 6.8–7.7k tokens vs 11–139k. — [DualGraph](https://arxiv.org/abs/2605.27164)
  - Evaporate-Code+ needs 110× fewer LLM tokens than per-document extraction by synthesizing extractors. — [Evaporate](https://arxiv.org/abs/2304.09433)
  - ZenDB costs about $0.02–0.03 per query per document (vs $0.01–0.02 for RAG) and is 4–29× cheaper than whole-document LLM processing. — [ZenDB](https://arxiv.org/abs/2405.04674)
- **Query-time cost:**
  - Hand-written TAG is the fastest pipeline (2.94 s average). — [TAG](https://arxiv.org/abs/2408.14717)
  - Agentic loops cost about 7× more tokens than a router with fallback (DualGraph). — [DualGraph](https://arxiv.org/abs/2605.27164)
  - Self-Route saves 39–65% vs always using long context. — [Self-Route](https://arxiv.org/abs/2407.16833)
- **Ceiling of typed extraction:**
  - QO-Bench IE→SQL: event extraction recall at most 75.8%, with 0% on joins whose linking key was not extracted. — [QO-Bench](https://arxiv.org/abs/2606.04646)
  - Evaporate: cheap code-based extraction is "far less accurate" than direct LLM extraction without ensembling. — [Evaporate](https://arxiv.org/abs/2304.09433)
  - DocETL: single-call LLM operators miss instances (e.g., "all instances of specific clauses") without task decomposition. — [DocETL](https://arxiv.org/abs/2410.12189)
- **Engine-level hybrid execution** is maturing:
  - LLM functions inside DuckDB (FlockMTL, PVLDB 2025). — [FlockMTL](https://arxiv.org/abs/2504.01157)
  - Semantic operators with accuracy guarantees (LOTUS). — [LOTUS](https://arxiv.org/abs/2407.11418)
  - Native hybrid vector/relational engines (CHASE). — [CHASE](https://arxiv.org/abs/2501.05006)
  - Predicate-agnostic filtered HNSW (ACORN). — [ACORN](https://arxiv.org/abs/2403.04871)
- **Explainability / traceability:**
  - Aryn's UI exposes the query plan and drill-down to source documents, which the authors argue analytics systems need in order to be practical. — [Aryn](https://arxiv.org/abs/2409.00847)
  - A.DOT emits evidence trails and data lineage. — [A.DOT](https://arxiv.org/abs/2603.14229)
  - Binder and BlendSQL produce inspectable programs. — [Binder](https://arxiv.org/abs/2210.02875); [BlendSQL](https://arxiv.org/abs/2402.17882)
- **Agentic RAG survey** frames the general pattern (planning, tool use, reflection) of agents choosing retrieval tools. — [Agentic RAG survey](https://arxiv.org/abs/2501.09136)

### Inferences
- **Recommended architecture for a deterministic, agent-retrievable data lake** (a synthesis; no single paper evaluates all parts together):
  1. **Ingest once, version everything.** Parse to structured documents (sections, tables kept as tables, as in TableRAG-hetero and NeuSym-RAG). Extract typed records with an explicit schema. Store `(doc_id, page, char_span)` provenance on every value. Pin extractor model, prompt and version, and treat outputs as a frozen snapshot.
  2. **Resolve entities to IDs before indexing text** (EDGAR, SRAG failure modes), so both stores share keys.
  3. **Dual index:** relational/graph store for typed records, plus BM25 (pinned implementation) and an exact-or-ANN vector index over chunks, keyed by the same IDs.
  4. **Route by operator, not by topic.** Count, group, intersect, join, filter-on-attribute and compare go to SQL/graph. Open-ended or descriptive questions go to text. Fall back to text when the executor returns empty or the schema lacks a field (DualGraph, Coverage Illusion).
  5. **Make the query side reproducible.** Log and cache compiled queries and plans (A.DOT), and return result rows with provenance spans. Answer generation is then a presentation layer over deterministic rows.
- **Maintenance costs of keeping both representations** (inferred from the cost data and failure modes above):
  - schema evolution, which needs re-extraction when new attributes are needed;
  - consistency between the stores on document update or delete;
  - duplicate storage.
  
  The evidence suggests these are worth paying for aggregation-heavy workloads. Index-time extraction is a one-off cost, while answering such questions from chunks is often impossible regardless of spend (AGGBench, QO-Bench, Aryn).

### Gaps
- No paper quantifies **ongoing maintenance cost** (re-extraction on schema change, incremental updates, store-consistency bugs) of dual representations. All cost figures are one-shot index-build or per-query.
- No end-to-end evaluation combines all five recommended components and measures determinism (run-to-run identical results) together with accuracy. The recommendation is assembled from component evidence.
