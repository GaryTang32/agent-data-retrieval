# Document Ingestion and Parsing for an Agent-Retrievable Data Lake (state as of Nov 2026)

Scope: the ingestion and parsing layer only: parsers, OCR/VLM models, benchmarks, licenses, internal representation, chunking, provenance, and non-PDF sources. Research date: 2026-11-06. Items dated 2024 to 2025 are marked as older. "Vendor-reported" means the publisher of the tool or model ran the numbers.

---

## Q1. Which open-source parsers and pipelines lead today, and what are their licenses (especially commercial-use restrictions)?

### Takeaway
The field has split into two groups:
- **Pipeline/framework toolkits:** Docling, MinerU pipeline, Marker, and Unstructured.
- **Small specialized document VLMs (roughly 0.1B to 9B parameters):** PaddleOCR-VL 1.5/1.6, MinerU2.5(-Pro), GLM-OCR, dots.ocr, DeepSeek-OCR 2, olmOCR 2, Chandra 2, and others. These now top the leaderboards.

On licensing, Docling is the cleanest choice (MIT code, permissive default weights). The others carry real conditions:
- **MinerU:** moved from AGPL in 2026 to a custom "Apache 2.0 + thresholds" license.
- **Marker, Surya, and Chandra:** the code is Apache 2.0, but the weights are under a modified OpenRAIL-M with $5M revenue/funding thresholds and a competitor clause.
- **PyMuPDF:** AGPL or commercial.

### Cited Findings

**Docling (IBM Research Zurich, now under LF AI & Data)**
- The code is MIT. "Individual model usage follows the licenses of the original model packages." — [Docling GitHub](https://github.com/docling-project/docling)
- The default Docling weights are tagged apache-2.0, cdla-permissive-2.0, or mit, with "no revenue threshold or competitor clause." Docling can also load third-party VLM checkpoints such as `datalab-to/chandra-ocr-2` (tagged openrail). In that case the weight license follows whichever checkpoint is enabled. — [Particula Tech, Docling vs MinerU vs Marker (2026)](https://particula.tech/blog/docling-vs-mineru-vs-marker-pdf-parser)
- Docling is a project in the LF AI & Data Foundation. It started with IBM Research Zurich's AI for knowledge team. — [Docling GitHub](https://github.com/docling-project/docling)
- Docling has a VLM pipeline built on GraniteDocling (258M parameters). Python 3.10+ is required from v2.70.0. — [Docling GitHub](https://github.com/docling-project/docling)
- Granite-Docling-258M outputs DocTags and supports English, Japanese, Arabic, and Chinese. HF lists its license as "Open". *(Older: Oct 2025.)* — [Hugging Face blog, Supercharge your OCR Pipelines with Open Models](https://huggingface.co/blog/ocr-open-models)

**MinerU (OpenDataLab / Shanghai AI Lab)**
- The current LICENSE.md says "MinerU is licensed under Apache License 2.0" with additional terms:
  - Commercial use is allowed without a separate license unless you and your affiliates, on a consolidated basis, exceed "monthly active users (MAU) exceed 100 million" or "total monthly revenue exceeds USD 20 million."
  - Online services offered to third parties must disclose prominently that MinerU is used.
  - Missing either the commercial license or the attribution "terminate[s] automatically."
  — [MinerU LICENSE.md](https://raw.githubusercontent.com/opendatalab/MinerU/HEAD/LICENSE.md)
- The license history:
  - LICENSE.md changed five times between 2026-03-20 and 2026-04-17.
  - PyPI releases 3.0.9 and earlier declare AGPL-3.0. Releases 3.1.0 and later declare "LicenseRef-MinerU-Open-Source-License."
  - The torch and Pro-2605 weight repos are tagged apache-2.0. The ONNX and GGUF repos (the GGUF one is used on the default llama.cpp path) carry no license tag.
  — [Particula Tech](https://particula.tech/blog/docling-vs-mineru-vs-marker-pdf-parser)
- Conflict: one search summary reported that the English LICENSE.md listed only the MAU threshold, while the Chinese text and GitHub discussion #4928 cite the $20M monthly revenue threshold. The LICENSE.md fetched today contains both thresholds. Third-party registries such as ecosyste.ms still list MinerU as AGPL-3.0, which is stale. — [MinerU discussion #4928](https://github.com/opendatalab/MinerU/discussions/4928); [MinerU LICENSE.md](https://raw.githubusercontent.com/opendatalab/MinerU/HEAD/LICENSE.md)

**Marker / Surya / Chandra (Datalab)**
- The Marker code is Apache 2.0 as of v2.0.0 (2026-07-20). Versions through v1.10.2 were GPL-3.0. — [Particula Tech](https://particula.tech/blog/docling-vs-mineru-vs-marker-pdf-parser)
- The Marker weights, which load through Surya even when OCR is disabled, use a modified AI Pubs OpenRAIL-M license. They are free for research, personal use, and startups under $5M in funding or revenue; other commercial use needs a paid arrangement. — [Marker GitHub](https://github.com/datalab-to/marker)
- The OpenRAIL-M restrictions trigger on any of:
  - more than $5,000,000 in prior-year gross revenue;
  - more than $5,000,000 in total equity or debt funding;
  - offering a product that competes with Datalab. This clause has no research or personal-use carve-out.

  The license also has an attribution clause (clause 7) and a clause letting the licensor restrict usage remotely (clause 9). The money thresholds were $2,000,000 until 2026-07-20. Surya 0.22.1 has Apache-2.0 code and the same weight license. The HF tag reads only "openrail", so the terms appear only in each repo's LICENSE file. — [Particula Tech](https://particula.tech/blog/docling-vs-mineru-vs-marker-pdf-parser)
- Chandra (9B, 40+ languages) has an OpenRAIL license and was the only non-"open" model in HF's Oct 2025 comparison apart from Nanonets ("unclear"). — [HF blog (Oct 2025)](https://huggingface.co/blog/ocr-open-models)

**PyMuPDF / PyMuPDF4LLM**
- PyMuPDF is dual-licensed under AGPL-3.0 or a commercial license. MinerU 4.x uses pypdfium2 instead. — [Particula Tech](https://particula.tech/blog/docling-vs-mineru-vs-marker-pdf-parser)

**Specialized document VLMs (licenses as reported)**
- PaddleOCR-VL-1.5 (0.9B) is listed as Apache 2.0; the playbook says PaddleOCR "and its VL variants are Apache-2.0." It supports 111 languages and scores 94.5% on OmniDocBench v1.5. — [FullStackCV OCR playbook (reviewed 2026-04-22)](https://fullstackcv.github.io/playbook/ocr/); see also the [PaddleOCR-VL-1.5 paper](https://arxiv.org/pdf/2601.21957)
- DeepSeek-OCR 2 is listed as Apache 2.0, and GLM-OCR (0.9B) as MIT with an Apache-2.0 layout component. Another source says GLM-OCR is Apache-2.0, so sources conflict on GLM-OCR. — [iconicompany OCR/VLM 2026](https://iconicompany.com/en/blog/best-llm-for-ocr-2026); [regolo.ai](https://regolo.ai/?p=2301)
- HF's Oct 2025 table, with sizes and output formats *(older)*:
  - Nanonets-OCR2-3B (4B): license unclear.
  - PaddleOCR-VL (0.9B, 109 languages, Markdown/JSON/HTML).
  - dots.ocr (3B, Markdown/JSON).
  - olmOCR-2 (8B, English only).
  - Granite-Docling-258M (DocTags).
  - DeepSeek-OCR (3B, about 100 languages).
  - Chandra (9B, OpenRAIL).
  - Qwen3-VL (9B, general).

  All except Chandra and Nanonets are described as open. — [HF blog](https://huggingface.co/blog/ocr-open-models)
- LayoutLMv3 is "CC-BY-NC-SA-4.0 — non-commercial only," a reminder that some classic layout models are not commercially usable. — [FullStackCV playbook](https://fullstackcv.github.io/playbook/ocr/)

**Unstructured**
- The open-source library partitions documents into typed elements with rich metadata (see Q4). Its license was not stated on the docs page fetched. — [Unstructured docs: Document elements](https://docs.unstructured.io/open-source/concepts/document-elements)

### Inferences
- For a permissively licensed open-source toolkit, Docling (MIT, permissive default weights) is the safest default orchestration layer. PaddleOCR-VL (Apache 2.0) is the strongest permissively licensed VLM backend on OmniDocBench.
- MinerU is usable by most adopters, but its threshold, attribution, and auto-termination terms make it "not OSI open source." A toolkit that bundles it should isolate it as an optional plugin.
- Marker, Surya, and Chandra should be optional backends only. Downstream users above $5M revenue or funding, or anyone competing with Datalab, need a commercial license.
- Weight licenses and code licenses diverge often, and HF tags can be misleading ("openrail", or untagged GGUF/ONNX repos). The toolkit should record a model-license manifest for every weight repo and revision it downloads.

### Gaps
- I could not confirm these licenses this session: dots.ocr / dots.mocr weights, PaddleOCR-VL-1.6, the top OmniDocBench entries (OXR-1.0, TeleOCR, OvisOCR2, Unlimited-OCR), olmOCR 2 (believed Apache 2.0, but not verified here), Unstructured OSS (believed Apache 2.0, not verified here), and PyMuPDF4LLM specifically.
- I did not fetch LlamaParse terms. It is a proprietary SaaS (LlamaIndex) and not open source.

---

## Q2. What do benchmarks show (OmniDocBench and others), which results are vendor-run vs independent, and where do parsers still fail?

### Takeaway
On OmniDocBench v1.6, specialized document VLMs now score about 93 to 97 overall, against 78 to 86 for pipeline tools (MinerU pipeline, Marker) and 84 to 93 for general frontier VLMs. olmOCR-Bench, an English unit-test benchmark, tops out around 86 (Chandra 2), and Docling scores much lower there.

Nearly every number is self-reported or run by an interested party:
- The OmniDocBench maintainers (OpenDataLab) also build MinerU.
- Datalab runs the Marker comparisons.
- LlamaIndex built ParseBench.

There is no neutral head-to-head of Docling, MinerU, Marker, and LlamaParse at current versions. The remaining weak spots are charts, semantic formatting (strike-through, super/subscripts, links), visual grounding, cross-page tables, and real-world photographed pages.

### Cited Findings

**OmniDocBench (OpenDataLab; leaderboard labeled v1.6_full, fetched Nov 2026)**
- The benchmark has 1,651 PDF pages covering 10 document types, 5 layout types, and 5 languages. The data_source field lists 9 types, so the README is internally inconsistent.
- Update history:
  - v1.0 to v1.5 on 2025/09/25: 374 pages added and a new Overall formula.
  - v1.5 to v1.6 on 2026/04/10: 296 pages added and Multi-Granularity Adaptive Matching.
  - v1.7 on 2026/04/30.
  - TeleOCR, OvisOCR2, and Unlimited-OCR added on 2026/09/11.

  — [OmniDocBench GitHub](https://github.com/opendatalab/OmniDocBench)
- Overall scores. Metrics in brackets are text edit distance (lower is better), formula CDM, table TEDS, and reading-order edit (lower is better). — [OmniDocBench GitHub](https://github.com/opendatalab/OmniDocBench)
  - **Specialized VLMs:**
    - OXR-1.0: 97.03 (text 0.024, CDM 96.93, TEDS 96.61, RO 0.122)
    - TeleOCR: 96.91
    - OvisOCR2: 96.47
    - PaddleOCR-VL-1.6: 96.34 (TEDS 94.76)
    - MinerU2.5-Pro: 95.75
    - GLM-OCR: 95.22
    - PaddleOCR-VL-1.5: 94.93
    - PaddleOCR-VL: 94.18
    - Unlimited-OCR: 94.00
    - Qianfan-OCR: 93.90
    - MinerU-2.5: 93.04
    - MonkeyOCR V2: 91.80
    - dots.ocr: 90.77
    - OpenDoc-0.1B: 90.67
    - DeepSeek-OCR 2: 90.25
    - HunyuanOCR: 89.95
    - Dolphin-v2: 89.50
    - olmOCR: 85.74
    - Mistral OCR: 85.66
    - Nanonets-OCR-s: 83.61
  - **General VLMs:**
    - Ovis2.6-30B-A3B: 93.70
    - Gemini 3 Pro: 92.91
    - Gemini 3 Flash: 92.62
    - Qwen3-VL-235B: 89.78
    - GPT-5.2: 86.59
    - Kimi K2.5: 84.53
    - InternVL3.5-241B: 83.76
  - **Pipeline tools:**
    - MinerU-Pipeline: 86.47 (TEDS 81.88)
    - Marker: 78.44 (text 0.157, TEDS 65.77, RO 0.243)
    - Docling is not listed on the leaderboard.
- Caveat: some OmniDocBench annotations come from SoTA VLMs or conventional OCR rather than only humans. HF calls CC-OCR the only option for evaluation beyond English and Chinese, though its document quality and diversity are lower. — [HF blog (Oct 2025)](https://huggingface.co/blog/ocr-open-models)

**olmOCR-Bench (Ai2; unit-test style, about 1,403 PDFs, English-centric)**
- The olmOCR 2 paper reports these scores *(older: Oct 2025)*:
  - Chandra OCR 0.1.0: 83.1 ± 0.9
  - olmOCR 2: 82.4
  - PaddleOCR-VL: 80.0 ± 1.0
  - dots.ocr: 79.1 ± 1.0

  — [olmOCR 2 paper, arXiv 2510.19817](https://arxiv.org/pdf/2510.19817); [HF blog](https://huggingface.co/blog/ocr-open-models)
- Datalab-reported Marker v2 numbers (Marker README; the harness is in `benchmarks/`, with no independent verification described). First figure is overall, second is digital-only where given:
  - Chandra 2 (hosted): 85.8
  - Gemini Flash 3.5 (API): 76.4 / 79.1
  - Marker balanced: 76.0 / 83.5
  - MinerU pipeline: 72.7 / 83.3
  - Marker fast: 66.6 / 71.6
  - Docling: 50.3 / 64.0
  - Marker fast no-OCR: 43.6 / 55.8
  - liteparse: 22.4 / 27.3

  — [Marker GitHub](https://github.com/datalab-to/marker); [MarkTechPost, 2026-07-24](https://www.marktechpost.com/2026/07/24/datalab-marker-v2-vs-mineru-docling-and-liteparse-benchmark-breakdown/)
- Aggregator snapshots (May 2026) list Chandra OCR 2 at 85.9, dots.mocr at 83.9, and DeepSeek-OCR at 75.7%. PaddleOCR-VL-1.6 has no published olmOCR-Bench score. — [benchmarklist.com olmOCR-bench](https://benchmarklist.com/benchmarks/olmocr_bench/); [Docsumo 2026](https://www.docsumo.com/blog/best-ocr-models); [CodeSOTA](https://www.codesota.com/ocr/benchmark/olmocr-bench). These are aggregators, so prefer the primary model cards.

**ParseBench (arXiv 2604.08538, April 2026; authored by LlamaIndex staff, so interested-party)**
- About 2,078 pages from 1,180 enterprise documents (insurance, finance, government), with more than 169,000 test rules. It measures five dimensions: tables, charts, content faithfulness, semantic formatting, and visual grounding. — [ParseBench](https://arxiv.org/html/2604.08538v2)
- Overall results:
  - LlamaParse Agentic: 84.88
  - LlamaParse Cost Effective: 71.89
  - Gemini 3 Flash: 71.0
  - Reducto: 67.8
  - Qwen 3 VL: 62.0
  - Azure DI: 59.6
  - dots OCR 1.5: 55.8
  - Docling: 50.6
  - AWS Textract: 47.9
  - GPT-5 Mini: 46.8
  - Haiku 4.5: 45.2

  — [ParseBench](https://arxiv.org/html/2604.08538v2)
- Docling sub-scores: tables 66.4, charts 52.8, content 66.9, semantic formatting 1.0, grounding 66.1 (13 pages with pipeline failures excluded). dots OCR scored tables 85.2, content 90.0, and charts 0.9. — [ParseBench](https://arxiv.org/html/2604.08538v2)

**Independent / third-party API rankings**
- openbenchmarks.com ranks parsers by downstream answer accuracy: Reducto r-1 at 84.8% ± 0.3% and LlamaParse agentic at 83.8%, with cost and latency per 1k pages. Its cost page shows different figures for the same vendors. — [openbenchmarks.com best PDF parsers](https://openbenchmarks.com/document-processing/best-pdf-parser-tools); [cost page](https://openbenchmarks.com/document-processing/best-pdf-parsing-apis-by-cost)
- One 2026 comparison "found no neutral head-to-head of the three [Docling, MinerU, Marker] at current versions." — [Particula Tech](https://particula.tech/blog/docling-vs-mineru-vs-marker-pdf-parser)

**Failure modes**
- Charts:
  - "Most specialized parsers score below 6%" on ParseBench charts, often because they output raw OCR text instead of structured data.
  - Single-pass general VLMs (GPT-5 Mini, Haiku 4.5) score below 10% on visual grounding.
  - Many parsers drop strike-through, superscripts, and hyperlinks.
  - Content faithfulness peaks at about 90% even for the best systems.

  — [ParseBench](https://arxiv.org/html/2604.08538v2)
- Docling's olmOCR-Bench gap narrows on born-digital PDFs (64.0, against 83.5 for Marker and 83.3 for MinerU). Much of the deficit is therefore on scanned or complex pages. — [Marker GitHub (vendor-run)](https://github.com/datalab-to/marker)
- Marker needs an LLM mode (`--use_llm`) to merge tables across pages, handle inline math, and extract form values. This implies these cases are weak in the non-LLM pipeline. — [Marker GitHub](https://github.com/datalab-to/marker)
- PaddleOCR-VL-1.5 is explicitly positioned for "Robust In-the-Wild Document Parsing," meaning photographed and distorted pages. In-the-wild robustness is still an open problem that model builders are now targeting. — [PaddleOCR-VL-1.5 paper, arXiv 2601.21957](https://arxiv.org/pdf/2601.21957)
- On reading order, even top models keep a reading-order edit distance of about 0.11 to 0.13 on OmniDocBench, against about 0.24 for Marker. — [OmniDocBench](https://github.com/opendatalab/OmniDocBench)
- New benchmarks keep appearing for real-world regulated documents (e.g., RealDocBench, field-level QA). — [RealDocBench, arXiv 2606.07401](https://arxiv.org/pdf/2606.07401)

### Inferences
- OmniDocBench is now saturating at the top (about 97). Differences of 1 to 2 points among the top 10 are unlikely to matter more than domain fit. HF's advice is to build a representative in-house eval set: "Your domain may not be well represented in existing benchmarks!" — [HF blog](https://huggingface.co/blog/ocr-open-models)
- Rankings differ by benchmark: dots.ocr is strong on OmniDocBench and tables but near zero on charts in ParseBench. The toolkit should therefore ship a pluggable eval harness covering OmniDocBench, olmOCR-Bench, and a ParseBench-style rule set, and run it on the user's own corpora.
- Handwriting, multi-column newspapers, and photographed pages are covered only partly (OmniDocBench "note" and "newspaper" types). I found no strong cross-tool numbers specifically for handwriting.

### Gaps
- I found no independent, current, apples-to-apples evaluation that includes Docling, MinerU, Marker, Unstructured, and the VLMs together.
- I found no per-category (handwriting, photographed) breakdown across tools this session. The OmniDocBench README has per-attribute tables that I did not extract.
- I could not verify who operates openbenchmarks.com or what its methodology is.

---

## Q3. VLM-based vs pipeline (layout + OCR + table models) parsing: cost, speed, and accuracy tradeoffs

### Takeaway
Small specialized VLMs (about 0.9B to 3B) now beat classic pipelines on accuracy:
- OmniDocBench: about 93 to 97 against about 78 to 86.
- Tables: TEDS above 90 against about 66 to 82.

They need GPUs, though. Pipelines remain much faster and cheaper on born-digital PDFs, and a text-layer fast path with no OCR is orders of magnitude faster. The practical design is a router: a fast text-layer path for clean digital pages, and a VLM or OCR path for scanned, complex, or low-confidence pages, with optional LLM post-passes. Heavier or "reasoning" settings show diminishing returns.

### Cited Findings
- Marker's own throughput figures (vendor-run; sustained and concurrent on one B200 host):

  | Configuration | Pages/s |
  |---|---|
  | Marker fast no-OCR (CPU) | 23.7 |
  | Marker fast | 7.4 |
  | Marker balanced | 2.9 (single stream about 0.3) |
  | Docling | 2.1 |
  | MinerU | 0.54 |
  | liteparse | 8.9 (1,721 with no OCR) |

  — [Marker GitHub](https://github.com/datalab-to/marker)
- olmOCR-2 costs about $178 per million pages on an H100 at $2.69/h with vLLM/SGLang. DeepSeek-OCR handles 200k+ pages/day on one A100-40GB, with a similar cost per million pages. *(Older: Oct 2025.)* — [HF blog](https://huggingface.co/blog/ocr-open-models)
- PP-OCRv5, a classic lightweight OCR model, is reported #1 on average 1-edit-distance on OmniDocBench and "beats larger VLMs at a fraction of the compute." Classical OCR is suggested above roughly 100k pages/month for cost reasons. — [FullStackCV playbook](https://fullstackcv.github.io/playbook/ocr/)
- On ParseBench, more expensive or higher-reasoning settings gave diminishing returns: Gemini 3.1 Pro scored below Gemini 3 Flash (minimal) at about 13x the cost. — [ParseBench](https://arxiv.org/html/2604.08538v2)
- On OmniDocBench, specialized 0.9B models such as PaddleOCR-VL-1.5/1.6 and GLM-OCR (94.9 to 96.3) beat large general VLMs: Gemini 3 Pro 92.9, GPT-5.2 86.6, Qwen3-VL-235B 89.8. — [OmniDocBench](https://github.com/opendatalab/OmniDocBench)
- Modern models use layout metadata (anchors, often bounding boxes) to keep reading order and reduce hallucination. For document Q&A on complex layouts, feeding the page image and query to a VLM such as Qwen3-VL can beat text conversion, because charts and images are not lost. — [HF blog](https://huggingface.co/blog/ocr-open-models)
- Hybrid LLM post-processing (Marker `--use_llm` with Gemini, Claude, OpenAI-compatible, or Ollama backends) fixes cross-page tables, inline math, and forms. — [Marker GitHub](https://github.com/datalab-to/marker)

### Inferences
- End-to-end page-to-markdown VLMs risk hallucination and often lack grounding, so bbox output is a key selection criterion. MinerU2.5, PaddleOCR-VL, and dots.ocr emit layout plus content; ParseBench shows single-pass general VLMs score below 10% on grounding.
- Recommended toolkit default:
  - Docling or pypdfium-style text extraction for born-digital pages.
  - A layout model plus a specialized VLM (PaddleOCR-VL / MinerU2.5 / GLM-OCR class) for scanned pages, complex tables, and formulas.
  - Optional frontier-LLM repair for charts and cross-page tables.
- Route each page by a text-layer quality check.

### Gaps
- I found no independent cost-per-page numbers for the 2026 top models (PaddleOCR-VL-1.6, MinerU2.5-Pro, GLM-OCR) on standard hardware.
- I found no measured hallucination rates comparing VLM and pipeline approaches.

---

## Q4. Which intermediate representation is best as a canonical internal format?

### Takeaway
DoclingDocument is the most complete open, lossless candidate:
- a typed pydantic tree with body/furniture separation and groups;
- JSON-pointer parent/child references, with reading order defined by the tree;
- tables, pictures, and key-value items, with per-item provenance and bounding boxes;
- MIT licensed, with exporters to Markdown, HTML, DocTags, and lossless JSON, and wide input-format coverage.

Unstructured's flat element list (typed elements, parent_id, coordinates, text_as_html for tables, deterministic SHA-256 IDs) is simpler but weaker on hierarchy. Marker's JSON block tree (polygon, section_hierarchy) is a third model. Markdown alone is not adequate as a canonical format, because it loses bboxes and provenance.

### Cited Findings
- **DoclingDocument fields:**
  - It is a unified representation introduced in Docling v2, a pydantic type in `docling_core.types.doc` with construction APIs.
  - Content lists are `texts` (paragraphs, headings, equations), `tables` (TableItem), `pictures` (PictureItem), and `key_value_items`.
  - Structure comes from `body` (main-content tree), `furniture` (headers and footers), and `groups` (lists, chapters).
  - Items reference parents and children via JSON pointers (e.g., `#/texts/1`), and reading order comes from the `body` tree.
  - It includes layout bboxes "where available" and provenance information.

  — [Docling concepts: DoclingDocument](https://docling-project.github.io/docling/concepts/docling_document/)
- **Docling formats:**
  - Inputs: PDF, DOCX, PPTX, XLSX, HTML, EPUB, Apple Pages/Numbers/Keynote, ODF, audio (WAV, MP3), video (MP4, AVI, MOV, MKV, WebM), WebVTT, email (EML, MSG), ICS, images, LaTeX, XBRL, Box Notes, and plain text.
  - Exports: Markdown, HTML, WebVTT, DocLang, DocTags, and lossless JSON.
  - It ships an MCP server and integrations with LangChain, LlamaIndex, CrewAI, and Haystack.

  — [Docling GitHub](https://github.com/docling-project/docling)
- **Unstructured elements:**
  - Types: Title, NarrativeText, ListItem, Table, Image, FigureCaption, Formula, Header, Footer, CodeSnippet, PageNumber, Address, EmailAddress, PageBreak, UncategorizedText, and CompositeElement (from chunking only).
  - Metadata: `coordinates` (points plus system, e.g., PixelSpace), `page_number`, `parent_id`, `category_depth`, `text_as_html` (tables), filename/filetype/last_modified, `languages`, emphasized text, links, email fields (sent_from, sent_to, subject, cc), `detection_class_prob`, and `image_base64`.
  - Element IDs are by default a SHA-256 of text, position, page number, and filename, so they are deterministic. `unique_element_ids=True` gives UUIDs.
  - Chunks keep `orig_elements` and an `is_continuation` flag.

  — [Unstructured docs](https://docs.unstructured.io/open-source/concepts/document-elements)
- **Marker JSON:** a tree of blocks, each with `id`, `block_type`, `html`, `polygon` (four-corner bbox), `children`, `section_hierarchy`, and `images`. A "chunks" output gives a flat list of top-level blocks for RAG. — [Marker GitHub](https://github.com/datalab-to/marker)
- **Output-format guidance:** layout-preserving formats such as DocTags or HTML for reconstruction, Markdown with image captions for LLM input, and JSON for programmatic use. — [HF blog](https://huggingface.co/blog/ocr-open-models)

### Inferences
- Use DoclingDocument, or a superset schema compatible with it, as the canonical internal model. It already carries hierarchy, tables, figures, furniture separation, and provenance, and Docling's exporters and chunkers come for free.
- Add the fields a data lake needs:
  - stable content-addressed IDs, modeled on Unstructured's deterministic SHA-256 IDs;
  - source URI and version;
  - per-item parser/model identity and version;
  - confidence scores;
  - links to graph entities and schema.
- Write adapters from Unstructured elements, Marker JSON, and MinerU / PaddleOCR-VL output into this model so backends stay swappable.
- Represent tables both structurally (cells with spans, as in Docling's table structure) and as HTML for LLM consumption. Unstructured's `text_as_html` shows the HTML half of this.

### Gaps
- The fetched page did not cover DoclingDocument's detailed ProvItem fields (page_no, bbox, charspan), TableData/cell spans, or the `pages` and `form_items` fields. Verify these in the `docling-core` source.
- I found no documented comparison of these schemas by a third party.

---

## Q5. Chunking strategies and evidence about which work

### Takeaway
The evidence favors simple structure-aware or recursive chunking of about 512 tokens (or page-level chunks) over embedding-based "semantic" chunking. The highest-evidence add-on is contextual chunk enrichment (Anthropic Contextual Retrieval, 2024): prepend 50 to 100 tokens of LLM-generated context and combine it with BM25 hybrid search and reranking. Late chunking has little independent evidence beyond Jina's own work. Results depend on the corpus, so evaluate on your own data.

### Cited Findings
- Anthropic Contextual Retrieval *(older: Sep 19, 2024; vendor-run)*:
  - Contextual embeddings cut the top-20 retrieval failure rate by 35% (5.7% to 3.7%).
  - Adding contextual BM25 brought the reduction to 49% (to 2.9%).
  - Adding reranking (top-150 to top-20) brought it to 67% (to 1.9%).
  - The context is usually 50 to 100 tokens per chunk. The one-time cost was about $1.02 per million document tokens with prompt caching (800-token chunks, 8k-token docs).

  — [Anthropic, Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)
- Vectara, NAACL 2025 (arXiv 2410.13070): 25 chunking configurations with 48 embedding models. Fixed-size chunking outperformed semantic chunking on realistic document sets. — [premai summary](https://www.premai.io/blog/rag-chunking-strategies-the-2026-benchmark-guide/); [arXiv 2410.13070](https://arxiv.org/abs/2410.13070)
- FloTorch/Vecta (Feb 2026; 50 academic papers, about 906k tokens), end-to-end accuracy:
  - recursive 512: 69%
  - fixed 512: 67%
  - semantic: 54% (fragments averaging 43 tokens)

  — [Vecta benchmark](https://www.runvecta.com/blog/we-benchmarked-7-chunking-strategies-most-advice-was-wrong) via [premai](https://www.premai.io/blog/rag-chunking-strategies-the-2026-benchmark-guide/)
- Chroma Research found a 9-point recall spread between the best and worst strategies. LLMSemanticChunker reached 91.9% recall and ClusterSemantic at 400 tokens 91.3%. Chroma is a vector DB vendor, so this is interested-party but methodologically public. — [Chroma Research](https://research.trychroma.com/evaluating-chunking)
- NVIDIA (2024) found page-level chunking best: RAGAS accuracy 0.648 with the lowest variance across five datasets. Chunk sizes from 128 to 2,048 tokens were tested. *(Older.)* — [NVIDIA blog](https://developer.nvidia.com/blog/finding-the-best-chunking-strategy-for-accurate-ai-responses/)
- One study found a 200-word fixed size could match or beat semantic chunking. — [arXiv 2506.13778](https://arxiv.org/pdf/2506.13778)
- A 2026 study on academic texts compared semantic, fixed, and recursive chunking with RAGAs, per question type. — [arXiv 2607.01852](https://arxiv.org/html/2607.01852v1)
- Late chunking (Jina) embeds the full document with a long-context model and then pools per chunk. Its gain over recursive splitting is described as marginal for plain prose (implemented in Chonkie's `LateChunker`). — [premai](https://www.premai.io/blog/rag-chunking-strategies-the-2026-benchmark-guide/); [Chonkie GitHub](https://github.com/chonkie-inc/chonkie)
- Sentence-level chunking with ColBERT v2 led MRR (0.3123) in Superlinked's VectorHub evaluation. — [Superlinked VectorHub](https://superlinked.com/vectorhub/articles/evaluation-rag-retrieval-chunking-methods)
- Structure-aware chunk outputs exist in the major parsers:
  - Unstructured CompositeElement chunks keep `orig_elements`.
  - Marker emits block-level "chunks."
  - Docling has a HybridChunker.

  — [Unstructured docs](https://docs.unstructured.io/open-source/concepts/document-elements); [Marker GitHub](https://github.com/datalab-to/marker)

### Inferences
- Default to structure-aware hierarchical chunking from the canonical document tree:
  - respect section boundaries, keep tables, figures, and captions atomic, and merge small siblings up to a token budget of about 512;
  - prepend a heading-path "contextual chunk header" deterministically and cheaply;
  - optionally add an LLM-generated contextual summary for high-value corpora;
  - pair this with hybrid BM25 plus dense retrieval and a reranker.
- Keep chunking as a re-runnable view over the canonical document, not as the stored truth. Chunk strategies can then change without re-parsing.

### Gaps
- I could not open the primary Vectara or Jina late-chunking papers this session for exact numbers.
- I found no independent replication of Anthropic's contextual retrieval gains on public benchmarks.
- I found no direct evidence comparing heading-path headers (deterministic) with LLM-generated context.

---

## Q6. Provenance and lineage: page/bbox/span citations through chunks to answers; incremental re-ingestion and change detection

### Takeaway
The building blocks exist, but no parser provides end-to-end lineage or incremental ingestion out of the box:
- Docling (provenance plus bboxes per item), Unstructured (coordinates, page_number, deterministic element IDs, `orig_elements` on chunks), and Marker (block polygons plus section_hierarchy) give per-element grounding.
- ParseBench shows visual grounding is a weak dimension for many parsers, and single-pass VLMs score below 10%.

The toolkit has to build lineage itself: content-addressed IDs, chunk-to-element maps, and parser-version stamps.

### Cited Findings
- DoclingDocument carries provenance and layout bounding boxes where available, and JSON-pointer references for every item. — [Docling concepts](https://docling-project.github.io/docling/concepts/docling_document/)
- Unstructured chunk lineage and IDs:
  - `orig_elements` on chunks points back to source elements.
  - Element IDs are deterministic SHA-256 hashes of text, position, page, and filename.
  - `last_modified` is recorded per element.

  — [Unstructured docs](https://docs.unstructured.io/open-source/concepts/document-elements)
- Marker JSON gives each block a four-corner polygon and section_hierarchy. — [Marker GitHub](https://github.com/datalab-to/marker)
- ParseBench measures "visual grounding" explicitly:
  - Docling scored 66.1, with 13 failed pages excluded.
  - GPT-5 Mini and Haiku 4.5 scored below 10%.

  — [ParseBench](https://arxiv.org/html/2604.08538v2)
- Many parsers lose layout anchors, which matter for reading order and hallucination control. — [HF blog](https://huggingface.co/blog/ocr-open-models)

### Inferences
- **Lineage chain:**
  - source object (URI, content hash, version or etag)
  - parsed document (parser name/version, model weights revision, config hash)
  - element (stable ID, page, bbox, char span)
  - chunk (ordered list of element IDs plus char offsets)
  - embedding and index entry
  - answer citation (chunk ID, resolving to page and bbox)
- **Incremental re-ingestion:**
  - Skip unchanged sources by file content hash.
  - When a source changes, diff element-level content hashes (in the style of Unstructured's deterministic IDs) to re-embed only changed chunks.
  - Re-parse everything only when the parser or model version changes. Version stamps make this auditable.
- Avoid VLM backends that do not emit bboxes when citations are required, or add a post-hoc alignment step that matches text back to the PDF text layer or OCR word boxes.

### Gaps
- I found no source this session describing an existing open-source framework with document-level change detection or incremental re-parse for parsed corpora. Candidates such as LlamaIndex's ingestion-pipeline docstore and CocoIndex were not researched.
- I did not retrieve Docling's ProvItem schema (charspan details).

---

## Q7. Non-PDF sources: Office, HTML, email, audio/video, spreadsheets, code

### Takeaway
Docling has expanded into a broad multi-format converter: Office and ODF, Apple iWork, HTML, EPUB, email (EML, MSG), ICS, LaTeX, XBRL, audio and video (via ASR), and WebVTT, all normalized into DoclingDocument. Unstructured partitions emails with structured header metadata, and keeps page numbers for DOCX, PPT, and XLSX. Code repositories are not covered by these document parsers and need a separate AST-aware path.

### Cited Findings
- Docling inputs: PDF, DOCX, PPTX, XLSX, HTML, EPUB, Apple Pages/Numbers/Keynote, audio (WAV, MP3), WebVTT, Box Notes, email (EML, MSG), iCalendar (ICS), images, LaTeX, DocLang, plain text, ODF (ODT, ODS, ODP), XBRL, and video (MP4, AVI, MOV, MKV, WebM). Recent additions include video parsing, ODF, XBRL, email, calendar, EPUB, iWork, and chart understanding. — [Docling GitHub](https://github.com/docling-project/docling)
- Unstructured carries email-specific metadata (sent_from, sent_to, subject, cc_recipient, bcc_recipient), HTML link_urls and link_texts, and page_number for DOCX, PDF, PPT, and XLSX. — [Unstructured docs](https://docs.unstructured.io/open-source/concepts/document-elements)
- Marker outputs Markdown, HTML, JSON, and chunks. LLM mode handles forms and tables. — [Marker GitHub](https://github.com/datalab-to/marker)

### Inferences
- Use Docling's backends for Office, HTML, and email to get a uniform representation.
- Spreadsheets warrant a dedicated path: keep the raw tabular data (sheets, typed cells, named ranges) as structured tables in the lake, alongside a text rendering for retrieval, because LLM-oriented Markdown flattening loses types and formulas.
- For audio and video, store time-coded segments (WebVTT-like start and end) as the provenance analog of page and bbox.
- For code, use a tree-sitter-style AST chunker by symbol, plus repository metadata (path, commit SHA). This is not covered by the document parsers researched.

### Gaps
- I did not research quality benchmarks for DOCX, PPTX, HTML, and XLSX conversion, or which ASR model Docling uses. I found no comparative evaluations.
- These tools were not researched this session: Microsoft MarkItDown, Apache Tika, email/attachment recursion handling, and code-repo ingestion tools.
