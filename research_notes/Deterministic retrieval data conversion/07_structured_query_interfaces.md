# 07 Structured Query Interfaces: how agents query converted databases reliably (text-to-SQL, text-to-Cypher/SPARQL, semantic layers, predefined query tools)

Scope note: this track covers the query interface over data that has already been converted into typed records, and how schema design changes agent query accuracy. Dates are publication or first-arXiv dates. "Author-reported" means the number comes from the paper or vendor that built the method. "Independent" means a third party measured it. Leaderboard entries are self-submitted, and the benchmark maintainers run them on hidden test sets. They are independent of the method authors, but the gold labels themselves are known to be noisy (see Q1).

## Q1. Text-to-SQL state of the art 2025-2026: benchmarks, methods, the gap between academic and enterprise schemas, and evaluation pitfalls

### Takeaway
On clean academic schemas, text-to-SQL is close to saturated: BIRD test execution accuracy (EX) is 83.4% against a human score of 92.96%, and one 2026 RL system reports human-level 92.96% on an expert-verified BIRD. On enterprise-shaped tasks it remains unreliable: BEAVER (real warehouse query logs) gives 10.8% with GPT-5.2 agents, BIRD-Interact gives 8.7–17% for GPT-5, and LiveSQLBench gives at most 57%. Gold-label errors of 50–60% in BIRD Mini-Dev and Spider 2.0-Snow mean that small leaderboard differences are not trustworthy. Free-form text-to-SQL is therefore an accuracy-limited and non-deterministic generation step. It should be wrapped with verification, used against well-modeled schemas, or replaced by constrained interfaces for repeatable queries.

### Cited Findings
**Benchmarks (academic → enterprise)**
- Spider 1.0 (2018, EMNLP; foundational): 10,181 questions and 5,693 SQL queries over 200 multi-table databases covering 138 domains, with cross-database train/test splits. The best model at release scored 12.4% exact match. — [Spider, Yu et al. 2018](https://arxiv.org/abs/1809.08887)
- BIRD (NeurIPS 2023): 12,751 question-SQL pairs over 95 databases totalling 33.4 GB across 37 domains. It emphasises dirty values, external knowledge ("evidence"), and SQL efficiency. — [BIRD, Li et al. 2023](https://arxiv.org/abs/2305.03111)
- The BIRD leaderboard (accessed Nov 2026) has top test EX of 83.40 (AskData, AT&T CDO, 26 Sep 2026), 82.95 (GrainSQL), and 82.39 (Huawei DataGallery). Human performance is 92.96. The maintainers released a cleaner dev split `bird-sql-dev-1106` in Nov 2025, are removing oracle evidence in favour of an interactive track, and since July 2023 have accepted tied results for `ORDER BY … LIMIT 1`. — [BIRD leaderboard](https://bird-bench.github.io/)
- Spider 2.0 (ICLR 2025 Oral) has 632 enterprise workflow tasks over BigQuery, Snowflake and SQLite. Databases often exceed 1,000 columns, tasks need dialect docs and codebases, and SQL often runs past 100 lines. An o1-preview code agent solved 21.3%, against 91.2% on Spider 1.0 and 73.0% on BIRD. — [Spider 2.0, Lei et al. 2024](https://arxiv.org/abs/2411.07763)
- The Spider 2.0 leaderboard (accessed Nov 2026) has 547 examples each in Snow and Lite and 68 DBT tasks. Top scores are Snow 96.70 (Genloop Sentinel Agent v2 Pro), Lite 76.23 (Tencent Tianqiong Data Agent + GLM 5.2) and DBT 65.6 (SignalPilot). The maintainers keep a data-update log and warn that "scores may change slightly over time". Runs that use gold tables are excluded from ranking. — [Spider 2.0 leaderboard](https://spider2-sql.github.io/)
- BEAVER (2024; v3 updated 2026) is the first benchmark built from private enterprise data warehouses. It has 9,128 question-SQL pairs from real query logs over 812 tables in 19 domains. SOTA agentic frameworks with GPT-5.2 reach only 10.8%, and 30.1% with oracle subtask hints. Residual errors include use of advanced functions. — [BEAVER, Chen et al.](https://arxiv.org/abs/2409.02038)
- BIRD-Interact (ICLR 2026 Oral) evaluates multi-turn interaction with a hierarchical knowledge base, metadata files and a function-driven user simulator across full CRUD. It has 600 full and 300 lite tasks. GPT-5 completes 8.67% in conversational mode (c-Interact) and 17.00% in agentic mode (a-Interact). — [BIRD-Interact, Huo et al. 2025](https://arxiv.org/abs/2510.05318)
- BIRD-CRITIC / SWE-SQL (NeurIPS 2025) is a SQL-debugging benchmark of 530 PostgreSQL and 570 multi-dialect tasks. o3-mini solves 38.87% (PG) and 33.33% (multi). The open 14B Bird-Fixer reaches 38.11% and 29.65%. — [SWE-SQL, Li et al. 2025](https://arxiv.org/abs/2506.18951)
- LiveSQLBench (BIRD team) is contamination-resistant: each release's hidden test becomes the next release's dev set.
  - Releases: Base-Lite (May 2025, 270 tasks over 18 DBs), Base-Full v1 (Sep 2025, 600 tasks over 22 DBs) and Large-v1 (Mar 2026, 480 tasks over ~1,000-column DBs, ~84K-token prompts, with "business rule drift").
  - Top scores: 57.00 (AntQL 1.1 with Claude Opus 5.5, Oct 2026), GPT-5.5 (low) 33.50, Gemini 3.1 Pro 36.50.
  - Scoring: SELECTs are scored by result comparison and DML/DDL by test cases.
  - — [LiveSQLBench](https://livesqlbench.ai/)
- DSABench (Oct 2026) covers multi-database source discovery: 815 tasks, 618 of which need several databases. Best routing-only RA-Set is 60.55%, but routing plus execution success has a median of 6.69–7.98%, rising to 16.99% at best with one clarification. — [DSABench, Luo et al. 2026](https://arxiv.org/abs/2610.14700)
- FLINT (EMNLP Industry 2026): on production financial schemas where concepts are opaque integer keys, general text-to-SQL methods "fall below 50%". FLINT adds a lookup agent, retrieval from an expert-authored bank of query templates, and foreign-key-chain schema linking. It is deployed in production. — [FLINT, Sehanobish et al. 2026](https://arxiv.org/abs/2610.03524)

**Methods (how each works / accuracy / cost / determinism / failure modes)**
- DIN-SQL (NeurIPS 2023) decomposes the task (schema linking → classification → generation → self-correction) and uses in-context learning. Author-reported: Spider test 85.3, BIRD test 55.9. It costs several LLM calls per question. — [DIN-SQL, Pourreza & Rafiei 2023](https://arxiv.org/abs/2304.11015)
- DAIL-SQL (VLDB 2024) systematically compares question representation and example selection/organisation, and stresses token efficiency. Author-reported: 86.6% EX on Spider. — [DAIL-SQL, Gao et al. 2023](https://arxiv.org/abs/2308.15363)
- MAC-SQL (COLING 2025) uses a decomposer agent plus a selector (sub-database) and a refiner (fixes erroneous SQL using execution). — [MAC-SQL, Wang et al. 2023](https://arxiv.org/abs/2312.11242)
- CHESS (2024) has four agents: information retriever (values), schema selector, candidate generator with iterative refinement, and unit tester (LLM-written natural-language unit tests). Author-reported: 71.10% on BIRD test. The schema selector gives about +2% and cuts tokens about 5×, and CHESS needs about 83% fewer LLM calls than the leading proprietary method. — [CHESS, Talaei et al. 2024](https://arxiv.org/abs/2405.16755)
- CHASE-SQL (2024) spends test-time compute: it generates diverse candidates (divide-and-conquer, query-plan CoT, synthetic examples) and picks one with a fine-tuned pairwise selector. Author-reported: 73.0% BIRD test, top of the board when submitted. — [CHASE-SQL, Pourreza et al. 2024](https://arxiv.org/abs/2410.01943)
- XiYan-SQL (2024) uses an M-Schema semi-structured schema representation, a multi-generator ensemble (fine-tuned plus in-context), a refiner and a fine-tuned selection model. Author-reported: 75.63% BIRD, 89.65% Spider test, 41.20% NL2GQL. — [XiYan-SQL, Gao et al. 2024](https://arxiv.org/abs/2411.08599)
- OmniSQL (2025) synthesises SynSQL-2.5M (2.5M samples over more than 16,000 synthetic DBs, with chain-of-thought). Its open 7B/14B/32B models match or beat GPT-4o and DeepSeek-V3 across nine datasets (author-reported). This matters for self-hosted, privacy-preserving deployments. — [OmniSQL, Li et al. 2025](https://arxiv.org/abs/2503.02240)
- Alpha-SQL (ICML 2025) is zero-shot Monte Carlo tree search over SQL construction actions. Author-reported: 69.7% BIRD dev with a 32B open model. — [Alpha-SQL, Li et al. 2025](https://arxiv.org/abs/2502.17248)
- Arctic-Text2SQL-R1 (2025) uses RL with a reward based only on execution correctness. Its 7B model beats prior 70B-class systems and was top of BIRD at the time (author-reported). — [Arctic-Text2SQL-R1, Yao et al. 2025](https://arxiv.org/abs/2505.20315)
- Reasoning-SQL (2025) uses GRPO with partial rewards (schema linking, AI feedback, n-gram, syntax). Its 14B model is about 4% above o3-mini on BIRD (author-reported). — [Reasoning-SQL, Pourreza et al. 2025](https://arxiv.org/abs/2503.23157)
- ReFoRCE (Snowflake, 2025) is an agent that uses:
  - pattern-based table grouping and LLM schema linking for compression
  - dialect-aware self-refinement
  - majority-vote consensus that defers low-confidence cases
  - iterative column exploration guided by execution feedback

  Author-reported: 35.83 on Spider 2.0-Snow and 36.56 on Lite, SOTA when published. — [ReFoRCE, Deng et al. 2025](https://arxiv.org/abs/2502.00675)
- HarnessSQL (Oct 2026) trains SQL agents inside their execution harness (SFT on verified trajectories, then execution-reward RL). Spider 2.0-SQLite: Qwen3-8B goes from 15.5% to 45.2% and Qwen3-14B from 22.2% to 54.8% (author-reported). It transfers to BIRD-Interact and LiveSQLBench. — [HarnessSQL, Yang et al. 2026](https://arxiv.org/abs/2610.12274)
- ReViSQL / BIRD-Platinum (2026): expert verification of 2.5k BIRD Train instances found errors in 61% of them. Fine-tuning on the clean data gives +11–16%. Result-based RL rewards have "non-trivial false positive rates", so the authors combine them with SQL-equivalence verification. ReViSQL-BIRD-K2.6 scores 92.96% on Arcwise-Plat, an expert-verified BIRD (author-reported "human-level"). — [Zhu et al. 2026](https://arxiv.org/abs/2603.20004)
- Schema linking is contested:
  - "Death of Schema Linking" (2024) skips linking whenever the schema fits in context and reached 71.83% on BIRD. — [Maamari et al. 2024](https://arxiv.org/abs/2408.07702)
  - AT&T (2025) disagrees on BIRD MiniDev with GPT-4o and no hints: full schema 61.2%, their linking 63.2%, perfect linking 69.0%. — [Shkapenyuk et al. 2025](https://arxiv.org/abs/2505.19988)
- Long-context NL2SQL (VLDB 2025): Gemini-1.5-pro "do[es] not get lost" in long context, and adding column example values, question-SQL pairs, hints and docs helps without self-consistency. — [Chung et al. 2025](https://arxiv.org/abs/2501.12372)
- Surveys: [Liu et al., TKDE 2025](https://arxiv.org/abs/2408.05109); [Hong et al., TKDE 2025](https://arxiv.org/abs/2406.08426).

**Evaluation pitfalls**
- BIRD noise (2024): incorrect gold SQL is prevalent. On corrected gold queries, zero-shot baselines surpassed state-of-the-art prompting methods. — [Wretblad et al. 2024](https://arxiv.org/abs/2402.12243)
- Expert re-annotation (2026):
  - Error rates: annotation errors in 52.8% of BIRD Mini-Dev (263/498) and 62.8% of Spider 2.0-Snow (76 of 121 public-gold tasks). The Spider 2.0 team had already corrected 45% and then 5% of examples during validation.
  - Effect on agents: re-scoring 16 open-source BIRD agents shifts performance by −7% to +31% relative and ranks by −9 to +9.
  - Rank correlation: uncorrected-subset ranks correlate with full-dev ranks (Spearman 0.85) but not with corrected ranks (0.32).
  - — [Jin et al. 2026](https://arxiv.org/abs/2601.08778)
- EX has false positives and negatives. LLM-judged FLEX raises agreement with human experts from κ 62 to 87.04, shifts models +2.6 points on average, and changes Spider and BIRD rankings. — [FLEX, Kim et al. 2024](https://arxiv.org/abs/2409.19014)
- Test-suite accuracy (EMNLP 2020; foundational) runs queries on distilled test-suite databases. The plain Spider metric had a 2.5% average false-negative rate and 8.1% at worst. — [Zhong et al. 2020](https://arxiv.org/abs/2010.02840)
- Enterprise evaluation (Merkle, 2026): the Hybrid-EX metric uses an LLM to align columns and aliases, then scores cells deterministically. It reaches κ=0.717 against 150 human-annotated industry queries. — [BADGER, Serrao et al. 2026](https://arxiv.org/abs/2606.02109)

### Inferences
- Benchmark results conflict. The Spider 2.0-Snow leaderboard top (96.70) sits beside an independent finding that 62.8% of publicly checkable Snow gold answers were wrong in early 2026. Either the gold has since been fixed, since the maintainers log data updates, or top scores partly reflect fitting to the gold. Treat any single leaderboard number with ±5–10 point uncertainty and prefer verified subsets such as BIRD-Platinum/Arcwise-Plat and bird-sql-dev-1106.
- Accuracy is far from deterministic across settings. The same frontier models score 80%+ on BIRD but 8–57% on interactive, enterprise or living benchmarks. Accuracy depends on schema quality, documentation and ambiguity, which the toolkit controls, more than on the model.
- Most SOTA gains come from test-time compute: multiple candidates, selection, consensus and execution feedback. These multiply cost (CHESS, CHASE and ReFoRCE make many LLM calls) and make the generated SQL vary from run to run. The determinism the user wants therefore has to come from persisting and re-executing an accepted query, not from regenerating it.
- For an open-source toolkit, open models like OmniSQL, Arctic-R1 and HarnessSQL-trained Qwen3 show that self-hosted text-to-SQL is viable. Fine-tuning on the toolkit's own synthetic schema-question pairs is a credible path.

### Gaps
- Independent replications of the top 2026 leaderboard entries (AskData, Genloop, AntQL) are not published. Most are closed systems with no papers.
- I found no rigorous study measuring run-to-run variance of text-to-SQL answers, as opposed to accuracy, across SOTA pipelines on the same snapshot.
- I could not confirm whether Spider 2.0 gold was corrected after the Jin et al. audit.

## Q2. Text-to-Cypher, text-to-SPARQL and GQL: accuracy, verification and repair

### Takeaway
Graph query generation trails SQL. Zero-shot frontier models score about 60% EX on CypherBench, small models under 20%, and complex SPARQL benchmarks top out around 45% for older LLMs. Gains come from (a) presenting the LLM a small, readable property-graph or ontology view instead of a raw RDF schema, (b) synthetic fine-tuning data, and (c) verification against grammar, schema or ontology plus selective repair. On narrow enterprise graphs with fine-tuning, execution F1 reaches 0.95 and above. Ontology-checked SPARQL reached 72% on the data.world enterprise benchmark, against 16% for raw SQL.

### Cited Findings
- CypherBench (2024): RDF knowledge graphs like Wikidata are hard for LLMs because:
  - schemas are huge (more than 4M entity types and 12k relation types)
  - entities are opaque IDs (QIDs/PIDs)
  - relations overlap
  - values are unnormalised

  The authors propose property-graph views over RDF, queried in Cypher. The benchmark has 11 graphs with about 7.8M entities and more than 10k questions (2,488 test), plus a provenance-subgraph metric (PSJS).
  - Zero-shot EX: claude-3.5-sonnet 61.58%, gpt-4o 60.18%, qwen2.5-72b 41.87%, all <10B models under 20%.
  - Top errors: reversed relation direction, entity-linking mistakes, schema-valid patterns that don't match intent. Small models make more schema violations.
  - — [CypherBench, Feng et al. 2024](https://arxiv.org/abs/2412.18702)
- Text2Cypher (Neo4j, 2024) combined, cleaned and syntax-validated 16 of 25 public datasets into 44,387 instances. Fine-tuning improved Google-BLEU and exact match, with smaller gains for strong models. One public fine-tuned baseline had seen 14.4% of the test data, a contamination warning. — [Ozsoy et al. 2024](https://arxiv.org/abs/2412.10064)
- Auto-Cypher (NAACL 2025) builds SynthCypher (29.8k) with "LLM-as-Database-Filler", which populates a DB so the generated Cypher can be checked by execution. Fine-tuned 7–8B models gain up to 40% on the Text2Cypher test and 30% on Spider adapted to graphs. — [Tiwari et al. 2024](https://arxiv.org/abs/2412.12612)
- Schema filtering for Text2Cypher (2025) mostly helps smaller models. For large models its value is token-cost reduction. — [Ozsoy 2025](https://arxiv.org/abs/2505.05118)
- Grammar- and schema-aware filtering at test time (2026): grammar filtering raises syntactic validity and schema filtering raises execution quality, but "stronger filtering also increases the number of empty predictions", trading coverage for reliability. — [Ozsoy 2026](https://arxiv.org/abs/2605.10318)
- KG2Cypher (2026, enterprise, Korean) generates executable Cypher from observed graph facts, then LLM questions, validated by an LLM judge and humans. With LoRA SFT, execution-result F1 goes from 0.806 to 0.950 (broadcast) and from 0.70 to 0.92 (company). In an 11-class setting it reaches 95.2% exact match, 99.9% execution rate and 0.964 F1 (author-reported). — [Choi et al. 2026](https://arxiv.org/abs/2606.27742)
- Grounded synthetic KG data (2026) lets small fine-tuned LLMs compete with large proprietary models on the major Text2Cypher benchmarks, a data-sovereignty argument. — [Cazzaro et al. 2026](https://arxiv.org/abs/2606.14325)
- NL2GQL: XiYan-SQL reports 41.20% on NL2GQL ([XiYan](https://arxiv.org/abs/2411.08599)). Multi-turn NL2GQL is an emerging task ([Liang et al. 2025](https://arxiv.org/abs/2508.01871)).
- SPARQL:
  - Spider4SPARQL (2023): 9,693 questions and 4,721 complex SPARQL queries over 166 KGs. KGQA systems and LLMs reach "only up to 45%" execution accuracy. — [Kosten et al. 2023](https://arxiv.org/abs/2309.16248)
  - LLM-KG-Bench (2024): the best LLMs fix SPARQL syntax easily, but "creating semantically correct SPARQL SELECT queries is difficult". — [Meyer et al. 2024](https://arxiv.org/abs/2409.05925)
  - Memorization: benchmark leakage inflates LLM SPARQL scores. Anonymised knowledge injection is proposed to measure it (ICWE 2025 best paper). — [Gashkov et al. 2025](https://arxiv.org/abs/2507.13859)
  - SPARQL-LLM (ACM TWEB 2026) indexes lightweight metadata (query examples, schema) for RAG prompting and validates queries.
    - Results: up to 59% higher F1 than the second-best Text2SPARQL challenge system, up to 27× faster, at most $0.01 per question.
    - Deployment: in production at expasy.org/chat.
    - TEXT2SPARQL 2026: ranked first of eight.
    - — [Smeros et al. 2025](https://arxiv.org/abs/2512.14277); [Smeros et al. 2026](https://arxiv.org/abs/2610.13648); [Emonet et al. 2024 federated version](https://arxiv.org/abs/2410.06062)
  - Text2SPARQL 2025 winner mKGQAgent: planning, entity linking and query refinement with an experience pool. — [Perevalov & Both 2025](https://arxiv.org/abs/2507.16971)
  - ARUQULA: ReAct-style iterative exploration and execution. — [Brei et al. 2025](https://arxiv.org/abs/2510.02200)
  - QALD-9-plus (2022) is the multilingual DBpedia/Wikidata KGQA benchmark. — [Perevalov et al. 2022](https://arxiv.org/abs/2202.00120)
  - Selective repair, GGC (2026): a gate predicts which queries need correction and only those get corrected. Query accuracy on MCQA goes from 90.23% to 98.33%, with 45% less overhead than correcting every query, avoiding damage to already-correct queries. — [Yang et al. 2026](https://arxiv.org/abs/2607.28082)
- data.world enterprise benchmark (2023): insurance schema, 43 questions, GPT-4 zero-shot, SQL vs SPARQL over an OWL ontology plus R2RML mappings.
  - Overall: SQL 16% vs SPARQL 54%.
  - Low question/low schema complexity: 25.5% vs 71.1%.
  - High schema complexity: SQL 0% vs 35.7–38.5%.
  - SQL accuracy fell to zero for questions needing more than five tables.
  - — [Sequeda, Allemang, Jacob 2023](https://arxiv.org/abs/2311.07509)
- Ontology-based Query Check (OBQC) plus LLM repair raises that to 72% accuracy, including 8% "I don't know", for a 20% error rate. — [Allemang & Sequeda 2024](https://arxiv.org/abs/2405.11706)

### Inferences
- For a toolkit that builds graphs from documents, the CypherBench lesson transfers directly. Expose a small, domain-scoped property-graph schema with human-readable labels, normalised units and typed properties, and keep internal IDs and provenance as properties rather than as the names the LLM must reason over.
- Graph queries have a distinctive failure: relationship direction and path choice. Cheap deterministic validators fix much of it: check patterns against the schema, check relation domain and range against the ontology (OBQC-style), and run a grammar parse. The usual trade-off is more abstentions or empty results.
- Text-to-SPARQL is mature only where rich example-query metadata exists (bioinformatics SPARQL-LLM). Elsewhere, Cypher over a curated property graph or SQL over a modeled schema is the more LLM-friendly target.

### Gaps
- There is no large, independent, enterprise-realistic text-to-Cypher benchmark comparable to BEAVER. PIPE-Cypher (2026) proposes generating one per deployment ([Ranganath & Raghavendra 2026](https://arxiv.org/abs/2606.08481)).
- I found no head-to-head study of SQL vs Cypher vs SPARQL on the same data with modern (2026) models. The data.world study (GPT-4, 2023) is the main one.
- I did not retrieve the LC-QuAD 2.0 paper. It is ISWC 2019 and not on arXiv.

## Q3. Semantic layers and metric stores as the agent interface (dbt MetricFlow, Cube, AtScale, Snowflake, Apache Ossie/OSI): evidence on accuracy gains

### Takeaway
Every available study reports large gains when business semantics (metrics, join paths, synonyms, conventions) are supplied explicitly, either as a queryable semantic layer or as a context document: roughly +8 to +70 points. Most evidence is vendor-run on small question sets, 11 to 150 questions. The key qualitative result holds across vendors and one independent paired study. A semantic layer turns wrong-but-plausible answers into explicit declines, and its compiled SQL is deterministic once the metric and dimensions are chosen. Modeling the data well (a few clean derived tables or views) closes much of the gap even for plain text-to-SQL.

### Cited Findings
- dbt Labs 2026 benchmark (vendor; ACME Insurance from data.world; 15 tables in 3NF; 11 questions × 20 runs):
  - 2023 (GPT-4): text-to-SQL 32.7% vs semantic layer 60.5%.
  - 2026, unmodeled schema: text-to-SQL 64.5% vs semantic layer 72.7% (Sonnet 4.6 and GPT-5.3 Codex). The semantic layer scored 100% on in-scope questions and 0% on "too many hops" questions, which it declined.
  - After an LLM added 3 dbt models: Sonnet 4.6 text-to-SQL 90.0% vs semantic layer 98.2%; GPT-5.3 Codex 84.1% vs 100%.
  - Sweep across 16 model/reasoning permutations: semantic layer 87.2–100%, text-to-SQL 50–65%. Higher reasoning effort added latency (>20 s vs 8 s) without adding accuracy.
  - Failure modes: text-to-SQL "returns plausible but wrong answers". The semantic layer "fails by declining", and MetricFlow generates queries deterministically, so a correct metric and dimension choice guarantees correct SQL.
  - — [dbt Labs, Ganz & Perigaud, Apr 2026](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026)
- Rebuttal (vendor, Bodo, PyDough): the LLM writes PyDough, a DSL over a logical graph of collections and relationships that compiles to SQL, so the LLM never writes joins. With offline column profiling and descriptions, about 11 LLM calls per question, and three candidates plus a consensus or judge step, it scored 100% (220/220 runs) on dbt's 11 questions with no extra hand-made models. Outputs averaged 11 distinct query strings per question even though every answer was correct. The authors could not reproduce dbt's harness and used SQLite. — [Bodo.ai blog](https://www.bodo.ai/blog/how-pydough-reached-100-accuracy-on-dbts-semantic-layer-benchmark)
- Cube/Delphi (vendor, Dec 2023): the LLM issues Cube REST queries (metrics, dimensions, filters) instead of SQL. It scored 100% over five runs on a subset of the data.world test, against dbt's then-reported 83% on 8 questions. — [Cube blog](https://cube.dev/blog/semantic-layers-the-missing-piece-for-ai-enabled-analytics)
- Independent paired study (2026): 100 questions over Contoso Retail in ClickHouse, single-shot, testing Claude Opus 4.7, Claude Sonnet 4.6 and GPT-5.4.
  - Effect: adding a 4 KB hand-written markdown "semantic layer" document (measures, conventions, disambiguation rules) gives +17 to +23 pp, with 67.7–68.7% with the document vs 45.5–50.5% without.
  - Significance: models within each condition are statistically indistinguishable. The document explains "essentially all of the significant variance".
  - — [Rumiantsau & Fokeev 2026](https://arxiv.org/abs/2604.25149)
- GROUND (2026) constrains generation to governed metrics, dimensions, join paths, filters and row-level security. It validates SQL against schema, metric, join, grain, filter, security and cost rules, and retries or abstains on violation.
  - Hallucinations: it is the only system with no measured hallucinations across six categories on a 100-question synthetic benchmark.
  - Leakage: an exact-metrics-only condition still leaks data through RLS violations.
  - Limits: enforced guarantees hold with zero violations on every model tested, but "refusing undefined metrics remain[s] fallible".
  - — [Pillai 2026](https://arxiv.org/abs/2608.26157)
- GATE (2026): hand-specified semantic layers are incomplete in expert domains. GATE bootstraps groundings from execution feedback into reusable memory. — [Lee et al. 2026](https://arxiv.org/abs/2606.05634)
- Agentic schema refinement (NeurIPS TRL workshop 2024) treats the semantic layer as a set of small, interpretable database views, discovered by multi-agent LLM simulation. — [Rissaki et al. 2024](https://arxiv.org/abs/2412.07786)
- Snowflake Cortex Analyst (vendor, Aug 2024): on an internal 150-question BI set, the agentic system with a semantic model reaches "90%+" SQL accuracy, while single-prompt GPT-4o reaches 51%. The semantic model holds named filters with synonyms, measures with definitions, literal sample values, and search over high-cardinality columns. Ambiguity is handled by making an assumption and stating it. — [Snowflake engineering blog](https://snowflake.com/en/engineering-blog/cortex-analyst-text-to-sql-accuracy-bi)
- AtScale (vendor) published a TPC-DS NLQ benchmark with question-complexity and schema-complexity axes; questions needing 5 or more tables count as high complexity. — [AtScale leaderboard post, Nov 2024](https://atscale.com/?p=24977)
  - Search-indexed BigDataWire coverage reports 20% (schema plus keys only) vs 92.5% (semantic layer) on 40 questions with Gemini 1.5 Pro. I could not open the article (HTTP 403), so this is unverified. — [BigDataWire, Aug 2024](https://bigdatawire.com/2024/08/15/atscale-claims-text-to-sql-breakthrough-with-semantic-layer)
- dbt MetricFlow mechanics:
  - Semantic models declare entities (join keys), dimensions and metrics (simple, ratio, derived, cumulative, conversion).
  - MetricFlow builds a semantic graph and infers joins from primary/foreign entity types. This "avoids fan-out and chasm joins".
  - Definitions live in version-controlled YAML.
  - — [MetricFlow docs](https://docs.getdbt.com/docs/build/about-metricflow)
- Apache Ossie (incubating), formerly the Open Semantic Interchange (OSI), is a vendor-neutral YAML/JSON spec under Apache-2.0. It ships a JSON schema, an ontology, a Python SDK, a TPC-DS example and converters for dbt, GoodData, Polaris and Salesforce. A compliance "Relational Query Interface" exists, but no formal semantic query spec yet. — [Ossie GitHub](https://github.com/open-semantic-interchange/OSI)
  - The coalition grew from 17 founding partners to more than 50 organisations. The code repository opened in Nov 2025, and the project entered the Apache Incubator in 2026. — [IT Brief, 15 Jul 2026](https://itbrief.co.uk/story/apache-ossie-joins-incubator-to-standardise-metrics)

### Inferences
- The semantic layer is the strongest available lever for deterministic agent retrieval of aggregates. The LLM's job shrinks to choosing among enumerated metric, dimension and filter identifiers, which is a classification task, and a compiler produces the SQL. Same selection and same snapshot give the same SQL and the same result. Out-of-scope requests produce a refusal instead of a silently wrong number.
- Its limits are coverage and multi-hop or ad-hoc questions. dbt's 0% on "too many hops" shows that a semantic layer needs a fallback, such as guarded text-to-SQL, and a modeling loop that adds derived models when gaps appear.
- For a document-to-data-lake toolkit, emitting an Ossie/MetricFlow-compatible semantic model alongside the tables is low-cost and interoperable. Even without a query engine, the same content as a markdown context document yields a +17–23 pp gain.
- Nearly all large effect sizes are vendor-reported on 11–150 questions. The direction is consistent, but the magnitude is uncertain.

### Gaps
- There is no independent large-scale benchmark (hundreds of questions, multiple schemas) comparing semantic-layer querying vs text-to-SQL vs predefined tools on the same data.
- The AtScale numbers could not be verified from a primary page.
- I found no published evaluation of Ossie-based agent querying.

## Q4. Predefined parameterized query tools vs free-form generated queries; verification, execution-guided repair, abstention; result determinism

### Takeaway
For recurring, known question shapes, a small set of domain-aligned, parameterized query tools beats free-form SQL. They are more accurate (0.94 vs 0.67 in the one controlled study), cheaper, usable by 3B–8B models, and immune to prompt-to-SQL injection, though they cannot answer novel questions. For free-form queries, reliability comes from layered checks: grammar or constrained decoding, schema and ontology validation, execution feedback, consensus, and explicit abstention. Abstention remains weak in frontier models by default. LLM output is not deterministic even at temperature 0. Determinism must therefore be engineered at the query and data layer: persist the accepted query, give it a total ORDER BY, and pin the table snapshot.

### Cited Findings
**Predefined / parameterized tools**
- Domain-Oriented Tooling Pattern for MCP (2026): the model chooses among domain tools whose parameterized SQL encapsulates joins and business rules, instead of generating SQL.
  - Setup: Sakila, 17 tasks, four 3B–8B local models, temperature 0, 3 repetitions, 609 cells.
  - Pooled score: verticalised domain pack 0.939 vs raw SQL execution 0.666 vs thin generic tool pack 0.605.
  - Smallest model: 0.583 → 0.929, cutting cost per correct answer by about 10×. The authors call this "Model Demotion": intent classification needs a lower model tier than SQL synthesis.
  - — [Bogliolo 2026](https://arxiv.org/abs/2608.22063)
- FinAI Data Assistant (CIKM 2025 workshop) routes requests via function calling to "a small library of vetted, parameterized queries". It shows lower latency and cost and higher reliability than a text-to-SQL baseline (author-reported). — [Kim et al. 2025](https://arxiv.org/abs/2510.14162)
- Google MCP Toolbox for Databases (open source) defines custom tools in `tools.yaml`, each with a source, parameters and a parameterized statement. The example is an `ILIKE` search that "keeps user input out of the raw SQL". It also ships generic `execute_sql` and `list_tables` prebuilt tools, connection pooling, IAM auth and OpenTelemetry. — [googleapis/mcp-toolbox](https://github.com/googleapis/mcp-toolbox)
- Prompt-to-SQL injection (ICSE 2025): LangChain-based apps are "highly susceptible" to prompt-injection-driven SQL injection across 7 LLMs. The authors propose four defences. — [Pedro et al. 2023/2025](https://arxiv.org/abs/2308.01990)
- StructGPT (EMNLP 2023; foundational) gives the LLM specialised interface functions that read evidence from tables, KGs and DBs (iterative reading-then-reasoning) instead of having it write full queries. — [Jiang et al. 2023](https://arxiv.org/abs/2305.09645)
- QO-Bench (EMNLP Findings 2026) runs typed-tuple queries over 22,984 news articles. Answers are computed deterministically and matched exactly. Similarity RAG leads on filter/project, while information-extraction-to-SQL leads on intersection and counting. "Operator execution … is a core bottleneck." — [Zhang et al. 2026](https://arxiv.org/abs/2606.04646)
- FLINT retrieves structurally similar query templates from a compact expert-authored bank, a hybrid between templates and generation. — [FLINT 2026](https://arxiv.org/abs/2610.03524)

**Verification and execution-guided repair (free-form path)**
- Execution-guided decoding (2018; foundational) executes partial programs during decoding to discard faulty ones, reaching 83.8% on WikiSQL. — [Wang et al. 2018](https://arxiv.org/abs/1807.03100)
- PICARD (EMNLP 2021; foundational) uses an incremental parser to reject inadmissible tokens, so output is always syntactically valid SQL. — [Scholak et al. 2021](https://arxiv.org/abs/2109.05093)
- Self-Debugging (2023): the LLM explains its code and reads execution results. Spider improves 2–3% and the hardest level 9%. — [Chen et al. 2023](https://arxiv.org/abs/2304.05128)
- Pipeline verifiers include CHESS's LLM-generated unit tests ([CHESS](https://arxiv.org/abs/2405.16755)) and ReFoRCE's majority-vote consensus with deferral of low-confidence cases ([ReFoRCE](https://arxiv.org/abs/2502.00675)). For graphs there are OBQC ontology checks ([Allemang & Sequeda](https://arxiv.org/abs/2405.11706)), grammar and schema filters for Cypher ([Ozsoy 2026](https://arxiv.org/abs/2605.10318)) and selective SPARQL correction ([GGC](https://arxiv.org/abs/2607.28082)).
- SQL debugging is itself hard. On BIRD-CRITIC, o3-mini fixes 38.87% of real PostgreSQL issues. — [SWE-SQL](https://arxiv.org/abs/2506.18951)

**Abstention and ambiguity**
- TrustSQL scores models with penalties for wrong answers vs abstentions. "Achieving high scores under severe penalties requires significant effort." — [Lee et al. 2024](https://arxiv.org/abs/2403.15879)
- DTE (ACL Findings 2023) groups ambiguous and unanswerable questions into 6 categories and detects, localises and explains them. — [Wang et al. 2022](https://arxiv.org/abs/2212.08902)
- PRACTIQ covers 4 ambiguous and 4 unanswerable categories in conversational form. SOTA systems "struggle". — [Dong et al. 2024](https://arxiv.org/abs/2410.11076)
- Query Carefully (2025, OncoMX biomedical): unanswerable-question detection accuracy is 0.8 overall, near-perfect for non-SQL, missing-column and out-of-domain questions, but 0.5 for missing-value and 0.3 for column-ambiguity questions. — [Saxer et al. 2025](https://arxiv.org/abs/2512.21345)
- PremiseSQL (Oct 2026) has 1,800 flawed-premise queries. Frontier LLMs are "strongly premise-trusting by default". Critique prompting raises abstention but also false "invalid" judgments on valid questions. — [Lin et al. 2026](https://arxiv.org/abs/2610.22158)
- AmbiQT (EMNLP 2023): with overlapping schema names or multiple join paths, beam search gives only token-level diversity. LogicalBeam is up to 2.5× better at surfacing every valid interpretation. — [Bhaskar et al. 2023](https://arxiv.org/abs/2310.13659)
- Agents end clarification too early and make silent assumptions that happen to match. PlanPool, an explicit question pool, reduces silent failures on BIRD-Interact-derived sets. — [Li et al. 2026](https://arxiv.org/abs/2610.02739)

**Result determinism**
- LLM nondeterminism (2024): five LLMs configured "deterministically" showed accuracy variation up to 15% across 10 runs and a best-to-worst gap up to 70%. None gave identical outputs. — [Atil et al. 2024](https://arxiv.org/abs/2408.04667)
- At temperature 0, Qwen3-235B produced 80 unique completions in 1,000 runs. The root cause is the lack of batch invariance in kernels. Batch-invariant kernels make all 1,000 identical, but vLLM runtime rises from 26 s to 42–55 s. — [He / Thinking Machines, Sep 2025](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)
- SQL itself is order-nondeterministic: "using different LIMIT/OFFSET values … will give inconsistent results unless you enforce a predictable result ordering with ORDER BY". The ORDER BY must be unique, with a tiebreaker. — [PostgreSQL 18 docs §7.6](https://www.postgresql.org/docs/current/queries-limit.html). BIRD had to accept ties for `ORDER BY … LIMIT 1` gold queries ([BIRD](https://bird-bench.github.io/)).
- Snapshot pinning: Iceberg supports `VERSION AS OF <snapshot_id>` (or a tag or branch) and `TIMESTAMP AS OF`. Snapshot and tag queries use the schema of that snapshot. — [Apache Iceberg Spark queries](https://iceberg.apache.org/docs/latest/spark-queries/)
- MetricFlow-style compilation produces the same SQL for the same metric and dimension selection ([dbt 2026](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026)). Free-generation pipelines produced about 11 distinct query strings per question even when every answer was correct ([Bodo PyDough](https://www.bodo.ai/blog/how-pydough-reached-100-accuracy-on-dbts-semantic-layer-benchmark)).

### Inferences
- Recommended tiered interface for agents over the converted lake, in decreasing determinism:
  1. Key and entity lookups plus predefined parameterized tools for known question shapes. These are exact, injection-safe and small-model-friendly.
  2. A semantic-layer query (metric × dimensions × filters) compiled to SQL.
  3. Guarded free-form read-only SQL or Cypher. It needs schema-validated parsing and execution checks, consensus or unit tests, and abstention, and should be logged and promotable into tier 1 or 2 once validated.
- Determinism contract for results: store the canonical query text and parameters, the snapshot or version id, and a total ORDER BY (primary key as tiebreaker). Re-running then gives byte-identical results regardless of LLM variance. LLM variance affects only which query gets chosen, so cache question → accepted query.
- Provenance: predefined tools and semantic-layer queries can always project source-span columns (document id, page, char offsets). Free-form SQL often drops them, so the guard layer should require that answer rows carry provenance keys.
- Abstention is unsafe to delegate to the LLM alone. Structural checks (missing column, unknown metric, RLS) are reliable, while semantic ambiguity detection is weak (0.3–0.5). Prefer structural refusal, i.e. a metric or tool that doesn't exist, as the first line.

### Gaps
- Only one controlled study (Bogliolo 2026; small models; Sakila) directly compares parameterized domain tools with raw SQL. No study measures frontier models on the same comparison or the coverage loss on novel questions.
- I found no published guidance quantifying how many predefined tools an agent can select among accurately before tool-selection errors dominate.

## Q5. How schema design for LLM consumption (descriptive names, comments, denormalized views, example values, ontologies) affects accuracy

### Takeaway
Schema and metadata quality is a first-order accuracy factor, often larger than model choice. Natural identifiers correlate significantly with accuracy, and renaming obscure identifiers through views recovers it. Rich column descriptions, profiled value summaries, sample values and documented business rules each add several to 20+ points. A few well-modeled derived tables lifted text-to-SQL from 64.5% to 90% in one vendor benchmark. Denormalization's effect is mixed: fewer joins help weaker models, while frontier models are largely insensitive. Readable, typed and unit-normalized graph views also help graph query generation.

### Cited Findings
- SNAILS (SIGMOD 2025; CC-BY 4.0):
  - Setup: 9 real databases including SAP Business One (about 500 tables and more than 5,000 columns), 503 NL-SQL pairs and more than 17,000 identifiers, labelled Regular, Low or Least naturalness.
  - Correlations: Kendall τ between query identifier naturalness and EX ranges from 0.09 (Gemini 1.5) to 0.19 (CodeS, Phind-CodeLlama). The share of Least-natural identifiers correlates at τ = −0.15 to −0.22 (p<0.0001 for all models).
  - Schema linking: moving to Least naturalness drops QueryRecall about 20% for every LLM.
  - When renaming helps: renaming to natural names improves EX for databases whose native naturalness score is below 0.69.
  - Model sensitivity: newer and larger models are less sensitive. DIN-SQL and CodeS pipelines "do not overcome schema naturalness effects".
  - Recommendation: expose "natural views" of the native schema.
  - — [Luoma & Kumar 2025 (PDF)](https://adalabucsd.github.io/papers/2025_SNAILS_SIGMOD.pdf); [project blog](https://adalabucsd.github.io/research-blog/snails.html)
- EGRefine (2026) frames renaming as optimisation. It screens ambiguous columns, generates candidate names, verifies them by execution, and materialises them as non-destructive views, keeping query equivalence. Recovered accuracy transfers across model families: "refine-once, serve-many-models". — [Wang et al. 2026](https://arxiv.org/abs/2605.00628)
- Synthetic column descriptions (2024, BIRD): zero-shot EX for GPT-4o goes from 0.3013 to 0.3678 with Qwen2-generated descriptions, and Mistral-7B from 0.1473 to 0.1690. Verbose LLM descriptions beat human-curated "gold" descriptions, and descriptions for fully uninformative columns gave more than 20% gains. — [Wretblad et al. 2024](https://arxiv.org/abs/2408.04691)
- Automatic metadata extraction (AT&T, 2025; BIRD MiniDev; GPT-4o; no hints):
  - Accuracy by metadata: none 49.8%, BIRD-supplied metadata 59.6%, automatic profiling metadata 61.2%, fused 63.2%. With BIRD hints: 72.0–73.0%.
  - Query logs: mining them found 25% more join equality constraints than were documented.
  - The authors note that if exact hints exist, "one might as well develop a canned query system".
  - — [Shkapenyuk et al. 2025](https://arxiv.org/abs/2505.19988)
- Automatic DB description generation (XiYan, 2025) adds only +0.93% on BIRD, a small effect when names are already descriptive. — [Gao & Luo 2025](https://arxiv.org/abs/2502.20657)
- Schema-free text-to-SQL (Oct 2026) builds a KG from parsed query logs with entity-driven GraphRAG. On BEAVER it reaches 95.7% execution validity vs 60.8% for embedding-based retrieval, and experts preferred it 70% to 10%. — [Akgül et al. 2026](https://arxiv.org/abs/2610.33946)
- Data-model robustness (FootballDB, 2024): about 6K real World Cup 2022 user questions over three data models of the same data.
  - Fine-tuned systems: the flatter v3 performs best, with fewer joins per test query (1.45 vs 1.78 for v1 and 2.63 for v2) and no set operations. ValueNet improves about 5 points and T5-PicardKeys about 3 points.
  - LLMs: GPT-3.5 does best on v1 (41%) and differences are small.
  - The study covers a single database.
  - — [Fürst et al. 2024](https://arxiv.org/abs/2402.08349)
- dbt 2026: having an LLM add 3 dbt models moved Sonnet 4.6 text-to-SQL from 64.5% to 90.0% on the same questions (vendor). — [dbt Labs](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026)
- Ontology context: the data.world KG mapping lifted GPT-4 from 16% to 54%, and SQL scored 0% on questions spanning more than 5 tables. The authors attribute the gain to synonyms and business concepts that DDL cannot express. — [Sequeda et al. 2023](https://arxiv.org/abs/2311.07509)
- Semantics as context (markdown with measures, conventions and disambiguation rules) gave +17–23 pp across frontier models. — [Rumiantsau & Fokeev 2026](https://arxiv.org/abs/2604.25149)
- Robustness to schema perturbation: Dr.Spider's 17 perturbations (DB, question, SQL) cause a 14.0% overall drop for the most robust model and 50.7% on the hardest perturbation. — [Chang et al. ICLR 2023](https://arxiv.org/abs/2301.08881)
- Opaque integer keys and codes push general methods below 50% on financial schemas, and lookup and reference-table resolution is required. — [FLINT 2026](https://arxiv.org/abs/2610.03524)
- Graph schemas: property-graph views with readable names, disambiguated relation types and normalised datatypes and units make Cypher generation tractable. — [CypherBench](https://arxiv.org/abs/2412.18702)
- Example values and docs in long context help Gemini-1.5-pro without fine-tuning ([Chung et al. VLDB 2025](https://arxiv.org/abs/2501.12372)). Snowflake's semantic model adds sample values and synonyms ([Snowflake](https://snowflake.com/en/engineering-blog/cortex-analyst-text-to-sql-accuracy-bi)). XiYan's M-Schema is a semi-structured schema serialisation designed for LLM understanding ([XiYan](https://arxiv.org/abs/2411.08599)).

### Inferences
- Practical schema rules for the toolkit's generated databases, ordered by the strength of evidence:
  1. Use Regular-naturalness English names for tables and columns, with no cryptic abbreviations or the word "table". Where source names must be preserved, expose natural views.
  2. Add a column comment or description for every column: meaning, units, value format, null semantics. Verbose is fine.
  3. Store profiled metadata: distinct-value samples, ranges, formats, special codes.
  4. Declare primary and foreign keys and explicit relationship names. Avoid multiple ambiguous foreign keys to the same table, or give them role-named views.
  5. Provide a small set of pre-joined, analysis-ready views or derived tables for common question shapes, a few models rather than full denormalization.
  6. Publish metric and business-rule definitions (semantic layer or markdown).
  7. Never make the LLM resolve opaque integer codes. Provide lookup tables and resolution tools.
- Because document-derived schemas are generated by the toolkit, these properties can be enforced by construction. That is a structural advantage over messy legacy warehouses, where most of the reported failures come from.
- Denormalization is not a universal win. Fewer joins help weaker or fine-tuned models, and frontier LLMs are insensitive. Wide views should complement the normalized, provenance-preserving base tables, not replace them.

### Gaps
- No study isolates the effect of each metadata type (names vs descriptions vs sample values vs views) on 2026 frontier models across many schemas. Most evidence uses GPT-4o-era models on BIRD.
- I found no quantitative evaluation of the SNAILS "natural views" method itself, and no evidence on how column-level provenance columns (source span ids) affect LLM query accuracy, for example through schema clutter.
