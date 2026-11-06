# Converting semi-structured and non-PDF sources into databases (spreadsheets, HTML, emails/contracts/invoices/clinical/financial, scientific literature, audio/video/charts, code/logs)

Scope note: this track covers source types other than plain PDF/prose and large research projects that built databases from literature. "Deterministic retrieval" = exact predicates over typed records with span-level provenance. Throughout, "author-reported" means numbers from the method's own paper; "independent" means a third-party benchmark or re-evaluation. Unless marked otherwise, every number below is author-reported.

A recurring pattern across all source types, which matters for the deterministic-retrieval goal: the strongest results come from **using the model at build time to produce an executable, inspectable artifact**, then running that artifact deterministically over the corpus. Examples of such artifacts are a wrapper/XPath, a transformation program, a log template, or a parse rule. The alternative, calling an LLM per record at extraction time, is less reproducible and more expensive. The exceptions are domains where the "structure" is in meaning, not layout (clinical notes, emails, literature), where per-document LLM extraction plus verification still wins.

---

## 1. Spreadsheets: table detection, normalization of messy Excel (multi-table sheets, merged/hierarchical headers), conversion to relational tables

### Takeaway
Treat spreadsheet-to-database as three separable steps:
1. Detect table regions (CNN or fine-tuned LLM, best reported ~0.79 F1 exact-boundary).
2. Classify cells/lines as header, data, or metadata. Pattern/rule methods reach ~96% precision and recall on CSVs.
3. Synthesize a deterministic relationalization program from a small operator DSL (stack/unpivot, transpose, ffill, …). Auto-Tables gets ~57% top-1 and 75% top-3.

Step 3 yields a replayable pipeline, so the output tables are reproducible and each cell traces to a source cell address. Asking an LLM to emit the table directly does not give you that.

### Cited Findings
- **TableSense (AAAI 2019).** Treats the cell grid like an image and uses a CNN with cell featurization plus active learning, trained on 22,176 tables across 10,220 sheets. It reports 91.3% recall and 86.5% precision under the EoB-2 tolerance metric. The authors say this beats the detection built into commodity spreadsheet tools. — [TableSense, Dong et al.](https://arxiv.org/abs/2106.13500)
- **SpreadsheetLLM (2024) and its SheetCompressor encoder.** Three modules:
  - structural-anchor extraction keeps heterogeneous boundary rows/columns within k=4 and drops ~75% of content while keeping ~97% of boundary rows/columns;
  - lossless inverted-index translation maps value → address ranges and drops empty cells;
  - data-format-aware aggregation groups cells by number format or type.
  Together they cut 1,548,577 tokens to 62,469 (24.8×). — [SpreadsheetLLM, Dong et al.](https://arxiv.org/html/2407.09025v2)
- **SpreadsheetLLM table detection, exact-boundary EoB-0 F1** on 188 sheets / 311 tables re-annotated from the TableSense data:

  | Setting | F1 |
  |---|---|
  | GPT-4 in-context, raw encoding | 0.154 |
  | GPT-4 in-context, compressed | 0.410 |
  | Fine-tuned GPT-4, compressed | 0.759 |
  | Fine-tuned GPT-4, compressed, no aggregation | 0.789 |
  | TableSense-CNN | 0.666 |
  | Fine-tuned Llama3 / Mistral, compressed | 0.719 / 0.726 |

  The headline "78.9%" is the no-aggregation variant. The full pipeline scores 75.9%. — [SpreadsheetLLM](https://arxiv.org/html/2407.09025v2)
- **SpreadsheetLLM QA and limitations.** On spreadsheet QA (307 questions over 64 sheets), Chain-of-Spreadsheet scores 0.743 (fine-tuned GPT-4, compressed) vs 0.466 for plain GPT-4. Stated limitation: background colour and borders are not encoded (too many tokens), and there is no semantic compression of text cells. — [SpreadsheetLLM](https://arxiv.org/html/2407.09025v2)
- **Auto-Tables (PVLDB 2024).** A survey of real spreadsheet and web tables found >30% are non-relational and need restructuring before SQL can use them. — [Auto-Tables, Li et al.](https://arxiv.org/abs/2307.14565)
  - *Method:* a CNN over cell embeddings (Sentence-BERT plus syntactic features) predicts a multi-step program over an 8-operator DSL: stack, wide-to-long, transpose, pivot, explode, ffill, subtitles, none.
  - *Training data:* self-supervised. Inverse operators are applied to ~15K relational tables to make 1.4M pairs, so no human labels are needed.
  - *Results on 244 real cases* (forums, notebooks, Excel, web): Hit@1 0.570 and Hit@3 0.75. Baselines: GPT-3.5 few-shot Hit@1 0.196; FlashRelate 0.336 and Foofah 0.283, both given 100 output-cell examples. Mean latency is 0.224 s per table. — [Auto-Tables HTML](https://arxiv.org/html/2307.14565v2)
- **Pytheas (PVLDB 2020).** Discovers tables inside messy CSVs with rule/pattern line classification and column-value coherency. Tested on 4,500 open-data CSVs from CA/US/UK/AU portals, it reports table-discovery precision >95.9% and recall >95.7%, vs ~89.6% and 81.3% for prior methods. F-measure stays >95% when trained on Canadian data and applied to other countries. — [Pytheas, Christodoulakis et al., PVLDB 13(11)](https://www.vldb.org/pvldb/vol13/p2075-christodoulakis.pdf)
- **HiTab.** Hierarchical (multi-level header) tables from statistical reports and Wikipedia: 3,597 tables and 10,686 QA pairs. A "hierarchy-aware logical form" for symbolic reasoning over hierarchical headers was highly effective. This is evidence that hierarchical headers should be normalized into explicit dimension columns. — [HiTab, Cheng et al.](https://arxiv.org/abs/2108.06712)
- **SQuARE (IEEE BigData 2025).** Computes a per-sheet complexity score from header depth and merge density. It then routes either to structure-preserving chunk retrieval or to SQL over an automatically built relational view. Authors report it beats single-strategy baselines and ChatGPT-4o on multi-header balance sheets and a heavily merged World Bank workbook, "ensuring that returned values are faithful to the original cells." — [SQuARE](https://arxiv.org/abs/2512.04292)
- **SheetBrain (Microsoft, 2025).** A neuro-symbolic agent: an understanding module, an execution module (Python sandbox plus Excel toolkit), and a validation module that re-executes on failure. It introduces SheetBench for large, multi-table, structurally complex sheets. The authors report significant gains, but the abstract gives no absolute numbers. — [SheetBrain](https://arxiv.org/abs/2510.19247)
- **GitTables.** 1M relational tables mined from CSVs on GitHub, with columns annotated by Schema.org/DBpedia semantic types. The authors report annotation quality on par with humans on T2Dv2. These tables are structurally unlike HTML web tables. — [GitTables, Hulsebos et al.](https://arxiv.org/abs/2106.07258)

### Inferences
- For a toolkit, the most deterministic spreadsheet path is:
  1. Parse the .xlsx natively (openpyxl-style) to get exact cell values, formats and merged ranges. Never OCR or render.
  2. Detect regions with a learned detector, or an LLM given a compressed encoding.
  3. Classify header/data/metadata rows (Pytheas-style rules).
  4. Emit a relationalization program over a small DSL (Auto-Tables operators), store it, and replay it.

  Every output row keeps its (sheet, cell-range) provenance, and the stored program makes re-ingestion bit-for-bit reproducible.
- Exact-boundary F1 of ~0.76–0.79 means about one in five tables gets a wrong boundary. A human/agent validation step, or schema constraints (type homogeneity per column), is needed before loading into SQL.
- Merged and hierarchical headers should be flattened into explicit dimension columns (HiTab evidence) rather than concatenated header strings.

### Gaps
- I found no independent re-evaluation of SpreadsheetLLM or Auto-Tables beyond their own benchmarks.
- No published numbers on frontier 2026 models for exact-boundary table detection.
- No standard benchmark measures end-to-end "spreadsheet → correct relational schema + values" accuracy. Existing ones measure detection or QA separately.

---

## 2. Web/HTML: wrapper induction (classic and LLM-generated), SWDE/WebSRC, closed IE from web tables (WDC, TURL), Common Crawl tables

### Takeaway
Template-generated websites are the best case for deterministic extraction. Induce a wrapper (XPath/CSS selector program) per site from a few pages, then run it over every page. LLMs now generate these wrappers zero-shot:
- AutoScraper: ~72% of SWDE extraction tasks fully correct with GPT-4-Turbo.
- Evaporate-Code+: beats direct per-document LLM extraction by about 10 F1 points at ~110× lower token cost.
- WebLists' BardeenAgent: 66% recall vs 31% for agents that are not program-based.

Grounding every value to a DOM node/XPath (AXE's "Grounded XPath Resolution") gives span-level provenance. Pages that already embed schema.org JSON-LD or microdata should be read directly, with no extraction model.

### Cited Findings
- **SWDE (SIGIR 2011), the canonical benchmark.** 8 verticals, 80 sites (10 per vertical), 124,291 pages, 32 attributes, labelled at the DOM text-node level. — [Hao et al., SIGIR 2011](https://doi.org/10.1145/2009916.2010020); [dataset record](https://academictorrents.com/details/411576c7e80787e4b40452360f5f24acba9b5159)
- **CERES (VLDB 2018).** Distantly supervised wrapper learning that aligns an existing KB to DOM nodes. On >400,000 pages from dozens of long-tail multilingual sites it harvested 1.25M facts at 90% precision. — [CERES, Lockard et al.](https://arxiv.org/abs/1804.04635)
- **FreeDOM (KDD 2020).** Neural node representation (text plus markup) followed by a relational network. It generalizes to unseen sites in a vertical, +3.7 F1 over prior SOTA on SWDE, without rendering features. — [FreeDOM, Lin et al.](https://arxiv.org/abs/2010.10755)
- **MarkupLM (ACL 2022).** Jointly pre-trains text and markup (XPath embeddings) for HTML/XML document understanding and significantly beats layout-free baselines. — [MarkupLM](https://arxiv.org/abs/2110.08518)
- **WebSRC.** 400K QA pairs over 6.4K pages, with HTML, screenshots and metadata. Answers are text spans or yes/no and require structural understanding. — [WebSRC](https://arxiv.org/abs/2101.09465)
- **Evaporate (PVLDB 2023).** Two strategies: an LLM extracts each document directly, or an LLM synthesizes extraction code. — [Evaporate, Arora et al.](https://arxiv.org/html/2304.09433v3)
  - *Evaporate-Code+ method:* generates many candidate functions from two prompt templates and 10 sample documents. It scores each function against LLM extractions on the sample, drops those scoring ≤0.5, treats empty output as abstention, and aggregates with weak supervision.
  - *Quality:* averaged over FDA reports, Enron emails, Wiki NBA and two SWDE verticals, OpenIE pair F1 is 66.7 for Code+ vs 56.6 for Direct.
  - *Cost:* ~1.9M tokens (~$39) vs ~258M tokens (~$5,157) per 10K documents, about 110× fewer.
  - *Without weak supervision:* majority vote over functions scores 56.2 and does not beat Direct.
  - *Failure modes:* >40% of generated functions score <25 F1. Code+ loses on free text (Enron: 86.9 vs 93.8 Direct). Direct LLM extraction on FDA misses ~27.5% of gold attributes per document, invents ~9.7 unmentioned attributes per document, and names the same attribute inconsistently.
  - *Closed IE:* Code+ averages 82.3 F1. On SWDE Movie it scores 79.5 vs 71.9 for the in-domain-trained DOM-LM. — [Evaporate](https://arxiv.org/html/2304.09433v3)
- **AutoScraper (2024; earlier titled AutoCrawler).** An LLM generates an XPath action sequence top-down through the DOM, backtracks up the tree on failure (max 5 retries), and synthesizes across 3 seed pages, with an LLM picking the most generalizable program. — [AutoScraper, Huang et al.](https://arxiv.org/html/2404.12753v2)
  - *Metric:* "executability": the percentage of (site, field) tasks with precision = recall = 1.
  - *SWDE "Correct" rates:* GPT-4-Turbo 71.56% (vs 61.88% CoT, 67.50% Reflexion); GPT-3.5-Turbo 54.84%; Mixtral-8×7B 46.88%; CodeLlama 23.99%.
  - *vs direct extraction:* direct LLM extraction beats the generated scraper for every model except GPT-4-Turbo, where the scraper gets 88.69 F1 vs 78.56.
  - *Cost:* break-even vs per-page LLM extraction at ~19.5 pages per site.
  - *Failure modes:* fields at varying DOM locations; values like "Not Available"; multi-location fields (addresses); XPaths with text predicates that break on new pages. Does not transfer to open-web tasks (Mind2Web/WebArena). — [AutoScraper](https://arxiv.org/html/2404.12753v2)
- **WebLists (2025).** 200 enterprise data-extraction tasks requiring navigation plus extraction of complete datasets. LLMs with search reach 3% recall and SOTA web agents 31%. BardeenAgent records the agent's execution as a replayable program with a generalizable CSS selector and reaches 66% recall at 3× lower cost per output row. — [WebLists](https://arxiv.org/abs/2504.12682)
- **Mind2Web.** Raw HTML of real sites is usually too large for LLMs. Filtering with a small LM first significantly improves effectiveness and efficiency. The same pruning idea recurs in extraction systems. — [Mind2Web](https://arxiv.org/abs/2306.06070)
- **AXE (2026).** Prunes the DOM tree to strip boilerplate, then a 0.6B LLM generates structured output. "Grounded XPath Resolution" ensures "every extraction is physically traceable to a source node." Zero-shot SWDE F1 is 88.1%. — [AXE](https://arxiv.org/abs/2602.01838)
- **NEXT-EVAL (2025).** Builds evaluation sets from MHTML snapshots with XPath labels. Its structure-aware metrics allow only positional hallucination, not text hallucination. LLMs given "Flat JSON" serialization of the DOM reach F1 0.9567 with minimal hallucination, outperforming slimmed HTML and hierarchical JSON inputs. It also benchmarks deterministic heuristic record extractors. — [NEXT-EVAL](https://arxiv.org/abs/2505.17125)
- **ScrapeGraphAI-100k (2026).** 93,695 real schema-constrained extraction events from ScrapeGraphAI telemetry (Markdown page → JSON schema), 18K+ schemas. Labels cover only structural schema conformance; semantic correctness is out of scope. The authors find "sharp failure thresholds as schema complexity grows." A distilled 1.7B student trails a 30B-A3B reference on schema compliance. — [ScrapeGraphAI-100k](https://arxiv.org/abs/2602.15189)
- **WDC Web Tables (2016).** A public corpus of 233M+ HTML tables from the July 2015 Common Crawl, each with source URL and context metadata. — [Lehmberg et al., WWW 2016 companion](https://archives.iw3c2.org/www2016/WWW2016-Proceedings/companion/p75.pdf)
- **TURL (PVLDB 2020).** Pre-trains a structure-aware Transformer on relational web tables with masked entity recovery. It improves 6 table-understanding tasks (entity linking, column type annotation, relation extraction, cell filling, etc.). These tasks map web tables onto KB schemas. — [TURL](https://arxiv.org/abs/2006.14806)
- **Schema.org data from Common Crawl.** Web Data Commons extracts schema.org data embedded in pages at Common Crawl scale and publishes it as RDF. For product data, an empirical study derives six best practices because raw WDC data is not directly usable without cleaning. — [Selvam & Kejriwal](https://arxiv.org/abs/2007.13829)
- **WDC-PAVE.** Built from 59 sites with schema.org annotations. GPT-4 extracts product attribute values at 91% F1, beating PLM extractors (SU-OpenTag, AVEQA, MAVEQA) by ~10 points. It performs similarly when also normalizing values (unit conversion, name expansion). — [Brinkmann, Baumann, Bizer](https://arxiv.org/abs/2403.02130)

### Inferences
- Ranked approach for HTML, most to least deterministic:
  1. Read embedded structured data (JSON-LD, microdata, RDFa) and HTML `<table>` elements directly.
  2. For template-generated sites, have an LLM induce a site-level wrapper (XPath/CSS program). Validate it on held-out pages of the same site, version it, and replay it. Re-induce when validation fails, which signals layout drift.
  3. For heterogeneous one-off pages, use per-page LLM extraction constrained to return DOM-node references (AXE/NEXT-EVAL style), so values are verbatim spans.
- Wrappers are deterministic given a fixed HTML snapshot. Snapshot the raw HTML/MHTML alongside extracted rows so retrieval is reproducible after the live page changes.
- Evaporate's Enron result shows code synthesis is the wrong tool for free text. Pick the method by whether structure is in the markup or in the language.

### Gaps
- No independent head-to-head of AutoScraper vs Evaporate-Code+ vs AXE on identical splits; all numbers are author-reported on differing SWDE subsets and metrics.
- No longitudinal study found on wrapper breakage rates when LLM-generated wrappers face live site changes.
- No Common Crawl table corpus newer than the WDC 2015 table corpus was verified in this pass.

---

## 3. Emails, chat logs, tickets, contracts (CUAD), invoices, clinical notes (n2c2/MIMIC), financial filings (XBRL vs extracted), patents

### Takeaway
- **Prefer native structure where it exists.** XBRL in filings, structured EHR tables, email headers. Mapping free numbers to XBRL concepts is very hard: best LLM concept-linking accuracy is <0.19.
- **Narrative sources** (emails, contracts, clinical notes) still show large gaps:
  - MailEx: fine-tuned extractors reach ~0.37–0.65 F1, and GPT-3.5 in-context learning fabricates ~36% of erroneous arguments.
  - CUAD: best supervised model scores 44% precision at 80% recall.
  - Clinical NER: prompted GPT-4 at 0.86 relaxed F1 trails fine-tuned BioClinicalBERT at 0.90.
- **Hybrid "deterministic parser + schema-guided LLM" pipelines with clinician validation** reach >92% accuracy on MIMIC discharge summaries.
- **Invoices:** vision-native multimodal LLMs beat text-converted inputs by large margins on scans.

### Cited Findings
- **MailEx, email event extraction.** 1.5K threads, ~4K emails, 10 event types, 76 argument types. — [MailEx](https://arxiv.org/html/2305.13469v2)
  - *Test-set F1:* fine-tuned BERT gets trigger-ID 0.537 and argument classification 0.368. GPT-3.5 (text-davinci-003) few-shot gets 0.169 and 0.058.
  - *LLM errors:* ~36% of gpt-3.5-turbo's argument errors were fabricated entities absent from the email; ~42% were semantically incorrect.
  - *Hardest cases:* non-contiguous shared triggers, long non-named-entity arguments (e.g., meeting agendas), and thread history.
- **Evaporate on Enron emails.** Direct LLM extraction (93.8 F1) beat code synthesis (86.9) on free-text emails. — [Evaporate](https://arxiv.org/html/2304.09433v3)
- **CUAD (NeurIPS 2021 D&B).** 510 contracts, 13,101 expert-labelled clauses across 41 categories. Annotation cost is estimated at >$2M (9,283 pages, each reviewed ≥4 times). Best model (DeBERTa-xlarge): AUPR 47.8%, precision 44.0% at 80% recall, 17.8% at 90% recall. BERT-base gets 8.2% at 80% recall. — [CUAD, Hendrycks et al.](https://arxiv.org/abs/2103.06268)
- **ContractEval (2025), an independent LLM evaluation on CUAD** (4 proprietary, 15 open models). Findings:
  - proprietary models beat open ones;
  - "thinking" mode improves output effectiveness but reduces correctness;
  - open models often answer "no related clause" when one exists ("laziness");
  - quantization costs accuracy.

  Most LLMs perform at roughly junior-legal-assistant level. — [ContractEval](https://arxiv.org/abs/2508.03080)
- **DocILE.** 6.7k annotated business documents, 55 key-information classes, plus line-item recognition. Baselines include LayoutLMv3 and Table Transformer, and the test set includes zero/few-shot layouts. — [DocILE](https://arxiv.org/abs/2302.05658)
- **Invoices: image vs Markdown input** (8 multimodal LLMs, zero-shot; independent of the model vendors).

  | Dataset | Best native-image accuracy | Markdown (Docling) accuracy |
  |---|---|---|
  | SROIE receipts | Gemini-2.5-pro 87.46% | 46.54% |
  | Scanned inv-cdip | Gemini-2.5-pro 92.71% | 63.94% |
  | Clean synthetic invoices | — | most models capped at 84–85% |

  On clean invoices the Markdown cap is attributed to the conversion step. IBANs fail through OCR-style confusions (0/O). Exact-match scoring did not normalize number punctuation. — [Berghaus et al.](https://arxiv.org/html/2509.04469v1)
- **Clinical NER with prompted LLMs.** MTSamples (i2b2-2010-style concepts): GPT-4 relaxed F1 0.804 with baseline prompts and 0.861 with guideline, error-analysis and few-shot prompts, vs fine-tuned BioClinicalBERT 0.901. VAERS: 0.736 vs 0.802. — [Hu et al., JAMIA 2024](https://arxiv.org/abs/2303.16416)
- **Few-shot clinical IE.** InstructGPT/GPT-3 does well at zero/few-shot clinical IE (span ID, token classification, relation extraction) on re-annotated CASI data and significantly beats prior zero/few-shot baselines. — [Agrawal et al., EMNLP 2022](https://arxiv.org/abs/2205.12689)
- **MIMIC-Note-Extract (2026).** A hybrid pipeline of "deterministic parsing with schema-guided LLM generation" turns 16 sections of 300,720 MIMIC-IV discharge summaries into structured tables. Validation by physicians: >92% accuracy across sections. It yields 10× more patient-history entries than structured MIMIC tables. — [MNE](https://arxiv.org/abs/2611.04685)
- **Reproducibility audit on MIMIC-IV discharge summaries (2026).** Three prompt variants × two model sizes over a fixed 17-flag yes/no/not_documented schema. Results:
  - cross-prompt agreement median κ ≈ 0.68–0.69;
  - most disagreement sits on the absence-vs-silence distinction and vanishes when collapsed to binary;
  - for a 47-tag admission-reason field, changing the model reassigns the dominant tag on ~half of notes, and changing prompt wording on ~1 in 8. — [Murin](https://arxiv.org/abs/2606.05970)
- **XBRL tagging, FiNER-139.** 1.1M sentences with gold XBRL tags over 139 entity types. Subword fragmentation of numbers hurts BERT; numeric pseudo-tokens and a domain SEC-BERT help. — [FiNER, ACL 2022](https://arxiv.org/abs/2203.06482)
- **FinTagging (2025).** 142 10-Ks: 319,893 sentences, 21,576 tables, 261,457 numeric facts linked to a 17,688-concept US-GAAP taxonomy. — [FinTagging](https://arxiv.org/html/2505.20650v5)
  - *Numeric fact extraction (FinNI) F1:* DeepSeek-V3 0.693, GPT-4o 0.540.
  - *Concept linking (FinCL) accuracy:* ≤0.189 for all models. Retrieval Acc@200 is only ~0.33, and table-origin facts are harder.
  - *Single-step classification over the full taxonomy* scores zero.
- **FinQA.** Expert-written QA over financial reports with gold reasoning programs. Pre-trained models "fall far short of expert humans" on multi-step numerical reasoning. This argues for storing filings' numbers as typed facts and computing deterministically. — [FinQA](https://arxiv.org/abs/2109.00122)
- **Patents (chemical reactions), ChEMU 2020 (CLEF).**
  - *Corpus:* 1,500 snippets from 170 patents; inter-annotator agreement 0.976 (NER) and 0.951 (events).
  - *Results:* best NER F1 0.957 exact (up to ~0.99 relaxed); event extraction 0.954 given gold entities; end-to-end systems ~0.92 F1. Seven runs exceeded 0.90 exact-match NER vs sixteen under relaxed match.
  - *What helped:* domain tokenizers (OSCAR4) and domain embeddings. — [He et al., ChEMU 2020 overview, Frontiers 2021](https://www.frontiersin.org/articles/10.3389/frma.2021.654438/pdf)

### Inferences
- **Financial data.** Ingest XBRL facts (already typed, unit-tagged and concept-linked) as the primary store. Use text extraction only for narrative facts. FinTagging shows that re-deriving concept links from text is unreliable (<19%).
- **Emails.** Header fields (from, to, date, thread-id, message-id) are deterministic metadata and should be primary keys. Body-level event/argument extraction needs fine-tuned models or LLM extraction constrained to verbatim spans, since ICL fabricates arguments.
- **Clinical.** The MNE pattern is the most credible template for a toolkit: deterministic section parsing, then schema-guided LLM per section, then expert validation. The audit shows schemas need an explicit "not documented" value and must pin the model version, because model choice moves results more than prompt wording.
- **Contracts.** Clause extraction is span-based, which gives natural provenance. Accuracy at high recall is still low, so contract databases need human review before predicates over them can be trusted.
- **Invoices and scanned forms.** Run extraction on the image with a multimodal model, or use a layout-aware model (DocILE baselines), rather than lossy text conversion. Validate arithmetic (line items sum to totals) deterministically.

### Gaps
- No peer-reviewed benchmark found for chat logs or support tickets → structured records with LLMs (MailEx is the closest). Treat ticket extraction evidence as missing.
- No independent study found comparing XBRL-native facts against LLM-extracted facts on the same filings for value accuracy (rather than tagging).
- The n2c2 2018 medication/ADE track overview numbers were not retrieved in this pass.

---

## 4. Scientific literature to databases: materials, chemistry reactions, biomedicine, systematic-review extraction with LLMs; reported precision/recall

### Takeaway
Large literature-to-database projects split into three generations:
1. **Rule/grammar pipelines** (ChemDataExtractor family). Precision 73–92%, recall often ~59–64%, deterministic.
2. **Fine-tuned NER/RE pipelines** (MatSciBERT/MaterialsBERT, PubTator, Kononova synthesis recipes). High precision on entities, low end-to-end yield: 28% of synthesis paragraphs yield a balanced reaction.
3. **LLM pipelines with verification** (ChatExtract ~91% precision / ~88% recall; MOF ChatGPT 90–99% author-reported; GPT-3.5 polymer F1 0.67–0.85). Better recall, but they depend on the model version.

Systematic-review extraction with LLMs reaches ~80–96% item accuracy on small samples, but independent studies show only moderate agreement once chance is corrected. The field has converged on human-in-the-loop with span evidence.

### Cited Findings
**Rule/grammar generation (deterministic)**
- **ChemDataExtractor (2016).** Tokenization, POS tagging, chemical NER (with word clusters), phrase-grammar parsing, and document-level resolution across text, tables and captions. F-scores: 93.4% (chemical identifiers), 86.8% (spectroscopic attributes), 91.5% (property attributes); 87.8% on CHEMDNER. MIT-licensed. — [Swain & Cole, JCIM 2016](https://www.repository.cam.ac.uk/bitstream/1810/266462/1/chemdataextractor.pdf)
- **ChemDataExtractor 2.0 (2021).** Auto-populates user-defined nested ontologies, focused on tables. A crystallographic hierarchy of 18 interrelated submodels is extracted at 92.2% overall precision across 26 journals. — [Mavračić et al., JCIM 2021](https://doi.org/10.1021/acs.jcim.1c00446)
- **Curie/Néel temperature database.** 39,822 records from 68,078 articles via ChemDataExtractor plus modified Snowball. Precision is reported as 73% (journal page) vs 82% (another record), an inconsistency between secondary sources. The built-in ChemDataExtractor 1.3 rules alone gave 66%. A 2025 follow-up has 56,037 records from 108,181 articles at 72% precision and 61% recall. — [Court & Cole, Sci Data 2018](https://www.nature.com/articles/sdata2018111.pdf); [Kelly & Cole 2025 follow-up](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12738733/)
- **Battery materials database (2020).**
  - *Scale:* 292,313 records (214,617 unique chemical–property relations; 17,354 chemicals) from 229,061 papers, using rule-based ChemDataExtractor 1.5.
  - *Overall quality:* precision 80.0%, recall 59.1%, F 68.0%. Precision was judged on 500 random records; recall from 51 papers.
  - *Error split:* wrong compound–value match 52%, incomplete composite names 31%, invalid names 10%, interdependency (cross-sentence) errors 7%.
  - *Trade-off:* filtering flagged records raises precision to ~85%. — [Huang & Cole, Sci Data 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7411033/)

**Fine-tuned NER/RE generation**
- **Text-mined inorganic synthesis recipes (Ceder group, 2019).** — [Kononova et al., Sci Data 2019](https://pmc.ncbi.nlm.nih.gov/articles/PMC6794279/)
  - *Pipeline:* 4.2M papers and 6.2M paragraphs; random-forest paragraph classifier; BiLSTM-CRF material roles (834 annotated paragraphs); operation classifier; regex conditions; SymPy equation balancing.
  - *Yield:* 19,488 recipes from 53,538 solid-state paragraphs, i.e. 28% of paragraphs give a balanced reaction.
  - *Precision by field:* precursors 0.99, targets 0.97, operations 0.86, heating temperature 0.85, mixing media 0.62.
  - *Whole-recipe accuracy:* 93% at chemistry level but only 51% with all attributes.
  - *Known failures:* doped and solid-solution materials, multi-word names.
- **MatSciBERT.** Materials-domain BERT that beats SciBERT on NER, relation extraction and abstract classification. — [Gupta et al., npj Comput Mater 2022](https://arxiv.org/abs/2109.15290)
- **Polymer pipeline (MaterialsBERT).** ~300,000 property records from ~130,000 abstracts in 60 hours, served at polymerscholar.org. — [Shetty et al., npj Comput Mater 2023](https://arxiv.org/abs/2209.13136)
- **DiSCoMaT.** Extracts material compositions from tables in materials papers: 4,408 distantly supervised tables plus 1,475 annotated ones. Combines GNNs with task-specific regular expressions and constraints, and beats generic table models. — [DiSCoMaT, ACL 2023](https://arxiv.org/abs/2207.01079)

**LLM generation (with verification)**
- **Polymer LLM pipeline (2024).**
  - *Scale:* ~2.4M full-text articles → ~681,000 polymer articles (~11% of paragraphs pass heuristic and NER filters) → >1M records for 24 properties of >106,000 polymers.
  - *F1:* GPT-3.5 0.67 (Tg) and 0.85 (bandgap); MaterialsBERT 0.63 and 0.66; LlaMa-2 0.64 (Tg).
  - *Cost:* GPT-3.5 cost ~$4.48 per ~2.9M tokens. MaterialsBERT processed 6,179 paragraphs locally in <30 min at no cost.
  - *Failure mode:* LLMs can hallucinate values when an entity is absent. — [Gupta et al., Commun Mater 2024](https://www.nature.com/articles/s43246-024-00708-9.pdf)
- **Fine-tuned GPT-3/Llama-2 joint NER+RE to JSON** (~500 training examples).
  - Host–dopant linking: best F1 0.821 (Llama-2, JSON schema).
  - MOF and general tasks: exact-match F1 ~0.3–0.6, which the authors call a lower bound because exact word match penalizes paraphrase. — [Dagdelen et al., Nat Commun 2024](https://www.nature.com/articles/s41467-024-45563-x.pdf); preprint [Dunn et al.](https://arxiv.org/abs/2212.05238)
- **ChatExtract.** — [Polak & Morgan, Nat Commun 2024](https://arxiv.org/html/2303.05352v3)
  - *Method:* sentence relevance filter (yes/no), passage = title + previous sentence + target, single- vs multi-valued paths, and redundant yes/no follow-up verification inside one conversation.
  - *Bulk-modulus test set, precision/recall:* GPT-4 90.8/87.7; GPT-3.5 70.1/65.4; LLaMA2-70B 61.5/62.9; ChemDataExtractor2 57/31.
  - *Ablation:* removing the follow-up questions drops GPT-4 precision to 42.7%.
  - *Metallic-glass critical cooling rates:* standardized database precision 91.9% and recall 84.2% vs a 721-entry manual reference. The paper also states 91.6/83.6 elsewhere.
  - *Reproducibility:* dated model snapshots (gpt-4-0314) were pinned for reproducibility, and the authors flag model deprecation as a reproducibility risk.
- **MOF synthesis with ChatGPT.** 26,257 synthesis parameters for ~800 MOFs. Author-reported precision/recall/F1 is 90–99% with "ChemPrompt" engineering, and the workflow code was written by ChatGPT. — [Zheng et al., JACS 2023](https://arxiv.org/abs/2306.11296)
- **Eunomia, a zero-shot LLM agent with tools.** Comparable or superior to fine-tuned SOTA on doping, MOF formula and property relations. — [Ansari & Moosavi](https://arxiv.org/abs/2312.11690)
- **OpenChemIE, multimodal (text + tables + figures) reaction extraction.** End-to-end F1 69.5% on R-group reaction schemes. 64.3% accuracy when compared directly against Reaxys. — [Fan et al., JCIM 2024](https://arxiv.org/abs/2404.01462)

**Manual / crowd curation baseline**
- **Perovskite Database.** The authors "manually gone through every paper found in the Web of Science with the search phrase 'perovskite solar' up to the end of February 2020 (that is, over 15,000 papers)" and manually extracted data for >42,400 devices with up to 100 parameters each, as a large multi-institution team effort under FAIR principles. — [Jacobsson et al., Nature Energy 2022](https://www.nature.com/articles/s41560-021-00941-3.pdf); [eprint record](https://eprints.gla.ac.uk/255586/)

**Biomedicine**
- **PubTator 3.0.** >1B entity and relation annotations over ~36M abstracts and 6M PMC full texts, updated weekly. Entity-pair search beats PubMed and Google Scholar on top-20 precision. GPT-4 with PubTator APIs improves factuality and verifiability. — [Wei et al., NAR 2024](https://arxiv.org/abs/2401.11048)
- **BioDEX, adverse drug event reports.** 65k abstracts and 19k full texts with 256k expert-made reports. Best model 62.3% F1 vs estimated human 72.0%. — [D'Oosterlinck et al.](https://arxiv.org/abs/2305.13395)

**Systematic-review data extraction**
- **Claude 2 proof of concept.** 10 RCT PDFs, 160 data items: accuracy 96.3% (test–retest 96.9% / 95.0%), with 4 of 6 errors being omissions. — [Gartlehner et al., Res Synth Methods 2024](https://medrxiv.org/content/medrxiv/early/2023/10/03/2023.10.02.23296415.full.pdf)
- **Claude 2 vs GPT-4.** 96.3% vs 68.8% (GPT-4 errors mostly from its PDF plug-in). On selected text, 98.7% vs 100%. A 2025 workflow-validation preprint in six live reviews found only 77.2% concordance between LLM-plus-human-verification and standard extraction. — [Konet et al., Res Synth Methods 2024](https://pubmed.ncbi.nlm.nih.gov/38895747/); [RTI summary](https://www.rti.org/publication/performance-two-large-language-models-data-extraction-evidence-synthesis)
- **Pre-registered "human-out-of-the-loop" GPT-4 evaluation** (independent of the model vendor). Accuracy looked on par with humans, but after adjusting for chance agreement and imbalance, data extraction was only "moderate." — [Khraisha et al., Res Synth Methods 2024](https://arxiv.org/abs/2310.17526)
- **GPT-4 feasibility study.** ~80% accuracy (82% clinical, 80% animal, 72% social science). Causal-inference and study-design items were most error-prone. The authors observed run-to-run variability and advise using the LLM as a second or third reviewer. — [Schmidt et al., ALTARS 2024](https://arxiv.org/abs/2405.14445)
- **TrialMind.** 100 reviews and 2,220 studies. Data extraction beats a GPT-4 baseline by 29.6–61.5%. Human+AI gives a 23.5% accuracy lift and 63.4% time saving. — [Wang et al.](https://arxiv.org/abs/2406.17755)
- **LEADS.** A domain model trained on 633,759 instruction examples from 21,335 reviews. Experts with LEADS: extraction accuracy 0.85 vs 0.80 alone, with 26.9% time saved. — [Wang et al. 2025](https://arxiv.org/abs/2501.16255)
- **EviStreams (2026).** Typed field definitions instead of prompts, every value shown with its supporting passage, and blinded dual review with adjudication. Across four clinical corpora and three frontier model families, "extraction quality is shaped far more by the field specification than by the choice of model." — [EviStreams](https://arxiv.org/abs/2609.27418)

### Inferences
- **Precision vs recall.** Rule-based pipelines (ChemDataExtractor, Kononova) are deterministic and auditable but cap recall at ~60%. LLM-with-verification raises recall to ~85–90% at similar precision on narrow schemas (material–value–unit triplets), but brings model-version drift. A practical design keeps the LLM for candidate generation, then:
  - stores the verbatim source sentence and offsets;
  - normalizes units deterministically (pymatgen/regex, as ChatExtract does);
  - freezes the resulting table as the queryable snapshot, so retrieval is deterministic even if extraction is not.
- **Schema design matters more than model choice** (EviStreams; Murin's audit). Typed fields with explicit "not reported" values and per-field definitions should be first-class in the toolkit.
- **Whole-record accuracy is far below per-field accuracy** (Kononova: 93% chemistry vs 51% full recipe). Agents querying multi-field predicates over extracted DBs will see compounding error. Expose per-field confidence and provenance.

### Gaps
- Most precision/recall numbers are author-reported on small samples: 100 paragraphs (Kononova), 10 PDFs (Gartlehner), 500 records (battery DB). Large independent audits are rare. Khraisha and the 2025 workflow preprint are the main independent checks, and both are less rosy.
- Cost per extracted record for frontier 2026 models at multi-million-paper scale was not found.
- The perovskite database's manual-curation error rate was not found.

---

## 5. Audio/video/meetings → structured records (ASR + extraction); images/charts → data (DePlot, MatCha, ChartQA, UniChart)

### Takeaway
- **Audio.** The dominant and most auditable design is a cascade: ASR with word-level timestamps (Whisper/WhisperX), then text extraction, with each field linked to an audio time span. Downstream extraction quality degrades almost linearly with word error rate (Pearson r ≈ −0.9 for several SLU tasks). On named-entity localization, pipelines beat end-to-end speech models (Frame-F1 74.1 vs 56.3).
- **Charts.** Chart-to-table "derendering" models (DePlot, MatCha) reach RMS-F1 ~92–94 on synthetic PlotQA, but only ~78% on out-of-domain charts. Multimodal LLMs show systematic y-axis biases. Chart-derived numbers should be flagged as estimates unless the chart's source data is available.

### Cited Findings
- **Whisper.** Trained on 680,000 hours of multilingual weakly supervised audio. Zero-shot it approaches fully supervised results and human robustness. — [Radford et al., ICML 2023](https://arxiv.org/abs/2212.04356)
- **WhisperX.** Adds voice-activity detection and forced phoneme alignment to give word-level timestamps; plain Whisper's timestamps are inaccurate and not word-level. Buffered long-form Whisper is prone to drift, hallucination and repetition. VAD-based batching gives a 12× speedup. — [Bain et al., Interspeech 2023](https://arxiv.org/abs/2303.00747)
- **SLUE.** Natural-speech benchmarks for NER, sentiment and ASR, designed to compare pipeline vs end-to-end. — [Shon et al.](https://arxiv.org/abs/2111.10367)
- **SLUE Phase-2, named-entity localization.** Frame-F1: pipeline with oracle text 89.0; pipeline with NeMo ASR 74.1; pipeline with wav2vec2 65.2; end-to-end wav2vec2 56.3. Across >20 ASR models, WER correlates with downstream quality: dialog acts r = −0.9, QA r = −0.89, summarization r = −0.9. — [Shon et al., ACL 2023](https://arxiv.org/html/2212.10525v2)
- **AISHELL-NER, Chinese speech NER.** Homophones make speech NER harder. Combining entity-aware ASR with a pretrained NER tagger works best. — [Chen et al.](https://arxiv.org/abs/2202.08533)
- **MUG / AliMeeting4MUG.** 654 Mandarin meetings annotated for topic segmentation, summarization, keyphrase extraction and action-item detection. Annotations are on manual transcripts. — [Zhang et al.](https://arxiv.org/abs/2303.13939)
- **DePlot.** — [Liu et al., Findings ACL 2023](https://arxiv.org/html/2212.10505v2)
  - *Metrics:* RMS treats a table as (row, column, value) triples matched with Levenshtein distance on keys and relative distance on values. RNSS compares number sets only.
  - *PlotQA RMS-F1:* DePlot 94.2, MatCha 92.3, ChartOCR 60.1, PaLI-17B 74.9.
  - *Downstream QA:* DePlot plus an LLM gets 67.6% on ChartQA-human vs MatCha 38.2%, but trails supervised MatCha on PlotQA (66.6 vs 91.5).
  - *Out-of-domain (TaTa charts):* ~78% RMS-F1.
  - *Failure modes:* distraction by adjacent text, arrow-linked labels, line points misaligned with x-labels (extrapolated values), and loss of colour/shape attributes.
- **MatCha.** Pix2Struct-based pretraining on chart derendering plus math reasoning. Up to ~20% better than prior SOTA on PlotQA and ChartQA. — [Liu et al., ACL 2023](https://arxiv.org/abs/2212.09662)
- **ChartQA.** 9.6K human-written plus 23.1K generated questions requiring visual and logical reasoning over charts. — [Masry et al., Findings ACL 2022](https://arxiv.org/abs/2203.10244)
- **UniChart.** Chart-specific pretraining including low-level data-table extraction. SOTA on three downstream chart tasks at the time. — [Masry et al., EMNLP 2023](https://arxiv.org/abs/2305.14761)
- **ChartAssistant.** Chart-to-table pre-training followed by multitask instruction tuning. Beats UniChart and ChartLlama, especially zero-shot on real-world charts. — [Meng et al.](https://arxiv.org/abs/2401.02384)
- **FairChart2Table (2026).** Five SOTA multimodal LLMs show significant chart-to-table biases tied to y-axis tick digit length, number of ticks, value range, tick format (abbreviated or scientific) and number of legend entities. Prompting with y-axis information helps some models. — [Song et al.](https://arxiv.org/abs/2604.24987)

### Inferences
- **Audio/meeting toolkit pattern:**
  1. Run deterministic ASR settings (fixed model version and decoding, no temperature fallback where possible) with WhisperX-style word timestamps and speaker diarization.
  2. Store the transcript as the canonical text layer.
  3. Extract records from it, each holding (start_ms, end_ms, speaker) provenance.

  Because errors compound with WER, keep the ASR confidence per span and allow re-extraction when ASR is upgraded.
- **Video.** Treat it as audio + keyframes + OCR; no direct video→database evidence was found (see Gaps).
- **Charts.** Prefer the chart's underlying data when available (embedded spreadsheet in Office files, SVG/JSON specs in HTML). Use derendering only as a fallback, and mark values as `derived_from_image=true` with the bounding box.

### Gaps
- No benchmark found for "meeting recording → structured action-item/decision database" with end-to-end precision/recall and LLM extractors. MUG baselines are on manual transcripts.
- No peer-reviewed evidence found on video → structured records beyond chart/document frames.
- No independent 2025–2026 evaluation found of frontier multimodal LLMs on exact chart-to-table RMS-F1 across real-world charts.

---

## 6. Code repositories and logs → structured metadata

### Takeaway
- **Logs.** The closest analogue to "LLM builds a deterministic artifact". Template parsers (Drain) are deterministic and fast but degrade on realistic data (FGA ~0.75 → ~0.55 on Loghub-2.0). LLM parsers with a template cache (LILAC) improve template accuracy by ~70% while querying the LLM only for new templates. The cached templates then act as deterministic regex-like parsers.
- **Repositories.** Metadata extraction mixes deterministic sources (package manifests, GitHub API, license files) with classifiers over READMEs (SOMEF), and can feed a knowledge graph.

### Cited Findings
- **Drain (2017).** Online streaming log parser with a fixed-depth parse tree. Highest accuracy on 4 of 5 datasets (>10M log lines) and a 51.8–81.5% runtime improvement over prior online parsers. — [He et al., ICWS 2017](https://pinjiahe.github.io/files/pdf/research/ICWS17.pdf)
- **Loghub-2.0 (ISSTA 2024).** 14 datasets averaging 3.6M lines each, used to re-evaluate 15 parsers.
  - All parsers degrade vs Loghub-2k. Drain is the most performant on grouping, with FGA falling from ~0.75 to ~0.55.
  - Only 7 of 15 parsers finished all datasets within 12 hours.
  - Templates with >5 parameters are nearly unparseable (FGA ≤0.16).
  - MoLFI and LogPPT have inherent randomness, so they were run 5× with the median reported.

  This is a large independent re-evaluation of others' parsers, by the LogPAI group. — [Jiang et al.](https://arxiv.org/html/2308.10828v2)
- **ChatGPT for log parsing.** Achieves promising accuracy with appropriate prompts, especially few-shot. — [Le & Zhang](https://arxiv.org/abs/2306.01590)
- **LILAC (FSE 2024).** ICL with hierarchical demonstration sampling plus an adaptive parsing cache that stores and refines LLM-generated templates. Average template-accuracy F1 is +69.5% over SOTA. LLM query counts drop by orders of magnitude to near the fastest baseline's efficiency. The cache also addresses the LLM's "inherent inconsistent answers." — [Jiang et al.](https://arxiv.org/abs/2310.01796)
- **SOMEF.** Extracts software metadata from READMEs and repositories using supervised classifiers, header analysis, regexes, GitHub/GitLab APIs and package-file parsers. It records the technique and confidence for each extracted field. — [SOMEF docs](https://somef.readthedocs.io/en/dev/); [Mao et al., IEEE BigData 2019](https://doi.org/10.1109/BigData47090.2019.9006447)
- **Scholarly knowledge graph from software packages.** SOMEF plus GitHub API metadata, AST analysis of scripts, and linking to the associated articles, published to the Open Research Knowledge Graph. — [Haris, Stocker, Auer](https://arxiv.org/abs/2212.07921)

### Inferences
- **Logs.** Parse with a deterministic template engine and use an LLM only for cache misses (new templates). Persist templates as versioned artifacts, so the same log line always maps to the same template ID and parameter columns. This is the clearest existing instance of the "LLM-compiles, engine-executes" pattern the toolkit should adopt elsewhere.
- **Code repositories.** Most high-value metadata is already structured: manifests (package.json, pyproject), lockfiles, CI configs, git history, licenses. AST parsing gives exact symbol tables. LLMs are needed only for README semantics such as purpose and usage. Keep per-field technique and confidence, as SOMEF does.

### Gaps
- No published precision/recall for SOMEF found in this pass (the 2019 paper's numbers were not retrieved).
- No benchmark found for LLM-based repository → metadata extraction against a gold CodeMeta set.

---

## 7. Which methods are most effective per source type? (synthesis, plus determinism and cost evidence)

### Takeaway
Effectiveness depends on where the structure lives:
- **In markup or layout** (template HTML, spreadsheets, logs): LLM-synthesized deterministic programs (wrappers, transformation DSLs, templates) are both cheaper and more reproducible than per-record LLM extraction. They match or beat it on quality once candidates are validated and ensembled.
- **In language** (emails, clinical notes, papers, contracts): per-document LLM extraction with typed schemas, verification questions, verbatim-span grounding and human adjudication is the best-performing option. The resulting tables must be frozen as versioned snapshots, because LLM outputs are not reproducible even at "deterministic" settings.
- **Already structured** (XBRL, schema.org, manifests): ingest directly.

### Cited Findings
- **LLMs are not reproducible at "deterministic" settings.** Five LLMs, eight tasks, 10 runs each: accuracy varies up to 15% across runs, best-vs-worst gaps reach 70%, and no model gives consistently identical output strings. — [Atil et al.](https://arxiv.org/abs/2408.04667)
- **Code synthesis vs direct extraction.** Code synthesis is cheap (110× fewer tokens), and with weak-supervision ensembling it beats direct extraction on semi-structured sources (+10.1 F1 average). It loses on free-text email. — [Evaporate](https://arxiv.org/html/2304.09433v3)
- **Generated scrapers.** They pay off after ~19.5 pages per site. They beat direct extraction only with the strongest model tested (GPT-4-Turbo). — [AutoScraper](https://arxiv.org/html/2404.12753v2)
- **Replayable programs.** WebLists' BardeenAgent: 66% vs 31% recall at 3× lower cost per row. — [WebLists](https://arxiv.org/abs/2504.12682)
- **LLM plus template cache.** Removes LLM inconsistency and cost in log parsing. — [LILAC](https://arxiv.org/abs/2310.01796)
- **Self-supervised DSL program synthesis for table relationalization.** Hit@1 0.57 at 0.2 s per table, without examples. — [Auto-Tables](https://arxiv.org/html/2307.14565v2)
- **Verification prompts are what make LLM literature extraction precise.** Without them, ChatExtract precision drops from 90.8% to 42.7%. — [ChatExtract](https://arxiv.org/html/2303.05352v3)
- **Rule-based extraction.** Deterministic with ~80% precision but ~59% recall. — [Battery DB](https://pmc.ncbi.nlm.nih.gov/articles/PMC7411033/)
- **Field specification beats model choice.** — [EviStreams](https://arxiv.org/abs/2609.27418); [Murin](https://arxiv.org/abs/2606.05970)
- **Native image beats converted text for scanned business documents.** For example 87.5% vs 46.5% on receipts. — [Berghaus et al.](https://arxiv.org/html/2509.04469v1)
- **Hybrid deterministic-parse + schema-guided LLM validated by doctors reaches >92% at 300K-document scale.** — [MNE](https://arxiv.org/abs/2611.04685)
- **Re-deriving taxonomy links from text fails (<19%), so structured XBRL should be used where available.** — [FinTagging](https://arxiv.org/html/2505.20650v5)

### Inferences
Recommended per-source method for the toolkit. These are syntheses from the evidence above, not separately measured.

| Source type | Primary method | Determinism | Provenance unit |
|---|---|---|---|
| XLSX/CSV | Native cell parse → table detection (fine-tuned LLM on compressed encoding, or CNN) → DSL relationalization program (Auto-Tables-style), stored and replayed | High once the program is frozen | sheet + cell range |
| Template HTML sites | Read embedded JSON-LD/microdata first; else LLM-induced XPath/CSS wrapper validated on held-out pages (AutoScraper/BardeenAgent/Evaporate-Code+), re-induced on drift | High per snapshot | URL + snapshot hash + XPath |
| One-off HTML | DOM pruning + LLM extraction returning node references (AXE/NEXT-EVAL) | Medium; freeze outputs | XPath |
| Web tables corpora | Table extraction + column-type/entity linking (TURL-style) | Medium | URL + table index |
| Emails/tickets | Header metadata deterministic; body via LLM with verbatim-span constraint + verification | Low → freeze | message-id + char offsets |
| Contracts | Span extraction per clause category (CUAD) + human review | Low–medium | char offsets |
| Invoices/scans | Multimodal LLM on image, or layout model; arithmetic validation | Low → freeze | page + bbox |
| Clinical notes | Deterministic section parser + schema-guided LLM per section with "not documented" option; pinned model; clinician validation | Low → freeze | note-id + section + offsets |
| Financial filings | XBRL facts directly; LLM only for narrative | High (XBRL) | XBRL context/fact id |
| Scientific papers | Filter (heuristic/NER) → LLM extraction with follow-up verification → deterministic unit normalization → frozen table; rule-based ChemDataExtractor where precision matters more than recall | Low → freeze | DOI + sentence offsets / table cell |
| Patents (chemistry) | Domain NER + event extraction (ChEMU-style, ~0.92 end-to-end F1) | Medium | patent id + offsets |
| Audio/meetings | WhisperX ASR (word timestamps, diarization) → text extraction | Low–medium; freeze transcript | time span + speaker |
| Charts | Use source data if embedded; else DePlot/MatCha/MLLM derendering flagged as estimates | Low | figure + bbox |
| Logs | Drain-style parser + LLM for cache misses (LILAC); versioned templates | High | file + line no. + template id |
| Code repos | Manifests/API/AST deterministic; LLM/classifiers for README semantics with per-field technique and confidence (SOMEF) | High (structured parts) | repo + commit + path |

The general rule: put the non-determinism in a build step that produces versioned artifacts (programs, templates, frozen tables with provenance and confidence). Agent retrieval then runs only exact queries over those artifacts.

### Gaps
- No single study compares all extraction paradigms on a common multi-source benchmark with span-level provenance accuracy (whether the cited span actually supports the value). Provenance faithfulness is rarely measured outside AXE/NEXT-EVAL-style XPath grounding.
- Independent replication is scarce. Most numbers here are author-reported, the main exceptions being Loghub-2.0, Khraisha et al., ContractEval, the invoice benchmark and the MIMIC sensitivity audit.
