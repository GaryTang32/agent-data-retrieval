# Specialist IDP / unstructured-data vendors and enterprise case studies of converting documents into databases

Scope: specialist vendors (LLM-native and incumbent IDP), not hyperscaler platforms. Research date: 2026-11-06. Every number below is vendor-reported unless it is explicitly marked as independent or peer-reviewed. Older information carries its year.

Reading guide for the report writer:
- "Accuracy" in vendor material is almost never defined. It could be field-level, document-level, or exact-match, and the eval set is rarely described.
- "Automation rate", "STP" and "touchless" are different metrics with different denominators.
- Treat any figure without a methodology as marketing.

---

## Q1. Which specialist vendors matter in late 2026, and how does each one approach conversion?

### Takeaway
The market has split into two groups.
- **LLM/VLM-native API vendors** sell per-page parse, classify, split and extract endpoints with JSON-schema output, citations or bounding boxes, and increasingly confidence scores. Examples: Reducto, Extend, LandingAI ADE, LlamaIndex LlamaParse/LlamaExtract, Datalab, Mistral OCR/Document AI, Unstructured, Contextual AI.
- **Incumbent IDP platforms** sell end-to-end workflows with validation stations, business rules, ERP integration and STP accounting, and have bolted generative extraction onto them. Examples: Hyperscience, Tungsten (ex-Kofax), ABBYY, UiPath, Automation Anywhere, Instabase, Indico, Rossum.

Both groups converge on the same pipeline: parse → classify/split → schema extraction → validation → human review → export.

### Cited Findings

**LLM-native API vendors**

- **Reducto**
  - Products: Parse, Extract, Split, Classify and Edit endpoints, plus "Deep Extract" and "Deep Split", which the pricing page describes as an "Agentic loop for near-perfect accuracy". Extract lists bounding boxes, structured schema and extraction citations. The pricing page does not mention confidence scores or HITL. — [Reducto pricing](https://reducto.ai/pricing)
  - Architecture: combines traditional OCR, VLMs and heuristic rules to segment pages, with specialized pipelines per content type. — [Reducto claims blog](https://reducto.ai/blog/extract-api-health-insurance-claims)
  - Uses traditional computer vision plus VLMs, with an "Agentic OCR" layer that reviews and corrects last-mile errors.
  - Funding: $75M Series B led by a16z (Oct 2025), $108M raised in total.
  - Scale: says it has processed over 1B pages. Named customers include Harvey, Mercor, Rogo, a Fortune 10 company and a top-5 hedge fund. — [Reducto Series B](https://reducto.ai/blog/reducto-series-b-funding)
- **Extend**
  - Every plan includes parsing, extraction, splitting, classification and editing, plus evaluation suites, Studio, Workflows and a "Review Agent". — [Extend pricing](https://www.extend.ai/pricing)
  - Brex deployment: OCR plus vision-model preprocessing for context engineering, dedicated models fine-tuned for Brex on private GPUs, and low-latency vs. async modes. — [Extend/Brex](https://www.extend.ai/blog/how-brex-reached-99-accuracy-across-millions-of-financial-documents)
  - Checkr deployment: returns structured outputs with confidence scores. High-confidence results auto-clear, low-confidence ones go to human review. — [Extend/Checkr](https://www.extend.ai/resources/checkr-case-study.md)
- **LandingAI Agentic Document Extraction (ADE)**
  - "Vision-first", using proprietary vision models (DPT-2) with agentic orchestration that "plans, makes decisions, and verifies output".
  - Grounding: page and coordinate grounding per chunk, bounding-box citations per extracted value, and table-cell grounding.
  - Confidence scores flag values for review. Schema-first extraction supports nested schemas and arrays.
  - Deployment: cloud, on-prem or VPC. Pricing is by quote. — [LandingAI ADE](https://landing.ai/agentic-document-extraction)
- **LlamaIndex (LlamaParse / LlamaExtract)**
  - Parse tiers: Cost Effective, Agentic and Agentic Plus. Auto Mode routes pages between tiers and is claimed to save up to 80%.
  - Extract targets: per document, per page or per table row. Citations and confidence scores are listed as Extract features. — [LlamaIndex pricing](https://www.llamaindex.ai/pricing)
  - Extract "guarantees that your data complies with the provided schema or provides helpful error messages". Tiers are Agentic Plus, Agentic, Cost Effective and Turbo. — [LlamaExtract docs](https://developers.llamaindex.ai/python/cloud/llamaextract/getting_started/)
  - `cite_sources` and `confidence_scores` are API booleans that default to false. Results come back in `extract_metadata`. The docs do not explain how confidence is computed. — [LlamaExtract options](https://developers.llamaindex.ai/python/cloud/llamaextract/features/options/)
- **Datalab** (the company behind open-source Marker, Surya and Chandra)
  - Hosted Convert tiers (Lite/Fast/Balanced/Accurate) and Extraction tiers (Turbo returns JSON only; Fast adds per-field citations). Schemas over 750 fields are not supported.
  - Open models are free for commercial use below $2M (Chandra) or $5M (Marker/Surya) revenue or funding thresholds. — [Datalab pricing](https://www.datalab.to/pricing)
- **Mistral OCR 3** (mistral-ocr-2512, 17 Dec 2025)
  - Outputs markdown with HTML tables (including colspan and rowspan). Claims a 74% win rate over OCR 2 on internal, fuzzy-matched benchmarks. OCR 4 has since been released. — [Mistral OCR 3](https://mistral.ai/news/mistral-ocr-3)
  - Annotations: `document_annotation` sends the OCR markdown plus the first 8 image bounding boxes to a vision LLM with a Pydantic/Zod/JSON schema. `bbox_annotation` annotates each figure. — [Mistral annotations docs](https://docs.mistral.ai/capabilities/document_ai/annotations/)
- **Unstructured.io**
  - Partition strategies: auto, fast (rule-based, "~100x faster"), hi_res (layout model), ocr_only and vlm. — [Unstructured partitioning docs](https://docs.unstructured.io/api-reference/partition/partitioning)
  - Its pricing page lists structured data extraction as "Coming Soon". Its strengths are chunking (by title, page, similarity, contextual), enrichments (NER, table-to-HTML) and 40+ connectors. — [Unstructured pricing](https://unstructured.io/pricing)
  - Inference: Unstructured remains RAG-ingestion-oriented rather than schema-to-database oriented.
- **Contextual AI Document Parser** (GA 13 May 2025)
  - Multi-stage vision + OCR + VLM pipeline with document hierarchy inference.
  - Tables come with confidence levels and bounding boxes.
  - In an internal test on 70+ SEC 10-K/10-Q filings (6,500+ pages), adding hierarchy metadata to chunks raised the RAG equivalence score from 69.2% to 84.0%. — [Contextual AI](https://contextual.ai/blog/document-parser-for-rag)
- **Sensible**
  - "Combines AI extraction with deterministic, rule-based methods", using SenseML as the configuration language. Outputs "typed, validated JSON", with "every field traceable".
  - Priced per document ("no token volatility"). Claims 75M+ documents processed. — [Sensible](https://www.sensible.so/)
- **Tensorlake: pivoted away from document AI**
  - In Jul–Aug 2025 Tensorlake shipped DocumentAI API v2: classify pages first, then scope each JSON-schema extraction to page classes, with source pages listed per record. — [Tensorlake page classification blog](https://www.tensorlake.ai/blog/announcing-page-classifications)
  - By Nov 2026 its pricing page and docs index cover only agent sandboxes, orchestration and versioned filesystems, with no document-ingestion pages. — [Tensorlake pricing](https://www.tensorlake.ai/pricing); [Tensorlake docs index](https://docs.tensorlake.ai/llms.txt)
  - This is a real 2026 market signal and should be flagged.
- **Aryn (Sycamore / DocParse / Luna)**
  - Aryn's 2024 paper describes DocSets: hierarchical documents with JSON properties, transformed by structured operators (filter, reduceByKey) and LLM operators (llmExtract, llmFilter).
  - Luna compiles natural-language queries into inspectable plans with lineage. On 30 NTSB questions it answered 20/30 correctly, versus 2/30 for a RAG baseline. — [Anderson et al., arXiv 2409.00847](https://arxiv.org/abs/2409.00847)
  - The last DocParse release note (5 Dec 2025) added "Agentic Property Extraction" with element-level attribution. — [Aryn release notes](https://docs.aryn.ai/release_notes.md)
  - Glean's acquisition of Aryn (reported March 2026) could not be confirmed from a primary source (see Gaps).
- **Vectara**
  - A RAG platform. Its relevant deterministic primitive is SQL-WHERE-like metadata filtering on `doc.` and `part.` fields with typed values (int, float, text, bool, lists). — [Vectara filter docs](https://docs.vectara.com/docs/learn/metadata-search-filtering/filter-overview)

**Incumbent IDP platforms**

- **Hyperscience (Hypercell)**
  - Over 50 predefined data types normalize values (e.g., dates to MMDDYYYY).
  - Ambiguous entities show candidate dropdowns to the reviewer, and duplicates go to an adjudication queue. — [Hyperscience](https://www.hyperscience.ai/?p=1524)
  - Agencies set target accuracy SLAs. Below-threshold *fields or characters* (not whole documents) go to reviewers. A Visual Page Classifier handles standardized forms, and Case Collation groups pages by case ID. — [Hyperscience public sector](https://www.hyperscience.ai/solutions/public-sector)
  - On AWS: deploys on EKS with RDS and SQS, and uses Claude 3 on Bedrock for validation blocks. — [AWS APN blog, Oct 2024](https://aws.amazon.com/blogs/apn/achieve-hyperautomation-for-insurance-document-processing-with-hyperscience-and-aws)
- **UiPath Document Understanding / IXP**
  - Metering per page: digitization 0 AI units, classification 0.2, extraction 0.8 with prior classification or 1.0 without. Generative Validation adds 1 unit per page. Training and serving models is free. — [UiPath metering](https://docs.uipath.com/document-understanding/automation-cloud/latest/user-guide/metering-charging-logic)
  - IXP combines document understanding, communications mining and generative extraction, with HITL validation, and feeds structured data to agents. — [UiPath Gartner 2026 blog](https://www.uipath.com/blog/ai/gartner-magic-quadrant-idp-report-2026)
- **Tungsten Automation** (ex-Kofax)
  - TotalAgility, DocAI Studio (no-code) and DocAI Accelerators (pretrained models).
  - Claims >10B documents a year, 25,000 organizations, and 8 of the top 10 global banks. — [Tungsten 2026 MQ release](https://www.01net.it/tungsten-automation-named-a-leader-in-the-2026-gartner-magic-quadrant-for-intelligent-document-processing/)
- **ABBYY Vantage**
  - Hybrid pattern in a lease-abstraction deployment:
    - Vantage classifies and segments 350+-field commercial leases (Preamble, Premises, Renewal Options).
    - GPT-4 Turbo extracts fields per segment.
    - Below-threshold fields go to Vantage's manual review station.
    - Blue Prism RPA enters the data.
  - Reported accuracy: 82%. — [ABBYY lease case](https://www.abbyy.com/customer-stories/generative-ai-idp-extracts-data-from-lease-agreements-with-82-accuracy)
- **Instabase AI Hub**
  - Pre-packaged blocks: digitize → classify → extract → validate → map into the settlement system. — [Instabase investment bank](https://www.casestudies.com/company/instabase/case-study/leading-global-investment-bank-customer-case-study)
- **Rossum Aurora / T-LLM**
  - A "highlighter" approach: the model locates and highlights values in the document rather than generating them. Rossum claims "0 hallucinated values" and 10x fewer training documents (Feb 2024, vendor claims). — [Rossum Aurora](https://rossum.ai/blog/rossum-aurora/)
  - Validation (Eurowag): formula fields for base and tax amounts, date-logic checks, and master-data matching. — [Rossum Eurowag](https://rossum.ai/customer-stories/eurowag/)
- **Indico Data**
  - An "Intake & Orchestration Platform" for insurance submissions (slips, SOVs, loss runs). — [Indico Convex](https://indicodata.ai/wp-content/uploads/2026/02/Indico-Data-and-Convex-Success-Story.pdf)
- **Nanonets**
  - A block-based workflow (simple, standard AI or complex AI blocks), with ERP and database integrations on the Growth plan. — [Nanonets pricing](https://nanonets.com/pricing)
- **Automation Anywhere Document Automation**
  - Classification, extraction, then routing to human reviewers for sensitive items. — [AA tax firm](https://www.casestudies.com/company/automationanywhere/case-study/401c-ai-streamlines-document-workflows-for-tax-service-leader)
- **Daloopa** (finance data, adjacent)
  - A verified, normalized fundamentals database from SEC filings for 5,500+ tickers, with every data point hyperlinked to its source. Exposed to agents via MCP.
  - Vendor benchmark:
    - Ungrounded frontier models answered financial retrieval questions at 11.2–63.8%.
    - Claude Opus 4.1 with the MCP reached 94.2%.
    - On a 170-company period-alignment subset, ungrounded models scored 7–43% vs. 92.4% with the MCP. — [Daloopa](https://daloopa.com/blog/product-updates/financial-data-quality-llm-workflows-mcp)

### Inferences
- The LLM-native vendors' core value is a typed record plus provenance (bounding box or page) plus, sometimes, a confidence score. That is exactly what a deterministic data lake needs at ingest time.
- None of these vendors makes extraction itself deterministic. The determinism has to come from persisting the extracted records once, versioned by snapshot, and querying those records with SQL or Cypher. Aryn's DocSet/lineage design and Daloopa's verified-table-plus-MCP design are the closest analogs to the user's goal.
- Rossum's "highlight, don't generate" principle and Sensible's "rules + LLM" are useful design patterns for an open-source toolkit:
  - Constrain values to document spans.
  - Run deterministic rules where the layout is fixed.

### Gaps
- Glean–Aryn: PitchBook (11 Mar 2026) and Techleap ("cloud service to shut down on 15 April") were seen only as search snippets. Both returned 403 on fetch, and Aryn's own release notes do not mention it. Treat it as reported but unverified.
- Not covered with primary sources: Eigen's current product inside Sirion; Docsumo's architecture beyond the PayU case; Vectara's table extraction; Contextual AI pricing; and Glean's post-acquisition document-extraction features.
- I found no vendor that publishes calibration curves for its confidence scores.

---

## Q2. How do vendors handle confidence, validation, HITL and STP, and which accuracy claims hold up?

### Takeaway
Production systems do not trust a single model score.
- They combine schema validation, deterministic business rules (math checks, date logic, master-data matching) and confidence thresholds, and route only failing fields to humans.
- Independent and academic work shows that raw LLM confidence (logprobs or verbalized) is poorly calibrated for extraction. Multi-signal confidence plus selective automation reaches roughly 99% accuracy at about 80% coverage.
- Nearly all headline "99%" figures are vendor marketing with no methodology.

### Cited Findings

**Confidence research**

- **Logprobs alone fail as a review trigger** — [Kumar, arXiv 2606.24420, IJCAI-ECAI 2026 RobustifAI workshop](https://arxiv.org/abs/2606.24420)
  - Logprob-mean, verbalized confidence and self-consistency all "flag nearly everything" at practical thresholds.
  - ExtractConf instead makes two structurally different LLM calls: a schema-guided "Hunter" and a holistic "Mapper". Their disagreement is fused with LLM uncertainty, OCR, image-quality and layout signals.
  - Results:
    - 0.928 AUROC on DocILE (55-field invoices, 26% failure rate) and 0.858 zero-shot on CORD.
    - 99.1% accuracy at 80% coverage.
    - Selective-prediction risk 70% lower than logprob-mean.
- **Box Extract** computes per-field confidence by sampling several responses (temperature, paraphrased prompts, shuffled field lists) and measuring value agreement.
  - Scores are returned as decimals with Low/Medium/High labels. Box says scores "approximate the actual probability" of correctness and tells customers to validate thresholds on their own documents.
  - Only Gemini 2.5 Flash and Pro are supported (Jan 2026). — [Box support](https://support.box.com/hc/en-us/articles/48546593181459-Confidence-Scores-via-API-in-Box-Extract-Jan-2026)

**Practitioner metric: "true automation rate"**

- Extend's head of engineering argues the metric that matters is the "true automation rate": documents processed fully end-to-end, with errors reliably caught. — [jxnl.co, Sep 2025](https://jxnl.co/writing/2025/09/11/how-extend-achieves-95-document-automation-lessons-from-eli-badgio/)
  - 85% true automation with the remaining 15% identified declaratively beats 98% accuracy where you cannot find the failing 2%.
  - Use declarative validation rules and guardrails to flag documents. Prefer deterministic code over LLMs wherever possible.

**Validation in practice**

- **Rossum / Eurowag:** formula fields recompute base and tax amounts, date checks block future-dated invoices, master-data matching validates vendors, then data posts to Coupa and SAP. Median review time for non-automated invoices is 45 s. — [Rossum Eurowag](https://rossum.ai/customer-stories/eurowag/)
- **Rossum / Trust:** extracted data is matched against 8 master datasets before ERP posting. — [Rossum Trust](https://rossum.ai/customer-stories/trust/)
- **Uber TextSense:** 7 stages (ingest, preprocessing, OCR, LLM extraction, business-rule post-processing, validation against existing data, metrics). Reviewers get side-by-side PDF and extracted-data views with soft warnings. — [Uber, Apr 2025](https://www.uber.com/blog/advancing-invoice-document-processing-using-genai/)
- **Hyperscience:** routes only the specific field or character below the target-accuracy SLA. — [Hyperscience public sector](https://www.hyperscience.ai/solutions/public-sector)
  - Its AWS blog says customers "configure the expected accuracy of a workflow", which sets how much is automated. Discrepancies between the ACORD form and supplemental documents become accept/reject tasks. — [AWS APN blog](https://aws.amazon.com/blogs/apn/achieve-hyperautomation-for-insurance-document-processing-with-hyperscience-and-aws)
- **LandingAI / Autyn:** per-field numeric confidence (e.g., 99.7% for an EIN vs. single digits for a low-signal field). Low-confidence fields route to a human processor. Every value carries a page and location tag. — [LandingAI/Autyn](https://landing.ai/case-studies/how-autyn-cut-loan-processing-from-2-hours-to-2-minutes-at-98-accuracy)

**Marketing flags on the "99.5%" claims**

- Hyperscience's AWS blog shows "[99.5%] accuracy" and "[98.0%] automation" in brackets, with no method. — [AWS APN blog](https://aws.amazon.com/blogs/apn/achieve-hyperautomation-for-insurance-document-processing-with-hyperscience-and-aws)
- The "IDC Customer Spotlight" PDF repeats 99.5% and a 615% three-year ROI. It is a Canva-made marketing piece built around a vendor product-marketing interview. — [IDC/Hyperscience spotlight, 2026](https://www.idc.com/wp-content/uploads/2026/09/Customer-Spotlight_Hyperscience-1.pdf)
- The 2026 MQ release again cites the IDC study (615% ROI, $8.6M a year, ~7-month payback) as a vendor citation. — [Hyperscience 2026 MQ](https://www.01net.it/hyperscience-recognized-as-a-leader-for-the-second-consecutive-year-in-the-gartner-magic-quadrant-for-intelligent-document-processing/)

**Marketing flags on vendor-run benchmarks**

- **LandingAI's DocVQA 99.16%:**
  - Run on the *validation* split (5,286/5,331) after excluding 18 "questionable" questions.
  - Exact-match scoring. The markdown baseline was 95.36%; JSON plus grounding plus guided prompting raised it.
  - Of the 45 errors, 18 were true parse failures.
  - The comparison against the test-set leaderboard is not like-for-like. — [LandingAI DocVQA, Nov 2025](https://landing.ai/blog/docvqa-benchmark)
- **Datalab OmniParseBench** (2,937 pages, 16,288 pass/fail tests, no LLM judge):
  - Ranks Datalab accurate 94.1, Reducto 90.8, LlamaParse 90.4, Mistral OCR 89.5, Extend 83.3, Azure 83.0.
  - Datalab created the benchmark and some test-creation models are also contestants. — [Datalab benchmarks](https://www.datalab.to/benchmarks)
- **LlamaIndex ParseBench** (~2,000 pages, 167k rules, 5 dimensions; Apr 2026):
  - Ranks LlamaParse Agentic first at 84.9%.
  - Content faithfulness is "mostly solved" at ~90%, i.e., about 1 in 10 pages still has errors. GPT-5 Mini and Haiku 4.5 score <8% on visual grounding. — [LlamaIndex ParseBench](https://www.llamaindex.ai/blog/parsebench)
- **Nanonets IDP leaderboard v1.5:**
  - Ranks Nanonets OCR-3 first at 85.9, then GPT-5.4 at 83.5.
  - Gemini 3.1 Pro has the top IDP-core score (89.6) but only 69.8 on OlmOCR. — [Nanonets leaderboard](https://benchmarking.nanonets.com/)
- **Extend's "LLM vs Document API" guide:**
  - Cites its own RealDoc-Bench (0.847 layout F1, 95.7% doc-QA).
  - Claims 20–40% retry overhead for raw LLM pipelines. Argues a 94%-accurate model "leaves 600 errors per 10,000 runs" and that LLMs fill missing fields with plausible values instead of null.
  - The 94% figure is unsourced. — [Extend guide](https://www.extend.ai/resources/llm-or-document-api-guide)

### Inferences
- Each vendor-run benchmark puts its author first, so cross-benchmark rankings disagree. For a toolkit, the only trustworthy accuracy number is one measured on the user's own golden set.
- STP is a *policy* outcome (threshold × validation-rule coverage), not a model property. Hyperscience's "configure expected accuracy" makes that explicit.
- For deterministic retrieval, the extraction layer should store, per field:
  - the value
  - the normalized type
  - the source span or bounding box
  - the confidence/validation status
  - the extractor version

  Queries can then filter on `status = 'verified'`, which makes an uncertain extraction a queryable state rather than a hidden error. Checkr's "human review as a first-class state" points the same way.

### Gaps
- No vendor publishes reliability diagrams for its confidence scores, and only Box documents its method.
- I could not find independent audits of any 99%+ STP claim.

---

## Q3. What does extraction cost per page, by vendor?

### Takeaway
List prices (Nov 2026) run from about $0.001 to $0.05 per page for API vendors, depending on tier. OCR-only is cheapest (Mistral $1–2 per 1k pages). Schema extraction with agentic or "deep" verification costs 2–5x plain parsing. Incumbents price by AI units, per field or per workflow block, and are hard to compare.

### Cited Findings
- **Reducto** (per 1k pages) — [Reducto pricing](https://reducto.ai/pricing)
  - Parse $10 (r-1) or $1 (r-1 mini); Extract $20 including parsing; Deep Extract $40.
  - Split $20; Deep Split $40; Classify $7.50 (first 5 pages); Deep Classify $15.
  - Edit $60.
  - Batch is 20% off Parse and Extract. $150 free credit.
- **Extend** ($0.01 per credit; per 1k pages) — [Extend pricing](https://www.extend.ai/pricing)
  - Parse $5 (Light) or $20 (Performance).
  - Extract $7, $30 or $50 (Light, Performance, Operator-1), with parse billed separately.
  - Split $5–20; Classify $5.
- **LlamaIndex**
  - PAYG $1.50 per 1k credits, Pro $1.25. Basic parse is "as low as 1 credit/page". — [LlamaIndex pricing](https://www.llamaindex.ai/pricing)
  - The ParseBench post gives ~1.2¢/page for Agentic and <0.4¢/page for Cost Effective. — [LlamaIndex ParseBench](https://www.llamaindex.ai/blog/parsebench)
- **Mistral OCR 3:** $2 per 1k pages ($1 batch); $3 per 1k for annotated pages. — [Mistral OCR 3](https://mistral.ai/news/mistral-ocr-3)
- **Datalab** (per 1k pages) — [Datalab pricing](https://www.datalab.to/pricing)
  - Convert $0.50 to $10.
  - Extraction $6 (Turbo/Fast), $15 (Balanced) or $20 (Accurate), plus fees.
  - Bounding-box add-ons $3–9.
- **Unstructured:** $0.015 per page after 10k free pages. — [Unstructured pricing](https://unstructured.io/pricing)
- **Nanonets:** per block run — $0.02 simple, $0.10 standard AI, $0.30 complex AI. Invoices use 4–6 blocks, which the vendor puts under $2 per invoice. — [Nanonets pricing](https://nanonets.com/pricing)
- **Instabase AI Hub:** 100 units per $1, charged *per field*, scaling with document length. — [Instabase pricing policy](https://docs.instabase.com/policies/pricing-policy)
  - 1–2 pages: 1 unit (standard) or 2 (advanced) per field.
  - Over 40 pages: 15 or 30 units per field.
  - Classification counts as 1 extra field. Spreadsheets are billed at 1,000 cells per page; email at 10,000 characters per page.
- **UiPath:** at most 1 AI unit per page for classification plus extraction; dollar price depends on licensing. — [UiPath metering](https://docs.uipath.com/document-understanding/automation-cloud/latest/user-guide/metering-charging-logic)
- **Per-document or quote-only:** Sensible (per document) and LandingAI ADE (by quote). — [Sensible](https://www.sensible.so/); [LandingAI ADE](https://landing.ai/agentic-document-extraction)
- **In-house comparison (Nilenso, KYC):** a Gemini 2.0 Flash pipeline cost about $1,000 per 1M documents vs. $10,000 for a third-party service, at similar p99 latency (7.9 s vs. ~10 s). — [Nilenso, May 2026](https://blog.nilenso.com/blog/2026/05/18/evals-before-prompts-building-an-llm-ocr-for-kyc/)

### Inferences
- Worked example: 20 fields on a 2-page document cost 20 units = $0.20 on Instabase standard, vs. $0.04 on Reducto Extract (2 pages × $0.02). Per-field pricing penalizes wide schemas; per-page pricing penalizes long documents.
- For a data lake, classify or split first and extract only the relevant pages:
  - Tensorlake's page-class scoping, Flatiron's "cheap parse to locate pages, premium parse for detail", and the KYC page-retrieval paper all show this cuts cost.
  - It also raises accuracy (see Q4 and Q6).

### Gaps
- Enterprise discount levels are undisclosed for every vendor.
- No official current Docsumo, Rossum or Hyperscience per-page price was found.

---

## Q4. What do real deployments report, by industry (accuracy, STP, ROI, failures)?

### Takeaway
Reported production outcomes cluster at:
- 90–99% field accuracy on narrow, high-volume document types
- 53–95% STP or automation
- review times cut to seconds per exception

Failures recur in predictable places: line items, handwriting, long mixed bundles, unseen layouts, and prior vendors or in-house builds. Almost every case is a vendor-curated story.

### Cited Findings

**Banking, lending and KYC**
- **Global investment bank, custody fax instructions** (Instabase): STP rose from 40% to >95%, accuracy 97.56%, >1,000 transactions a month, 20 FTEs freed. — [Instabase](https://www.casestudies.com/company/instabase/case-study/leading-global-investment-bank-customer-case-study)
- **Brex** (Extend; invoices, receipts, bank statements, W-9s):
  - Before: four legacy vendors with "mixed" accuracy; foundation models alone reached ~80–90% on raw PDFs.
  - After: 99%+ on many tasks. Accuracy is undefined. — [Extend/Brex](https://www.extend.ai/blog/how-brex-reached-99-accuracy-across-millions-of-financial-documents)
- **Autyn, mortgage lending** (LandingAI): field accuracy 94–98%; 1–3 min per borrower package vs. 1–2 h; 500+ loan files.
  - The prior OCR+LLM pipeline failed through mislabeled values on unseen layouts, hallucinations with no source link, retry loops with unpredictable cost, and no confidence signal. — [LandingAI/Autyn](https://landing.ai/case-studies/how-autyn-cut-loan-processing-from-2-hours-to-2-minutes-at-98-accuracy)
- **PayU, digital lending in India** (Docsumo): >100k applications a month, >95% processed without human intervention, 70% lower processing cost. Earlier vendor and in-house attempts had failed. — [Docsumo/PayU](https://www.casestudies.com/company/docsumo/case-study/automating-customer-onboarding-for-payu)
- **Indian KYC IDs** (Nilenso): 92% on a 50-document-per-type golden set.
  - Failures: fabricated but checksum-valid Aadhaar or PAN numbers on unreadable scans; names put in the father's-name field; the wrong number picked on driving licences. — [Nilenso](https://blog.nilenso.com/blog/2026/05/18/evals-before-prompts-building-an-llm-ocr-for-kyc/)
- **Industrial KYC, peer-reviewed-style study**:
  - 120 production documents (~3,000 multilingual scanned pages). The best OCR+VLM pipeline reached 87.27% field accuracy, up to +31.9 points over direct PDF-to-VLM.
  - Page-level retrieval was the dominant factor. — [Han et al., arXiv 2604.26462 / ACL 2026 Industry](https://arxiv.org/abs/2604.26462)

**Insurance**
- **Convex, specialty carrier** (Indico; slips, SOVs, loss runs):
  - Before: the prior vendor scored <60% accuracy, with up to 2 h per submission.
  - After: median 40 s per submission, live in production in 8 weeks.
  - Indico also claims a "97% implementation success rate — nearly five times the industry average", which implies the industry average is ~20% (unsourced). — [Indico Convex PDF](https://indicodata.ai/wp-content/uploads/2026/02/Indico-Data-and-Convex-Success-Story.pdf)
- **$50B carrier** (Indico): review went from 7 days to "under 15 minutes", but the headline also says "70% faster", an internal inconsistency. It also says the carrier's in-house automation effort "could not meet production requirements". — [Indico 50B carrier](http://indicodata.ai/customer-story-50b-carrier-cuts-underwriting-and-renewal-processing-time-from-7-days-to-15-minutes/)
- **Claims audit** (Reducto vendor page): claimed customer accuracy gains of "up to 20%" against an undisclosed baseline. — [Reducto claims blog](https://reducto.ai/blog/extract-api-health-insurance-claims)

**Healthcare**
- **Anterior, prior authorization** (Reducto): 99.24% accuracy (undefined) over 20,000+ documents; 95% of reviews completed within 1 minute. — [Reducto/Anterior](https://www.casestudies.com/company/reducto/case-study/how-anterior-accelerates-prior-authorization-and-clinical-decision-making-with-99-accuracy)
- **Flatiron Health, oncology NGS biomarker extraction** (Extend):
  - Built in-house from 2018 to 2023 with OCR, NLP and rules on Textract, where one misread table cell could change a table's meaning. Decided in 2024 to buy.
  - Extend reproduced 6 months of in-house work in 2 weeks. Oncologists do manual error analysis on sensitive deliveries.
  - No accuracy figure is given. — [Extend/Flatiron](https://www.extend.ai/resources/flatiron-case-study.md)
- **Trust, Portuguese medical invoices** (Rossum): ~80% automation in the first month, 95% extraction accuracy, 10 s review per document, staffing from 4 to 1 FTE, 150k invoices a year. — [Rossum Trust](https://rossum.ai/customer-stories/trust/)

**Accounts payable**
- **Rossum / Eurowag:** 70% automation across 60 entities; end-to-end time from 9 days to 4; on-time payments from 60% to >90%; median 45 s per exception. — [Rossum Eurowag](https://rossum.ai/customer-stories/eurowag/)
- **Thermo Fisher** (UiPath): 824k invoices a year, 53% STP, 82.4% "document reading" accuracy, processing time down 70%. — [UiPath/Thermo Fisher](https://www.casestudies.com/company/uipath/case-study/thermo-fisher-scientific-cuts-invoice-processing-time-by-70-for-824000-documents-processed-annually)
- **Canon** (UiPath): ~90% STP on 4,500 invoices a month. The previous RegEx extraction reached only 35–40% accuracy. Saves 6,000 h a year. — [UiPath/Canon](https://www.casestudies.com/company/uipath/case-study/canon-leverages-ai-for-document-processing-to-save-6000-hours)
- **Global tax firm** (Automation Anywhere): 1.5M invoices a year, 1,500+ document types, 90% extraction accuracy, human review kept for sensitive items. — [AA](https://www.casestudies.com/company/automationanywhere/case-study/401c-ai-streamlines-document-workflows-for-tax-service-leader)
- **Uber TextSense** (in-house, GPT-4):
  - ~90% overall accuracy: 35% of invoices at ~99.5%, 65% at >80%.
  - Handling time down 70%, cost down 25–30%, manual work halved.
  - Fine-tuned Flan-T5 and Llama 2 failed on line items after the first line and hallucinated. Business logic had to live in post-processing. — [Uber](https://www.uber.com/blog/advancing-invoice-document-processing-using-genai/)

**Logistics**
- **South Asian freight forwarder, bills of lading and invoices** (Docketry): 98% accuracy, 90% less processing time, 20% lower admin cost. Covers 60 BoL formats, outputs XML into CargoWise, live in ~3 months. — [Docketry](https://www.casestudies.com/company/docketry/case-study/leading-freight-forwarder-saves-20-of-administrative-costs-by-automating-bol-processing-in-3-months)
- **Nuvocargo, cross-border freight** (Extend): 97–99% accuracy (index summary only). — [Extend resources](https://www.extend.ai/resources)

**Government**
- **Cabinet-level federal benefits agency, handwritten mail claims** (Hyperscience, 2021):
  - Live about 2 months after contract. Processed 1M+ pages (115k claims) automatically in 3 months.
  - Accuracy >96% (vs. ~77% with the old solution) at >99% automation. — [DLT/Hyperscience PDF, 2021](https://www.dlt.com/sites/default/files/resource-attachments/2021-11/Hyperscience-Speeding-Claims-Processing.pdf)
- **Hyperscience public-sector page:** lists SSA, VA, USCIS and others. The SSA figures (250M retiree and survivor forms a year, "$100M+ annual savings") are vendor claims. — [Hyperscience public sector](https://www.hyperscience.ai/solutions/public-sector)

**Legal / contracts / real estate**
- **HomeLight, real-estate contracts** (Extend; 35+ fields, 150+-page packets):
  - An OpenAI-API prototype reached ~85%. With Extend: 93% in early tests, then >98%.
  - Human review was switched off after a month with zero corrections; review time per file went from 20+ min to 0. — [Extend/HomeLight](https://www.extend.ai/blog/homelight-hits-99-accuracy-and-eliminates-manual-review-with-extend)
- **Fast-food franchisor leases** (ABBYY + GPT-4 Turbo): 350+ fields; 30,000 documents a year previously handled by 25 outsourced FTEs; 82% accuracy. — [ABBYY](https://www.abbyy.com/customer-stories/generative-ai-idp-extracts-data-from-lease-agreements-with-82-accuracy)
- **Contract-ingestion client** (Extend; ~150–200k documents, ~1M pages): a characterization pass first found problematic suppliers, mishandled pricing terms and unexpected document types. — [jxnl.co](https://jxnl.co/writing/2025/09/11/how-extend-achieves-95-document-automation-lessons-from-eli-badgio/)

**Finance / 10-K**
- Daloopa's verified fundamentals plus MCP: 94.2% vs. 11–64% for ungrounded LLMs (vendor benchmark). — [Daloopa](https://daloopa.com/blog/product-updates/financial-data-quality-llm-workflows-mcp)
- Contextual AI's hierarchy metadata raised 10-K/10-Q RAG from 69.2% to 84.0% (vendor test). — [Contextual AI](https://contextual.ai/blog/document-parser-for-rag)

**Screening / background checks**
- **Checkr** (Extend; court extracts, police certificates, international IDs): 95–100% accuracy on held-out eval sets and 60–100% less human review time. — [Extend/Checkr](https://www.extend.ai/resources/checkr-case-study.md)

### Inferences
- Hard semi-structured documents (long leases, line items, handwriting, multilingual KYC) land at 82–92% field accuracy even in vendor-reported cases. Narrow, repetitive types (IDs, custody faxes, AP invoices from a known supplier base) reach 95–99%. A toolkit should expect per-document-type variance and report metrics per type.
- The common failure story is "prior vendor, regex or in-house OCR+LLM could not reach production". The fixes are classify-first, grounding, confidence routing and evals, not just a better model.
- "Accuracy" and STP are measured inconsistently (Thermo Fisher's 82.4% "reading accuracy" alongside 53% STP), so cross-case comparison is unreliable.

### Gaps
- No public XBRL-specific IDP case study from these vendors was found. XBRL is already structured, which may be why.
- Few case studies report what fraction of auto-approved records were later found wrong (post-STP error rate). Only HomeLight's "zero corrections in a month" comes close.
- I found no independently audited ROI study. The IDC-cited 615% ROI is vendor-sponsored.

---

## Q5. What do analysts say, and how is the market consolidating (2025–2026)?

### Takeaway
- Gartner launched its first IDP Magic Quadrant in Sept 2025 (18 vendors) and published a second in Sept 2026 (15 vendors). Hyperscience, Tungsten and UiPath were Leaders both years; ABBYY and Infrrd were also Leaders in 2025.
- Forrester (DMAP Wave Q2 2026) calls it "very much a 'buy' market".
- Everest's 2025 IDP PEAK Matrix rewards GenAI/agentic and zero-shot capabilities.
- Consolidation: process and spend suites are buying IDP specialists (Coupa–Rossum, Sirion–Eigen, Box–Alphamoon, SER–Klippa), and at least one LLM-native vendor exited the category (Tensorlake).

### Cited Findings

**Analyst reports**
- **Gartner MQ for IDP Solutions, 2025** (3 Sep 2025, inaugural): 18 vendors evaluated. Hyperscience was a Leader, "furthest for completeness of vision". — [Hyperscience 2025 MQ](https://www.hyperscience.ai/?p=13088)
- Infrrd also claims Leader status in the 2025 MQ. — [Infrrd Gartner page](https://www.infrrd.ai/featured/gartner-ebook-page)
- **Gartner MQ for IDP, 2026** (8 Sep 2026):
  - Hyperscience: Leader, "furthest for completeness of vision and highest for ability to execute among 15 vendors", and first in 3 of 4 Critical Capabilities use cases. — [Hyperscience 2026 MQ](https://www.01net.it/hyperscience-recognized-as-a-leader-for-the-second-consecutive-year-in-the-gartner-magic-quadrant-for-intelligent-document-processing/)
  - Tungsten: Leader for the second time (authors Vashisth, Emmott et al.). — [Tungsten 2026 MQ](https://www.01net.it/tungsten-automation-named-a-leader-in-the-2026-gartner-magic-quadrant-for-intelligent-document-processing/)
  - UiPath: Leader for the second year, positioning IXP as the document layer that feeds agents. — [UiPath 2026 MQ](https://www.uipath.com/blog/ai/gartner-magic-quadrant-idp-report-2026)
- **Forrester Wave: Document Mining and Analytics Platforms, Q2 2026:**
  - Forrester: DMAP is "very much a 'buy' market" and "Agentic AI can accelerate prototyping and automate parts of document mining workflows".
  - Hyperscience was a Leader and Customer Favorite and the only IDP pure play in the evaluation. — [Hyperscience Forrester release](https://www.01net.it/hyperscience-named-a-leader-and-a-customer-favorite-in-document-mining-and-analytics-platforms-evaluation/)
- **Everest IDP Products PEAK Matrix 2025** (May 2025): 29 vendors. Per Infrrd's summary, Leader status depended on agentic and GenAI-driven IDP, zero-shot learning, pre-built industry models and responsible-AI governance. — [Infrrd Everest release](https://www.infrrd.ai/newsroom/infrrd-named-a-leader-and-star-performer-peak-matrix-2025)
- All analyst content above comes from vendor press releases; the underlying reports are paywalled.

**Consolidation and funding**
- **Coupa acquired Rossum** (announced 12–14 May 2026, undisclosed terms). It extends a 2024 partnership in which Rossum was embedded in Coupa AP; the Rossum T-LLM is now applied across source-to-pay. — [CFOtech](https://cfotech.news/story/coupa-acquires-rossum-to-widen-ai-document-processing)
- **Sirion (CLM) acquired Eigen Technologies** (6 Jun 2024) to extend extraction "beyond contracts". — [Legal Tech Monitor](https://www.legaltechmonitor.com/2024/06/sirionlabs-acquires-eigen-technologies-to-expand-capabilities-and-financial-services-footprint/)
- **Box launched Box Extract** (Jan 2026), built on technology from its 2024 Alphamoon acquisition. — [idp-software.com Jan 2026](https://idp-software.com/news/2026-01-news/)
- **Reducto** raised a $75M Series B (Oct 2025), $108M in total. — [Reducto](https://reducto.ai/blog/reducto-series-b-funding)
- **Tensorlake** had moved from DocumentAI (2025) to agent sandboxes by Nov 2026. — [Tensorlake docs index](https://docs.tensorlake.ai/llms.txt)
- **Coforge closed its $2.4B Encora deal** (Jan 2026 news roundup). — [idp-software.com Jan 2026](https://idp-software.com/news/2026-01-news/)

### Inferences
- Gartner's IDP Leaders are incumbent workflow platforms with HITL, ModelOps and FedRAMP, while API-first LLM-native vendors (Reducto, Extend, LlamaIndex, Datalab) are funded by VCs and sell to AI-native builders.
- For an open-source toolkit, the "buy" consensus applies to regulated workflow operations, not to the parse/extract primitive, which is commoditizing quickly. Mistral at $1–2 per 1k pages and Datalab's open models are examples.
- Rossum and Eigen being absorbed into application suites (AP, CLM) suggests IDP value is migrating to "documents → system of record". That is analogous to the user's "documents → data lake" goal.

### Gaps
- Gartner's full 2025 and 2026 Leader lists, and Gartner's own market statements beyond the abstract ("over 100 vendors" per search snippet), were not readable; gartner.com returned 403.
- The IDC MarketScape IDP 2025–2026 and Deep Analysis "IDP Market Analysis 2026–2030: Rise of the Agents" (64 vendors per search snippet) pages could not be read (403, 405, or empty).
- The Glean–Aryn deal could not be verified (see Q1).

---

## Q6. What have enterprises found works best in practice?

### Takeaway
What works is a **hybrid, staged, eval-driven pipeline**:
1. Characterize the corpus first.
2. Classify, split and locate relevant pages.
3. Run schema-guided LLM/VLM extraction constrained to source spans.
4. Run deterministic post-processing and validation (math, dates, master data, checksums).
5. Route by calibrated confidence to human review on failing fields only.
6. Use corrections as continuously sampled golden data.

Pure templates break on layout variety, and pure LLMs hallucinate and cannot locate their own errors.

### Cited Findings

**Hybrid beats pure approaches**
- Canon's RegEx extraction reached 35–40% accuracy; ML-based Document Understanding reached ~90% STP. — [UiPath/Canon](https://www.casestudies.com/company/uipath/case-study/canon-leverages-ai-for-document-processing-to-save-6000-hours)
- Autyn's template and pattern extraction failed on unseen layouts, and its LLM-only extraction hallucinated with no traceability. — [LandingAI/Autyn](https://landing.ai/case-studies/how-autyn-cut-loan-processing-from-2-hours-to-2-minutes-at-98-accuracy)
- Sensible explicitly combines deterministic rules with LLM extraction. — [Sensible](https://www.sensible.so/)
- ABBYY's lease solution uses IDP for classification and segmentation and GPT-4 Turbo for per-segment extraction. — [ABBYY](https://www.abbyy.com/customer-stories/generative-ai-idp-extracts-data-from-lease-agreements-with-82-accuracy)
- On copy-heavy identity documents, a hybrid OCR-LLM framework with format-aware routing reached F1 1.0 on structured formats (table-based extraction) and 0.997 on images with PaddleOCR, at under 1 s latency. — [Wang & Shen, arXiv 2510.10138](https://arxiv.org/abs/2510.10138)

**Classify and locate before extracting**
- Page-level retrieval contributed 16.8–24 points in industrial KYC. Gains were >40 points on complex financial statements and ~8 on standardized payslips. — [Han et al., arXiv 2604.26462](https://arxiv.org/abs/2604.26462)
- Tensorlake: extraction should run "only where it's actually relevant". — [Tensorlake page classification blog](https://www.tensorlake.ai/blog/announcing-page-classifications)
- Flatiron: cheap parse to find pages, premium parse for detail. — [Extend/Flatiron](https://www.extend.ai/resources/flatiron-case-study.md)
- Extend: 100+-page healthcare PDFs bundle multiple referrals and need splitting. — [jxnl.co](https://jxnl.co/writing/2025/09/11/how-extend-achieves-95-document-automation-lessons-from-eli-badgio/)

**Golden datasets and evals before prompts**
- Nilenso's method:
  - Build a domain-expert-vetted golden set (50 per document type) and a field rubric before writing prompts.
  - Score hallucinations worse than nulls or "[unreadable]".
  - Evaluate per document type, since blended scores hide weak slices. — [Nilenso](https://blog.nilenso.com/blog/2026/05/18/evals-before-prompts-building-an-llm-ocr-for-kyc/)
- Extend's practices:
  - Task-specific evals at every pipeline step.
  - Continuous production sampling to catch drift.
  - Treat proprietary eval data as an asset.
  - "Automate when possible, augment otherwise".
  - Start with human augmentation, then convert to automation. — [jxnl.co](https://jxnl.co/writing/2025/09/11/how-extend-achieves-95-document-automation-lessons-from-eli-badgio/)
- Checkr measures on held-out eval sets and monitors for regressions. — [Extend/Checkr](https://www.extend.ai/resources/checkr-case-study.md)

**Prompting and templates matter more than hyperparameters**
- On Spanish electricity invoices, few-shot prompting beat zero-shot by >19 F1 points, while hyperparameters barely mattered.
- Template structure was the main driver of difficulty. Best F1: 97.61% (Gemini 1.5 Pro), 96.11% (Mistral-small). — [Gómez & Sánchez, arXiv 2604.25927](https://arxiv.org/abs/2604.25927)

**Put business logic in deterministic code, and focus labels where volume is**
- Uber: generative models found what was present in documents but did not learn internal data patterns, so business logic moved to post-processing.
- Uber concentrated labeling on high-volume suppliers with low field accuracy, and onboarded new templates through configuration. — [Uber](https://www.uber.com/blog/advancing-invoice-document-processing-using-genai/)

**HITL thresholds and incremental removal of humans**
- HomeLight removed human review only after a month with zero corrections. — [Extend/HomeLight](https://www.extend.ai/blog/homelight-hits-99-accuracy-and-eliminates-manual-review-with-extend)
- Hyperscience routes only below-SLA fields. — [Hyperscience public sector](https://www.hyperscience.ai/solutions/public-sector)
- ExtractConf shows a principled coverage/accuracy trade-off (99.1% at 80% coverage). — [arXiv 2606.24420](https://arxiv.org/abs/2606.24420)
- Box: validate thresholds per document type. — [Box](https://support.box.com/hc/en-us/articles/48546593181459-Confidence-Scores-via-API-in-Box-Extract-Jan-2026)

**Grounding and provenance as a requirement**
- In regulated lending, every value is tied to a page and location so it "must be defensible to an underwriter and auditor". — [LandingAI/Autyn](https://landing.ai/case-studies/how-autyn-cut-loan-processing-from-2-hours-to-2-minutes-at-98-accuracy)
- Brex flagged the lack of bounding boxes as a gap in in-house foundation-model options. — [Extend/Brex](https://www.extend.ai/blog/how-brex-reached-99-accuracy-across-millions-of-financial-documents)
- Rossum's "highlighter" design constrains values to document text. — [Rossum Aurora](https://rossum.ai/blog/rossum-aurora/)

**A structured, verified layer beats asking LLMs over raw documents**
- Daloopa: "The key is not necessarily the model itself, but rather the data that it is retrieving" (94.2% with verified data vs. ≤63.8% without; vendor benchmark). — [Daloopa](https://daloopa.com/blog/product-updates/financial-data-quality-llm-workflows-mcp)
- Aryn/Luna, a plan-based structured query over extracted properties, answered 20/30 vs. 2/30 for RAG on NTSB reports. Its failures were counting duplicates, overly generous LLM filters and query misreads, i.e., the non-deterministic LLM operators. — [arXiv 2409.00847](https://arxiv.org/abs/2409.00847)

### Inferences
Recommended pattern for the user's toolkit, synthesized from the above. It is an inference, not a vendor recommendation.
- **(a) Characterize:** run a cheap characterization and classification pass over the whole corpus.
- **(b) Extract once, stored:** extract per-document-type schemas once, with LLM/VLM extractors constrained to spans, and store the results. Do not extract at query time.
- **(c) Validate deterministically:** normalize types and run validation code (checksums, cross-field arithmetic, reference-data joins).
- **(d) Persist provenance and status:** store the value, source span or bounding box, confidence, validation status and extractor/model version.
- **(e) Route by policy:** send failures to review under a calibrated, per-document-type threshold policy.
- **(f) Snapshot:** publish immutable snapshots so agent queries (SQL or Cypher over typed records) are deterministic and auditable.
- **(g) Grow the golden set:** use review corrections as the golden set and regression tests.

Key design point: the "true automation rate" with catchable errors should be the toolkit's primary KPI, rather than raw accuracy.

### Gaps
- Little public evidence on long-term drift, i.e., how STP decays over years as layouts change. Extend mentions drift sampling but gives no figures.
- No controlled head-to-head of template vs. LLM vs. hybrid on the same enterprise corpus with cost was found; the evidence is per-case.
