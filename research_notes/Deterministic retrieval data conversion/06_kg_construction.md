# Knowledge graph construction from unstructured text as a route to deterministic, queryable data (Track 06)

Scope: LLM-era pipelines that *build* a knowledge graph (KG) as the target database, how good the stored graph is, and how to make it precise, canonical, provenance-linked and reproducible enough for exact Cypher/SPARQL/SQL lookups. GraphRAG/LightRAG are covered only as graph *builders*, not their retrieval heuristics. "AR" = author-reported result; "3P" = reported by a third party (often a competing method's authors, so not neutral); "IND" = neutral/independent study. Snapshot: November 2026.

---

## 1. Pipelines: how the main LLM KG-construction systems work, and their determinism, accuracy, cost and failure modes

### Takeaway
The field has converged on a multi-stage pattern: chunk, extract (open or schema-guided), canonicalize or resolve entities and relations, optionally verify or judge, then merge. Systems differ mainly in two things: whether the predicate vocabulary is *closed* (a fixed schema or ontology) or *open* (free-text relations clustered afterwards), and how entity resolution is done. Only closed-vocabulary pipelines with typed predicates produce graphs that suit exact queries. GraphRAG and LightRAG produce description-centric graphs that are not typed. None of the published pipelines is run-to-run deterministic; at best they claim "stability."

### Cited Findings

**EDC: Extract-Define-Canonicalize (Zhang & Soh, EMNLP 2024)**
- How it works: (1) open IE extracts free-form triplets. (2) An LLM writes a natural-language definition for each relation it extracted. (3) Canonicalization uses those definitions to map each relation onto a target schema ("Target Alignment") or onto a schema that grows from the data itself ("Self Canonicalization"). A trained Schema Retriever fetches relevant schema elements, so a large schema never has to fit in the prompt. An optional refinement loop (EDC+R) re-prompts with hints. — [EDC, arXiv 2404.03868](https://arxiv.org/abs/2404.03868)
- Canonicalization works by embedding the relation definitions with E5. The LLM then verifies the top-5 retrieved candidates, so a relation can be mapped or rejected. If no schema element fits, the triplet is dropped under Target Alignment, or the schema is extended under Self Canonicalization. — [EDC](https://arxiv.org/abs/2404.03868)
- Accuracy (AR), EDC+R with GPT-4 doing OIE, P/R/F1 under the WebNLG "Exact" criterion:
  - WebNLG: 0.796/0.808/0.800, against REGEN 0.714/0.738/0.723.
  - REBEL: exact F1 0.574, against GenIE 0.364.
  - Wiki-NRE: exact F1 0.709, against GenIE 0.478.
  - With Mistral-7B doing OIE: WebNLG exact F1 0.739, REBEL 0.505, Wiki-NRE 0.658. — [EDC tables 3–5](https://arxiv.org/pdf/2404.03868)
- Removing the schema retriever lowers WebNLG Partial F1 from 0.794 to 0.752 (GPT-3.5). — [EDC Table 1](https://arxiv.org/pdf/2404.03868)
- Self-canonicalization (AR, human-evaluated precision, inter-annotator agreement 0.94):
  - WebNLG: EDC 0.956 precision with 200 relation types, against CESI 0.724 with 280 and the raw open KG 0.982 with 529.
  - REBEL: EDC 0.867 with 225 types, against CESI 0.504 with 307.
  - CESI over-merges, for example collapsing "place of birth," "date of death" and "cause of death" into one relation. — [EDC Table 2](https://arxiv.org/pdf/2404.03868)
- Cost and failure modes: the authors call EDC "a costly framework, involving a large number of LLM calls," at about US$0.009 per example with GPT-3.5-turbo. Reference sets built by distant supervision (REBEL, Wiki-NRE) penalize correct extra triples: EDC extracts about one more triple per sentence than the references contain. — [EDC limitations and §4.2](https://arxiv.org/pdf/2404.03868)

**KGGen and the MINE benchmark (Mo et al., 2025; Stanford)**
- How it works:
  1. Two DSPy-signature LLM calls per chunk: first entities, then subject–predicate–object relations given those entities.
  2. Aggregation: all entities and edges are lower-cased and unioned. This step uses no LLM.
  3. Resolution: S-BERT embeddings are k-means clustered into clusters of 128 items. For each item, the top-16 neighbours are retrieved with fused BM25 and embeddings. The LLM picks exact duplicates and a canonical representative, kept as an alias map.
  - [KGGen, arXiv 2502.09956](https://arxiv.org/abs/2502.09956)
- Accuracy (AR):
  - MINE-1 average: KGGen 66.07%, GraphRAG 47.80%, OpenIE 29.84%.
  - By model: Claude Sonnet 3.5 73%, GPT-4o 66%, Gemini 2.0 Flash 44%.
  - Manual validity check of 100 triples per system: KGGen 98%, GraphRAG 0%, OpenIE 55%.
  - Inconsistency: the method section says Gemini 2.0 Flash is the extraction model, yet that model's MINE-1 score is listed as 44%. — [KGGen §4, §6, Table 1](https://arxiv.org/pdf/2502.09956)
- Cost and scale (AR), 1M-character novel: 5.37M tokens, 551 s, US$0.84. Deduplication removed 22.4% of entities and 23% of edges. GraphRAG took 2,319 s for extraction alone and produced 966 relation types for 981 edges, i.e. almost no relation reuse. — [KGGen Tables 2–4](https://arxiv.org/pdf/2502.09956)
- Failure modes acknowledged by the authors: "over or under de-duplication of entities and relations." — [KGGen §8](https://arxiv.org/pdf/2502.09956)
- 3P comparison on four datasets under soft graph metrics (G-BERTScore, G-BLEU, G-ROUGE): KGGen has high accuracy but the lowest recall. On Re-DocRED its G-BS recall is 0.391, against 0.758 for GraphJudge. — [GraphJudge Table 1, arXiv 2411.17388](https://arxiv.org/pdf/2411.17388)

**iText2KG (Lairgi et al., WISE 2024) and its successor ATOM (EACL Findings 2026)**
- How iText2KG works, as four modules:
  1. A Document Distiller rewrites each document into a user-supplied JSON "blueprint."
  2. Incremental entity extraction matches each new local entity to the global entity set by exact match, then by cosine similarity above a threshold.
  3. The same incremental matching is applied to relations.
  4. A graph integrator writes to Neo4j.
  - [iText2KG, arXiv 2409.03284](https://arxiv.org/abs/2409.03284)
- Thresholds: θE = 0.8 for entities and θR = 0.7 for relations. — [ATOM §4, arXiv 2510.22590](https://arxiv.org/pdf/2510.22590)
- Accuracy (AR):
  - False-discovery rate of unresolved entities on websites: 0 for iText2KG, against 0.31 (OpenAI function calling) and 0.29 (LangChain).
  - Triplet precision: 0.94 when local entities are passed as context, 0.83 with global entities. This is a stated precision/richness trade-off of about 10 points. — [iText2KG Tables 2–4](https://arxiv.org/pdf/2409.03284)
- ATOM:
  - Decomposes text into "atomic facts," extracts 5-tuples (subject, relation, object, t_start, t_end) from each, and merges the atomic temporal KGs in parallel.
  - Uses "dual-time modeling" that separates *observation time* from *validity time*.
  - AR: about 18% higher exhaustivity, about 33% better stability, and over 90% lower latency than baselines.
  - The cost is a roughly 9% drop in factual precision, because decomposition produces "inferred" facts that are not in the gold set. — [ATOM](https://arxiv.org/abs/2510.22590)

**AutoKG: two different systems share the name**
- Chen & Bertozzi (IEEE BigData 2023 workshop): an LLM extracts keywords, and edge weights come from graph Laplace learning. The result is a weighted keyword graph for hybrid retrieval, with no typed relations. — [AutoKG, arXiv 2311.14740](https://arxiv.org/abs/2311.14740)
- Zhu et al. (World Wide Web Journal): evaluated GPT-4 across eight datasets and concluded that LLMs "are more suited as inference assistants rather than few-shot information extractors." They propose a separate multi-agent AutoKG. — [Zhu et al., arXiv 2305.13168](https://arxiv.org/abs/2305.13168)

**Graphusion (Yang et al., 2024/WWW'25 workshop)**
- How it works: zero-shot extraction is followed by a *global* fusion module that merges entities, resolves conflicts and discovers new triplets across documents.
- Evidence (AR): human ratings of 2.92/3 for entity extraction and 2.37/3 for relations. Link prediction is up to 10% better than supervised baselines on the authors' TutorQA benchmark. No triple-level precision/recall against a gold KG is reported. — [Graphusion, arXiv 2407.10794](https://arxiv.org/abs/2407.10794); [Graphusion WWW'25 version, arXiv 2410.17600](https://arxiv.org/abs/2410.17600)

**SAC-KG (Chen et al., ACL 2024)**
- How it works: for each entity, a Generator produces relations and tails, using retrieved domain sentences plus DBpedia template triples. A rule-based, parameter-free Verifier checks the output against RuleHub rules. A Pruner (a T5 classifier) decides whether to expand a tail into the next level.
- Accuracy (AR): over one million nodes at 89.32% precision with ChatGPT, against PiVe 64.48% and OpenIE6 42.05%. Smaller backbones score lower: Llama2-7B 54.39%, Qwen-7B 69.89%.
- Precision was judged with GPT-4, whose agreement with humans was checked. — [SAC-KG, arXiv 2410.02811](https://arxiv.org/abs/2410.02811)

**GraphJudge (Huang et al., EMNLP 2025)**
- How it works, in three stages:
  1. Entity-centric text denoising with GPT-4o-mini.
  2. Knowledge-aware supervised fine-tuning (LoRA on LLaMA-2-7B) on positive triples and corrupted negatives.
  3. The fine-tuned model judges every candidate triple and filters out the false ones.
- Accuracy (AR): G-BS-F1 on REBEL-Sub 0.580, against 0.429 for GPT-4o-mini alone. On SciERC 0.728 against 0.688. Ablation on REBEL-Sub: removing the judge drops G-BS-F1 from 0.728 to 0.420. — [GraphJudge, arXiv 2411.17388](https://arxiv.org/abs/2411.17388)

**LLM ontology-constrained construction**
- Ontology-grounded construction under the Wikidata schema (Feng et al., KDD'24 workshop):
  - Generates competency questions, extracts relations, and replaces them with Wikidata equivalents where possible.
  - Partial F1 under the target-schema constraint: Wiki-NRE 0.71 (GPT-4o) / 0.66 (Mistral), SciERC 0.77 / 0.73, WebNLG 0.76 / 0.74.
  - The listed "LLM Baseline" scored 0.07 on SciERC, though that row mixes models from different papers. — [Feng et al., arXiv 2412.20942](https://arxiv.org/abs/2412.20942)
- SPIRES/OntoGPT:
  - Recursively prompts against a user-defined nested schema (LinkML) and grounds every element to ontology identifiers.
  - Authors describe accuracy as "comparable to the mid-range of existing Relation Extraction methods." — [SPIRES, Bioinformatics 2024, arXiv 2304.02711](https://arxiv.org/abs/2304.02711)
- OntoMetric (2025):
  - Ontology-constrained extraction with "deterministic identifiers," two-phase validation (semantic type check plus rule-based schema check), and segment- and page-level provenance.
  - 65–90% semantic accuracy and over 80% schema compliance, against 3–10% for unconstrained extraction, at US$0.01–0.02 per validated entity (AR). — [OntoMetric, arXiv 2512.01289](https://arxiv.org/abs/2512.01289)
- Industrial French power-grid reports (IJCKG 2026, local 7B–32B models):
  - Schema-guided prompting raised strict NER F1 by 36% (0.42→0.57, Gemma3) and relation-classification F1 by 37%.
  - The best models still reach only about 50% F1, and direct RE reached 26% exact-match F1.
  - Q4_K_M quantization is an acceptable cost trade-off. — [Belfadel et al., arXiv 2609.31663](https://arxiv.org/abs/2609.31663)
- ANCHOR for cyber-threat intelligence: replaces "prompt-based schema inclusion" with search-and-navigate over large ontologies (UCO, STIX, MALOnt) and SHACL validation. A local LLM nearly matches enterprise-LLM typing. — [ANCHOR, arXiv 2606.01208](https://arxiv.org/abs/2606.01208)

**Neo4j LLM Graph Builder and LangChain LLMGraphTransformer**
- Neo4j LLM Graph Builder:
  - Uploaded sources become `Document` nodes, and content is split into `Chunk` nodes linked to the Document and to each other.
  - Similar chunks get `SIMILAR` (kNN) edges, and embeddings are stored.
  - Entities and relationships come from `llm-graph-transformer` or `diffbot-graph-transformer` and are linked back to their originating Chunks.
  - Users can configure a schema and run clean-up after extraction. — [Neo4j Labs LLM Graph Builder docs](https://neo4j.com/labs/genai-ecosystem/llm-graph-builder/); [repo README](https://github.com/neo4j-labs/llm-graph-builder)
- LangChain LLMGraphTransformer:
  - Accepts `allowed_nodes` and `allowed_relationships`, the latter optionally as (source_type, rel, target_type) tuples.
  - `strict_mode=True` (the default) *post-filters* LLM output that breaks those constraints, so schema conformance is enforced by code, not trusted to the prompt. — [LangChain graph_transformers/llm.py](https://github.com/langchain-ai/langchain-experimental/blob/main/libs/experimental/langchain_experimental/graph_transformers/llm.py)

**Microsoft GraphRAG and LightRAG, as graph builders**
- GraphRAG:
  - Each TextUnit yields entities with `title`, `type` and `description`, and relationships with only `source`, `target` and `description`. There is no typed predicate.
  - Subgraphs merge where title *and* type match exactly. Description arrays are then summarized by the LLM into one description.
  - Claim extraction (time-bounded "covariates") exists but is off by default because it "generally requires prompt tuning." — [GraphRAG default dataflow docs](https://github.com/microsoft/graphrag/blob/main/docs/index/default_dataflow.md)
  - The paper uses "exact string matching for entity matching" and argues GraphRAG is "resilient to duplicate entities." GPT-4 extracted about twice as many entity references with 600-token chunks as with 2,400-token chunks, which motivated "gleanings," i.e. self-reflection re-prompts. — [Edge et al., arXiv 2404.16130](https://arxiv.org/abs/2404.16130)
  - A FastGraphRAG option replaces LLM extraction with NLP extraction. — [GraphRAG dataflow docs](https://github.com/microsoft/graphrag/blob/main/docs/index/default_dataflow.md)
- LightRAG:
  - Builds the graph as D̂ = Dedupe ∘ Prof(V, E): the LLM recognizes entities and relations per chunk, an LLM "profiling" step writes key–value text, and a deduplication step merges identical entities and relations.
  - Incremental update is a union of node and edge sets. — [LightRAG, arXiv 2410.05779](https://arxiv.org/abs/2410.05779)

**Docs2KG (2024)**
- Builds a unified multimodal KG from emails, web pages, PDFs and Excel files. Layout analysis and markdown conversion produce a *layout/structure* subgraph (headings, paragraphs, tables, images) linked to a *semantic* subgraph.
- No triple-level accuracy evaluation is reported. — [Docs2KG, arXiv 2406.02962](https://arxiv.org/abs/2406.02962)

**2025–2026 successors (selection)**
- AutoSchemaKG/ATLAS:
  - Extracts entity–entity, entity–event and event–event triples with Llama-3-8B and then induces a schema by "conceptualization." The result is 900M+ nodes and 5.9B edges, built in about 78,400 GPU-hours.
  - Triple precision is 95.65–100% and recall 84.6–94.3%, but the judge was DeepSeek-V3, not humans.
  - Schema alignment with human schemas is stated as both 92% and 95% in different places of the same paper. — [AutoSchemaKG, arXiv 2505.23628](https://arxiv.org/abs/2505.23628)
- RAKG: pre-extracts entities, then uses them as retrieval queries to gather cross-chunk context. 95.91% accuracy on the authors' MINE variant, against GraphRAG 89.71% (AR). — [RAKG, arXiv 2504.09823](https://arxiv.org/abs/2504.09823)
- KARMA (NeurIPS 2025 spotlight): nine agents covering discovery, extraction, schema alignment and conflict resolution. 83.1% "LLM-verified correctness" and 18.6% fewer conflict edges on 1,200 PubMed articles. — [KARMA, arXiv 2502.06472](https://arxiv.org/abs/2502.06472)
- LKD-KGC: orders documents by inferred knowledge dependencies and induces the entity schema autoregressively. Claims 10–20% gains in precision and recall. — [LKD-KGC, arXiv 2505.24163](https://arxiv.org/abs/2505.24163)
- InvertiTune: fine-tunes small models for single-shot Text2KG on synthetic text generated *from* KB subgraphs (an inverse task). — [InvertiTune, arXiv 2512.03197](https://arxiv.org/abs/2512.03197)
- Hyper-KGGen: n-ary hyperedges, plus a "skill library" learned using *extraction stability* as the reward signal. — [Hyper-KGGen, arXiv 2602.19543](https://arxiv.org/abs/2602.19543)
- Executable Schema Contracts (2026):
  - A closed-world field catalog with hash-based field IDs, which the LLM may only reference.
  - *Deterministic* statistics infer identity keys (uniqueness ≥ 0.95), foreign keys and source hierarchy.
  - The schema then drives extraction, deduplication and linking into a typed Neo4j KG, with a `SourceRecord`/`DERIVED_FROM` edge per raw record. Removing the deterministic structural step lowers EM by 2.1–6.8 points. — [Executable Schema Contracts, arXiv 2606.05415](https://arxiv.org/abs/2606.05415)
- SCOPE/SCION (2026): a benchmark for corpus-to-schema induction, plus an "auditable reference pipeline." Naming, merging, filtering and fusion are restricted to candidate-linked evidence under strict JSON contracts. Releases include parse/fallback logs, merge logs and run manifests. — [SCOPE/SCION, arXiv 2607.21610](https://arxiv.org/abs/2607.21610)
- Hardware datasheet KGs (2026): the LLM proposes graph updates as *validated instructions* that are applied by "deterministic local execution," with source provenance kept. Property faithfulness is 98.8%, against 76.1% for one-shot extraction. — [Qiao & Dick, arXiv 2610.12762](https://arxiv.org/abs/2610.12762)

**Earlier generative or closed IE that many pipelines build on**
- REBEL (2021): seq2seq end-to-end relation extraction over a Wikidata-aligned silver dataset. — [REBEL, Findings EMNLP 2021](https://aclanthology.org/2021.findings-emnlp.204/)
- GenIE (NAACL 2022): bi-level constrained generation, so that "only triplets consistent with the predefined knowledge base schema are produced." — [GenIE, arXiv 2112.08340](https://arxiv.org/abs/2112.08340)
- SynthIE (EMNLP 2023): 1.8M synthetic examples generated in the reverse direction (text from triples), giving +57 micro-F1 over the prior state of the art for closed IE. — [SynthIE, arXiv 2303.04132](https://arxiv.org/abs/2303.04132)
- CodeKGC: extraction framed as code completion with schema-aware prompts. — [CodeKGC, arXiv 2304.09048](https://arxiv.org/abs/2304.09048)
- KnowCoder: schemas as Python classes, with a 30k-type schema library. — [KnowCoder, arXiv 2403.07969](https://arxiv.org/abs/2403.07969)
- Grapher: generates nodes first, then edges. — [Grapher, arXiv 2211.10511](https://arxiv.org/abs/2211.10511)
- PiVe: a small verifier model iteratively corrects LLM graph output. — [PiVe, arXiv 2305.12392](https://arxiv.org/abs/2305.12392)
- Cheap baseline: dependency-parsing KG construction reaches 94% of LLM-based performance (61.87% vs 65.83%) at much lower cost in an enterprise GraphRAG setting (AR). — [Min et al., arXiv 2507.03226](https://arxiv.org/abs/2507.03226)

### Inferences
- For *exact* querying, the deciding design choice is whether predicates come from a closed, versioned vocabulary. GraphRAG and LightRAG relationships are untyped (source, target, free-text description), so `MATCH (a)-[:ACQUIRED]->(b)`-style predicates are impossible without a second canonicalization pass. KGGen's open predicates and GraphRAG's 966 relation types for 981 edges show the same problem.
- EDC, GenIE-style constrained decoding, LLMGraphTransformer `strict_mode`, SHACL-validated ANCHOR, OntoMetric and Executable Schema Contracts all enforce the schema *outside* the LLM, with code or a grammar. That is the property that makes stored predicates trustworthy for exact queries.
- Judge or verifier stages (SAC-KG Verifier, PiVe, GraphJudge) consistently raise precision, usually at some cost in recall. Precision is what exact retrieval needs most, because a false triple is returned as a "fact" with no similarity score to discount it.

### Gaps
- No neutral head-to-head study evaluates EDC, KGGen, iText2KG, GraphRAG, LightRAG, Neo4j LLM Graph Builder and Docs2KG on the same corpus under *strict* exact-match triple metrics. The closest is GraphJudge's comparison, which uses soft BERTScore-based graph metrics and was run by a competitor.
- Docs2KG and the Neo4j LLM Graph Builder have no published extraction-accuracy numbers I could find.

---

## 2. Benchmarks and evaluation of constructed graphs (Text2KGBench, WebNLG, REBEL, MINE, triple P/R, fact recoverability); independent vs author-reported

### Takeaway
Benchmarks measure different things: closed-schema triple match (WebNLG, REBEL, Wiki-NRE, Text2KGBench), ontology conformance and hallucination (Text2KGBench), or *fact recoverability* (MINE). Many recent "precision" figures are LLM-judged, and many reference sets are incomplete. Strict exact-match F1 for LLM pipelines is roughly 0.5–0.8 on clean benchmarks and around 0.25–0.5 on real domain text. Headline accuracies of 90%+ are almost always LLM-judged or human-judged precision without recall against a gold standard.

### Cited Findings
- **WebNLG+ 2020** defines the triple-matching criteria later reused by EDC and others:
  - *Strict*: the element and its type (subject, predicate or object) must match exactly.
  - *Exact*: exact element match, type ignored.
  - *Partial*: partial element match.
  - Only automatic metrics were used for text-to-RDF. — [WebNLG+ 2020 overview](https://aclanthology.org/2020.webnlg-1.7/)
- **REBEL** data is aligned by distant supervision from Wikipedia and Wikidata. EDC shows that its references are non-exhaustive and sometimes contain facts not stated in the text, which makes evaluation "overly pessimistic" for LLMs. — [EDC §4.2](https://arxiv.org/pdf/2404.03868); [REBEL](https://aclanthology.org/2021.findings-emnlp.204/)
- **Text2KGBench (ISWC 2023 Resources)**:
  - Two datasets: Wikidata-TekGen (10 ontologies, 13,474 sentences) and DBpedia-WebNLG (19 ontologies, 4,860 sentences).
  - Seven metrics: P, R, F1, ontology conformance (OC), and subject, relation and object hallucination.
  - It uses a "locally closed" evaluation that only scores relations present in the ground truth, to avoid false negatives.
  - Baselines: Vicuna-13B F1 0.35 (Wikidata-TekGen, all) with OC 0.83; Alpaca-LoRA F1 0.27; on DBpedia-WebNLG F1 0.30 and 0.25. — [Text2KGBench, arXiv 2308.02357](https://arxiv.org/abs/2308.02357)
- **MINE (KGGen)**:
  - MINE-1: 100 articles, each with 15 LLM-extracted, manually verified facts. A fact counts as recovered if an LLM judge can infer it from the KG nodes retrieved by embedding (all-MiniLM-L6-v2 top-k) plus their 2-hop neighbourhood. The judge agreed with humans 90.2% of the time.
  - MINE-2: downstream RAG evaluated with an LLM judge. — [KGGen §5](https://arxiv.org/pdf/2502.09956)
  - MINE is therefore an approximate, similarity-plus-LLM *fact-recoverability* test, not an exact-query test.
  - Conflict: RAKG reports GraphRAG at 89.71% on its "MINE dataset" while KGGen reports 47.80% on MINE-1, so the two papers must use different protocols. — [RAKG](https://arxiv.org/abs/2504.09823) vs [KGGen](https://arxiv.org/pdf/2502.09956)
- **LLM-judged headline numbers**:
  - AutoSchemaKG's 95–100% precision uses DeepSeek-V3 as judge. — [AutoSchemaKG](https://arxiv.org/pdf/2505.23628)
  - KARMA reports 83.1% "LLM-verified correctness." — [KARMA](https://arxiv.org/abs/2502.06472)
  - SAC-KG's 89.32% uses GPT-4 evaluation. — [SAC-KG](https://arxiv.org/abs/2410.02811)
- Judge-Bench (ACL 2025, 20 NLP tasks, 11 LLMs): LLM judges show "substantial variance across models and datasets" and "should be carefully validated against human judgments." Proprietary judges also raise reproducibility concerns. — [Judge-Bench, arXiv 2406.18403](https://arxiv.org/abs/2406.18403)
- **IND or third-party evaluations of LLM extraction quality**:
  - Han et al.: GPT-4 shows "a visible performance gap" against state-of-the-art supervised IE. — [arXiv 2305.14450](https://arxiv.org/abs/2305.14450)
  - Zhu et al.: GPT-4 is better as an inference assistant than as a few-shot extractor. — [arXiv 2305.13168](https://arxiv.org/abs/2305.13168)
  - Wadhwa et al.: exact-match evaluation under-credits generative RE. Under human evaluation, few-shot GPT-3 is roughly equal to fully supervised RE. — [Wadhwa et al., ACL 2023, arXiv 2305.05003](https://arxiv.org/abs/2305.05003)
  - FAA maintenance records: sixteen NLP tools and LLMs show "significant performance limitations" for mission-critical KG construction. — [Mealey et al., arXiv 2507.22935](https://arxiv.org/abs/2507.22935)
  - Paediatric literature (seven frontier LLMs, zero-shot and schema-free): models "generally produce relevant and document-faithful triples with limited hallucination" but behave very differently across construction stages. — [Chen et al., arXiv 2510.11297](https://arxiv.org/abs/2510.11297)
  - Local LLMs on DocRED: zero-shot F1 0.70 ± 0.041, against 0.80 for supervised DREEAM. — [Jourlin, arXiv 2604.11104](https://arxiv.org/abs/2604.11104)
- **Prompt and schema sensitivity**:
  - Automatic prompt optimization (DSPy, APE, TextGrad) on SynthIE and REBEL gives up to +16% triple F1 with an Extract-Critique-Refine prompt.
  - Relation and triple extraction "drops significantly" as the number of allowed relations grows from 100 to 800.
  - Prompts are "brittle due to subtle changes in the LLM models employed." — [Mihindukulasooriya et al., arXiv 2506.19773](https://arxiv.org/abs/2506.19773)
- **Evaluation without gold data**:
  - Financial-report triples evaluated with ontology-conformance and faithfulness proxies. An automatically induced ontology reached 100% conformance.
  - A regex-plus-LLM-judge hybrid check cut *apparent* subject hallucination from 65.2% to 1.6%; most "hallucinations" were coreference artefacts. — [Wesslund et al., arXiv 2602.11886](https://arxiv.org/abs/2602.11886)
- **Sampling-based accuracy estimation** (VLDB 2019): cluster, two-stage and stratified sampling give statistically bounded KG accuracy estimates. Annotation cost falls by up to 60% for a static KG and 80% for an evolving KG. — [Gao et al., arXiv 1907.09657](https://arxiv.org/abs/1907.09657)
- Deterministic structured-output scoring: Object Aligner aligns JSON or graph outputs to gold with the Hungarian algorithm and Weisfeiler-Leman referential alignment. It is "invariant to relabeling," positioned against LLM judges that are "expensive, opaque, and non-deterministic." — [Object Aligner, arXiv 2607.01972](https://arxiv.org/abs/2607.01972)
- FActScore defines atomic-fact precision against a knowledge source. This is the conceptual basis for MINE-style and ATOM-style atomic evaluation. — [FActScore, arXiv 2305.14251](https://arxiv.org/abs/2305.14251)

### Inferences
- For a deterministic-retrieval toolkit, the most informative metric is *strict/exact* triple precision and recall against canonical identifiers (WebNLG "Strict," Text2KGBench P/R plus OC). That metric is close to what an exact Cypher or SQL query will return. MINE-style recoverability and LLM-judged precision overstate usability for exact queries.
- A practical in-house protocol has four parts:
  - a small gold set, scored with strict matching after ID canonicalization;
  - Text2KGBench-style ontology-conformance and hallucination checks, which are deterministic validators;
  - stratified sampling (Gao et al.) for production precision estimates;
  - a deterministic structural scorer such as Object Aligner for regression tests between builds.

### Gaps
- I found no independent replication of MINE, of EDC's numbers, or of SAC-KG's 89% precision.
- No widely used benchmark scores *bitemporal* correctness or *span-level provenance* accuracy of constructed graphs.

---

## 3. Entity and relation canonicalization, linking (Wikidata or internal ontology), coreference, triple deduplication, LLM-as-judge filtering

### Takeaway
Canonicalization is where exactness is won or lost. The robust stack has four layers:
1. Deterministic identity first: identity keys, exact normalized strings, links to an internal KB or Wikidata.
2. Blocked candidate generation by entity type and embeddings, with the LLM or matcher deciding only within blocks.
3. Coreference resolution before extraction.
4. A recorded merge map, so that every canonical node can be reproduced and audited.

LLM judges raise precision but are themselves stochastic, so their verdicts must be stored, not recomputed.

### Cited Findings
- Relation canonicalization:
  - EDC's definition-based canonicalization yields smaller and less redundant schemas than CESI. On WebNLG, redundancy score is 0.833 for EDC against 0.893 for CESI, with 200 relation types against 280. — [EDC Table 2](https://arxiv.org/pdf/2404.03868)
  - CESI (WWW 2018) is the classic embedding-plus-side-information canonicalizer for open KBs. — [CESI, arXiv 1902.00172](https://arxiv.org/abs/1902.00172)
- Entity resolution in LLM-built KGs:
  - DEG-RAG (2025) gives the first systematic study of ER for LLM-generated KGs. Removing about 40% of entities and relations through ER plus "triple reflection" *improved* four Graph-RAG methods.
  - Type-aware blocking was the most effective blocking strategy, classic KG embeddings rivalled LLM embeddings, and simple merging beat adding synonym edges. — [DEG-RAG, arXiv 2510.14271](https://arxiv.org/abs/2510.14271)
- Embedding-plus-LLM deduplication:
  - KGGen clusters with k-means, retrieves top-16 candidates with BM25 plus embeddings, lets the LLM pick duplicates, and keeps an alias map. The authors acknowledge over- and under-merging. — [KGGen](https://arxiv.org/pdf/2502.09956)
  - iText2KG and ATOM use cosine thresholds (0.8 for entities, 0.7 for relations). — [ATOM](https://arxiv.org/pdf/2510.22590)
  - Graphiti combines embeddings and full-text search for candidates, then applies an LLM ER prompt. Edge deduplication is restricted to edges between the *same entity pair*, which prevents wrong cross-pair merges. — [Zep/Graphiti, arXiv 2501.13956](https://arxiv.org/abs/2501.13956)
- LLM entity matching (EDBT 2025):
  - GPT-4-class models match PLMs fine-tuned on thousands of examples with few or no examples, and are more robust to unseen entities.
  - "There is no single best prompt"; prompts must be tuned per model and dataset. — [Peeters et al., arXiv 2310.11244](https://arxiv.org/abs/2310.11244)
- AgenticER (VLDB vision 2026) argues that one-shot similarity ER fails in heterogeneous data lakes and frames ER as sequential evidence gathering. — [AgenticER, arXiv 2607.27435](https://arxiv.org/abs/2607.27435)
- Entity linking to a KB:
  - ReLiK (ACL Findings 2024) is a retriever–reader that does EL and RE in a single forward pass, achieves state-of-the-art results, and is up to 40× faster. — [ReLiK, arXiv 2408.00103](https://arxiv.org/abs/2408.00103)
  - ReFinED (NAACL Industry 2022) links end to end to Wikidata, is more than 60× faster than prior approaches, and supports zero-shot linking. — [ReFinED, arXiv 2207.04108](https://arxiv.org/abs/2207.04108)
  - LELA (ISWC 2026) is coarse-to-fine LLM EL that works across KBs without fine-tuning and is competitive with fine-tuned systems. — [LELA, arXiv 2601.05192](https://arxiv.org/abs/2601.05192)
  - Grammar-constrained decoding guarantees outputs inside a candidate set, which suits entity disambiguation and closed IE. — [Geng et al., EMNLP 2023, arXiv 2305.13971](https://arxiv.org/abs/2305.13971)
  - GenIE constrains generation to valid KB entities and relations. — [GenIE](https://arxiv.org/abs/2112.08340)
- Coreference:
  - LINK-KG adds three-stage LLM coreference with a type-specific prompt cache before extraction. It reduced node duplication by 45.21% and noisy nodes by 32.22% on legal documents (AR). — [LINK-KG, arXiv 2510.26486](https://arxiv.org/abs/2510.26486)
  - Maverick (ACL 2024): a 500M-parameter encoder pipeline reaches state of the art on CoNLL-2012 with 170× faster inference than prior state of the art. That makes it a cheap, deterministic-friendly coreference stage. — [Maverick, arXiv 2407.21489](https://arxiv.org/abs/2407.21489)
  - Unresolved coreference shows up as false "hallucination" flags in evaluation. — [Wesslund et al.](https://arxiv.org/abs/2602.11886)
- Triple filtering and judging:
  - GraphJudge's fine-tuned 7B judge is the main precision lever: removing it drops G-BS-F1 on REBEL-Sub from 0.728 to 0.420. — [GraphJudge](https://arxiv.org/pdf/2411.17388)
  - SAC-KG's verifier is rule-based and "parameter-free," and therefore deterministic. — [SAC-KG](https://arxiv.org/abs/2410.02811)
  - KGValidator frames LLM validation with structural (schema) and semantic checks, optionally against external KBs. — [KGValidator, ESWC Text2KG 2024, arXiv 2404.15923](https://arxiv.org/abs/2404.15923)
- Schema-driven deterministic deduplication:
  - Executable Schema Contracts use exact identity-key grouping (O(n) hashing) wherever keys exist, and embedding clustering (cosine ≥ 0.85) only as a fallback. Cross-source edges are built with hash joins over inferred foreign keys. — [Executable Schema Contracts](https://arxiv.org/pdf/2606.05415)

### Inferences
- Order of operations for canonical IDs:
  1. Exact normalization and identity keys.
  2. Linking to an internal registry or Wikidata QIDs with a dedicated linker (ReLiK, ReFinED, LELA) or constrained decoding.
  3. Type-blocked embedding candidates, adjudicated by an LLM or matcher.
  4. Persistence of every merge decision (alias → canonical ID, with evidence and model version) as data.
- Re-running ER then becomes a *replay* of stored decisions, not a fresh stochastic computation.
- Coreference must happen before extraction, or at the latest before ER; otherwise pronoun and alias nodes multiply.

### Gaps
- No study I found measures how ER merge decisions *drift* across LLM versions. That is a key threat to stable canonical IDs.

---

## 4. Temporal and bitemporal facts, n-ary relations, reification, property graph vs RDF, and their effect on exact queries

### Takeaway
Real-document facts are often qualified (time, place, role, quantity, condition). Flat binary triples either lose that information or create false contradictions. A query-ready store needs statement-level identity: a statement or event node in a property graph, an RDF 1.2 reifier or an n-ary relation node, or a row in a statement table. Those statements need valid-time and transaction-time columns. Hernández et al. found no clear query-performance winner between standard reification, n-ary relations and named graphs; singleton properties performed badly.

### Cited Findings
- Bitemporal facts:
  - Zep/Graphiti implements a "bi-temporal model": timeline T is event (valid) time and T′ is ingestion (transaction) time. Each edge stores t′_created, t′_expired, t_valid and t_invalid.
  - Contradicting new edges *invalidate* old ones by setting t_invalid, rather than deleting them.
  - Writes use "predefined Cypher queries" instead of LLM-generated queries "to ensure consistent schema formats." — [Zep, arXiv 2501.13956](https://arxiv.org/abs/2501.13956)
  - ATOM separates observation time from validity time and stores 5-tuples with lists of start and end timestamps per fact, so a fact's history accumulates. — [ATOM](https://arxiv.org/pdf/2510.22590)
  - SQL:2011 standardized application-time period tables and system-versioned tables, i.e. the relational form of valid time and transaction time. — [Kulkarni & Michels, SIGMOD Record 2012](https://sigmodrecord.org/publications/sigmodRecord/1209/pdfs/07.industry.kulkarni.pdf)
  - GraphRAG's optional claim "covariates" carry status and time bounds, but are off by default. — [GraphRAG dataflow](https://github.com/microsoft/graphrag/blob/main/docs/index/default_dataflow.md)
- N-ary relations:
  - Text2NKG (NeurIPS 2024) extracts fine-grained n-ary facts and supports hyper-relational, event-based, role-based and hypergraph schemas. — [Text2NKG, arXiv 2310.05185](https://arxiv.org/abs/2310.05185)
  - Hyper-KGGen extracts knowledge hypergraphs and releases the HyperDocRED benchmark. — [Hyper-KGGen](https://arxiv.org/abs/2602.19543)
  - AutoSchemaKG adds event nodes (entity–event and event–event triples) and argues events preserve more passage information than entity triples. — [AutoSchemaKG](https://arxiv.org/pdf/2505.23628)
  - Graphiti models multi-entity facts as hyper-edges by extracting the same fact between different entity pairs. — [Zep](https://arxiv.org/abs/2501.13956)
- Reification in RDF:
  - The study modelled Wikidata qualifiers four ways (standard reification, n-ary relations, singleton properties, named graphs) across five SPARQL engines.
  - Singleton properties were the most concise per triple, but four of five engines "struggled with the high number of unique predicates."
  - Only n-ary predicates supported SPARQL property paths natively. Otherwise there was "no clear winner." — [Hernández, Hogan & Krötzsch, SSWS 2015](https://ceur-ws.org/Vol-1457/SSWS2015_paper3.pdf)
- RDF-star and RDF 1.2:
  - Hartig and Thompson's RDF*/SPARQL* proposal aimed to bridge statement-level metadata, property graphs and RDF. — [Hartig & Thompson, arXiv 1406.3399](https://arxiv.org/abs/1406.3399)
  - RDF 1.2 (W3C Candidate Recommendation Snapshot, 7 April 2026) adds *triple terms*, and a *reifier* linked by `rdf:reifies` that "can be the subject or object of other triples." Annotations such as provenance or time attach to the reifier. — [RDF 1.2 Concepts](https://www.w3.org/TR/rdf12-concepts/)
- Graph data models: the ACM Computing Surveys tutorial contrasts directed edge-labelled graphs (RDF), heterogeneous graphs and property graphs, and covers schema, identity, context (including time and provenance), validation (SHACL) and quality assessment. — [Hogan et al., Knowledge Graphs, arXiv 2003.02320](https://arxiv.org/abs/2003.02320)
- Validation: SHACL validates RDF data graphs against shapes graphs. — [W3C SHACL](https://www.w3.org/TR/shacl/) ANCHOR uses SHACL to enforce schema-compliant typing of LLM output. — [ANCHOR](https://arxiv.org/abs/2606.01208)

### Inferences
- For exact queries, the representation should make *every asserted fact a first-class record* with an ID. In a property graph that means a `(:Statement {id, predicate, valid_from, valid_to, recorded_at, superseded_at})` node or relationship-with-properties; in RDF 1.2, a reifier; in SQL, a statement table. Only then can queries filter by time, source, confidence or extractor version, and a corrected fact supersede the old one without destroying history.
- Bitemporality (valid time plus build or transaction time) is what reconciles "deterministic retrieval" with incremental updates: a query "as of build B" is exactly reproducible even after later corrections.
- Property graph or RDF matters less than (a) a closed predicate vocabulary, (b) statement-level identity and (c) consistent n-ary modelling. Avoid singleton-property-style designs that mint one predicate per statement; this matches both Hernández et al. and KGGen's critique of GraphRAG's near-unique relation types.

### Gaps
- No LLM-KG paper I found evaluates extraction accuracy for *valid-time intervals* on standard benchmarks beyond ATOM's 2020-COVID-NYT set.
- No benchmark compares how RDF 1.2 reifiers and property-graph statement nodes affect LLM extraction pipelines (as opposed to query engines).

---

## 5. Provenance to source spans, incremental updates, reproducibility across runs and model versions

### Takeaway
LLM inference is not reproducible in practice even at temperature 0. That instability is amplified at the triple-set level: ATOM measured run-to-run Jaccard of only 0.21–0.55 at temperature 0. Builds of LLM graphs must therefore be treated as *materialized, versioned snapshots* with cached LLM I/O, span-level provenance and recorded extractor metadata. Determinism lives in the stored snapshot and the query engine, not in the extractor.

### Cited Findings
- Run-to-run instability of KG extraction:
  - ATOM's stability score is the Jaccard similarity of the 5-tuple sets across reruns, with gpt-4.1 at temperature 0.
  - Extracting from whole lead paragraphs gave only 0.212 ± 0.181 (run 2) and 0.218 ± 0.195 (run 3). Extracting from atomic facts gave 0.552 ± 0.124 and 0.534 ± 0.12.
  - The authors describe zero- and few-shot KG methods as suffering "instability across multiple runs." — [ATOM Table 1](https://arxiv.org/pdf/2510.22590)
- LLM nondeterminism in general:
  - Atil et al.: across five LLMs "configured to be deterministic," eight tasks and ten runs, accuracy varied by up to 15%, with a best-to-worst gap of up to 70%. "None of the LLMs consistently delivers repeatable accuracy across all tasks, much less identical output strings." — [Atil et al., arXiv 2408.04667](https://arxiv.org/abs/2408.04667)
  - Thinking Machines: 1,000 temperature-0 completions from Qwen3-235B produced 80 unique outputs, because kernels lack batch invariance. With batch-invariant kernels all 1,000 were identical, at a throughput cost (26 s for default vLLM vs 55 s for the unoptimized deterministic mode). — [He / Thinking Machines, "Defeating Nondeterminism in LLM Inference," 2025](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)
  - Self-consistency at k=5, T=0.7 recovered 23% EM on questions unsolvable at T=0. The author warns that strong consensus among samples can signal "collective hallucination." — [Jourlin, arXiv 2604.11104](https://arxiv.org/abs/2604.11104)
- Model-version brittleness: hand-crafted KG-extraction prompts are "brittle due to subtle changes in the LLM models employed." — [Mihindukulasooriya et al.](https://arxiv.org/abs/2506.19773)
- Build-reproducibility features in tools:
  - GraphRAG caches LLM invocation results "for faster performance when re-running the indexing process," partitioned by model instance. Clustering has a `seed` "if consistent run-to-run results are desired." Gleaning cycles are configurable (`max_gleanings`). — [GraphRAG config docs](https://github.com/microsoft/graphrag/blob/main/docs/config/yaml.md)
  - SCION releases run manifests, parse/fallback logs and candidate retention/merging logs, so schema-induction runs can be audited. — [SCOPE/SCION](https://arxiv.org/abs/2607.21610)
- Span-level provenance:
  - LangExtract (Google) maps "every extraction to its exact location in the source text." Ungrounded extractions get `char_interval = None` and can be filtered. It uses controlled generation for schema adherence and multiple extraction passes for recall. — [LangExtract README](https://github.com/google/langextract)
  - GraphRAG: TextUnits "are referenced by extracted knowledge items, providing provenance back to the original source text." — [GraphRAG dataflow](https://github.com/microsoft/graphrag/blob/main/docs/index/default_dataflow.md)
  - Graphiti: episodes are a "non-lossy data store" with bidirectional episode↔edge indices for citation. — [Zep](https://arxiv.org/abs/2501.13956)
  - Neo4j Builder links entities to originating Chunks. — [Neo4j docs](https://neo4j.com/labs/genai-ecosystem/llm-graph-builder/)
  - Executable Schema Contracts: a `SourceRecord` node with `DERIVED_FROM` per raw record. — [arXiv 2606.05415](https://arxiv.org/pdf/2606.05415)
  - OntoMetric: segment- and page-level provenance. — [arXiv 2512.01289](https://arxiv.org/abs/2512.01289)
  - KGGen links each relation to its source chunk. — [KGGen](https://arxiv.org/pdf/2502.09956)
- Provenance as a query result: GraphRAGProv runs SPARQL over source-grounded RDF graphs and returns *how-provenance polynomials* recording which statement occurrences were combined. Across 400 multi-hop cases this exposed extraction and query errors "even when the final answer is correct." — [GraphRAGProv, arXiv 2610.37237](https://arxiv.org/abs/2610.37237)
- Standard provenance vocabulary: W3C PROV-O (2013 Recommendation) provides classes and properties for entities, activities and agents. — [PROV-O](https://www.w3.org/TR/prov-o/)
- Incremental updates:
  - iText2KG matches new entities and relations to the global sets incrementally. — [iText2KG](https://arxiv.org/abs/2409.03284)
  - LightRAG unions new node and edge sets. — [LightRAG](https://arxiv.org/abs/2410.05779)
  - Graphiti invalidates contradicted edges. — [Zep](https://arxiv.org/abs/2501.13956)
  - ATOM merges atomic temporal KGs in parallel with about 90% lower latency. — [ATOM](https://arxiv.org/abs/2510.22590)
  - Executable Schema Contracts extend the schema under a *monotonicity invariant* (types, relations and attributes only grow), so prior elements stay valid. — [arXiv 2606.05415](https://arxiv.org/pdf/2606.05415)
  - Incremental KG accuracy can be estimated with stratified or reservoir sampling. — [Gao et al.](https://arxiv.org/abs/1907.09657)
- Exhaustivity versus chunk size: smaller inputs raise recall and stability. GraphRAG's 600-token chunks gave about twice the entity references of 2,400-token chunks. — [Edge et al.](https://arxiv.org/abs/2404.16130) ATOM keeps atomic-fact batches under 400 tokens. — [ATOM](https://arxiv.org/pdf/2510.22590) A small "propositioner" mostly helps weaker extractors. — [Pommeret et al., LREC KG-LLM 2026, arXiv 2604.02866](https://arxiv.org/abs/2604.02866)

### Inferences
- Reproducibility should be defined at three levels:
  - **Query determinism** over a frozen snapshot. This is fully achievable with standard DB engines.
  - **Build replay**: rebuilding with the same inputs, prompts, model ID and cache gives a byte-identical graph, because cached LLM responses are replayed.
  - **Build regeneration**: a new model or prompt version is a *new* snapshot, diffed against the previous one with deterministic scorers (Object Aligner, strict triple diff) and gated by evaluation.
  - Only the first two can be guaranteed. The third can only be measured and controlled.
- Every stored assertion should carry: source document hash, character span, chunk ID, extractor model ID and version, prompt or template hash, schema version, judge verdict and judge model, confidence, and build ID. PROV-O or a simple column set suffices. LangExtract-style span alignment makes the "traceable to source spans" requirement checkable by code (`char_interval != None`), not by an LLM.
- Self-hosting with batch-invariant inference kernels is the only route to *bitwise* reproducible regeneration. Hosted APIs do not guarantee it.

### Gaps
- No study I found measures graph drift across *model versions* (for example GPT-4o → GPT-4.1) for the same pipeline. ATOM measured only same-model reruns, and only at the 5-tuple level.
- No public numbers exist on cache-replay reproducibility in GraphRAG or other builders; the claim is architectural.

---

## 6. Which pipeline design is most effective for a precise, query-ready graph?

### Takeaway
No single published system is best. The evidence favours a **schema-first, constrain-validate-judge-record** pipeline:
- deterministic document structure and span provenance;
- coreference and atomic decomposition;
- extraction against a closed, versioned schema (induced once with EDC, AutoSchemaKG or SCION if none exists, then frozen);
- code-enforced schema conformance (constrained decoding, `strict_mode`, SHACL);
- deterministic identity resolution plus a KB linker, with LLM adjudication only inside blocks;
- a verifier or judge filter;
- writes as reified, bitemporal, provenance-stamped statements in versioned snapshots, with all LLM I/O cached.

GraphRAG and LightRAG-style description graphs suit sense-making but not exact predicates.

### Cited Findings (evidence for each design element)
- **Schema constraint drives precision.** Ontology-guided extraction gives 65–90% semantic accuracy against 3–10% unconstrained. — [OntoMetric](https://arxiv.org/abs/2512.01289) Schema-guided prompting gives +36–37% F1. — [Belfadel et al.](https://arxiv.org/abs/2609.31663) Constrained decoding guarantees schema-valid triples. — [GenIE](https://arxiv.org/abs/2112.08340); [GCD](https://arxiv.org/abs/2305.13971)
- **Large schemas need retrieval, not stuffing.** EDC's schema retriever raised F1, and accuracy falls as allowed relations grow from 100 to 800. — [EDC](https://arxiv.org/pdf/2404.03868); [APO study](https://arxiv.org/abs/2506.19773) ANCHOR's ontology navigation replaces prompt inclusion. — [ANCHOR](https://arxiv.org/abs/2606.01208)
- **Open extraction followed by canonicalization works when no schema exists.** EDC Self-Canonicalization reaches 0.956 precision with a 2.6× smaller schema than the raw open KG. — [EDC](https://arxiv.org/pdf/2404.03868) SCION-style auditable induction is an option. — [SCION](https://arxiv.org/abs/2607.21610)
- **Deterministic structure beats LLM inference where data allows.** Statistical identity and foreign keys add 2.1–6.8 EM. — [Executable Schema Contracts](https://arxiv.org/pdf/2606.05415) Validated instructions with deterministic execution give 98.8% faithfulness against 76.1%. — [Qiao & Dick](https://arxiv.org/abs/2610.12762) Dependency parsing reaches 94% of LLM KG quality. — [Min et al.](https://arxiv.org/abs/2507.03226)
- **Atomic decomposition improves stability and recall** (about +33% stability, about +18% exhaustivity) at roughly a 9% precision cost. — [ATOM](https://arxiv.org/abs/2510.22590)
- **Verification and judging improve precision.** — [GraphJudge](https://arxiv.org/abs/2411.17388); [SAC-KG](https://arxiv.org/abs/2410.02811); [PiVe](https://arxiv.org/abs/2305.12392)
- **ER and denoising improve the graph while shrinking it by about 40%.** — [DEG-RAG](https://arxiv.org/abs/2510.14271)
- **Coreference before extraction cuts duplicate nodes by about 45%.** — [LINK-KG](https://arxiv.org/abs/2510.26486)
- **Small fine-tuned extractors are an option for cost and stability.** — [SynthIE](https://arxiv.org/abs/2303.04132); [InvertiTune](https://arxiv.org/abs/2512.03197); [ReLiK](https://arxiv.org/abs/2408.00103)
- **Description-centric builders are a poor fit for exact queries.** GraphRAG relationships are untyped (source, target, description). — [GraphRAG docs](https://github.com/microsoft/graphrag/blob/main/docs/index/default_dataflow.md) In KGGen's (competitor-run) manual check, 0/100 sampled GraphRAG triples were valid subject–predicate–object triples. — [KGGen](https://arxiv.org/pdf/2502.09956)

### Inferences (recommended reference design for the toolkit)
1. **Lexical layer (deterministic).** Document → section → chunk nodes or rows, each with a content hash and character offsets, as in Docs2KG, Neo4j Builder and GraphRAG TextUnits. Tables and other structured sources go through deterministic extractors, not LLMs, following Executable Schema Contracts.
2. **Schema registry.** A versioned, closed predicate and type vocabulary with domain and range constraints, expressed as SHACL, LinkML/SPIRES or a JSON Schema. Induce it with EDC, AutoSchemaKG or SCION, have a human review it, then freeze it. Only monotonic extensions are allowed.
3. **Pre-processing.** Coreference (Maverick or LLM coreference as in LINK-KG), then atomic-fact or proposition decomposition (ATOM, Propositioner).
4. **Extraction.** Schema-retrieved prompts as in EDC, with structured output or grammar-constrained decoding (GenIE, GCD, LangExtract controlled generation). Every value must align to a source span; drop ungrounded extractions.
5. **Validation (deterministic).** Schema and SHACL checks, domain and range checks, a span-grounding check, and Text2KGBench-style conformance and hallucination metrics.
6. **Canonicalization.** Identity keys and normalized exact match, then a KB linker (ReLiK, ReFinED or LELA against Wikidata or an internal registry), then type-blocked candidates with LLM adjudication. Persist the alias map and merge decisions.
7. **Judging.** A fine-tuned small judge (GraphJudge-style) or a rule verifier (SAC-KG). Store the verdict, the judge model and the score; never recompute at query time.
8. **Storage.** Reified statements (a property-graph statement node or relationship with properties, an RDF 1.2 reifier, or a statement table) carrying valid_from/valid_to and recorded_at/superseded_at (Zep, ATOM, SQL:2011), plus PROV-O-style provenance (doc hash, span, chunk, model, prompt hash, schema version, build ID). Corrections supersede; they do not delete.
9. **Reproducibility.** Cache all LLM calls keyed by (input hash, prompt hash, model ID, parameters), as GraphRAG's cache does. Rebuilds replay the cache. Model or prompt changes create a new snapshot that is diffed with deterministic scorers and gated by a strict-match gold set plus sampled precision estimates (Gao et al.). Self-host with batch-invariant kernels if bitwise regeneration is required.

Under this design, agents get deterministic answers (same query plus same snapshot gives the same rows) and every answer row traces to a span. Extraction error remains a *measured* quantity, roughly 0.5–0.8 strict F1 on benchmarks and lower on messy domain text. It is not eliminated, so precision-oriented filtering and human review of the schema and of high-impact facts remain necessary.

### Gaps
- No published end-to-end system combines all of the above and reports strict-match accuracy, run-to-run stability and cross-model drift together. The recommendation is a synthesis of component evidence, not a validated system.
- Cost per million tokens for a full constrain-plus-judge pipeline is not well documented. Available points:
  - EDC: about US$0.009 per sentence-level example (GPT-3.5).
  - KGGen: US$0.84 per 1M characters.
  - OntoMetric: US$0.01–0.02 per validated entity.
  - AutoSchemaKG: about 78,400 GPU-hours for 5.9B edges.
