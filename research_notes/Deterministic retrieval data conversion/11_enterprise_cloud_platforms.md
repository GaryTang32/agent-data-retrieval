# Enterprise Cloud and Data Platforms: Converting Unstructured Data into Queryable Tables for Deterministic Retrieval

Scope: hyperscaler and data-platform offerings (Snowflake, Databricks, Google Cloud, Microsoft, AWS, Oracle, SAP, IBM, Salesforce, ServiceNow, Palantir). Specialist IDP vendors are covered in another track. As of November 2026. Labels used below: **[GA]**, **[Preview]**, **[Beta]** for product status; **[vendor claim]** for figures the vendor reports about itself; **[customer-reported]** for figures in vendor-hosted customer stories, which no one has independently checked; **[independent]** for third-party measurements. All prices are list prices in USD on the date fetched, unless noted.

Cross-cutting framing for the reader. Every platform now splits the problem into two layers with very different determinism properties:
1. **Conversion layer (non-deterministic):** LLM or VLM parse, extract and classify, writing to tables. No vendor guarantees run-to-run identical extraction output.
2. **Retrieval layer (deterministic if built that way):** SQL, graph or key lookups over the materialized tables. Agent front-ends (Cortex Analyst, Genie, BigQuery data agents, Fabric data agents, Bedrock KB structured retrieval, Select AI) add a non-deterministic NL-to-SQL step on top. Each vendor offers a "verified or trusted query" mechanism to pin that step.

---

## 1. Snowflake: Cortex AI Functions (AISQL), Document AI, Cortex Analyst with semantic views, and Cortex Search

### Takeaway
By 2026 Snowflake has fully moved document-to-table conversion into SQL functions. AI_PARSE_DOCUMENT (OCR, LAYOUT and an AGENTIC preview) feeds AI_EXTRACT (schema-based extraction with arctic-extract and optional per-field scores), and AI_CLASSIFY routes documents between them. The legacy Document AI UI and !PREDICT were decommissioned in March 2026. Deterministic retrieval is then provided by semantic views (with AI_VERIFIED_QUERIES) queried directly or through Cortex Analyst/Agents. Snowflake does not guarantee that extraction is deterministic, and AGENTIC output conformance is explicitly "not guaranteed".

### Cited Findings
**Functions and architecture**
- The Cortex AI Functions family includes AI_COMPLETE, AI_CLASSIFY, AI_FILTER, AI_AGG, AI_SUMMARIZE_AGG, AI_EMBED, AI_EXTRACT, AI_PARSE_DOCUMENT, AI_TRANSCRIBE, AI_REDACT and others, plus TO_FILE and the FILE data type for staged files. Snowflake says the functions are "optimized for throughput", and recommends the REST API for low-latency use. — [Snowflake docs: Cortex AI Functions](https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql)
- Recommended composition: AI_PARSE_DOCUMENT for full text and layout (RAG, summarization); AI_EXTRACT for schema-defined fields and tables; AI_CLASSIFY to route mixed document streams (invoices, contracts, statements) to the right extraction workflow; and AI_COMPLETE as a general fallback. — [Snowflake docs: AI Functions for documents](https://docs.snowflake.com/en/user-guide/snowflake-cortex/ai-documents)
- Snowflake's reference layering for unstructured data is Raw (OpenFlow ingest with metadata for traceability) → Transformed (Cortex AI Functions write structured fields in SQL) → Curated (joined KPI tables) → Consumption (BI, ML, Cortex Analyst). Published December 18, 2025. — [Snowflake blog: Structuring the Unstructured](https://snowflake.com/en/blog/structuring-unstructured-data-cortex-aisql/)
- **Academic paper (vendor-published):** "Cortex AISQL: A Production SQL Engine for Unstructured Data" (SIGMOD Companion '26 Industry Track; arXiv 2511.07663, v3 April 2026). It describes three techniques: AI-aware query optimization (2-8x speedups), adaptive model cascades that send most rows to a proxy model and escalate uncertain ones to an oracle (2-6x speedups at 90-95% of oracle quality), and semantic-join rewriting into multi-label classification (15-70x). [vendor claim] — [arXiv 2511.07663](https://arxiv.org/abs/2511.07663)
- Determinism implication of the paper: model cascades mean that *which* model labels a row depends on proxy confidence. Semantic operators are therefore probabilistic by design. (Inference from the paper's described mechanism.) — [arXiv 2511.07663](https://arxiv.org/abs/2511.07663)

**AI_PARSE_DOCUMENT**
- Modes: OCR (text only, default), LAYOUT (Markdown with tables and structure), and AGENTIC (interprets charts, diagrams and tables, generating summaries and structured data). Options are `page_split` (PDF, PPTX and DOCX only), `page_filter`, `extract_images` (LAYOUT only; errors in AGENTIC) and `return_error_details`. Failed rows return NULL without stopping the query. — [Snowflake docs: AI_PARSE_DOCUMENT](https://docs.snowflake.com/en/sql-reference/functions/ai_parse_document)
- Limits: 100 MB per file, 2,000 pages per document, 10,000×10,000 px per page. Formats are PDF, PPTX, DOCX, JPEG/JPG, PNG, TIFF/TIF, HTML and TXT. LAYOUT extracts up to 50 images per document; AGENTIC handles up to 2,000 images. Billing is per page processed, with each 3,000-character chunk of HTML or TXT counting as one page. A MEDIUM or smaller warehouse is recommended. The page states "schema conformance is not guaranteed" for AGENTIC output. — [Snowflake docs: Parsing documents](https://docs.snowflake.com/en/user-guide/snowflake-cortex/parse-document)
- **AGENTIC mode [Preview]** entered Public Preview on October 28, 2026. In a practitioner test, 79 pages across 4 PDFs parsed in about 47 seconds, and charts and timelines were parsed correctly. Caveats from that test: page indexes are file-relative, not printed page numbers; failed images return `{"description":"error"}`; the output structure is best-effort; and no AGENTIC-specific rate had been published as of November 1, 2026. Their architecture was parse → chunk (400 characters, 80 overlap) → Cortex Search (arctic-embed-l-v2.0) plus Cortex Analyst on a semantic view → Cortex Agent. [independent] — [Classmethod DevelopersIO (JP)](https://dev.classmethod.jp/articles/snowflake-try-ai-parse-document-with-agentic-mode/)
- **[vendor claim]** In a February 26, 2026 Snowflake engineering post, LAYOUT mode reconstructs about 39.6% of tables exactly on 50 annotated financial documents (vs. 32% for AWS Textract), with about 70.8% shape match. The post claims roughly 80% JSON accuracy on the OmniAI OCR benchmark and a cost of about $6.66 per 1,000 pages (Standard Edition). — [Snowflake engineering blog: Enterprise-Scale Document AI](https://www.snowflake.com/en/blog/engineering/enterprise-scale-document-ai/)

**AI_EXTRACT**
- Accepts `text` or `file` (not both). Response formats are a simple object, an array of label/question pairs, or a JSON schema. Lists use `type: array`, and tables use an object with `column_ordering` and array columns. **String is the only supported scalar type**, so downstream casting is needed. — [Snowflake docs: AI_EXTRACT](https://docs.snowflake.com/en/sql-reference/functions/ai_extract)
- Limits: under 100 MB; 1,000 pages with cross-region inference or 125 pages without; up to 100 entity questions or 10 table questions per call (one table question counts as 10 entities); output capped at 512 tokens per entity and 4,096 tokens per table answer. Supports roughly 20 formats (PDF, DOCX, PPTX, EML, HTML, images, MD and others) and about 28 languages. The model is a fine-tuned `arctic-extract`. — [Snowflake docs: AI_EXTRACT](https://docs.snowflake.com/en/sql-reference/functions/ai_extract)
- Billing: each page of a PDF, DOCX or TIFF counts as 970 input tokens, and each image counts as one page. `scores => TRUE` returns 0-1 confidence per entity field (aggregate only for lists and tables) at no extra cost. With cross-region inference a bad file errors per row; without it, the whole statement fails. — [Snowflake docs: AI_EXTRACT](https://docs.snowflake.com/en/sql-reference/functions/ai_extract)
- Status timeline: extraction scores went GA on May 22, 2026; fine-tuning of arctic-extract went to preview on January 28, 2026 and GA on April 20, 2026. A March 13, 2026 practitioner guide states that AI_EXTRACT had *no* confidence scores and a 125-page limit, which was correct at the time but is now superseded by the docs above. The same guide's worked cost example: 1,000 three-page invoices with 5 questions ≈ 3.6M tokens ≈ 18 credits ≈ $36 (about $0.012 per page). Its recommendations are to persist results in tables, process each document once with Streams and Tasks, and build your own validation. — [Flexera: Snowflake AI_EXTRACT guide](https://www.flexera.com/blog/finops/snowflake-ai-extract/); contradicted (on scores and page limit, for current state) by [Snowflake docs: AI_EXTRACT](https://docs.snowflake.com/en/sql-reference/functions/ai_extract)

**Document AI (legacy)**
- The Document AI UI and `!PREDICT` were decommissioned on March 16, 2026; the change log shows the date was updated on February 20, 2026. Models not migrated to the Model Registry can no longer run inference, and migrated models cannot be fine-tuned further. The migration path is AI_EXTRACT (arctic-extract), with token-based billing. — [Snowflake BCR-2156: Document AI decommission](https://docs.snowflake.com/en/release-notes/bcr-bundles/un-bundled/bcr-2156)
- Historical (2024) context: Document AI was built on Arctic-TILT. Best practices were: one model build per use case, fine-tune with annotations rather than prompt-tweak, keep a held-out eval set, set per-field confidence thresholds, route low-confidence output to SMEs, and "extract raw values before applying formatting". The "50% manual labor reduction" figure is illustrative, not measured. — [Snowflake engineering blog: Document AI best practices (Oct 2024)](https://www.snowflake.com/en/blog/engineering/best-practices-snowflake-document-ai/)
- **Academic paper (vendor-published, 2024):** Arctic-TILT is a sub-billion-parameter model that claims accuracy comparable to models about 1,000x larger on document QA. It reports SOTA on 7 benchmarks, handles documents up to 400k tokens, runs on a single 24 GB GPU and outputs confidence scores. [vendor claim] — [arXiv 2408.04632](https://arxiv.org/abs/2408.04632)

**Retrieval layer: semantic views, Cortex Analyst, Cortex Search**
- Semantic views are schema-level objects holding logical tables, relationships (join keys), facts, dimensions and metrics. They can be queried with SELECT, used as a Cortex Agent tool, or passed to the Cortex Analyst API. Authoring options are Autopilot (which imports YAML, Tableau or Power BI), Semantic Studio, or `CREATE SEMANTIC VIEW`. — [Snowflake docs: Semantic views](https://docs.snowflake.com/en/user-guide/views-semantic/overview)
- On April 5, 2026, Snowflake added verified queries inside semantic views through the `AI_VERIFIED_QUERIES` clause of `CREATE SEMANTIC VIEW`, "to improve accuracy and trustworthiness" of Cortex Analyst. — [Snowflake release note 2026-04-05](https://docs.snowflake.com/en/release-notes/2026/other/2026-04-05-semantic-views-verified-queries)
- Cortex Analyst is LLM-based text-to-SQL that runs in the customer's warehouse under the caller's role (RBAC applies). It publishes **no numeric accuracy claim**. It is stateless, limited to questions SQL can answer, and degrades in long conversations. It is billed per message (standalone) or per token via Agents. Snowflake now "recommends transitioning to Cortex Agents." — [Snowflake docs: Cortex Analyst](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst)
- Cortex Search provides hybrid vector, keyword and semantic reranking. It supports `ATTRIBUTES` filters (`@eq`, `@primarykey`) and TARGET_LAG refresh with Dynamic Table semantics, where content can lag the base data by up to the target lag. Default limits are 20 QPS per service and 140 QPS per account, with materialized results under 400M rows. Serving is billed per GB-month of indexed data even when idle. The docs do not address result determinism. — [Snowflake docs: Cortex Search](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-search/cortex-search-overview)
- "Agentic Document Analytics" (BUILD, November 4, 2025) treats documents as queryable data for aggregate questions (counts and sums across thousands of documents) rather than RAG. Snowflake's Jeff Hollan: "For RAG to work, it requires that all of the answers ... already exist in some published way." The announcement named no customers. — [VentureBeat](https://venturebeat.com/data/snowflake-builds-new-intelligence-that-goes-beyond-rag-to-query-and)
- Snowflake's "analytical search" reference pattern: Cortex Search prunes the corpus to candidates, AI_FILTER and AI_EXTRACT create columns, AI_AGG clusters them, and SQL counts, groups and ranks. A router sends per-document questions to RAG and corpus-wide questions to the analytical path. Extracted signals feed a Semantic View. — [Snowflake developer guide: Analytical search over SEC filings](https://www.snowflake.com/en/developers/guides/analytical-search-over-sec-filings-with-snowflake-cowork/)

**Pricing**
- AI Credits cost $2.00 with global cross-region routing and $2.20 with regional routing. AI Parse Doc is billed per 1,000 pages with mode-dependent rates (numbers are only in the Consumption Table PDF). AI_EXTRACT is per million tokens, Cortex Analyst per 1,000 messages, and Cortex Search per GB-month plus embedding tokens. — [Snowflake docs: AI pricing](https://docs.snowflake.com/en/user-guide/snowflake-cortex/pricing)

**Customers**
- **[customer-reported]** Florida State University uses Document AI to extract request reason, date and approver from PDF data-request forms for auditing and outlier detection. Reported results: time-to-value fell from 90 to 5 days (95% faster) and 47 sources were consolidated (11x versus Oracle). The story is undated (©2026). — [Snowflake customer story: FSU](https://www.snowflake.com/en/customers/all-customers/case-study/florida-state-university/)

### Inferences
- Snowflake's intended deterministic path is to materialize AI_EXTRACT output once into typed tables (casting from string), expose those tables via a semantic view with verified queries, and let agents call the semantic view. Cortex Search is for discovery and candidate pruning, not exact answers.
- AI_EXTRACT has scores but documents no span-level citations (bounding boxes or offsets) for extracted values. Provenance must come from AI_PARSE_DOCUMENT page indexes or your own mapping. This is weaker than Databricks ai_extract v2.1 or Azure Content Understanding grounding.
- Model churn (Document AI decommissioned about 18 months after its 2024 GA) shows that platform extraction models are not stable artifacts. Reproducibility requires storing outputs together with model and version metadata.

### Gaps
- Exact credit rates per 1,000 pages for OCR, LAYOUT and AGENTIC are only in the Consumption Table PDF, which I did not retrieve. A third-party JP estimate (about $1.36 for OCR and $7.32 for LAYOUT per 1,000 pages) was seen only in a search snippet, so it is not cited.
- I found no named Snowflake customer case study with metrics specific to AI_EXTRACT. A hands-on lab referenced QTS, but I found no write-up.
- No vendor statement on whether AI_EXTRACT is deterministic at fixed inputs.

---

## 2. Databricks: ai_parse_document, ai_extract, ai_query, Agent Bricks (Information Extraction and Knowledge Assistant), Unity Catalog, and Genie

### Takeaway
Databricks offers the most complete in-lakehouse "parse → extract with citations → Delta table → Unity Catalog → Genie" chain. ai_parse_document went GA on April 16, 2026. ai_extract v2.1 adds typed JSON schemas, per-field confidence and **citations back to text spans or bounding boxes**. Genie's trusted assets give a verified-SQL path. Databricks explicitly says underlying models may change, so only the output *schema* is version-pinned, not the content.

### Cited Findings
- **ai_parse_document [GA, April 16, 2026]** takes BINARY content and returns VARIANT `document.pages` and `document.elements`. Each element has id, type, content, confidence (0-1), bbox with page_id, and description. Types are text, table (as HTML), figure (chart JSON when readable), signature, title, caption, section_header, page_header and footer, page_number and footnote. Options are `version` ("2.0"), `imageOutputPath` (a UC volume), `descriptionElementTypes` and `pageRange`. — [Databricks docs: ai_parse_document](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_parse_document); GA date from [Databricks release notes, April 2026](https://docs.databricks.com/aws/en/release-notes/product/2026/april)
- Limits: 500 pages (longer documents fail immediately unless `pageRange` is set) and 100 MB. Formats are PDF, JPG/PNG, TIFF, DOC/DOCX and PPT/PPTX. It needs DBR 17.3+. Non-Latin text in images may underperform, the model cannot be customized, and Databricks "may change the underlying models"; the `version` option pins only the schema. The September 22, 2025 schema change (adding descriptions and bbox) required migrating from `pages` to `elements`. — [Databricks docs: ai_parse_document](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_parse_document)
- **ai_extract** v2.0/2.1: `ai_extract(content, schema [, options])`. Schemas support string, integer, number, boolean, enum, nested objects (up to 12 levels) and arrays. Types are validated and invalid values error. Limits are up to 256 fields, 500 enum values and a 1M-token context. Input can be raw STRING or ai_parse_document VARIANT. v2.1 adds `enableCitations` (a text span, or a bounding box for parsed PDFs and images) and `enableConfidenceScores`, plus a `precision` mode. Not available on DBSQL Classic or in views. — [Databricks docs: ai_extract](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_extract)
- **ai_query** is a general function over Model Serving endpoints. `responseFormat` accepts a json_schema for structured output. Temperature **defaults to 0.0**. `failOnError=false` returns a STRUCT of response and error. The docs say nothing on determinism beyond the temperature default. — [Databricks docs: ai_query](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_query)
- **Agent Bricks Information Extraction (legacy) [Beta]** turns unlabeled text into a structured table. The workflow is: auto-generated JSON schema → feedback ("Fix it", at least 3 reviewed responses) → batch via `ai_query` or a scheduled Lakeflow pipeline → Quality tab evaluation. Models are "Optimize for Scale" or "Optimize for Complexity" (40+ fields). Limits are a 128k context, no union types, no native PDF (convert with ai_parse_document first) and no support in Enhanced Security workspaces. — [Databricks docs: Information Extraction](https://docs.databricks.com/aws/en/generative-ai/agent-bricks/key-info-extraction)
- Announcement (November 11, 2025, then Public Preview): ai_parse_document runs incrementally in Spark Declarative Pipelines (retries, checkpointing), stores images in UC volumes and preserves lineage. **[vendor claim]** It claims "highest quality in its price category" on OmniOCR and quality competitive with leading parsers and VLMs at 3-5x lower cost. Benchmark charts showed an *upcoming* release and promotional pricing. Customer quotes came from Rockwell Automation, TE Connectivity and Emerson. — [Databricks blog: PDFs to Production](https://www.databricks.com/blog/pdfs-production-announcing-state-art-document-intelligence-databricks)
- **[customer-reported, vendor blog]** AstraZeneca "parsed through more than 400,000 clinical trial documents and extracted structured data points ... without writing a single line of code", with a working agent built in under 60 minutes. Same post (November 3, 2025): UC governs models and external MCP servers. — [Databricks blog: Building Trusted AI Agents](https://www.databricks.com/blog/building-trusted-ai-agents-new-capabilities-choose-govern-and-scale-confidence)
- **[customer-reported]** YipitData replaced 500+ regex rules with Information Extraction agents for merchant tagging. Lakebase (Postgres) first narrows candidates using structured relationships, then AI Search plus IE decide. Results: 92-95% tagging accuracy out of the box, 1M records in about 1 hour (down from about 24 h), and company coverage up roughly 20x (about 3,000 to more than 60,000). — [Databricks customer story: YipitData](https://www.databricks.com/customers/yipitdata/ai)
- **Pricing (US East estimates, Databricks page):**
  - AI Parse Document per 1,000 pages: $0.70-$1.05 (simple text), $1.40-$1.75 (sparse tables or images), $4.20-$4.55 (complex tables and figures) and $5.95-$6.30 (dense forms and diagrams).
  - AI Extract: $2.10-$4.20 per 1,000 inputs; precision mode $26.25-$50.75 per 1,000.
  - AI Classify: $0.21-$4.20 per 1,000.
  - AI Extract and AI Classify on documents require prior ai_parse_document.
  — [Databricks pricing: AI Functions](https://www.databricks.com/product/pricing/ai-functions)
- **Genie** (Genie Agents, formerly spaces) builds context from UC metadata (names, descriptions, PK/FK), a knowledge store (synonyms, joins, SQL expressions), example queries and instructions. Generated SQL is "always read-only". **Trusted assets**, meaning parameterized example queries and SQL functions verified by an author, mark answers as built on verified logic. Benchmarks are evaluation-only and not fed back into context. Inspect [Public Preview] re-checks SQL. Row filters and column masks apply per user. Chat mode handles structured data only; unstructured volumes require Agent mode. — [Databricks docs: Genie concepts](https://docs.databricks.com/gcp/en/genie/concepts)
- Genie's branding is now Genie One, Genie Agents and Genie Code. Genie One and Agents usage by users is free through January 31, 2027; Genie Code has been pay-as-you-go since July 8, 2026. — [Databricks docs: Genie](https://docs.databricks.com/aws/en/genie/)
- **[independent]** Factored ran a matched RAG A/B test (40 hard documents, more than 1,000 pages, 33 golden questions, 3 runs, medians). ai_parse_document beat Azure Content Understanding by about 20% across four metrics, with the correct document surfacing about 40% more often. Cost was about half on average (about 2/3 of CU with gpt-4.1-mini, about 1/3 with gpt-4.1); CU's figure-description tokens drove its cost. The authors flag the small sample. — [Factored POV](https://www.factored.ai/our-pov/databricks-ai-parse-document-rag)
- **[independent, determinism-critical]** Xebia's production postmortem (updated October 28, 2026) on clinical letters:
  - Without checkpoints every run reprocesses every document, and prompt changes force full re-extraction.
  - "Even at temperature 0, LLM outputs can vary between runs" (a `follow_up_required` flag flipped).
  - `ai_query` returned free text with embedded JSON.
  - Duplicates appear when documents are resent under new filenames.

  Its fixes:
  - Structured Streaming with checkpoints.
  - Separate parse, assemble and extract Delta tables.
  - Dedupe in Silver.
  - Materialize Silver as a table with a prompt-version column.
  - A labeled regression set.
  - Deterministic parsers (e.g., OpenDataLoader PDF) for fixed templates, with the LLM used only for normalization.

  At medium pricing a 30,000-page corpus costs about $126-137 per parse pass. — [Xebia blog (DE)](https://xebia.com/de/blog/versteckte-kosten-ki-dokumentenanalyse-produktion-databricks/)
- Analyst commentary at launch (InfoWorld, November 13, 2025): Futurum's Bradley Shimmin said enterprises should "run their own benchmarks" rather than rely on price-performance claims. Databricks' and Snowflake's messaging is described as "very similar". — [InfoWorld](https://www.infoworld.com/article/4089186/databricks-fires-back-at-snowflake-with-sql-based-ai-document-parsing.html)
- A partner guide's (LatentView) reference pipeline is UC volumes → ai_parse_document → Agent Bricks or ai_query extraction → Vector Search → analytics. It recommends rules or regex instead when formats are fixed. Its status labels conflict internally and its cost figures are estimates. — [LatentView](https://www.latentview.com/blog/document-intelligence-on-databricks-2025-2026-what-to-use-when-and-why/)

### Inferences
- Databricks is the best-documented hyperscaler path to provenance-linked rows. ai_extract v2.1 citations (bbox or span) plus ai_parse_document element IDs allow each extracted cell to be traced back to its source, which meets the "traceable to source spans" requirement natively.
- The Xebia findings generalize: in-warehouse AI functions encourage re-running extraction inside views and queries. For determinism, extraction must be a versioned, append-only materialization keyed on content hash and prompt or model version, never a view.

### Gaps
- The status and docs of the *new* (non-legacy) Information Extraction and of Knowledge Assistant were not retrieved. The legacy page says a newer version exists.
- No independent accuracy benchmark for ai_extract v2.1 citations or confidence calibration.
- The AstraZeneca 400k-document figure is vendor-reported only.

---

## 3. Google Cloud: Document AI (Custom Extractor, Layout Parser), BigQuery AI.GENERATE_TABLE / AI.PARSE_DOCUMENT / ObjectRef, Vertex AI, and Gemini Enterprise

### Takeaway
Google offers two routes. (a) Document AI processors: Custom Extractor (Gemini-based, with fine-tuning, confidence and, as of June 2026, CEL validation rules [Preview]) and Layout Parser (hierarchy-aware chunks). (b) In-warehouse SQL: ObjectRef multimodal tables, AI.GENERATE_TABLE with a typed `output_schema` [GA November 2025], and AI.PARSE_DOCUMENT [GA November 2, 2026], which wraps the Document AI layout parser. BigQuery data agents with **verified queries** provide the agent-facing SQL layer and are publishable into Gemini Enterprise [GA October 14, 2026]. Rapid processor-version deprecation is the main reproducibility risk.

### Cited Findings
- **Custom Extractor** training options: a fine-tuned foundation model (generative; about 0-50+ documents; recommended first for variable layouts such as contracts, invoices and payslips), a custom model for layout variation (about 10-100+ documents) and a template model (about 3 documents). Confidence scores (0-1) support thresholds and manual review. — [Google docs: Custom extractor overview](https://docs.cloud.google.com/document-ai/docs/custom-extractor-overview)
- The generative Custom Extractor went GA on January 11, 2024 and is covered by the Document AI SLA. Google says it delivers structured data "with no training required". **[customer-reported]** Iron Mountain implements processors "in hours instead of days or weeks", and Automation Anywhere reports deployment more than 2x faster and maintenance costs halved. Processor versions are deprecated 6+ months after a new stable version. — [Google Cloud blog: Custom Extractor GA (2024)](https://cloud.google.com/blog/products/ai-machine-learning/document-ai-custom-extractor-powered-by-generative-ai-is-now-ga)
- **Version churn (release notes):**
  - Custom extractor v1.2/v1.3 inaccessible from September 24, 2025; v1.4 inaccessible from February 5, 2026.
  - Legacy processors (including `pretrained-foundation-model-v1.0`) discontinued June 30, 2026.
  - New previews: Gemini 3 Pro and Flash (January 2026; the global endpoint is "not compliant with Data Residency (DMZ)"), Gemini 3.5 Flash (July 17, 2026) and Gemini 3.1 Flash Lite (September 21, 2026).
  - Document validation and correction with CEL rules [Preview], June 4, 2026.
  - Automated schema extraction [Preview], November 12, 2025.
  - An upgrade path for fine-tuned processors (v1.4→v1.5) [Preview], March 31, 2026.
  — [Document AI release notes](https://docs.cloud.google.com/document-ai/docs/release-notes)
- **Layout Parser** outputs a tree-structured `DocumentLayout` (headings, paragraphs, tables, figures) and context-aware chunks carrying ancestor headings and table headers. Gemini-based versions (v1.5 on 2.5 Flash/Pro, v1.6 on Gemini 3, v3.1-lite) are Preview or RC; v1.0 is the stable default. Limits: online 20 MB and 15 pages per PDF; batch 1 GB and 500 pages. GA formats are PDF, HTML, DOCX, PPTX, XLSX and XLSM. Bounding boxes are supported only for v1.0 (per the February 16, 2026 release note). — [Google docs: Layout parser](https://docs.cloud.google.com/document-ai/docs/layout-parse-chunk); [release notes](https://docs.cloud.google.com/document-ai/docs/release-notes)
- **Pricing (per 1,000 pages):**
  - Enterprise OCR: first 1,000 free, then $1.50 (down to $0.60 above 5M).
  - Layout Parser: $10.
  - Custom Extractor and Form Parser: $30 (down to $20 above 1M).
  - Custom classifier and splitter: $5.
  - Custom processors also pay hosting ($0.05 per hour).
  - The generative and custom-model extractor cost the same.
  - Failed requests (4xx/5xx) are not billed.
  — [Google: Document AI pricing](https://cloud.google.com/document-ai/pricing)
- **AI.GENERATE_TABLE** runs Gemini over a table or query with a `prompt` column. `output_schema` takes typed fields (STRING, INT64, FLOAT64, BOOL, ARRAY, STRUCT) with NOT NULL and OPTIONS(description, enum). Output columns are the schema columns plus `full_response` and `status`. Temperature 0 "always selects the highest-probability response"; if unset, the model chooses. `max_output_tokens` is at most 8,192. **Known issue:** a job can succeed while some rows contain "RESOURCE EXHAUSTED", so rows need retry handling. — [BigQuery docs: AI.GENERATE_TABLE](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/bigqueryml-syntax-generate-table)
- **BigQuery release-note timeline:**
  - AI.GENERATE_TABLE first appeared April 3, 2025 and went GA November 18, 2025; throughput improved more than 100x on July 31, 2025.
  - Field descriptions in output_schema went GA February 12, 2026.
  - ObjectRef direct input to AI functions went GA June 12, 2026.
  - OBJ.LIST went GA September 30, 2026.
  - AI.AGG went GA October 13, 2026, with output_schema.
  - **Publishing a Conversational Analytics agent in Gemini Enterprise went GA October 14, 2026.**
  - **AI.PARSE_DOCUMENT went GA November 2, 2026.** It uses the Document AI layout parser to extract titles, headings, paragraphs, lists, tables and images into structured JSON.
  — [BigQuery release notes](https://docs.cloud.google.com/bigquery/docs/release-notes)
- **ObjectRef / multimodal tables:** an ObjectRef is a STRUCT of GCS metadata plus an authorizer (a connection, or NULL for end-user credentials). It can be stored in standard tables next to structured columns. ObjectRefRuntime access URLs expire within 6 hours, so persist the ObjectRef and regenerate runtime URLs as needed. Functions include OBJ.MAKE_REF, OBJ.FETCH_METADATA, OBJ.GET_ACCESS_URL and OBJ.LIST. The AI functions that accept ObjectRef are AI.GENERATE / GENERATE_TABLE / BOOL / INT / DOUBLE, AI.CLASSIFY, AI.IF, AI.SCORE and embeddings. Limits are 20 connections per project and region, and references to at most 5 other projects. — [BigQuery docs: Analyze multimodal data](https://docs.cloud.google.com/bigquery/docs/analyze-multimodal-data)
- **Data agents (Conversational Analytics):** knowledge sources are tables, views, graphs and UDFs, up to 100 per agent. **Verified queries** (formerly "golden queries") are SQL the agent uses when they match a prompt; they support parameters. Recommended context priority is verified queries > glossary > instructions. Agents are read-only (no DML or remote functions) and respect VPC-SC. GQL graph queries need an Enterprise or Enterprise Plus reservation. Cost is the BigQuery compute of the generated queries. — [BigQuery docs: Conversational analytics](https://docs.cloud.google.com/bigquery/docs/conversational-analytics)
- **[customer-reported]** Giles AI uses Document AI parsing plus Gemini Pro: 95% extraction accuracy, an 85% reduction in clinical research task time and 98% AI-to-human agreement. — [Google Cloud customer: Giles AI](https://cloud.google.com/customers/giles)
- **[customer-reported, internally inconsistent]** MediConCen (medical insurance claims): the headline says "98% field-level data extraction accuracy". The body quote says "more than 95% ... while other models hit only 70-80%". It also claims claim processing fell from days to hours and the straight-through rate rose 100%. BigQuery is only *planned*, for fraud similarity. — [Google Cloud customer: MediConCen](https://cloud.google.com/customers/mediconcen)

### Inferences
- With AI.PARSE_DOCUMENT GA, Google now matches Snowflake and Databricks on SQL-native parsing. The canonical BigQuery pattern is: OBJ.LIST or an object table → ObjectRef column → AI.PARSE_DOCUMENT and/or AI.GENERATE_TABLE(output_schema) → typed table → verified queries in a data agent → Gemini Enterprise.
- Unlike Databricks ai_extract v2.1, AI.GENERATE_TABLE documents no per-field citations or confidence. Document AI Custom Extractor offers confidence scores, and Layout Parser offers bounding boxes only on v1.0. Source-span traceability on Google therefore usually needs the Document AI processor path (Document object with page anchors) rather than AI.GENERATE_TABLE.

### Gaps
- Vertex AI RAG Engine and Gemini Enterprise connector-side handling of unstructured data were not researched in depth.
- No independent benchmark of Custom Extractor accuracy; Google publishes no numeric accuracy figures in the sources read.
- AI.PARSE_DOCUMENT pricing (presumably Layout Parser rates) was not confirmed.

---

## 4. Microsoft: Azure AI Document Intelligence, Azure Content Understanding, Fabric AI Functions and data agents, Azure AI Search, and Foundry IQ

### Takeaway
Microsoft has consolidated document IDP under **Content Understanding** in Foundry Tools (GA API 2025-11-01; agentic mode in the 2026-06-01 preview). It has schema-based extract, classify and generate fields with per-field **confidence and source grounding**, and you bring your own Foundry LLM deployment. Document Intelligence v4.0 remains GA; Microsoft itself positions it as giving "reliable deterministic extraction from structured documents". On the retrieval side, Fabric data agents do read-only NL2SQL/DAX/KQL over lakehouse tables but explicitly don't support unstructured files. Foundry IQ (on Azure AI Search agentic retrieval) is a search layer whose query reconstruction "isn't guaranteed".

### Cited Findings
- **Content Understanding**:
  - An analyzer configures content extraction (OCR, layout, tables, barcodes, formulas), segmentation, field extraction, confidence (0-1) and **grounding** ("identifies the specific regions in the content where each value was extracted"). Both are enabled via `estimateFieldSourceAndConfidence`.
  - Field methods: **Extract** (values as they appear; documents only), **Classify** (from a fixed set) and **Generate** (free generation).
  - It uses "multiple AI models to ... cross-validate".
  - Output is Markdown (for RAG) or schema JSON.
  - API 2025-11-01 is GA; 2026-06-01-preview adds agentic mode, in-page segmentation, signature detection and distilled training.
  — [Microsoft Learn: Content Understanding overview](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/overview)
- **CU agentic mode [Preview, 2026-06-01-preview]**:
  - Purpose: multistep reasoning, calculations, validation and visual analysis, returning schema fields.
  - "Isn't a replacement for human review in high-impact scenarios."
  - Limits: one input file per request; document analyzers only; `extract`-method fields not supported; no labeled samples.
  - Needs about 400,000 TPM per analyzer job on the Foundry deployment.
  - Uses the advanced contextualization rate.
  - The retired "pro mode" (2025-05-01-preview) must be migrated.
  — [Microsoft Learn: CU agentic mode](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/concepts/agentic-mode)
- **CU pricing model**:
  - Content extraction per 1,000 pages uses three meters (minimal for digital formats, basic for OCR, standard for layout).
  - Contextualization costs $1 per 1,000 pages (standard) or $3 per 1,000 pages (advanced; applies to labeled custom analyzers and agentic).
  - LLM tokens bill separately on your Foundry deployment.
  - Source grounding and confidence roughly double field-extraction tokens.
  - Worked example (illustrative rates): prebuilt-invoice on 10 pages ≈ $0.0837 (about $8.4 per 1,000 pages).
  - Failed requests aren't charged for extraction or contextualization.
  — [Microsoft Learn: CU pricing explainer](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/pricing-explainer)
- **Retail meters (East US, Azure Retail Prices API, fetched November 6, 2026):**
  - Content Understanding: Doc Content Extraction Standard $5.00 per 1,000 pages, Basic $1.00 per 1,000, Min $0.01 per 1,000 (Sync Standard $7.50 per 1,000); Std Contextualization $0.001 per 1,000 tokens; Advanced $0.003 per 1,000 tokens.
  - Document Intelligence: Read $1.50 per 1,000 pages ($0.60 at volume); Pre-built/Layout $10 per 1,000; Custom (extraction) $30 per 1,000; **Custom Generative $30 per 1,000**; Query fields add-on $10 per 1,000; Classifier $3 per 1,000; Training $3 per hour.
  — [Azure Retail Prices API](https://prices.azure.com/api/retail/prices)
- **Document Intelligence**:
  - v4.0 (2024-11-30) is GA and current, with no retirement date. v3.0 reaches end of support March 30, 2029.
  - Model types include read, layout, prebuilt and custom template/neural/generative.
  - Microsoft states that as part of CU capabilities Document Intelligence "provides high-accuracy and reliable deterministic extraction from structured documents", while CU offers LLM analyzers for complex content. [vendor claim]
  — [Microsoft Learn: Document Intelligence overview](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/overview)
- CU accuracy tuning (Foundry blog, March 24, 2026): improve field names and descriptions first, then add labeled examples per template (these add tokens). On 45 documents in 5 categories, labeled examples beat zero-shot on F1. Example: "Taxable Amount" confidence rose from 0.6 to 0.998 after one labeled sample. The headline says "up to 40% higher field-extraction accuracy", but the body text does not substantiate that figure. [vendor claim] — [Microsoft Foundry blog](https://techcommunity.microsoft.com/t5/microsoft-foundry-blog/closing-the-last-mile-in-document-ai-improving-extraction/ba-p/4502029)
- **Fabric AI Functions**:
  - Functions: `ai.extract` (with `ExtractLabel`, a JSON Schema with types, enums, nested, nullable and `additionalProperties=false`), `ai.classify`, `ai.generate_response` (`response_format` JSON Schema or Pydantic), `ai.summarize`, `ai.embed`, `ai.similarity` and others.
  - Interfaces: pandas, PySpark, T-SQL (`ai_extract`, `ai_classify` etc. in Warehouse and SQL endpoints) and Dataflow Gen2.
  - Multimodal input includes PDFs and images via `column_type="path"`. Helpers `aifunc.load` (folder → structured table) and `ai.infer_schema` are available.
  - The default model is gpt-5-mini with low reasoning effort. Prompts and outputs are not stored.
  - `ai.stats` reports exceptions, content-filtered rows and capacity-exceeded rows.
  - Requires F2+ capacity.
  — [Microsoft Learn: Fabric AI Functions](https://learn.microsoft.com/en-us/fabric/data-science/ai-functions/overview)
- **Fabric data agent [GA]**:
  - Generates read-only NL2SQL (Lakehouse and Warehouse), NL2DAX (semantic models), NL2KQL and Graph queries under the user's identity, with Purview DLP applied.
  - Configuration: up to 5 sources, up to 100 example queries per source, Git integration and deployment pipelines.
  - "Doesn't support unstructured data, such as .pdf, .docx, or .txt files". Lakehouse files must be ingested as tables.
  - Responses are capped at 25 rows × 25 columns, and chat history influences later answers.
  - The LLM can't be changed.
  — [Microsoft Learn: Fabric data agent](https://learn.microsoft.com/en-us/fabric/data-science/concept-data-agent)
- **Azure AI Search agentic retrieval / Foundry IQ**:
  - Flow: knowledge base → LLM query planning (skipped at `minimal` reasoning effort) → parallel keyword, vector or hybrid subqueries → semantic rerank → merged content plus optional references and activity log.
  - The GA API is 2026-04-01 (minimal, extractive retrieval); query planning and answer synthesis remain in the 2026-08-01-preview.
  - The docs state "Precise reconstruction of a query or response isn't guaranteed" when reissuing logged queries.
  — [Microsoft Learn: Agentic retrieval](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview)
- Foundry IQ is a permission-aware knowledge base over Blob, SharePoint, OneLake and web. It handles ACL sync and Purview labels, Entra on-behalf-of queries and citations. Some features are GA and some preview depending on API version. Microsoft positions three "IQs": Fabric IQ (ontologies, semantic models and graphs over OneLake), Work IQ (M365 signals) and Foundry IQ (enterprise knowledge). — [Microsoft Learn: What is Foundry IQ](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/what-is-foundry-iq)
- **[customer-reported, 2023]** Volvo Group uses Power Automate (Outlook intake) → Azure Data Factory preprocessing (denoise, rotate, trim) → Document Intelligence extraction and translation → XML or CSV per division → archive, with metrics in SharePoint and Power BI. Reported savings are about 10,000 manual hours (850+ per month); a 6-week PoC became a 4-month production rollout. — [Microsoft customer story: Volvo Group](https://www.microsoft.com/en/customers/story/1703814256939529124-volvo-group-automotive-azure-ai-services)

### Inferences
- Microsoft's agent-retrieval story splits in two. Exact answers over typed data go through Fabric data agents (tables only). Document recall goes through Foundry IQ (search). A deterministic system therefore needs CU or Document Intelligence output landed in Fabric Lakehouse or Warehouse tables, which then become data-agent sources. Microsoft provides the components but not a turnkey "CU → Fabric table" pipeline in the sources reviewed.
- CU's "Extract" method with grounding is the closest hyperscaler analogue to span-anchored extraction. Agentic mode disallows `extract` fields, so it trades provenance for reasoning.

### Gaps
- The list price page for CU (azure.microsoft.com) rendered placeholders. Rates come from the Retail Prices API, so verify regional variance.
- No 2025-2026 Microsoft customer story specifically about Content Understanding with metrics was found.

---

## 5. AWS: Textract, Bedrock Data Automation (BDA), the IDP reference architecture/accelerator, Bedrock Knowledge Bases structured retrieval, and Glue/Lake Formation

### Takeaway
AWS's document-to-table path is BDA blueprints (custom output at $0.04/page, with explicit and inferred fields, confidence, visual grounding and normalization/validation) or Textract plus Bedrock LLMs. These are orchestrated by the open-source **GenAI IDP Accelerator** (with HITL, evaluation and confidence assessment), and results land in S3, Aurora or Redshift. Agents reach the data through **Bedrock Knowledge Bases structured data retrieval**, a managed NL2SQL over Redshift and the Glue/SageMaker Lakehouse catalog. Its `GenerateQuery` returns SQL for review, which makes it the most "pin-able" text-to-SQL interface.

### Cited Findings
- BDA turns documents, images, audio and video into structured outputs, with classification, extraction, normalization and validation. It emphasizes "visual grounding and confidence scores". It can act as a Knowledge Bases parser for RAG. — [AWS docs: Bedrock Data Automation](https://docs.aws.amazon.com/bedrock/latest/userguide/bda.html)
- **BDA limits**:
  - Documents:
    - Async: up to 3,000 pages with the splitter and 500 MB; 20 pages and 200 MB in the console.
    - Sync: 10 pages and 50 MB.
    - Formats: PDF, TIFF, JPEG, PNG, DOC and DOCX. DOCX is converted to PDF, so "page number mapping will not work for DOCX".
    - Languages: EN, DE, ES, FR, IT and PT; no vertical CJK text.
  - Blueprints:
    - ≤100 leaf fields and ≤30 list leaf fields.
    - 40 blueprints per project and 100 versions per blueprint.
    - Field descriptions up to 600 characters; up to 100,000 JSON characters per blueprint.
  — [AWS docs: BDA prerequisites/limits](https://docs.aws.amazon.com/bedrock/latest/userguide/bda-limits.html)
- **BDA pricing**:
  - Documents: Standard Output $0.010 per page; Custom Output $0.040 per page for blueprints of ≤30 fields, plus $0.0005 per field per page beyond 30. Worked example: 40 fields → $0.045 per page.
  - Images: $0.003 (standard) / $0.005 (custom).
  - Blueprint prompt optimization: $0.010 per example page.
  - **Knowledge Bases Structured Data Retrieval (SQL generation): $2.00 per 1,000 queries.**
  — [AWS: Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) (dollar values resolved from AWS's published metered-unit price map for the page)
- **Textract (per 1,000 pages, first 1M / over 1M; US West Oregon page)**: Detect Text $1.50/$0.60; Tables $15/$10; Forms $50/$40; Queries $15; Forms+Tables+Queries $70/$55; Custom Queries $25/$15; AnalyzeExpense $10/$8. Layout is free with Tables. — [AWS: Textract pricing](https://aws.amazon.com/textract/pricing/)
- **KB structured data retrieval**:
  - Announced December 4, 2024, as a managed NL2SQL module over Amazon Redshift and SageMaker Lakehouse. It uses "database schema, previous query history, and other context".
  - Three APIs: RetrieveAndGenerate (answer), Retrieve (rows only, no LLM summary) and **GenerateQuery** (returns SQL only, "independently ... insert it into your workflow").
  - Aurora PostgreSQL is reachable via zero-ETL into Redshift.
  — [AWS What's New (Dec 2024)](https://aws.amazon.com/about-aws/whats-new/2024/12/amazon-bedrock-knowledge-bases-structured-data-retrieval); [AWS docs: KB structured data store](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-build-structured.html)
- Reference build (June 17, 2025): S3 → Glue Data Catalog → auto-mounted in Redshift with Lake Formation permissions → KB sync loads the schema into the NL2SQL module. The post gives no accuracy metrics. — [AWS ML blog: Conversational interfaces for structured data](https://aws.amazon.com/blogs/machine-learning/build-conversational-interfaces-for-structured-data-using-amazon-bedrock-knowledge-bases/)
- **AWS Guidance for multimodal data processing with BDA**:
  - Loan-origination path: custom blueprints per class (W-2, pay slip, driver's license, 1099, bank statement), with normalizations, transformations and validations. Then EventBridge on S3 put → Lambda → BDA, which splits documents into up to 20-page segments, classifies each page and applies the matching blueprint → JSON to S3 → downstream systems.
  - Claims path: BDA flags low-confidence items for adjudicators, and Bedrock Agents update an Aurora claims DB.
  — [AWS Solutions Guidance](https://docs.aws.amazon.com/solutions/multimodal-data-processing-using-amazon-bedrock-data-automation/)
- **GenAI IDP Accelerator** (open-source; post from August 22, 2025, updated March 2026, v0.5.0):
  - Modes: BDA mode or Textract+Bedrock mode, switchable via `use_bda`.
  - Stages: OCR, classification and packet splitting, extraction (optional agentic), assessment and confidence, summarization, and evaluation.
  - Built-in HITL review UI (Admin and Reviewer roles), few-shot examples, rule validation, Test Studio and KB integration.
  - **[customer-reported]** Competiscan: 85% classification and extraction accuracy, 35,000-45,000 campaigns per day, production in 8 weeks.
  — [AWS ML blog: Accelerate IDP with GenAI](https://aws.amazon.com/blogs/machine-learning/accelerate-intelligent-document-processing-with-generative-ai-on-aws)
- **[customer-reported]** Ricoh (March 4, 2026) runs a multi-tenant healthcare IDP on the accelerator, using Pattern 2 (Textract OCR + Bedrock classification and extraction):
  - Confidence: per-field 0-100% confidence "calculated by comparing Textract and Bedrock results". Fields below customer-set thresholds (typically 70-85%) go to human review. Payers require about 98-99% accuracy.
  - Accuracy: context-aware prompting improved accuracy 15-20% over static prompts.
  - Effort: 60-70% lower manual review cost; onboarding fell from weeks to days (previously 40-60 developer hours per customer).
  — [AWS ML blog: Ricoh](https://aws.amazon.com/blogs/machine-learning/how-ricoh-built-a-scalable-intelligent-document-processing-solution-on-aws)

### Inferences
- Ricoh's "confidence = agreement between two independent extractors (OCR-based vs. LLM-based)" is a practical, model-agnostic validation technique worth copying. It also gives a reproducible acceptance criterion.
- `GenerateQuery`, together with a human-approved SQL library, is the cleanest way on AWS to make agent retrieval deterministic. Generate once, review, store as a named query, and then execute the stored SQL.
- AWS's pattern lands extraction JSON in S3, then Glue/Athena or Redshift. Unlike Snowflake, Databricks and BigQuery, AWS has no SQL-native "AI function" inside Redshift for document extraction in the sources reviewed, so pipelines are event-driven Lambda/Step Functions code.

### Gaps
- Re:Invent 2025 announcements (any BDA or Redshift updates) were not reviewed.
- No independent BDA accuracy benchmark was found. BDA language support is limited (6 languages for documents).

---

## 6. Others: Oracle, SAP, IBM, Salesforce, ServiceNow and Palantir

### Takeaway
The application and database vendors embed extraction close to their system of record. Oracle uses Document Understanding (generative key-value extraction, January 2026), in-database text extraction (DBMS_VECTOR_CHAIN.UTL_TO_TEXT) and Select AI NL2SQL with `showsql` and `feedback`. SAP has Document AI premium editions. Salesforce's Document AI turns UDMOs into DMOs. ServiceNow's Now Assist Document Intelligence writes values into table fields. Palantir uses a typed Use LLM node writing to Ontology objects. IBM is the outlier: it builds its unstructured pipeline on open-source **Docling** (MIT) and Data Prep Kit.

### Cited Findings
**Oracle**
- `SELECT AI` actions: runsql (the default; supports RAG), **showsql**, explainsql, narrate, chat, **showprompt**, summarize, **feedback** (26ai only; natural-language corrections to improve later SQL), translate and agent. Oracle recommends contextual column names and **column comments**. It warns that LLMs "may generate SQL that ... returns incorrect results". Only SELECT is supported (no DML or DDL). — [Oracle 26ai docs: Select AI keyword](https://docs.oracle.com/en/database/oracle/oracle-database/26/selai/use-ai-keyword-enter-prompts.html)
- DBMS_VECTOR_CHAIN provides UTL_TO_TEXT (documents such as PDF, DOC, JSON, XML and HTML → plain text, via Oracle Text CONTEXT), UTL_TO_CHUNKS, UTL_TO_EMBEDDING(S), UTL_TO_SUMMARY, UTL_TO_GENERATE_TEXT (third-party LLMs) and UTL_TO_RERANK. — [Oracle 26ai docs: DBMS_VECTOR_CHAIN](https://docs.oracle.com/en/database/oracle/oracle-database/26/vecse/dbms_vector_chain-vecse.html)
- OCI Document Understanding added generative key-value extraction on January 16, 2026 (a custom model type using LMMs). Fields are defined via natural-language prompts plus optional few-shot examples, output is normalized JSON, and it claims "stable outputs and fewer hallucinations" via pre- and post-processing [vendor claim]. Regions: Chicago, London, Osaka and São Paulo. — [OCI release note](https://docs.oracle.com/iaas/releasenotes/document-understanding/generative-key-value-extraction.htm)

**SAP**
- SAP Document AI (formerly Document Information Extraction) handles structured, semi-structured and unstructured documents with OCR in 100+ languages. It has a review and validation UI with Joule and an accuracy framework that learns from user corrections. It is embedded in S/4HANA scenarios: Private Edition goods receipt (TM) and service initiation, with Public Edition 2508 adding QM, order management and inventory. A "Premium Plus" edition (generative AI, Instant Learning) is forthcoming. **[vendor claim]** processing is "up to 70 percent" faster. — [SAP Community: Document Information Extraction topic](https://pages.community.sap.com/topics/document-information-extraction)

**IBM**
- watsonx.data integration was launched June 11, 2025. Its Unstructured Data Integration provides low-code or Python SDK pipelines, permission-aware connectors, PII and HAP masking, quality filtering, confidence scoring, chunking and embedding, and incremental updates. **watsonx Document Understanding and Docling** handle parsing and entity/table extraction. It is built on IBM Research's Data Prep Kit (Linux Foundation). — [IBM announcement (ES)](https://www.ibm.com/es-es/new/announcements/ibm-announces-unstructured-data-capabilities-for-integration-and-governance); [IBM product page](https://www.ibm.com/products/watsonx-data-integration/unstructured-data-processing)
- **[vendor claim]** watsonx.data premium edition (GA) yields "40% more accurate AI than conventional RAG". The footnote describes this as IBM internal testing of answer correctness across 3 use cases on proprietary datasets versus vector-only RAG. It creates "structured derivatives" from extracted, normalized entities and carries source ACLs through. — [IBM announcement: watsonx.data](https://www.ibm.com/new/announcements/improving-ai-accuracy-with-ai-ready-unstructured-and-structured-data-on-ibm-watsonx-data)
- **Academic paper (vendor-published):** Docling Technical Report (arXiv 2408.09869, v5, December 2024) describes MIT-licensed PDF conversion using DocLayNet layout analysis and TableFormer table structure. It "runs efficiently on commodity hardware". — [arXiv 2408.09869](https://arxiv.org/abs/2408.09869)

**Salesforce**
- Data Cloud Document AI (September 18, 2025) takes documents landing as UDLOs/UDMOs (from S3 or GCS), extracts them with NLP, ML and LLMs, and stores results as **DLOs/DMOs** that "can be queried like any other structured data". These can join calculated insights and the data graph, and Agentforce agents view verified extracted data via flows or Apex. The post gives no metrics, GA dates or pricing. — [Salesforce blog: Document AI in Data Cloud](https://www.salesforce.com/blog/?p=125302)

**ServiceNow**
- Now Assist in Document Intelligence (Australia release, March 2026) has two modes. **Default** autofills fields and a reviewer checks every field. **Full automation** submits without review, with required fields filled or flagged missing, and can optionally pause when required fields are missing. Extracted values populate workspace fields that drive workflows. — [ServiceNow docs: Data extraction modes](https://www.servicenow.com/docs/r/FwUPJkMbovpxa7P5GwPYsg/BVEpNN1t1Q0ZVx55bYfxzw)

**Palantir**
- The Pipeline Builder **Use LLM** node has templates for classification, summarization, translation, sentiment and **entity extraction with typed outputs**. Struct outputs use strict parsing: a mismatch fails with "Cannot coerce to provided output type", and "Include errors" wraps the output with an error string. Model choice covers Palantir-provided or registered models, with temperature settings. Trial runs and an evaluation suite (including exact-match) are available. **Skip recomputing rows** caches outputs for unchanged inputs, which "requires deterministic upstream steps". — [Palantir docs: Use LLM node](https://www.palantir.com/docs/foundry/pipeline-builder/pipeline-builder-llm/)
- Enforced output types for LLM nodes were added June 5, 2024. As of October 2024 they were not exposed as an API outside Pipeline Builder. — [Palantir Community](https://community.palantir.com/t/pipeline-builder-now-supports-enforced-output-types-for-llm-nodes/350)
- The Ontology represents decisions as data (objects and links), logic (functions) and permissioned actions. Agents typically create *proposals* reviewed by operators, via AIP Logic or Use LLM in Pipeline Builder. — [Palantir docs: Platform overview](https://palantir.com/docs/foundry/platform-overview/overview/)

### Inferences
- Palantir's "Skip recomputing rows" and the strict struct coercion are the most explicit vendor mechanisms for *reproducible* LLM extraction: cache keyed by input, plus schema-enforced failure. These are good design references for an open-source toolkit.
- Oracle's `showsql` + `feedback`, AWS's `GenerateQuery`, Snowflake's verified queries, Genie's trusted assets and BigQuery's verified queries converge on one pattern: separate SQL *generation* from SQL *execution*, and curate a library of approved queries.
- IBM's choice of Docling shows that an open-source parser can be an enterprise default. That supports building a portable toolkit on Docling-class components to reduce lock-in.

### Gaps
- SAP Joule and HANA Cloud Knowledge Graph integration with extracted document data were not found; no SAP pricing was found.
- No metrics for the Salesforce, ServiceNow or Palantir document-extraction features in the official sources read.
- OCI Document Understanding custom generative pricing was not found.

---

## 7. The common enterprise implementation pattern, plus costs, limits, accuracy claims and lock-in

### Takeaway
Across vendors the practical pattern is:
1. Ingest to object storage or a stage with an event trigger.
2. Parse (OCR or layout) into an intermediate table.
3. Classify and route by document type.
4. Extract to a typed schema with confidence and, where available, grounding.
5. Validate (rules, cross-model agreement, thresholds) and send low-confidence fields to HITL.
6. Materialize to governed warehouse tables (UC, Horizon, Dataplex, Lake Formation, Purview).
7. Expose to agents through a semantic layer plus verified or trusted queries.

Determinism comes only from steps 6-7, by treating extraction as a versioned batch materialization, not something recomputed at query time. List prices span roughly $0.001-$0.07 per page depending on depth.

### Cited Findings
**Pipeline stages, as documented by vendors**
- Ingest and trigger: S3 "Object Created" → EventBridge → Lambda → BDA, then results JSON → S3 → downstream ([AWS Guidance](https://docs.aws.amazon.com/solutions/multimodal-data-processing-using-amazon-bedrock-data-automation/)). Spark Declarative Pipelines incremental parsing from SharePoint, S3 or ADLS ([Databricks blog](https://www.databricks.com/blog/pdfs-production-announcing-state-art-document-intelligence-databricks)). OpenFlow raw layer ([Snowflake blog](https://snowflake.com/en/blog/structuring-unstructured-data-cortex-aisql/)). OBJ.LIST / object tables → ObjectRef ([BigQuery release notes](https://docs.cloud.google.com/bigquery/docs/release-notes)).
- Classify and route: AI_CLASSIFY routing ([Snowflake docs](https://docs.snowflake.com/en/user-guide/snowflake-cortex/ai-documents)). BDA per-page classification to blueprints ([AWS Guidance](https://docs.aws.amazon.com/solutions/multimodal-data-processing-using-amazon-bedrock-data-automation/)). CU segmentation and classification ([Microsoft Learn](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/overview)).
- Extract with confidence and grounding: Databricks ai_extract v2.1 citations and confidence ([docs](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_extract)); CU confidence and grounding ([docs](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/overview)); Snowflake AI_EXTRACT scores ([docs](https://docs.snowflake.com/en/sql-reference/functions/ai_extract)); Document AI confidence ([docs](https://docs.cloud.google.com/document-ai/docs/custom-extractor-overview)).
- Validate and HITL:
  - Google CEL validation rules [Preview] ([release notes](https://docs.cloud.google.com/document-ai/docs/release-notes)).
  - Ricoh's Textract-vs-Bedrock agreement scoring with thresholds of 70-85% ([AWS blog](https://aws.amazon.com/blogs/machine-learning/how-ricoh-built-a-scalable-intelligent-document-processing-solution-on-aws)).
  - IDP Accelerator reviewer UI ([AWS blog](https://aws.amazon.com/blogs/machine-learning/accelerate-intelligent-document-processing-with-generative-ai-on-aws)).
  - ServiceNow default vs. full-automation modes ([docs](https://www.servicenow.com/docs/r/FwUPJkMbovpxa7P5GwPYsg/BVEpNN1t1Q0ZVx55bYfxzw)).
  - Snowflake guidance on per-field thresholds and SME review ([2024 blog](https://www.snowflake.com/en/blog/engineering/best-practices-snowflake-document-ai/)).
- Expose to agents with pinned SQL: Snowflake AI_VERIFIED_QUERIES ([release note](https://docs.snowflake.com/en/release-notes/2026/other/2026-04-05-semantic-views-verified-queries)); Genie trusted assets ([docs](https://docs.databricks.com/gcp/en/genie/concepts)); BigQuery verified queries ([docs](https://docs.cloud.google.com/bigquery/docs/conversational-analytics)); Bedrock GenerateQuery ([docs](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-build-structured.html)); Oracle showsql and feedback ([docs](https://docs.oracle.com/en/database/oracle/oracle-database/26/selai/use-ai-keyword-enter-prompts.html)); Fabric example queries ([docs](https://learn.microsoft.com/en-us/fabric/data-science/concept-data-agent)).

**Determinism caveats stated by vendors and practitioners**
- Databricks may swap the underlying model, and the version option pins only the schema ([Databricks docs](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_parse_document)).
- Snowflake AGENTIC "schema conformance is not guaranteed" ([Snowflake docs](https://docs.snowflake.com/en/user-guide/snowflake-cortex/parse-document)).
- Azure agentic retrieval: "Precise reconstruction of a query or response isn't guaranteed" ([Microsoft Learn](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview)).
- Output varied run to run even at temperature 0 ([Xebia](https://xebia.com/de/blog/versteckte-kosten-ki-dokumentenanalyse-produktion-databricks/)).
- BigQuery jobs can succeed with partial row failures ([BigQuery docs](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/bigqueryml-syntax-generate-table)).
- Google deprecates processor versions on a 6-18 month cadence ([Document AI release notes](https://docs.cloud.google.com/document-ai/docs/release-notes)).
- Fabric data agent answers are capped at 25×25 and history-dependent ([Microsoft Learn](https://learn.microsoft.com/en-us/fabric/data-science/concept-data-agent)).

**List-price comparison per 1,000 pages (USD; sources above)**

| Platform / operation | Price | Source |
|---|---|---|
| OCR only: Textract Detect / DI Read / Google Enterprise OCR | $1.50 (all three) | [Textract](https://aws.amazon.com/textract/pricing/), [Azure API](https://prices.azure.com/api/retail/prices), [Google](https://cloud.google.com/document-ai/pricing) |
| Layout: Google Layout Parser / Azure DI Layout / Azure CU standard extraction | $10 / $10 / $5 | same |
| Databricks ai_parse_document (by complexity) | $0.70-$6.30 | [Databricks](https://www.databricks.com/product/pricing/ai-functions) |
| Snowflake AI_PARSE_DOCUMENT LAYOUT (vendor blog) | ~$6.66 | [Snowflake blog](https://www.snowflake.com/en/blog/engineering/enterprise-scale-document-ai/) |
| Schema extraction: Google Custom Extractor | $30 ($20 above 1M) | [Google](https://cloud.google.com/document-ai/pricing) |
| Schema extraction: Azure DI Custom / Custom Generative | $30 | [Azure API](https://prices.azure.com/api/retail/prices) |
| Schema extraction: BDA custom output (≤30 fields) | $40 | [Bedrock](https://aws.amazon.com/bedrock/pricing/) |
| Schema extraction: Textract Forms+Tables+Queries | $70 | [Textract](https://aws.amazon.com/textract/pricing/) |
| Schema extraction: Databricks AI Extract (per 1,000 inputs) | $2.10-$4.20 | [Databricks](https://www.databricks.com/product/pricing/ai-functions) |
| Schema extraction: Snowflake AI_EXTRACT (worked example, 3-page invoices) | ~$12 | [Flexera](https://www.flexera.com/blog/finops/snowflake-ai-extract/) |
| Schema extraction: Azure CU invoice (worked example, ex-model choice) | ~$8.4 | [MS pricing explainer](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/pricing-explainer) |
| Agent NL2SQL: Bedrock KB SQL generation (per 1,000 queries) | $2.00 | [Bedrock](https://aws.amazon.com/bedrock/pricing/) |

**Lock-in signals**
- Proprietary output schemas: Databricks VARIANT element schema, Snowflake JSON, Document AI `Document` proto, BDA blueprint JSON, CU analyzer JSON.
- Model and version churn: Snowflake Document AI was decommissioned in 2026 ([BCR-2156](https://docs.snowflake.com/en/release-notes/bcr-bundles/un-bundled/bcr-2156)), Google custom extractor versions retire ([release notes](https://docs.cloud.google.com/document-ai/docs/release-notes)), and the Azure CU pro mode preview was retired ([MS Learn](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/concepts/agentic-mode)).
- Region limits: BDA documents support 6 languages ([AWS](https://docs.aws.amazon.com/bedrock/latest/userguide/bda-limits.html)); Google Gemini-3 processors are not DMZ-compliant ([release notes](https://docs.cloud.google.com/document-ai/docs/release-notes)); Snowflake requires cross-region inference outside select regions ([docs](https://docs.snowflake.com/en/sql-reference/functions/ai_parse_document)).
- The one open counterexample is IBM's use of MIT-licensed Docling ([arXiv 2408.09869](https://arxiv.org/abs/2408.09869)).

**Accuracy claims: classification by evidence quality**
- Vendor self-benchmarks:
  - Snowflake: 39.6% exact table match ([blog](https://www.snowflake.com/en/blog/engineering/enterprise-scale-document-ai/)).
  - Databricks: "3-5x lower cost" ([blog](https://www.databricks.com/blog/pdfs-production-announcing-state-art-document-intelligence-databricks)).
  - IBM: "40% more accurate than RAG" (internal) ([IBM](https://www.ibm.com/new/announcements/improving-ai-accuracy-with-ai-ready-unstructured-and-structured-data-on-ibm-watsonx-data)).
  - Microsoft: "up to 40%" (headline only) ([blog](https://techcommunity.microsoft.com/t5/microsoft-foundry-blog/closing-the-last-mile-in-document-ai-improving-extraction/ba-p/4502029)).
- Customer-reported:
  - YipitData 92-95% ([Databricks](https://www.databricks.com/customers/yipitdata/ai)).
  - Competiscan 85% ([AWS](https://aws.amazon.com/blogs/machine-learning/accelerate-intelligent-document-processing-with-generative-ai-on-aws)).
  - Giles 95% ([Google](https://cloud.google.com/customers/giles)).
  - MediConCen 95-98% (inconsistent) ([Google](https://cloud.google.com/customers/mediconcen)).
- Independent: Factored's matched A/B (ai_parse_document vs. CU) ([Factored](https://www.factored.ai/our-pov/databricks-ai-parse-document-rag)); Classmethod's AGENTIC smoke test ([Classmethod](https://dev.classmethod.jp/articles/snowflake-try-ai-parse-document-with-agentic-mode/)).
- No vendor publishes text-to-SQL accuracy for its agent layer (Cortex Analyst explicitly gives none) ([Snowflake docs](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst)).

### Inferences
- **Most effective enterprise-proven approach for deterministic agent retrieval.** Treat LLM extraction as an *offline, versioned ETL step*:
  - Key each run on a document content hash plus model/version/prompt/schema version.
  - Store per-field confidence and source anchors (page and bbox or char span).
  - Gate on validation rules and HITL.
  - Write to append-only typed tables, and serve agents through a semantic layer with curated, parameterized queries. Free-form NL2SQL becomes a fallback whose generated SQL is logged and promotable to the verified set.

  Every major vendor converges on this. They differ mainly in where the extraction runs (in-warehouse SQL function vs. external service) and in the strength of the provenance metadata. Databricks ai_extract v2.1 and Azure CU are strongest; Snowflake AI_EXTRACT and BigQuery AI.GENERATE_TABLE are weakest.
- For an open-source toolkit, lock-in risk sits mostly in (a) proprietary intermediate parse schemas and (b) silent model upgrades. A neutral intermediate representation, such as a Docling-style document model with element IDs and bboxes, plus explicit model pinning or recording would let any vendor parser or extractor be swapped in while keeping the retrieval layer deterministic.
- Cost is dominated by re-processing, not first-pass parsing. Practitioner evidence (Xebia; Flexera's "process each document once") suggests incremental, checkpointed materialization saves more than choosing the cheapest parser.

### Gaps
- No apples-to-apples independent benchmark across all five hyperscalers on extraction F1 and cost.
- No vendor publishes run-to-run variance statistics for extraction functions at temperature 0.
- Glue's specific role beyond catalog and Lake Formation (e.g., Glue ETL calling Bedrock) was not documented in the sources reviewed.
