# Schema Induction, Ontology Learning, Schema Matching, Entity Resolution and Canonicalization with LLMs (Track 05)

Scope: how the target schema of an agent-retrievable data lake is chosen or induced, how heterogeneous extracted records are mapped onto it, and how entities and values are deduplicated and normalized so that exact predicates (SQL, Cypher, key lookups) return the same results every time. Notes are as of Nov 2026. "Author-reported" means numbers from the method's own paper. "Independent" means a third-party benchmark or a comparison by other authors. Classic papers are marked with their year.

## Q1. Schema induction from unstructured corpora (LLM schema discovery, OpenIE-to-schema, ontology learning, table-schema generation, human-in-the-loop)

### Takeaway
The approaches that work best treat schema induction as a separate, cheap step run on a sample. An LLM proposes attributes, entity types or relations from a few documents. Those proposals are then consolidated against a retrieved or closed vocabulary (canonicalization) and frozen as a versioned schema before full-corpus extraction. Fully autonomous induction at web scale (AutoSchemaKG) reports high "semantic alignment" only under soft, embedding-based metrics. Ontology-learning benchmarks show LLMs are good at term typing, mediocre at taxonomy discovery, and poor at non-taxonomic relations. Human review of the induced schema therefore remains the norm in every system aimed at real users.

### Cited Findings
**Table-schema induction for document collections**
- Evaporate (Arora et al., PVLDB 2023) builds a structured view (a table) of a semi-structured document collection in two steps. Schema identification runs on a small sample of k≪n documents, because "attributes are consistent across documents". The LLM extracts candidate attributes per sampled document, ranks them by frequency, and re-ranks the union with an LLM prompt. Only attributes "explicitly mentioned in the document" are kept, "to ensure provenance in schema identification" — [Evaporate](https://arxiv.org/abs/2304.09433)
- Evaporate also measures a cost/quality trade-off. Direct LLM extraction on every document would cost over $110k (gpt-3.5) for a large data lake. Code synthesis is cheap, but its extractions are "up to 14 points worse in Pair F1". Evaporate-Code+ synthesizes many candidate extraction functions and ensembles them with weak supervision. It beats SOTA systems while making a 110× reduction in the number of documents the LLM must process, across 16 real-world settings (author-reported) — [Evaporate](https://arxiv.org/abs/2304.09433)
- Evaporate's schema identification is noisy. Recall@K (K = number of gold attributes) averaged 59.1 across 8 SWDE Movie websites with generic prompts, with per-site scores as low as 14.4. Domain-specific in-context examples raised it to 63.6 (+4.5) — [Evaporate](https://arxiv.org/abs/2304.09433)
- Determinism angle: Evaporate-Code+ produces Python functions. Once synthesized and frozen, they apply deterministically to new documents, and the LLM is only re-invoked for schema identification and function synthesis — [Evaporate](https://arxiv.org/abs/2304.09433)
- ScheMatiQ (2026) starts from a research question and a corpus. It (1) discovers the "observation unit" (the entity each row describes), (2) induces a query-guided schema, and (3) extracts values, "grounding each output" in evidence. A web UI lets experts revise both the schema and the results in an interactive loop. It was evaluated qualitatively with law and computational-biology experts — [ScheMatiQ](https://arxiv.org/abs/2604.09237)
- DocSage (2026) infers "query-specific minimal joinable schemas", extracts text into relational tables with error-aware correction, and then reasons over those tables. It argues that vector-similarity RAG "often omits critical facts" for multi-entity questions — [DocSage](https://arxiv.org/abs/2603.11798)
- Executable Schema Contracts (2026) is the closest published design to a deterministic data-lake ingester:
  - A *closed-world field catalog* lists every observable field with a stable hash ID, type, null rate and example values. The LLM may only reference catalog IDs. A deterministic validator computes FieldValidity = |referenced IDs ∩ catalog| / |referenced IDs| and flags any schema below 1.0 for repair.
  - Identity keys (uniqueness ratio ≥0.95, or ≥0.80 with an ID-like name), foreign keys (value overlap) and cardinalities are computed statistically, without the LLM. The authors justify this because "LLMs remain unreliable even at simple structural and counting tasks". Removing this structural step lowers exact match by 2.1–6.8 points (author-reported).
  — [Executable Schema Contracts](https://arxiv.org/abs/2606.05415)
- In the same system the schema Σ "alone determines what is extracted, how duplicates are resolved, and where cross-source links are created". Deterministic extractors handle schema-mapped fields, and the LLM is used only for sources marked "hybrid". Every raw record becomes a SourceRecord node with DERIVED_FROM edges, so citations are traceable — [Executable Schema Contracts](https://arxiv.org/abs/2606.05415)
- Map&Make (2025) breaks text into atomic propositions, induces a latent schema from them, and then populates tables. While evaluating, the authors found and corrected hallucination errors in the Rotowire gold set. The benchmark noise matters when comparing text-to-table numbers — [Map&Make](https://arxiv.org/abs/2505.23174)
- Auto-Tables (Li, He et al., 2023) found that over 30% of real spreadsheet and web tables are non-relational. Its system synthesizes multi-step Python transformations that "relationalize" tables, without examples, and succeeds on >70% of 244 real test cases (author-reported) — [Auto-Tables](https://arxiv.org/abs/2307.14565)
- SINT-Flow (Korini & Bizer, 2026) integrates many source tables into one global schema with five LLM operators: Table Splitting, Schema Matching, Table Grouping, Attribute Merging and Integrated Schema Output. Denormalized tables are split into entity-specific relations.
  - On the new SINT-Bench (10 tasks, 93 tables) it reaches ≥97% completeness for entity-type detection, 81% for attribute detection and 84% F1 for schema mapping, with GPT-5.2 or Qwen-3.6-27B.
  - Self-consistency (majority over multiple runs) and a review loop each help. The review loop raises mapping F1 by ≥10% (author-reported).
  — [SINT-Flow](https://arxiv.org/abs/2607.24492)

**OpenIE → schema (KG construction) and canonicalization of induced relations**
- EDC (Extract–Define–Canonicalize, Zhang & Soh, EMNLP 2024) runs three stages: (1) open IE with an LLM, (2) an LLM writes a natural-language definition of each extracted relation, and (3) relations are canonicalized either to an existing target schema ("Target Alignment") or to themselves ("Self Canonicalization"). Matching uses embedding similarity (E5-Mistral-7b) followed by LLM verification. A trained "Schema Retriever" pulls relevant schema elements so large schemas need not fit in the prompt — [EDC](https://arxiv.org/abs/2404.03868)
- EDC self-canonicalization (human-evaluated, inter-annotator agreement 0.94; author-reported):
  - WebNLG: EDC 0.956 precision with 200 relation types, vs CESI 0.724 with 280 and the raw open KG at 529 types.
  - REBEL: EDC 0.867 precision with 225 types, vs CESI 0.504.
  - CESI "inappropriately clusters diverse relations" (over-generalization).
  — [EDC](https://arxiv.org/abs/2404.03868)
- EDC target alignment (WebNLG, GPT-3.5 OIE): EDC+R reaches partial F1 0.794. Removing the Schema Retriever drops it to 0.752. On REBEL and Wiki-NRE, reference sets are non-exhaustive and penalize correct extra triples — [EDC](https://arxiv.org/abs/2404.03868)
- CESI (classic, 2018) is the pre-LLM baseline for open-KB canonicalization. It clusters noun phrases and relation phrases over learned KB embeddings plus side information (PPDB, WordNet, entity linking) — [CESI](https://arxiv.org/abs/1902.00172)
- AutoSchemaKG (2025) extracts entity, event and relation triples and "conceptualizes" instances into types with no predefined schema. It built ATLAS from 50M+ documents: 900M+ nodes and 5.9B edges.
  - The headline "92% semantic alignment with human-crafted schemas" is measured with BERTScore-style token-embedding similarity (BS-R/BS-C) against FB15kET/YAGO43kET types and wikiHow event types. It is not exact type agreement.
  - Example: the YAGO43kET BS-C score was 58.86 with LLaMA-3-8B.
  — [AutoSchemaKG](https://arxiv.org/abs/2505.23628)
- KGGen (2025) extracts triples with an LLM and then runs iterative clustering. "For each set of duplicates, the LLM selects a canonical representative." On a full novel this removed 22.4% of entities and 23% of edges. On its own MINE benchmark it scores 66.07% vs GraphRAG 47.80% and OpenIE 29.84% (author-reported; LLM-as-judge with 90.2% agreement to humans) — [KGGen](https://arxiv.org/abs/2502.09956)
- SCOPE/SCION (2026) is a benchmark for corpus-to-schema induction built from 24 IE datasets (15 RE, 9 EE) with normalized gold schema graphs. The reference pipeline SCION limits naming, merging, filtering and fusion to "candidate-linked evidence under strict JSON contracts". It beats Text2Onto-style, LLM-only and extract-then-aggregate baselines (author-reported) — [SCOPE and SCION](https://arxiv.org/abs/2607.21610)
- DIAL-KG (2026) builds KGs incrementally around a Meta-Knowledge Base. A "Schema Evolution" stage induces new schema elements from validated knowledge each cycle, instead of rebuilding the graph — [DIAL-KG](https://arxiv.org/abs/2603.20059)

**Ontology learning with LLMs**
- LLMs4OL (Babaei Giglou et al., ISWC 2023) frames ontology learning as three tasks, evaluated zero-shot across nine LLM families on WordNet, GeoNames and UMLS: term typing, taxonomy discovery, and non-taxonomic relation extraction — [LLMs4OL](https://arxiv.org/abs/2307.16648)
- LLMs4OL 2024 challenge at ISWC (independent, multi-team; 272 submissions from 14 participants):
  - Term typing: best F1 0.9938 on WordNet (BERT plus rules beat GPT-4 at 0.9264), 0.5906 on GeoNames, 0.8249 on UMLS-NCI, and only ~0.27–0.30 on the Gene Ontology subtasks.
  - Taxonomy discovery: best F1 0.6557 on GeoNames and 0.6157 on Schema.org.
  - Non-taxonomic relation extraction: best F1 0.0783 on UMLS.
  - Random Forest models won several few-shot term-typing subtasks, and GPT-4o won the zero-shot ones.
  — [LLMs4OL 2024 Overview](https://arxiv.org/abs/2409.10146)
- OLLM (Lo et al., NeurIPS 2024) fine-tunes an LLM to generate whole taxonomic subgraphs, with a regularizer against high-frequency concepts. On Wikipedia it beats compositions of subtask methods, and it adapts to arXiv with few examples. It also proposes graph-similarity metrics, arguing that literal-match metrics are inadequate — [OLLM](https://arxiv.org/abs/2410.23584)
- SPIRES/OntoGPT (Caufield et al., Bioinformatics 2024) takes a user-defined LinkML schema and recursively prompts the LLM for each class and slot, including nested classes. It then grounds extracted strings to ontology identifiers through deterministic annotators (OAKlib, Gilda, BioPortal, OLS) — [SPIRES](https://arxiv.org/abs/2304.02711)
  - Grounding: for 100 random GO terms, SPIRES returned correct IDs for 98 (GPT-3.5) and 97 (GPT-4-turbo). Direct GPT-3.5 prompting returned only 3 correct IDs ("mass hallucination").
  - BC5CDR chemical–disease relation extraction: F 41.16 (GPT-3.5, chunked) and 43.80 (GPT-4, no chunking), vs 44.98 for a domain-tuned model (author-reported).
  — [SPIRES](https://arxiv.org/abs/2304.02711)
- Schema-to-ontology mapping (RODI benchmark, 2026): one-shot or naive multi-stage LLM prompting performs poorly. A neuro-symbolic decomposition (symbolic constraints narrow the search, the LLM reasons inside each sub-task) with self-generated demonstrations gains ~25 F1 points over prior methods (author-reported) — [Self-Demonstrations for Schema-Ontology Mapping](https://arxiv.org/abs/2609.13776)
- LinkML schema-automator bootstraps a LinkML schema from TSVs, spreadsheets, SQLite or RDF (`generalize-tsv(s)`, with foreign keys auto-inferred across multiple TSVs). It can also annotate the schema with LLMs (class/slot URIs, enum-to-ontology mappings). Its docs warn that generalization "is inherently a heuristic process" and the output is a draft to refine by hand — [LinkML Schema Automator](https://linkml.io/schema-automator/packages/generalizers.html)

### Inferences
- A sample → induce → canonicalize → freeze → extract pipeline is the reproducible pattern:
  - Evaporate's sample-based schema identification;
  - EDC's define-then-canonicalize step;
  - Schema Contracts' closed-world catalog plus deterministic structural profiling;
  - SPIRES's deterministic grounding.
  Every LLM decision then becomes a reviewable, versioned artifact (schema file, mapping table, synonym table), and the per-record path can be deterministic code or constrained extraction.
- Structural facts (keys, FKs, cardinality, types) should come from data profiling, not LLMs (Schema Contracts' ablation). Semantic facts (names, definitions, entity types, relation meaning) are where LLMs add value.
- The weakness LLMs4OL shows on non-taxonomic relations (F1 <0.1) implies that fully automatic relation-schema discovery for graph targets needs human curation. Typing instances into a curated type list is reliable. Inventing relations is not.
- Soft metrics (BERTScore alignment, LLM-as-judge) overstate how usable induced schemas are for exact predicates. A query like `WHERE type = 'Person'` needs exact type IDs, not "semantically similar" ones.

### Gaps
- No found benchmark measures *run-to-run stability* of induced schemas (same corpus, same model, repeated induction → identical schema?). This determinism property is untested in the literature reviewed.
- No head-to-head independent comparison of Evaporate, ScheMatiQ, DocSage, Schema Contracts and SINT-Flow on a common document-collection benchmark. All numbers are author-reported on different datasets.

## Q2. Schema matching and mapping with LLMs (Magneto, ReMatch, Valentine, Jellyfish, Unicorn, FM wrangling, Table-GPT)

### Takeaway
The strongest LLM-era schema matchers are retrieve-then-rerank hybrids:
- **Retrieve:** a cheap embedding, lexical or small-LM step proposes top-k candidate target columns or tables.
- **Rerank:** an LLM reranks or verifies the k candidates.
- **Confirm:** a human confirms, because accuracy is far from perfect on real, wide, domain-specific schemas (e.g., Magneto MRR ≈0.86 but Recall@GT ≈0.42–0.54 on the 700+-attribute GDC standard).

Matching is a one-time, per-source design-time step whose output (a mapping table) is reviewed and frozen. That makes LLM nondeterminism tolerable, provided the mapping, not the LLM call, is what runs at ingestion.

### Cited Findings
- Rahm & Bernstein (classic, 2001) gave the canonical taxonomy of matchers that later work, including LLM work, still uses: schema-level vs instance-level, element- vs structure-level, and language- vs constraint-based — [Rahm & Bernstein 2001](https://doi.org/10.1007/s007780100057)
- Valentine (Koutras et al., ICDE 2021) is an independent benchmark suite of classic matchers (COMA, Cupid, Similarity Flooding, Distribution-based, EmbDI, SemProp, Jaccard-Levenshtein):
  - "There is not a single schema matching method that consistently performs better than others." COMA was best on fabricated pairs, and Distribution-based was best on real ING bank data.
  - A ~70-line Jaccard-Levenshtein baseline "works surprisingly well".
  - Most methods need data-dependent parameter tuning. The reported results used grid search on ground truth, so "in the wild" performance would be lower.
  - The authors recommend presenting matches as ranked candidates with human feedback.
  — [Valentine](https://arxiv.org/abs/2010.07386)
- "Can Foundation Models Wrangle Your Data?" (Narayan et al., PVLDB 2022) cast entity matching, error detection, imputation, schema matching and data transformation as prompts to GPT-3-175B:
  - Schema matching on Synthea: F1 0.5 zero-shot vs 45.2 with k=3 demonstrations (previous SOTA SMAT: 38.5).
  - Entity matching: few-shot (k=10) reached F1 100 on Fodors-Zagats and Beer, but only 63.5 on Amazon-Google (Ditto: 75.58).
  - Zero-shot results were far worse (e.g., Walmart-Amazon 60.6), and results were sensitive to prompt formatting.
  — [FM Wrangle](https://arxiv.org/abs/2205.09911)
- ReMatch (Sheetrit et al., 2024) needs no training and no source data. It turns each target table into a document, retrieves J candidate target tables per source table by embedding, and asks the LLM (GPT-4) to rank target attributes. Results on MIMIC-III→OMOP (author-reported):
  - Acc@1 0.424 with J=1; Acc@5 0.729 with J=2.
  - Skipping retrieval (whole target schema in the prompt) drops Acc@1 to 0.311.
  - Names only, without descriptions, drops Acc@5 to 0.503.
  - Guidance (one confirmed mapping per table) lifts Acc@1 to 0.539.
  - The supervised SMAT baseline trained on 20% of the data got Acc@1 0.077.
  — [ReMatch](https://arxiv.org/abs/2403.01567)
- Magneto (Liu, Freire et al., PVLDB 2025) has two phases:
  - Candidate retrieval with a small LM (MPNet), fine-tuned self-supervised on LLM-generated, syntactically diverse column variants. Columns are serialized as header plus priority-sampled values.
  - LLM reranking with a prompt that scores each candidate pair 0.00–1.00.
  - Benchmarks: the new GDC biomedical benchmark (target standard with 700+ attributes) plus Valentine.
  — [Magneto](https://arxiv.org/abs/2412.08194)
- Magneto results (author-reported):
  - Best configuration (fine-tuned MPNet + LLaMA3.3-70B reranker): MRR 0.860 on GDC. GPT-4o-mini reranker: 0.815–0.846. Zero-shot bipartite (no LLM): MRR 0.731.
  - Recall@GT on GDC stays low, 0.36–0.54 across configurations.
  - Sending the whole schema to the LLM without SLM retrieval was worse than every Magneto variant, and took over 6,000 seconds per table for GPT-4o.
  - Stated limitation: "if the correct match is missing from the top-k, reranking cannot recover it."
  — [Magneto](https://arxiv.org/abs/2412.08194)
- Parciak et al. (2024) is an experimental study of GPT-3.5/GPT-4 on health-domain schemas, using names and descriptions only:
  - Prompt "task scopes" (1-to-1, 1-to-N, N-to-1, N-to-M) matter. All except 1-to-1 beat a string-similarity baseline by up to 0.245 F1, but "no single task scope consistently dominates".
  - Both too little and too much context hurt.
  - Run-to-run F1 standard deviation was <0.1 for 1-to-N and N-to-1, which the authors judge "consistent enough to be used in practice".
  - Retrieved candidates were <10% of the search space, keeping human verification effort low.
  — [Parciak et al.](https://arxiv.org/abs/2407.11852)
- LLMatch (2025) splits matching into schema preparation, table-candidate selection and column alignment. A "Rollup/Drilldown" step groups related columns into concepts and then re-expands them. It introduces the SchemaNet multi-table enterprise benchmark — [LLMatch](https://arxiv.org/abs/2507.10897)
- Schemora (2025) combines metadata enrichment with hybrid vector + lexical retrieval and an LLM. It reports +7.49% HitRate@5 on MIMIC-OMOP over previous best, and the authors note "the critical role of retrieval" — [Schemora](https://arxiv.org/abs/2507.14376)
- Matchmaker (Seedat & van der Schaar, 2024) is a compositional LLM program (candidate generation → refinement → confidence scoring). It self-improves zero-shot with synthetic in-context demonstrations and beats prior ML methods on medical benchmarks (MIMIC-OMOP, Synthea; author-reported) — [Matchmaker](https://arxiv.org/abs/2410.24105)
- ConStruM (Chen, Zhang & Jagadish, 2026) treats context selection as "budgeted evidence packing". It builds a reusable structure and selects the most useful schema context per column, since full metadata "can obscure the relevant evidence even when it fits" in context — [ConStruM](https://arxiv.org/abs/2601.20482)
- Prompt-Matcher (2024) starts from multiple candidate mapping results kept with probabilities. It uses GPT-4 to verify individual correspondences, chosen by a (1−1/e)-approximation algorithm that maximizes uncertainty reduction under a budget — [Prompt-Matcher](https://arxiv.org/abs/2408.14507)
- KcMF (2024) uses pseudo-code task decomposition, "Dataset as Knowledge" / "Example as Knowledge" knowledge sets, and result ensembling to suppress badly formatted outputs. It reports +17.93% average F1 over non-LLM competitors on schema and entity matching (author-reported) — [KcMF](https://arxiv.org/abs/2410.12480)
- Unicorn (Tu, Fan, Tang et al., SIGMOD 2023) is one model (shared encoder, mixture-of-experts layer, binary matcher) for seven matching tasks across 20 datasets, including schema matching, entity matching, column type annotation and entity linking. It supports zero-shot on new tasks but needs supervised pre-training — [Unicorn](https://doi.org/10.1145/3588938); [Unicorn code](https://github.com/ruc-datalab/Unicorn)
- Jellyfish (Zhang et al., 2023/EMNLP 2024) instruction-tunes 7B/8B/13B local models (Mistral-7B, Llama-3-8B, OpenOrca-Platypus2-13B) for data preprocessing tasks, including schema matching and entity matching. The authors report competitiveness with GPT-3.5/4 and generalization to unseen tasks, while running on "a local, single, and low-priced GPU" for data security (author-reported) — [Jellyfish](https://arxiv.org/abs/2312.01678)
- Table-GPT (Li, He et al., 2023) "table-tunes" GPT-3.5/ChatGPT on table tasks synthesized from real tables. It improves on vanilla models across table-understanding tasks, including unseen ones — [Table-GPT](https://arxiv.org/abs/2310.09263)
- Human-in-the-loop tools:
  - BDIViz (IEEE VIS 2025) shows matcher candidates as an interactive heatmap with LLM-assisted validation for biomedical schema matching. Domain experts said even SOTA automated methods "often yield low accuracy" on such schemas — [BDIViz](https://arxiv.org/abs/2507.16117)
  - Harmonia (Santos, Freire et al., 2025) combines LLM reasoning, a UI and a library of harmonization primitives to synthesize *reusable* pipelines that map datasets to a standard (e.g., GDC) — [Harmonia](https://arxiv.org/abs/2502.07132)
- The 2026 survey "Can LLMs Clean Up Your Mess?" sorts LLM data preparation into cleaning (standardization, error processing, imputation), integration (entity matching, schema matching) and enrichment. It lists persistent limitations: scaling cost and "persistent hallucinations even in advanced agents" — [LLM Data Prep Survey](https://arxiv.org/abs/2601.17058)

### Inferences
- The recommended matcher for a data lake has four parts. Each step leaves an auditable artifact (candidate list, scores, accepted mapping), and the accepted mapping is applied deterministically:
  1. A deterministic lexical/embedding retriever (top-k ~5–20), with value sampling for instance evidence.
  2. An LLM reranker that emits calibrated scores in a fixed JSON structure.
  3. A human accept/reject UI for low-confidence or high-impact columns.
  4. A persisted mapping table (source column → target attribute + transform), versioned with the schema.
- Retrieval sets the recall ceiling (Magneto, ReMatch, Schemora all show this). Investing in the retriever and in column serialization (header + representative values + description) pays off more than a bigger reranker.
- For privacy or cost, fine-tuned 7–13B local models (Jellyfish) or a fine-tuned SLM retriever plus open LLM reranker (Magneto with LLaMA3.3-70B, MRR 0.860) are competitive with hosted GPT-4-class models.

### Gaps
- "SMBench" could not be found as an established LLM schema-matching benchmark. The benchmarks in active use are Valentine, MIMIC-OMOP / Synthea-OMOP (OMAP), GDC (Magneto), SchemaNet (LLMatch), SINT-Bench and RODI (schema-to-ontology).
- No independent leaderboard compares Magneto, ReMatch, LLMatch, Matchmaker, Schemora and KcMF on identical splits with identical LLMs. Cross-paper numbers use different metrics (MRR, Recall@GT, Acc@k, HitRate@k, F1) and are not comparable.

## Q3. Entity matching/resolution, canonicalization, value normalization, and entity linking

### Takeaway
Pairwise LLM matchers (zero-shot GPT-4-class) now equal or beat fine-tuned PLM matchers like Ditto on in-distribution benchmarks. They are far more robust on unseen entities. They are also expensive and not bit-reproducible.

The most cost-effective designs:
- block deterministically first;
- resolve with cheap signals (exact keys, Fellegi–Sunter/Splink weights, small models such as AnyMatch);
- send only ambiguous pairs or small candidate sets to an LLM, using batching, select-among-candidates or in-context clustering;
- persist the resulting cluster IDs (golden-record keys).

Values (dates, units, currencies, identifiers) should be normalized by deterministic parsers and reference vocabularies. LLMs may be used to generate or choose the normalizer, not to emit the normalized value.

### Cited Findings
**Pre-LLM foundations**
- Ditto (Li et al., PVLDB 2020) casts entity matching as sequence-pair classification with fine-tuned BERT/RoBERTa. It adds domain-knowledge injection, summarization of long strings, and data augmentation, gaining up to 29% F1 over prior SOTA and matching it with ≤ half the labels — [Ditto](https://arxiv.org/abs/2004.00584)
- ZeroER (Wu et al., SIGMOD 2020) needs no labels. It fits a Gaussian Mixture Model to match and unmatch similarity-vector distributions, with adaptive regularization and transitivity, and reports results comparable to supervised approaches on five benchmarks. It is deterministic given features and seed — [ZeroER](https://arxiv.org/abs/1908.06049)
- Splink (Linacre et al., IJPDS 2022) implements the Fellegi–Sunter probabilistic linkage model (classic, 1969), estimated with Expectation-Maximisation, in SQL across execution backends. It provides blocking, similarity comparisons, explicit match weights and clerical review, and the paper reports ~2 million downloads. It is a deterministic, explainable baseline for person/organization ER — [Splink paper](https://ijpds.org/index.php/ijpds/article/view/1794); [Splink realtime linkage (2026)](https://ijpds.org/index.php/ijpds/article/view/3814)
- Blocking survey (Papadakis et al., ACM CSUR 2020): blocking and filtering are what make ER scale. Semi-structured, heterogeneous data led to *schema-agnostic* blocking plus block processing, which suits records from heterogeneous extractors — [Blocking & Filtering Survey](https://arxiv.org/abs/1905.06167)
- Zeakis et al. (PVLDB 2023) is an independent analysis of 12 pre-trained embedding models across 17 ER datasets for blocking and matching. It covers vectorization overhead and scalability as practical guidance for choosing embeddings for candidate generation — [Pre-trained Embeddings for ER](https://arxiv.org/abs/2304.12329)

**LLM-based entity matching**
- Peeters, Steiner & Bizer (EDBT 2025) ran all LLMs at temperature 0:
  - Best zero-shot prompt per model: GPT-4 reaches F1 89.61 on WDC Products vs Ditto 84.90 (fine-tuned on thousands of pairs). GPT-4 beats the best PLM on 3 of 6 datasets (+2.65 to +4.71 F1) and loses on the others (−0.33 to −4.49).
  - On *unseen* entities, transferred Ditto/RoBERTa drop 22–61 F1, and GPT-4 beats the best transferred PLM by 40–68%.
  - "There is no single best prompt"; prompts must be tuned per model/dataset.
  - Costs on WDC Products range from 0.006¢ per prompt (GPT-mini zero-shot) to ~3¢ (GPT-4 with demonstrations).
  — [Peeters et al.](https://arxiv.org/abs/2310.11244)
- ComEM (Wang et al., COLING 2025) compares three strategies: matching (pairwise yes/no), comparing, and selecting (pick the match among candidates for one record).
  - Selecting yields an average +16.02% F1 over pairwise matching across 8 datasets and 10 LLMs, because it exploits the one-to-one nature of record linkage.
  - The compound framework uses a cheap model to filter and a stronger model to select, gaining up to a further 4% F1 at lower cost.
  - LLMs show position bias in selection.
  — [ComEM](https://arxiv.org/abs/2405.16884)
- BatchER (Fan et al., 2023) batches many questions into one prompt and selects demonstrations by coverage. It finds batch prompting "very cost-effective for ER" compared both with fine-tuned PLMs and with per-pair LLM prompting, and more stable than standard prompting — [BatchER](https://arxiv.org/abs/2312.03987)
- LLM-CER (Fu et al., SIGMOD 2026) does in-context clustering: the LLM clusters small record sets directly, and clusters are merged hierarchically, with hallucination mitigation. Over 9 datasets it reports up to 150% higher accuracy, +10% F-measure, and up to 5× fewer API calls at comparable cost to the cheapest baseline (author-reported) — [LLM-CER](https://arxiv.org/abs/2506.02509)
- BoostER (Li et al., 2024) starts from a probability distribution over possible partitions of an initial clustering. It selects the most uncertainty-reducing pairs for LLM verification, with error-tolerant updates for LLM mistakes — [BoostER](https://arxiv.org/abs/2401.03426)
- AnyMatch (Zhang, Groth, Calixto & Schelter, 2024) is a small LM (GPT-2 scale) fine-tuned for zero-shot transfer. Its average F1 is within 4.4% of MatchGPT on GPT-4, at "3,899 times lower inference cost", and it ranks second-highest overall among 13 baselines on 9 datasets (author-reported) — [AnyMatch](https://arxiv.org/abs/2409.04073)
- KGGen's dedup step (cluster entities and edges, then have the LLM pick a canonical representative) cut entities by 22.4% on a novel — [KGGen](https://arxiv.org/abs/2502.09956)
- Executable Schema Contracts:
  - Types *with* identity keys are deduplicated by exact key grouping (O(n) hashing).
  - Other types fall back to embedding clustering at cosine ≥0.85.
  - Cross-source edges are materialized by hash joins over FK columns.
  — [Executable Schema Contracts](https://arxiv.org/abs/2606.05415)

**Entity linking to reference KBs (Wikidata etc.)**
- ReFinED (Ayoola et al., NAACL 2022 Industry) does mention detection, fine-grained typing and disambiguation in one forward pass. It is >60× faster than competing approaches, +3.7 F1 on average on standard EL datasets, scales to Wikidata (15× more entities than Wikipedia), and handles zero-shot linking — [ReFinED](https://arxiv.org/abs/2207.04108)
- GENRE (De Cao et al., ICLR 2021) generates entity names autoregressively under a prefix-trie constraint, so outputs are always valid KB entity names. Constrained decoding is the general way to make LLM linking outputs valid by construction — [GENRE](https://arxiv.org/abs/2010.00904)
- ChatEL (Ding et al., LREC-COLING 2024) uses a 3-step LLM prompting pipeline for entity linking: candidates come from a retriever, and the LLM disambiguates. It gains >2% average F1 across 10 datasets. Error analysis found many gold labels were wrong — [ChatEL](https://arxiv.org/abs/2402.14858)
- The W3C Reconciliation Service API (v0.2, Final Community Group Report, 10 Apr 2023; not a W3C standard) defines the protocol OpenRefine uses to match local records against a KB such as Wikidata:
  - Queries carry `query`, `type`, `properties`, `limit` and `type_strict`.
  - Candidates return `id`, `name`, `score` and an optional boolean `match`.
  — [Reconciliation API v0.2](https://www.w3.org/community/reports/reconciliation/CG-FINAL-specs-0.2-20230410/)
- SPIRES grounds values through ontology lookup services (OAKlib/Gilda/BioPortal/OLS), not LLM recall: 98/100 correct GO IDs vs 3/100 by direct GPT-3.5 prompting — [SPIRES](https://arxiv.org/abs/2304.02711)

**Value normalization (dates, units, quantities, currencies)**
- CQE (Almasian et al., EMNLP 2023) extracts quantities with dependency parsing and a unit dictionary. It captures value + unit + behavior (rising/falling) + associated concept and outputs normalized, standardized quantities. It outperforms other quantity extractors on a new dataset (author-reported) — [CQE](https://arxiv.org/abs/2305.08853)
- SEED (Chen, Cao, Madden, Kraska et al., 2023) is an "LLM-as-compiler" for data curation. It compiles a task into a hybrid pipeline of LLM-generated code, vector caching, small models trained on LLM labels, and LLM calls as a last resort. It matches SOTA few-shot quality across 9 datasets and 5 curation tasks while greatly reducing LLM calls — [SEED](https://arxiv.org/abs/2310.00749)
- Evaporate's schema-cleaning appendix uses an expensive LLM to decompose complex values into atomic attributes on one example, and a cheaper model to apply it. Atomic-attribute F1 rose from 21.0 to 57.5 on Wiki NBA. Normalization of compound values remains hard — [Evaporate](https://arxiv.org/abs/2304.09433)
- FM Wrangle: GPT-3-175B with k=3 examples reached 65.3% accuracy on StackOverflow data-transformation tasks and 54.0% on Bing-QueryLogs, vs the search-based TDE SOTA at 63.0 and 32.0. Roughly a third or more of LLM-performed value transformations are still wrong — [FM Wrangle](https://arxiv.org/abs/2205.09911)

**Determinism of LLM decisions**
- Atil et al. (2024) tested five LLMs configured to be deterministic (temperature 0, fixed seed), 10 runs each. Accuracy varied by up to 15% across runs, with up to 70% best-to-worst gap; "none of the LLMs consistently delivers repeatable accuracy across all tasks, much less identical output strings" — [Non-Determinism of "Deterministic" LLM Settings](https://arxiv.org/abs/2408.04667)
- Ouyang et al. (2023) found that "setting the temperature to 0 does not guarantee determinism" in ChatGPT code generation — [Non-determinism of ChatGPT in Code Generation](https://arxiv.org/abs/2308.02828)

### Inferences
- For a deterministic data lake, ER output must be materialized: stable entity IDs, a cluster-membership table, and match evidence per pair. Re-running the LLM at query time cannot guarantee identical results (Atil et al.). The LLM belongs in the offline resolution job.
- Practical cascade, ordered by cost and determinism:
  1. Exact identifier keys (ISBN, LEI, DOI, Wikidata QID) via hashing.
  2. Rule- or Splink-based probabilistic matching with explicit thresholds.
  3. Small-model matcher (AnyMatch/Ditto-class).
  4. LLM "select among blocked candidates" (ComEM) or in-context clustering (LLM-CER) only for residual ambiguity.
  5. Human review queue for low-confidence clusters.
- Entity linking to Wikidata or domain ontologies should use a deterministic candidate generator (reconciliation API, label index, ReFinED). The LLM's role is limited to disambiguating among returned IDs, never inventing IDs (SPIRES's 98 vs 3 result). Constrained decoding (GENRE-style) is the alternative when a generative model must emit IDs.
- Values: use deterministic libraries for dates, units and currencies (CQE-style unit dictionaries; ISO-style codes). LLMs are best used per source to write and verify normalization code (SEED, Evaporate-Code+, Auto-Tables), so the code runs reproducibly over all records.

### Gaps
- No peer-reviewed benchmark specific to LLM-based date, unit or currency normalization was found. Evidence is indirect (CQE for quantities; FM-Wrangle transformation accuracy). Standard tools such as UCUM, QUDT, Duckling, pint and ISO 4217 were not separately evaluated here.
- LLM ER papers report F1 on classic two-table benchmarks (Magellan/DeepMatcher, WDC Products). Few report multi-source cluster quality on LLM-extracted (noisy) records, which is the data-lake setting.
- BatchER's exact cost-reduction numbers and BoostER's quantitative results were not extracted beyond their abstracts.

## Q4. Schema standards as LLM extraction targets (LinkML, schema.org, SHACL, JSON Schema, PG-Schema)

### Takeaway
No single standard covers extraction, validation and querying. A pragmatic stack:
- one source-of-truth model in **LinkML**;
- generators from it to **JSON Schema** (the target for constrained or structured LLM output), SQL DDL and Pydantic;
- **SHACL** for RDF graph validation, or **PG-Schema**-style types and keys for property graphs;
- **schema.org** and domain ontologies as vocabulary for class/slot URIs and enums.

JSON Schema is the de facto interface for LLM structured output, but provider subsets are restrictive. Format constraints can also hurt reasoning, so extraction prompts should allow reasoning separate from the constrained record.

### Cited Findings
- LinkML (Moxon et al., 2025) is "an open framework that simplifies the process of authoring, validating, and sharing data". It supports models from flat to "complex, interrelated, and normalized models that utilize polymorphism and compound inheritance", schema imports, and optional ontology alignment. Adoption spans biology and other fields — [LinkML](https://arxiv.org/abs/2511.16935)
- SPIRES/OntoGPT uses LinkML schemas directly as the extraction template. It relies on LinkML's static and dynamic value sets (e.g., "all descendants of class D in ontology O") to constrain grounding, and on LinkML-OWL to emit OWL — [SPIRES](https://arxiv.org/abs/2304.02711)
- OpenAI Structured Outputs guarantees adherence to the supplied JSON Schema, unlike JSON mode, within a supported subset:
  - all fields `required` (optional fields emulated with `null` unions);
  - `additionalProperties: false` on every object;
  - ≤5000 object properties; ≤10 nesting levels; ≤1000 enum values in total;
  - no `allOf`, `not`, `if/then/else`, `dependentRequired`, `dependentSchemas`;
  - root must be an object and not `anyOf`; refusals bypass the schema.
  — [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- JSONSchemaBench (Geng et al., 2025): constrained-decoding frameworks "have standardized around JSON Schema". The benchmark has 10K real-world schemas plus the official JSON Schema Test Suite and evaluates Guidance, Outlines, llama.cpp, XGrammar, OpenAI and Gemini on efficiency, constraint coverage and output quality, documenting uneven coverage of constraint types — [JSONSchemaBench](https://arxiv.org/abs/2501.10868)
- "Let Me Speak Freely?" (Tam et al., 2024) found "a significant decline in LLMs reasoning abilities under format restrictions", with stricter constraints causing greater degradation — [Let Me Speak Freely](https://arxiv.org/abs/2408.02442)
- Text-to-table structured decoding (2025): schema-guided constrained decoding "significantly enhances the validity and alignment of generated tables", especially numeric alignment (Rotowire). It can degrade results on dense text (E2E) or long aggregation (Livesum) — [Structured Decoding for Text-to-Table](https://arxiv.org/abs/2508.15910)
- SHACL (W3C Recommendation, 20 July 2017) validates an RDF data graph against a shapes graph and produces a machine-readable validation report (`sh:conforms` plus results naming focus node, path, value and failed constraint). Core constraints: cardinality (`minCount`/`maxCount`), `datatype`/`class`/`nodeKind`, `pattern`/length, value ranges, property-pair comparisons, logical combinations, `closed`, `in`, `hasValue` — [SHACL](https://www.w3.org/TR/shacl/)
- PG-Schema (Angles et al., SIGMOD 2023) defines property-graph schemas with PG-Types (flexible types, multi-inheritance) and PG-Keys constraints, aimed at GQL's future DDL. Schema support in existing graph systems and in GQL v1 is limited — [PG-Schema](https://arxiv.org/abs/2211.10962)
- Ahmetaj et al. (2025) formalize SHACL, ShEx and PG-Schema in one framework and identify their common and distinctive features, for choosing among graph schema languages — [Common Foundations for SHACL, ShEx, PG-Schema](https://arxiv.org/abs/2502.01295)
- schema.org (Guha, Brickley & Macbeth, CACM 2016) is a vocabulary created in 2011 by Bing, Google and Yahoo (Yandex joined later). In a 10-billion-page sample, 31.3% of pages had schema.org markup. It is the broadest shared vocabulary for generic web entity types — [schema.org CACM](https://cacm.acm.org/magazines/2016/2/197422-schemaorg)
- schema.org is also an ontology-learning testbed: the best LLMs4OL 2024 taxonomy-discovery F1 on Schema.org was only 0.6157. LLMs reconstruct its class hierarchy imperfectly — [LLMs4OL 2024 Overview](https://arxiv.org/abs/2409.10146)

### Inferences
- LLM-facing target = JSON Schema subset generated from LinkML. Keep it flat-ish (≤10 levels), all fields required and nullable, closed objects, enums for controlled vocabularies, and per-field `evidence_span` / offset fields for provenance.
- Persistence-facing targets = SQL DDL or PG-Schema-like graph types with keys, plus SHACL or LinkML validators run *after* extraction. Validators catch what constrained decoding cannot express (patterns, ranges, cross-field rules), since provider subsets drop `pattern`, `minimum` and similar for some models.
- Two-pass extraction (free reasoning, then a constrained record) is supported by the format-restriction evidence and the text-to-table structured-decoding results.

### Gaps
- No head-to-head study was found measuring LLM extraction accuracy when the same target is expressed as LinkML vs JSON Schema vs SHACL vs PG-Schema.
- The JSON Schema 2020-12 specification and Pydantic docs were not separately reviewed. Claims about LinkML generators (JSON Schema/SQL/Pydantic) come from LinkML documentation summaries, not from a measured evaluation.

## Q5. Schema evolution, data migration and versioning

### Takeaway
Evolution should be additive and metadata-only wherever possible:
- use stable column/field IDs (Iceberg);
- record schema modifications as explicit operators (PRISM SMOs) so queries and data can be rewritten;
- extend induced schemas monotonically (Schema Contracts: T′⊇T, R′⊇R, A′(t)⊇A(t)) so earlier queries stay valid;
- version every snapshot so that "same query + same snapshot = same result".

LLM-specific work on schema evolution (DIAL-KG, Schema Contracts, CRAFT) is recent and author-evaluated only.

### Cited Findings
- PRISM (Curino, Moon & Zaniolo, PVLDB 2008, classic) introduced Schema Modification Operators (SMOs): a concise language for schema changes plus impact analysis, automatic query rewriting and data migration. It was validated on Wikipedia's 170+ schema versions — [PRISM (dblp)](https://dblp1.uni-trier.de/rec/journals/pvldb/CurinoMZ08.html)
- Apache Iceberg supports add, drop, rename, widen and reorder (including nested fields) as "metadata changes, so no data files need to be rewritten". Columns are tracked by unique IDs: "When you add a column, it is assigned a new ID so existing data is never used by mistake." Changes are "independent and free of side-effects". Partition and sort-order evolution are also metadata operations — [Iceberg Evolution](https://iceberg.apache.org/docs/latest/evolution/)
- Executable Schema Contracts formalizes "conditional schema augmentation" under a monotonicity invariant so "prior schema elements remain valid". Two modes:
  - Persistent extension (full two-pass discovery when the corpus grows; saved Σ′).
  - Query-scoped extension (one LLM call; an in-memory Σ′ discarded after the query).
  — [Executable Schema Contracts](https://arxiv.org/abs/2606.05415)
- DIAL-KG (2026) runs incremental KG construction with a "Schema Evolution" stage. It induces new schema elements from validated knowledge and applies only the current round's knowledge to the existing KG, avoiding full rebuilds (author-reported SOTA) — [DIAL-KG](https://arxiv.org/abs/2603.20059)
- CRAFT (2026) notes that injecting exhaustive schema documentation into each prompt "complicates schema evolution". It proposes post-training agents on schema-grounded plans instead. A deployment trade-off: post-trained schema knowledge must be retrained when the schema changes — [CRAFT](https://arxiv.org/abs/2607.22642)
- LinkML supports schema imports and is positioned to reduce "the proliferation of single-use data models". It is a natural unit for versioning, and generated artifacts (JSON Schema, DDL) can be regenerated per version — [LinkML](https://arxiv.org/abs/2511.16935)

### Inferences
- Treat the induced schema plus mapping tables plus canonicalization dictionaries (synonym → canonical relation/type; alias → entity ID) as one versioned "contract" release. Each data snapshot records the contract version, which makes results reproducible per snapshot.
- Prefer additive changes (new attributes, new types, new enum values). Renames and splits should go through explicit SMO-style operators that can rewrite stored queries and views. Rely on ID-based column identity (Iceberg) rather than names.
- Re-running LLM induction from scratch on a grown corpus risks schema drift (different names or splits for the same concept). Incremental, monotone extension with canonicalization against the existing schema (EDC target alignment, Schema Contracts) avoids churn.

### Gaps
- No empirical study was found of LLM-proposed schema migrations (e.g., accuracy of LLM-generated SMOs or ALTER scripts with data backfills), nor of drift rates when re-inducing schemas over time.
- The "Compound Schema Registry" (arXiv 2406.11227) surfaced in search but was not reviewed.

## Q6. Most effective method combinations and measured accuracy (synthesis)

### Takeaway
Across induction, matching, ER and linking, the consistently best-performing and most reproducible pattern has four parts:
1. **Deterministic candidate generation:** profiling, closed-world catalogs, lexical/embedding retrieval, blocking, KB lookup.
2. **LLM judgment over a small candidate set:** rerank, select, define/canonicalize, cluster.
3. **Deterministic validation:** schema validators, FieldValidity, SHACL, key constraints.
4. **Materialization of decisions:** mapping tables, canonical dictionaries, entity IDs, generated code, applied by deterministic code at scale and versioned per snapshot.

Measured accuracies are good but not perfect (schema-matching MRR ~0.73–0.86 on hard real schemas; EM F1 ~76–98 depending on dataset). Human review of design-time decisions remains part of every high-accuracy deployment.

### Cited Findings
- Retrieve-then-rerank beats LLM-only:
  - Magneto: whole-schema LLM < all hybrid variants; best MRR 0.860.
  - ReMatch: no-retrieval Acc@1 0.311 vs 0.424 with retrieval.
  - Schemora: hybrid lexical+vector retrieval gives SOTA on MIMIC-OMOP.
  — [Magneto](https://arxiv.org/abs/2412.08194); [ReMatch](https://arxiv.org/abs/2403.01567); [Schemora](https://arxiv.org/abs/2507.14376)
- Define-then-canonicalize beats clustering-only canonicalization: EDC 0.956 vs CESI 0.724 precision on WebNLG, with fewer relation types (200 vs 280) — [EDC](https://arxiv.org/abs/2404.03868)
- Deterministic grounding beats LLM recall for IDs: SPIRES 98/100 vs 3/100 correct GO IDs — [SPIRES](https://arxiv.org/abs/2304.02711)
- Deterministic structure inference helps: removing statistical key/FK inference costs 2.1–6.8 EM points — [Executable Schema Contracts](https://arxiv.org/abs/2606.05415)
- Code generation amortizes the LLM: Evaporate-Code+ uses 110× fewer LLM document passes than direct extraction and is better in quality. SEED similarly replaces most LLM calls with generated code, caches and small models — [Evaporate](https://arxiv.org/abs/2304.09433); [SEED](https://arxiv.org/abs/2310.00749)
- For ER:
  - Selecting among candidates beats pairwise matching (+16.02% F1; ComEM).
  - In-context clustering cuts API calls up to 5× (LLM-CER).
  - Small fine-tuned models get within 4.4% of GPT-4 at 3,899× lower cost (AnyMatch).
  - Zero-shot GPT-4 rivals fine-tuned Ditto and generalizes far better to unseen entities (Peeters et al.).
  — [ComEM](https://arxiv.org/abs/2405.16884); [LLM-CER](https://arxiv.org/abs/2506.02509); [AnyMatch](https://arxiv.org/abs/2409.04073); [Peeters et al.](https://arxiv.org/abs/2310.11244)
- Self-consistency and review loops stabilize LLM schema operators: SINT-Flow's review loop gives ≥10% mapping F1 — [SINT-Flow](https://arxiv.org/abs/2607.24492)
- Independent evidence of a ceiling and a need for humans:
  - Valentine: no matcher dominates; parameters need tuning.
  - LLMs4OL 2024: relation-learning F1 <0.1; GO typing ~0.3.
  - BDIViz/Harmonia build expert-validation UIs because automated biomedical matching accuracy is low.
  — [Valentine](https://arxiv.org/abs/2010.07386); [LLMs4OL 2024 Overview](https://arxiv.org/abs/2409.10146); [BDIViz](https://arxiv.org/abs/2507.16117); [Harmonia](https://arxiv.org/abs/2502.07132)
- LLM outputs are not reproducible at temperature 0 (up to 15% accuracy variation across runs). Determinism must come from persisting decisions, not from sampling settings — [Atil et al.](https://arxiv.org/abs/2408.04667)

### Inferences
Recommended end-to-end recipe for the toolkit (derived from the findings above):
1. **Profile and catalog:** deterministic profiling of all sources (types, null rates, uniqueness, value overlap) produces a closed-world field catalog with stable IDs.
2. **Induce on a sample:**
   - The LLM proposes entity types, attributes and relations from a stratified document sample (Evaporate, Schema Contracts two-pass), restricted to attested fields and spans.
   - Write a definition per element (EDC "Define").
   - Canonicalize against existing vocabularies (schema.org, domain ontologies, prior schema version) via retrieval plus LLM verification.
   - Keep keys, FKs and cardinality statistical.
3. **Freeze as contract:** author the result in LinkML. Generate the JSON Schema subset for extraction, DDL/PG types for storage, and SHACL/LinkML validation. Human review in a BDIViz/ScheMatiQ-style UI. Version it.
4. **Map sources:** retrieve-then-rerank matching (Magneto-style) produces a persisted mapping table, with human acceptance for low-confidence items. Apply mappings and LLM-synthesized transform code (Evaporate-Code+/Auto-Tables/SEED) deterministically.
5. **Extract:** constrained JSON output with evidence spans. Validate deterministically (FieldValidity, SHACL/LinkML). Normalize values with deterministic parsers and unit/currency vocabularies.
6. **Resolve entities:**
   - blocking → exact keys → Splink/small-model scores → LLM select/cluster on residual blocks;
   - link to Wikidata or domain KBs via a reconciliation API or ReFinED with LLM disambiguation over returned IDs;
   - persist cluster IDs and match evidence.
7. **Evolve:** monotone schema extensions, ID-based columns (Iceberg), SMO-style migrations for breaking changes, and the contract version stamped on each snapshot.

Cost/accuracy trade-off: LLM spend sits in steps 2, 4 and 6 and scales with the number of *sources, schema elements and ambiguous pairs*, not with total records. Per-record LLM extraction (step 5) is the dominant cost unless replaced by synthesized code where document formats are regular.

### Gaps
- No single published system has been evaluated end-to-end on this full recipe against a deterministic-retrieval QA benchmark. Executable Schema Contracts (2026) comes closest, but its evaluation is author-reported, on four QA benchmarks, with one LLM.
- No study quantifies how much run-to-run variance remains after decisions are persisted, e.g., with re-extraction of the same document under a frozen schema. Track 05 found no direct measurement.
