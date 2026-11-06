# Document parsing into structured records: tables, forms and key-value pairs, layout analysis, and document-to-structure models

Scope: the parsing step that turns PDFs, scans and images into tables, key-value pairs and typed fields, ready to load into SQL, graph or key-value stores and traceable to page coordinates. General LLM information extraction from prose belongs to another track. Status as of November 2026.

Conventions:
- "Author-reported" means the developers of the model or benchmark reported the number.
- "Independent" means a third party measured it. Several of the main benchmarks (OmniDocBench, Real5-OmniDocBench, olmOCR-Bench) are maintained by groups that also ship competing parsers, and these notes flag that wherever it applies.
- Metrics:
  - **TEDS** (Tree-Edit-Distance Similarity) compares the HTML trees of the predicted and true tables, so it scores structure and content together.
  - **TEDS-S** is the structure-only variant.
  - **GriTS** (Grid Table Similarity) compares the predicted table directly as a 2-D grid of cells. GriTS_Con scores cell content, GriTS_Top cell topology (rows, columns and spans), and GriTS_Loc cell locations.
  - **Acc_Con** is exact-match table accuracy: the share of tables reproduced with every cell correct.

---

## Q1. Table structure recognition (TSR) and table extraction: classic models, benchmarks, VLM-based extraction (2024–2026), cross-page tables, and turning tables into relational form

### Takeaway
For born-digital PDFs, small specialised detector or structure models reliably give the most database-ready tables, with every cell grounded:
- Examples are TableFormer, TATR and POTATR (Page-Object Table Transformer), all taking cell text from the PDF's own text layer.
- They match or beat frontier multimodal LLMs on single tables and single pages.
- They run at roughly 1/300 of the cost.

Frontier multimodal LLMs win only on whole-document, multi-page table extraction, at $15k–$37k per million pages. Rule-based extractors (Tabula, Camelot) lag far behind. Converting a recognised grid into relational tuples is a separate step: it needs header detection, merged-cell propagation, unit and scale handling, and cross-page merging. That step is still poorly benchmarked.

### Cited Findings

**Foundational datasets and metrics**
- **TableBank (2019):** 417K tables labelled by weak supervision from Word and LaTeX source documents, for table detection and recognition. — [TableBank](https://arxiv.org/abs/1903.01949)
- **PubTabNet and EDD (2019; ECCV 2020):**
  - PubTabNet holds 568k table images with HTML ground truth, generated automatically by matching the PubMed Central XML to the PDF.
  - The paper introduced the encoder-dual-decoder (EDD) image-to-HTML model and the TEDS metric. TEDS captures multi-hop cell misalignment and OCR errors better than adjacency-relation metrics. — [PubTabNet](https://arxiv.org/abs/1911.10683)
- **FinTabNet and GTE (WACV 2021):**
  - Global Table Extractor (GTE) does joint table detection and hierarchical cell detection, using a cell-containment penalty.
  - The authors auto-labelled cell structure to create FinTabNet, a dataset of complex financial tables. — [GTE/FinTabNet](https://arxiv.org/abs/2005.00589)
- **PubTables-1M (2021; CVPR 2022):**
  - Nearly one million tables from scientific articles, with header and location annotations.
  - It introduced "canonicalization" to fix oversegmentation, an inconsistency in earlier ground truth.
  - DETR-style Table Transformer (TATR) models trained on it did detection, structure recognition and "functional analysis" (header roles) with no task-specific customisation. — [PubTables-1M](https://arxiv.org/abs/2110.00061)
- **TATR v1.0 results on the PubTables-1M test set:**
  - Structure recognition: AP 0.902, GriTS_Top 0.9849, GriTS_Con 0.9850, GriTS_Loc 0.9786, exact-match Acc_Con 0.8243.
  - Detection: AP 0.970.
  - TATR needs the words as a separate input, from OCR or the PDF text layer, to emit HTML or CSV.
  - The GitHub repository is MIT-licensed but is now archived and read-only. — [microsoft/table-transformer](https://github.com/microsoft/table-transformer)
- **GriTS metric (ICDAR 2023):**
  - Evaluates a predicted table directly as a matrix, using a polynomial heuristic for the "2D most similar substructures" problem.
  - Unifies cell topology, location and content scoring, which TEDS's tree view does not. — [GriTS](https://arxiv.org/abs/2203.12555)
- **Aligning benchmark datasets (ICDAR 2023):**
  - TATR's exact-match accuracy on ICDAR-2013 is 65% when trained on PubTables-1M, 42% on FinTabNet, and 69% on both combined.
  - After the annotations were canonicalised and aligned, these rose to 75%, 65% and 81%.
  - So label inconsistency across datasets, not just the architecture, limits exact-match table reproduction. — [Smock et al. 2023](https://arxiv.org/abs/2303.00716)

**Model families**
- **TableFormer (CVPR 2022, IBM):**
  - Replaces EDD's LSTM decoders with transformers and adds a cell-bounding-box decoder.
  - Cell content can then be lifted from the PDF text layer instead of decoded by OCR, which also makes it language-agnostic.
  - It introduced SynthTabNet: four synthetic sets of 150k tables each, 600k in total.
  - TEDS (simple / complex / all):
    - PubTabNet 98.5 / 95.0 / 96.75, against EDD at 89.9 all and GTE at 93.01.
    - FinTabNet 97.5 / 96.0 / 96.8.
    - TableBank 89.6.
    - SynthTabNet 96.7.
  - Large tables covering half a page or more "yield poor predictions" because the image is downsampled. — [TableFormer PDF](https://arxiv.org/pdf/2203.01017)
- **TableFormer against rule-based and commercial tools** (structure plus content from PDF cells, PubTabNet, TEDS all): Tabula 67.9, Traprange 55.4, Camelot 73.0, Acrobat Pro 65.3, EDD 88.3, TableFormer 93.6. — [TableFormer PDF](https://arxiv.org/pdf/2203.01017)
- **OTSL (Optimized Table-Structure Language; ICDAR 2023):**
  - A 5-token table language: C, L, U, X and NL.
  - Its backward-looking syntax rules make every generated sequence syntactically valid; HTML needs 28+ tokens.
  - With TableFormer it halves inference time versus HTML and raises TEDS (FinTabNet 0.959 vs 0.92; PubTables-1M 0.977 vs 0.966).
  - mAP@0.75 for cell boxes rises on FinTabNet from 0.722 to 0.862. — [OTSL](https://arxiv.org/abs/2305.03393)
  - MinerU2.5 adopts OTSL internally, converts it to HTML afterwards, and says it cuts structural tokens "from over 28 to just 5". — [MinerU2.5](https://arxiv.org/abs/2509.22186)
- **Other TSR architectures:**
  - LGPMA (ICDAR 2021) uses soft pyramid masks and handles empty cells. — [LGPMA](https://arxiv.org/abs/2105.06224)
  - VAST (CVPR 2023) decodes cell box coordinates as a token sequence for more precise physical structure. — [VAST](https://arxiv.org/abs/2303.06949)
  - Cycle-CenterNet and the WTW dataset (ICCV 2021) target photographed, deformed tables: +24.6 TEDS on WTW. — [WTW](https://arxiv.org/abs/2109.02199)
  - UniTable (2024) unifies structure, content and cell-box prediction as language modelling over pixels with self-supervised pretraining. It reports beating GPT-4o, GPT-4-turbo-vision and LLaVA at table parsing (author-reported). — [UniTable](https://arxiv.org/abs/2403.04822)
  - InstructTable (2026) adds instruction pretraining and reports SOTA on FinTabNet, PubTabNet and MUSTARD, plus a new 900-image complex-table benchmark, BCDSTab (author-reported). — [InstructTable](https://arxiv.org/abs/2604.02880)

**PubTables-v2 (2025–2026): the main evidence on VLMs vs specialised models and on multi-page tables**
- **Dataset:**
  - 548k tables on 468k pages, plus 135k long or wide cropped tables.
  - 9,172 full documents containing 9,492 multi-page tables, spanning up to 13 pages.
  - Licensed CDLA-Permissive-2.0 on Hugging Face. — [PubTables-v2](https://arxiv.org/abs/2512.10888); [HF dataset](https://huggingface.co/datasets/kensho/PubTables-v2)
- **Cropped-table TSR (GriTS_Con):**
  - Specialised: TATR-v1.2-Pub with direct PDF text reaches 0.9801.
  - Frontier models (zero-shot): Gemini 3.1 Pro 0.9242, Claude Opus 4.6 0.8952, GPT-5.4 0.8775.
  - dots.ocr: 0.8011. — [PubTables-v2](https://arxiv.org/html/2512.10888v4)
- **Page-level extraction (GriTS_Con):** POTATR with direct text 0.9647; Gemini 3.1 Pro 0.9418; Claude 0.9106; GPT-5.4 0.9102; dots.ocr 0.8991. — [PubTables-v2](https://arxiv.org/html/2512.10888v4)
- **Full-document, multi-page extraction (GriTS_Con):**
  - Frontier models lead: Gemini 3.1 Pro 0.9309, Claude 0.9079, GPT-5.4 0.8847.
  - dots.ocr scores 0.5768 page-by-page and 0.7495 with cross-page merging.
  - The authors summarise this as frontier models leading by +0.354 GriTS_Con on full-document extraction, while targeted small models reverse the gap (−0.056) on cropped tables. — [PubTables-v2](https://arxiv.org/abs/2512.10888)
- **Failure modes observed in VLMs (PubTables-v2):**
  - SmolDocling's DocTags output failed to parse 958 times on Single Pages; GraniteDocling failed 35 times.
  - Qwen2.5-VL-3B and -7B loop until they hit the token limit.
  - Granite-Vision never output more than one table per page, and nearby tables were fused.
  - Gemini 3.1 Pro split spanning cells into a content cell plus blanks; DeepSeek-OCR got rowspans wrong.
  - On tables split within a single page, no model exceeded Acc_Top 0.0625, and all had Acc_Con of 0.
  - The paper does not evaluate cell-level grounding; it lists it as future work. — [PubTables-v2](https://arxiv.org/html/2512.10888v4)
- **POTATR (Kensho, 2026):**
  - A 29M-parameter, non-autoregressive "image-to-graph" extension of TATR. It predicts page objects (table, caption, footer, rotated table) and parent-child relations in parallel.
  - Every element has a bounding box, so text can be assigned geometrically from the PDF layer or an external OCR.
  - Throughput: about 52,031 pages/hour on one A10G, against 393 pages/hour for Gemini 3.1 Pro.
  - Cost per million pages: about $47, against $15,000 (Gemini 3.1 Pro), $16,800 (GPT-5.4) and $36,680 (Claude Opus 4.6).
  - Latency is about 21 ms per page regardless of cell count; autoregressive VLMs take 1.8–12 s per page.
  - With OCR text instead of PDF text, GriTS_Con falls from 0.965 to 0.877 (PaddleOCR), 0.881 (docTR) or 0.783 (EasyOCR).
  - Multi-page: page-by-page processing gives 0.671. Adding a ViT-B-16 continuation classifier (recall 0.995) and vertically concatenating the segments gives 0.835.
  - Limitations: trained and tested only on English PubMed articles. Authors are the PubTables-v2 creators (author-reported). — [POTATR](https://arxiv.org/abs/2606.09788); [HTML](https://arxiv.org/html/2606.09788v2)

**Cross-page tables and document-level structure**
- **MPDocBench-Parse (2026):**
  - 433 documents, 3,246 pages, 15 document types.
  - Scores truncated-table merging, heading hierarchy and reading order.
  - Finding: models "perform well on basic text extraction" but fall short on semantic continuity and hierarchical structure recovery. — [MPDocBench-Parse](https://arxiv.org/abs/2605.22100)
- **MinerU-Popo (2026):** a fine-tuned Qwen3-VL-4B post-processor that repairs page-level outputs from any parser. It handles text and table truncation recovery, title hierarchy, and image-text association, and improves title-hierarchy TEDS by at least 20% across five OCR models (author-reported). — [MinerU-Popo](https://arxiv.org/abs/2605.24973)
- **MonkeyOCR v1.5 (2025):** a "Type-Guided Table Merging" module for tables crossing pages or columns, plus render-and-compare reinforcement learning (RL) for table structure. — [MonkeyOCR v1.5](https://arxiv.org/abs/2511.10390)
- **LingDT-VL-OCR (2026, finance):**
  - Cross-page consolidation, plus a CellBBoxRegressor that localises table cells from decoder hidden states.
  - Introduces FinDocBench, with cross-page concatenated TEDS and cell IoU metrics. — [LingDT-VL-OCR](https://arxiv.org/abs/2603.11044)
- **OvisOCR3 (Oct 2026):** a 0.8B model that claims to lead in Relation F1 on CrossTabBench and in truncated-table TEDS on MPDocBench-Parse (author-reported). — [OvisOCR3](https://arxiv.org/abs/2610.33066)
- **TASER (2025, financial filings):**
  - 99.4% of tables in its dataset lack bounding boxes, and the largest table spans 44 pages.
  - Its agentic, schema-guided pipeline beats Table Transformer detection by 10.1%. — [TASER](https://arxiv.org/abs/2508.13404)
- **Azure Document Intelligence:** its layout documentation tells users with multi-page tables to split the PDF and "post-process the pages to a single table". Cross-page merging is left to the caller. — [Azure DI layout](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/layout)

**From recognised table to relational form: normalisation, headers, units, verification**
- **Auto-Tables (VLDB 2024):**
  - Over 30% of real spreadsheet and web tables are not relational and need multi-step restructuring before SQL can query them.
  - Auto-Tables synthesises transformation pipelines for over 70% of 244 real cases, with no user examples. — [Auto-Tables](https://arxiv.org/abs/2307.14565)
- **HiTab (ACL 2022):** 3,597 hierarchical tables from statistical reports and Wikipedia. Hierarchical headers need "hierarchy-aware" logical forms, which flat-table methods lack. — [HiTab](https://arxiv.org/abs/2108.06712)
- **Header metadata in extractors:**
  - PubTables-1M annotates column headers and projected row headers. — [PubTables-1M](https://arxiv.org/abs/2110.00061)
  - Docling's `TableCell` schema has `bbox`, `row_span`, `col_span`, start and end row/column offsets, `column_header`, `row_header` and `row_section` flags. — [docling-core table_data.py](https://github.com/docling-project/docling-core/blob/main/docling_core/types/doc/items/table/table_data.py)
  - Azure DI marks cells of kind `columnHeader`, with polygon and content-span offsets. Since v4.0 (2024-11-30) its Markdown output uses HTML tables, so merged cells and multi-row headers survive. — [Azure DI layout](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/layout)
- **Units and scale (TableVQA-Bench, 2024):** answers "inconsistent[ly]" included scale units such as thousand, million and billion, especially thousands. The evaluation deliberately excludes units ("relieved accuracy"), because multimodal LLMs score poorly under strict accuracy. — [TableVQA-Bench](https://arxiv.org/html/2404.19205v1)
- **SynFinTabs (2024):** a synthetic financial-table dataset with word positions. It addresses the reliance of training data on "unreliable OCR". — [SynFinTabs](https://arxiv.org/abs/2412.04262)
- **Arithmetic verification, TableVision (2026):**
  - On historical election registers, the best open-source reader reproduces 99.0% of digits but files only 83.7% of figures in the correct cell, and gets only 11 of 30 columns right.
  - Amazon Textract files 1 of 1,494 figures correctly on degraded 1888 pages; TableVision files 99.2%.
  - Its sum-check gate accepted 2,042 of 2,201 columns, flagged 118 and withheld 41. Official returns confirmed 933 of 934 testable accepted sums.
  - It added 491,359 gated rows to a 9.3-million-row dataset. — [TableVision](https://arxiv.org/abs/2610.17448)
- **Arithmetic verification, Karnataka fiscal documents (2025):** an LLM pipeline over 200+-page fiscal documents uses the hierarchy of totals as multi-level validation checks, because "traditional OCR methods" cannot verify numbers. — [Fiscal documents](https://arxiv.org/abs/2511.10659)

### Inferences
- In Acc_Con terms, "database-ready" means every cell exactly right. Even strong models reach only about 0.82 exact-match on in-domain PubTables-1M (TATR v1.0) and 65–81% on ICDAR-2013. Mean GriTS/TEDS scores of 0.95 or more therefore still imply a meaningful fraction of tables with at least one wrong cell. Row-level validation (sum checks, type checks, header consistency) belongs in the load path, not just at evaluation time.
- The most reliable recipe for born-digital PDFs:
  1. A layout or table detector.
  2. A structure model emitting a grid with cell boxes (TableFormer, TATR or POTATR).
  3. Text taken from the PDF text layer, not regenerated.
  This keeps cell text byte-identical to the source and gives each cell coordinates. Generative paths can silently rewrite values.
- Cross-page tables are the clearest case where expensive frontier models still help. A cheaper deterministic path is a continuation classifier plus header-aware concatenation (POTATR appendix). MinerU-Popo-style post-processing is another option.
- Header and unit normalisation (wide to long, propagating spanning headers, attaching "in millions" scale factors) is barely benchmarked for PDF-derived tables. Auto-Tables-style program synthesis, which is deterministic once synthesised, is the closest established method.

### Gaps
- I found no benchmark that scores end-to-end PDF-to-relational output: header semantics, unit and scale attachment, and correct tuples. GriTS and TEDS stop at the grid.
- I found no independent, non-author replication of POTATR's cost and speed numbers.
- PubTables-v2 covers only scientific articles. The multi-page comparison of financial, government and invoice tables relies on small or vendor-specific sets (TASER, FinDocBench).
- No public benchmark measures numeric value fidelity, i.e. digits silently altered by generative models, at scale. The only measurement found is a single-document vendor report (Q5).

---

## Q2. Form understanding and key-value / key information extraction (KIE): LayoutLM family, DocFormer, Donut, Pix2Struct, UDOP, LiLT, GeoLayoutLM; datasets (FUNSD, CORD, SROIE, DocILE, Kleister, VRDU, XFUND, KVP10k); LLM and VLM approaches

### Takeaway
Two settings behave differently.

- **Fixed schema, in-domain, with labelled data.** Fine-tuned layout-aware encoders over OCR tokens reach 90–97 F1 (LayoutLMv3, LiLT, GeoLayoutLM), and their outputs are naturally grounded in the OCR boxes.
- **Many templates, few or zero examples, nested line items.** Scores fall sharply. LLM methods that pass OCR coordinates in and verify every value against the source text (LMDX) beat those encoders in few-shot settings and guarantee grounding. Zero-shot VLMs reach only about 40–82% exact-match field F1 on new benchmarks and still hallucinate.

Line items and hierarchical fields remain the weakest part everywhere.

### Cited Findings

**Datasets and benchmarks**
- **FUNSD (2019):** 199 fully annotated noisy scanned forms, covering entity labelling and linking. — [FUNSD](https://arxiv.org/abs/1905.13538)
- **CORD (NeurIPS 2019 Document Intelligence workshop):** 1,000 released Indonesian receipts (800 train / 100 dev / 100 test), 5 superclasses and 42 subclasses, CC BY 4.0. — [CORD GitHub](https://github.com/clovaai/cord)
- **SROIE (ICDAR 2019):** 1,000 scanned receipts, with tasks for text localisation, OCR and key information extraction. — [SROIE](https://arxiv.org/abs/2103.10213)
- **Kleister (ICDAR 2021):**
  - Long-document key information extraction: Kleister NDA has 540 NDAs and 3,229 pages; Kleister Charity has 2,788 financial reports, 61,643 pages and 21,612 entities.
  - The best baseline reached F1 81.77 (NDA) and 83.57 (Charity). — [Kleister](https://arxiv.org/abs/2105.05796)
- **XFUND, introduced with LayoutXLM (2021):** form key-value pairs in 7 languages. — [LayoutXLM/XFUND](https://arxiv.org/abs/2104.08836)
- **DocILE (ICDAR 2023):**
  - 6.7k annotated business documents, 100k synthetic and about 1M unlabelled.
  - 55 field classes, plus Line Item Recognition (LIR): assigning fields to table rows.
  - Evaluation requires localisation: a predicted box must cover exactly the pseudo-character centres of the true field.
  - Best permitted baselines: KILE AP 0.539 and LIR F1 0.698 (RoBERTa+synthetic). LayoutLMv3 is no better without forbidden pretraining (KILE AP 0.512). — [DocILE](https://arxiv.org/abs/2302.05658); [HTML](https://arxiv.org/html/2302.05658v2); [DocILE 2023 teaser](https://arxiv.org/abs/2301.12394)
- **VRDU (Google, KDD 2023):**
  - Rich schemas, hierarchical line items and template diversity.
  - Three observations: generalising to new templates is hard, few-shot has large headroom, and models "struggle with hierarchical fields such as line-items". — [VRDU](https://arxiv.org/abs/2211.15421)
- **KVP10k (2024):** 10,707 business documents for key-value pair discovery without predefined keys. — [KVP10k](https://arxiv.org/abs/2405.00505)

**Layout-aware pre-trained encoders and OCR-free models**
- **LayoutLM (KDD 2020):** joint text and 2-D position pretraining. FUNSD rose from 70.72 to 79.27, receipts from 94.02 to 95.24. — [LayoutLM](https://arxiv.org/abs/1912.13318)
- **LayoutLMv2:** adds image features and spatial-aware attention. FUNSD 84.20, CORD 96.01, SROIE 97.81, Kleister-NDA 85.20. — [LayoutLMv2](https://arxiv.org/abs/2012.14740)
- **LayoutLMv3 (ACM MM 2022):**
  - Unified text and image masking.
  - FUNSD F1 90.29 (BASE) and 92.08 (LARGE); CORD 96.56 and 97.46.
  - Baselines in the same table: DocFormer-LARGE FUNSD 84.55 / CORD 96.99; LiLT-BASE 88.41 / 96.07; BROS-LARGE 84.52 / 97.40. — [LayoutLMv3 HTML](https://arxiv.org/html/2204.08387v3)
  - **Licence:** LayoutLMv3 and LayoutLMv2 weights are CC-BY-NC-SA-4.0 on Hugging Face, i.e. non-commercial. — [HF layoutlmv3-base](https://huggingface.co/microsoft/layoutlmv3-base)
- **DocFormer (ICCV 2021):** multimodal self-attention with spatial embeddings shared across modalities. — [DocFormer](https://arxiv.org/abs/2106.11539)
- **LiLT (ACL 2022):**
  - A language-independent layout transformer: pretrain on one language, then fine-tune with any off-the-shelf text model.
  - Hugging Face weights are MIT-licensed. — [LiLT](https://arxiv.org/abs/2202.13669); [HF](https://huggingface.co/SCUT-DLVCLab/lilt-roberta-en-base)
- **GeoLayoutLM (CVPR 2023):** explicit geometric pretraining and relation heads. Relation extraction (the key-to-value linking step) on FUNSD rose from 80.35 to 89.45 F1. — [GeoLayoutLM](https://arxiv.org/abs/2304.10759)
- **Donut (ECCV 2022):**
  - OCR-free: an image goes in, a JSON-like token sequence comes out; 143M parameters.
  - CORD: 84.1 F1 / 90.9 TED-accuracy at 1.2 s per image, against LayoutLMv2+OCR at 78.9 / 82.4.
  - Ticket: 94.1 F1. — [Donut HTML](https://arxiv.org/html/2111.15664v5)
- **Pix2Struct (2022):** pretrained by parsing masked web screenshots into simplified HTML; state of the art on 6 of 9 tasks across four domains. — [Pix2Struct](https://arxiv.org/abs/2210.03347)
- **UDOP (CVPR 2023):** unifies vision, text and layout in a prompt-based seq2seq model; first on the DUE leaderboard. — [UDOP](https://arxiv.org/abs/2212.02623)

**LLM and VLM approaches**
- **LMDX (Google, 2023):**
  - Gives the LLM OCR lines tagged with quantised coordinate tokens and asks for JSON in which each value cites its segment ID.
  - Discards any entity whose text is not found in the cited segment ("grounding guarantees").
  - Samples 16 completions at temperature 0.5 and takes a majority vote.
  - **VRDU Registration Form, mixed templates:** 87.72 F1 with 10 training documents, against 69.44 for LayoutLMv2.
  - **VRDU Ad-buy Form, mixed templates, line items:** 72.09 with 200 documents, against 25.46 for LayoutLMv2 and 24.51 for LayoutLMv3.
  - **CORD:** zero-shot 66.95 F1. At 800 documents, Gemini Pro scores 95.57 against LayoutLMv3's 95.66.
  - Removing coordinate tokens costs 14.98 F1.
  - **Limitations:**
    - Text-only input.
    - Localisation is reliable only at line level.
    - Slow and expensive, because of long prompts. — [LMDX](https://arxiv.org/abs/2309.10952); [HTML](https://arxiv.org/html/2309.10952v2)
- **DocLLM (JPMorgan, 2023):**
  - Adds bounding-box-only spatial attention to an LLM, with no image encoder.
  - Reports beating state-of-the-art LLMs on 14 of 16 datasets (author-reported). — [DocLLM](https://arxiv.org/abs/2401.00908)
- **LayoutLLM (CVPR 2024):** layout instruction tuning with "LayoutCoT" (layout chain-of-thought). — [LayoutLLM](https://arxiv.org/abs/2404.05225)
- **Retrieval Augmented Structured Generation (RASG; 2024):**
  - Frames business-document extraction as tool use.
  - Text LLMs with RASG are competitive with or better than large multimodal models on KIE and line-item recognition.
  - Includes a heuristic to back-calculate bounding boxes for predicted line items without a vision encoder. — [RASG](https://arxiv.org/abs/2405.20245)
- **UNIKIE-Bench (2026):**
  - 6,133 documents, scored by exact-match field F1.
  - Constrained-schema track: Gemini-3-Pro 82.37, Qwen3-VL-8B 79.12, GPT-4o 69.15, GPT-5 67.59, Claude-Sonnet-4.5 66.39.
  - Open-schema track: Gemini-3-Pro 81.65, GPT-5 47.39, Claude-Sonnet-4.5 39.71.
  - Observed failures:
    - Digit confusion (2.32 read as 4.32).
    - A value assigned to an adjacent line.
    - A correct value mapped to the wrong field.
    - Values absent from the document.
  - Forms are the hardest document type. — [UNIKIE-Bench](https://arxiv.org/abs/2602.07038); [HTML](https://arxiv.org/html/2602.07038v2)
- **KIE-HVQA (2025):** a benchmark of OCR hallucination on degraded identity cards and invoices. A GRPO-trained 7B model gains 22 points of hallucination-free accuracy over GPT-4o. — [KIE-HVQA](https://arxiv.org/abs/2506.20168)
- **ReceiptBench (2026):** about 10k receipts, with sub-tasks including Format Normalization and Structure Parsing for nested line items. It also proposes metric-aware GRPO. — [ReceiptBench](https://arxiv.org/abs/2605.22413)
- **Invoice benchmark (Fraunhofer, 2025):** compares GPT-5, Gemini 2.5 and Gemma 3 zero-shot. Feeding the image directly "generally outperforms" converting to Markdown first. — [Invoice benchmark](https://arxiv.org/abs/2509.04469)
- **VDInstruct (2025):** content-aware vision tokenisation for KIE; +5.5 F1 zero-shot over DocOwl 1.5 with about 3.6x fewer image tokens. — [VDInstruct](https://arxiv.org/abs/2507.09531)
- **Qianfan-OCR (2026, 4B):**
  - "Layout-as-Thought" emits bounding boxes, element types and reading order before the final output.
  - Claims the top average on public KIE benchmarks, above Gemini-3.1-Pro (author-reported). — [Qianfan-OCR](https://arxiv.org/abs/2603.13398)

### Inferences
- Headline FUNSD and CORD F1 scores (90–97) come from entity labelling over ground-truth or provided OCR. They are not comparable to end-to-end, OCR-free scores (Donut CORD 84.1) or to exact-match field F1 on new templates (UNIKIE 40–82). The realistic accuracy to expect for unseen document types is the lower range.
- For a deterministic data lake, LMDX's pattern is the most important design idea in this area:
  1. Pass coordinates in.
  2. Require each value to cite a source segment.
  3. Programmatically reject values not present in the source.
  The same check can wrap any VLM or LLM extractor and turns hallucinations into explicit nulls.
- Licensing matters for an open-source toolkit. LayoutLMv2 and v3 weights are non-commercial. LiLT (MIT), Donut (MIT), UDOP (MIT on Hugging Face) and the TATR code (MIT) are permissive.

### Gaps
- I found no independent head-to-head of LMDX-style grounded LLM extraction against fine-tuned encoders on DocILE line items in 2025–2026.
- KVP10k baseline numbers were not extracted; only the abstract was read.
- I could not open the DocILE competition overview (CLEF 2023) to confirm the winners' scores.

---

## Q3. End-to-end document-to-structure VLMs (Nougat, GOT-OCR2, olmOCR, MinerU2.5, PaddleOCR-VL, dots.ocr, Docling/SmolDocling/GraniteDocling, DeepSeek-OCR and successors): table and form accuracy

### Takeaway
As of late 2026, compact two-stage parsers hold the top author-reported OmniDocBench table scores. They run layout analysis with boxes first, then recognise each element. Examples are PaddleOCR-VL (0.9B), MinerU2.5 (1.2B) and dots.ocr (3B), all at TEDS 86–91 on v1.5. OmniDocBench v1.6 leaders now report table TEDS of about 93–97. Early page-to-Markdown models (Nougat, GOT, SmolDocling, olmOCR v1) are much weaker on tables.

All of these generate tables autoregressively. They can loop, drop or fuse tables, mis-span cells, or fail to produce parseable output, and few emit cell-level coordinates.

### Cited Findings
- **Nougat (Meta, ICLR 2024):**
  - 350M parameters; scientific PDF to markup, with tables in LaTeX.
  - On arXiv test pages the Tables modality scores F1 78.0 and edit distance 0.211, against GROBID at 69.7.
  - Repetition loops on 1.5% of test pages, more out of domain.
  - Non-Latin scripts trigger immediate repetition. Each page is processed independently.
  - Weights CC-BY-NC-4.0. — [Nougat HTML](https://arxiv.org/html/2308.13418v1); [HF](https://huggingface.co/facebook/nougat-base)
- **GOT-OCR2.0 (2024):** 580M-parameter "OCR-2.0" model producing plain or formatted output (Markdown, TikZ and other formats). It supports region-level OCR guided by coordinates. — [GOT](https://arxiv.org/abs/2409.01704)
- **OmniDocBench (CVPR 2025):** 9 document sources, 19 layout categories and 15 attribute labels, covering pipeline and end-to-end evaluation. — [OmniDocBench](https://arxiv.org/abs/2412.07626)
- **OmniDocBench v1.5 (author-reported in the MinerU2.5 paper), Overall / Table TEDS / Table TEDS-S:**

  | Model | Overall | Table TEDS | Table TEDS-S |
  |---|---|---|---|
  | MinerU2.5 (1.2B) | 90.67 | 88.22 | 92.38 |
  | MonkeyOCR-pro-3B | 88.85 | 86.78 | 90.63 |
  | dots.ocr (3B) | 88.41 | 86.78 | 90.62 |
  | Gemini-2.5 Pro | 88.03 | 85.71 | 90.29 |
  | Qwen2.5-VL-72B | 87.02 | 82.15 | 86.22 |
  | PP-StructureV3 | 86.73 | 81.68 | 89.48 |
  | Mistral-OCR | 78.83 | 70.03 | 78.04 |
  | GPT-4o | 75.02 | 67.07 | 76.09 |
  | olmOCR-7B | 81.79 | 68.92 | 74.77 |
  | Dolphin | 74.67 | 68.70 | 77.77 |
  | Marker-1.8.2 | 71.30 | 57.88 | 71.17 |

  — [MinerU2.5](https://arxiv.org/html/2509.22186v2)
- **MinerU2.5 on table-only benchmarks (TEDS):** FinTabNet 95.97, against dots.ocr 84.12 and GPT-4o 83.94. On an in-house set it scores 71.48, against Gemini-2.5 Pro 69.72 and GPT-4o 46.99. — [MinerU2.5](https://arxiv.org/html/2509.22186v2)
- **MinerU2.5 design:** the layout stage predicts each element's position, class, rotation and reading order on a downsampled page, then recognises native-resolution crops. Throughput is 2.12 pages/s on an A100. Weights are AGPL-3.0 on Hugging Face. — [MinerU2.5](https://arxiv.org/abs/2509.22186); [HF](https://huggingface.co/opendatalab/MinerU2.5-2509-1.2B)
- **PaddleOCR-VL (Baidu, 2025):**
  - PP-DocLayoutV2 provides layout boxes and reading order; a 0.9B VLM recognises each element.
  - OmniDocBench v1.5: Overall 92.86, Table TEDS 90.89, TEDS-S 94.76.
  - olmOCR-Bench: 80.0.
  - Throughput: 1.62 pages/s on an A100 with FastDeploy.
  - Apache-2.0 licence. — [PaddleOCR-VL HTML](https://arxiv.org/html/2510.14528v4); [HF](https://huggingface.co/PaddlePaddle/PaddleOCR-VL)
- **PaddleOCR-VL-1.5:** reports 94.5 on OmniDocBench v1.5. — [PaddleOCR-VL-1.5](https://arxiv.org/abs/2601.21957)
- **OmniDocBench v1.6 leaderboard (Sept 2026 snapshot), Table TEDS:** OXR-1.0 96.61, TeleOCR 96.82, PaddleOCR-VL-1.6 94.76, MinerU2.5-Pro 93.42, GLM-OCR 92.83.
  - The benchmark changed its matching algorithm in v1.5 and again in v1.6 (Multi-Granularity Adaptive Matching), and added harder pages including complex nested tables. Scores are therefore not comparable across versions.
  - The maintainer, OpenDataLab, also develops MinerU. — [OmniDocBench GitHub](https://github.com/opendatalab/OmniDocBench)
- **Robustness under physical distortion, Real5-OmniDocBench (2026; authors from Baidu PaddlePaddle):**
  - Table TEDS from Scanning to Skew:
    - Pipeline tools: PP-StructureV3 79.06 → 25.27; Marker 56.05 → 17.23.
    - VLM parsers: MinerU2.5-Pro 90.57 → 81.07; PaddleOCR-VL-1.6 94.12 → 91.04.
    - General VLMs: Gemini-3 Pro stays within about 1 point (87–88).
  - Overall under Skew: DeepSeek-OCR 63.01, against Gemini-2.5 Pro 89.07. — [Real5-OmniDocBench](https://arxiv.org/abs/2603.04205); [HTML](https://arxiv.org/html/2603.04205v2)
- **dots.ocr (rednote):**
  - One VLM performs layout detection and recognition together. Output is JSON with each element's bbox, category and text, with tables as HTML.
  - MIT licence on Hugging Face.
  - Self-reported olmOCR-Bench Tables score: 88.3; its successor dots.mocr scores 90.7.
  - Stated limitation: "complex tables and mathematical formulas remain difficult".
  - Throughput is low: 0.28–0.35 pages/s, as measured by MinerU2.5 and PaddleOCR-VL authors. — [dots.ocr GitHub](https://github.com/rednote-hilab/dots.ocr); [MinerU2.5](https://arxiv.org/html/2509.22186v2); [PaddleOCR-VL](https://arxiv.org/html/2510.14528v4)
- **olmOCR (AI2, 2025):**
  - Fine-tuned 7B VLM producing linearised text with tables.
  - Cost claim: $176 per million pages, against about $6,240 for GPT-4o.
  - Introduced olmOCR-Bench: 1,400 PDFs scored by binary unit tests. — [olmOCR](https://arxiv.org/abs/2502.18443)
- **olmOCR 2:**
  - RL with unit-test rewards. olmOCR-Bench Tables score rose from 62.3 (v1) to 84.9; overall 82.4.
  - Other Tables scores in the same table:
    - Reproduced by AI2: DeepSeek-OCR 80.2, Marker 72.9, Mistral OCR 60.6.
    - Self-reported by their developers: Chandra 88.0, MinerU 2.5.4 84.9, PaddleOCR-VL 84.1.
  - The table test only "checks the relative position of cells (with specific values)".
  - Inference uses dynamic temperature, 0.1 rising to 0.8 when no EOS token is produced, plus retries. — [olmOCR 2](https://arxiv.org/html/2510.19817v1)
- **SmolDocling (IBM / Hugging Face, 2025):**
  - 256M parameters, emitting DocTags. Every element can carry location tags on a 0–500 grid, and tables are written in OTSL.
  - Table TEDS (with content / structure only): FinTabNet 0.52 / 0.81 and PubTables-1M 0.65 / 0.88, against TableFormer at 0.89 and 0.84.
  - DocLayNet layout mAP: 0.231, against 0.82 for human annotators.
  - Speed: 0.35 s per page on an A100.
  - Failures: missing location tags, missing closing tags, endless token repetition. — [SmolDocling HTML](https://arxiv.org/html/2503.11576v1)
- **GraniteDocling-258M (IBM, Sept 2025):** Apache-2.0. It addresses SmolDocling's repetition instabilities through data cleaning; the announcement gives no measured rate. — [IBM announcement](https://www.ibm.com/new/announcements/granite-docling-end-to-end-document-conversion); [HF](https://huggingface.co/ibm-granite/granite-docling-258M)
- **DeepSeek-OCR (2025):**
  - Uses optical compression of the page into vision tokens.
  - OmniDocBench v1.0 Table edit distance (EN), lower is better:
    - DeepSeek-OCR: 0.134 at 795 tokens (Gundam mode), 0.163 at 256 tokens.
    - Other parsers: MinerU2.0 0.150, dots.ocr 0.166, GOT 0.459, Nougat 0.572, olmOCR 0.608, SmolDocling 0.729.
    - General VLMs: Gemini2.5-Pro 0.130, GPT-4o 0.234.
  - Above 10x compression, precision drops to about 60%.
  - MIT licence. — [DeepSeek-OCR](https://arxiv.org/html/2510.18234v1); [HF](https://huggingface.co/deepseek-ai/DeepSeek-OCR)
- **MonkeyOCR (2025):** a Structure-Recognition-Relation paradigm (3B), which its authors say beats Gemini 2.5-Pro. — [MonkeyOCR](https://arxiv.org/abs/2506.05218)
- **Dolphin (ByteDance, 2025):** analyses layout first, then parses elements in parallel using "anchor" prompts. — [Dolphin](https://arxiv.org/abs/2505.14059)
- **FireRed-OCR (2026):** names "structural hallucination" as the barrier to industrial use. It uses format-constrained GRPO to enforce table closure and syntax validity, and reports OmniDocBench v1.5 Overall 92.94. — [FireRed-OCR](https://arxiv.org/abs/2603.01840)
- **OvisOCR3 (Oct 2026, 0.8B):** reports OmniDocBench v1.6 Overall 96.74 and covers key information extraction and cross-page tables in one model (author-reported). — [OvisOCR3](https://arxiv.org/abs/2610.33066)
- **Harder or independent benchmarks:**
  - Dr. DocBench (2026): 4,514 expert-domain pages sampled where parsers fail. "Strong performance on existing benchmarks does not transfer". — [Dr. DocBench](https://arxiv.org/abs/2606.01393)
  - READoc (2024): 3,576 real documents converted to Markdown, where it finds a gap to realistic structured extraction. — [READoc](https://arxiv.org/abs/2409.05137)
  - CC-OCR (2024): finds weaknesses of large multimodal models in text grounding and "hallucination of repetition". — [CC-OCR](https://arxiv.org/abs/2412.02210)
- **Evaluation caveat, SCORE (Unstructured, 2025):** on 2–5% of pages with ambiguous table structure, traditional metrics such as TEDS penalised valid alternative interpretations by 12–25%, distorting rankings. — [SCORE](https://arxiv.org/abs/2509.19345)
- **Survey:** the "Document Parsing Unveiled" survey splits the field into modular pipelines and unified VLMs, and lists "reliability of VLM-based parsing" as an open challenge. — [Survey](https://arxiv.org/abs/2410.21169)

### Inferences
- The OmniDocBench table leaderboard has saturated near TEDS 90–97 on digital pages, and the main contenders benchmark each other on suites they partly control. For selection, independent harder suites carry more weight: PubTables-v2, Real5, Dr. DocBench and the user's own documents. On PubTables-v2, dots.ocr's page-level table GriTS of 0.899 trails a 29M-parameter TATR derivative at 0.965.
- Prefer the decoupled designs: PaddleOCR-VL, MinerU2.5, MonkeyOCR and Dolphin. Layout detection yields element boxes that can be stored as provenance, and the VLM's output for one region cannot spill across the page. End-to-end page-to-Markdown models (Nougat, GOT, olmOCR) lose that grounding.
- Licence spread for toolkit embedding:
  - Permissive: Apache-2.0 (PaddleOCR-VL, GraniteDocling, olmOCR 2, GOT) and MIT (DeepSeek-OCR, dots.ocr).
  - Copyleft: AGPL-3.0 (MinerU2.5 weights).
  - Non-commercial: CC-BY-NC (Nougat).

### Gaps
- None of the VLM parser papers reported cell-level coordinate accuracy for tables. Only LingDT-VL-OCR proposes a cell-IoU metric, and PubTables-v2 explicitly defers grounding evaluation.
- No paper reported run-to-run output variance (same input, same model, repeated runs) for any parser.
- I did not read GOT-OCR2's own table results in depth.

---

## Q4. Layout analysis and coordinate grounding: linking each extracted cell or field back to the page

### Takeaway
Grounding is a property of the pipeline, not of a model family.
- **Detector-based pipelines provide it natively** (DocLayNet-trained detectors, TATR, POTATR, TableFormer, Azure DI, Textract). They yield page number, polygon and character spans per cell. With born-digital PDFs, text comes from the PDF layer, so it is byte-traceable.
- **Generative VLMs vary.** Some emit element-level boxes (dots.ocr JSON, DocTags location tags, MinerU2.5 and PaddleOCR-VL layout stages, Qianfan's Layout-as-Thought). Cell-level boxes are rare.
- **LLM extractors** need explicit segment-ID schemes (LMDX) or after-the-fact back-matching (RASG).

### Cited Findings
- **PubLayNet (ICDAR 2019):** over 360k page images auto-annotated from PubMed Central XML. Models trained on it generalise poorly to non-scientific layouts. — [PubLayNet](https://arxiv.org/abs/1908.07836); [DocLayNet](https://arxiv.org/abs/2206.01062)
- **DocLayNet (KDD 2022):** 80,863 manually annotated pages in 11 classes, with double- and triple-annotated subsets. Detectors trail inter-annotator agreement by about 10%. — [DocLayNet](https://arxiv.org/abs/2206.01062)
- **Docling Heron layout models (2025):**
  - RT-DETR and D-FINE detectors trained on 150k documents.
  - "heron-101" reaches 78% mAP at 28 ms per image on an A100, 20.6–23.9% mAP above Docling's previous baseline.
  - Permissive licence. — [Docling layout models](https://arxiv.org/abs/2509.11720)
- **DocLayout-YOLO (2024):** pretraining on the synthetic DocSynth-300K, plus the DocStructBench benchmark. Positioned as fast and accurate. — [DocLayout-YOLO](https://arxiv.org/abs/2410.12628)
- **PP-DocLayout (2025):** 23 region classes. The L model reaches 90.4% mAP@0.5 at 13.4 ms per page on a T4. — [PP-DocLayout](https://arxiv.org/abs/2503.17213)
- **DiT (ACM MM 2022):** a self-supervised document image backbone. Table detection rose from 94.23 to 96.55, layout from 91.0 to 94.9. — [DiT](https://arxiv.org/abs/2203.02378)
- **LayoutParser (ICDAR 2021):** a unified toolkit for deep-learning layout detection and OCR pipelines. — [LayoutParser](https://arxiv.org/abs/2103.15348)
- **Docling pipeline (technical report; AAAI 2025 paper):**
  1. The PDF backend extracts text tokens with coordinates.
  2. Layout boxes are intersected with those tokens.
  3. TableFormer predictions are matched back to PDF cells, so table text is not re-transcribed.
  - Runtime: 0.6–2.45 pages/s on CPU without OCR. Tables take 2–6 s each on CPU; EasyOCR, when needed, takes "upwards of 30 seconds per page" on CPU.
  - MIT licence. — [Docling technical report](https://arxiv.org/html/2408.09869v5); [Docling AAAI](https://arxiv.org/abs/2501.17887)
- **Docling's document model:** `DoclingDocument` keeps body and furniture trees plus `tables` and `key_value_items`, with "layout information (i.e. bounding boxes) for all items, if available". Table cells carry `bbox` and row/column offsets. — [DoclingDocument concept](https://docling-project.github.io/docling/concepts/docling_document/); [TableCell source](https://github.com/docling-project/docling-core/blob/main/docling_core/types/doc/items/table/table_data.py)
- **Azure Document Intelligence:**
  - Each table cell carries row and column index, bounding polygon, and an offset/length span into the top-level content string.
  - Selection marks carry polygon, confidence and state; words carry confidence. — [Azure DI layout](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/layout)
- **Grounding in generative VLM parsers:**
  - SmolDocling and GraniteDocling encode element locations on a 0–500 grid inside DocTags. — [SmolDocling](https://arxiv.org/html/2503.11576v1)
  - dots.ocr outputs `[x1,y1,x2,y2]` per element. — [dots.ocr](https://github.com/rednote-hilab/dots.ocr)
  - DeepSeek-OCR can emit detection boxes normalised to 1000 bins when prompted. — [DeepSeek-OCR](https://arxiv.org/html/2510.18234v1)
  - LingDT-VL-OCR regresses table-cell boxes from decoder states using "structural anchor tokens". — [LingDT-VL-OCR](https://arxiv.org/abs/2603.11044)
- **Grounding in LLM extractors:**
  - LMDX localisation accuracy is 93.21 (Registration Form) and 88.18 (Ad-buy) zero-shot, and 98–99% when fine-tuned. It fails when the same text appears twice on one line. — [LMDX](https://arxiv.org/html/2309.10952v2)
  - RASG back-calculates bounding boxes for line items without a vision encoder. — [RASG](https://arxiv.org/abs/2405.20245)
- **DocILE scoring:** a field is correct only if its location exactly covers the true field's character centres, so grounding is part of correctness. — [DocILE](https://arxiv.org/html/2302.05658v2)

### Inferences
- For traceable records, store per value: document hash, page number, polygon or bbox in normalised page coordinates, the source text span, and the parser and model version. Docling's `TableCell` (bbox, spans, header flags) and Azure DI's cell schema (polygon, content span) are good reference schemas.
- When a VLM emits only element-level boxes, cell-level grounding can be recovered deterministically. For digital PDFs, match each emitted cell string back to PDF text tokens inside the table box, as TableFormer and Docling do. For scans, match against OCR word boxes. Cells that cannot be matched become a quality flag.

### Gaps
- I found no standard benchmark for cell-level grounding accuracy of VLM parsers. FinDocBench's C-IoU is new and comes from one group.

---

## Q5. Which approach produces database-ready output most reliably, at what cost, and where does each fail (including determinism)?

### Takeaway
No single model wins everywhere. The most reliable route to deterministic, grounded records is a tiered pipeline:
- **Tier 1, born-digital PDFs:** text-layer extraction plus a layout detector plus a specialised structure model (TableFormer, TATR or POTATR class). This is the cheapest option (about $47 per million pages for POTATR), the most accurate on single pages, grounded per cell, and non-autoregressive.
- **Tier 2, scans and photos:** a compact, permissively licensed two-stage VLM parser (PaddleOCR-VL or MinerU2.5 class, about 1–2 pages/s per GPU), with element boxes kept.
- **Tier 3, escalation:** frontier multimodal LLMs only for multi-page or complex tables and novel forms. They are 300x or more costlier and not bit-reproducible by default.
- **Throughout:** grounding verification and arithmetic and type checks.

Determinism should be anchored by parsing once into a versioned, immutable snapshot, not by assuming the parser is deterministic.

### Cited Findings

**Cost**
- POTATR costs about $47 per million pages on an A10G, against $15,000–$36,680 for Gemini 3.1 Pro, GPT-5.4 and Claude Opus 4.6. — [POTATR](https://arxiv.org/html/2606.09788v2)
- olmOCR costs $176 per million pages, against about $6,240 for GPT-4o. — [olmOCR](https://arxiv.org/abs/2502.18443)
- Measured throughput:
  - MinerU2.5: 2.12 pages/s (A100) and 4.47 pages/s (H200). — [MinerU2.5](https://arxiv.org/html/2509.22186v2)
  - PaddleOCR-VL: 1.62 pages/s (A100). — [PaddleOCR-VL](https://arxiv.org/html/2510.14528v4)
  - Docling: 0.6–2.45 pages/s on CPU. — [Docling](https://arxiv.org/html/2408.09869v5)
  - DeepSeek-OCR: "200k+ pages per day" on one A100-40G. — [DeepSeek-OCR](https://arxiv.org/abs/2510.18234)
- AWS Textract list prices (US West, first 1M pages per month):
  - Detect Document Text $0.0015 per page.
  - Tables $0.015 per page, with Layout free alongside Tables.
  - Forms $0.05; Tables + Forms + Queries $0.07.
  - AnalyzeExpense $0.01. — [Textract pricing](https://aws.amazon.com/textract/pricing/)

**Accuracy versus model class (independent or semi-independent evidence)**
- PubTables-v2 shows specialised models beating frontier models on cropped and single-page tables, and frontier models leading on full-document multi-page extraction (numbers in Q1). — [PubTables-v2](https://arxiv.org/html/2512.10888v4)
- **Needl.ai vendor report (June 2026; one 17-page financial PDF, about 20 scorable tables; low statistical weight):**
  - Cell accuracy, scored on (row label, column header, value) triples:
    - Local parsers: Docling 0.36, MinerU 0.32, Marker 0.36, PaddleOCR-VL 0.57.
    - Cloud APIs: Textract 0.73, Gemini 3 Flash 0.91, Claude Opus 4.8 1.00, GPT-5.5 0.88.
  - Value fidelity:
    - GPT-5.5 "systematically alters financial-table values", with 25 findings, reproduced across two runs.
    - Textract captures tables incompletely but "never fabricates".
  - Mistral OCR scored 0 on tables. — [Needl.ai benchmark](https://needl.ai/technical-notes/benchmarking-pdf-extraction-tools)
- **Rule-based tools:** Tabula and Camelot reach TEDS 67.9–73.0, against TableFormer at 93.6, on PubTabNet PDFs. — [TableFormer](https://arxiv.org/pdf/2203.01017)

**Failure modes by class**
- **Generative VLMs:**
  - Repetition loops: Nougat on 1.5% of pages; SmolDocling; Qwen2.5-VL in PubTables-v2.
  - Unparseable output: 958 SmolDocling parse failures.
  - Fused or missing tables; spanning-cell errors.
  - Digit confusion and values absent from the source (UNIKIE).
  - Structural hallucination (FireRed-OCR).
  - Large degradation under skew for some models: DeepSeek-OCR Overall 63.01 under Skew.
  - Sources: [Nougat](https://arxiv.org/html/2308.13418v1); [PubTables-v2](https://arxiv.org/html/2512.10888v4); [UNIKIE-Bench](https://arxiv.org/html/2602.07038v2); [FireRed-OCR](https://arxiv.org/abs/2603.01840); [Real5](https://arxiv.org/html/2603.04205v2)
- **Detector and structure-model pipelines:**
  - Downsampling hurts very large tables (TableFormer). — [TableFormer](https://arxiv.org/pdf/2203.01017)
  - Quality depends heavily on OCR when there is no text layer: POTATR falls from 0.965 to 0.783–0.881. — [POTATR](https://arxiv.org/html/2606.09788v2)
  - Pipeline tools collapse under geometric distortion: PP-StructureV3 table TEDS falls from 79 to 25 under skew. — [Real5](https://arxiv.org/html/2603.04205v2)
  - They are domain-bound: POTATR has been tested only on PubMed. — [POTATR](https://arxiv.org/html/2606.09788v2)
- **Layout-encoder key information extraction:** generalisation to unseen templates and line items is weak. On VRDU Ad-buy line items, LayoutLMv3 scores 24.51 F1 even with 200 training documents. — [LMDX](https://arxiv.org/html/2309.10952v2); [VRDU](https://arxiv.org/abs/2211.15421)

**Determinism and reproducibility**
- **LLM inference is not deterministic even at temperature 0.** Batch-size variation changes kernel reduction order.
  - In 1,000 temperature-0 completions of Qwen3-235B, there were 80 unique outputs.
  - Batch-invariant kernels made all 1,000 identical, at roughly 1.6–2x slower (Qwen3-8B on vLLM: 26 s default, 42–55 s deterministic). — [Thinking Machines, He 2025](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)
- **PyTorch guarantees no reproducibility across releases, commits or platforms, or between CPU and GPU.**
  - cuDNN benchmarking "may select different algorithms on subsequent runs, even on the same machine".
  - `torch.use_deterministic_algorithms` enforces deterministic kernels at a speed cost. — [PyTorch randomness notes](https://docs.pytorch.org/docs/2.15/notes/randomness.html)
- **VLM parsers often rely on sampling by design.** olmOCR uses dynamic temperature escalation (0.1 → 0.8) and retries; LMDX samples 16 completions at temperature 0.5 and majority-votes. Their outputs are therefore stochastic unless seeds and kernels are fixed. — [olmOCR 2](https://arxiv.org/html/2510.19817v1); [LMDX](https://arxiv.org/html/2309.10952v2)
- **Constraining output format improves validity, not correctness:**
  - OTSL guarantees syntactically valid tables. — [OTSL](https://arxiv.org/abs/2305.03393)
  - FireRed-OCR uses format-constrained RL. — [FireRed-OCR](https://arxiv.org/abs/2603.01840)
  - olmOCR found that switching from JSON to YAML output "reduced the retry rate dramatically". — [olmOCR 2](https://arxiv.org/html/2510.19817v1)
- **Non-autoregressive detectors such as POTATR run in constant time per page.** Their outputs depend only on the weights and the deterministic post-processing, subject to the PyTorch caveats. — [POTATR](https://arxiv.org/html/2606.09788v2)

**Verification makes outputs database-grade**
- TableVision's sum-check gate confirmed 933 of 934 testable accepted sums. — [TableVision](https://arxiv.org/abs/2610.17448)
- The fiscal-documents pipeline uses hierarchical totals as validation. — [Fiscal documents](https://arxiv.org/abs/2511.10659)
- LMDX rejects values not found in the cited source segment. — [LMDX](https://arxiv.org/abs/2309.10952)

### Inferences
- **Recommended architecture for deterministic agent retrieval:**
  1. Route by document type: born-digital vs scanned, table-heavy vs form.
  2. Parse once with pinned model weights, pinned library versions, greedy decoding, and deterministic kernels where feasible.
  3. Persist a canonical intermediate (DoclingDocument-like JSON with cell bboxes and spans), keyed by document hash plus parser version.
  4. Normalise tables to typed relational rows: header propagation, unit and scale columns, cross-page merge.
  5. Run validation gates (sum checks, type and range checks, source-text matching). Rows that fail are flagged, not silently loaded.
  6. Retrieval determinism then holds by construction over the immutable snapshot. Re-parsing produces a new snapshot version.
- **Cost-quality frontier as of late 2026:**
  - About $50 per million pages (detector models on a text layer).
  - About $100s per million pages (self-hosted 1–3B VLM parsers at 1–2 pages/s per GPU).
  - $0.01–$0.07 per page (cloud document APIs).
  - About $15k–$37k per million pages (frontier multimodal LLMs).
  Escalate to the costlier tiers only on validation failure or on detected multi-page and complex tables.
- **Most consequential failure mode for a database: plausible but wrong values,** such as altered digits or a value under the wrong header, rather than visible structural breakage. Structural metrics (TEDS, GriTS) miss these when the structure is right. Exact-match cell checks against the source text layer, plus arithmetic constraints, are the countermeasure.

### Gaps
- No peer-reviewed, independent study measured hallucinated or altered numeric cells across parsers at scale. The only data point found is a single-document vendor report.
- No study measured run-to-run variance of VLM document parsers under production batching. The determinism claims here are extrapolated from general LLM inference findings (Thinking Machines) and the PyTorch documentation.
- Cost figures for cloud APIs are list prices. The VLM self-hosting costs are derived from reported throughput rather than published $/page, except POTATR and olmOCR.
