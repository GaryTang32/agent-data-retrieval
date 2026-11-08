# Graph Information Engineering for Agent-Retrievable Data (state as of Nov 2026)

Scope: the graph layer only, covering KG construction from unstructured documents, GraphRAG variants, hybrid retrieval, graph-based agent memory, graph stores, query interfaces, incremental updates, provenance and graph-quality evaluation. Each source is labelled as one of: peer-reviewed (PR), preprint (PP), vendor (V), or secondary blog/aggregator (S). Information from 2024 is marked [2024].

## LLM-based KG construction: extraction, schema-guided vs open, entity resolution, measured quality

### Takeaway
LLM-based extraction is now the default way to build KGs, but measured quality is modest and depends heavily on the benchmark. Open extractors produce sparse, duplicated or generic nodes unless an explicit entity-resolution step (clustering or deduplication) runs. No standard benchmark yet exists for entity resolution in LLM-built KGs; most papers define their own precision, recall and F1 or use an LLM-judge "fact recoverability" score.

### Cited Findings
- KGGen (Stanford-affiliated, arXiv 2502.09956, PP) introduces the MINE benchmark: 100 LLM-generated Wikipedia-style articles of about 1,000 tokens each. An LLM judge scores whether each source fact can be inferred from the extracted graph. KGGen's main technique is to cluster and de-duplicate related entities to reduce graph sparsity. — [arXiv 2502.09956](https://arxiv.org/html/2502.09956v2)
- Reported MINE scores: KGGen about 66%, Microsoft GraphRAG's extractor about 48%, OpenIE about 30%. These figures come from secondary summaries, so check them against the PDF. The abstract itself says KGGen performs "comparably to GraphRAG" on separate retrieval benchmarks and scales better on information compression and sparsity as text length grows. KGGen's authors built the benchmark, so it is not independent. — [arXiv 2502.09956](https://arxiv.org/pdf/2502.09956); [Moonlight summary (S)](https://www.themoonlight.io/en/review/kggen-extracting-knowledge-graphs-from-plain-text-with-language-models)
- Reported failure modes of open extraction: OpenIE produced long or generic nodes such as "it" and "are", and GraphRAG sometimes produced very small or sparse graphs that missed connections. — [Emergent Mind summary (S)](https://www.emergentmind.com/topics/kggen)
- ATOM (arXiv 2510.22590, PP, dynamic temporal KG construction) notes that earlier work (Lairgi et al. 2024) measured entity/relation resolution only by false discovery rate (1 − precision). ATOM extends the evaluation to precision, recall and F1 for both entity resolution (ER) and relation resolution (RR). This is evidence that ER evaluation practice is still immature and non-standard. — [arXiv 2510.22590](https://arxiv.org/pdf/2510.22590)
- A Frontiers in Big Data 2025 study (PR) evaluates LLM-generated graphs with graph-level and triple-level P/R/F1, graph edit distance and semantic matching on WebNLG+ and other domains. It reports low triple-level scores for the tested models. — [Frontiers fdata.2025.1505877](https://www.frontiersin.org/journals/big-data/articles/10.3389/fdata.2025.1505877/full)
- In a domain-specific case, a Jan 2026 ChemRxiv preprint on chunking strategies for chemistry KG extraction reports 92.1% precision and 89.2% F1 for entity and relationship extraction. Treat this as an upper bound for narrow, schema-constrained domains, not for open text. — [ChemRxiv Jan 2026 (PP)](https://chemrxiv.org/doi/pdf/10.26434/chemrxiv.10001546/v1)
- Over-generation risk in LLM mapping and alignment (relevant to entity linking and schema alignment): in a medical ontology-mapping study, one LLM had 70.37% recall but only 19.19% precision. — [Frontiers frai.2025.1546179 (PR)](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1546179/full)
- GraphJudge (EMNLP 2025, PR) adds an LLM "graph judge" with entity-centric filtering to clean extracted triples, scored with accuracy, recall, F1 and G-BERTScore. This is a post-extraction verification step. — [ACL Anthology 2025.emnlp-main.554](https://aclanthology.org/2025.emnlp-main.554.pdf)
- GraphRAG-Bench (Xiang et al.) measured how dense each system's constructed graph is, per 10k corpus tokens. Average node degree on the novel corpus: MS-GraphRAG 1.48, HippoRAG 1.73, LightRAG 2.10, Fast-GraphRAG 3.19, HippoRAG2 8.75. Clustering coefficient: HippoRAG2 0.657 vs MS-GraphRAG 0.315. The authors find that denser graphs (HippoRAG2) correlate with better recall and generation. — [arXiv 2506.05690v3](https://arxiv.org/html/2506.05690)
- LazyGraphRAG [2024] skips LLM entity extraction at index time entirely, using noun-phrase extraction instead. Its indexing cost is "about the same as vector RAG" and about 0.1% of full GraphRAG. This shows that a cheap, non-LLM construction path is a viable design point. — [Microsoft Research blog (V)](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)

### Inferences
- For the toolkit, construction should be a pipeline of separate steps: (a) extraction, schema-guided where a domain schema exists and open otherwise; (b) entity resolution by embedding clustering plus LLM adjudication; (c) a judge or verification pass; (d) storage with provenance. The evidence shows that (b) and (c) carry most of the quality difference (KGGen clustering, GraphJudge filtering).
- MINE-style "can facts be recovered from the graph" scoring is a cheap, task-agnostic quality metric the toolkit could adopt. Recall around 50–66% on short articles means a third or more of facts are lost. That argues for keeping source chunks alongside the graph (hybrid), not replacing them.
- Schema-guided extraction appears to score far higher in narrow domains (around 90% F1) than open extraction on general text. This is an inference from different benchmarks, not a head-to-head comparison.

### Gaps
- I found no head-to-head, independent benchmark of schema-guided vs open LLM extraction on the same corpus.
- I found no standard entity-resolution benchmark for LLM-built KGs, and no measured "recall of entities needed for downstream questions" metric beyond MINE.
- I did not verify current tooling for schema-guided extraction (e.g., Neo4j LLM Graph Builder / neo4j-graphrag SchemaConfig, LlamaIndex PropertyGraphIndex, Cognee ontologies, KAG's schema-constrained construction) in this session.

## GraphRAG variants: mechanisms, independent benchmark evidence vs vector RAG, cost multiples

### Takeaway
Independent benchmarks agree on the pattern. Plain vector RAG, especially with a reranker, matches or beats GraphRAG on simple factoid questions. Graph methods win on multi-hop or complex reasoning and on corpus-level summarization. The cost difference is mostly in query-time tokens: MS-GraphRAG global search uses about 377x more prompt tokens per query than vector RAG and LightRAG about 115x, while HippoRAG2 is only about 1.15x. HippoRAG2 is the most consistent all-rounder in independent tests.

### Cited Findings
**Mechanisms**
- Microsoft GraphRAG: LLM entity/relation extraction per chunk, then community detection (Leiden), then LLM-written community reports. It offers local, global and DRIFT search modes. Indexing makes n extraction calls plus c community-summarization calls, and community restructuring makes updates expensive. — [LearnOpenCV (S)](https://learnopencv.com/lightrag/); [EraRAG arXiv 2506.20963 (PP)](https://arxiv.org/pdf/2506.20963)
- LightRAG: graph extraction similar to GraphRAG but without community reports. It uses dual-level (low/high-level keyword) retrieval and makes one LLM call per chunk at indexing. Its extraction cost is said to be similar to GraphRAG's, but builds and updates are cheaper because there are no community reports. — [Medium explainer (S)](https://medium.com/data-science-in-your-pocket/what-is-lightrag-af1c7439f47c); [LearnOpenCV (S)](https://learnopencv.com/lightrag/)
- HippoRAG 2 (ICML 2025, PR): builds on HippoRAG's Personalized PageRank over an open-IE KG. It adds deeper passage integration (passages as graph nodes) and more effective online LLM use (recognition memory/filtering). It reports a 7% gain on associative-memory tasks over a state-of-the-art embedding retriever, and also gains on factual and sense-making tasks. These are author-reported. — [arXiv 2502.14802](https://arxiv.org/abs/2502.14802)
- LazyGraphRAG [Nov 2024, editor's note Jun 2025] (V): indexes with noun-phrase extraction and builds concept graphs, with no LLM summarization at index time. Query cost is tunable by a "relevance test budget". Microsoft reports Z100_Lite costs the same per query as vector RAG with 8k tokens. On global queries it reports quality comparable to GraphRAG Global Search at more than 700x lower query cost, and says Z500 (4% of GraphRAG C2's query cost) significantly beats all 8 baselines on local and global queries. Evaluation used 5,590 AP news articles, 100 synthetic queries and pairwise LLM judging. As of Jun 2025 it was shipped in Microsoft Discovery and Azure Local (preview), and the blog does not say it is in the OSS GraphRAG library. — [Microsoft Research blog (V)](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)

**Independent benchmark 1: GraphRAG-Bench, "When to use Graphs in RAG" (Xiang et al., Xiamen U. / PolyU; arXiv 2506.05690 v3, Feb 2026; listed by an ICLR 2026 paper-notes site, but the arXiv page shows no venue). Generator GPT-4o-mini; 4 task levels; novel (Gutenberg) and medical (NCCN) corpora**
- Novel corpus, answer accuracy (Fact / Complex reasoning / Contextual summarization):
  - RAG with rerank: 60.92 / 42.93 / 51.30
  - RAG without rerank: 58.76 / 41.35 / 50.08
  - MS-GraphRAG: 49.29 / 50.93 / 64.40
  - HippoRAG2: 60.14 / 53.38 / 64.10
  - LightRAG: 58.62 / 49.07 / 48.85
  - Fast-GraphRAG: 56.95 / 48.55 / 56.41
  - LazyGraphRAG: 51.65 / 49.22 / 58.29
  - RAPTOR: 49.25 / 38.59 / 47.10
  - HippoRAG: 52.93 / 38.52 / 48.70
  
  — [arXiv 2506.05690](https://arxiv.org/html/2506.05690)
- Medical corpus: RAG with rerank scored 64.73 on fact accuracy, HippoRAG2 66.28 on fact and 61.98 on reasoning, LightRAG 63.32 on fact and 61.32 on reasoning. MS-GraphRAG fell to 38.63 on fact. One secondary note says reranked RAG (65.75%) beat HippoRAG2 (63.08%) on medical contextual summarization, so graph wins are not universal. — [arXiv 2506.05690](https://arxiv.org/html/2506.05690); [Persistent blog (S)](https://www.persistent.com/blogs/when-does-graphrag-outperform-traditional-rag/)
- Average prompt tokens per query on the novel corpus:
  - vanilla RAG: 879
  - HippoRAG2: 1,008
  - RAPTOR: 3,441
  - Fast-GraphRAG: 4,204
  - HippoRAG: 7,208
  - MS-GraphRAG local: 38,707
  - LightRAG: 100,832
  - MS-GraphRAG global: 331,375

  The paper's text elsewhere says about 4×10⁴ for global, which is an internal inconsistency in the source. — [arXiv 2506.05690](https://arxiv.org/html/2506.05690)
- Authors' conclusions: basic RAG matches or beats GraphRAG on simple fact retrieval, where extra graph context adds noise. Graphs help on complex reasoning and summarization. Token inflation (LightRAG, GraphRAG global) can hurt context relevance. One summary also reports that as the corpus grows from 56k to 1.1M tokens, vanilla RAG's complex-reasoning performance drops while GraphRAG stays more stable. That is secondary and I did not verify it in the paper. — [arXiv 2506.05690](https://arxiv.org/html/2506.05690); [ML Digest (S)](https://ml-digest.com/when-to-use-kg-rag/)

**Independent benchmark 2: "RAG vs. GraphRAG: A Systematic Evaluation and Key Insights" (Han et al., arXiv 2502.11371, PP)**
- RAG is stronger on single-hop, detail-focused factual questions. GraphRAG is better on multi-hop, reasoning-heavy questions. For query-based summarization, RAG keeps fine-grained details while GraphRAG gives more diverse, corpus-level summaries. Neither wins consistently, and the two are complementary. The paper flags noisy or incomplete graph construction, extra compute and storage, and position bias in LLM-as-judge summarization evaluation (a known weakness of the original GraphRAG and LazyGraphRAG win-rate methodology). — [arXiv 2502.11371](https://arxiv.org/html/2502.11371v2)

**Cost multiples (indexing)**
- LazyGraphRAG indexing costs about 0.1% of full GraphRAG, which puts full GraphRAG indexing at roughly 1000x vector RAG on Microsoft's own framing. — [Microsoft Research (V)](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)
- One preprint measured LightRAG default indexing at 42.42M tokens (about $7.39) vs 7.77M (about $1.59) for its own method on its corpus. This is a single setup and not generalizable. — [M-RAG arXiv 2603.26667 (PP)](https://arxiv.org/pdf/2603.26667)
- A 2026 commentary piece argues that the about-1,000x index bill is "the small one" and that query-time token cost dominates. This is opinion, and it is consistent with the GraphRAG-Bench token figures. — [beri.net (S)](https://www.beri.net/article/graphrag-vs-vector-rag-indexing-query-cost-lightrag-lazygraphrag-2026)
- Efficiency-focused successors appeared in 2025–26 (E²GraphRAG, LinearRAG, LiteSemRAG, EraRAG), aiming at cheaper or LLM-free graph construction and incremental growth. These are all preprints with author-reported results. — [E²GraphRAG](https://arxiv.org/pdf/2505.24226); [LinearRAG](https://arxiv.org/pdf/2510.10114); [LiteSemRAG](https://arxiv.org/pdf/2604.16350); [EraRAG](https://arxiv.org/pdf/2506.20963)

### Inferences
- Default to vector plus reranker for factoid lookups. Route multi-hop and "global / summarize the corpus" questions to a graph path. A query router (classifying question type) is therefore a core component, not an add-on.
- HippoRAG2-style designs (passage nodes plus a PPR-walked entity graph) give graph benefits at near-vector query cost (about 1.15x tokens), so they are the strongest default graph-retrieval candidate on current evidence. GraphRAG-style community summaries are worth their cost only for global sensemaking workloads.
- RAPTOR-style trees underperformed on fact and reasoning in GraphRAG-Bench but had the highest creative-task faithfulness (70.85). Use them as a summarization index, not a primary retriever.

### Gaps
- Not verified this session: KAG (Ant Group/OpenSPG), nano-graphrag, and Fast-GraphRAG internals and current repo status; MS GraphRAG's latest release and whether LazyGraphRAG/DRIFT are in OSS.
- There is a second benchmark also named "GraphRAG-Bench" (domain-specific reasoning, a different author group), which I did not fetch. The report writer should avoid conflating the two.
- No independent study found that measures absolute indexing $ or time across all variants on the same corpus. GraphRAG-Bench's visible content did not include indexing cost.

## Hybrid vector + graph retrieval: evidence

### Takeaway
Hybrid evidence is positive but thin. Most of it comes from author-run preprints. The strongest independent signal is indirect: benchmarks show RAG and GraphRAG fail on different question types, so combining them should help.

### Cited Findings
- HybridRAG (Sarmah et al., BlackRock/NVIDIA, arXiv 2408.04948, Aug 2024, PP) [2024]: combines vector and KG context on financial earnings-call transcripts. It reports beating both standalone VectorRAG and GraphRAG on retrieval and generation metrics (faithfulness, answer relevance, context relevance). I found no independent replication. — [arXiv 2408.04948](https://arxiv.org/abs/2408.04948v1)
- Han et al. propose two hybrids, Selection (route each query to RAG or GraphRAG) and Integration (merge both contexts), motivated by the two being complementary. They report improvements over either alone (author-reported). — [arXiv 2502.11371](https://arxiv.org/html/2502.11371v2)
- HippoRAG2 is itself a hybrid (dense passage retrieval seeds plus a graph walk over passage and phrase nodes) and is the top or near-top performer across task types in independent GraphRAG-Bench. — [arXiv 2506.05690](https://arxiv.org/html/2506.05690); [arXiv 2502.14802](https://arxiv.org/abs/2502.14802)
- An LLM-assisted incremental multi-source fusion KG used for GraphRAG reported context recall of 0.876 vs 0.737 for its baseline on a 50-question benchmark. The sample is small. — [ScienceDirect S2667305326000499](https://www.sciencedirect.com/science/article/pii/S2667305326000499)

### Inferences
- The toolkit should store chunks with embeddings and graph nodes/edges linked to chunks (passage nodes), so that one store can serve vector-only, graph-only and hybrid retrieval. Routing and integration can then be compared empirically on the user's own data.

### Gaps
- No large, independent hybrid-vs-single-mode benchmark across domains was found.
- Not verified: Neo4j's or other vendors' hybrid retrievers (e.g., VectorCypherRetriever) and any vendor accuracy claims.

## Graph-based agent memory: Graphiti/Zep, Mem0 graph, Cognee, Letta; temporal and bitemporal modeling; benchmark claims

### Takeaway
Temporal KGs are the leading graph-memory design. Zep/Graphiti's bitemporal edges keep "true when" separate from "learned when" and invalidate old facts instead of deleting them. Benchmark claims in this area are almost entirely vendor-run and contested: the Zep vs Mem0 LoCoMo dispute is unresolved, and reproducibility problems have been documented. Mem0's own paper shows its graph variant adds only about 2% over its non-graph memory.

### Cited Findings
- Zep paper (arXiv 2501.13956, Jan 2025, V-authored preprint): Graphiti is a temporally aware KG engine. It reports DMR 94.8% vs MemGPT 93.4%, LongMemEval accuracy gains of up to 18.5% over baselines, and 90% lower response latency than baselines. The authors note DMR is near-saturated for full-context baselines with modern LLMs, so LongMemEval is the more informative test. — [arXiv 2501.13956](https://arxiv.org/abs/2501.13956)
- Bitemporal model: one timeline tracks when facts were true in the world (valid/invalid), and another tracks when the system ingested or expired them (transactional). Each fact edge carries four timestamps. On contradiction, the old edge is invalidated (its invalid time is set to the new edge's valid time) rather than deleted, which preserves history. — [Emergent Mind summary of 2501.13956 (S)](https://www.emergentmind.com/papers/2501.13956); [Graphiti docs (V)](https://help.getzep.com/graphiti/graphiti/overview/)
- Graphiti is open source under Apache-2.0 (pip `graphiti-core`). — [Graphiti docs (V)](https://help.getzep.com/graphiti/graphiti/overview/)
- Mem0 paper (arXiv 2504.19413, Apr 2025, V-authored): Mem0 reports a 26% relative improvement over OpenAI memory on LoCoMo (LLM-as-judge). The graph variant Mem0g scores about 2% higher than base Mem0. Mem0 reports 91% lower p95 latency and more than 90% token savings vs full context. — [arXiv 2504.19413](https://arxiv.org/abs/2504.19413)
- LoCoMo dispute (vendor vs vendor):
  - Zep first claimed 84% on LoCoMo. Mem0 said this included adversarial questions the benchmark excludes, bringing it to 58.44%. Zep revised its own figure to 75.14% and argues Mem0's paper misimplemented Zep, which Mem0 reported at 65.99%. — [Zep blog (V)](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/); [Atlan comparison (S)](https://atlan.com/know/zep-vs-mem0/)
  - 2026 headline claims: Mem0 92.5% LoCoMo and 94.4% LongMemEval for a new retrieval algorithm, and Zep 94.7% LoCoMo. These use different models and setups and are not comparable. — [Mem0 blog (V)](https://mem0.ai/blog/ai-memory-benchmarks-in-2026); [Atlan (S)](https://atlan.com/know/zep-vs-mem0/)
- Reproducibility: ATANT v1.1 (arXiv 2604.10981, PP) reports that practitioners could not reproduce Mem0's published LoCoMo numbers with its open-source harness, and flags a refusal-matching bug in that harness. — [arXiv 2604.10981](https://arxiv.org/pdf/2604.10981)
- Newer research designs include hierarchical-graph memory with dual-route retrieval (Mnemis, arXiv 2602.15313, PP). — [arXiv 2602.15313](https://arxiv.org/pdf/2602.15313)
- Practitioner comparisons of Mem0, Zep, Graphiti, Letta, LangMem and Cognee conclude that no system wins across all dimensions. These are opinion pieces. — [Medium (S)](https://medium.com/@wasowski.jarek/i-compared-5-ai-agent-memory-systems-across-6-dimensions-none-wins-6a658335ed0a); [AI Engineer substack (S)](https://theaiengineer.substack.com/p/cognee-vs-zep-vs-mem0-vs-letta)

### Inferences
- The toolkit's graph schema should adopt bitemporal edges (valid_from/valid_to plus recorded_at/expired_at) and invalidate rather than delete. This is low-cost and supports both agent memory and incremental document updates.
- Treat all memory-benchmark numbers as vendor marketing unless reproduced. A toolkit that ships a neutral, reproducible LoCoMo/LongMemEval harness would add real value.
- Mem0g's small (about 2%) gain over non-graph Mem0 suggests that the benefit of graph memory for conversational recall is modest. Graphs matter more for temporal reasoning and contradiction handling.

### Gaps
- Not verified this session: Cognee's architecture and license; Letta's memory model (Letta is primarily tiered or archival memory, not a KG, and needs confirmation); the current Mem0 graph backend support list.
- I found no fully independent replication of Zep or Mem0 LongMemEval numbers.

## Graph stores: Neo4j, Memgraph, FalkorDB, Kuzu, Apache AGE, NebulaGraph, lakehouse, RDF; licenses and embeddability

### Takeaway
The embeddable, permissively licensed slot changed in late 2025. Kuzu (MIT, embedded) was archived in Oct 2025 after a reported Apple acquisition, and the community fork LadybugDB is now its main successor. Among server databases, only Apache AGE (a Postgres extension), NebulaGraph, ArcadeDB and HugeGraph are under OSI-approved permissive licenses. Neo4j Community is GPLv3 and single-instance, Memgraph is BSL 1.1, and FalkorDB is SSPLv1, which restricts offering it as a service.

### Cited Findings
- Kuzu: GitHub repo archived in October 2025. Sources give 10 Oct 2025, and one says September. It was reportedly acquired by Apple, but sources differ on the exact framing. The archived code remains usable under MIT but receives no fixes or security patches. — [gdotv blog (S)](https://gdotv.com/blog/kuzu-legacy-embedded-graph-database-landscape/); [The Data Quarry (S)](https://thedataquarry.com/blog/from-kuzu-to-ladybug/); [gdotv Weekly Edge 24 Oct 2025 (S)](https://gdotv.com/blog/weekly-edge-kuzu-forks-duckdb-graph-cypher-24-october-2025/)
- LadybugDB, the community fork (MIT):
  - It keeps Kuzu's Cypher dialect, columnar storage, and full-text and vector indexes. v0.15 was released 1 Mar 2026. Migration is Kuzu EXPORT then Ladybug IMPORT. — [LadybugDB blog](https://blog.ladybugdb.com/post/ladybug-spreading-its-wings/); [The Data Quarry (S)](https://thedataquarry.com/blog/from-kuzu-to-ladybug/)
  - One source reports 20+ releases, 1,000+ commits and 80+ contributors. — [gdb-engines (S)](https://gdb-engines.com/db/ladybugdb/)
  - Other forks are Bighorn (Kineviz), RyuGraph, and Vela Partners' multi-writer fork. — [gdotv (S)](https://gdotv.com/blog/kuzu-legacy-embedded-graph-database-landscape/); [Vela Partners (V)](https://vela.partners/blog/kuzudb-ai-agent-memory-graph-database)
  - ArcadeDB (a competitor) describes such forks as "early-stage experiments" without funding or a roadmap. This is a biased source. — [ArcadeDB blog (V)](https://arcadedb.com/blog/neo4j-alternatives-in-2026-a-fair-look-at-the-open-source-options/)
- Licenses:
  - Neo4j Community: GPLv3, one database on a single instance, with clustering only in Enterprise.
  - Memgraph Community: BSL 1.1, converting to Apache 2.0 in July 2030. One table lists Apache 2.0, which appears to be an error.
  - FalkorDB: SSPLv1. It can be self-hosted but cannot be offered as a managed service.
  - Apache AGE: Apache-2.0 Postgres extension.
  - NebulaGraph: Apache 2.0 Community Edition.
  - ArcadeDB and HugeGraph: Apache 2.0.

  — [ArcadeDB OSS GraphRAG DB comparison (V)](https://arcadedb.com/blog/open-source-knowledge-graph-graphrag-databases-compared/); [Flur.ee (V)](https://flur.ee/blog/neo4j-alternatives); [HydraDB (V)](https://hydradb.com/blog/open-source-graph-databases); [renezander FalkorDB vs Neo4j (S)](https://renezander.com/guides/falkordb-vs-neo4j/)
- Popularity: the GDB-Engines Cypher ranking for Oct 2026 puts Neo4j first (86.6), then Memgraph (67.8) and FalkorDB (66.0), with Apache AGE at 56.8. This is an aggregator index, not a quality measure. — [GDB-Engines rankings (S)](https://gdb-engines.com/rankings/cypher/)
- Graph in the lakehouse or analytics engines: an Oct 2025 industry newsletter headlines "DuckDB goes graph" and Cypher 25, pointing to DuckDB-based graph querying as a lakehouse-adjacent option. Details were not verified. — [gdotv Weekly Edge (S)](https://gdotv.com/blog/weekly-edge-kuzu-forks-duckdb-graph-cypher-24-october-2025/)

### Inferences
- For an OSS toolkit that may be embedded or redistributed, the licensing-safe defaults are: an embedded LadybugDB (MIT, with fork-maturity risk), Postgres + Apache AGE (Apache-2.0, which pairs naturally with pgvector), or a pluggable driver layer over Cypher. Neo4j (GPLv3), Memgraph (BSL) and FalkorDB (SSPL) should be optional backends, not hard dependencies, especially if anyone might offer the toolkit as a hosted service.
- Kuzu's archiving is a concrete lesson in vendor and maintenance risk. Abstract the store behind an interface (e.g., openCypher/GQL subset plus a portable export format such as Parquet nodes/edges tables) so backends can be swapped.

### Gaps
- Not verified this session: RDF stores (Apache Jena/Fuseki, Oxigraph, GraphDB, Virtuoso, QLever) and their licenses; ISO GQL support status across engines; Neo4j's current vector-index features; lakehouse graph options (PuppyGraph over Iceberg/Delta, DuckPGQ, Spark GraphFrames); FalkorDB's embedded "FalkorDBLite" status.
- License facts come from vendor or secondary comparisons. The report writer should check LICENSE files before making firm statements.

## Query interfaces: text-to-Cypher/SPARQL/GQL accuracy vs predefined graph tools

### Takeaway
Zero-shot text-to-Cypher on realistic, full-scale graphs is unreliable. The CypherBench (ACL 2025) baseline was about 60% execution accuracy for frontier models and under 20% for models below 10B parameters. Enterprise-schema benchmarks are much worse for small local models. Database-grounded correction or agentic self-refinement lifts this to roughly 88–95% in 2026 preprints. For agents, predefined parameterized graph tools plus a guarded text-to-Cypher fallback is the evidence-consistent design.

### Cited Findings
- CypherBench (ACL 2025, PR) uses full-scale Wikidata-derived property graphs. Zero-shot execution accuracy: Claude 3.5 Sonnet 61.6%, GPT-4o 60.2%, best open-source model 41.9%. No model under 10B parameters exceeded 20%. — [ACL Anthology 2025.acl-long.438](https://aclanthology.org/2025.acl-long.438.pdf); [arXiv 2412.18702](https://arxiv.org/html/2412.18702v1)
- CypherGuard (arXiv 2610.41755, PP, Oct 2026) adds a database-grounded correction layer. On all 2,348 CypherBench test questions it reports 88.50% overall execution accuracy. It reports lifting gpt-5.4-mini from 63.42% to 88.50% and sonnet-4.6 from 71.76% to 94.68%. These are author-reported. — [arXiv 2610.41755](https://arxiv.org/html/2610.41755v1)
- CYPHERTURN (arXiv 2609.36987, PP): on a multi-turn conversational text-to-Cypher benchmark, the best model reaches only 64.7% execution accuracy. — [arXiv 2609.36987](https://arxiv.org/pdf/2609.36987)
- PIPE-Cypher (arXiv 2606.08481, PP) auto-generates enterprise benchmarks. A local Qwen3.5-9B baseline gets 0.189 execution accuracy, and the zero-shot average across 11 local models is 0.036. — [arXiv 2606.08481](https://arxiv.org/html/2606.08481v1)
- LAST-CQ (arXiv 2609.12746, PP) studies what drives recovery in agentic, self-refining text-to-Cypher. — [arXiv 2609.12746](https://arxiv.org/pdf/2609.12746)

### Inferences
- Agents should get mostly typed, predefined graph tools, such as get_entity, neighbors(k-hop, edge types, time window), path_between, community_summary and facts_about(entity, as_of). Free-form Cypher should sit behind schema injection, read-only enforcement, EXPLAIN/dry-run validation and DB-grounded repair. Small local models should not be trusted with raw text-to-Cypher.
- I found no direct head-to-head between "predefined tools" and "text-to-Cypher" for agents. The recommendation is inferred from the low zero-shot accuracy plus the large gains from grounding and correction.

### Gaps
- I found no current text-to-SPARQL or text-to-GQL accuracy numbers comparable to CypherBench in this session. Neo4j's Text2Cypher dataset and fine-tuned model results (2024–25) were not fetched.
- No independent benchmark of MCP-style graph tool interfaces vs generated queries was found.

## Incremental updates, provenance to source spans, and graph-quality evaluation

### Takeaway
Community-summary designs (MS GraphRAG) are expensive to update because new data forces re-clustering and re-summarizing. LightRAG, HippoRAG-style and temporal-KG designs (Graphiti) support cheaper incremental inserts. Provenance is usually kept at chunk ("text unit") level rather than character spans. Graph-quality evaluation is fragmented across fact-recoverability (MINE), triple P/R/F1, ER/RR P/R/F1, structural statistics and downstream QA.

### Cited Findings
- GraphRAG 1.0 added an `update` command that computes deltas between an existing index and new content and relies on an LLM cache, so re-runs are "often significantly faster and cheaper". Community restructuring remains the cost driver. — [beri.net (S)](https://www.beri.net/article/graphrag-vs-vector-rag-indexing-query-cost-lightrag-lazygraphrag-2026); [LearnOpenCV (S)](https://learnopencv.com/lightrag/)
- EraRAG (arXiv 2506.20963, PP) states that GraphRAG performs full re-clustering after each update, causing excessive time and memory use. It proposes hyperplane-based LSH bucketing for incremental growth of a hierarchical graph. — [arXiv 2506.20963](https://arxiv.org/pdf/2506.20963)
- LightRAG updates with minimal API calls because it has no community reports to rebuild. The LightRAG paper's cost analysis is cited at about 1,399 × 2 × 5,000 tokens for GraphRAG community regeneration on its legal corpus (secondary citation). — [LearnOpenCV (S)](https://learnopencv.com/lightrag/); [Maarga Systems (S)](https://www.maargasystems.com/2025/05/12/understanding-graphrag-vs-lightrag-a-comparative-analysis-for-enhanced-knowledge-retrieval/)
- Graphiti ingests "episodes" incrementally and resolves contradictions by edge invalidation with bitemporal timestamps, which supports point-in-time queries. — [Graphiti docs (V)](https://help.getzep.com/graphiti/graphiti/overview/); [Emergent Mind (S)](https://www.emergentmind.com/papers/2501.13956)
- ATOM (arXiv 2510.22590, PP) targets dynamic temporal KG construction and reports P/R/F1 for entity and relation resolution as the KG evolves. — [arXiv 2510.22590](https://arxiv.org/pdf/2510.22590)
- Quality metrics in use:
  - MINE fact recoverability by LLM judge — [arXiv 2502.09956](https://arxiv.org/pdf/2502.09956)
  - Triple-level and graph-level P/R/F1, graph edit distance and G-BERTScore — [Frontiers](https://www.frontiersin.org/journals/big-data/articles/10.3389/fdata.2025.1505877/full); [GraphJudge](https://aclanthology.org/2025.emnlp-main.554.pdf)
  - Structural statistics (average degree, clustering coefficient) correlating with retrieval quality — [GraphRAG-Bench](https://arxiv.org/html/2506.05690)
  - Downstream QA accuracy and retrieval recall/relevance by task type — [GraphRAG-Bench](https://arxiv.org/html/2506.05690)

### Inferences
- Toolkit design implications:
  1. Make every node and edge carry provenance (source doc id, chunk id and, ideally, character offsets, plus extractor model/version and timestamp), so facts can be re-derived or retracted when a source changes.
  2. Prefer append-plus-invalidate over rewrite.
  3. Recompute expensive global artifacts (communities, summaries) lazily or on schedule, LazyGraphRAG-style, not on every insert.
  4. Ship an evaluation harness combining MINE-style recoverability, ER P/R/F1 on a labelled sample, structural statistics and task-typed QA (fact / multi-hop / global).

### Gaps
- I found no benchmark that measures provenance fidelity (whether the cited span actually supports the fact) for GraphRAG systems.
- I did not confirm how MS GraphRAG's update path maintains text-unit provenance, or whether any major framework stores character-level spans by default.
- I found no independent measurement of incremental-update cost across GraphRAG variants on the same corpus.
