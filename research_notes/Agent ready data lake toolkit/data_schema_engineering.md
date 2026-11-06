# Data Schema Engineering for Agent-Queryable Document Data (state as of Nov 2026)

Scope: the schema layer of a document-to-data-lake toolkit. Covers structured extraction, schema discovery, ontologies and standards, semantic layers, catalogs, schema evolution/versioning, and data quality. Research date: 2026-11-06. Many sources are vendor blogs or single-author preprints. Each is labelled where that matters.

## 1. Structured extraction from documents with LLMs (constrained decoding, libraries, accuracy evidence, grounding)

### Takeaway
Major APIs now ship schema-valid JSON as a stable feature through grammar-constrained decoding. Syntactic validity is therefore largely solved, but semantic accuracy is not. Supported JSON Schema subsets are narrow, and 2025 independent benchmarks still found gaps in constrained-decoding frameworks. The evidence on whether format constraints hurt reasoning is mixed and depends on the model. Grounding each value to a source span (LangExtract-style char intervals, ExtractBench word/page-level grounding F1) is becoming the main way to audit extractions. No independent, multi-vendor 2026 accuracy leaderboard exists. The largest 2026 benchmark (ExtractBench) appears to be LlamaIndex-built, and LlamaIndex's own product ranks first on it.

### Cited Findings
**Constrained decoding / native structured outputs**
- Anthropic's Structured Outputs feature (Claude API) uses constrained decoding: "Your JSON schema is compiled into a grammar that constrains Claude's output." Compiled grammars are cached for 24h. It guarantees valid JSON, correct field types and required fields, with no retries needed. Exceptions: refusals, `max_tokens` truncation, enum casing drift, and fixed property order (required fields first). Status is "stable" and it is available on the Claude API, Bedrock, Google Cloud and Microsoft Foundry. Parameter: `output_config.format` with `type: "json_schema"`. The `structured-outputs-2025-11-13` beta header/`output_format` is deprecated. — [Anthropic docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- Supported JSON Schema features in Anthropic's implementation exclude recursive schemas, numeric constraints (`minimum`/`maximum`), string length constraints, array constraints beyond `minItems` 0/1, external `$ref`, and `additionalProperties` other than `false`. Per-request limits: 20 strict tools, 24 optional params, 16 union-typed params, 180s compile timeout. SDK helpers move unsupported constraints into descriptions and validate locally. — [Anthropic docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- Secondary blogs disagree about whether Claude's structured outputs are true grammar-constrained decoding (one claims a 0.5–5% failure rate via tool use). Anthropic's current docs settle it in favor of constrained decoding, so treat the blog claims as stale. — [mer.vin blog](https://mer.vin/news/why-claude-still-wraps-json-in-markdown-fences/); [Anthropic docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- JSONSchemaBench (Geng et al., arXiv 2501.10868, Jan 2025; ICML 2025 ES-FoMo workshop): 10K real-world JSON schemas plus the official JSON Schema Test Suite. It evaluates Guidance, Outlines, llama.cpp, XGrammar, OpenAI and Gemini on efficiency, constraint coverage and output quality. It finds the benchmark is a "significant challenge for both LLMs and constrained decoding frameworks". Independent/academic. Code: guidance-ai/jsonschemabench. — [arXiv](https://arxiv.org/pdf/2501.10868); [ICML](https://icml.cc/virtual/2025/51849)
- "Let Me Speak Freely?" (Tam et al., Appier, EMNLP 2024 Industry): format restrictions caused a "significant decline in LLMs' reasoning abilities", and stricter formats degraded more. — [ACL Anthology](https://aclanthology.org/2024.emnlp-industry.91.pdf). Rebutted by .txt (Outlines vendor, biased), which argued the result came from using a second LLM as a parser and that structured generation does not hurt. — [.txt blog](https://blog.dottxt.ai/say-what-you-mean.html). An independent replication by Dylan Castillo found structured outputs as good or better for LLaMA3-8B but not for GPT-4o-mini. — [Castillo](https://dylancastillo.co/posts/say-what-you-mean-sometimes.html). (Older, 2024, and covers only simple reasoning+answer schemas.)

**Libraries**
- LangExtract (Google, Apache 2.0, "not an officially supported Google product", v1.6.0 cited 2026). It maps every extraction to its exact char location in the source. Ungroundable extractions get `char_interval = None` so they can be filtered. Schemas are driven by few-shot examples, with controlled generation best on Gemini, and `output_schema` is supported for Gemini/OpenAI. For long documents it uses chunking, parallel workers and multiple extraction passes (e.g., `extraction_passes=3`). It produces an interactive HTML review visualization. No benchmark numbers are published. — [GitHub](https://github.com/google/langextract)
- Thoughtworks Radar lists LangExtract. It notes the library suits long-form unstructured text better than short predictable inputs, and that Thoughtworks teams used it to populate a knowledge graph. — [Thoughtworks Radar](https://www.thoughtworks.com/en-us/radar/languages-and-frameworks/langextract)
- No public benchmark includes LangExtract or LlamaExtract (as of the comparing vendor's post). Span grounding "checks location, not correctness", so a cited value can still be wrong, especially on OCR input. (Nutrient, a competing vendor.) — [Nutrient blog](https://www.nutrient.io/blog/langextract-vs-llamaindex-extraction-comparison/)
- BAML (BoundaryML) uses compact TypeScript-like type definitions instead of JSON Schema plus "Schema-Aligned Parsing" (SAP), which tolerantly repairs LLM output in place of JSON.parse. Boundary claimed SOTA on BFCL "with every LLM" (vendor-reported, ~2024, an older BFCL version, assertions unmodified). A third-party write-up claims SAP is Rust-based, corrects errors in <10 ms, and cuts tokens ~4x (unverified). — [BoundaryML blog](https://boundaryml.com/blog/sota-function-calling); [Nanonets cookbook](https://nanonets.com/cookbooks/structured-llm-outputs/unconstrained-decoding/baml/)
- Instructor: Pydantic validation over function-calling/structured-output APIs with automatic retry-on-validation-error. Commonly recommended as the least-code, most provider-flexible option for extraction-only work. PydanticAI is positioned for agents with tools and dependency injection. Outlines is for guaranteed compliance with local models. (All secondary blog comparisons, no benchmark.) — [DEV Community](https://dev.to/nebulagg/top-5-structured-output-libraries-for-llms-in-2026-48g0); [glukhov.org BAML vs Instructor](https://www.glukhov.org/post/2025/12/baml-vs-instruct-for-structured-output-llm-in-python/)
- Instructor docs show Pydantic validators for pre-processing and validating LLM-extracted data. — [Instructor validation docs](https://git.kennethreitz.org/kennethreitz/instructor/src/commit/a10e8c81da0b1266e7875bcb3460814dafc3fc6f/docs/validation.md)
- OntoGPT/SPIRES (Monarch Initiative) takes a LinkML schema plus text and does zero-shot recursive extraction of nested structures, outputting JSON/YAML/RDF/OWL that conforms to the schema. It now uses LiteLLM (OpenAI, Anthropic, Ollama). schema-automator converts OWL to LinkML YAML. — [OntoGPT PyPI](https://pypi.org/project/ontogpt/0.3.2); [GitHub](https://github.com/balhoff/ontogpt)
- Unstract (Zipstack, open source): no-code LLM extraction. In Prompt Studio, schema fields are defined in natural language and outputs and costs are compared across multiple LLMs. The OSS edition lacks LLMChallenge (dual-LLM cross-check), SinglePass, Summarized Extraction and HITL review with source highlighting, which are Cloud/On-prem only. Its OCR engine LLMWhisperer is not open source. — [Unstract editions](https://unstract.com/unstract-editions/); [Prompt Studio](https://unstract.com/prompt-studio/)

**Accuracy evidence**
- ExtractBench (arXiv 2607.29677, Jul/Aug 2026; Zhang, Lyjak, Stewart, Li, Suo; dataset under `llamaindex`/`run-llama` namespaces, so likely LlamaIndex-authored, vendor bias). It covers 4,869 pages, 370 enterprise docs, 8 domains and 67 doc types, scored on value F1 (order-insensitive), record completeness, grounding (word- and page-level F1) and cost. It evaluates 14 methods. LlamaExtract Agentic Plus "ranks first on all three metrics" (~8.1¢/page). Commercial VLMs do well on short docs but "often truncate record lists" on long ones. Coding agents are accurate but much costlier. — [arXiv](https://arxiv.org/abs/2607.29677)
- AIMultiple invoice benchmark (updated Aug 2026, but tests run Dec 2024): Claude 3.5 Sonnet was most accurate across document qualities, scored binary per field. Other quoted figures (Gemini 2.5 Pro 96.5% clean / 92.7% scanned) come from an unclear source and are unverified. — [AIMultiple](https://aimultiple.com/invoice-ocr)
- Microsoft recommends "document accuracy" (all required fields correct) and critical-field accuracy, broken down by document type, as extraction metrics. — [C# Corner / Azure Content Understanding](https://www.c-sharpcorner.com/article/azure-content-understanding-measuring-agentic-document-extraction-accuracy-and/)

### Inferences
- The toolkit should assume native constrained decoding for syntax. Constraints the grammar can't express (ranges, lengths, cross-field rules) belong in a post-hoc validation layer such as Pydantic, Pandera or SHACL. Schema design must stay inside the narrow common subset: no recursion, `additionalProperties:false`, limited unions.
- Grounding is a schema concern, not just a UI one. Every extracted field should carry `(doc_id, page, char_start, char_end, extractor_version)`. That allows grounding F1 to be measured as ExtractBench does, and it allows a cheap hallucination filter (drop values with no span).
- Long-document recall (record-list truncation) is the dominant failure mode in 2026 evidence. Multi-pass/chunked extraction (LangExtract) or agentic extraction should be default for list-valued fields.

### Gaps
- No independent (non-vendor) multi-library accuracy benchmark compares Instructor, BAML, Outlines, LangExtract, DSPy and Unstract on the same document extraction task. All comparisons found are blogs.
- ExtractBench's per-model numeric scores were not retrievable from the abstract page.
- DSPy for extraction (signatures/optimizers) was not researched in depth. No 2026 evidence was gathered.
- I could not verify OpenAI's commonly cited "100% schema adherence" eval figure (Aug 2024 launch) in this session.
- Docling, Reducto and LlamaExtract schema features were not covered by retrieved sources.

## 2. Schema discovery/induction (auto-proposing tables, fields, entity types; HITL refinement; research systems)

### Takeaway
Corpus-level schema induction is an active 2025–2026 research area, but almost all of it is preprints with self-reported results. The document-analytics systems (ZenDB, DocETL, LOTUS, Palimpzest/Abacus) mostly assume the user supplies the schema or query and optimize how to fill it. DocETL/DocWrangler is the clearest evidence on human-in-the-loop refinement. Its user study found users steer by turning open-ended operations into classifiers, and it flagged provenance tooling as a gap.

### Cited Findings
- **ZenDB** (Lin, Hulsebos, Ma, Shankar, Zeighami, Parameswaran, Wu; arXiv 2405.04674, May 2024, older): SQL over templatized documents. It builds "Semantic Hierarchical Trees" from visual header cues, attaches summaries to tree nodes, and lets users impose a schema queried with SQL. Authors report it beats LLM and RAG baselines (secondary summary: up to 61% higher accuracy than RAG, ~30% cost of LLM-only; unverified). — [arXiv](https://arxiv.org/abs/2405.04674); [Berkeley TR](https://people.eecs.berkeley.edu/~adityagp/papers/zendb-tr.pdf)
- **DocETL** (Shankar, Chambers, Shah, Parameswaran, Wu; arXiv 2410.12189, v3 Apr 2025): a declarative YAML pipeline of LLM operators (map, reduce, resolve, gather, split). An agent applies rewrite directives (decomposition of data/task) and synthesizes validation prompts to evaluate candidate plans. It reports outputs 25–80% more accurate than well-engineered baselines on 4 tasks (author-reported, small task count). — [arXiv](https://arxiv.org/abs/2410.12189)
- DocETL handles documents exceeding context windows. ZenDB targets templatized docs. Palimpzest focuses on map-like ops with partial aggregation. Semantic join exists in LOTUS and DocETL but not Palimpzest, and none support semantic difference/intersection (per the SABER paper). — [DocETL paper](https://arxiv.org/pdf/2410.12189); [SABER arXiv 2509.00277](https://arxiv.org/pdf/2509.00277)
- **DocWrangler** (Shankar et al., UC Berkeley/Columbia, arXiv 2504.14764, Apr 2025): a mixed-initiative IDE for DocETL with in-situ user notes, LLM-assisted prompt refinement (sends current prompt plus output schema plus sampled docs plus notes), and operation decomposition. It runs a background LLM-as-judge on 5 sampled docs with gpt-4o-mini. Evaluation: a 10-participant think-aloud study plus 1,500+ public deployment sessions. Users converted open-ended ops into classifiers for easier validation. The authors identify a need for better provenance tracking. — [arXiv](https://arxiv.org/abs/2504.14764)
- **LOTUS / Semantic Operators** (Patel et al., PVLDB vol. 18, VLDB 2025): a pandas-like semantic filter/join/sort/aggregate with statistical accuracy guarantees. An aggregator claims "up to 1,000×" cost reduction (unverified). — [VLDB](https://vldb.org/pvldb/volumes/18/paper/Semantic%20Operators%20and%20Their%20Optimization%3A%20%20Towards%20AI-Based%20Data%20Analytics%20with%20Accuracy%20Guarantees)
- **Palimpzest / Abacus** (arXiv 2505.14661): a cost-based optimizer using a modified infinite-armed bandit to find the Pareto frontier of physical operators. Authors report 18.7–39.2% better quality and up to 23.6x lower cost and 4.2x lower latency vs the next-best system on BioDEX, CUAD and MMQA (self-reported). A later MOAR paper reports 27% higher accuracy than Abacus across 6 workloads. Competitor Sema reports a 2–4x speedup over LOTUS and 2–10x over Palimpzest (competitor-reported). — [Abacus arXiv](https://arxiv.org/html/2505.14661v2)
- **SchemaLoop / AnnoIndex** ("Structure then Query", Teng Lin, arXiv 2608.13384, Aug/Oct 2026): automatically induces hierarchical schemas from raw corpus (dataset → table/entity-category → row/field levels). A lightweight LM extracts the values into an index. The query engine filters on the index first, then runs LLM extraction lazily in cost order and merges new attributes back into the index. Reports average F1 0.87 on 3 unnamed datasets. No HITL. Baselines are not named in the abstract. — [arXiv](https://arxiv.org/abs/2608.13384)
- **Generative Ontology Induction** (Sergienko, single author, arXiv 2607.16201, Jul 2026): induces entities, dimensions, properties, relationships and constraints from a corpus and exports a typed graph. — [arXiv](https://arxiv.org/abs/2607.16201)
- **LLMs4SchemaDiscovery** (arXiv 2504.00752, Apr 2025): an HITL scientific schema-mining workflow. The LLM drafts a schema from a spec document, refines it on a few expert-selected papers, then runs on the uncurated corpus. — [arXiv](https://arxiv.org/pdf/2504.00752)
- **Map&Make** (arXiv 2505.23174): schema-guided text-to-table that dynamically infers table structure. **Intent-Aware Schema Generation** (arXiv 2507.19521): iteratively grows literature-review table schemas batch by batch. **AutoSchemaKG** (arXiv 2505.23628): unsupervised schema induction for KGs at scale (per survey). — [Map&Make](https://arxiv.org/pdf/2505.23174); [Intent-aware](https://arxiv.org/pdf/2507.19521); [KG construction survey](https://arxiv.org/html/2510.20345v1)
- LLM-based schema *mapping* at scale (matching induced fields to existing target schemas) is studied in arXiv 2505.24716. — [arXiv](https://arxiv.org/pdf/2505.24716)

### Inferences
- A practical design pattern emerges: (1) sample documents → LLM proposes a candidate schema (entity types, tables, fields with descriptions), (2) a human edits or approves it with in-situ notes, as in DocWrangler and LLMs4SchemaDiscovery, (3) extract eagerly for core fields and lazily/on-demand for long-tail attributes, merging them back (AnnoIndex), (4) optimize the operator plan cost/quality (Abacus/DocETL).
- Induced schemas should be first-class versioned artifacts, since they will churn. This connects directly to Section 6.
- The research systems don't share a schema format. A toolkit could export induced schemas to LinkML or JSON Schema plus OSI/Ossie semantic models to bridge them.

### Gaps
- No independent head-to-head of schema-induction quality (precision/recall of induced fields vs gold schemas) across systems was found.
- SchemaLoop's datasets and baselines, and Generative Ontology Induction's results, were not retrievable from abstracts.
- ZenDB's final venue (VLDB?) was not confirmed.

## 3. Ontologies and standards (schema.org, OWL/SHACL, LinkML, property-graph schemas; when formal ontologies are worth it)

### Takeaway
LinkML is the most pragmatic "one schema, many targets" layer for an extraction toolkit. It already drives LLM extraction (OntoGPT/SPIRES) and exports to OWL/RDF. Property-graph schemas have a formal basis in PG-Schema (SIGMOD 2023), which informed ISO GQL (ISO/IEC 39075). The best quantitative evidence that ontologies help LLM querying comes from the data.world line of work (16%→54%→~72% incl. abstentions on one insurance benchmark, GPT-4, small and partly vendor-authored). That suggests ontologies pay off when they are used to *validate and repair* agent queries, not just as documentation.

### Cited Findings
- SPIRES/OntoGPT takes a LinkML schema plus text and produces JSON/YAML/RDF/OWL conforming to the schema. LinkML's linkml-owl mappings allow OWL export viewable in Protégé. schema-automator converts OWL ontologies into LinkML YAML. — [OntoGPT PyPI](https://pypi.org/project/ontogpt/0.3.2); [GitHub](https://github.com/balhoff/ontogpt)
- PG-Schema (SIGMOD/PACMMOD vol. 1(2), June 2023) is a formal property-graph schema language with PG-Types (flexible, multi-inheritance) and PG-Keys constraints. It was proposed to inform ISO GQL (39075), with ISO SC32 member authors. The Semantic Web and DB communities developed SHACL, ShEx and PG-Schema independently. — [arXiv 2211.10962](https://arxiv.org/abs/2211.10962); [Edinburgh Research](https://www.research.ed.ac.uk/en/publications/pg-schemas-schemas-for-property-graphs/)
- An AI-generated summary claims PG-Schema is more tractable than SHACL because it avoids recursive types. This is unverified. — [alphaxiv overview](https://www.alphaxiv.org/overview/2211.10962v4)
- Sequeda, Allemang, Jacob (data.world, arXiv 2311.07509, 2023): on an insurance enterprise SQL benchmark, GPT-4 zero-shot reached ~16.7% directly on SQL vs ~54.2% over a knowledge-graph (ontology-mapped) representation. — [alphaxiv](https://www.alphaxiv.org/abs/2311.07509)
- Allemang & Sequeda (arXiv 2405.11706, May 2024): Ontology-Based Query Check (OBQC) validates LLM-generated SPARQL against ontology semantics, then LLM Repair fixes it. Overall accuracy reached 72.55%, but this includes ~8% "I don't know" answers. A commentator reads the result as ~64–65% correct answers. Single benchmark, single model (GPT-4). — [arXiv](https://arxiv.org/abs/2405.11706); [Ontolog forum](https://groups.google.com/g/ontolog-forum/c/CjzjE1piIMQ)
- Apache Ossie (ex-OSI) explicitly expanded its scope to "semantic layers and ontologies" and has an Ontology working group. That points toward convergence of BI semantic models and ontologies. — [Snowflake blog, Jul 2026](https://www.snowflake.com/en/blog/apache-ossie-open-semantic-interchange-incubator/)
- Thoughtworks teams used LangExtract to populate a knowledge graph, which shows the extraction-to-graph route is in practice. — [Thoughtworks Radar](https://www.thoughtworks.com/en-us/radar/languages-and-frameworks/langextract)

### Inferences
- Recommended layering for the toolkit: author the canonical schema in LinkML (classes, slots, enums, descriptions). Generate JSON Schema/Pydantic for constrained extraction, SHACL for RDF validation, a property-graph schema (PG-Schema/GQL-style or Neo4j constraints) for graph storage, and SQL DDL for tables. schema.org types can serve as `class_uri`/`slot_uri` mappings for interoperability, not as the primary design.
- Formal OWL reasoning is likely worth it only where (a) cross-source entity identity and class hierarchies matter (biomedical, regulatory, finance), or (b) the ontology is used as a runtime checker for agent queries (OBQC). For most document lakes, a lightweight typed schema plus a semantic layer delivers most of the measured gains.

### Gaps
- No primary source was retrieved in this session on SHACL 1.2 / W3C Data Shapes WG status, the GQL publication date, or LinkML's current release and SHACL/PG generators. These need verification.
- No 2025–2026 independent replication of the ontology-improves-accuracy results was found.
- No quantitative evidence was found on schema.org's utility for LLM extraction specifically.

## 4. Semantic layers and metric definitions (MetricFlow, Cube, OSI/Ossie, Malloy, LookML; evidence on accuracy)

### Takeaway
OSI published v0.1-ish spec in Jan 2026 and was renamed and accepted into the Apache Incubator as **Apache Ossie** (announced Jul 8, 2026). Its maturity is still "experiment, don't migrate". dbt relicensed MetricFlow to Apache 2.0 (v0.209.0, Oct 14, 2025). Evidence that semantic modeling improves text-to-SQL is consistent in direction: +17 to +31 pp across benchmarks, and the semantic layer's effect is bigger than switching models. However, every benchmark found is vendor-run, and sample sizes are small (11 to 410 questions).

### Cited Findings
**Standards / governance**
- OSI's first spec was released Jan 2026 under Apache 2.0 as YAML/JSON covering datasets, metrics, dimensions, relationships and contexts. Sources disagree on whether it is "v0.1" or "v1.0". One commentator says the metrics language is still being formalized and production use is not advised. — [Apache Ossie site](https://ossie.apache.org/updates/); [Snowflake "Specs Finalized"](https://www.snowflake.com/en/blog/open-semantic-interchanges-specs-finalized/); [DEV Community (Alex Merced, Dremio)](https://dev.to/alexmercedcoder/meet-apache-ossie-the-open-semantic-interchange-finds-its-home-at-the-asf-2mio)
- Snowflake post (Jul 8, 2026): OSI was accepted into the Apache Incubator as "Apache Ossie (Incubating)". The spec format is unchanged. ASF governance means public mailing lists, discuss-and-vote on spec changes, and earned committership. Three working groups exist: Metric Language, Catalog and Ontology. Contributors come from Snowflake, Salesforce, Databricks, dbt Labs, RelationalAI, GoodData and Honeydew, and the coalition grew from 17 launch partners to 50+ orgs. Delivered converters: Ossie↔dbt MetricFlow, Apache Polaris catalog metadata, Snowflake Semantic Model. Polaris catalog-discovery integration is planned. (Snowflake is a founding vendor, so the post is promotional.) — [Snowflake blog](https://www.snowflake.com/en/blog/apache-ossie-open-semantic-interchange-incubator/)
- Claims of "native support in 50+ platforms in Q2–Q4 2026" are roadmap marketing. No adoption data was found. — [unwinddata](https://unwinddata.com/osi-open-semantic-interchange-guide); [SBI](https://www.sbi-group.com/blog/open-semantic-interchange-osi)
- dbt MetricFlow moved to Apache 2.0 with v0.209.0 (Oct 14, 2025). The last BSL release was 0.208.1. The relicense covers metric definition, multi-dialect SQL compilation and semantic metadata. dbt hopes to donate it to a foundation but still hosts it. The hosted dbt Semantic Layer APIs remain proprietary (per Atlan, secondary). — [dbt blog](https://www.getdbt.com/blog/open-source-metricflow-governed-metrics); [PR Newswire](https://tools.prnewswire.com/en-us/live/20813/release/20251014EN96968); [Atlan](https://atlan.com/know/ai-agent/semantic-layer/metricflow-apache-2-license-dbt-semantic-layer/)

**Accuracy evidence (all vendor or vendor-adjacent)**
- **dbt Labs 2026** (Apr 7, 2026; ACME Insurance benchmark from Sequeda/data.world, 15 tables in 3NF; **11 questions × 20 runs**). Original schema: text-to-SQL 64.5% vs SL 72.7% (Sonnet 4.6 and GPT-5.3 Codex). After an LLM generated 3 extra dbt models: Sonnet 4.6 text-to-SQL 90.0% vs SL 98.2%, and GPT-5.3 Codex 84.1% vs 100%. On in-scope questions the SL scored 100% for both models vs text-to-SQL at 62.5%/51.2%. On "too many hops" questions the SL scored **0%**, while text-to-SQL scored 70–100%. The SL errors out rather than returning wrong data, while text-to-SQL fails silently. Higher reasoning effort mostly added latency. Vendor-run, tiny n, and full schema in prompt. — [dbt docs blog](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026)
- **Cube benchmark / arXiv 2604.25149** (Rumiantsau & Fokeev, Apr 28, 2026; the same design as the cubedevinc repo, so likely Cube-affiliated). **100 questions** (5 tiers × 20) on Contoso retail in ClickHouse, with Claude Opus 4.7, Sonnet 4.6 and GPT-5.4. Raw DDL scored 45.5–50.5%. Adding a ~4 KB hand-written semantic-layer markdown raised it to 67.7–68.7% (+17 to +23 pp). Paired McNemar p<0.01 (repo says p<0.002 per model). Models within each condition are statistically indistinguishable. Caveats: the judge is Claude Sonnet 4.6, which is also a model under test. The repo's size claim conflicts (4 KB vs ~9 KB file). It has one commit. The semantic layer was untuned, and the authors call 68% a floor. — [arXiv](https://arxiv.org/abs/2604.25149); [GitHub](https://github.com/cubedevinc/semantic-layer-benchmark)
- **AtScale** (BIRD-Interact based; **410 business questions, 7 LLMs**): 21.5–36.1% without a semantic layer vs 44.6–62.2% with one, a +20 to +31 pp gain for every model, larger than switching models. Vendor (AtScale sells a semantic layer). — [AtScale blog](https://www.atscale.com/blog/semantic-layer-text-to-sql-accuracy/)
- **data.world 2023** (see Section 3): 16.7% → 54.2% for SQL vs KG, GPT-4, a small insurance benchmark. The original 2023 dbt run on it gave 32.7% text-to-SQL vs 60.5% SL. — [alphaxiv](https://www.alphaxiv.org/abs/2311.07509); [dbt docs blog](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026)
- Other 2026 academic work: "Bootstrapping Semantic Layer from Execution for Text-to-SQL" (arXiv 2606.05634) and "Bounded Semantic Planning and Deterministic Compilation for Reliable Enterprise Text-to-SQL" (arXiv 2608.16663). Results were not retrieved. — [arXiv 2606.05634](https://arxiv.org/pdf/2606.05634); [arXiv 2608.16663](https://arxiv.org/pdf/2608.16663)
- A critic notes the earlier dbt study had only 11 questions, was vendor-run, and that the SL scored zero on questions its model couldn't express. — [Galaxy](https://www.getgalaxy.io/articles/rag-vs-knowledge-graph-vs-semantic-layer-enterprise-ai)

### Inferences
- Even a short natural-language semantic document (measures, conventions, disambiguation rules) yields roughly a +20 pp gain in the Cube study. That means a toolkit can get much of the benefit by auto-generating a "semantic README" per dataset alongside a formal model (MetricFlow/Ossie YAML).
- The coverage/correctness trade-off is structural: a compiled semantic layer refuses out-of-scope questions, while free SQL answers silently wrong. A hybrid design fits: route to the semantic layer first, fall back to text-to-SQL with explicit low-confidence flagging. This matches the dbt finding.
- Ossie is the natural export target for interoperability, but it is pre-1.0 and incubating. Keep the internal model decoupled and ship converters.

### Gaps
- No independent (non-vendor, peer-reviewed) benchmark of semantic layers vs text-to-SQL with >500 questions was found.
- Cube's own semantic model format, Malloy (Meta/Malloy project status), and LookML (Looker's open-sourcing or Ossie support) were not covered by retrieved sources. Their current 2026 status is unverified.
- Exact current Ossie spec version, repo URL and incubation acceptance date were not stated in the sources.

## 5. Data catalogs and metadata (Unity Catalog OSS, Polaris, DataHub, OpenMetadata, Gravitino; exposure to agents via MCP)

### Takeaway
The market has split into *technical catalogs* (Polaris, Unity Catalog OSS, Gravitino: Iceberg REST, credentials, access control) and *metadata/discovery platforms* (DataHub, OpenMetadata: search, lineage, glossary). In 2026 the latter group ships first-party MCP servers. Polaris graduated to an Apache TLP (Feb 2026). OpenMetadata joined the Linux Foundation (Mar 2026). An MCP server gives discovery, not governance: credential vending and grants still live in the technical catalog.

### Cited Findings
- Per a Sep 2026 comparison by Alex Merced (Dremio employee, Dremio's catalog is Polaris-based; disclosed bias):
  - DataHub (ex-Acryl, rebranded to DataHub) shipped an Iceberg REST catalog in 2025, with MCP plus GraphQL agent APIs.
  - OpenMetadata joined the Linux Foundation in Mar 2026 and released standards spec v1.13 in Apr 2026. Its agent API is MCP plus SDK, with an "early and complete" MCP implementation. It is metadata-only, not a technical catalog.
  - Unity Catalog OSS is under LF AI & Data with an Iceberg REST endpoint. MCP is available in the hosted Databricks version, and the OSS agent API is REST.
  - Apache Polaris graduated to TLP in Feb 2026 with policy frameworks, catalog federation and RBAC. It is Iceberg-only, has no discovery/glossary, and no MCP is listed.
  - Apache Gravitino federates multiple catalogs, supports Iceberg REST, and covers unstructured data and AI assets.
  - [Merced blog, Sep 2026](https://alexmerced.blog/blog/2026-09-02-metadata-platforms-in-2026.html)
- Gravitino 1.1.0 (Dec 2025) was reframed as an "AI-native metadata platform" with a Model Catalog plus an MCP server (secondary source). Databricks managed MCP servers expose Unity Catalog tables, functions and Vector Search to agents. Sources conflict on whether Unity OSS governance lags the managed version. — [Atlan OSS catalog list](https://atlan.com/open-source-data-catalog-tools/); [llms3 catalog guide](https://llms3.com/guides/choosing-a-lakehouse-catalog-control-plane/); [DEV: State of Iceberg Catalogs June 2026](https://dev.to/alexmercedcoder/the-state-of-apache-iceberg-catalogs-in-june-2026-265e)
- "A metadata platform's MCP server only finds tables. The technical catalog still has to grant read access", and an MCP server returning every table to every agent is "a discovery tool, not a governance tool". Agent identity is enforced via Polaris principals/roles, Unity grants, or Lake Formation. — [llms3 guide](https://llms3.com/guides/choosing-a-lakehouse-catalog-control-plane/); [Catalog wars blog](https://www.nidhivichare.com/blog/catalog-wars-part-2)
- DataHub's official `mcp-server-datahub` (PyPI) has these tools: `search` (structured /q syntax, filters, sort by usage), opt-in semantic search (`SEMANTIC_SEARCH_ENABLED=false` by default), `get_lineage`, `get_lineage_paths_between` (column-level paths), `list_schema_fields` and `get_dataset_queries`. Mutation tools (tags, owners) are off unless `TOOLS_IS_MUTATION_ENABLED=true`. DataHub also ships an "Agent Context Kit". — [PyPI mcp-server-datahub](https://pypi.org/project/mcp-server-datahub/); [Goose docs](https://goose-docs.ai/docs/mcp/datahub-mcp)
- OpenMetadata's official MCP server covers metadata search (`search_metadata`), glossary management and lineage. Server v1.1.0 (docs v2.1.x) uses Streamable HTTP with OAuth 2.0 or JWT/PAT and exposes 24 tools. Older 0.11.2 used SSE. — [OpenMetadata docs](https://docs.open-metadata.org/v2.0.x/how-to-guides/mcp/connect.md)
- Apache Ossie ships a Polaris catalog metadata converter and plans Polaris integration for semantic-model discovery. That would link semantic layer and catalog. — [Snowflake blog](https://www.snowflake.com/en/blog/apache-ossie-open-semantic-interchange-incubator/)

### Inferences
- For the toolkit, the agent-facing metadata surface should expose, via MCP: dataset/table search (keyword plus semantic), schema fields with descriptions, lineage back to source documents and extractor versions, glossary/semantic-model lookups, and sample queries. DataHub and OpenMetadata tool sets are a good template. Read-only by default with mutation gated, as DataHub does it.
- Register extracted tables in an Iceberg REST catalog (Polaris/Unity OSS/Gravitino) for engine access and credentialing, and push descriptive metadata to DataHub/OpenMetadata. Neither alone covers both roles.
- Document-derived lineage (table row → document span → extractor/prompt version) is not a native concept in these catalogs. It would need custom aspects or entities.

### Gaps
- No first-party MCP server for Unity Catalog OSS or Apache Polaris was confirmed. The status of a Gravitino MCP server was confirmed only by secondary sources.
- No evaluation was found of how catalog MCP servers affect agent task accuracy.
- Current version numbers for DataHub, Unity Catalog OSS and Gravitino in late 2026 were not retrieved.

## 6. Schema evolution and versioning of extracted data (when model, prompt or schema changes)

### Takeaway
This is a genuine gap. No standard, library or catalog feature was found that treats "extraction run = (schema version, prompt version, model version, source doc hash)" as a first-class versioned entity with diffing and selective re-extraction. Existing practice consists of scattered blog advice and individual papers' conventions: append-only rows keyed by model version, PROV-O lineage, and lineage tables. One paper's data shows why it matters: 26.5% of re-extracted values changed across model versions.

### Cited Findings
- Registry-bound trait-extraction pipeline (arXiv 2606.00994, 2026): rows are keyed on (entity, field, model_version), so re-running with a new model appends rather than overwrites. Of 2,064 multi-version pairs, 1,518 (73.5%) were identical and 546 (26.5%) diverged. — [arXiv](https://arxiv.org/pdf/2606.00994)
- Practitioner guidance: version chunking logic, prompt templates, few-shot retrieval index and model weights, and log raw pre-parse output, so that records before and after any change are distinguishable. (Substack, finance AI; not peer-reviewed.) — [Mycroft Substack](https://mycroftproject.substack.com/p/data-lineage-provenance-financial-ai)
- Log extraction method and schema version, so that a changed value can be attributed to a source change vs an extraction change (vendor blog). — [Olostep](https://www.olostep.com/blog/data-provenance-for-ai-agents)
- An open-source data-extraction contract (AI4RA-UDM issue) proposes a dedicated extraction-lineage table (extractor name/version, upstream extractor, time) and `source_provenance` in contract v1.1.0. — [GitHub issue](https://github.com/ui-insight/AI4RA-UDM/issues/24)
- IDEA2 (arXiv 2604.01344) links each LLM output to its generation configuration (checkpoint, seed, temperature) using PROV-O for exact replay. — [arXiv](https://arxiv.org/pdf/2604.01344)
- DocWrangler's user study explicitly identified "the need for better provenance tracking" in semantic data processing tooling. — [arXiv 2504.14764](https://arxiv.org/abs/2504.14764)
- AnnoIndex merges lazily extracted new attributes back into the index, an implicit additive schema evolution with no versioning semantics described. — [arXiv 2608.13384](https://arxiv.org/abs/2608.13384)

### Inferences
- The toolkit can differentiate here with an explicit design:
  - (a) Content-addressed `extraction_spec` = hash(schema version, prompt, few-shot examples, model id plus params, parser version).
  - (b) Each extracted value carries `spec_id` plus a source span.
  - (c) Table-format schema evolution (e.g., Iceberg add/rename columns, snapshots) handles physical changes, while the spec registry handles semantic changes.
  - (d) A schema change triggers a dependency analysis: which fields' specs changed, and which documents need re-extraction. Unchanged fields are reused.
  - (e) Shadow re-extraction on a sample with a diff report (agreement rate, like the 73.5%/26.5% split) before promotion.
  - (f) Agents query a "current" view while lineage still records which spec produced each value.
- Semantic versioning of schemas (breaking = removed/retyped field; additive = new optional field) can map onto data-contract tooling.

### Gaps
- I did not find any open-source tool purpose-built for versioned LLM extraction (diff/re-extract/promote). This claim is based on absence in searches, so a dedicated search of GitHub (e.g., data-contract CLIs, LakeFS/Nessie branching applied to extraction) is warranted.
- Iceberg/Delta/Lance schema-evolution specifics were not retrieved in this session.
- There is no empirical study of extraction drift across prompt changes (only across model versions in one paper).

## 7. Data quality/validation of extracted data (Great Expectations, Pandera, LLM-as-judge)

### Takeaway
No authoritative benchmark compares validation approaches for LLM-extracted data. Sources converge on a layered approach: (1) type/shape validation (Pydantic at extraction time; Pandera/Great Expectations at the table level), (2) cheap grounding checks (does the value appear at the cited span?), (3) LLM-as-judge or dual-LLM cross-checks only for failing or high-stakes fields, at a 3–5x cost multiplier. Claimed judge catch rates are unsourced.

### Cited Findings
- Pandera is a Python library for validating dataframes across pandas, Dask and PySpark, and Thoughtworks Radar lists it. Great Expectations is a widely adopted validation framework. — [Thoughtworks Radar: Pandera](https://www.thoughtworks.com/es-cl/radar/languages-and-frameworks/pandera); [endjin comparison](https://endjin.com/blog/a-look-into-pandera-and-great-expectations-for-data-validation)
- Research uses LLMs to translate natural-language data-quality requirements into Great Expectations suites. A fine-tuned LLM significantly outperformed generic models (single paper). — [Najah Univ. publication](https://staff.najah.edu/en/publications/18414/)
- Grounding heuristic: if the extracted value does not appear anywhere in the input document, it is likely hallucinated. This is cheap, but it misses paraphrased or derived values (blog). — [CallSphere blog](https://www.callsphere.ai/blog/validating-llm-outputs-custom-validators-business-rules-data-quality)
- LLM-as-judge for extraction is recommended because the extraction model is "incentivized to fill all fields". The cost is 3–5x. The guide's claim that judges catch "~85–92% of errors" is unsourced. — [theneuralbase guide](https://theneuralbase.com/structured-outputs/learn/intermediate/llm-as-judge-for-extraction-quality/)
- Unstract's "LLMChallenge" (a second LLM cross-checks extraction) and HITL review with source highlighting are commercial-only features. This is a sign that dual-model verification is a productized pattern. — [Unstract editions](https://unstract.com/unstract-editions/)
- DocWrangler runs an LLM-as-judge in the background on 5 sampled documents per operation with gpt-4o-mini. — [arXiv 2504.14764](https://arxiv.org/abs/2504.14764)
- ExtractBench measures record completeness and grounding F1 in addition to value F1. These are useful as production QA metrics. — [arXiv 2607.29677](https://arxiv.org/abs/2607.29677)
- LangExtract marks ungroundable extractions (`char_interval=None`) for filtering. — [GitHub](https://github.com/google/langextract)

### Inferences
- Toolkit QA pipeline:
  1. Constrained decoding plus Pydantic validators.
  2. Span-grounding check, with ungrounded values rejected or flagged.
  3. Table-level Pandera/GX suites (null rates, ranges, uniqueness, referential integrity to entity tables), possibly auto-generated from the LinkML schema.
  4. Sampled LLM-judge plus a human review queue for low-confidence values.
  5. Track metrics per extraction_spec: completeness, grounding rate, judge agreement, and cross-version agreement.
- Expose quality metrics in the catalog (DataHub/OpenMetadata support data-quality assertions/tests). That lets agents see confidence before querying.

### Gaps
- No peer-reviewed study was found that quantifies LLM-as-judge precision/recall for field-level extraction errors.
- I did not verify whether Great Expectations or Pandera added LLM- or extraction-specific features in 2025–2026.
- Calibration of per-field confidence scores from LLM extractors (e.g., logprob-based) was not researched.
