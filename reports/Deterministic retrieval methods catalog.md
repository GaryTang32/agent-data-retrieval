# Deterministic Retrieval Methods Catalog

This catalog lists the methods, systems, models, frameworks and products found in the 13 research-note files on converting unstructured data (documents, tables, forms, spreadsheets, web pages, emails, scientific literature, audio) into a database that agents can query deterministically, meaning exact queries over typed, versioned records that trace back to source spans. For each entry it gives the developer and the type of organisation behind it, the first release date, the high-level flow, the main tools or models, and one headline result labelled by who measured it. Entries are grouped into 12 categories that follow the pipeline from parsing to extraction, schema work, storage as tables or graphs, querying, quality control and production practice. The research notes are the source for all descriptions; developers were checked against author affiliations on the first page of each paper, and arXiv dates were looked up through the arXiv API. Notes snapshot: November 2026.

## How to read this

- **Main tables vs. "Also covered briefly".** Each category has a table of the entries the notes treat in most depth, followed by a one-line list of further entries the notes describe in less detail (name, developer, first release). Benchmarks and datasets are not catalogued as methods unless they ship a method.
- **Developer.** Organisation(s) from the paper's affiliations or the product owner, with lead authors in parentheses where useful. "unverified" means the affiliation could not be confirmed from the source.
- **Developer type.** One of: *LLM lab* (OpenAI, Anthropic, Google DeepMind, Meta AI/FAIR, Mistral, DeepSeek, …), *Big tech* (Google non-DeepMind, Microsoft, Amazon, IBM, Baidu, Alibaba, ByteDance, Huawei, Uber, LinkedIn and other large technology companies), *Data platform* (Snowflake, Databricks, Neo4j, dbt Labs, Palantir), *Startup/vendor* (startups, specialist vendors, and non-tech enterprises such as banks), *Academia* (universities, public research institutes, non-profit labs such as AI2 and Shanghai AI Lab), *Academia + industry* (with the industry partner named), *Open-source community* (community projects and standards bodies such as W3C). Where a paper's latest PDF lists Google DeepMind, it is filed as LLM lab, even if the work started at Google Research.
- **First release.** For arXiv papers, the month of the first arXiv version (v1), taken from the arXiv API. Where a venue publication came before the arXiv posting, or a public release came before the paper, the earlier date is given with a note. For products, the first public release or announcement from the notes; "~" marks dates not verified against an official source, and "n/a" means unknown. For products the notes describe mainly through a later milestone, that milestone is shown (e.g. "GA 2026-04").
- **High-level flow** is an arrow chain of the processing steps. **Key result** is one headline number with its provenance: *(author)* = reported by the method's own authors; *(vendor)* / *(company-reported)* / *(customer story)* = reported by the selling or deploying company; *(indep.)* = measured by a party that did not build the system; "as reported in X" = a number taken from another paper's comparison table. Author-reported numbers are not comparable across papers.

## Methods from LLM labs and big tech

Entries whose developer type is *LLM lab* or *Big tech*, grouped by company (main-table and brief entries both included). Each line gives the method, the category, the first release date, and what it does. Co-developed academic work and data-platform entries are listed after the company lists.

**Google / Google DeepMind** (LLM lab + big tech units)
- LMDX: Parsing/tables/forms, 2023-09. OCR lines tagged with quantised coordinate tokens + schema → LLM → JSON where each value cites segment ID → drop values not found in cited segment.
- Pix2Struct: Parsing/tables/forms, 2022-10. Masked web screenshots → parse to simplified HTML (pretraining) → fine-tune on doc/UI tasks.
- LangExtract: LLM IE & constrained decoding, 2025-07. Few-shot examples define schema → chunk document (max_char_buffer) → parallel controlled generation, multiple passes.
- Self-consistency / Universal Self-Consistency: LLM IE & constrained decoding, 2022-03. Sample k outputs → majority vote (or LLM picks most consistent free-form answer).
- UQE (Universal Query Engine): Semantic operators, 2024-06. SQL dialect with NL conditions → sampling + online-learned embedding proxies → compiled workflow → statistical aggregate estimates.
- AI query proxy models (BigQuery/AlloyDB): Semantic operators, 2026-03. AI.IF predicate → embed rows → train logistic-regression proxy online on sample (or offline) → proxy labels most rows, LLM the rest.
- schema.org: Schema/matching/ER, 2011. Shared vocabulary of web entity types → used as class/slot URIs and enums in schemas.
- Google MCP Toolbox for Databases: Query interfaces, ~2025-02. Tools.yaml defines tools (source, parameters, parameterised SQL) → agents call via MCP; plus execute_sql/list_tables.
- Self-Debugging: Query interfaces, 2023-04. LLM generates code → explains it + reads execution results → revises.
- Chain-of-Table: Hybrid retrieval, 2024-01. Table → LLM plans chained table operations (add column, select rows, group) → evolving table → answer.
- Self-Route: Hybrid retrieval, 2024-07. Try RAG → model self-reflects whether answerable → else route to long context.
- TFX Data Validation (TFDV): Quality/versioning/provenance, 2019. Infer schema → humans curate + version it → validate each batch → inter-batch drift/skew detection → propose schema edits.
- AIS / AutoAIS: Quality/versioning/provenance, 2021-12. Human two-stage judgment "attributable to identified source" → AutoAIS NLI classifier approximates it.
- DePlot: Semi-structured & multimodal, 2022-12. Chart image → plot-to-table translation model → linearised table → LLM reasons.
- MatCha: Semi-structured & multimodal, 2022-12. Pix2Struct pretraining on chart derendering + math reasoning → fine-tune chart QA.
- Google Document AI Custom Extractor: Enterprise cloud, 2024-01 (generative GA). Define schema → generative (0–50 docs), custom (10–100) or template (~3) model → fields with 0–1 confidence → CEL validation rules (preview).
- Google Document AI Layout Parser: Enterprise cloud, n/a. Document → tree-structured DocumentLayout (headings, paragraphs, tables, figures) → context-aware chunks with ancestor headings.
- BigQuery AI.GENERATE_TABLE / AI functions: Enterprise cloud, 2025-04 (GA 2025-11). Table or ObjectRef column + prompt + typed output_schema → Gemini per row → typed columns + status; AI.IF/AI.SCORE/AI.CLASSIFY/AI.AGG as SQL operators.
- BigQuery AI.PARSE_DOCUMENT + ObjectRef: Enterprise cloud, 2026-11 (GA). GCS objects → ObjectRef STRUCT columns → Document AI layout parser → structured JSON (titles, tables, images) in SQL.
- BigQuery / Gemini Enterprise data agents (verified queries): Enterprise cloud, n/a (publish to Gemini Enterprise GA 2026-10). Knowledge sources (tables, views, graphs, UDFs) + verified parameterised queries > glossary > instructions → agent SQL.

**Microsoft**
- TATR (Table Transformer) + PubTables-1M: Parsing/tables/forms, 2021-09. Page → DETR table detection → DETR structure recognition (rows, columns, headers, spans) → words from PDF text layer/OCR placed into cells → HTML/CSV.
- LayoutLM / LayoutLMv2 / LayoutLMv3: Parsing/tables/forms, 2019-12. OCR tokens + 2-D boxes (+ image patches from v2) → masked multimodal pretraining → fine-tune token labelling / linking.
- UDOP: Parsing/tables/forms, 2022-12. Text + image + layout → unified prompt-based seq2seq transformer → task outputs.
- DiT: Parsing/tables/forms, 2022-03. Self-supervised pretraining on document images → backbone for table/layout detection.
- ReMatch: Schema/matching/ER, 2024-03. Target tables as documents → embed + retrieve J candidate tables per source table → GPT-4 ranks target attributes.
- Table-GPT: Schema/matching/ER, 2023-10. Synthesise table tasks from real tables → "table-tune" GPT-3.5/ChatGPT.
- Microsoft GraphRAG (graph builder): KG construction, 2024-04. Chunk into TextUnits → LLM extracts entities (title, type, description) + untyped relationships, with "gleanings" re-prompts.
- Execution-guided decoding: Query interfaces, 2018-07. Execute partial SQL during decoding → discard faulty candidates.
- Self-verification for clinical IE: Quality/versioning/provenance, 2023-05. LLM extracts value → produces provenance span → checks/prunes its own output.
- TableSense: Semi-structured & multimodal, 2019-01 (AAAI). Spreadsheet cell grid featurised like an image → CNN detects table regions → active learning.
- SpreadsheetLLM (SheetCompressor): Semi-structured & multimodal, 2024-07. Sheet → structural-anchor extraction + inverted-index translation + format-aware aggregation (24.8x fewer tokens).
- MarkupLM: Semi-structured & multimodal, 2021-10. HTML/XML text + XPath embeddings → joint pretraining → fine-tune extraction/QA.
- Azure AI Document Intelligence (formerly Form Recognizer): Enterprise cloud, ~2019-05. Document → read / layout / prebuilt / custom template, neural or generative models → cells with polygons + content spans, fields with confidence.
- Azure AI Content Understanding: Enterprise cloud, ~2024-11 (GA API 2025-11). Analyzer: content extraction → segmentation/classification → field Extract / Classify / Generate with confidence + source grounding.
- Microsoft Fabric AI Functions: Enterprise cloud, n/a. Pandas / PySpark / T-SQL ai.extract with JSON Schema labels, ai.classify, ai.generate_response → columns; aifunc.load folder → table, ai.infer_schema.
- Microsoft Fabric data agent: Enterprise cloud, n/a. Tables / semantic models → read-only NL2SQL, NL2DAX, NL2KQL under user identity; example queries; no unstructured files.
- Azure AI Search agentic retrieval / Foundry IQ: Enterprise cloud, ~2025-05. Knowledge base → LLM query planning → parallel keyword/vector/hybrid subqueries → semantic rerank → merged content + references.

**IBM**
- EDD (PubTabNet): Parsing/tables/forms, 2019-11. Table image → CNN encoder → dual decoder (HTML structure + cell content) → HTML table; introduced TEDS metric.
- TableFormer: Parsing/tables/forms, 2022-03. Table crop → CNN backbone → transformer structure decoder + cell-bbox decoder → match boxes to PDF text cells → grid (no re-OCR).
- OTSL table language: Parsing/tables/forms, 2023-05. Structure model emits 5-token OTSL (C, L, U, X, NL) under syntax rules → always-valid grid → convert to HTML.
- SmolDocling / GraniteDocling: Parsing/tables/forms, 2025-03. Page → compact VLM → DocTags (elements with 0–500 grid locations, OTSL tables) → DoclingDocument.
- Docling: Parsing/tables/forms, 2024-08. PDF backend extracts text tokens + coordinates → layout detector → intersect boxes with tokens → TableFormer matched to PDF cells → optional OCR.
- GTE (Global Table Extractor): Parsing/tables/forms, 2020-05. Page → joint table detection → hierarchical cell detection with cell-containment penalty → grid; auto-labelled FinTabNet.
- Docling Heron layout models: Parsing/tables/forms, 2025-09. Page image → RT-DETR / D-FINE detector trained on 150k docs → layout boxes for Docling.
- Grapher: KG construction, 2022-11. Text → generate nodes first → then generate edges between them.
- A.DOT: Hybrid retrieval, 2026-03. NL question → DAG plan over SQL + document stores → structural/semantic validation → execute → cache plan via paraphrase-aware templates → lineage.
- Blended RAG: Hybrid retrieval, 2024-03. Dense + sparse indexes → hybrid query strategies → retrieval.
- IBM watsonx.data integration (unstructured): Enterprise cloud, 2025-06. Connectors → Docling / watsonx Document Understanding parse → PII masking, quality filter, confidence.

**Amazon / AWS**
- DocFormer: Parsing/tables/forms, 2021-06. OCR text + image + layout → multimodal self-attention with shared spatial embeddings → token labels.
- SLOT: LLM IE & constrained decoding, 2025-05. Any LLM free-text output → fine-tuned small model + constrained decoding restructures into schema.
- ReFinED: Schema/matching/ER, 2022-07. One forward pass: mention detection → fine-grained typing → disambiguation to Wikidata.
- Deequ: Quality/versioning/provenance, 2018. Declare constraints (completeness, uniqueness, range, satisfiesIf cross-field) → compile to Spark aggregation queries.
- Amazon Textract: Enterprise cloud, ~2019-05. Page → Detect Text / AnalyzeDocument (Tables, Forms, Queries, Layout) / AnalyzeExpense → blocks with geometry + confidence.
- Amazon Bedrock Data Automation (BDA): Enterprise cloud, ~2024-12. Docs/images/audio/video → per-page classification → blueprint (≤100 fields) extraction with normalisation, validation, confidence, visual grounding.
- GenAI IDP Accelerator: Enterprise cloud, 2025-08. OCR → classification + packet splitting → extraction (BDA or Textract+Bedrock) → assessment/confidence → HITL review UI → evaluation.
- Bedrock Knowledge Bases structured data retrieval: Enterprise cloud, 2024-12. Question + schema + query history → managed NL2SQL over Redshift / SageMaker Lakehouse; GenerateQuery returns SQL only.

**Alibaba / Ant Group**
- LingDT-VL-OCR: Parsing/tables/forms, 2026-03. VLM page parsing → cross-page table consolidation → CellBBoxRegressor localises cells from decoder hidden states.
- OvisOCR3: Parsing/tables/forms, 2026-10. One 0.8B model → page parsing + KIE + cross-page tables in a single pass.
- GeoLayoutLM: Parsing/tables/forms, 2023-04. OCR tokens + geometry → explicit geometric pretraining → relation heads link keys to values.
- XiYan-SQL: Query interfaces, 2024-11. M-Schema serialisation → multi-generator ensemble (fine-tuned + ICL) → refiner → fine-tuned selector.
- DAIL-SQL: Query interfaces, 2023-08. Compare question representations → similarity-based example selection/organisation → token-efficient prompt → SQL.

**Meta (FAIR / Meta AI)** (LLM lab)
- Nougat: Parsing/tables/forms, 2023-08. Scientific PDF page image → Swin encoder → mBART decoder → Markdown with LaTeX tables, page by page.
- Chain-of-Verification: LLM IE & constrained decoding, 2023-09. Draft answer → plan verification questions → answer independently → revise.
- GENRE: Schema/matching/ER, 2020-10. Text → seq2seq generates entity name under prefix-trie constraint → always-valid KB entity.
- UniK-QA: Hybrid retrieval, 2020-12. Verbalise text, tables, lists, KB triples to text → one dense retriever-reader.
- FAISS: Hybrid retrieval, ~2017-02. Vector index (flat, IVF, HNSW, PQ) → search; seeds fixed, same-thread-count runs reproducible except HNSW add order.

**Anthropic** (LLM lab)
- Quote-then-extract guidance: LLM IE & constrained decoding, n/a. Long doc → extract word-for-word quotes first → answer only from quotes, allow "I don't know".
- Contextual Retrieval: Hybrid retrieval, 2024-09. LLM prepends chunk-specific context → contextual BM25 + contextual embeddings → rerank.
- Claude structured outputs: OSS & case studies, n/a. JSON schema via output_config.format or strict tool use → constrained output (no recursive schemas, no numeric min/max).
- Anthropic "Writing effective tools for agents": OSS & case studies, 2025-09. Consolidated task-shaped tools → namespacing → readable IDs → concise/detailed response_format → pagination + actionable errors.

**Baidu**
- Qianfan-OCR: Parsing/tables/forms, 2026-03. Page → "Layout-as-Thought" (boxes, element types, reading order) → final structured output.
- PaddleOCR-VL (0.9B, v1.5, v1.6): Parsing/tables/forms, 2025-10. PP-DocLayoutV2 layout boxes + reading order → 0.9B VLM recognises each element → Markdown/JSON.
- PP-DocLayout: Parsing/tables/forms, 2025-03. Page → detector over 23 region classes → layout boxes.

**OpenAI** (LLM lab)
- OpenAI Structured Outputs: LLM IE & constrained decoding, 2024-08. JSON Schema in API request → server-side constrained decoding → schema-valid JSON.
- Whisper: Semi-structured & multimodal, 2022-09 (release; arXiv 2022-12). Audio → encoder-decoder transformer trained on 680k h weakly supervised audio → transcript.
- Provider batch APIs (OpenAI, Anthropic): OSS & case studies, ~2024. Submit up to 50k–100k requests with custom_id → async within 24 h → map results by custom_id (order not guaranteed).

**ServiceNow**
- PICARD: Query interfaces, 2021-09. Incremental SQL parser rejects inadmissible tokens during beam search → always-valid SQL.
- Auto-Cypher (SynthCypher): Query interfaces, 2024-12. Generate Cypher + questions → "LLM-as-Database-Filler" populates DB → execution check → 29.8k training pairs.
- ServiceNow Now Assist in Document Intelligence: Enterprise cloud, 2026-03. Document → autofill fields → reviewer checks every field (default) or full automation with missing-field flags → work records.

**Uber**
- Uber TextSense (invoices): OSS & case studies, 2025-04. Ingest → preprocessing → OCR → GPT-4 extraction → business-rule post-processing (exact/fuzzy match) → validation vs existing data.
- Uber QueryGPT: OSS & case studies, 2024-09. Question → Intent agent picks workspace → Table agent → Column-Prune agent → SQL; golden-set eval (intent, table overlap, run success).
- Uber Finch: OSS & case studies, 2025-07. LangGraph supervisor + SQL agent over curated single-table marts → OpenSearch alias index for columns and values → RBAC check.

**Grab**
- Grab metadata classification: OSS & case studies, 2023. Column metadata → GPT-3.5 picks one tag from curated library (with None option), JSON output → Kafka → access-control tiers.
- Grab Data-Arks: OSS & case studies, 2024-10. Frequent SQL queries and Python functions registered as individual APIs → LLM (Spellvault RAG) selects which pre-written query to run.

**Oracle**
- Oracle Select AI: Enterprise cloud, ~2023. NL prompt → LLM SQL over Autonomous DB with runsql / showsql / explainsql / feedback actions; column comments as context.
- Oracle DBMS_VECTOR_CHAIN + OCI Document Understanding: Enterprise cloud, 2026-01 (generative KV). In-DB UTL_TO_TEXT / chunks / embeddings; OCI DU generative key-value extraction from NL field prompts + few-shot → normalised JSON.

**SAP**
- Dependency-parsing KG construction: KG construction, 2025-07. Dependency parsing extracts triples (no LLM) → KG for GraphRAG.
- SAP Document AI: Enterprise cloud, n/a. Structured/semi-structured docs → OCR (100+ languages) + extraction → review UI with Joule → learns from corrections → S/4HANA.

**Xiaohongshu (rednote)**
- dots.ocr: Parsing/tables/forms, ~2025-07. Page → one VLM does layout + recognition → JSON per element (bbox, category, text; tables as HTML).
- FireRed-OCR: Parsing/tables/forms, 2026-03. VLM parser trained with format-constrained GRPO enforcing table closure and syntax validity.

**AT&T**
- Automatic metadata extraction for text-to-SQL: Query interfaces, 2025-05. Profile database + mine query logs (join constraints) → LLM-written metadata → schema linking → SQL.

**ByteDance**
- Dolphin: Parsing/tables/forms, 2025-05. Page → layout elements in reading order → parallel element parsing with heterogeneous anchor prompts.

**DeepSeek** (LLM lab)
- DeepSeek-OCR: Parsing/tables/forms, 2025-10. Page → DeepEncoder compresses to few vision tokens ("optical compression") → MoE decoder → Markdown (boxes on request).

**DoorDash**
- DoorDash product knowledge graph: OSS & case studies, ~2024. Classifier → LLM brand extraction → second LLM dedups vs taxonomy; organic labels via string match → LLM/OCR.

**Huawei**
- TableRAG (heterogeneous documents): Hybrid retrieval, 2025-06. Keep tables as MySQL tables + text KB → loop: decompose query → text retrieval → SQL generation and execution → intermediate answer.

**Instacart**
- Instacart PARSE: OSS & case studies, 2025-08. Versioned config (attribute definition, input SQL, few-shot, model, prompt) → multimodal LLM extraction.

**Intuit**
- Executable Schema Contracts: Schema/matching/ER, 2026-06. Deterministic profiling → closed-world field catalog with hashed IDs → LLM proposes schema citing only catalog IDs → validator (FieldValidity = 1.0).

**LinkedIn**
- LinkedIn SQL Bot: OSS & case studies, 2024-12. KG of users/tables/fields from DataHub + query logs → embed-retrieve top-20 tables → LLM re-rank to 7 → SQL → existence checks + EXPLAIN.

**Mistral AI** (LLM lab)
- Mistral OCR / Document AI: IDP vendors, ~2025-03 (OCR 3: 2025-12). Page → OCR model → Markdown with HTML tables → document_annotation: markdown + first 8 image boxes → vision LLM fills Pydantic/JSON schema.

**NAVER**
- Donut: Parsing/tables/forms, 2021-11. Document image → Swin encoder → BART decoder → JSON-like token sequence (no OCR).

**NVIDIA**
- HybridRAG (KG + vector): Hybrid retrieval, 2024-08. Retrieve from KG and vector store → combine contexts → LLM answer.

**Pinterest**
- Pinterest text-to-SQL / Analytics Agent: OSS & case studies, ~2024. RAG over table + query summaries (OpenSearch) → LLM top-K tables → user confirms → SQL; 2026: EXPLAIN validation, governance-aware ranking.

**Salesforce**
- Salesforce Data Cloud Document AI: Enterprise cloud, 2025-09. Documents as UDLOs → NLP/ML/LLM extraction → DLO/DMO objects queryable like structured data → Agentforce.

**Samsung**
- DualGraph: Hybrid retrieval, 2026-05. Specs → symbolic KG (typed triples, SPARQL) + text KG → LLM router → symbolic first, text fallback on failure.

**Shopify**
- Shopify Global Catalogue: OSS & case studies, 2025-07. Fine-tuned open vision LLMs with taxonomy-constrained outputs → selective field prompting → multi-LLM annotation + arbitrator.

**Swiggy**
- Swiggy Hermes V3: OSS & case studies, ~2026-01. Historical Snowflake SQL → NL descriptions indexed as few-shot → ReAct orchestrator → SQL with confidence explanation; RBAC, audit logs.

**TCS**
- Self-demonstrations for schema-ontology mapping: Schema/matching/ER, 2026-09. Symbolic constraints narrow search → LLM reasons per sub-task → self-generated demonstrations.

**Co-developed with universities** (Academia + industry; the company is a co-author, not the sole developer):
- Google / Google DeepMind: Fiscal-documents LLM pipeline, Attribute First, then Generate, Galois, iPDB, PG-Schema, CHASE-SQL, Reasoning-SQL, TableRAG (million-token tables), TURL, FreeDOM.
- Alibaba / Ant Group: Cycle-CenterNet (WTW), OneKE, IEPile, SEMA-SQL, ComEM, SAC-KG, LKD-KGC, CodeKGC, StructRAG, Dater.
- Amazon / AWS: RUBICON, Schema-free text-to-SQL via query-log KG, PlanPool, HybGRAG, Join-Aware Retrieval (JAR), ARM, OpenTab, KG accuracy estimation by sampling, CERES.
- Microsoft: Auto-Tables, UniversalNER, CESI, HarnessSQL, ParlayANN, ReAcTable, UDT-QA, SheetBrain.
- Huawei: GraphJudge, AutoSchemaKG / ATLAS, InvertiTune, Alpha-SQL.
- Meta (FAIR / Meta AI): GenIE, Binder, FActScore.
- NVIDIA: XGrammar, TP-invariant kernels.
- ByteDance: InstructUIE, OmniSQL.
- Tencent: Code4UIE, MAC-SQL.
- Salesforce: MiniCheck, UniChart.
- Kingsoft: MonkeyOCR / MonkeyOCR v1.5.
- Meituan: InstructTable.
- Baidu: UIE (Universal IE).
- LinkedIn: NL2Pipe.
- NAVER: KG2Cypher.
- Apple: Compatibility adapters for model updates.

**Data platforms** (for comparison):
- Snowflake: Snowflake Cortex AISQL (engine paper) (2025-11), Arctic-Text2SQL-R1 (2025-05), ReFoRCE (2025-02), Snowflake AI_PARSE_DOCUMENT (n/a (AGENTIC mode preview 2026-10)), Snowflake AI_EXTRACT (arctic-extract) (n/a (scores GA 2026-05)), Snowflake Document AI / Arctic-TILT (legacy) (2024-08), Snowflake semantic views + Cortex Analyst (~2024-08), Snowflake Cortex Search + analytical search pattern (~2024).
- Neo4j: Neo4j LLM Knowledge Graph Builder (~2024), Text2Cypher dataset (2024-12), Neo4j GraphRAG KG Builder (SimpleKGPipeline) (n/a).
- dbt Labs: dbt Semantic Layer / MetricFlow (~2023-10).
- Databricks: Delta Lake (~2019-04), Databricks ai_parse_document (~2025-11 (GA 2026-04)), Databricks ai_extract v2.1 (n/a), Databricks Agent Bricks Information Extraction (~2025-06), Databricks Genie (trusted assets) (~2024-06), Databricks ai_query (n/a).
- Palantir: Palantir Pipeline Builder "Use LLM" + Ontology (~2024-06 (typed outputs)).

**Pattern**

- **Big tech dominates parsing and the managed platforms.** In category 1, 26 of 45 entries come from big tech or LLM labs: IBM's TableFormer, OTSL and Docling line, Microsoft's TATR and LayoutLM family, Baidu's PaddleOCR-VL, Google's Pix2Struct and LMDX, Meta's Nougat, DeepSeek-OCR and ByteDance's Dolphin. All 31 category-10 product features are big tech or data platforms.
- **LLM labs mostly ship building blocks, not pipelines.** Only 20 of about 470 catalogued entries are LLM-lab work. Most are models (Whisper, Nougat, DeepSeek-OCR, FAISS), API features (OpenAI and Claude structured outputs, batch APIs) or guidance documents (quote-then-extract, tool design). Google DeepMind's LMDX, UQE, DePlot/MatCha and Self-Route are the main exceptions.
- **Academia dominates the middle of the pipeline.** Academic groups produced most entries in semantic operators and document-to-table systems (28 of 39, led by UC Berkeley, Stanford and MIT), schema matching and entity resolution (25 of 42), KG construction (21 of 39), source-specific literature and multimodal methods (25 of 39), and most determinism and provenance research. Open constrained-decoding engines come from academia and startups (Outlines from Normal Computing/.txt, XGrammar from CMU with NVIDIA, SGLang from Berkeley/Stanford). The LLM labs offer the API-side equivalent.
- **Startups and data platforms own the commercial and glue layers.** Startups account for 21 of 22 IDP-vendor entries and most of the open-source glue (Instructor, Pydantic AI, BAML, CocoIndex, dlt, Dagster, LlamaIndex, Unstructured, promptfoo). Data platforms (Snowflake, Databricks, Neo4j, dbt Labs, Palantir; 19 entries) own warehouse-native AI SQL functions and semantic layers. Snowflake also publishes text-to-SQL research (Arctic-Text2SQL-R1, ReFoRCE).
- **Evidence on query-side determinism comes mainly from company engineering write-ups.** Uber QueryGPT and Finch, LinkedIn SQL Bot, Grab Data-Arks and Pinterest, together with the vendor semantic-layer benchmarks (dbt, Cube), are the main sources showing that restricting agents to curated tables, pre-registered queries or compiled semantic-layer SQL makes results repeatable. Academic text-to-SQL work mostly targets benchmark accuracy.

## 1. Document parsing, tables and forms

Turning PDFs, scans and images into grids, key-value pairs and element boxes. Specialised detector/structure models give the most grounded tables; VLM parsers are the scan fallback. (25 main entries, 20 brief.)

| Method | Developer | Developer type | First release | High-level flow | Tools / models | Key result |
|---|---|---|---|---|---|---|
| EDD (PubTabNet) | IBM Research Australia (Zhong, ShafieiBavani, Jimeno Yepes) | Big tech | 2019-11 | table image → CNN encoder → dual decoder (HTML structure + cell content) → HTML table; introduced TEDS metric | CNN encoder, LSTM decoders; PubTabNet 568k tables | TEDS 89.9 on PubTabNet (measured by TableFormer authors, third-party) |
| TATR (Table Transformer) + PubTables-1M | Microsoft (Smock, Pesala, Abraham) | Big tech | 2021-09 | page → DETR table detection → DETR structure recognition (rows, columns, headers, spans) → words from PDF text layer/OCR placed into cells → HTML/CSV | DETR; PubTables-1M; MIT code (repo archived) | Acc_Con 0.824 exact-match, PubTables-1M (author) |
| TableFormer | IBM Research Zurich (Nassar, Livathinos, Lysak et al.) | Big tech | 2022-03 | table crop → CNN backbone → transformer structure decoder + cell-bbox decoder → match boxes to PDF text cells → grid (no re-OCR) | transformer decoders; SynthTabNet 600k | TEDS 93.6 vs Camelot 73.0 on PubTabNet PDFs (author) |
| OTSL table language | IBM Research Zurich (Lysak, Nassar, Livathinos et al.) | Big tech | 2023-05 | structure model emits 5-token OTSL (C, L, U, X, NL) under syntax rules → always-valid grid → convert to HTML | TableFormer; adopted by MinerU2.5, SmolDocling | TEDS 0.959 vs 0.92 (HTML) on FinTabNet, ~2x faster (author) |
| POTATR (Page-Object TATR) + PubTables-v2 | Kensho Technologies (S&P Global) (Smock, Liang, Sokolov) | Startup/vendor | 2026-06 | page image → non-autoregressive image-to-graph (tables, captions, footers + parent-child links, all boxed) → text assigned geometrically from PDF layer/OCR → ViT continuation classifier merges multi-page tables | 29M-param TATR extension; ViT-B-16; PubTables-v2 (548k tables) | page-level GriTS_Con 0.965 vs Gemini 3.1 Pro 0.942, ~$47 vs $15,000 per M pages (author) |
| MinerU-Popo | Shanghai AI Lab, SJTU (OpenDataLab ecosystem) | Academia | 2026-05 | page-level output of any parser → fine-tuned VLM post-processor → merge truncated text/tables, rebuild title hierarchy, link images to text | Qwen3-VL-4B | ≥20% title-hierarchy TEDS gain across 5 OCR models (author) |
| MonkeyOCR / MonkeyOCR v1.5 | Huazhong Univ. of Science and Technology, Kingsoft | Academia + industry (Kingsoft) | 2025-06 | layout detection (Structure) → block recognition (Recognition) → reading-order relations (Relation); v1.5 adds type-guided cross-page table merging + render-and-compare RL | 3B VLM | Table TEDS 86.78 on OmniDocBench v1.5 (pro-3B; reported by MinerU2.5 authors) |
| Auto-Tables | Microsoft Research, Georgia Tech (Li, He, Yan et al.) | Academia + industry (Microsoft) | 2023-07 | non-relational spreadsheet/web table → model predicts multi-step transformation program (transpose, stack, wide-to-long) → execute → relational table | learned program synthesiser; no user examples | relationalises >70% of 244 real cases (author) |
| TableVision | Harvard University | Academia | 2026-10 | degraded historical table scans → digit reading → cell assignment → column sum-check gate (accept / flag / withhold) → add gated rows | VLM reader + arithmetic verification | 933 of 934 testable accepted sums confirmed by official returns (author) |
| Fiscal-documents LLM pipeline | Google + independent co-authors | Academia + industry (Google) | 2025-11 | 200+-page fiscal PDFs → LLM extraction → hierarchy-of-totals used as multi-level validation checks | LLMs | n/a |
| LayoutLM / LayoutLMv2 / LayoutLMv3 | Microsoft Research Asia (Xu, Li, Cui; Huang, Lv et al.) | Big tech | 2019-12 | OCR tokens + 2-D boxes (+ image patches from v2) → masked multimodal pretraining → fine-tune token labelling / linking | BERT-style encoder; v2/v3 weights CC-BY-NC-SA | FUNSD F1 92.08 (v3-LARGE, author) |
| Donut | NAVER Clova (Kim, Hong, Yim et al.) | Big tech | 2021-11 | document image → Swin encoder → BART decoder → JSON-like token sequence (no OCR) | 143M params; MIT | CORD F1 84.1 vs 78.9 LayoutLMv2+OCR (author) |
| LMDX | Google Cloud AI Research, Google DeepMind (Perot, Kang, Luisier et al.) | LLM lab | 2023-09 | OCR lines tagged with quantised coordinate tokens + schema → LLM → JSON where each value cites segment ID → drop values not found in cited segment → 16 samples, majority vote | PaLM 2 / Gemini Pro | VRDU Registration F1 87.72 vs 69.44 LayoutLMv2 at 10 training docs (author) |
| DocLLM | JPMorgan AI Research (Wang, Raman, Sibue et al.) | Startup/vendor | 2023-12 | OCR text + bounding boxes → LLM with disentangled spatial attention (no image encoder) → infilling pretraining → instruction tuning | Llama/Falcon-based LLM | beats SOTA LLMs on 14 of 16 datasets (author) |
| RASG (Retrieval Augmented Structured Generation) | Expedock | Startup/vendor | 2024-05 | retrieve similar annotated docs → text LLM with structured generation as tool use → heuristic back-calculates line-item boxes | text LLMs, constrained decoding | competitive with LMMs on KIE and line items (author; no single figure) |
| Qianfan-OCR | Baidu (Qianfan team) (Dong, Zheng, Xu et al.) | Big tech | 2026-03 | page → "Layout-as-Thought" (boxes, element types, reading order) → final structured output | 4B end-to-end VLM | top average on public KIE benchmarks, above Gemini-3.1-Pro (author) |
| Nougat | Meta AI (Blecher, Cucurull, Scialom et al.) | LLM lab | 2023-08 | scientific PDF page image → Swin encoder → mBART decoder → Markdown with LaTeX tables, page by page | 350M params; CC-BY-NC weights | table F1 78.0 vs GROBID 69.7 (author) |
| MinerU2.5 | Shanghai AI Lab (OpenDataLab), PKU, SJTU (Niu, Liu, Gu et al.) | Academia | 2025-09 | downsampled page → layout stage (boxes, class, rotation, reading order) → native-resolution crops → VLM recognises each element (tables via OTSL → HTML) | 1.2B decoupled VLM; AGPL-3.0 weights | OmniDocBench v1.5 overall 90.67, 2.12 pages/s A100 (author) |
| PaddleOCR-VL (0.9B, v1.5, v1.6) | Baidu (Cui, Sun, Liang et al.) | Big tech | 2025-10 | PP-DocLayoutV2 layout boxes + reading order → 0.9B VLM recognises each element → Markdown/JSON | PP-DocLayoutV2, ERNIE-based 0.9B VLM; Apache-2.0 | OmniDocBench v1.5 overall 92.86 (author) |
| dots.ocr | rednote hilab | Big tech | ~2025-07 | page → one VLM does layout + recognition → JSON per element (bbox, category, text; tables as HTML) | 3B VLM; MIT | olmOCR-Bench Tables 88.3 (self-reported); 0.28–0.35 pages/s (measured by MinerU2.5/PaddleOCR-VL authors) |
| olmOCR / olmOCR 2 | Allen Institute for AI (Poznanski, Soldaini, Lo et al.) | Academia | 2025-02 | PDF page image + text-layer anchors → fine-tuned 7B VLM → linearised text with tables; v2 adds RL with unit-test rewards; temperature escalation + retries | Qwen2-VL-7B base; olmOCR-Bench; Apache-2.0 | $176 per M pages vs ~$6,240 GPT-4o; olmOCR-Bench 82.4 (author) |
| SmolDocling / GraniteDocling | IBM Research, Hugging Face (Nassar, Marafioti, Omenetti et al.) | Big tech | 2025-03 | page → compact VLM → DocTags (elements with 0–500 grid locations, OTSL tables) → DoclingDocument | 256M / 258M VLMs; GraniteDocling Apache-2.0 (2025-09) | FinTabNet table TEDS 0.52 vs TableFormer 0.89 (author) |
| DeepSeek-OCR | DeepSeek-AI (Wei, Sun, Li) | LLM lab | 2025-10 | page → DeepEncoder compresses to few vision tokens ("optical compression") → MoE decoder → Markdown (boxes on request) | ~3B MoE decoder; MIT | 200k+ pages/day on one A100-40G (author) |
| Dolphin | ByteDance (Feng, Wei, Fei et al.) | Big tech | 2025-05 | page → layout elements in reading order → parallel element parsing with heterogeneous anchor prompts | VLM | OmniDocBench v1.5 overall 74.67 (reported by MinerU2.5 authors) |
| Docling | IBM Research Zurich (Auer, Lysak, Nassar et al.) | Big tech | 2024-08 | PDF backend extracts text tokens + coordinates → layout detector → intersect boxes with tokens → TableFormer matched to PDF cells → optional OCR → DoclingDocument JSON with bboxes | Heron layout model, TableFormer, EasyOCR; MIT | 0.6–2.45 pages/s on CPU without OCR (author) |

**Also covered briefly:** GTE (Global Table Extractor) (IBM Research, 2020-05); Cycle-CenterNet (WTW) (Alibaba, Wuhan University, 2021-09); UniTable (Georgia Tech, ADP, 2024-03); InstructTable (Beijing Institute of Technology, Meituan, 2026-04); LingDT-VL-OCR (Ant Group, 2026-03); OvisOCR3 (Alibaba, 2026-10); TASER (J.P. Morgan AI Research, 2025-08); DocFormer (AWS AI, 2021-06); LiLT (South China Univ. of Technology, INTSIG, 2022-02); GeoLayoutLM (Alibaba Research, 2023-04); Pix2Struct (Google Research, 2022-10); UDOP (Microsoft Azure Cognitive Services Research, 2022-12); VDInstruct (KAIST, Auburn University, 2025-07); GOT-OCR2.0 (StepFun, Megvii, Tsinghua, UCAS, 2024-09); FireRed-OCR (Xiaohongshu, 2026-03); Docling Heron layout models (IBM Research Zurich, 2025-09); DocLayout-YOLO (Shanghai AI Lab, 2024-10); PP-DocLayout (Baidu, 2025-03); DiT (Microsoft Research Asia, 2022-03); SCORE evaluation (Unstructured Technologies, 2025-09).

## 2. LLM information extraction and constrained decoding

Turning text into typed records: instruction/code-tuned IE models, span encoders, schema-guided extraction, grammar-constrained decoding and grounding checks. (23 main entries, 21 brief.)

| Method | Developer | Developer type | First release | High-level flow | Tools / models | Key result |
|---|---|---|---|---|---|---|
| UIE (Universal IE) | Chinese Academy of Sciences, Baidu (Lu, Liu, Dai et al.) | Academia + industry (Baidu) | 2022-03 | text + schema prompt ("structural schema instructor") → pretrained text-to-structure T5 → structured extraction language (SEL) → entities/relations/events | T5 | SOTA on 13 datasets across 4 IE tasks (author) |
| GoLLIE | HiTZ, University of the Basque Country (Sainz, García-Ferrero, Agerri et al.) | Academia | 2023-10 | schema = Python classes with guideline docstrings + candidate comments → fine-tuned code LLM writes `result = [...]` → execute to get typed instances | Code-LLaMA 7B/13B/34B | zero-shot avg F1 55.3 vs 42.3 without guidelines (author) |
| KnowCoder / KnowCoder-X | Chinese Academy of Sciences (ICT) (Li, Zeng, Zuo et al.) | Academia | 2024-03 | code-style schema library (>30k types) → code pretraining (~1.5B tokens) → instruction tuning → code-form extraction | LLaMA2-based | +49.8% relative F1 vs LLaMA2 few-shot (author) |
| UniversalNER | USC, Microsoft Research (Zhou, Zhang, Gu et al.) | Academia + industry (Microsoft) | 2023-08 | ChatGPT labels diverse text → targeted distillation into small LLM → open-type NER | LLaMA 7B/13B | +7–9 F1 over ChatGPT on 43 datasets (author) |
| R1-RE | UMD, UNC et al. (Dai, Zheng, Yang et al.) | Academia | 2025-07 | relation extraction framed as guideline-guided reasoning → RL with verifiable reward | 7B LLM, RLVR | ~70% avg out-of-domain accuracy, on par with GPT-4o (author) |
| GLiNER | LIPN CNRS, FI Group (Zaratiana, Tomeh, Holat) | Academia + industry (FI Group) | 2023-11 | text + entity-type labels → bidirectional encoder scores all spans against label embeddings in parallel → spans above threshold | DeBERTa-v3, 50–300M params; CPU | zero-shot avg F1 60.9 vs ChatGPT 47.5 on 7 OOD sets (author, competitor numbers copied) |
| GLiNER2 | Fastino AI (Zaratiana, Pasternak, Boyd et al.) | Startup/vendor | 2025-07 | schema interface → one encoder does NER, classification and hierarchical structured extraction → typed spans | small encoder; CPU-efficient | n/a (CPU-efficient multi-task claim) |
| NuExtract (2.0 / 3) | NuMind | Startup/vendor | ~2024-06 | JSON template with typed leaves (verbatim-string, integer, date-time, enum…) + document → fine-tuned VLM fills template, null/[] when absent; temperature ~0 | NuExtract 2.0-8B = Qwen2.5-VL-7B fine-tune, MIT | ExtractBench (LlamaIndex) value F1 47.9 vs 95.6 for LlamaExtract (benchmark by competitor) |
| ChatIE | Beijing Jiaotong University (Wei, Cui, Cheng et al.) | Academia | 2023-02 | stage 1: ask ChatGPT which types are present → stage 2: multi-turn QA fills slots per type → assemble records | ChatGPT | beats some full-shot models on NYT11-HRL (author) |
| SPIRES / OntoGPT | Lawrence Berkeley National Lab (Monarch) (Caufield et al.) | Academia | 2023-04 | LinkML schema → recursive per-class LLM prompting → parse values → ground each value to ontology identifiers | GPT-3.5/4, LinkML, ontology lookups | comparable to mid-range RE methods with no training data (author) |
| LangExtract | Google | Big tech | 2025-07 | few-shot examples define schema → chunk document (max_char_buffer) → parallel controlled generation, multiple passes → align each extraction to char offsets (char_interval or None) | Gemini / OpenAI structured output; Apache-2.0 | n/a (no benchmark published) |
| OneKE | Zhejiang University, Ant Group (Luo, Ru, Liu et al.) | Academia + industry (Ant Group) | 2024-12 | web page / PDF → schema agent → extraction agent → reflection agent with configurable knowledge base of schemas and error cases → records | multi-agent LLM, Docker | n/a (demo) |
| xmemory (schema-grounded memory) | xmemory (Petrov et al.) | Startup/vendor | 2026-04 | object detection → field detection → field-value extraction with validation gates and local retries → verified records → reads as constrained queries | LLM + validators | 90.42% object-level accuracy (vendor, author) |
| Radiology archive structuring | TU Munich, TUM University Hospital et al. (Puttkammer, Drexel, Fritzsche et al.) | Academia | 2026-10 | report → constrained-decoding selection among 150 templates (3 steps) → fill template → flag unsupported content | gpt-oss-120B, one GPU | 2.19M reports; 88.7% of fields unchanged by residents (author) |
| Outlines | Normal Computing (Willard, Louf) | Startup/vendor | 2023-07 | regex/CFG/JSON Schema → finite-state machine → precomputed vocabulary index → mask invalid tokens each step | Python library (.txt) | little per-token overhead (author) |
| XGrammar | CMU, NVIDIA, SJTU, UC Berkeley (Dong, Ruan, Cai et al.) | Academia + industry (NVIDIA) | 2024-11 | grammar → split vocabulary into context-independent (prechecked) and context-dependent tokens (runtime stack check) → token mask | integrated in vLLM/SGLang | up to 100x faster than prior engines (author) |
| llguidance | guidance-ai (Moskal) | Open-source community | ~2024 | JSON Schema/grammar → Earley parser over regex-derivative lexer + token trie → per-token mask (~50 µs) | Rust; powers OpenAI Structured Outputs; in vLLM, SGLang, llama.cpp; MIT | top JSONSchemaBench coverage 0.41 GitHub-Hard (Guidance; benchmark co-authored by its developers) |
| OpenAI Structured Outputs | OpenAI | LLM lab | 2024-08 | JSON Schema in API request → server-side constrained decoding → schema-valid JSON | gpt-4o-2024-08-06+; JSON Schema subset | 100% vs <40% schema following on vendor eval (vendor) |
| Grammar-constrained decoding for IE (input-dependent grammars) | EPFL (Geng, Josifoski, Peyrard et al.) | Academia | 2023-05 | build grammar from input/KB (only allow strings present in text or valid KB IDs) → constrained decoding with off-the-shelf LM | off-the-shelf LMs | beats unconstrained LMs and some fine-tuned models on closed IE (author) |
| Draft-Conditioned Constrained Decoding | Univ. of Central Florida, Lockheed Martin AI Center (Reddy, Walker, Ide) | Academia + industry (Lockheed Martin) | 2026-02 | unconstrained draft → constrained decoding conditioned on draft → valid structured answer | any LLM + CD engine | GSM8K strict accuracy 15.2% → 39.0% (1B model, author) |
| SafePassage | Pattern Data (Barrow, Patel, Kharkovski) | Startup/vendor | 2025-09 | LLM emits entity + supporting context → Smith-Waterman aligner locates context in doc (reject <0.6) → NLI scorer checks entailment | black-box LLMs, fine-tuned DeBERTa NLI | up to 85% fewer hallucinations on legal IE (author) |
| Quote-then-extract guidance | Anthropic | LLM lab | n/a | long doc → extract word-for-word quotes first → answer only from quotes, allow "I don't know" → retract claims without quotes; best-of-N disagreement as signal | Claude | n/a (vendor guidance) |
| Self-consistency / Universal Self-Consistency | Google Research (Brain) (Wang, Wei, Schuurmans et al.; Chen et al.) | Big tech | 2022-03 | sample k outputs → majority vote (or LLM picks most consistent free-form answer) | any LLM | +17.9% on GSM8K (author) |

**Also covered briefly:** InstructUIE (Fudan University, ByteDance, 2023-04); CodeIE (Fudan University, ECNU, 2023-05); Code4UIE (Chinese Academy of Sciences (ICT), Tencent, 2023-11); IEPile (Zhejiang University (ZJU–Ant Group lab), 2024-02); ADELIE (Tsinghua University, 2024-05); MetaIE / Cuckoo (UC San Diego, 2024-03); RUIE (Central South University, 2024-09); EAGER (Univ. of Oldenburg, DFKI, 2026-09); GLiREL (Quantexa, 2025-01); GLiNER multi-task / bi-encoder / GLiNER-Relex (Knowledgator, 2024-06); GPT-NER (unverified, 2023-04); StructSense (MIT McGovern Institute, Fylo Labs et al., 2025-07); STAGE (Seoul National University, 2026-06); SGLang (compressed FSM) (UC Berkeley, Stanford et al. (LMSYS), 2023-12); DOMINO (ETH Zurich, 2024-02); CRANE (UIUC, 2025-02); SLOT (Amazon, 2025-05); Attribute First, then Generate (Bar-Ilan University, Google Research, 2024-03); ContextCite (MIT, 2024-09); Chain-of-Verification (Meta AI, 2023-09); Multi-stage clinical validation (Oak Ridge National Lab, Vanderbilt, 2026-04).

## 3. Semantic operators and document-to-table systems

Database-community systems that materialise tables from documents or run LLM-backed operators inside queries. (23 main entries, 16 brief.)

| Method | Developer | Developer type | First release | High-level flow | Tools / models | Key result |
|---|---|---|---|---|---|---|
| Evaporate / Evaporate-Code+ | Stanford University, Cornell (Arora, Yang, Eyuboglu et al.) | Academia | 2023-04 | sample docs → LLM proposes attributes → LLM writes many candidate extraction functions → weak supervision ensembles them → run on all docs → table | text-davinci-003 / GPT-3.5; Python | 110x fewer LLM tokens, +10.1 F1 vs direct extraction (author); least accurate on complex docs in UDA-Bench (indep.) |
| TWIX | UC Berkeley (Lin, Hasan, Kosalge et al.) | Academia | 2025-01 | templatised docs (invoices, tax forms) → infer visual template (field co-location, row/column alignment) → extract against template, not per-doc prompting | template inference + LLM on samples | 3,786x cheaper and >25% more accurate than Textract/Azure DI/GPT-4V on 34 datasets (author) |
| Doctopus | Chai, Li, Deng et al. (BIT group behind QUEST/UDA-Bench (affiliation unverified)) | unverified | 2025 | index docs → send only relevant chunks → estimate quality per strategy per attribute → choose LLM / non-LLM strategy under cost budget → table | LLMs + non-LLM extractors | +11% quality at equal cost (author) |
| Text2DB / OPAL | UIUC (Jiao, Li, Zhou et al.) | Academia | 2025-10 | IE recast as DB update (infill, add rows, add columns) → Observer/Planner/Analyzer agents write code plans calling IE models → adapt to existing schema | LLM agents + IE models | n/a |
| Aryn Sycamore / Luna / DocParse | Aryn Inc. (Anderson, Fritz, Lee et al.) | Startup/vendor | 2024-09 | DocParse PDFs → DocSets → Sycamore declarative pipeline extracts schema fields (with lineage) → OpenSearch index → Luna LLM planner turns NL question into plan over index + LLM operators | DocParse, Sycamore, OpenSearch, LLMs | 20/30 questions vs 2/30 for RAG on NTSB reports (author, preliminary) |
| LOTUS | Stanford, UC Berkeley (Patel, Jha, Pan et al.) | Academia | 2024-07 | pandas-like API with semantic operators (sem_filter, sem_join, sem_topk, sem_agg) → optimiser uses proxies with accuracy guarantees vs "gold algorithm" → LLM calls per row | LLMs, embedding/small-model proxies; optional SQLite cache | SemBench quality 0.731 at $0.86 (indep.) |
| Palimpzest (+ PalimpChat) | MIT, UChicago, Arizona (Liu, Russo, Cafarella et al.) | Academia | 2024-05 | declarative AI-analytics program → optimiser chooses plan for cost/runtime/quality → execute LLM operators; PalimpChat agent writes pipelines from NL | LLMs; Archytas ReAct agent | SemBench quality 0.715 at $1.06 (indep.) |
| Abacus | MIT (Russo, Liu, Sudhir et al.) | Academia | 2025-05 | estimate operator quality from few validation examples, priors, LLM judge → cost-based optimisation under constraints → plan | Palimpzest | 10.8x cheaper, 6.7–39.4% better quality than next best (author) |
| DocETL (+ DocWrangler) | UC Berkeley, Columbia (Shankar, Chambers, Shah et al.) | Academia | 2024-10 | YAML/Python map/reduce/filter/resolve pipeline → agentic optimiser applies rewrite directives (split/gather, decompose) → LLM-synthesised validators pick plan → run | LLMs; DocWrangler IDE | 21–80% more accurate than baselines (author); Doc2DB relation F1 41.51 (indep.) |
| UQE (Universal Query Engine) | Google DeepMind, Georgia Tech (Dai, Wang, Wan et al.) | LLM lab | 2024-06 | SQL dialect with NL conditions → sampling + online-learned embedding proxies → compiled workflow → statistical aggregate estimates | LLMs, embeddings | n/a (aggregates are estimates) |
| ThalamusDB | Jo, Trummer (Cornell University) | Academia | 2024 | SQL with NL predicates on text/images/audio → run models on a sample → return deterministic bounds on result, trade error vs time vs labelling | multimodal models | 35x faster than MindsDB (author) |
| SUQL | Stanford University (Liu, Xu, Tjangnaka et al.) | Academia | 2023-11 | conversational query → SQL with `summary()` / `answer()` free-text primitives → execute over hybrid data | LLM in-context parser | 90.3% vs 63.4% (linearisation) on Yelp KB (author) |
| BlendSQL | Fidelity Investments (FMR) (Glenn, Dakle, Wang et al.) | Startup/vendor | 2024-02 | SQLite superset → LLM "ingredient" functions inside SQL → type-constrained LLM calls → hybrid QA | SQLite, open/API LLMs | 35% fewer tokens (author); open models 390x cheaper than API (author, 2026) |
| TAG (Table-Augmented Generation) | UC Berkeley, Stanford (Biswal, Patel, Jha et al.) | Academia | 2024-08 | NL question → query synthesis → exact DB execution → LM generates answer over results | LLM + SQL DB | 55% vs ≤20% for Text2SQL/RAG on TAG-Bench (author) |
| RUBICON | TU Darmstadt, MIT, AWS AI Labs (Wenz, Treutwein, Demiralp, Stonebraker et al.) | Academia + industry (Amazon) | 2026-04 | wrap sources as tables → restricted SQL-like Agentic Query Language → optimisable, reproducible SQL execution | LLM agent + SQL | 100% vs 0% (ReAct) on own enterprise benchmark; −98.64% tokens on SemBench E-Commerce (author) |
| Snowflake Cortex AISQL (engine paper) | Snowflake (Liskowski, Han, Aggarwal et al.) | Data platform | 2025-11 | SQL with AI_FILTER/AI_CLASSIFY/AI_AGG/AI_EXTRACT → AI-aware optimiser (inference cost first-class) → proxy→oracle model cascades → semantic join rewritten as multi-label classification | Snowflake engine, hosted LLMs | cascades 2–6x faster at 90–95% oracle quality (author, production) |
| AI query proxy models (BigQuery/AlloyDB) | Google Cloud (Chung, Desai, He et al.) | Big tech | 2026-03 | AI.IF predicate → embed rows → train logistic-regression proxy online on sample (or offline) → proxy labels most rows, LLM the rest | embeddings + LR proxies | 991x latency / 792x cost reduction with offline proxies (author) |
| ZenDB | UC Berkeley, Columbia, Tsinghua (Lin, Hulsebos, Ma et al.) | Academia | 2024-05 | offline: build Semantic Hierarchical Tree per templatised doc → user declares SQL schema → query time: tree search + LLM fills attributes → per-tuple text-span provenance | NLTK summaries, GPT | 4–29x cheaper than whole-doc GPT (author) |
| QUEST | Beijing Institute of Technology (Sun, Deng, Chai et al.) | Academia | 2025-07 | index attribute-relevant segments → evidence-augmented retrieval → per-document filter ordering, join-to-filter rewrite → LLM extraction | LLM + index | 30%–6x cost savings, +10–27% F1 (author) |
| OCTOPUS (tag model) | UC Irvine, UC Berkeley, Blizzard (Zhang, Lahjouji, Lin, Mehrotra et al.) | Academia | 2026-10 | each semantic judgment written back as a tag column + provenance side-table → later queries reuse tags via exact-match/complement/implication rules → SQL only | LLM + RDBMS | 10–108x fewer model rows; 3 of 8 queries with zero LLM calls (author) |
| SemReuse | RMIT Vietnam, Deakin, Aalborg (Tran-Truong, Kieu, Le et al.) | Academia | 2026-10 | cache filter results as materialised views → LLM decides equivalence/implication with new filter → pooled stratified audit bounds errors | LLM reasoner + audits | up to 15.4x reduction (author) |
| SemBaker | University of Hawaii (Dong, Wang) | Academia | 2026-08 | semantic operator → LLM called once to generate deterministic Python function → refine/validate → run locally; cost model routes native vs compiled | plug-ins for Palimpzest, LOTUS, Nirvana, DocETL | 5.4–10.7x cheaper, 4.8–6.3x faster (author) |
| BARGAIN | UC Berkeley (Zeighami, Shankar, Parameswaran) | Academia | 2025-09 | adaptive sampling + statistical estimation → route records to cheap LLM vs oracle with accuracy/precision/recall guarantees | LLM cascades | up to 86% more cost reduction than SUPG (author) |

**Also covered briefly:** Galois (EURECOM, Google, 2023-04); CAESURA (TU Darmstadt, 2023-08); ELEET (TU Darmstadt, 2024-10); FlockMTL (Polytechnique Montréal, U. Waterloo, 2025-04); iPDB (Purdue University, Google, 2026-01); Sema (Wuhan Univ., CUHK, BIT, 2026-03); Unify / AgenticData (Tsinghua DB group (Wang, Li, Feng; Sun, Li et al.), 2025); Nirvana (Zhejiang University, Aalborg University, 2025-11); SEMA-SQL (Alibaba, Univ. of Michigan, 2026-04); NL2Pipe (Univ. of Hawaii, LinkedIn, 2026-06); ScaleDoc (Tsinghua University, 2025-09); PLOP (UC Berkeley, 2026-04); JEVDB (Purdue University, 2026-10); Task cascades (UC Berkeley, 2026-01); Featurized-Decomposition Join (FDJ) (UC Berkeley, 2025-12); Stretto (TU Darmstadt, EURECOM, 2026-02).

## 4. Schema induction, schema matching, entity resolution

Choosing or inducing the target schema, mapping sources onto it, and resolving entities and values to stable IDs. (26 main entries, 16 brief.)

| Method | Developer | Developer type | First release | High-level flow | Tools / models | Key result |
|---|---|---|---|---|---|---|
| ScheMatiQ | Hebrew University, Allen AI | Academia | 2026-04 | research question + corpus → discover observation unit (row entity) → induce query-guided schema → extract grounded values → experts revise schema and results in web UI | LLMs + web UI | n/a (qualitative expert evaluation) |
| DocSage | HKUST (Guangzhou) | Academia | 2026-03 | question → infer query-specific minimal joinable schema → extract text into relational tables with error-aware correction → reason over tables | LLMs + SQL | n/a |
| Executable Schema Contracts | Intuit AI Research | Big tech | 2026-06 | deterministic profiling → closed-world field catalog with hashed IDs → LLM proposes schema citing only catalog IDs → validator (FieldValidity = 1.0) → statistical keys/FKs/cardinality → deterministic extractors + SourceRecord/DERIVED_FROM provenance → monotone schema extension | LLM + statistical profiling + graph store | removing statistical key/FK step costs 2.1–6.8 EM points (author) |
| SINT-Flow | University of Mannheim (Korini, Bizer) | Academia | 2026-07 | many source tables → Table Splitting → Schema Matching → Table Grouping → Attribute Merging → integrated global schema; self-consistency + review loop | GPT-5.2 or Qwen-3.6-27B | 84% schema-mapping F1 on SINT-Bench (author) |
| EDC (Extract–Define–Canonicalize) | National University of Singapore (Zhang, Soh) | Academia | 2024-04 | LLM open IE → LLM writes definition per relation → embed definitions → retrieve target schema elements (Schema Retriever) → LLM verifies canonical mapping (target alignment or self-canonicalisation) | GPT-3.5/4, E5-Mistral-7B | 0.956 vs 0.724 (CESI) precision on WebNLG canonicalisation (author, human-evaluated) |
| SCOPE / SCION | Chinese Academy of Sciences (IIE) | Academia | 2026-05 | corpus → candidate-linked evidence → naming, merging, filtering, fusion under strict JSON contracts → induced schema graph; benchmark from 24 IE datasets | LLMs | beats Text2Onto-style and LLM-only baselines (author) |
| LLMs4OL | TIB Leibniz Information Centre (Babaei Giglou et al.) | Academia | 2023-07 | ontology learning as 3 tasks: term typing → taxonomy discovery → non-taxonomic relation extraction, zero-shot over 9 LLM families | GPT-class and open LLMs; WordNet, GeoNames, UMLS | 2024 challenge: relation-extraction best F1 0.0783 on UMLS (indep., multi-team) |
| LinkML + Schema Automator | LinkML community (Moxon et al.) | Academia | 2025-11 | author one LinkML model → generate JSON Schema / SQL DDL / Pydantic / OWL; schema-automator bootstraps draft schema from TSV/SQLite/RDF, optional LLM annotation | LinkML toolchain | n/a |
| Valentine | TU Delft, ING Bank (Koutras et al.) | Academia + industry (ING) | 2020-10 | benchmark harness running classic matchers (COMA, Cupid, Similarity Flooding, Distribution-based, EmbDI, Jaccard-Levenshtein) on fabricated + real pairs | classic matchers | no single matcher dominates (indep.) |
| FM wrangling ("Can Foundation Models Wrangle Your Data?") | Stanford University (Narayan et al.) | Academia | 2022-05 | serialise rows/columns as text → few-shot prompts for entity matching, schema matching, imputation, transformation | GPT-3-175B | schema matching F1 45.2 (k=3) vs SMAT 38.5 on Synthea (author) |
| ReMatch | Microsoft (Sheetrit et al.) | Big tech | 2024-03 | target tables as documents → embed + retrieve J candidate tables per source table → GPT-4 ranks target attributes | embeddings + GPT-4 | Acc@1 0.424 vs 0.077 (SMAT) on MIMIC-III→OMOP (author) |
| Magneto | New York University (Liu, Freire et al.) | Academia | 2024-12 | serialise columns (header + sampled values) → fine-tuned small LM retrieves top-k candidates → LLM reranks with 0–1 scores | MPNet (self-supervised on LLM-generated variants) + LLaMA3.3-70B / GPT-4o-mini | MRR 0.860 on GDC (author) |
| Unicorn | Tu, Fan, Tang et al. (Renmin University of China, QCRI) | Academia | 2023-06 | one model (shared encoder + mixture-of-experts + binary matcher) for 7 matching tasks (schema, entity, column type, entity linking) | DeBERTa-class encoder, MoE | n/a (20 datasets, supervised pretraining) |
| Jellyfish | NEC Corporation, Osaka University (Zhang et al.) | Academia + industry (NEC) | 2023-12 | instruction-tune local 7–13B models on data-preprocessing tasks (schema/entity matching, imputation) → run on single GPU | Mistral-7B, Llama-3-8B, OpenOrca-Platypus2-13B | competitive with GPT-3.5/4 (author) |
| Ditto | Megagon Labs, UW-Madison (Li et al.) | Academia + industry (Megagon Labs) | 2020-04 | record pair serialised → fine-tuned BERT/RoBERTa sequence-pair classifier with domain knowledge, summarisation, augmentation | BERT/RoBERTa | up to +29% F1 over prior SOTA (author) |
| Splink | UK Ministry of Justice data-linking team (Linacre, Lindsay, Manassis) | Open-source community | ~2020 | blocking rules → comparison levels → Fellegi–Sunter weights estimated by EM → match probabilities → clustering + clerical review | SQL backends (DuckDB, Spark, etc.) | ~2 million downloads (author) |
| MatchGPT (zero-shot LLM entity matching) | University of Mannheim (Peeters, Steiner, Bizer) | Academia | 2023-10 | record pair → zero/few-shot prompt at temperature 0 → match yes/no | GPT-4 and open LLMs | GPT-4 F1 89.61 vs Ditto 84.90 on WDC Products (author) |
| ComEM | Chinese Academy of Sciences, Alibaba (Wang et al.) | Academia + industry (Alibaba) | 2024-05 | cheap LLM filters candidates → stronger LLM selects the match among candidates for each record | 10 LLMs | selecting +16.02% F1 over pairwise matching (author) |
| LLM-CER | Zhejiang University, Aalborg University (Fu et al.) | Academia | 2025-06 | LLM clusters small record sets in-context → hierarchical cluster merging → hallucination mitigation | LLMs | up to 5x fewer API calls, up to 150% higher accuracy (author) |
| AnyMatch | University of Amsterdam, TU Berlin (Zhang, Groth, Calixto, Schelter) | Academia | 2024-09 | fine-tune small LM for zero-shot transfer entity matching | GPT-2-scale model | within 4.4% F1 of GPT-4 at 3,899x lower cost (author) |
| ReFinED | Amazon Alexa AI (Ayoola et al.) | Big tech | 2022-07 | one forward pass: mention detection → fine-grained typing → disambiguation to Wikidata | transformer encoder | >60x faster, +3.7 F1 on EL datasets (author) |
| GENRE | Facebook AI Research, UCL (De Cao et al.) | LLM lab | 2020-10 | text → seq2seq generates entity name under prefix-trie constraint → always-valid KB entity | BART | n/a |
| W3C Reconciliation Service API | W3C Entity Reconciliation Community Group | Open-source community | 2023-04 (v0.2) | local record (query, type, properties) → reconciliation service → candidates (id, name, score, match) | OpenRefine, Wikidata | n/a (protocol) |
| SEED | MIT, Renmin University (Chen, Cao, Madden, Kraska et al.) | Academia | 2023-10 | curation task → "LLM-as-compiler" builds hybrid pipeline: LLM-generated code, vector cache, small models trained on LLM labels, LLM as last resort | LLMs + generated code | matches SOTA few-shot on 9 datasets with far fewer LLM calls (author) |
| SHACL | W3C (Knublauch, Kontokostas) | Open-source community | 2017-07 | RDF data graph + shapes graph → validator → report (sh:conforms, focus node, path, failed constraint) | W3C Recommendation | n/a (standard) |
| schema.org | Bing, Google, Yahoo (later Yandex) (Guha, Brickley, Macbeth) | Big tech | 2011 | shared vocabulary of web entity types → used as class/slot URIs and enums in schemas | vocabulary | on 31.3% of 10B sampled pages (author) |

**Also covered briefly:** Map&Make (Arizona State University, 2025-05); CESI (IISc Bangalore, 2018-04 (WWW)); OLLM (University of Cambridge, 2024-10); Self-demonstrations for schema-ontology mapping (TCS Research, 2026-09); LLMatch (Singapore Management Univ., SUTD, 2025-07); Schemora (Informatica, 2025-07); Matchmaker (University of Cambridge, 2024-10); KcMF (Zhejiang University, 2024-10); Table-GPT (Microsoft, 2023-10); BDIViz (New York University, 2025-07); Harmonia (New York University, 2025-02); ZeroER (Georgia Tech, HBKU, 2019-08); BatchER (Renmin University, Tsinghua, BIT, 2023-12); ChatEL (University of Notre Dame, 2024-02); CQE (Heidelberg University, 2023-05); PG-Schema (LDBC multi-institution (universities, Neo4j, Google, Amazon, data.world), 2022-11).

## 5. Knowledge graph construction

Pipelines that build a graph as the target database, plus canonicalisation, linking and verification stages. (22 main entries, 17 brief.)

| Method | Developer | Developer type | First release | High-level flow | Tools / models | Key result |
|---|---|---|---|---|---|---|
| Microsoft GraphRAG (graph builder) | Microsoft Research (Edge et al.) | Big tech | 2024-04 | chunk into TextUnits → LLM extracts entities (title, type, description) + untyped relationships, with "gleanings" re-prompts → merge on exact title+type → LLM summarises descriptions → community detection; LLM cache, seedable clustering | GPT-4-class LLMs; FastGraphRAG NLP option | 0/100 sampled triples valid S-P-O (KGGen authors, competitor-run) |
| LightRAG (graph builder) | BUPT, HKU | Academia | 2024-10 | per chunk: LLM recognises entities/relations → LLM profiling writes key-value text → dedupe identical nodes/edges → incremental union | LLMs + vector store | n/a (as builder) |
| KGGen (+ MINE benchmark) | Stanford University, FAR AI (Mo, Yu, Kazdan et al.) | Academia | 2025-02 | per chunk: DSPy call for entities → call for relations → lower-case union → S-BERT k-means clusters → BM25+embedding top-16 → LLM picks duplicates + canonical name (alias map) | DSPy, S-BERT, LLMs | MINE-1 66.07% vs GraphRAG 47.80% (author, LLM-judged) |
| iText2KG | LIRIS CNRS, AuvaLie (Lairgi, Moncla, Cazabet) | Academia + industry (AuvaLie) | 2024-09 | Document Distiller rewrites doc to JSON blueprint → incremental entity extraction matched to global set (exact, then cosine ≥0.8) → same for relations (≥0.7) → write to Neo4j | LLM, embeddings, Neo4j | unresolved-entity FDR 0 vs 0.31 (OpenAI function calling) (author) |
| ATOM | LIRIS CNRS, AuvaLie (Lairgi, Moncla, Benabdeslem) | Academia + industry (AuvaLie) | 2025-10 | text → atomic facts → 5-tuples (s, r, o, t_start, t_end) with dual-time (observation vs validity) → parallel merge of atomic temporal KGs | gpt-4.1 | run-to-run Jaccard 0.55 vs 0.21 for whole-paragraph extraction (author) |
| SAC-KG | USTC, Alibaba (Chen, Shen, Lv et al.) | Academia + industry (Alibaba) | 2024-09 | per entity: Generator (retrieved domain text + DBpedia templates) → rule-based Verifier (RuleHub) → T5 Pruner decides expansion | ChatGPT, T5 | 89.32% precision at >1M nodes (author, GPT-4-judged) |
| GraphJudge | HKUST, Peking Univ., Huawei Cloud (Huang, Chen, Sheng et al.) | Academia + industry (Huawei) | 2024-11 | entity-centric text denoising → LLM extracts triples → LoRA-fine-tuned judge filters false triples | GPT-4o-mini, LLaMA-2-7B LoRA | G-BS-F1 0.580 vs 0.429 on REBEL-Sub (author) |
| OntoMetric | UNSW, CSIRO Data61, Adelaide (Yu, Rabhi, Xia et al.) | Academia | 2025-12 | ontology-constrained extraction with deterministic IDs → semantic type check + rule-based schema check → segment/page provenance | LLM + ontology | >80% schema compliance vs 3–10% unconstrained (author) |
| Neo4j LLM Knowledge Graph Builder | Neo4j Labs (Hunger, Bratanic, De Jong) | Data platform | ~2024 | upload → Document + Chunk nodes with embeddings, SIMILAR kNN edges → llm/diffbot graph transformer extracts entities linked to chunks → optional schema + clean-up | Neo4j, LangChain transformers, LLMs | n/a (no accuracy published) |
| LangChain LLMGraphTransformer | LangChain | Startup/vendor | ~2024 | text → LLM extracts nodes/relationships → strict_mode post-filters against allowed_nodes / allowed_relationships (source, rel, target) | LangChain, any LLM | n/a |
| Docs2KG | University of Western Australia, HIT (Sun, Luo, Zhang et al.) | Academia | 2024-06 | emails/web/PDF/Excel → layout analysis + Markdown → layout subgraph (headings, tables, images) linked to semantic subgraph | layout tools + LLM, Neo4j | n/a |
| AutoSchemaKG / ATLAS | HKUST, Huawei Theory Lab | Academia + industry (Huawei) | 2025-05 | extract entity–entity, entity–event, event–event triples → "conceptualise" instances into types (schema induction) → web-scale KG | Llama-3-8B; ~78,400 GPU-hours | 900M+ nodes, 5.9B edges; 95–100% precision judged by DeepSeek-V3 (author) |
| Datasheet KG via validated instructions | University of Michigan (Qiao, Dick) | Academia | 2026-10 | LLM proposes graph updates as validated instructions → deterministic local execution with provenance | LLM + executor | 98.8% vs 76.1% property faithfulness (author) |
| REBEL | Huang Cabot, Navigli (Sapienza University of Rome, Babelscape) | Academia + industry (Babelscape) | 2021-11 | text → seq2seq generates linearised triplets → relations aligned to Wikidata | BART | n/a (silver Wikidata dataset) |
| GenIE | EPFL, Meta AI (Josifoski, De Cao, Peyrard et al.) | Academia + industry (Meta AI) | 2021-12 | text → seq2seq with bi-level constrained generation → only triples valid under KB schema | BART + prefix tries | n/a |
| PiVe | Monash University, Univ. of Cambridge (Han, Collier, Buntine) | Academia | 2023-05 | LLM generates graph → small verifier model flags errors → iterative correction prompts | LLM + small verifier | n/a |
| Dependency-parsing KG construction | SAP (Min, Bansal, Pan et al.) | Big tech | 2025-07 | dependency parsing extracts triples (no LLM) → KG for GraphRAG | spaCy-style parser | 94% of LLM quality (61.87% vs 65.83%) at far lower cost (author) |
| DEG-RAG | Nanjing University, Mila, NTU | Academia | 2025-10 | LLM-built KG → type-aware blocking → entity resolution + triple reflection → merged graph | embeddings + LLM | ~40% fewer entities/relations, improved 4 Graph-RAG methods (author) |
| Zep / Graphiti | Zep AI (Rasmussen, Paliychuk, Beauvais et al.) | Startup/vendor | 2025-01 | episodes stored losslessly → LLM extracts entities/edges → embedding + full-text candidates → LLM ER → bitemporal edges (t_valid/t_invalid, created/expired), contradictions invalidate → writes via predefined Cypher | Neo4j, LLMs | n/a (memory benchmarks in paper) |
| ReLiK | Sapienza University of Rome (Orlando, Huguet Cabot, Barba et al.) | Academia | 2024-07 | retriever fetches candidate entities/relations → reader does EL + RE in one forward pass | retriever–reader encoders | up to 40x faster at SOTA accuracy (author) |
| LINK-KG | George Mason University (Meher, Domeniconi, Correa-Cabrera) | Academia | 2025-10 | three-stage LLM coreference with type-specific prompt cache → then KG extraction | LLMs | −45.21% node duplication on legal docs (author) |
| Maverick | Sapienza University of Rome (Martinelli, Barba, Navigli) | Academia | 2024-07 | 500M-param encoder pipeline → mention detection → coreference clustering | DeBERTa-class encoder | SOTA CoNLL-2012 at 170x faster inference (author) |

**Also covered briefly:** AutoKG (keyword graph) (UCLA, 2023-11); Graphusion (Yale University et al., 2024-07); Ontology-grounded KG under Wikidata schema (CUHK, 2024-12); ANCHOR (Incheon International Airport Corp., 2026-05); RAKG (Shanghai AI Lab, Nankai Univ. et al., 2025-04); KARMA (Peking University, Tsinghua, Georgia Tech, 2025-02); LKD-KGC (SJTU, Zhejiang Univ., Alibaba, 2025-05); InvertiTune (Huawei, McGill, 2025-12); Hyper-KGGen (Tsinghua, Xi'an Jiaotong et al., 2026-02); DIAL-KG (Northeastern University, 2026-03); SynthIE (EPFL, 2023-03); CodeKGC (Zhejiang University, Ant Group, 2023-04); Grapher (IBM Research, 2022-11); AgenticER (Univ. of Athens, 2026-07); LELA (Télécom Paris, 2026-01); KGValidator (Quantexa, 2024-04); Text2NKG (Beihang University, NTU, 2023-10).

## 6. Structured query interfaces (text-to-SQL/Cypher, semantic layers, predefined tools)

How agents query the converted store: generated SQL/Cypher/SPARQL, semantic layers that compile queries, and pre-registered parameterised tools. (24 main entries, 22 brief.)

| Method | Developer | Developer type | First release | High-level flow | Tools / models | Key result |
|---|---|---|---|---|---|---|
| DIN-SQL | University of Alberta (Pourreza, Rafiei) | Academia | 2023-04 | schema linking → query classification → SQL generation → self-correction (in-context) | GPT-4 | BIRD test 55.9 (author) |
| CHESS | Stanford University, University of Alberta (Talaei et al.) | Academia | 2024-05 | information retriever (values) → schema selector → candidate generator with refinement → unit tester (LLM-written tests) | LLMs | BIRD test 71.10% (author) |
| CHASE-SQL | Google Cloud, Stanford (Pourreza et al.) | Academia + industry (Google) | 2024-10 | diverse candidates (divide-and-conquer, query-plan CoT, synthetic examples) → fine-tuned pairwise selector | Gemini + fine-tuned selector | BIRD test 73.0% (author) |
| XiYan-SQL | Alibaba (XGenerationLab) (Gao et al.) | Big tech | 2024-11 | M-Schema serialisation → multi-generator ensemble (fine-tuned + ICL) → refiner → fine-tuned selector | fine-tuned + ICL LLMs | BIRD 75.63%, Spider test 89.65% (author) |
| OmniSQL | Renmin University, ByteDance (Li et al.) | Academia + industry (ByteDance) | 2025-03 | synthesise SynSQL-2.5M (16k synthetic DBs, CoT) → fine-tune open 7B/14B/32B models | Qwen2.5-Coder base | matches/beats GPT-4o across 9 datasets (author) |
| Arctic-Text2SQL-R1 | Snowflake AI Research (Yao et al.) | Data platform | 2025-05 | RL (GRPO) with execution-correctness-only reward → open text-to-SQL models | Qwen2.5-Coder 7B–32B | 7B beats prior 70B systems; BIRD #1 at release (author) |
| ReFoRCE | Snowflake AI Research, UCSD (Deng et al.) | Data platform | 2025-02 | table grouping + LLM schema linking (compression) → dialect-aware self-refinement → majority-vote consensus, defer low confidence → execution-guided column exploration | LLM agent | Spider 2.0-Snow 35.83 (author) |
| FLINT | Kensho Technologies (S&P Global) (Sehanobish et al.) | Startup/vendor | 2026-10 | lookup agent resolves opaque keys → retrieve expert-authored query templates → FK-chain schema linking → SQL | LLM agents | general methods <50% on these schemas; deployed in production (author) |
| Automatic metadata extraction for text-to-SQL | AT&T (Shkapenyuk et al.) | Big tech | 2025-05 | profile database + mine query logs (join constraints) → LLM-written metadata → schema linking → SQL | GPT-4o | BIRD MiniDev 49.8% → 63.2% with fused metadata (author) |
| SNAILS natural views | UC San Diego ADA Lab (Luoma, Kumar) | Academia | 2025 | measure identifier naturalness → expose natural-name views over native schema → text-to-SQL | evaluation over 9 DBs incl. SAP B1 | renaming helps when naturalness <0.69 (author) |
| CypherBench property-graph views | Megagon Labs (Feng et al.) | Startup/vendor | 2024-12 | RDF KG (Wikidata) → domain property-graph views with readable labels → text-to-Cypher; PSJS metric | LLMs, Neo4j | claude-3.5-sonnet 61.58% EX zero-shot (author benchmark) |
| Text2Cypher dataset | Neo4j (Ozsoy et al.) | Data platform | 2024-12 | combine, clean, syntax-validate 16 public datasets (44,387 pairs) → fine-tune text-to-Cypher models | Neo4j, LLMs | fine-tuning improves exact match (author) |
| SPARQL-LLM | SIB Swiss Institute of Bioinformatics (Smeros et al.) | Academia | 2025-12 | index example queries + schema metadata → RAG prompt → generate SPARQL → validate against schema | LLMs; deployed at expasy.org/chat | up to 59% higher F1 than 2nd-best Text2SPARQL system, ≤$0.01/question (author) |
| Ontology + R2RML KG for enterprise QA (data.world) | data.world (Sequeda, Allemang, Jacob) | Startup/vendor | 2023-11 | SQL schema mapped to OWL ontology via R2RML → LLM writes SPARQL over KG instead of SQL | GPT-4 | 54% vs 16% for direct SQL (author) |
| Ontology-based Query Check (OBQC) + repair | data.world (Allemang, Sequeda) | Startup/vendor | 2024-05 | generated SPARQL → check domain/range against ontology → LLM repair or "I don't know" | GPT-4 + ontology rules | 72% accuracy incl. 8% abstentions (author) |
| dbt Semantic Layer / MetricFlow | dbt Labs | Data platform | ~2023-10 | YAML semantic models (entities, dimensions, metrics) → semantic graph infers joins → LLM selects metric + dimensions + filters → MetricFlow compiles deterministic SQL | dbt, MetricFlow | 98.2–100% vs 84–90% text-to-SQL on 11 questions (vendor) |
| PyDough | Bodo.ai | Startup/vendor | n/a | offline column profiling → LLM writes PyDough DSL over logical graph of collections → compiles to SQL (no LLM joins) → 3 candidates + consensus/judge | PyDough, LLMs | 100% (220/220 runs) on dbt's 11 questions (vendor) |
| Cube semantic layer + Delphi | Cube | Startup/vendor | 2023-12 | LLM issues Cube REST queries (metrics, dimensions, filters) instead of SQL → Cube generates SQL | Cube, LLM | 100% over 5 runs on data.world subset (vendor) |
| Apache Ossie (formerly OSI) | Open Semantic Interchange coalition (50+ orgs) | Open-source community | 2025-11 (repo) | vendor-neutral YAML/JSON semantic-model spec → converters (dbt, GoodData, Polaris, Salesforce) → Python SDK | JSON schema, ontology; Apache-2.0 | n/a (spec) |
| GROUND | Cox Automotive (author affiliation) (Pillai) | Startup/vendor | 2026-07 | constrain generation to governed metrics, joins, filters, RLS → validate SQL against schema/metric/join/grain/security/cost rules → retry or abstain | LLM + rule validator | zero measured hallucinations on 100-question benchmark (author) |
| Domain-Oriented Tooling Pattern (MCP) | unverified (single author, Bogliolo) (Bogliolo) | unverified | 2026-08 | model picks among domain tools whose parameterised SQL encodes joins/business rules → execute | MCP, 3B–8B local models | 0.939 vs 0.666 raw SQL (author) |
| Google MCP Toolbox for Databases | Google | Big tech | ~2025-02 | tools.yaml defines tools (source, parameters, parameterised SQL) → agents call via MCP; plus execute_sql/list_tables | MCP, connection pooling, IAM, OpenTelemetry | n/a |
| Execution-guided decoding | Microsoft Research (Wang et al.) | Big tech | 2018-07 | execute partial SQL during decoding → discard faulty candidates | seq2seq SQL models | WikiSQL 83.8% (author) |
| PICARD | ElementAI (a ServiceNow company) (Scholak et al.) | Big tech | 2021-09 | incremental SQL parser rejects inadmissible tokens during beam search → always-valid SQL | T5 | n/a |

**Also covered briefly:** DAIL-SQL (Alibaba Group, 2023-08); MAC-SQL (Beihang University, Tencent Youtu Lab, 2023-12); Alpha-SQL (HKUST-GZ, Renmin Univ., Huawei, 2025-02); Reasoning-SQL (Google Cloud, Stanford, 2025-03); HarnessSQL (Microsoft Research, Tsinghua, HKUST, 2026-10); ReViSQL / BIRD-Platinum (UIUC, Bridgewater AIA Labs, 2026-03); "Death of Schema Linking" (Distyl AI, 2024-08); Synthetic column descriptions (Linköping University, 2024-08); EGRefine (Xidian University, 2026-05); Schema-free text-to-SQL via query-log KG (USC, Amazon, 2026-10); Auto-Cypher (SynthCypher) (ServiceNow, 2024-12); KG2Cypher (Sungkyunkwan Univ., NAVER, 2026-06); mKGQAgent (Leipzig Univ. of Applied Sciences, Paderborn Univ., 2025-07); GGC selective SPARQL repair (A*STAR, NTU Singapore, 2026-07); AtScale semantic layer NLQ (AtScale, 2024-11); GATE (Seoul National University, 2026-06); Agentic schema refinement (Northeastern University, RelationalAI, 2024-11); FinAI Data Assistant (Mirae Asset, Meritz (Korea), 2025-10); StructGPT (Renmin University of China, 2023-05); Self-Debugging (Google DeepMind, UC Berkeley, 2023-04); LogicalBeam (AmbiQT) (IIT Bombay, 2023-10); PlanPool (Cornell University, Amazon, 2026-10).

## 7. Hybrid structured/unstructured retrieval

Systems that combine typed stores with text retrieval, routers that choose between them, and the deterministic properties of the retrieval primitives. (23 main entries, 16 brief.)

| Method | Developer | Developer type | First release | High-level flow | Tools / models | Key result |
|---|---|---|---|---|---|---|
| StructRAG | Chinese Academy of Sciences, Alibaba Tongyi | Academia + industry (Alibaba) | 2024-10 | question + docs → DPO-trained router picks structure (table, graph, algorithm, catalogue, chunk) → structurizer LLM rewrites docs into it → utilizer answers | Qwen2-7B router, Qwen2-72B | Loong set 1: 69.43 vs 46.11 chunk RAG (author, LLM-judged) |
| SRAG | HKUST (Guangzhou) | Academia | 2025-03 | SPARQL over Wikidata finds entity set → GPT-4 proposes table schema → LLM fills one row per entity from pages → GPT-4 writes SQL | GPT-4, Wikidata, SQL | MEBench 0.889 vs 0.593 GPT-4+RAG (author) |
| Binder | HKU, Meta AI, Allen AI, Salesforce, Yale | Academia + industry (Meta AI, Salesforce) | 2022-10 | question + table → Codex writes SQL/Python with embedded LM calls → execute | Codex | SOTA on WikiTQ, TabFact with dozens of exemplars (author) |
| Chain-of-Table | Google Cloud AI Research, Google Research | Big tech | 2024-01 | table → LLM plans chained table operations (add column, select rows, group) → evolving table → answer | PaLM 2 / GPT-3.5 | SOTA on WikiTQ, FeTaQA, TabFact at publication (author) |
| TableRAG (million-token tables) | Google Cloud AI Research, National Taiwan Univ. (Chen et al.) | Academia + industry (Google) | 2024-10 | query expansion → schema-level + cell-level retrieval → LLM reasons over retrieved schema/cells instead of whole table | LLMs | SOTA on two new million-token benchmarks (author) |
| TableRAG (heterogeneous documents) | Huawei (Yu et al.) | Big tech | 2025-06 | keep tables as MySQL tables + text KB → loop: decompose query → text retrieval → SQL generation and execution → intermediate answer | MySQL, Claude-3.5 etc. | HeteQA 44.19 vs NaiveRAG 34.54 (author) |
| NeuSym-RAG | Shanghai Jiao Tong University | Academia | 2025-05 | parse PDFs into DuckDB (metadata, sections, tables) + multi-view vector store → agent iterates RetrieveFromDatabase (SQL) / RetrieveFromVectorstore actions | DuckDB, vector store, LLM agent | AirQA-REAL 39.6 vs 10.5 classic RAG (author) |
| UniK-QA | Meta AI | LLM lab | 2020-12 | verbalise text, tables, lists, KB triples to text → one dense retriever-reader | DPR + FiD | +11 points on KBQA over graph methods (author) |
| IE→SQL reference pipeline (QO-Bench) | NUS, NTU (Zhang et al.) | Academia | 2026-06 | news articles → extract typed event tuples → SQL answers operator queries; benchmark scores by exact match | LLM extractor + SQL | intersection recall 50.9 vs 6.0 for RAG (indep. comparison) |
| DFA (Disambiguation–Filtering–Aggregation) | Southeast Univ., Imperial College, Manchester | Academia | 2026-02 | "find all" question → disambiguate entities → filter evidence → aggregate | LLM pipeline | evidence recall 0.211 vs 0.008 naive RAG on AGGBench (author) |
| DualGraph | Samsung AI | Big tech | 2026-05 | specs → symbolic KG (typed triples, SPARQL) + text KG → LLM router → symbolic first, text fallback on failure | SPARQL store, LLM router | FC F1 0.298 vs 0.092 vector RAG; 16M vs 181M indexing tokens vs GraphRAG (author) |
| HybGRAG | CMU, Amazon | Academia + industry (Amazon) | 2024-12 | LLM extracts topic entities/subgraph → text + graph retrieval → critic feedback iterates | LLM + graph PPR + vector search | +51% relative Hit@1 on STaRK (author) |
| Cheapest-first escalation cascade (Coverage Illusion) | Aarhus University | Academia | 2026-05 | run cheapest retrieval step → escalate to LLM query augmentation only when no documents return | production search stack | +0.140 quality, −31.8% latency (indep., production) |
| Self-Route | Google DeepMind, Univ. of Michigan | LLM lab | 2024-07 | try RAG → model self-reflects whether answerable → else route to long context | Gemini-1.5-Pro, GPT-4o | −65% cost at comparable quality (author) |
| Adaptive-RAG | KAIST | Academia | 2024-03 | small classifier predicts complexity → no-retrieval / single-step / multi-step strategy | T5 classifier + LLM | n/a |
| HybridRAG (KG + vector) | NVIDIA, BlackRock | Big tech | 2024-08 | retrieve from KG and vector store → combine contexts → LLM answer | KG + vector DB | beats either alone on earnings calls (author) |
| A.DOT | IBM Research India | Big tech | 2026-03 | NL question → DAG plan over SQL + document stores → structural/semantic validation → execute → cache plan via paraphrase-aware templates → lineage | LLM planner | n/a (no numbers in abstract) |
| Contextual Retrieval | Anthropic | LLM lab | 2024-09 | LLM prepends chunk-specific context → contextual BM25 + contextual embeddings → rerank | Claude, BM25, embeddings | −49% failed retrievals, −67% with reranking (vendor) |
| ACORN | Stanford, UC Berkeley | Academia | 2024-03 | predicate-agnostic filtered HNSW (denser graph, predicate-aware traversal) → structured filter + vector search | HNSW | 2–1,000x throughput at fixed recall (author) |
| ParlayANN | CMU, Microsoft Research, UMD | Academia + industry (Microsoft) | 2023-05 | deterministic, lock-free parallel graph-ANN build algorithms | C++ ParlayLib | billion-scale deterministic builds (author) |
| pgvector | pgvector open-source project (Kane) | Open-source community | ~2021-04 | Postgres extension: exact kNN by default (perfect recall) → optional HNSW/IVFFlat ANN; iterative scans (0.8.0) for filtered queries | PostgreSQL | n/a |
| FAISS | Meta AI Research (FAIR) | LLM lab | ~2017-02 | vector index (flat, IVF, HNSW, PQ) → search; seeds fixed, same-thread-count runs reproducible except HNSW add order | C++/Python, GPU | n/a |
| Pyserini | University of Waterloo | Academia | 2021-02 | prebuilt indexes + pinned BM25/dense/hybrid baselines → regression-tested reproducible runs | Lucene/Anserini, FAISS | n/a |

**Also covered briefly:** Dater (Alibaba DAMO, USTC, 2023-01); TabSQLify (University of Alberta, 2024-04); ReAcTable (UW-Madison, Microsoft, 2023-10); H-STAR (Arizona State, Virginia Tech, UPenn, 2024-06); Weaver (Arizona State, UPenn, 2025-05); UDT-QA (Microsoft Research, CMU, 2021-10); TAGOP (TAT-QA) (NUS, 6Estates, 2021-05); Join-Aware Retrieval (JAR) (AWS AI Labs, MIT, 2024-04); ARM (MIT, AWS AI, 2025-01); OpenTab (UMD, Amazon Web Services, 2024-02); RouterRetriever (KAIST, Yale, Allen AI, 2024-09); R³AG (Renmin University, SCUT, 2026-04); HC-RAG (Sun Yat-sen Univ., Central South Univ., 2026-06); MoR (Mixture of Structural and Textual Retrieval) (Michigan State, Adobe Research, 2025-02); Blended RAG (IBM, 2024-03); CHASE (hybrid relational/vector engine) (Fudan University, Transwarp, 2025-01).

## 8. Data quality, versioning, provenance, determinism

Validation, confidence and review, deterministic inference, data versioning, lineage and provenance standards, and evaluation metrics. (29 main entries, 18 brief.)

| Method | Developer | Developer type | First release | High-level flow | Tools / models | Key result |
|---|---|---|---|---|---|---|
| Deequ | Amazon (Schelter, Lange, Schmidt et al.) | Big tech | 2018 | declare constraints (completeness, uniqueness, range, satisfiesIf cross-field) → compile to Spark aggregation queries → incremental validation on deltas → anomaly detection on metric history | Apache Spark | incremental beats batch after 3–4 deltas on 120M records (author) |
| TFX Data Validation (TFDV) | Google (Breck, Polyzotis, Roy et al.) | Big tech | 2019 | infer schema → humans curate + version it → validate each batch → inter-batch drift/skew detection → propose schema edits | TensorFlow Extended | >700 production pipelines; 53–100% of fired anomalies fixed (author) |
| Great Expectations | Great Expectations | Startup/vendor | ~2018 | declare "Expectations" (not null, regex, unique, row counts) → validate batches → data docs | Python | 50+ built-in expectations (vendor docs) |
| SPADE | UC Berkeley, LangChain (Shankar et al.) | Academia + industry (LangChain) | 2024-01 | mine prompt version history → each added instruction = failure mode → synthesise candidate assertions → select minimal set meeting coverage/accuracy | LLM + LangSmith | −21% false failures, −14% assertions (author) |
| EvalGen | UC Berkeley (Shankar et al.) | Academia | 2024-04 | LLM proposes criteria + implementations (code or LLM grader) → humans grade sample → keep evaluators aligned with grades | LLMs + UI | n/a (finds "criteria drift") |
| MiniCheck | UT Austin, Salesforce AI Research (Tang, Laban, Durrett) | Academia + industry (Salesforce) | 2024-04 | synthetic GPT-4 training data → small fact-checker scores whether claim is grounded in source | Flan-T5 770M etc. | GPT-4-level on LLM-AggreFact at ~400x lower cost (author) |
| FActScore | UW, UMass, Meta AI, Allen AI (Min, Krishna, Lyu et al.) | Academia + industry (Meta AI) | 2023-05 | output → atomic facts → check each against knowledge source → fraction supported | LLM decomposer + retrieval | automated estimator <2% error vs human (author) |
| Self-verification for clinical IE | Microsoft Research (Gero, Singh, Cheng et al.) | Big tech | 2023-05 | LLM extracts value → produces provenance span → checks/prunes its own output | GPT-3.5/4 | consistent accuracy gains across LLMs (author) |
| ExtractConf (multi-signal confidence engine) | Perfios Software Solutions (Kumar) | Startup/vendor | 2026-06 | two structurally different extraction calls (Hunter, Mapper) → disagreement + LLM uncertainty + OCR/image/layout features → classifier → field confidence | LLMs + classifier | 99.1% accuracy at 80% coverage on DocILE (author) |
| Conformal prediction / risk control | UC Berkeley (Angelopoulos, Bates et al.) | Academia | 2021-07 | labelled calibration set → score threshold → prediction sets or abstention with distribution-free coverage (risk control bounds any monotone loss) | model-agnostic | finite-sample guarantee, e.g. 90% coverage (theory) |
| Conformal medical entity extraction | Drexel University (Shrestha, Kim) | Academia | 2026-03 | LLM extracts entities → FactScore-style verification scores → per-domain conformal threshold → reject below | GPT-4.1, Llama-4-Maverick | ≥90% coverage at 9–13% rejection (author) |
| Batch-invariant inference kernels | Thinking Machines Lab (He) | Startup/vendor | 2025-09 | replace kernels whose results depend on batch size (matmul, attention, RMSNorm reductions) with batch-invariant versions → identical temperature-0 outputs | vLLM, custom kernels | 1,000/1,000 identical vs 80 unique outputs, at 1.6–2.1x slower (author) |
| CoRun | Peking University, Nanjing University (Zhao, Yang, Chen et al.) | Academia | 2026-08 | isolate prefill + fixed-shape (padded) batched decode → determinism without batch-invariant kernels | serving engine | 15–324% higher throughput than batch-invariant approaches (author) |
| Vosti | Duke University (Qin, Du, Zhang) | Academia | 2026-09 | formal spec of deterministic inference (bitwise-identical logits) → formally verified engine | verified inference engine | finds vLLM/SGLang deterministic modes differ under some variations (author) |
| Apache Iceberg (snapshots, branching, schema evolution) | Netflix → Apache Software Foundation | Open-source community | ~2018 | every write = snapshot → VERSION/TIMESTAMP AS OF time travel → branches/tags retain snapshots → ID-based metadata-only schema evolution | Spark, Trino, Flink | n/a |
| Delta Lake | Databricks (Armbrust, Das, Sun et al.) | Data platform | ~2019-04 | ACID transaction log in object store → time travel, rollback, DESCRIBE HISTORY audit | Spark | n/a |
| lakeFS | Treeverse | Startup/vendor | ~2020 | Git-like branches over object store → zero-copy branch → commit = reproducible point → pre-merge hooks (write-audit-publish) → atomic merge | object stores | n/a |
| Project Nessie | Dremio-originated open-source project | Open-source community | ~2020 | transactional catalog with Git-like branches/tags → cross-table atomic commits for Iceberg | Iceberg | n/a |
| DVC | Iterative | Startup/vendor | ~2017 | dvc.yaml pipeline stages → dvc.lock records dependency/output hashes → invalidate and reproduce changed stages | Git + remote storage | n/a |
| Provenance semirings (how-provenance) | UPenn (Green, Karvounarakis, Tannen) | Academia | 2007-06 | annotate tuples with semiring elements → union adds, join multiplies → query results carry provenance polynomials over source tuples | theory (K-relations) | n/a (theory) |
| GraphRAGProv | Inria (El Amrani, Galárraga) | Academia | 2026-10 | source-grounded RDF graph → SPARQL answers return how-provenance polynomials over statement occurrences | SPARQL engine | exposed errors in 400 multi-hop cases even when answers were correct (author) |
| OpenLineage | OpenLineage project (LF AI & Data) | Open-source community | ~2021 | jobs/runs/datasets events with facets (schema, version, dataQualityAssertions, column lineage) → lineage backend | Marquez, Airflow, Spark integrations | n/a (spec) |
| W3C PROV-O | W3C Provenance Working Group (Lebo, Sahoo, McGuinness) | Open-source community | 2013-04 | Entity / Activity / Agent with wasGeneratedBy, wasDerivedFrom, used → provenance graph | RDF/OWL | n/a (standard) |
| ALCE citation metrics | Princeton University (Gao et al.) | Academia | 2023-05 | generated statements + citations → NLI (TRUE T5-11B) scores citation recall and precision | TRUE NLI model | best models lacked full citation support 50% of time on ELI5 (author) |
| Object Aligner | unverified (single author, Drchal) (Drchal) | unverified | 2026-07 | JSON/graph output vs gold → recursive tree alignment (Hungarian for sets) + Weisfeiler-Leman ID bijection → deterministic score + repair hints | metric | n/a (deterministic by design) |
| KG accuracy estimation by sampling | Amazon, Duke University (Gao, Li, Xu et al.) | Academia + industry (Amazon) | 2019-07 | cluster / two-stage / stratified sampling of triples → human annotation → bounded accuracy estimate | sampling estimators | up to 60% (static) / 80% (evolving) less annotation (author) |
| RDF 1.2 triple terms and reifiers | W3C RDF & SPARQL Working Group | Open-source community | 2026-04 (CR) | statement as triple term → reifier node (rdf:reifies) carries provenance/time annotations | RDF/SPARQL | n/a (standard) |
| SQL:2011 temporal tables | ISO SQL committee (described by Kulkarni, Michels) | Open-source community | 2011 | application-time period tables + system-versioned tables → valid-time and transaction-time queries | SQL engines | n/a (standard) |
| PRISM schema modification operators | UCLA (Curino, Moon, Zaniolo) | Academia | 2008 | schema changes expressed as SMOs → impact analysis → automatic query rewriting + data migration | relational DBs | validated on Wikipedia's 170+ schema versions (author) |

**Also covered briefly:** Pandera (Bantilan, 2020); AlignScore (UC San Diego, 2023-05); VALID framework (Flatiron Health, 2025-06); BSDetector (Cleanlab, 2023-08); Semantic entropy (University of Oxford, 2023-02); Conformal factuality (Stanford University, 2024-02); CoAnnotating (NUS, A*STAR, Stanford, 2023-10); Snorkel (weak supervision) (Stanford University, 2017-11); GAIDA (DFKI, 2026-10); TP-invariant kernels (Univ. of Minnesota, Rice, NVIDIA, 2025-11); Compatibility adapters for model updates (UC San Diego, Apple, 2024-07); Selective fallback on model updates (University of Ottawa, Vector Institute, 2026-08); OrpheusDB (UIUC, Peking University, 2017-03); DataHub (dataset version control) (UMD, MIT, UIUC, 2014-09); Explain-Da-V (Northeastern University, 2023-01); Smoke (Columbia University, 2018-01); AIS / AutoAIS (Google Research, 2021-12); ANLS* (DeepOpinion, 2024-02).

## 9. Semi-structured and multimodal source methods

Source-specific methods for spreadsheets, HTML, emails/clinical/financial text, scientific literature, audio, charts and logs. (26 main entries, 13 brief.)

| Method | Developer | Developer type | First release | High-level flow | Tools / models | Key result |
|---|---|---|---|---|---|---|
| TableSense | Microsoft Research Asia (Dong, Liu, Han et al.) | Big tech | 2019-01 (AAAI) | spreadsheet cell grid featurised like an image → CNN detects table regions → active learning | CNN | 91.3% recall / 86.5% precision (EoB-2) (author) |
| SpreadsheetLLM (SheetCompressor) | Microsoft (Dong et al.) | Big tech | 2024-07 | sheet → structural-anchor extraction + inverted-index translation + format-aware aggregation (24.8x fewer tokens) → LLM detects tables / answers (Chain-of-Spreadsheet) | fine-tuned GPT-4, Llama3, Mistral | table-detection F1 0.789 vs 0.666 TableSense (author) |
| Pytheas | Christodoulakis, Munson, Gabel et al. (University of Toronto) | Academia | 2020 | messy CSV → rule/pattern line classification (header, data, metadata) + column coherency → table discovery | rules, trained weights | >95.9% precision, >95.7% recall on 4,500 open-data CSVs (author) |
| CERES | Amazon, University of Washington (Lockard, Dong, Einolghozati et al.) | Academia + industry (Amazon) | 2018-04 | align existing KB facts to DOM nodes (distant supervision) → learn per-site wrapper → extract new facts | distantly supervised classifier | 1.25M facts at 90% precision from >400k pages (author) |
| AutoScraper | Fudan University (Huang, Gu, Peng et al.) | Academia | 2024-04 | 3 seed pages → LLM generates XPath action sequence top-down, backtracks on failure → LLM picks most generalisable program → replay on site | GPT-4-Turbo etc. | 71.56% of SWDE tasks fully correct (GPT-4-Turbo, author) |
| BardeenAgent (WebLists) | Bardeen, UC Berkeley (Bohra, Saroyan, Melkozerov et al.) | Academia + industry (Bardeen) | 2025-04 | agent navigates and extracts → execution recorded as replayable program with generalisable CSS selectors → replay for full dataset | LLM web agent | 66% vs 31% recall for SOTA web agents (author) |
| AXE | Cairo University (Mansour, Alshaer, Elsaban et al.) | Academia | 2026-02 | prune DOM boilerplate → 0.6B LLM generates structured output → Grounded XPath Resolution ties each value to a node | 0.6B LLM | zero-shot SWDE F1 88.1% (author) |
| TURL | Ohio State University, Google Research (Deng, Sun, Lees et al.) | Academia + industry (Google) | 2020-06 | relational web tables → structure-aware transformer pretraining (masked entity recovery) → entity linking, column typing, relation extraction | transformer | improves 6 table-understanding tasks (author) |
| MIMIC-Note-Extract | TU Munich, Imperial College (Schwethelm, Kuntzer, Ketzer et al.) | Academia | 2026-11 | discharge summary → deterministic section parsing → schema-guided LLM per section → physician validation → tables | LLMs | >92% accuracy across sections on 300,720 notes (author) |
| ChemDataExtractor (1.x / 2.0) | University of Cambridge (Swain, Cole; Mavračić et al.) | Academia | 2016 | tokenise → POS + chemical NER → phrase-grammar parsing → document-level resolution across text/tables/captions; 2.0 autopopulates nested ontologies | rule/grammar NLP; MIT | battery DB: 80.0% precision, 59.1% recall on 292k records (author) |
| Inorganic synthesis-recipe text mining | UC Berkeley / LBNL Ceder group (Kononova, Huo, He et al.) | Academia | 2019 | paragraph classifier (random forest) → BiLSTM-CRF material roles → operation classifier → regex conditions → SymPy reaction balancing | BiLSTM-CRF, SymPy | 28% of paragraphs yield balanced reaction; 51% full-recipe accuracy (author) |
| MaterialsBERT polymer pipeline | Georgia Tech (Shetty, Rajan, Kuenneth et al.) | Academia | 2022-09 | abstracts → MaterialsBERT NER → heuristic relation rules → property records → polymerscholar.org | MaterialsBERT | ~300k records from ~130k abstracts in 60 h (author) |
| Polymer LLM extraction pipeline | Georgia Tech Ramprasad group (Gupta, Mahmood, Shetty et al.) | Academia | 2024 | 2.4M articles → heuristic + NER paragraph filter → GPT-3.5 / LlaMa-2 extract property records | GPT-3.5, LlaMa-2, MaterialsBERT | F1 0.85 bandgap / 0.67 Tg (GPT-3.5, author); >1M records |
| ChatExtract | University of Wisconsin-Madison (Polak, Morgan) | Academia | 2023-03 | sentence relevance filter → passage (title + previous + target sentence) → single/multi-value extraction → redundant yes/no follow-up verification → unit normalisation | GPT-4 (pinned gpt-4-0314) | 90.8% precision / 87.7% recall on bulk modulus (author) |
| ChemPrompt (MOF synthesis with ChatGPT) | UC Berkeley (Zheng, Zhang, Borgs et al.) | Academia | 2023-06 | filter synthesis paragraphs → engineered ChatGPT prompts → tabulate 26,257 synthesis parameters | ChatGPT | 90–99% precision/recall/F1 (author) |
| OpenChemIE | MIT (Fan, Qian, Wang et al.) | Academia | 2024-04 | text + tables + figures → specialised models for molecules, reactions, R-groups → aligned reaction records | multimodal chemistry models | 69.5% end-to-end F1 on R-group schemes (author) |
| PubTator 3.0 | NCBI/NLM (Wei, Allot, Lai et al.) | Academia | 2024-01 | weekly: PubMed/PMC text → NER + entity normalisation + relation extraction → searchable annotations + APIs | AIONER, BioREx-style models | >1B annotations over 36M abstracts (author) |
| TrialMind | UIUC (Wang et al.) | Academia | 2024-06 | systematic review: search → screening → data extraction with LLM → human verification | LLMs | +23.5% accuracy, 63.4% time saved with human+AI (author) |
| EviStreams | University of Pennsylvania et al. (Kosuri, Bhosale, Glick et al.) | Academia | 2026-09 | typed field definitions → LLM extraction with supporting passage per value → blinded dual review + adjudication | frontier LLMs | field spec matters more than model choice (author) |
| Whisper | OpenAI (Radford et al.) | LLM lab | 2022-09 (release; arXiv 2022-12) | audio → encoder-decoder transformer trained on 680k h weakly supervised audio → transcript | Whisper models | approaches supervised SOTA zero-shot (author) |
| WhisperX | University of Oxford (Bain, Huh, Han et al.) | Academia | 2023-03 | VAD segmentation → batched Whisper ASR → forced phoneme alignment → word-level timestamps (+ diarisation) | Whisper, wav2vec2 alignment | 12x speedup with VAD batching (author) |
| DePlot | Google DeepMind, Univ. of Cambridge (Liu, Eisenschlos, Piccinno et al.) | LLM lab | 2022-12 | chart image → plot-to-table translation model → linearised table → LLM reasons | Pix2Struct-based model + LLM | PlotQA RMS-F1 94.2; ~78% out-of-domain (author) |
| MatCha | Google DeepMind, Univ. of Cambridge (Liu, Piccinno, Krichene et al.) | LLM lab | 2022-12 | Pix2Struct pretraining on chart derendering + math reasoning → fine-tune chart QA | Pix2Struct | up to ~20% over prior SOTA on PlotQA/ChartQA (author) |
| Drain | CUHK (He, Zhu, Zheng et al.) | Academia | 2017 | log line → fixed-depth parse tree (length, leading tokens) → match/create template → template ID + parameters | online parser | FGA ~0.75 → ~0.55 on Loghub-2.0 (indep. re-evaluation) |
| LILAC | CUHK, Sun Yat-sen University (Jiang, Liu, Chen et al.) | Academia | 2023-10 | log line → check adaptive parsing cache → on miss, LLM ICL with hierarchical demo sampling generates template → store/refine in cache | LLM + template cache | +69.5% template-accuracy F1 over SOTA (author) |
| SOMEF | USC ISI / UPM (Mao, Garijo, Fakhraei) | Academia | 2019 | README + repo → supervised classifiers, header analysis, regexes, GitHub/GitLab APIs, package-file parsers → metadata with per-field technique + confidence | Python | n/a |

**Also covered briefly:** SQuARE (S&P Global, 2025-12); SheetBrain (Microsoft Research, Brown Univ. et al., 2025-10); FreeDOM (USC, Google, 2020-10); MarkupLM (Microsoft Research Asia, 2021-10); NEXT-EVAL (Wordbricks, 2025-05); LLM product attribute extraction (WDC-PAVE) (University of Mannheim, 2024-03); FiNER / SEC-BERT (Athens Univ. of Economics and Business, 2022-03); MatSciBERT (IIT Delhi, 2021-09); DiSCoMaT (IIT Delhi, 2022-07); Eunomia (University of Toronto, 2023-12); LEADS (UIUC, NIH, 2025-01); UniChart (York University, NTU Singapore, Salesforce, 2023-05); ChartAssistant (Shanghai AI Lab, HKU, Nanjing Univ., 2024-01).

## 10. Enterprise cloud platform features

Hyperscaler and data-platform product features (status as reported in the notes, Nov 2026). Most products publish no accuracy figures. (29 main entries, 2 brief.)

| Method | Developer | Developer type | First release | High-level flow | Tools / models | Key result |
|---|---|---|---|---|---|---|
| Snowflake AI_PARSE_DOCUMENT | Snowflake | Data platform | n/a (AGENTIC mode preview 2026-10) | staged file → OCR / LAYOUT (Markdown with tables) / AGENTIC (charts, diagrams) → JSON with page indexes | Snowflake Cortex | ~39.6% exact table reconstruction vs 32% Textract on 50 financial docs (vendor) |
| Snowflake AI_EXTRACT (arctic-extract) | Snowflake | Data platform | n/a (scores GA 2026-05) | text or file + JSON schema / questions → arctic-extract → string-typed fields, tables, optional 0–1 per-field scores; AI_CLASSIFY routes doc types | arctic-extract (fine-tunable) | n/a (no accuracy claim; ~$12/1k 3-page invoices, third-party estimate) |
| Snowflake Document AI / Arctic-TILT (legacy) | Snowflake (Snowflake) | Data platform | 2024-08 | annotate docs → fine-tune Arctic-TILT per use case → !PREDICT with per-field confidence → SME review; decommissioned 2026-03 | Arctic-TILT (<1B params, 400k-token docs) | SOTA on 7 benchmarks at ~1,000x smaller size (vendor paper) |
| Snowflake semantic views + Cortex Analyst | Snowflake | Data platform | ~2024-08 | semantic view (logical tables, joins, metrics, verified queries) → Cortex Analyst LLM text-to-SQL under caller's RBAC → SQL in warehouse | Cortex LLMs | "90%+" vs 51% single-prompt GPT-4o on internal 150-question set (vendor) |
| Databricks ai_parse_document | Databricks | Data platform | ~2025-11 (GA 2026-04) | binary doc → VARIANT pages + elements (type, content, confidence, bbox, page_id) → Delta table in Spark Declarative Pipelines | Databricks-hosted models | ~20% better than Azure CU on matched RAG A/B (indep., Factored) |
| Databricks ai_extract v2.1 | Databricks | Data platform | n/a | parsed doc or text + typed JSON schema (12 levels, 256 fields) → typed validated values + per-field confidence + citations to spans/bboxes | Databricks-hosted LLMs | n/a ($2.10–$4.20 per 1k inputs list price) |
| Databricks Agent Bricks Information Extraction | Databricks | Data platform | ~2025-06 | unlabeled text → auto JSON schema → reviewer feedback → batch via ai_query / Lakeflow → quality evaluation | Agent Bricks | 92–95% tagging accuracy at YipitData (customer-reported) |
| Databricks Genie (trusted assets) | Databricks | Data platform | ~2024-06 | UC metadata + knowledge store + example queries → read-only NL2SQL; trusted assets (verified parameterised queries/functions) answer matching questions | Unity Catalog | n/a |
| Google Document AI Custom Extractor | Google Cloud | Big tech | 2024-01 (generative GA) | define schema → generative (0–50 docs), custom (10–100) or template (~3) model → fields with 0–1 confidence → CEL validation rules (preview) | Gemini-based processors | n/a ($30 per 1k pages list) |
| Google Document AI Layout Parser | Google Cloud | Big tech | n/a | document → tree-structured DocumentLayout (headings, paragraphs, tables, figures) → context-aware chunks with ancestor headings | Document AI, Gemini versions | n/a ($10 per 1k pages list) |
| BigQuery AI.GENERATE_TABLE / AI functions | Google Cloud | Big tech | 2025-04 (GA 2025-11) | table or ObjectRef column + prompt + typed output_schema → Gemini per row → typed columns + status; AI.IF/AI.SCORE/AI.CLASSIFY/AI.AGG as SQL operators | Gemini, BigQuery | n/a (failed rows become NULL) |
| BigQuery AI.PARSE_DOCUMENT + ObjectRef | Google Cloud | Big tech | 2026-11 (GA) | GCS objects → ObjectRef STRUCT columns → Document AI layout parser → structured JSON (titles, tables, images) in SQL | Document AI | n/a |
| BigQuery / Gemini Enterprise data agents (verified queries) | Google Cloud | Big tech | n/a (publish to Gemini Enterprise GA 2026-10) | knowledge sources (tables, views, graphs, UDFs) + verified parameterised queries > glossary > instructions → agent SQL | Gemini | n/a |
| Azure AI Document Intelligence (formerly Form Recognizer) | Microsoft | Big tech | ~2019-05 | document → read / layout / prebuilt / custom template, neural or generative models → cells with polygons + content spans, fields with confidence | Azure AI | n/a ("deterministic extraction from structured documents", vendor) |
| Azure AI Content Understanding | Microsoft | Big tech | ~2024-11 (GA API 2025-11) | analyzer: content extraction → segmentation/classification → field Extract / Classify / Generate with confidence + source grounding → Markdown or JSON; agentic mode preview | bring-your-own Foundry LLM | n/a (worked example ~$8.4 per 1k invoice pages) |
| Microsoft Fabric AI Functions | Microsoft | Big tech | n/a | pandas / PySpark / T-SQL ai.extract with JSON Schema labels, ai.classify, ai.generate_response → columns; aifunc.load folder → table, ai.infer_schema | gpt-5-mini default | n/a |
| Microsoft Fabric data agent | Microsoft | Big tech | n/a | tables / semantic models → read-only NL2SQL, NL2DAX, NL2KQL under user identity; example queries; no unstructured files | Fabric, fixed LLM | n/a |
| Azure AI Search agentic retrieval / Foundry IQ | Microsoft | Big tech | ~2025-05 | knowledge base → LLM query planning → parallel keyword/vector/hybrid subqueries → semantic rerank → merged content + references | Azure AI Search | n/a ("precise reconstruction not guaranteed", vendor) |
| Amazon Textract | AWS | Big tech | ~2019-05 | page → Detect Text / AnalyzeDocument (Tables, Forms, Queries, Layout) / AnalyzeExpense → blocks with geometry + confidence | AWS ML models | table cell accuracy 0.73 on one financial PDF, "never fabricates" (Needl.ai report, independent of AWS) |
| Amazon Bedrock Data Automation (BDA) | AWS | Big tech | ~2024-12 | docs/images/audio/video → per-page classification → blueprint (≤100 fields) extraction with normalisation, validation, confidence, visual grounding → JSON | Bedrock models | n/a ($0.04/page custom output) |
| GenAI IDP Accelerator | AWS | Big tech | 2025-08 | OCR → classification + packet splitting → extraction (BDA or Textract+Bedrock) → assessment/confidence → HITL review UI → evaluation | Textract, Bedrock, BDA; open source | 85% accuracy at Competiscan (customer-reported) |
| Bedrock Knowledge Bases structured data retrieval | AWS | Big tech | 2024-12 | question + schema + query history → managed NL2SQL over Redshift / SageMaker Lakehouse; GenerateQuery returns SQL only | Bedrock LLMs | n/a ($2 per 1k queries) |
| Oracle Select AI | Oracle | Big tech | ~2023 | NL prompt → LLM SQL over Autonomous DB with runsql / showsql / explainsql / feedback actions; column comments as context | third-party LLMs | n/a |
| Oracle DBMS_VECTOR_CHAIN + OCI Document Understanding | Oracle | Big tech | 2026-01 (generative KV) | in-DB UTL_TO_TEXT / chunks / embeddings; OCI DU generative key-value extraction from NL field prompts + few-shot → normalised JSON | Oracle 26ai, LMMs | n/a ("stable outputs", vendor) |
| SAP Document AI | SAP | Big tech | n/a | structured/semi-structured docs → OCR (100+ languages) + extraction → review UI with Joule → learns from corrections → S/4HANA | SAP AI | n/a |
| IBM watsonx.data integration (unstructured) | IBM | Big tech | 2025-06 | connectors → Docling / watsonx Document Understanding parse → PII masking, quality filter, confidence → "structured derivatives" + embeddings, incremental | Docling | "40% more accurate than conventional RAG" (vendor, internal) |
| Salesforce Data Cloud Document AI | Salesforce | Big tech | 2025-09 | documents as UDLOs → NLP/ML/LLM extraction → DLO/DMO objects queryable like structured data → Agentforce | Data Cloud | n/a |
| ServiceNow Now Assist in Document Intelligence | ServiceNow | Big tech | 2026-03 | document → autofill fields → reviewer checks every field (default) or full automation with missing-field flags → work records | Now Assist | n/a |
| Palantir Pipeline Builder "Use LLM" + Ontology | Palantir | Data platform | ~2024-06 (typed outputs) | LLM node with typed struct output (strict coercion fails on mismatch) + skip recomputing rows → Ontology objects/links; agent proposals reviewed by operators | AIP, Foundry | n/a |

**Also covered briefly:** Snowflake Cortex Search + analytical search pattern (Snowflake, ~2024); Databricks ai_query (Databricks, n/a).

## 11. Specialist IDP vendors

Commercial LLM-native and incumbent IDP vendors. Almost every number is vendor- or customer-reported. (22 main entries, 0 brief.)

| Method | Developer | Developer type | First release | High-level flow | Tools / models | Key result |
|---|---|---|---|---|---|---|
| Reducto (Parse / Extract / Deep Extract) | Reducto | Startup/vendor | n/a | traditional OCR + VLMs + heuristics segment pages → content-type pipelines → "Agentic OCR" corrects errors → schema extraction with bounding boxes + citations; Deep Extract adds agentic verification loop | proprietary OCR/VLMs | 99.24% accuracy at Anterior (customer story, undefined metric) |
| Extend | Extend | Startup/vendor | n/a | parse → classify/split → extract (Light / Performance / Operator-1) with confidence → Review Agent + eval suites; custom fine-tuned models for large clients | OCR + VLMs, fine-tuned models | HomeLight >98%, human review switched off after zero corrections (customer story) |
| LandingAI Agentic Document Extraction (ADE) | LandingAI | Startup/vendor | n/a | vision-first parsing (DPT-2) → agentic plan/verify → schema-first nested extraction with per-value bbox citations, table-cell grounding, confidence | DPT-2 vision models | Autyn 94–98% field accuracy (customer story); DocVQA 99.16% on validation split (vendor) |
| LlamaParse / LlamaExtract | LlamaIndex | Startup/vendor | ~2024-02 (LlamaParse) | parse tiers (Cost Effective / Agentic / Agentic Plus, Auto Mode routing) → extract per document/page/table row → schema-validated JSON + optional citations, confidence | LLMs/VLMs | LlamaExtract Agentic Plus 95.6 value F1 on ExtractBench (benchmark by LlamaIndex itself) |
| Datalab (Marker, Surya, Chandra; hosted Convert/Extract) | Datalab | Startup/vendor | ~2023-11 (Marker) | PDF → layout + OCR (Surya) → Markdown/JSON (Marker) or VLM OCR (Chandra) → hosted schema extraction with per-field citations | open-weight models (revenue-gated licence) | Chandra 88.0 on olmOCR-Bench tables (self-reported); OmniParseBench 94.1 (own benchmark) |
| Mistral OCR / Document AI | Mistral AI | LLM lab | ~2025-03 (OCR 3: 2025-12) | page → OCR model → Markdown with HTML tables → document_annotation: markdown + first 8 image boxes → vision LLM fills Pydantic/JSON schema | mistral-ocr-2512 | 74% win rate over OCR 2 (vendor); scored 0 on tables in Needl.ai test (third party) |
| Unstructured | Unstructured.io | Startup/vendor | ~2022 | partition (fast rules / hi_res layout model / ocr_only / vlm) → typed elements → chunking + enrichments (NER, table-to-HTML) → 40+ connectors | layout models, VLMs | n/a (structured extraction "coming soon") |
| Contextual AI Document Parser | Contextual AI | Startup/vendor | 2025-05 | multi-stage vision + OCR + VLM parsing → document hierarchy inference → tables with confidence + bboxes → hierarchy-aware chunks | VLMs | RAG equivalence 69.2% → 84.0% on 10-K/10-Q with hierarchy metadata (vendor) |
| Sensible (SenseML) | Sensible | Startup/vendor | n/a | SenseML config combines deterministic rule-based extraction with LLM extraction → typed, validated JSON with traceable fields | rules + LLMs | 75M+ documents processed (vendor) |
| Tensorlake DocumentAI v2 (discontinued) | Tensorlake | Startup/vendor | 2025-07 | classify pages first → scope JSON-schema extraction to page classes → records list source pages | LLMs | n/a (vendor pivoted away by 2026-11) |
| Vectara metadata filtering | Vectara | Startup/vendor | n/a | RAG index with typed doc./part. metadata → SQL-WHERE-like filters before semantic retrieval | Vectara platform | n/a |
| Hyperscience (Hypercell) | Hyperscience | Startup/vendor | n/a | classify (Visual Page Classifier) → extract → 50+ data types normalise values → only below-SLA fields/characters to reviewers → case collation; LLM validation blocks | proprietary models + Claude 3 on Bedrock | >96% accuracy at >99% automation for a federal agency (2021 vendor case) |
| UiPath Document Understanding / IXP | UiPath | Startup/vendor | n/a | digitise → classify → extract (+ generative validation) → HITL validation station → structured data to agents | UiPath models + generative extraction | Thermo Fisher 53% STP, 82.4% reading accuracy (customer story) |
| Tungsten Automation (ex-Kofax) TotalAgility / DocAI | Tungsten Automation | Startup/vendor | n/a | no-code DocAI Studio + pretrained accelerators → capture → workflow | proprietary | >10B documents/year claimed (vendor) |
| ABBYY Vantage (+ GPT-4 Turbo hybrid) | ABBYY | Startup/vendor | n/a | classify + segment long documents → GPT-4 Turbo extracts per segment → below-threshold fields to manual review → RPA entry | Vantage skills + GPT-4 Turbo | 82% accuracy on 350+-field leases (customer story) |
| Instabase AI Hub | Instabase | Startup/vendor | n/a | digitise → classify → extract → validate → map into target system (per-field pricing) | proprietary + LLMs | custody faxes STP 40% → >95%, 97.56% accuracy (customer story) |
| Rossum Aurora (T-LLM) | Rossum (acquired by Coupa 2026) | Startup/vendor | 2024-02 | "highlighter" model locates values in document instead of generating → formula fields, date checks, master-data matching → ERP posting | transactional LLM (T-LLM) | "0 hallucinated values" (vendor); Eurowag 70% automation (customer story) |
| Indico Data | Indico Data | Startup/vendor | n/a | intake + orchestration for insurance submissions (slips, SOVs, loss runs) → extraction → review | proprietary | Convex median 40 s per submission (customer story) |
| Nanonets | Nanonets | Startup/vendor | n/a | block-based workflow (simple / standard AI / complex AI blocks) → ERP / DB integrations | Nanonets OCR models | Nanonets OCR-3 85.9 on own IDP leaderboard (vendor) |
| Automation Anywhere Document Automation | Automation Anywhere | Startup/vendor | n/a | classify → extract → route sensitive items to human reviewers | proprietary | 90% extraction accuracy at a global tax firm (customer story) |
| Box Extract | Box (Alphamoon technology) | Startup/vendor | 2026-01 | extract fields with Gemini → confidence from agreement across sampled responses (temperature, paraphrased prompts, shuffled fields) → Low/Medium/High labels | Gemini 2.5 Flash/Pro | n/a (vendor tells users to validate thresholds) |
| Daloopa (verified fundamentals + MCP) | Daloopa | Startup/vendor | n/a | SEC filings → verified, normalised fundamentals DB with hyperlink to source per data point → exposed to agents via MCP | MCP server | 94.2% vs 11.2–63.8% ungrounded LLMs on financial retrieval (vendor) |

## 12. Open-source frameworks and engineering case studies

Permissively licensed building blocks for extraction, caching, loading, orchestration, agent access and evaluation, plus company engineering write-ups. (30 main entries, 8 brief.)

| Method | Developer | Developer type | First release | High-level flow | Tools / models | Key result |
|---|---|---|---|---|---|---|
| Instructor | 567 Labs (Jason Liu) | Open-source community | ~2023-06 | Pydantic model → LLM call in tool/JSON mode → validate → retry on failure; cache keyed on SHA-256 of model, messages, mode and full JSON schema | Python, any LLM provider; MIT | n/a |
| Pydantic AI | Pydantic | Startup/vendor | ~2024-12 | agent with typed output (tool output / native structured output / prompted) → output validators raise ModelRetry → typed result | Python; MIT | n/a |
| BAML | Boundary | Startup/vendor | n/a | typed .baml function definitions → generated client (Python/TS/Go/Ruby) → JSON repair + retries + playground tests | DSL; Apache-2.0 | n/a |
| DSPy | Stanford University, UC Berkeley et al. (Khattab et al.) | Academia | 2023-10 | declarative signatures/modules → compiler optimises prompts and demos against a metric → cached LM calls (memory + disk) | Python; MIT | n/a |
| CocoIndex | CocoIndex | Startup/vendor | n/a | source files → @coco.fn(memo=True) memoised by hash(input) + hash(code) + declared deps (prompt, model) → reprocess only changes → reconcile target state (retire stale rows) | Rust core, Python API; Apache-2.0 | n/a |
| dlt (data load tool) | dltHub | Startup/vendor | n/a | Python sources → schema inference → append / replace / merge (delete-insert, SCD2, upsert, CDC) with state tracking → destination | Python; Apache-2.0 | n/a |
| Dagster (dynamic partitions) | Dagster Labs | Startup/vendor | n/a | software-defined assets (parse → extract → validate → publish) → sensor adds partition per new file → runs; ≤100k partitions advised | Python | n/a |
| Neo4j GraphRAG KG Builder (SimpleKGPipeline) | Neo4j | Data platform | n/a | schema triplets + enforcement → LLM extraction → lexical graph (Document → Chunk → Entity) for provenance → exact / spaCy / RapidFuzz entity resolvers | neo4j-graphrag-python | n/a (experimental) |
| Provider batch APIs (OpenAI, Anthropic) | OpenAI; Anthropic | LLM lab | ~2024 | submit up to 50k–100k requests with custom_id → async within 24 h → map results by custom_id (order not guaranteed) | OpenAI Batch, Claude Message Batches | 50% cost reduction (vendor) |
| Claude structured outputs | Anthropic | LLM lab | n/a | JSON schema via output_config.format or strict tool use → constrained output (no recursive schemas, no numeric min/max) | Claude API | n/a |
| vLLM batch-invariant mode | vLLM project | Open-source community | n/a | VLLM_BATCH_INVARIANT=1 → deterministic kernels, fixed reduction orders → identical outputs across batch sizes (beta) | vLLM | ~1.6x slower in Thinking Machines tests (third party) |
| Postgres MCP Pro | crystaldba | Startup/vendor | n/a | MCP server with restricted mode: read-only transactions, execution-time limits, safe SQL parsing; explain_query, index tuning | Postgres; MIT | n/a |
| DuckDB / MotherDuck MCP server | MotherDuck | Startup/vendor | n/a | MCP server opens DuckDB read-only by default without file lock → agent SQL; read-write opt-in | DuckDB; MIT | n/a |
| DuckLake time travel | DuckDB Labs | Open-source community | ~2025-05 | each commit = snapshot → SELECT … AT (VERSION => n) or ATTACH (SNAPSHOT_VERSION n) pins session → snapshots kept until expired | DuckDB, catalog DB | n/a |
| Anthropic "Writing effective tools for agents" | Anthropic | LLM lab | 2025-09 | consolidated task-shaped tools → namespacing → readable IDs → concise/detailed response_format → pagination + actionable errors → eval on held-out tasks | MCP / tool use | concise mode used ~1/3 of tokens (vendor) |
| promptfoo | promptfoo (acquired by OpenAI 2026-03) | Startup/vendor | n/a | test cases → deterministic asserts (equals, regex, is-json + schema, is-sql, python, cost, latency) + model-graded asserts → CI gate | Node; MIT | used by >25% of Fortune 500 (vendor claim) |
| LangSmith evaluation | LangChain | Startup/vendor | ~2023-07 | versioned datasets with splits → code / LLM-judge / pairwise / human evaluators → offline regression + online evaluation | LangSmith | n/a |
| Uber TextSense (invoices) | Uber | Big tech | 2025-04 | ingest → preprocessing → OCR → GPT-4 extraction → business-rule post-processing (exact/fuzzy match) → validation vs existing data → side-by-side review UI; orchestrated on Cadence | GPT-4, Cadence | 90% overall accuracy, −70% handling time (company-reported) |
| Instacart PARSE | Instacart | Big tech | 2025-08 | versioned config (attribute definition, input SQL, few-shot, model, prompt) → multimodal LLM extraction → self-verification "yes" probability as confidence → low confidence to auditors | multimodal LLMs | "organic" attribute 95% accuracy in 1 day (company-reported) |
| Shopify Global Catalogue | Shopify | Big tech | 2025-07 | fine-tuned open vision LLMs with taxonomy-constrained outputs → selective field prompting → multi-LLM annotation + arbitrator → product clusters with Universal Product IDs | LLaVA → Llama 3.2 11B → Qwen2-VL 7B | ~40M LLM calls/day; −40% GPU (company-reported) |
| DoorDash product knowledge graph | DoorDash | Big tech | ~2024 | classifier → LLM brand extraction → second LLM dedups vs taxonomy; organic labels via string match → LLM/OCR → web-search agent; GPT-4 labels fine-tune small model | GPT-4 + fine-tuned models | annotation in ~1 week vs months (secondary summary) |
| Grab metadata classification | Grab | Big tech | 2023 | column metadata → GPT-3.5 picks one tag from curated library (with None option), JSON output → Kafka → access-control tiers | GPT-3.5 (Azure OpenAI) | <1 tag changed per table on average; ~360 man-days/yr saved (company-reported) |
| Uber QueryGPT | Uber | Big tech | 2024-09 | question → Intent agent picks workspace → Table agent → Column-Prune agent → SQL; golden-set eval (intent, table overlap, run success) | LLMs | authoring time 10 → ~3 min; ~5% run-to-run variation treated as noise (company-reported) |
| Uber Finch | Uber | Big tech | 2025-07 | LangGraph supervisor + SQL agent over curated single-table marts → OpenSearch alias index for columns and values → RBAC check → execute; eval by result equality | LangGraph, OpenSearch | n/a (no accuracy disclosed) |
| LinkedIn SQL Bot | LinkedIn | Big tech | 2024-12 | KG of users/tables/fields from DataHub + query logs → embed-retrieve top-20 tables → LLM re-rank to 7 → SQL → existence checks + EXPLAIN → self-correction | LLMs, DataHub | ~95% of users rate "Passes" or better (company-reported) |
| Pinterest text-to-SQL / Analytics Agent | Pinterest | Big tech | ~2024 | RAG over table + query summaries (OpenSearch) → LLM top-K tables → user confirms → SQL; 2026: EXPLAIN validation, governance-aware ranking | LLMs, OpenSearch | first-shot acceptance 20% → >40% (secondary summary) |
| Grab Data-Arks | Grab | Big tech | 2024-10 | frequent SQL queries and Python functions registered as individual APIs → LLM (Spellvault RAG) selects which pre-written query to run | LLM + API registry | 3–4 h saved per report (company-reported) |
| Nilenso KYC LLM-OCR | Nilenso | Startup/vendor | 2026-05 | expert-vetted golden set (50/doc type) + rubric before prompts → Gemini 2.0 Flash pipeline → per-type evals, hallucinations scored worse than nulls | Gemini 2.0 Flash | 92% on golden set; ~$1k vs $10k per 1M docs vs third-party service (company-reported) |
| Industrial KYC OCR+VLM pipeline | OCBC Bank (Han et al.) | Startup/vendor | 2026-04 | page-level retrieval of relevant pages → OCR + VLM field extraction | OCR + VLMs | 87.27% field accuracy, up to +31.9 points over direct PDF-to-VLM (author) |
| Xebia Databricks production postmortem | Xebia | Startup/vendor | n/a (updated 2026-10) | Structured Streaming checkpoints → separate parse / assemble / extract Delta tables → dedupe in Silver → prompt-version column → labelled regression set; deterministic parsers for fixed templates | Databricks ai_query, OpenDataLoader PDF | ~$126–137 per 30k-page parse pass (practitioner) |

**Also covered briefly:** Prefect 3 caching (Prefect, n/a); Airbyte S3 "Document File Type Format" (Airbyte, 2023-10); autoevals (Braintrust, n/a); Ramp receipts (on Modal) (Ramp / Modal, 2024-03); Neurosymbolic transactional-document extraction (La Rochelle University, Shift Technology, 2025-12); Production Document AI microservices (Kungfu.ai, 2026-05); Swiggy Hermes V3 (Swiggy, ~2026-01); Hybrid OCR-LLM identity-document extraction (Eastern Institute of Technology, Ningbo, 2025-10).

## Method families at a glance

- **Specialised parsers on the PDF text layer** (TATR/TableFormer/POTATR, Docling, layout detectors). *Best for:* born-digital PDFs and tables. *Determinism:* a non-autoregressive or fixed forward pass, with cell text copied byte-for-byte from the PDF and a bbox per cell. Use VLM parsers (MinerU2.5, PaddleOCR-VL, olmOCR) for scans. They generate autoregressively and can loop or change values, so parse once and freeze the output.
- **Schema-guided LLM extraction with constrained decoding and span grounding** (LangExtract, LMDX, SPIRES, SafePassage, Outlines/XGrammar/llguidance, provider structured outputs). *Best for:* narrative documents and bespoke nested schemas. *Determinism:* output is schema-valid by construction but not reproducible run to run, even at temperature 0. The grounding check (value must align to source offsets) is deterministic. Store outputs as versioned snapshots.
- **Small span encoders** (GLiNER, GLiNER2, ReFinED, Maverick). *Best for:* high-volume entity tagging, linking and coreference. *Determinism:* a single forward pass with no sampling, and every output is a span of the input. Weak on nested records and normalisation.
- **LLM-synthesised programs** (Evaporate-Code+, Auto-Tables, AutoScraper/BardeenAgent wrappers, LILAC templates, SemBaker). *Best for:* templated and semi-structured families such as web sites, spreadsheets, logs and forms. *Determinism:* fully deterministic once the program is frozen and versioned. The LLM runs only at build time. Weak on free text.
- **Query-time semantic operators** (LOTUS, Palimpzest, DocETL, UQE, warehouse AI functions). *Best for:* one-off exploratory questions over documents. *Determinism:* answers depend on the plan, the model and server load. Write judgments back as columns (OCTOPUS, SemReuse) or compile them to code to make repeat questions exact.
- **Design-time schema, matching and entity-resolution steps** (EDC, Executable Schema Contracts, Magneto, Splink, ComEM, LLM-CER). *Best for:* integrating many sources into one schema with stable entity IDs. *Determinism:* LLM decisions are frozen as mapping tables, alias maps and cluster IDs, then replayed by deterministic code. Keys and foreign keys come from statistical profiling.
- **Closed-vocabulary knowledge graphs** (EDC, GenIE, LLMGraphTransformer strict mode, OntoMetric, Zep/Graphiti bitemporal edges), as opposed to description graphs (GraphRAG, LightRAG). *Best for:* multi-hop relational questions. *Determinism:* exact Cypher/SPARQL works only with typed predicates, stored merge decisions and reified, time-stamped statements.
- **Constrained query interfaces over pinned snapshots** (parameterised MCP tools, dbt MetricFlow and other semantic layers, Grab Data-Arks; Iceberg/DuckLake time travel), with guarded text-to-SQL (CHESS, ReFoRCE, LinkedIn SQL Bot) as the fallback. *Best for:* recurring question shapes and aggregates. *Determinism:* tools and semantic layers compile the same SQL for the same selection. Free text-to-SQL varies run to run, so log and cache accepted queries, use a total ORDER BY, and pin the snapshot ID.
