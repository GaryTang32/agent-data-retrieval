# Freeze LLM Extractions, Then Query Them Exactly

The most effective way to convert heterogeneous, unstructured data into a database that AI agents can query deterministically is to **run the LLM once, at ingestion, as a non-deterministic compiler, and never at query time**. Parse each source into a provenance-bearing intermediate representation. Extract into a closed, versioned schema, with every value grounded to a source span and checked by deterministic validators. Resolve entities to stable IDs. Then publish the result as an immutable, snapshot-pinned set of typed tables, plus a property graph where relationships matter. Agents query it only through exact predicates: parameterized tools or a semantic layer first, guarded read-only SQL or Cypher second, and a labelled fallback to unstructured retrieval last. Determinism has to come from the data layer because the models cannot supply it. LLMs set to "deterministic" settings vary by **up to 15% in accuracy across runs** ([Atil et al.](https://arxiv.org/abs/2408.04667)). One prompt at temperature 0 produced **80 distinct completions in 1,000 tries** ([Thinking Machines](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)). Reruns of knowledge-graph extraction overlapped by a Jaccard similarity of **only 0.21–0.55** ([ATOM](https://arxiv.org/pdf/2510.22590)). Snapshots, total ordering and provenance, by contrast, are settled database theory. Materializing also wins on accuracy in independent tests. Extracting an attribute and then filtering on it beats asking an LLM to evaluate the filter ([UDA-Bench](https://arxiv.org/abs/2510.27119)). Extraction-then-SQL beats chunk RAG on intersection queries (**50.9 vs 6.0 recall**) and on counting (**51.2 vs 30.0**) ([QO-Bench](https://arxiv.org/abs/2606.04646)). The limits are just as well measured. Independent extraction F1 on hard legal, finance and healthcare documents is only about **0.51–0.66**, relation-level database construction tops out near **72 F1** ([Doc2DB-Bench](https://arxiv.org/abs/2608.08459)), and a typed store cannot answer a question its schema never anticipated. A review loop and a logged fallback are therefore mandatory. Snowflake, Databricks, Google, Microsoft, AWS and the specialist IDP vendors have all converged on the same pattern: parse, classify, extract with confidence, validate with humans in the loop, land in governed tables, and expose verified queries. List prices run from about **$1.50 per 1,000 pages for OCR to $30–70 for schema extraction**. Their accuracy and straight-through-processing (STP) claims are almost entirely vendor-reported. An open-source stack under permissive licences can implement the whole pattern.

*Evidence base.* This report synthesizes 13 research tracks. Their manifests contain 1,115 entries, which reduce to **965 distinct sources** (666 papers and 299 web sources such as documentation, pricing pages and engineering blogs) after de-duplicating by arXiv ID, DOI and URL. A catalog of all sources is in `papers/README.md` and `papers/manifest.csv`. PDFs are kept locally only and can be rebuilt with `scripts/download_papers.py`. Throughout, **independent** means a party that did not build the winning system measured the result. **Author-reported** means the number comes from the method's own paper. **Vendor-reported** and **customer-reported** mark marketing material and vendor-hosted customer stories, which no one has audited. Status is as of November 2026.

## Where the LLM runs decides whether answers can be exact

The literature gives no single taxonomy, but surveys, benchmarks and vision papers agree on one organizing axis: **where the language model sits relative to the query** ([LLM × DATA survey](https://arxiv.org/abs/2505.18458); [UDA-Bench](https://arxiv.org/html/2510.27119v1); [LROBench](https://arxiv.org/abs/2603.02537)). There are four placements:

- **Ingest-time systems** (EVAPORATE, ZenDB, ReDD, Doctopus, TWIX, warehouse batch extraction) fill a schema once and then answer with ordinary SQL.
- **Query-time systems** (LOTUS, Palimpzest, DocETL, UQE, ThalamusDB, inline `AI_FILTER`/`AI.IF`) call a model per tuple or per pair on every query.
- **Plan-time systems** have the LLM write a program or query that is then frozen and executed: synthesized extractors, wrappers, Text-to-SQL, Deep-Research runtimes.
- **Hybrids** persist or compile LLM judgments: OCTOPUS tags, SemReuse views, SemBaker compiled functions, SUQL, TAG.

Determinism falls in a strict order: ingest-time, then plan-time with frozen artifacts, then query-time. The DocETL authors state the core problem directly. Traditional databases give identical answers whatever the physical plan, whereas their system's "output quality and correctness can vary dramatically based on physical operator parameter choices" ([DocETL](https://arxiv.org/abs/2410.12189)). The EPFL "confining nondeterminism" proposal turns this into a design rule. The LLM is "a stochastic compiler that may only edit" a deterministic, versioned dataflow plan, and "the executor never calls the LLM" ([Kim & Ailamaki](https://arxiv.org/abs/2607.10508)).

| Family | Representative systems | How it works | Query-time determinism | Accuracy evidence | Cost profile | Main failure modes |
|---|---|---|---|---|---|---|
| Rules, grammars, native structure | SystemT, ChemDataExtractor, Drain, direct XBRL/JSON-LD reads | Declarative rules or reading already-typed markup | Fully deterministic | Battery-materials DB P 80.0% / R 59.1% (author) ([Huang & Cole](https://pmc.ncbi.nlm.nih.gov/articles/PMC7411033/)); Drain grouping accuracy falls 0.75→0.55 on realistic logs (independent) ([Loghub-2.0](https://arxiv.org/html/2308.10828v2)) | Engineering-heavy, near-zero run cost | Recall caps near 60%; brittle on informal text |
| Specialized non-generative models | TableFormer/TATR/POTATR, GLiNER, layout encoders | Detector or encoder emits spans or grids tied to source tokens | Deterministic forward pass | TATR 0.980 vs Gemini 3.1 Pro 0.924 GriTS on cropped tables (benchmark authors) ([PubTables-v2](https://arxiv.org/html/2512.10888v4)); GLiNER produced zero malformed outputs (independent) ([Chaganti](https://arxiv.org/abs/2610.00007)) | ~$47 per million pages for POTATR (author) ([POTATR](https://arxiv.org/html/2606.09788v2)) | Domain-bound; collapses without a text layer or under skew |
| LLM/VLM extraction, materialized | ZenDB, Doctopus, LangExtract, `ai_extract`, `AI_EXTRACT` | Model fills a schema per document; SQL afterwards | Deterministic over the snapshot; extraction itself is not | F1 ≈0.85 on simple corpora, 0.51–0.66 on hard ones (independent) ([UDA-Bench](https://arxiv.org/abs/2510.27119)); best relation F1 72.33 (independent) ([Doc2DB-Bench](https://arxiv.org/abs/2608.08459)) | One pass per document × attribute, amortized over all queries | Dropped records on long documents, wide-schema collapse, relation errors |
| Synthesized code, wrappers, templates | Evaporate-Code+, AutoScraper, TWIX, LILAC, Auto-Tables, SemBaker | LLM writes extractor code or infers a template once, then code runs over the corpus | Deterministic once frozen | 110× fewer tokens and +10 F1 vs direct extraction (author) ([Evaporate](https://arxiv.org/abs/2304.09433)), yet least accurate in UDA-Bench (independent) | Cheapest: ~3.5K tokens per document per query vs 818K for DocETL on Finance (independent) | Breaks on free text and layout drift |
| Query-time semantic operators | LOTUS, Palimpzest, DocETL, UQE, ThalamusDB, BigQuery/Snowflake AI functions | LLM evaluates predicates inside the plan on every query | Non-deterministic; statistical guarantees relative to an oracle at best | Average quality 0.59–0.73 with >100× cost spread on LIMIT queries (independent) ([SemBench](https://arxiv.org/abs/2511.01716)) | Paid per query | Run-to-run variance, silent NULLs, approximate aggregates |
| Hybrid persist-or-compile | OCTOPUS, SemReuse, SemBaker, SUQL, TAG | Judgments written back as columns or compiled to code; exact SQL plus LLM primitives | Deterministic for persisted judgments | 10–108× fewer model rows, 3 of 8 queries with zero LLM calls (author) ([OCTOPUS](https://arxiv.org/abs/2610.32586)); SUQL 90.3% vs 63.4% (author) ([SUQL](https://arxiv.org/abs/2311.09818)) | Medium, falling with reuse | Inferred reuse rules can be wrong; nondeterminism leaks at the boundary |
| Query-time restructuring | StructRAG, SRAG, Chain-of-Table | LLM builds a table or graph per question, then reasons over it | Non-deterministic (structure rebuilt each time) | SRAG 0.889 vs 0.593 for GPT-4+RAG (author) ([SRAG](https://arxiv.org/abs/2503.01346)) | High per query | Synonym-broken predicates, wrong relations |
| Vector/chunk RAG (baseline) | Dense or hybrid retrieval over chunks | Top-k similarity, then generation | Approximate; ANN adds further variance | Overall recall 25.2 vs 37.9 for IE→SQL (independent) ([QO-Bench](https://arxiv.org/abs/2606.04646)) | Cheap to index | Top-k caps set completeness; cannot count |

### Parsing: small specialized models beat frontier LLMs on single pages at 1/300th of the cost

For born-digital PDFs the most database-ready tables come from a layout detector plus a non-generative structure model that lifts cell text from the PDF's own text layer. Each cell's text is then byte-identical to the source and carries coordinates. On the PubTables-v2 benchmark, a TATR model with direct PDF text reached **0.980 cell-content GriTS on cropped tables, against 0.924 for Gemini 3.1 Pro, 0.895 for Claude Opus 4.6 and 0.878 for GPT-5.4**. The 29M-parameter POTATR reached **0.965 at page level against Gemini's 0.942**. Frontier models led only on full-document, multi-page extraction, by +0.354 GriTS ([PubTables-v2](https://arxiv.org/html/2512.10888v4)). POTATR processes about 52,000 pages per hour on one A10G, at roughly **$47 per million pages against $15,000–$36,680 for the frontier models**. It loses that edge without a text layer: GriTS falls from 0.965 to 0.78–0.88 when OCR text replaces PDF text (author-reported) ([POTATR](https://arxiv.org/html/2606.09788v2)). "Database-ready" also means every cell exactly right, and that bar is stricter than mean scores suggest. TATR's exact-match table accuracy was 0.82 even in-domain ([table-transformer](https://github.com/microsoft/table-transformer)). Label inconsistency alone moved exact-match accuracy between 42% and 81% across datasets ([Smock et al.](https://arxiv.org/abs/2303.00716)).

Compact two-stage VLM parsers are the best general option for scans and photos. They detect layout boxes first, then recognize each element: PaddleOCR-VL (0.9B, Apache-2.0), MinerU2.5 (1.2B) and dots.ocr (3B). Their author-reported OmniDocBench v1.5 table TEDS is 86–91, and they run at 1.6–2.1 pages per second on an A100 ([MinerU2.5](https://arxiv.org/html/2509.22186v2); [PaddleOCR-VL](https://arxiv.org/html/2510.14528v4)). OmniDocBench is maintained by OpenDataLab, which also develops MinerU, and it changed its matching algorithm between versions ([OmniDocBench](https://github.com/opendatalab/OmniDocBench)). Independent, harder suites therefore carry more weight. Under skew, pipeline tools collapse (PP-StructureV3 table TEDS 79→25) while robust VLM parsers hold ([Real5-OmniDocBench](https://arxiv.org/abs/2603.04205)). Generative parsers have failure modes a database cannot tolerate silently:

- **Repetition loops:** Nougat on 1.5% of pages ([Nougat](https://arxiv.org/html/2308.13418v1)).
- **Unparseable output:** 958 parse failures for SmolDocling, plus fused or missing tables ([PubTables-v2](https://arxiv.org/html/2512.10888v4)).
- **Altered digits:** a single-document vendor report found GPT-5.5 "systematically alters financial-table values", while Textract captured tables incompletely but "never fabricates" ([Needl.ai](https://needl.ai/technical-notes/benchmarking-pdf-extraction-tools)).

| Parsing approach | Representative tools | Accuracy evidence | Throughput / cost | Grounding | Determinism | Failure modes |
|---|---|---|---|---|---|---|
| Rule-based PDF table extractors | Tabula, Camelot | TEDS 67.9–73.0 vs TableFormer 93.6 (TableFormer authors) ([TableFormer](https://arxiv.org/pdf/2203.01017)) | Very cheap | Cell coordinates | Deterministic | Low structural accuracy |
| Detector + structure model on text layer | TableFormer, TATR, POTATR, Docling | 0.965 page-level GriTS (author) | ~$47/M pages; Docling 0.6–2.45 pages/s on CPU ([Docling](https://arxiv.org/html/2408.09869v5)) | Per-cell bbox, text-layer spans | Non-autoregressive, deterministic given weights | OCR dependence, domain shift, large-table downsampling |
| Two-stage compact VLM parsers | PaddleOCR-VL, MinerU2.5, dots.ocr | TEDS 86–91 (author; maintainer conflict) | 1.6–2.1 pages/s on A100 | Element boxes | Generative; stochastic unless pinned | Loops, mis-spanned cells |
| End-to-end page-to-Markdown VLMs | Nougat, olmOCR, SmolDocling | olmOCR 2 tables 84.9 on its own benchmark (author) ([olmOCR 2](https://arxiv.org/html/2510.19817v1)) | olmOCR $176/M pages (author) ([olmOCR](https://arxiv.org/abs/2502.18443)) | Weak or none | Sampling by design (temperature escalation) | Loops, lost grounding |
| Frontier multimodal LLMs | Gemini 3.1 Pro, Claude Opus, GPT-5.x | Best multi-page GriTS 0.931 (benchmark authors) | $15k–37k/M pages | No cell grounding | Not bit-reproducible | Value alteration, fused tables |
| Cloud document APIs | Textract, Azure DI/CU, Google Document AI, Bedrock Data Automation | Textract 0.73 cell accuracy on one document (vendor) | $1.50–$70 per 1,000 pages (list) | Polygons, content spans | Model churn on the vendor side | Incomplete tables; caller must merge cross-page tables ([Azure DI](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/layout)) |

Forms and key-value extraction show the same split between in-domain and novel inputs. Fine-tuned layout encoders reach **90–97 F1** on FUNSD and CORD ([LayoutLMv3](https://arxiv.org/html/2204.08387v3)). Their weights are non-commercial, however ([HF](https://huggingface.co/microsoft/layoutlmv3-base)). Zero-shot frontier VLMs score only **40–82 exact-match field F1** on a new 6,133-document benchmark, with digit confusion, values placed in adjacent fields, and values absent from the document ([UNIKIE-Bench](https://arxiv.org/html/2602.07038v2)). The most important single design idea for deterministic lakes comes from Google's LMDX:

1. Feed OCR lines to the model with coordinate tokens.
2. Require every value to cite its segment ID.
3. Programmatically discard any value not found in the cited segment.

LMDX beat LayoutLMv3 on line items by **72.09 vs 24.51 F1** ([LMDX](https://arxiv.org/html/2309.10952v2)). The same verify-against-source wrapper can sit around any extractor and turns hallucinations into explicit nulls.

### Text to typed records: schema-guided LLM extraction works only when decomposed, constrained and grounded

Three extractor families coexist, and none suffices alone.

- **Span-scoring encoders** such as GLiNER emit only spans that exist in the input, run on CPU, and match 7–13B generative IE models on zero-shot NER (60.9 vs 58.0 for GoLLIE, with competitor numbers copied from their papers) ([GLiNER](https://aclanthology.org/2024.naacl-long.300.pdf)). An independent deployability study found GLiNER had zero malformed outputs, while small generative models emitted **up to 27% invalid output on long inputs**. It also found that switching from LLM-written silver labels to human gold labels flipped the paradigm ranking in favour of encoders ([Chaganti](https://arxiv.org/abs/2610.00007)).
- **Instruction- or code-tuned IE models** (GoLLIE, KnowCoder, UniversalNER) give typed outputs from open weights that can be pinned, but they generalize unevenly.
- **Frontier prompting** is the most flexible for nested business schemas. Independent 2023 work found LLMs "consistently" inferior to fine-tuned small models on strict IE ([Ma et al.](https://arxiv.org/abs/2303.08559)). Exact-match scoring also under-credits valid generative outputs ([Wadhwa et al.](https://arxiv.org/abs/2305.05003)).

Reliability collapses as schemas widen and documents lengthen. On an independent benchmark of 35 PDFs and 12,867 fields, frontier models produced valid JSON in only **51% of extractions**, scored **0% valid output on a 369-field SEC 10-K schema**, and enabling provider structured-output modes *lowered* validity to 37% ([ExtractBench, Contextual AI](https://arxiv.org/abs/2602.12247)). A second ExtractBench, built by LlamaIndex (which ranks its own product first), found Gemini 3.5 Flash value F1 of **87.9 on short documents but 27.9 on documents over 50 pages**, because "entire records are dropped rather than misread" ([ExtractBench, LlamaIndex](https://arxiv.org/abs/2607.29677)). The remedies that work all decompose the problem:

- chunk with overlap, run multiple passes, and merge deterministically on canonical keys ([LangExtract](https://github.com/google/langextract));
- split wide schemas into per-object sub-schemas ([SPIRES](https://arxiv.org/abs/2304.02711));
- stage extraction as object → field → value with validation gates ([xmemory](https://arxiv.org/abs/2604.27906)).

Grammar-constrained decoding guarantees syntactic validity at near-zero overhead in modern engines ([XGrammar](https://arxiv.org/abs/2411.15100); [llguidance](https://github.com/guidance-ai/llguidance)). It does not guarantee correctness. Small models move from 78.6–92.9% to 100% schema validity, but instruction-semantic errors remain ([Chavan](https://arxiv.org/abs/2609.23742)). Engines also differ in which JSON Schema features they actually enforce ([JSONSchemaBench](https://arxiv.org/abs/2501.10868), co-authored by Guidance developers). The "format tax" on reasoning comes mostly from format-requesting instructions and from forcing answers before reasoning. Recent closed models show little of it ([The Format Tax](https://arxiv.org/abs/2604.03616)). Schemas should therefore order fields as evidence quote, then optional reasoning, then value.

Grounding is the decisive gate. SafePassage aligns each model-supplied evidence quote to the document with character-level Smith-Waterman and checks entailment with a small NLI model. It cut hallucinations **by up to 85%** on legal IE, and its DeBERTa checker beat a GPT-4.1 grader (F1 0.891 vs 0.827) at about 1/2,000 of the cost ([SafePassage](https://arxiv.org/abs/2510.00276)). In a 919,783-note clinical deployment, rule-based plausibility filters plus semantic grounding **removed 14.59% of LLM-positive extractions** as unsupported ([Mahbub et al.](https://arxiv.org/abs/2604.06028)). Absence needs its own schema value. Two ChatGPT-4o sessions agreed on 94.1% of systematic-review data points, but only on **77.2% when the information was not reported** ([Jensen et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC11706374/)). So every field needs an explicit null reason (not documented, explicitly negative, or ambiguous).

Code synthesis is the most deterministic LLM extraction method and the most underused. Evaporate-Code+ generates many candidate extraction functions from ten sample documents, scores them against LLM output, and ensembles them with weak supervision. It costs about **$39 per 10,000 documents versus $5,157 for direct extraction**, with pair F1 of 66.7 vs 56.6 on semi-structured corpora. It loses on free-text email (86.9 vs 93.8), and without weak supervision a majority vote over the functions does not beat direct extraction (author-reported) ([Evaporate](https://arxiv.org/html/2304.09433v3)).

| Extraction method | Determinism | Accuracy evidence | Cost | Failure modes |
|---|---|---|---|---|
| Rules / grammars | Fully deterministic | Precision ~72–92%, recall ~59–61% in literature databases (author) ([Huang & Cole](https://pmc.ncbi.nlm.nih.gov/articles/PMC7411033/); [Kelly & Cole](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12738733/)) | Build cost only | Low recall |
| Encoders (GLiNER, GLiREL, GLiNER2) | Deterministic forward pass; spans are grounded by construction | Matches 7–13B IE LLMs on zero-shot NER (author); zero malformed output (independent) | CPU-cheap | Weak on nested records, normalization and long-range relations |
| Instruction-/code-tuned IE LLMs | Pinnable open weights | GoLLIE 55.3 vs 42.3 zero-shot avg (author) ([GoLLIE](https://arxiv.org/abs/2310.03668)) | GPU, moderate | Academic label sets; uneven transfer |
| Frontier LLM + constrained decoding + grounding | Non-deterministic; outputs must be frozen | 51% valid JSON on real schemas (independent); hallucinations cut up to 85% with alignment (author) | Highest per document | Dropped records, wide-schema collapse, absence fabrication |
| Synthesized extractor code (Evaporate-Code+) | Deterministic once frozen | +10 F1 vs direct on semi-structured data (author); worst on complex documents (independent) | ~110× fewer tokens | Free text, heterogeneous layouts |
| Template inference (TWIX) | Deterministic | >25% better precision/recall than Textract, Azure DI and GPT-4V; 3,786× cheaper (author) ([TWIX](https://arxiv.org/abs/2501.06659)) | Very low | Non-templated documents |

### Query-time semantic operators trade exactness for coverage

Independent benchmarks show that no query-time system dominates and none is exact.

- **SemBench** ran LOTUS, Palimpzest, ThalamusDB and BigQuery with the same model at temperature 0, 5 repetitions each. Average quality was **0.731, 0.715, 0.592 and 0.677**. Costs differed by more than 100× on LIMIT queries because LOTUS applies LIMIT only after evaluating every row. Variance "mainly comes from randomness in LLM outputs", and BigQuery varied more because its model parameters "are not exposed to users" ([SemBench](https://arxiv.org/abs/2511.01716)).
- **UDA-Bench** (5 domains, more than 10,000 annotation hours) found extracting first and filtering afterwards **more accurate** than direct LLM booleans. Chunk-based systems were cheaper but missed information, and "there is no system supporting end-to-end query optimization" ([UDA-Bench](https://arxiv.org/html/2510.27119v1)).
- **Doc2DB-Bench** asked systems to build normalized multi-table databases. DocETL scored 74.91 entity F1 but only **41.51 relation F1**, and the authors conclude that "maintaining relational consistency and valid entity references remains a critical challenge" ([Doc2DB-Bench](https://arxiv.org/abs/2608.08459)).

The warehouse AI functions add operational traps. BigQuery's default `max_error_ratio` of 1.0 turns failed rows into silent NULLs ([BigQuery](https://docs.cloud.google.com/bigquery/docs/generative-ai-overview)). None of the Snowflake, Databricks or BigQuery overview pages discuss output determinism ([Databricks](https://docs.databricks.com/aws/en/large-language-models/ai-functions); [Snowflake](https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql)). Even evaluation breaks: exact-result execution accuracy recognized as few as 25% of correct AI-operator SQL translations ([Stochastic Shift](https://arxiv.org/abs/2609.21133)). Guarantee-bearing optimizers (LOTUS, BARGAIN, task cascades) bound drift from an oracle LLM, not from ground truth. If the oracle is 0.5–0.7 accurate on long documents, the guarantee bounds distance from a mediocre reference ([BARGAIN](https://arxiv.org/abs/2509.02896); [task cascades](https://arxiv.org/abs/2601.05536)).

The 2026 trend matters more than any single system. The operator community is converging on **persisted LLM judgments**:

- OCTOPUS writes every semantic judgment back as a tag column with provenance ([OCTOPUS](https://arxiv.org/abs/2610.32586)).
- SemReuse stores filter results as audited materialized views ([SemReuse](https://arxiv.org/abs/2610.16035)).
- SemBaker compiles an operator into a deterministic Python function, at 5.4–10.7× lower cost ([SemBaker](https://arxiv.org/abs/2608.06677)).

That is the materialize-first design under another name.

### Schemas, entities and graphs: let profiling and lookups decide structure, and LLMs decide meaning

Across schema induction, matching, entity resolution and linking, the best-performing reproducible pattern has four steps:

1. Generate candidates deterministically (profiling, blocking, lexical or embedding retrieval, KB lookup).
2. Let an LLM judge only within the small candidate set.
3. Validate deterministically.
4. Persist each decision as data (mapping tables, alias maps, cluster IDs) and apply it with code.

The evidence for each step:

- **Structure from statistics, not the LLM.** Executable Schema Contracts compute keys, foreign keys and cardinalities statistically because "LLMs remain unreliable even at simple structural and counting tasks". Removing that step costs 2.1–6.8 exact-match points ([Schema Contracts](https://arxiv.org/abs/2606.05415)).
- **Invented relations need human curation.** In the independent LLMs4OL 2024 challenge the best F1 for non-taxonomic relation discovery was **0.078** ([LLMs4OL 2024](https://arxiv.org/abs/2409.10146)).
- **Matching recall is the ceiling.** Retrieve-then-rerank schema matching reached MRR 0.86, but recall of the true match stayed at **0.36–0.54** on a 700-attribute biomedical standard, and "if the correct match is missing from the top-k, reranking cannot recover it" ([Magneto](https://arxiv.org/abs/2412.08194)).
- **LLMs match well but cost more.** Zero-shot GPT-4 matched entities at 89.61 F1 against 84.90 for a fine-tuned Ditto, and generalized far better to unseen entities ([Peeters et al.](https://arxiv.org/abs/2310.11244)). A GPT-2-scale model came within 4.4% of GPT-4 at **3,899× lower inference cost** ([AnyMatch](https://arxiv.org/abs/2409.04073)).
- **IDs from lookups, never from recall.** Grounding through ontology services returned 98 of 100 correct Gene Ontology IDs, against 3 of 100 from direct GPT-3.5 prompting ([SPIRES](https://arxiv.org/abs/2304.02711)).

Knowledge-graph construction follows the same logic, and closed predicate vocabularies are the dividing line. Microsoft GraphRAG relationships carry only source, target and a free-text description, with no typed predicate ([GraphRAG dataflow](https://github.com/microsoft/graphrag/blob/main/docs/index/default_dataflow.md)). One build produced **966 relation types for 981 edges** ([KGGen](https://arxiv.org/pdf/2502.09956)), so `MATCH (a)-[:ACQUIRED]->(b)` is impossible without another canonicalization pass. Define-then-canonicalize (EDC) reached 0.956 precision with 200 relation types, against 0.724 for clustering-based CESI (author-reported) ([EDC](https://arxiv.org/pdf/2404.03868)). Ontology-constrained extraction reached 65–90% semantic accuracy against 3–10% unconstrained ([OntoMetric](https://arxiv.org/abs/2512.01289)). Entity resolution plus triple reflection removed about 40% of entities and relations and *improved* four Graph-RAG methods ([DEG-RAG](https://arxiv.org/abs/2510.14271)). Coreference before extraction cut duplicate nodes by 45% ([LINK-KG](https://arxiv.org/abs/2510.26486)). Strict exact-match triple F1 is roughly 0.5–0.8 on clean benchmarks and 0.25–0.5 on real domain text ([Text2KGBench](https://arxiv.org/abs/2308.02357); [Belfadel et al.](https://arxiv.org/abs/2609.31663)). Headline 90%+ figures are almost always precision judged by an LLM, without recall ([AutoSchemaKG](https://arxiv.org/abs/2505.23628)).

| Graph builder | Predicate vocabulary | Entity resolution | Provenance | Fit for exact Cypher |
|---|---|---|---|---|
| Microsoft GraphRAG / LightRAG | Untyped (description edges) | Exact title+type match / dedupe union | TextUnit references | Poor without re-canonicalization |
| KGGen | Open, LLM-clustered | Embedding+BM25 candidates, LLM picks canonical | Chunk links | Moderate; over- and under-merging admitted |
| EDC | Closed (target alignment) or self-canonicalized | Definition embedding + LLM verification | Sentence-level | Good once frozen |
| iText2KG / ATOM | Blueprint-guided; temporal 5-tuples | Cosine thresholds 0.8 / 0.7 | Atomic facts with valid/observed time | Good for temporal queries |
| LangChain LLMGraphTransformer / Neo4j Builder | `allowed_nodes`/`allowed_relationships`, `strict_mode` post-filter ([LangChain](https://github.com/langchain-ai/langchain-experimental/blob/main/libs/experimental/langchain_experimental/graph_transformers/llm.py)) | Clean-up after extraction | Document→Chunk lexical graph ([Neo4j](https://neo4j.com/labs/genai-ecosystem/llm-graph-builder/)) | Good with strict schema |
| Executable Schema Contracts | Closed catalog with hash IDs | Exact identity keys; embedding fallback at cosine ≥0.85 | `SourceRecord`/`DERIVED_FROM` per raw record | Strong |
| Graphiti/Zep | Typed edges, predefined Cypher writes | Hybrid candidates + LLM, same-pair edge dedupe | Episode↔edge indices, bitemporal | Strong for evolving facts ([Zep](https://arxiv.org/abs/2501.13956)) |

Real facts carry qualifiers (time, role, quantity), so the store needs statement-level identity: a statement node, an RDF 1.2 reifier, or a row in a statement table ([RDF 1.2](https://www.w3.org/TR/rdf12-concepts/)). Each statement needs valid-time and transaction-time columns. A query "as of build B" then stays exactly reproducible after later corrections. A Wikidata-qualifier study found no clear performance winner among reification, n-ary relations and named graphs. It did find that minting one predicate per statement overwhelmed four of five SPARQL engines ([Hernández et al.](https://ceur-ws.org/Vol-1457/SSWS2015_paper3.pdf)).

## Extract once, query exactly: the evidence, and where it bends

### Materialization wins on accuracy, reproducibility and cost at once

Three independent lines of evidence point the same way.

**Accuracy.** QO-Bench is the cleanest head-to-head. It covers 22,984 news articles, computes gold answers deterministically from typed event tuples, and scores by exact match rather than an LLM judge. Under the same answer model, extraction-to-SQL reached **37.9 overall recall, against 25.2 for RAG, 23.9 for ReAct-RAG and 3.8 for GraphRAG-global**. The gap is concentrated in set operators. Fixed top-k retrieval reached only about a third of gold articles, so set completeness was "unattainable by construction" ([QO-Bench](https://arxiv.org/abs/2606.04646)). Other studies agree:

- On "find all" aggregation, naive RAG reached **0.008 evidence-chunk recall**, and raising top-k did not improve count error ([AGGBench](https://arxiv.org/abs/2602.01355)).
- Over NTSB reports, RAG answered "how many incidents involved substantial damage?" with 10 when the answer was 94. The structured-plan system got 20 of 30 questions right against RAG's 2 (author-reported) ([Aryn](https://arxiv.org/abs/2409.00847)).
- At 128k tokens, long-context models scored 0.14–0.40 on Spider-style compositional questions against 0.74 for a SQL pipeline (independent) ([LOFT](https://arxiv.org/abs/2406.13121)).
- GPT-5, Claude Sonnet 4 and Gemini 2.5 Pro all scored **under 50%** on counting over 128K contexts ([Oolong](https://arxiv.org/abs/2511.02817)).
- Even a long-context oracle given gold evidence scored **3.9 on intersection queries** in QO-Bench. Unlimited context does not substitute for an executor.

**Reproducibility.** Query-time inference cannot be made reliably reproducible on hosted models:

- Accuracy varies up to 15% across "deterministic" runs ([Atil et al.](https://arxiv.org/abs/2408.04667)).
- GPU count, GPU type and batch size moved one reasoning model's accuracy by up to 9% under greedy decoding ([Yuan et al.](https://arxiv.org/abs/2506.09501)).
- OpenAI's seed is best-effort and tied to a changing `system_fingerprint` ([OpenAI Cookbook](https://cookbook.openai.com/examples/reproducible_outputs_with_the_seed_parameter)).
- Batch-invariant kernels fix this for self-hosted models at roughly 1.3–2× cost ([SGLang](https://lmsys.org/blog/2025-09-22-sglang-deterministic/); [Thinking Machines](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)). Yet a formally verified engine found that **vLLM's and SGLang's deterministic modes still produced different logits under some execution variations** ([Vosti](https://arxiv.org/abs/2609.38981)).

Persisting a model's outputs is therefore more robust than relying on bit-reproducible inference.

**Cost.** Ingest-time conversion amortizes across every later query. Query-time operators pay on every query, and agent workloads are heavily redundant. The SemBench scalability study alone spent $9,935.80 on LLM calls ([SemBench](https://arxiv.org/html/2511.01716v2)). One team had spent over $50,000 processing a single dataset before DocETL optimization ([DocETL](https://arxiv.org/abs/2410.12189)). By contrast, 3 of 8 benchmark queries needed **no model call at all** once OCTOPUS tags existed ([OCTOPUS](https://arxiv.org/abs/2610.32586)). The Berkeley "agent-first" position paper describes agentic workloads as high-volume and redundant "speculation" ([Liu et al.](https://arxiv.org/abs/2509.00997)). That favours materialization over per-query inference.

### The recommended approach in one view

The most effective end-to-end approach is a **compile-once, query-many pipeline**. A row in the table is a stage. The last column names the stage's frozen artifact, which is what makes it reproducible.

| Stage | What happens | Deterministic artifact | Key evidence |
|---|---|---|---|
| 1. Register | Content-hash every file; record source, URI, MIME type | `doc_id = sha256(bytes)` | Docling `DocumentOrigin.binary_hash` ([docling-core](https://github.com/docling-project/docling-core/blob/main/docling_core/types/doc/common/reference.py)) |
| 2. Parse | Route by type (born-digital, scan, spreadsheet, HTML, audio) to a parser emitting a lossless intermediate representation with page/bbox/char spans | Versioned IR keyed by doc hash + parser version | PubTables-v2, POTATR, DoclingDocument |
| 3. Classify and locate | Classify pages; extract only relevant pages | Page-class labels | Page retrieval contributed 16.8–24 points in industrial KYC ([Han et al.](https://arxiv.org/abs/2604.26462)) |
| 4. Schema contract | Induce on a sample, canonicalize, human-review, freeze; author in LinkML or Pydantic and generate JSON Schema and DDL | Versioned contract (schema + mappings + synonym and alias tables) | Evaporate sampling; EDC; Schema Contracts |
| 5. Extract | Cheapest adequate method per field: native structure → rules or synthesized code → encoders → constrained LLM with evidence-first fields | Raw responses + parsed records, cached by (doc, schema, prompt, model, code) | Evaporate; GLiNER; ExtractBench |
| 6. Ground and validate | Re-slice each evidence span from the source; NLI check for derived values; type, arithmetic and reference-data rules | Validation results stored as data | SafePassage; LangExtract; Deequ |
| 7. Confidence and review | Cross-call disagreement + conformal threshold; humans see only failing fields | Versioned corrections overriding extractor values | ExtractConf; conformal extraction |
| 8. Resolve | Exact keys → probabilistic or small-model matching → LLM selection among blocked candidates → KB linking | Entity IDs, alias map, match evidence | ComEM; SPIRES; Splink |
| 9. Publish | Commit to a branch, run regression gates, merge, tag an immutable snapshot | Snapshot ID / tag | Iceberg, Delta, lakeFS, DuckLake |
| 10. Serve | Parameterized tools and semantic layer → guarded read-only SQL/Cypher → labelled text fallback | Canonical query text + parameters + snapshot ID + total `ORDER BY` | dbt, Bogliolo, QO-Bench |

### Which approach wins depends on the question

Typed stores win on operator questions and lose on questions their schema never anticipated. The question-type picture is consistent across benchmarks:

| Question type | Chunk / vector RAG | Typed store + SQL/graph executor | Evidence |
|---|---|---|---|
| Point lookup, single-hop fact | Competitive or best | Competitive if the field was extracted | QO-Bench filter recall 53.6 vs 50.6 ([QO-Bench](https://arxiv.org/abs/2606.04646)); RAG wins single-hop ([RAG vs GraphRAG](https://arxiv.org/abs/2502.11371)) |
| Multi-constraint filter | Degrades on exact attributes | Strong | SUQL 90.3 vs 63.4 (author) ([SUQL](https://arxiv.org/abs/2311.09818)); NeuSym-RAG 58.2 vs 9.4 on metadata questions (author) ([NeuSym-RAG](https://arxiv.org/abs/2505.19754)) |
| Count / group-by | Fails above top-k | Strong | 51.2 vs 30.0 (independent); Aryn 94 vs 10 |
| Intersection / "find all" | Near zero | Strong | 50.9 vs 6.0 (independent) |
| Cross-entity comparison | Moderate | Strong | TAG 0.65 vs 0.00 on comparisons (author) ([TAG](https://arxiv.org/abs/2408.14717)) |
| Ordering / superlatives | Mixed | Mixed; depends on extracted dates | RAG 29.8 > IE→SQL 17.8 (independent) |
| Multi-hop relational | Weak | Graph traversal helps; text+graph hybrids best | Oracle text/graph routing 0.452 vs 0.291 Hit@1 (author) ([HybGRAG](https://arxiv.org/abs/2412.16311)) |
| Open-ended, thematic | Good locally | Poor (no schema for it) | GraphRAG was designed for global sense-making ([GraphRAG](https://arxiv.org/abs/2404.16130)) |

### Which approach wins depends on where the source's structure lives

Where structure lives in markup or layout (template HTML, spreadsheets, logs, fixed forms), an LLM-synthesized deterministic program is both cheaper and more reproducible than per-record extraction. Where structure lives in language (email, clinical notes, contracts, papers), per-document LLM extraction with verification wins, and its output must be frozen. Where data is already structured, it should be ingested directly.

| Source type | Most effective primary method | Key evidence (type) | Provenance unit |
|---|---|---|---|
| XLSX/CSV | Native cell parse → region detection → stored relationalization program over a small operator DSL | >30% of real tables are non-relational; Auto-Tables Hit@1 0.570 vs GPT-3.5 0.196 (author) ([Auto-Tables](https://arxiv.org/html/2307.14565v2)); fine-tuned LLM exact-boundary detection F1 0.76–0.79 (author) ([SpreadsheetLLM](https://arxiv.org/html/2407.09025v2)) | Sheet + cell range |
| Template HTML | Read JSON-LD/microdata first; otherwise an LLM-induced XPath/CSS wrapper, validated on held-out pages and re-induced on drift | 71.6% of SWDE tasks fully correct with GPT-4-Turbo; break-even ~19.5 pages per site (author) ([AutoScraper](https://arxiv.org/html/2404.12753v2)); replayable programs 66% vs 31% recall (author) ([WebLists](https://arxiv.org/abs/2504.12682)) | URL + snapshot hash + XPath |
| One-off HTML | DOM pruning + LLM returning node references | 88.1% zero-shot SWDE F1 with grounded XPath (author) ([AXE](https://arxiv.org/abs/2602.01838)) | XPath |
| Born-digital PDF tables/forms | Text layer + layout detector + structure model; frontier model only for multi-page tables | PubTables-v2 (benchmark authors) | Page + bbox + char span |
| Scans, invoices, receipts | Multimodal model on the image (not lossy Markdown) + arithmetic checks | Gemini-2.5-pro 87.5% on receipts from images vs 46.5% via Markdown (independent of vendors) ([Berghaus et al.](https://arxiv.org/html/2509.04469v1)) | Page + bbox |
| Emails, tickets | Header fields as deterministic keys; body via span-constrained LLM + verification | GPT-3.5 fabricated ~36% of erroneous arguments (author) ([MailEx](https://arxiv.org/html/2305.13469v2)) | Message-ID + offsets |
| Contracts | Clause-span extraction + mandatory review | Best supervised model 44% precision at 80% recall ([CUAD](https://arxiv.org/abs/2103.06268)); LLMs at roughly junior-assistant level (independent) ([ContractEval](https://arxiv.org/abs/2508.03080)) | Char offsets |
| Clinical notes | Deterministic section parser + schema-guided LLM per section + clinician validation | >92% accuracy on 300,720 MIMIC-IV summaries (author) ([MNE](https://arxiv.org/abs/2611.04685)); model change reassigns the dominant tag on ~half of notes (independent) ([Murin](https://arxiv.org/abs/2606.05970)) | Note + section + offsets |
| Financial filings | XBRL facts directly; LLM only for narrative | LLM concept linking ≤0.189 accuracy (author) ([FinTagging](https://arxiv.org/html/2505.20650v5)) | XBRL fact ID |
| Scientific literature | Filter → LLM extraction with follow-up verification questions → deterministic unit normalization | 90.8% P / 87.7% R with GPT-4, falling to 42.7% P without follow-ups (author) ([ChatExtract](https://arxiv.org/html/2303.05352v3)); only "moderate" agreement after chance correction (independent) ([Khraisha et al.](https://arxiv.org/abs/2310.17526)) | DOI + sentence offsets |
| Audio, meetings, video | ASR with word timestamps and diarization → text extraction; video as audio + keyframes + OCR | Pipelines beat end-to-end models on entity localization, 74.1 vs 56.3 Frame-F1; WER correlates r ≈ −0.9 with downstream quality (author) ([SLUE Phase-2](https://arxiv.org/html/2212.10525v2)); word timestamps via forced alignment ([WhisperX](https://arxiv.org/abs/2303.00747)) | Time span + speaker |
| Charts | Use embedded source data; otherwise derendering flagged as estimates | 94.2 RMS-F1 on PlotQA but ~78% out of domain (author) ([DePlot](https://arxiv.org/html/2212.10505v2)); systematic y-axis biases in MLLMs ([FairChart2Table](https://arxiv.org/abs/2604.24987)) | Figure + bbox |
| Logs | Template parser + LLM only on cache misses; versioned templates | +69.5% template accuracy with orders-of-magnitude fewer LLM calls (author) ([LILAC](https://arxiv.org/abs/2310.01796)) | File + line + template ID |
| Code repositories | Manifests, APIs and AST deterministically; LLM or classifiers for README semantics | Per-field technique and confidence recorded ([SOMEF](https://somef.readthedocs.io/en/dev/)) | Repo + commit + path |

### When the recommendation changes

The materialize-first default should yield in six situations:

- **Genuinely one-off, exploratory questions over data that will not be revisited.** Query-time operators with cheap proxies are affordable here: embedding proxies gave 329× lower latency and 728× lower cost on a 10M-row filter ([Chung et al.](https://arxiv.org/abs/2603.15970)). ThalamusDB offers deterministic *bounds* through sampling ([ThalamusDB](https://par.nsf.gov/servlets/purl/10577787)). Their judgments should still be logged as candidate columns.
- **Open-ended, thematic questions.** These belong to text retrieval or GraphRAG-style global summaries.
- **Questions outside the schema.** QO-Bench's extractor recall peaked at **75.8%**, and joins scored **0%** where the linking key was populated in only about 4% of records ([QO-Bench](https://arxiv.org/abs/2606.04646)). Coverage is the binding constraint, so a logged fallback and a "promote recurring questions into schema" loop are part of the design, not an afterthought.
- **Multi-page and degraded documents.** Frontier multimodal models justify their 300× premium here, but only as an escalation tier triggered by validation failure or detected cross-page tables.
- **Templated families.** Compiled code (TWIX, Evaporate-Code+, wrappers) replaces per-document LLM calls.
- **Native structure.** XBRL, JSON-LD and manifests make extraction unnecessary.

## Agents should choose queries, not write them

### Free-form text-to-SQL is saturated on clean benchmarks and fragile on enterprise schemas

On academic schemas text-to-SQL is near saturation. The top BIRD test execution accuracy is **83.40 against a human 92.96** ([BIRD](https://bird-bench.github.io/)). On enterprise-shaped tasks it collapses:

- **BEAVER** (real warehouse query logs): state-of-the-art agents with GPT-5.2 reach **10.8%** ([BEAVER](https://arxiv.org/abs/2409.02038)).
- **BIRD-Interact**: GPT-5 completes 8.67% of tasks in conversational mode and 17.00% in agentic mode ([BIRD-Interact](https://arxiv.org/abs/2510.05318)).
- **LiveSQLBench**: the best score is 57.00 ([LiveSQLBench](https://livesqlbench.ai/)).
- **DSABench**: median success for routing plus execution across multiple databases is 6.69–7.98% ([DSABench](https://arxiv.org/abs/2610.14700)).

Benchmark gold labels are themselves unreliable. Expert re-annotation found errors in **52.8% of BIRD Mini-Dev and 62.8% of Spider 2.0-Snow** gold answers. Corrections shifted agent rankings by up to nine places ([Jin et al.](https://arxiv.org/abs/2601.08778)). Generation is also variable from run to run:

- Distinct correct sub-plans across 50 attempts per BIRD problem were "less than 10–20% of the total" ([Liu et al.](https://arxiv.org/html/2509.00997v2)).
- Uber treats **~5% run-to-run variation** in QueryGPT as noise ([Uber QueryGPT](https://www.uber.com/blog/query-gpt/)).
- A pipeline that answered all 220 runs correctly still emitted an average of **11 distinct query strings per question** (vendor) ([Bodo PyDough](https://www.bodo.ai/blog/how-pydough-reached-100-accuracy-on-dbts-semantic-layer-benchmark)).

Determinism therefore has to come from persisting and re-executing an accepted query, never from regenerating it.

Graph query generation trails SQL. Zero-shot Claude 3.5 Sonnet and GPT-4o score **61.6% and 60.2%** execution accuracy on CypherBench, and every model under 10B parameters scores below 20%. The top errors are reversed relation direction and entity-linking mistakes ([CypherBench](https://arxiv.org/abs/2412.18702)). Complex SPARQL tops out near 45% ([Spider4SPARQL](https://arxiv.org/abs/2309.16248)). An ontology layer is unusually powerful in enterprise settings. In the data.world insurance benchmark, GPT-4 scored **16% on raw SQL vs 54% via SPARQL** over an ontology with mappings, and SQL fell to 0% on questions spanning more than five tables (independent) ([Sequeda et al.](https://arxiv.org/abs/2311.07509)). Ontology-based query checks with LLM repair lifted this to 72% ([Allemang & Sequeda](https://arxiv.org/abs/2405.11706)). Fine-tuning on synthetic, execution-verified data closes much of the gap on narrow graphs: execution F1 0.806→0.950 (author) ([KG2Cypher](https://arxiv.org/abs/2606.27742)).

### Semantic layers and parameterized tools convert generation into selection

Semantic layers turn query generation into classification over enumerated metrics, dimensions and filters. A compiler then produces the SQL, so the same selection on the same snapshot gives the same rows.

- **dbt Labs (vendor, 11 questions × 20 runs).** On an unmodeled 3NF insurance schema the semantic layer scored 72.7% against 64.5% for text-to-SQL. After an LLM added three dbt models it scored 98.2% and 100% against 90.0% and 84.1%. More importantly, it "fails by declining", while text-to-SQL "returns plausible but wrong answers" ([dbt Labs](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026)).
- **Independent paired study (100 questions, three frontier models).** A 4 KB markdown "semantic layer" document added **17–23 percentage points**, and the document explained "essentially all of the significant variance". Models within a condition were statistically indistinguishable ([Rumiantsau & Fokeev](https://arxiv.org/abs/2604.25149)).
- **Snowflake (vendor).** It reports "90%+" with its semantic model against 51% for single-prompt GPT-4o on an internal 150-question set ([Snowflake](https://snowflake.com/en/engineering-blog/cortex-analyst-text-to-sql-accuracy-bi)).
- **GROUND.** Enforcing governed metrics, join paths and row-level security left zero measured hallucinations across six categories. Refusing undefined metrics remained fallible ([GROUND](https://arxiv.org/abs/2608.26157)).

Predefined, parameterized tools go one step further. In the one controlled study (four 3B–8B models, 609 cells), a domain tool pack scored **0.939 against 0.666 for raw SQL**. The smallest model rose from 0.583 to 0.929, cutting cost per correct answer about 10× ([Bogliolo](https://arxiv.org/abs/2608.22063)). Grab exposes frequently used SQL as individual APIs that an LLM *selects* rather than writes ([Grab Data-Arks](https://engineering.grab.com/transforming-the-analytics-landscape-with-RAG-powered-LLM)). Google's MCP Toolbox declares parameterized statements in `tools.yaml`, which keeps user input out of raw SQL ([MCP Toolbox](https://github.com/googleapis/mcp-toolbox)). Safety is a further reason. LangChain-style apps were "highly susceptible" to prompt-injection-driven SQL injection across 7 LLMs ([Pedro et al.](https://arxiv.org/abs/2308.01990)). Anthropic's reference Postgres MCP server wrapped queries in a read-only transaction, yet still accepted `COMMIT; DROP SCHEMA public CASCADE;` ([Datadog Security Labs](https://securitylabs.datadoghq.com/articles/mcp-vulnerability-case-study-SQL-injection-in-the-postgresql-mcp-server/)).

Because the converted schema is generated rather than inherited, it can be made LLM-friendly by construction, and schema quality often outweighs model choice:

- **Natural identifiers.** Identifier naturalness correlated with accuracy for every model tested, and obscure names cut schema-linking recall by about 20% ([SNAILS](https://adalabucsd.github.io/papers/2025_SNAILS_SIGMOD.pdf)).
- **Column descriptions.** Synthetic descriptions lifted GPT-4o zero-shot BIRD accuracy from 0.301 to 0.368 ([Wretblad et al.](https://arxiv.org/abs/2408.04691)).
- **Profiled metadata.** Automatic profiling metadata lifted accuracy from 49.8% to 61.2% ([Shkapenyuk et al.](https://arxiv.org/abs/2505.19988)).
- **No opaque codes.** Integer concept keys pushed general methods below 50% on financial schemas ([FLINT](https://arxiv.org/abs/2610.03524)).

| Agent interface | Determinism | Accuracy evidence | Coverage | Characteristic failure |
|---|---|---|---|---|
| Key / entity lookup | Exact | — | Narrow | Missing key |
| Parameterized query tools | Exact for same arguments + snapshot | 0.939 vs 0.666 raw SQL (independent, small models) | Known question shapes only | Tool-selection error; novel questions unanswerable |
| Semantic layer (metric × dimension × filter) | Compiled SQL is deterministic | +17–23 pp (independent); 72.7–100% (vendor) | Modeled metrics only | Declines multi-hop questions (0% on "too many hops") |
| Guarded read-only SQL/Cypher | Non-deterministic generation; deterministic once the accepted query is stored | BIRD 83.4 vs BEAVER 10.8 (leaderboards / independent) | Broad | Plausible-but-wrong answers; weak abstention (0.3–0.5 on ambiguity) ([Saxer et al.](https://arxiv.org/abs/2512.21345)) |
| Text fallback (BM25 + vector) | Approximate | Wins single-hop; fails set operators | Unbounded | Cannot count; ANN variance |

### Snapshot pinning and total ordering are the result-level contract

Exact systems are not automatically deterministic. PostgreSQL warns that `LIMIT` without an `ORDER BY` that imposes a unique order returns "an unpredictable subset" ([PostgreSQL](https://www.postgresql.org/docs/current/queries-limit.html)). Lucene breaks score ties by internal document IDs that vary across index instances ([Lin & Yang](https://arxiv.org/abs/1807.05798)). The result-level contract therefore has three parts:

- store the canonical query text and parameters;
- pin the snapshot (Iceberg `VERSION AS OF`, DuckLake `AT (VERSION => n)` or `SNAPSHOT_VERSION`) ([Iceberg](https://iceberg.apache.org/docs/latest/spark-queries/); [DuckLake](https://ducklake.select/docs/stable/duckdb/usage/time_travel));
- require a total `ORDER BY` with a primary-key tiebreaker.

Re-running then gives byte-identical rows whatever the LLM does. Every result row should project its provenance keys: document ID, document hash, page, character offsets or bbox, extraction run, and snapshot.

### The fallback to unstructured retrieval must be routed, verified and labelled

A hybrid design beats either representation alone in controlled ablations:

- **DualGraph:** symbolic-only 0.273, text-only 0.140, combined up to 0.306 factual correctness ([DualGraph](https://arxiv.org/abs/2605.27164)).
- **NeuSym-RAG:** database + vectorstore 39.6, against 37.3 neural-only and 28.0 symbolic-only ([NeuSym-RAG](https://arxiv.org/abs/2505.19754)).

The best-supported router is simple: send operator queries to the executor, and fall back to text when the executor returns nothing or the schema lacks the field. In DualGraph, router-plus-fallback scored 0.298 against 0.268 for routing alone, while an agentic loop scored 0.240 at **about 7× the tokens**. In a production system with 20,000 query-workflow pairs, pre-retrieval routers could not predict needs that only appear after searching. A cheapest-first cascade that escalates on empty results improved quality by +0.140 and cut latency by 31.8% ([Coverage Illusion](https://arxiv.org/abs/2605.27220)). Searching all modalities at once instead of the right source hurt retrieval ([mmRAG](https://arxiv.org/abs/2505.11180)).

The fallback should sit on the same document and entity IDs as the typed store, and its outputs should be labelled non-deterministic. Its retrieval should also be as reproducible as possible, which means accounting for approximate search:

- **pgvector:** exact search "provides perfect recall". With an HNSW index and default settings, a filter matching 10% of rows returns **about 4 rows on average**, because filtering happens after the index scan ([pgvector](https://github.com/pgvector/pgvector)).
- **FAISS:** HNSW `add` runs "in an unspecified order", so index builds differ ([FAISS](https://github.com/facebookresearch/faiss/wiki/Threads-and-asynchronous-calls)).
- **Elasticsearch:** "scores are not reproducible" across replicas ([Elasticsearch](https://www.elastic.co/guide/en/elasticsearch/reference/current/consistent-scoring.html)).

The resulting retrieval-determinism ladder runs: SQL or key lookup on a pinned snapshot, then inverted-index term match, then BM25 with frozen statistics, then exact kNN over a structurally pre-filtered candidate set, then ANN. Questions that recur in the fallback log should be promoted into the schema as new, versioned attributes.

## Quality gates, versioning and provenance make a snapshot worth trusting

A deterministic query over wrong values is reproducibly wrong. The quality stack therefore matters more than inference determinism. The extractor is best treated as a drifting measurement instrument. The quality stack's job is to gate what enters a snapshot, pin each snapshot to the configuration that produced it, and carry per-value lineage back to the source.

### Layered validation, with deterministic checks first

Deterministic validation has the strongest production evidence. Amazon's Deequ compiles declarative constraints into incremental Spark aggregations ([Deequ](https://www.vldb.org/pvldb/vol11/p1781-schelter.pdf)). Google's TFX Data Validation runs schema checks on more than 700 pipelines; the most frequent anomalies are new columns, out-of-domain values and missing columns, and 53–66% of fired anomalies get fixed ([TFDV](https://mlsys.org/Conferences/2019/doc/2019/167.pdf)). Cross-field arithmetic is the cheapest strong detector of semantic errors in tabular domains:

- A sum-check gate over historical election registers confirmed **933 of 934** testable accepted sums ([TableVision](https://arxiv.org/abs/2610.17448)).
- Fiscal-document pipelines use the hierarchy of totals as multi-level validation ([fiscal documents](https://arxiv.org/abs/2511.10659)).

Grounding checks come next, in two tiers:

- **String alignment** of the value to its cited span is deterministic and catches fabricated values and values copied from few-shot examples ([LangExtract](https://github.com/google/langextract)).
- **Small NLI checkers** handle normalized or derived values. MiniCheck matches GPT-4 on grounding at about 400× lower cost ([MiniCheck](https://arxiv.org/abs/2404.10774)).

LLM-as-judge shows position, verbosity and self-enhancement biases ([Zheng et al.](https://arxiv.org/abs/2306.05685)), and 12 bias types persist in advanced models ([CALM](https://arxiv.org/abs/2410.02736)). It belongs in review triage, not in the gate.

### Confidence routing and human review

Raw LLM confidence is a poor gate for field extraction:

- Token log-probabilities, verbalized confidence and self-consistency "collapse toward all-positive behaviour at practical thresholds" ([ExtractConf](https://arxiv.org/abs/2606.24420)).
- A preregistered audit of entity extraction found verbalized calibration error of **0.53–0.94**. Single-sentence counterfactuals flipped 95.6–100% of high-confidence judgments, and the author concluded that confidence "may set review priorities, never truth" ([Qian](https://arxiv.org/abs/2610.20417)).

Two techniques work better:

- **Cross-call disagreement.** Disagreement between two structurally different extraction calls, fused with OCR and layout signals, gave **99.1% accuracy at 80% coverage** on DocILE (author-reported, single author) ([ExtractConf](https://arxiv.org/abs/2606.24420)). Ricoh's production system scores agreement between Textract and Bedrock extractions and routes fields below 70–85% to review (customer-reported) ([AWS/Ricoh](https://aws.amazon.com/blogs/machine-learning/how-ricoh-built-a-scalable-intelligent-document-processing-solution-on-aws)).
- **Split-conformal thresholds.** These turn any score into a reject rule with a finite-sample guarantee ([Angelopoulos & Bates](https://arxiv.org/abs/2107.07511)). In clinical extraction they reached at least 90% coverage at **9–13% rejection**, even though miscalibration reversed direction between domains (author-reported) ([Shrestha & Kim](https://arxiv.org/abs/2603.00924)).

Humans then review only rejected or failed fields. Reviewing LLM pre-annotations cut labelling time by up to 73.7% in a single-annotator study ([GAIDA](https://arxiv.org/abs/2610.26362)). Corrections should be stored as versioned overrides and reused as gold data.

| Layer | Mechanism | Deterministic? | Relative cost | Main failure mode |
|---|---|---|---|---|
| L0 | Constrained decoding to JSON Schema; keep raw output | Validity yes, values no | ~0 | Valid but wrong |
| L1 | Type, constraint, cross-field arithmetic, FK/uniqueness rules (Pydantic, Deequ, Great Expectations, Pandera) | Yes | ~0 | Catches only what rules encode |
| L2 | Span re-slicing; pinned local NLI checker for derived values | Yes, if pinned | Low | Derived or inferred values |
| L3 | Cross-call or cross-model disagreement + conformal threshold per field type | Threshold fixed per version | ~1–2× extraction cost + calibration labels | Exchangeability breaks under drift |
| L4 | Human review of deferred fields; corrections as versioned overrides | Decisions recorded | Dominant variable cost (~10–20% of fields) | Reviewer fatigue, criteria drift ([EvalGen](https://arxiv.org/abs/2404.12272)) |
| L5 | LLM-as-judge on sampled slices, aligned to human grades | No | Moderate | Bias; not a gate |
| L6 | Branch commit with extractor fingerprint + lineage; merge gated on gold-set negative flips and query-suite exact match; tagged snapshot | Yes | Storage | Snapshot expiry; floating model aliases |

### Versioning: the database must never depend on re-running the model

Re-extraction drifts for three reasons.

- **Silent provider updates.** GPT-4 identified primes at 84% in March 2023 and 51% in June 2023 ([Chen, Zaharia, Zou](https://arxiv.org/abs/2307.09009)).
- **Prompt sensitivity.** Meaning-preserving prompt formatting changes moved few-shot accuracy by up to 76 points ([Sclar et al.](https://arxiv.org/abs/2310.11324)).
- **Unpredictable regressions.** No universal signal predicts which samples regress after a model update ([Sheng & Lu](https://arxiv.org/abs/2608.13607)).

Model lifetimes are short compared with data-retention needs:

- OpenAI promises at least 6 months' notice before retiring generally available models ([OpenAI](https://platform.openai.com/docs/deprecations)), and Anthropic at least 60 days ([Anthropic](https://docs.anthropic.com/en/docs/about-claude/model-deprecations)).
- 42% of model mentions in biomedical LLM papers involved a model retired, or scheduled to retire within two years, with a median of **538 days** from publication to retirement ([Wolfrath et al.](https://arxiv.org/abs/2609.04699)).
- Snowflake decommissioned its Document AI UI and `!PREDICT` about 18 months after general availability ([Snowflake BCR-2156](https://docs.snowflake.com/en/release-notes/bcr-bundles/un-bundled/bcr-2156)).

Every row or snapshot should therefore carry a full extractor fingerprint:

- source content hash;
- parser and OCR version;
- model ID with an exact date or version (never a floating alias);
- decoding parameters;
- prompt and few-shot hashes;
- schema version;
- chunking parameters;
- validation rule-set version.

Keyed on that fingerprint, an LLM-call cache gives **deterministic replay**: an unchanged configuration re-runs with zero model calls. The storage layer supplies snapshots:

- Iceberg uses atomic metadata swaps, time travel by snapshot ID, and tags that protect snapshots from expiry ([Iceberg spec](https://iceberg.apache.org/spec/); [Iceberg maintenance](https://iceberg.apache.org/docs/latest/maintenance/)).
- Delta Lake provides time travel and audit history ([Delta Lake](https://www.vldb.org/pvldb/vol13/p3411-armbrust.pdf)).
- lakeFS and Nessie add Git-like branches and *multi-table* atomic merges ([lakeFS](https://docs.lakefs.io/); [Nessie](https://projectnessie.org/)). This is essential when entity, relation and evidence tables change together.

A new model or prompt runs on a branch and is diffed field by field against main. It merges only if negative flips on the gold set stay below a threshold: the write-audit-publish pattern.

### Provenance: where, why and how

Database theory supplies the vocabulary. **Where-provenance** records which source location a value was copied from: for extracted data, the document span. **Why-provenance** records which source facts justify an output tuple ([Buneman, Khanna, Tan](https://repository.upenn.edu/cis_papers/210)). **How-provenance**, through provenance semirings, survives joins, unions and aggregation, so a SQL answer can carry the exact set of spans that produced it ([Green, Karvounarakis, Tannen](https://web.cs.ucdavis.edu/~green/papers/pods07.pdf)). This pays off in practice: returning provenance polynomials over source-grounded graphs exposed extraction and query errors "even when the final answer is correct" ([GraphRAGProv](https://arxiv.org/abs/2610.37237)). OpenLineage and W3C PROV-O standardize run-level lineage. OpenLineage has dataset version facets that can hold an Iceberg snapshot ID, and `dataQualityAssertions` facets for the validation certificate ([OpenLineage](https://openlineage.io/docs/spec/object-model); [PROV-O](https://www.w3.org/TR/prov-o/)). Model-generated citations cannot be trusted unverified: even the best models lacked complete citation support 50% of the time on ELI5 ([ALCE](https://arxiv.org/abs/2305.14627)). Provenance stored as offsets into a content-hashed document, by contrast, can be checked by code: re-slice the span and compare.

Evaluation should use deterministic metrics so it can gate merges in CI:

- exact-match field F1 after type-aware normalization;
- ANLS* for fuzzy strings ([ANLS*](https://arxiv.org/abs/2402.03848));
- GriTS or TEDS for tables ([GriTS](https://arxiv.org/abs/2203.12555));
- Hungarian-aligned record and graph matching, which is "invariant to relabeling" ([Object Aligner](https://arxiv.org/abs/2607.01972));
- grounding rate;
- selective accuracy at the operating coverage;
- a fixed suite of SQL/Cypher questions whose answers are compared by exact result equality on each snapshot.

Run-to-run agreement metrics such as TARa@N quantify any residual nondeterminism ([Atil et al.](https://arxiv.org/abs/2408.04667)).

## Enterprise platforms and vendors converge on one seven-step pattern

### Hyperscalers and data platforms

Every major platform now splits the problem into a non-deterministic conversion layer and a retrieval layer that is deterministic if built that way. Each one also offers a "verified query" mechanism to pin the NL-to-SQL step.

| Platform | Conversion functions (status, Nov 2026) | Typed output and provenance | Agent query layer and pinning mechanism | Indicative list price | Stated determinism caveats |
|---|---|---|---|---|---|
| Snowflake | `AI_PARSE_DOCUMENT` (OCR, LAYOUT; AGENTIC preview), `AI_EXTRACT` (arctic-extract, fine-tuning GA), `AI_CLASSIFY`; legacy Document AI decommissioned March 2026 ([docs](https://docs.snowflake.com/en/user-guide/snowflake-cortex/ai-documents)) | Strings only (cast downstream); per-field scores GA; no span citations ([AI_EXTRACT](https://docs.snowflake.com/en/sql-reference/functions/ai_extract)) | Semantic views with `AI_VERIFIED_QUERIES`, Cortex Analyst/Agents (no published accuracy) ([release note](https://docs.snowflake.com/en/release-notes/2026/other/2026-04-05-semantic-views-verified-queries)) | LAYOUT ~$6.66/1k pages (vendor blog); worked extraction ≈$0.012/page ([Flexera](https://www.flexera.com/blog/finops/snowflake-ai-extract/)) | AGENTIC "schema conformance is not guaranteed" ([docs](https://docs.snowflake.com/en/user-guide/snowflake-cortex/parse-document)) |
| Databricks | `ai_parse_document` (GA April 2026), `ai_extract` v2.1, `ai_query`, Agent Bricks Information Extraction (Beta) ([docs](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_parse_document)) | Typed JSON schema (256 fields), confidence, **citations to text spans or bboxes** ([ai_extract](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_extract)) | Genie with trusted assets (verified parameterized SQL), read-only ([Genie](https://docs.databricks.com/gcp/en/genie/concepts)) | Parse $0.70–6.30/1k pages; extract $2.10–4.20/1k inputs ([pricing](https://www.databricks.com/product/pricing/ai-functions)) | May change underlying models; the version option pins only the schema |
| Google Cloud | Document AI Custom Extractor and Layout Parser; BigQuery `AI.GENERATE_TABLE` (GA Nov 2025), `AI.PARSE_DOCUMENT` (GA Nov 2, 2026), ObjectRef ([release notes](https://docs.cloud.google.com/bigquery/docs/release-notes)) | Typed `output_schema`; confidence on Custom Extractor; bboxes only on Layout Parser v1.0 | BigQuery data agents with parameterized verified queries; publishing to Gemini Enterprise GA ([docs](https://docs.cloud.google.com/bigquery/docs/conversational-analytics)) | OCR $1.50, Layout $10, Custom Extractor $30/1k pages ([pricing](https://cloud.google.com/document-ai/pricing)) | Jobs succeed with partial row failures; processor versions deprecated on 6–18-month cadence |
| Microsoft | Content Understanding (GA 2025-11-01; agentic preview), Document Intelligence v4.0, Fabric AI Functions ([CU](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/overview)) | Extract/Classify/Generate fields with **confidence and source grounding** | Fabric data agents (read-only NL2SQL/DAX/KQL, tables only, 25×25 cap); Foundry IQ for search ([Fabric](https://learn.microsoft.com/en-us/fabric/data-science/concept-data-agent)) | DI Read $1.50, Layout $10, Custom $30/1k pages; CU invoice ≈$8.4/1k ([Azure prices](https://prices.azure.com/api/retail/prices)) | Agentic retrieval: "precise reconstruction ... isn't guaranteed" ([Learn](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview)) |
| AWS | Bedrock Data Automation blueprints; Textract; open-source GenAI IDP Accelerator with HITL ([BDA](https://docs.aws.amazon.com/bedrock/latest/userguide/bda.html)) | Explicit and inferred fields, normalization, validation, confidence, visual grounding | Bedrock KB structured retrieval; `GenerateQuery` returns SQL for review ([docs](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-build-structured.html)) | BDA custom $0.04/page; Textract Forms+Tables+Queries $70/1k; SQL generation $2/1k queries ([Bedrock](https://aws.amazon.com/bedrock/pricing/)) | 6 document languages; DOCX page mapping lost |
| Oracle | OCI Document Understanding generative key-value extraction (Jan 2026); in-database `UTL_TO_TEXT` ([OCI](https://docs.oracle.com/iaas/releasenotes/document-understanding/generative-key-value-extraction.htm)) | Normalized JSON | Select AI with `showsql`, `explainsql`, `feedback`; SELECT only ([Oracle](https://docs.oracle.com/en/database/oracle/oracle-database/26/selai/use-ai-keyword-enter-prompts.html)) | Not found | Warns generated SQL may return incorrect results |
| SAP | Document AI (formerly Document Information Extraction) embedded in S/4HANA scenarios ([SAP](https://pages.community.sap.com/topics/document-information-extraction)) | Review UI learning from corrections | Within S/4HANA workflows | Not found | "Up to 70 percent" faster (vendor) |
| IBM | watsonx.data integration built on open-source **Docling** and Data Prep Kit ([IBM](https://www.ibm.com/products/watsonx-data-integration/unstructured-data-processing)) | "Structured derivatives", source ACLs carried | watsonx.data | Not found | "40% more accurate than conventional RAG" (internal) ([IBM](https://www.ibm.com/new/announcements/improving-ai-accuracy-with-ai-ready-unstructured-and-structured-data-on-ibm-watsonx-data)) |
| Palantir | Pipeline Builder "Use LLM" node with enforced typed outputs; strict struct coercion fails loudly ([Palantir](https://www.palantir.com/docs/foundry/pipeline-builder/pipeline-builder-llm/)) | Ontology objects and links | Agents create proposals reviewed by operators | Not found | "Skip recomputing rows" cache "requires deterministic upstream steps" |
| Salesforce / ServiceNow | Data Cloud Document AI → DMOs queryable like structured data ([Salesforce](https://www.salesforce.com/blog/?p=125302)); Now Assist Document Intelligence default vs full-automation modes ([ServiceNow](https://www.servicenow.com/docs/r/FwUPJkMbovpxa7P5GwPYsg/BVEpNN1t1Q0ZVx55bYfxzw)) | Workflow fields | Agentforce / workflows | Not found | No metrics published |

Practitioner evidence repeats the core lesson. Xebia's production postmortem on Databricks found that "even at temperature 0, LLM outputs can vary between runs". Without checkpointing, every run reprocessed every document. The fix was separate parse, assemble and extract Delta tables, a prompt-version column and a labelled regression set (independent) ([Xebia](https://xebia.com/de/blog/versteckte-kosten-ki-dokumentenanalyse-produktion-databricks/)). A matched independent RAG test found Databricks `ai_parse_document` about 20% better than Azure Content Understanding at about half the cost, on a small sample ([Factored](https://www.factored.ai/our-pov/databricks-ai-parse-document-rag)). No vendor publishes run-to-run variance for its extraction functions, and none publishes accuracy for its agent query layer.

### Specialist IDP vendors

The specialist market has split. LLM-native API vendors sell parse, classify, split and extract endpoints with JSON-schema output, citations and increasingly confidence. Incumbent platforms sell end-to-end workflows with validation stations and STP accounting.

| Vendor | Approach | Grounding / confidence | List price (per 1,000 pages unless stated) | Claims (all vendor-reported) |
|---|---|---|---|---|
| Reducto | OCR + VLM + rules; "Deep Extract" agentic loop | Bboxes, citations ([pricing](https://reducto.ai/pricing)) | Parse $1–10; Extract $20; Deep Extract $40 | >1B pages processed ([Series B](https://reducto.ai/blog/reducto-series-b-funding)) |
| Extend | Parse/extract/split + evals + review agent | Confidence routing ([Checkr](https://www.extend.ai/resources/checkr-case-study.md)) | Extract $7–50 + parse $5–20 ([pricing](https://www.extend.ai/pricing)) | Brex 99%+ (undefined metric) |
| LandingAI ADE | Vision-first agentic extraction | Per-value bbox, table-cell grounding, confidence ([ADE](https://landing.ai/agentic-document-extraction)) | Quote | DocVQA 99.16% on the validation split, not like-for-like ([LandingAI](https://landing.ai/blog/docvqa-benchmark)) |
| LlamaIndex LlamaParse/LlamaExtract | Tiered parse with auto-routing; schema-guaranteed extract | Citations and confidence, off by default ([options](https://developers.llamaindex.ai/python/cloud/llamaextract/features/options/)) | ~$1.25–1.50 per 1k credits; ~1.2¢/page agentic | Ranks itself first on its own ParseBench and ExtractBench |
| Datalab (Marker/Surya/Chandra) | Hosted convert + extraction; open weights with revenue thresholds | Per-field citations on Fast tier ([pricing](https://www.datalab.to/pricing)) | Convert $0.50–10; extract $6–20 | Ranks itself first on OmniParseBench |
| Mistral OCR 3 | Markdown + HTML tables; schema annotations | Image bboxes | $2 ($1 batch); $3 annotated ([Mistral](https://mistral.ai/news/mistral-ocr-3)) | 74% win rate over OCR 2 (internal) |
| Unstructured | Partitioning and chunking for RAG | Element coordinates | $15 after 10k free ([pricing](https://unstructured.io/pricing)) | Structured extraction "Coming Soon" |
| Rossum (acquired by Coupa, 2026) | "Highlighter" model locates values rather than generating them | Values constrained to document text ([Aurora](https://rossum.ai/blog/rossum-aurora/)) | Not public | "0 hallucinated values" (2024) |
| Hyperscience | Field- or character-level routing to target-accuracy SLAs | Per-field thresholds ([public sector](https://www.hyperscience.ai/solutions/public-sector)) | Not public | "[99.5%]" accuracy shown in brackets with no method ([AWS APN](https://aws.amazon.com/blogs/apn/achieve-hyperautomation-for-insurance-document-processing-with-hyperscience-and-aws)) |
| UiPath IXP | Document understanding + generative validation | HITL validation | ≤1 AI unit/page ([metering](https://docs.uipath.com/document-understanding/automation-cloud/latest/user-guide/metering-charging-logic)) | Gartner MQ Leader 2025–2026 |
| Instabase AI Hub | Digitize → classify → extract → validate blocks | — | Per field: 1–30 units at 100 units/$1 ([pricing](https://docs.instabase.com/policies/pricing-policy)) | Bank STP 40%→>95% |
| Sensible | Deterministic rules (SenseML) + LLM | "Every field traceable" ([Sensible](https://www.sensible.so/)) | Per document | 75M+ documents |
| Daloopa | Verified, source-hyperlinked fundamentals via MCP | Every data point linked to source | — | 94.2% with verified data vs 11–64% ungrounded ([Daloopa](https://daloopa.com/blog/product-updates/financial-data-quality-llm-workflows-mcp)) |

Every vendor-run benchmark puts its author first:

- Datalab's OmniParseBench ranks Datalab first ([Datalab](https://www.datalab.to/benchmarks)).
- LlamaIndex's ParseBench ranks LlamaParse first ([LlamaIndex](https://www.llamaindex.ai/blog/parsebench)).
- Nanonets' leaderboard ranks Nanonets first ([Nanonets](https://benchmarking.nanonets.com/)).

Cross-vendor rankings therefore disagree, and the only trustworthy number is one measured on one's own golden set. The market is consolidating:

- Gartner's first IDP Magic Quadrant (September 2025) evaluated 18 vendors and the second (September 2026) 15, with Hyperscience, Tungsten and UiPath named Leaders both years ([Hyperscience 2026](https://www.01net.it/hyperscience-recognized-as-a-leader-for-the-second-consecutive-year-in-the-gartner-magic-quadrant-for-intelligent-document-processing/)).
- Coupa acquired Rossum ([CFOtech](https://cfotech.news/story/coupa-acquires-rossum-to-widen-ai-document-processing)).
- Tensorlake pivoted away from document AI entirely ([Tensorlake docs](https://docs.tensorlake.ai/llms.txt)).

The parse/extract primitive is commoditizing, while the value moves to "documents → system of record".

### What deployments report

All figures below are vendor- or customer-reported unless marked otherwise, and "accuracy" is rarely defined.

| Organization (vendor/stack) | Documents | Reported outcome | Evidence type |
|---|---|---|---|
| Global investment bank (Instabase) | Custody fax instructions | STP 40%→>95%, 97.56% accuracy ([Instabase](https://www.casestudies.com/company/instabase/case-study/leading-global-investment-bank-customer-case-study)) | Vendor |
| Thermo Fisher (UiPath) | 824k invoices/yr | 53% STP, 82.4% "reading accuracy" ([UiPath](https://www.casestudies.com/company/uipath/case-study/thermo-fisher-scientific-cuts-invoice-processing-time-by-70-for-824000-documents-processed-annually)) | Vendor |
| Canon (UiPath) | 4,500 invoices/month | ~90% STP; prior regex 35–40% accuracy ([UiPath](https://www.casestudies.com/company/uipath/case-study/canon-leverages-ai-for-document-processing-to-save-6000-hours)) | Vendor |
| Eurowag (Rossum) | AP invoices, 60 entities | 70% automation, 45 s median exception review ([Rossum](https://rossum.ai/customer-stories/eurowag/)) | Vendor |
| Lease abstraction (ABBYY + GPT-4 Turbo) | 350+-field leases | 82% accuracy ([ABBYY](https://www.abbyy.com/customer-stories/generative-ai-idp-extracts-data-from-lease-agreements-with-82-accuracy)) | Vendor |
| HomeLight (Extend) | 150+-page real-estate packets | Prototype ~85% → >98%; review switched off after a month with zero corrections ([Extend](https://www.extend.ai/blog/homelight-hits-99-accuracy-and-eliminates-manual-review-with-extend)) | Vendor |
| Autyn (LandingAI) | Mortgage packages | 94–98% field accuracy, every value page- and location-tagged ([LandingAI](https://landing.ai/case-studies/how-autyn-cut-loan-processing-from-2-hours-to-2-minutes-at-98-accuracy)) | Vendor |
| Federal benefits agency (Hyperscience, 2021) | Handwritten claims | >96% accuracy at >99% automation vs ~77% before ([DLT](https://www.dlt.com/sites/default/files/resource-attachments/2021-11/Hyperscience-Speeding-Claims-Processing.pdf)) | Vendor |
| YipitData (Databricks) | Merchant tagging (replaced 500+ regex rules) | 92–95% accuracy; 1M records in ~1 h ([Databricks](https://www.databricks.com/customers/yipitdata/ai)) | Customer |
| Competiscan (AWS IDP Accelerator) | Marketing campaigns | 85% accuracy, production in 8 weeks ([AWS](https://aws.amazon.com/blogs/machine-learning/accelerate-intelligent-document-processing-with-generative-ai-on-aws)) | Customer |
| Ricoh (AWS) | Healthcare IDP | 60–70% lower manual review cost ([AWS](https://aws.amazon.com/blogs/machine-learning/how-ricoh-built-a-scalable-intelligent-document-processing-solution-on-aws)) | Customer |
| Uber TextSense (in-house, GPT-4) | Invoices, 25+ languages | ~90% accuracy; 35% of invoices at 99.5%; fine-tuned open models hallucinated line items ([Uber](https://www.uber.com/blog/advancing-invoice-document-processing-using-genai/)) | Engineering blog |
| Industrial KYC study | 3,000 multilingual scanned pages | Best OCR+VLM pipeline 87.27% field accuracy, +31.9 points over direct PDF-to-VLM ([Han et al.](https://arxiv.org/abs/2604.26462)) | Peer-reviewed industry track |

The engineering write-ups show a deterministic layer after the LLM in every extraction case:

- **Uber** applies business-rule validation with exact match on invoice numbers.
- **Instacart PARSE** treats attribute definitions, prompts and models as versioned configs. It derives confidence from a self-verification prompt and found a cheaper model 70% cheaper on easy attributes but 60% worse on hard ones ([Instacart](https://company.instacart.com/tech-innovation/scaling-catalog-attribute-extraction-with-multi-modal-llms)).
- **Shopify** runs about 40M LLM calls a day on fine-tuned open vision models with taxonomy-constrained outputs, and warns that "a single incorrect edge can create a large cluster of mismatched products" ([Shopify](https://shopify.engineering/leveraging-multimodal-llms)).
- **Grab** tags columns from a curated library with an explicit `<None>` option ([Grab](https://engineering.grab.com/llm-powered-data-classification)).

On the query side, determinism rises as agent freedom shrinks:

- QueryGPT's free text-to-SQL treats ~5% run-to-run variance as noise.
- Uber Finch restricts agents to curated single-table marts with value-alias indexes and compares query *results* against golden queries ([Finch](https://www.uber.com/en-US/blog/unlocking-financial-insights-with-finch/)).
- LinkedIn validates table existence and runs EXPLAIN ([LinkedIn](https://www.linkedin.com/blog/engineering/ai/practical-text-to-sql-for-data-analytics)).
- Grab pre-registers queries as APIs.

### The common implementation pattern

Across vendors the documented pattern has seven steps:

1. Ingest to object storage with an event trigger.
2. Parse into an intermediate table.
3. Classify and route by document type.
4. Extract to a typed schema with confidence and, where available, grounding.
5. Validate with rules, cross-model agreement and thresholds, sending low-confidence fields to human review.
6. Materialize to governed tables (Unity Catalog, Horizon, Dataplex, Lake Formation, Purview).
7. Expose to agents through a semantic layer plus verified or trusted queries ([AWS Guidance](https://docs.aws.amazon.com/solutions/multimodal-data-processing-using-amazon-bedrock-data-automation/); [Snowflake](https://snowflake.com/en/blog/structuring-unstructured-data-cortex-aisql/)).

Determinism comes only from steps 6 and 7. Provenance strength varies: Databricks `ai_extract` v2.1 and Azure Content Understanding return span or region grounding, while Snowflake `AI_EXTRACT` and BigQuery `AI.GENERATE_TABLE` document none. Lock-in sits in two places: proprietary intermediate schemas and silent model churn. IBM's choice of MIT-licensed Docling shows that a neutral open representation can be an enterprise default ([Docling](https://arxiv.org/abs/2408.09869)).

| Operation (per 1,000 pages, list) | Low end | High end |
|---|---|---|
| OCR only | Mistral OCR 3 $1–2; Textract / DI Read / Google OCR $1.50 | — |
| Layout parsing | Databricks $0.70 (simple) | Google Layout Parser / Azure DI Layout $10 |
| Schema extraction via API | Databricks $2.10–4.20 per 1k inputs; Datalab $6 | Reducto Deep Extract $40; BDA $40; Textract Forms+Tables+Queries $70 |
| Self-hosted specialized models | POTATR ~$47 per *million* pages (author) | olmOCR $176 per million (author) |
| Frontier multimodal LLM parsing | — | $15,000–36,680 per million pages (author estimate) |
| Batch-API discount for LLM backfills | 50% off ([Claude](https://platform.claude.com/docs/en/build-with-claude/batch-processing); [OpenAI](https://developers.openai.com/api/docs/guides/batch)) | — |

## A blueprint that makes determinism a testable property

The practical implementation below fuses the research evidence with what the platforms and case studies converged on. Every open-source component named is MIT- or Apache-2.0-licensed. Managed equivalents are listed for teams already committed to a platform.

| Layer | Open-source choice | Managed equivalent | Determinism mechanism | Evidence |
|---|---|---|---|---|
| Registry & ingest | SHA-256 document registry; dlt merge/SCD2 ([dlt](https://dlthub.com/docs/general-usage/incremental-loading)) | S3/EventBridge, OpenFlow, UC volumes | Content-addressed IDs; idempotent merges | Docling `binary_hash` |
| Parse IR | Docling (DoclingDocument with `ProvenanceItem` page/bbox/charspan) ([Docling](https://docling-project.github.io/docling/)); Unstructured for hash-based element IDs ([Unstructured](https://docs.unstructured.io/open-source/concepts/document-elements)); PaddleOCR-VL for scans | `ai_parse_document`, `AI.PARSE_DOCUMENT`, CU, Textract | IR keyed by doc hash + parser version | PubTables-v2; OCR dominates latency ([arXiv 2605.18818](https://arxiv.org/abs/2605.18818)) |
| Schema contract | LinkML or Pydantic → JSON Schema + DDL ([LinkML](https://arxiv.org/abs/2511.16935)); explicit null-reason enums | BDA blueprints, CU analyzers | Versioned contract; monotone, additive evolution with ID-based columns ([Iceberg evolution](https://iceberg.apache.org/docs/latest/evolution/)) | Schema Contracts; EviStreams |
| Extraction | Strict provider structured outputs or Outlines/vLLM; Instructor or Pydantic AI validators; GLiNER2 for entities; Evaporate-style synthesized functions for templated families | `ai_extract`, `AI_EXTRACT`, Custom Extractor | Memoized on (doc IR, schema, prompt, model, params, code version) | ExtractBench; Evaporate |
| Grounding & validation | LangExtract-style char-interval check; MiniCheck/NLI pinned locally; Pandera/Great Expectations rules | CEL rules (Google), BDA validation | Re-slice spans; rule results stored as data | SafePassage; Deequ |
| Confidence & review | Two-call disagreement + conformal threshold; review UI writing versioned overrides | IDP Accelerator review UI, CU confidence | Fixed thresholds per version | ExtractConf; conformal extraction |
| Entity resolution | Exact keys → Splink ([Splink](https://ijpds.org/index.php/ijpds/article/view/1794)) → DocETL `resolve` or LLM selection among blocked candidates; ReFinED/reconciliation API for KB links | — | Persisted cluster IDs, alias maps, `entity_mentions` with spans | ComEM; SPIRES; DEG-RAG |
| Storage & versioning | DuckDB + DuckLake (embedded, time travel) or Postgres (multi-user, RLS); Iceberg + Nessie/lakeFS at lake scale; property graph for relations, with bitemporal statement nodes | Delta + UC, Iceberg + Horizon/Dataplex | Immutable snapshot IDs and tags; write-audit-publish branches | Iceberg; lakeFS; Zep |
| Orchestration & caching | CocoIndex (memoizes on input + code hash, retires stale rows) ([CocoIndex](https://cocoindex.io/docs/programming_guide/function/)) or Dagster assets partitioned by source/batch; batch APIs for backfills | Lakeflow, Step Functions, Streams & Tasks | Rebuild from cache = zero LLM calls | CocoIndex; Prefect caching |
| Agent access | MCP Toolbox `tools.yaml` parameterized statements; dbt semantic layer via dbt-mcp; restricted postgres-mcp or read-only DuckDB MCP as fallback ([postgres-mcp](https://github.com/crystaldba/postgres-mcp)) | Verified queries, trusted assets, `GenerateQuery` | Query text + parameters + snapshot ID + total `ORDER BY` | Bogliolo; dbt; Datadog |
| Fallback retrieval | BM25 (pinned implementation) + exact kNN over pre-filtered candidates, keyed by the same IDs | Cortex Search, Azure AI Search | Labelled approximate; logged for promotion into schema | DualGraph; Coverage Illusion |
| Evaluation gates | promptfoo deterministic asserts in CI ([promptfoo](https://www.promptfoo.dev/docs/configuration/expected-outputs/)); golden documents with expected records + spans; agent question suite scored by result equality | LangSmith/Braintrust dataset versions | Merge blocked on negative flips | Finch; LinkedIn; Hamel Husain ([evals](https://hamel.dev/blog/posts/evals/)) |

The data model should make provenance a column rather than a convention. It needs six kinds of table:

- `documents`: hash, URI, MIME type, source system.
- `doc_ir`: parsed IR keyed by document hash and parser version.
- One typed table per record type, with `record_id = hash(doc_id, schema_version, path)` and a `status` of verified, auto-accepted, review-pending or rejected.
- `evidence`: record, field, document, page, bbox, char start/end, quote.
- `extraction_runs`: model, prompt hash, schema version, code version, cost.
- Canonical entity tables plus mention tables, and relationship tables or statement nodes with valid-time and transaction-time columns.

Agents can then filter on `status = 'verified'`, so an uncertain extraction is a queryable state rather than a hidden error.

Four invariants make determinism testable rather than asserted:

1. Rebuilding the lake from cache over an unchanged snapshot issues zero model calls and yields byte-identical table checksums.
2. Running the agent question suite twice on the same snapshot returns identical result sets.
3. Every answer row's evidence span re-slices from the content-hashed source to the stored quote.
4. A new model or prompt merges only through a branch whose gold-set negative flips stay below threshold.

The build order should follow the risk profile seen in the case studies:

1. Start with one document type, mandatory human review and a golden set built before prompts. Nilenso used 50 expert-vetted documents per type, scoring hallucinations worse than nulls ([Nilenso](https://blog.nilenso.com/blog/2026/05/18/evals-before-prompts-building-an-llm-ocr-for-kyc/)).
2. Measure the "true automation rate", meaning documents processed end to end with errors reliably caught, rather than raw accuracy ([jxnl.co on Extend](https://jxnl.co/writing/2025/09/11/how-extend-achieves-95-document-automation-lessons-from-eli-badgio/)).
3. Remove human review only after sustained zero-correction periods.
4. Add cascades, cheaper or fine-tuned models, and synthesized extractors once labels accumulate.

A rough cost envelope for one million pages, combining the list prices above (an inference, not a measured total):

- **Parsing:** $50–200 self-hosted on specialized models, or $1,500–10,000 via cloud OCR and layout APIs.
- **Schema extraction:** roughly $2,000–70,000 depending on vendor tier, halved for LLM backfills through batch APIs.
- **Human review:** the dominant variable cost, at roughly 10–20% of fields.

Practitioner evidence suggests that reprocessing, not first-pass parsing, is where costs run away, so checkpointed, incremental materialization saves more than choosing the cheapest parser ([Xebia](https://xebia.com/de/blog/versteckte-kosten-ki-dokumentenanalyse-produktion-databricks/)).

## Conclusion

The research moves the "deterministic retrieval" problem out of the model. Two years ago the question was which model extracts best. The evidence now says that model choice explains less variance than the field specification, the schema's readability and the query interface. Typed field definitions shaped extraction quality "far more" than the choice among three frontier model families ([EviStreams](https://arxiv.org/abs/2609.27418)). A 4 KB semantic document explained essentially all significant text-to-SQL variance across frontier models ([Rumiantsau & Fokeev](https://arxiv.org/abs/2604.25149)). Restricting agents to parameterized tools let 3B models match much larger ones ([Bogliolo](https://arxiv.org/abs/2608.22063)). The scarce engineering asset is therefore the versioned contract (schema, mappings, alias tables, golden set and verified-query library), not the extractor, which can be swapped and should be expected to be retired within about two years. Meanwhile the database community's query-time "semantic operator" line and the IDP industry's extract-and-review line are converging from opposite directions on one design: persist each LLM judgment once, with provenance, and maintain it like a materialized view.

What remains unknown is as important as what is settled. No public benchmark yet measures end-to-end query accuracy over a database built by LLM extraction from heterogeneous documents. No study measures field-level churn when the same corpus is re-extracted under successive commercial model versions. No vendor publishes calibration curves or run-to-run variance for its extraction functions. Until those gaps close, every team should treat its own golden set, its fallback logs and its snapshot diffs as the real benchmark. The way to prove the design works is the four invariants above: zero-call rebuilds, identical repeat answers, re-sliceable evidence and gated merges. A team that can pass all four has deterministic retrieval in the sense this report set out to define, whatever models it uses.

*Sources: 965 distinct sources across the 13 track manifests. The full catalog is in `papers/README.md` and `papers/manifest.csv`. PDFs are stored locally only and are rebuilt by `scripts/download_papers.py`.*
