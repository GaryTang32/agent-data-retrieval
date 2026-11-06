# 01 Indexing, Chunking, Enrichment and Multi-Representation for a Searchable Agent Knowledge Base (state as of Nov 2026)

Scope: how unstructured, heterogeneous content is segmented, enriched and indexed so agents can find related topics, domain knowledge, rules, policies and SOPs. Not covered here (other tracks): SOP/procedure modeling, rule/policy representation, taxonomies/wikis as products, agentic search loops and memory, KB lifecycle, enterprise products, open-source stacks. Basics already covered in earlier notes are not repeated: parser comparisons, Anthropic contextual-retrieval headline numbers, the Vectara/Chroma/NVIDIA/FloTorch summaries (`Agent ready data lake toolkit/document_ingestion_parsing.md` Q5), and hybrid BM25+dense+rerank basics (`storage_agent_retrieval.md` Q3). This file adds primary-source numbers, 2025-2026 studies and the enrichment and multi-representation evidence.

Labels used below:
- **[vendor]**: the author sells the model or product being evaluated.
- **[author]**: results reported by the method's own authors.
- **[independent]**: third-party or comparative studies.
- **[older: YYYY]**: material from before 2025.

---

## Q1. Chunking: fixed, recursive, structure/heading-aware, semantic, page-level, late chunking, LumberChunker, Meta-Chunking, agentic/LLM chunking. What do independent comparisons show?

### Takeaway
Independent evidence from 2024 to 2026 converges on two points:
- **Simple segmentation works best for corpus-wide search.** Structure-aware splitting (headers, sections, paragraphs) or plain token/recursive splitting at roughly 200 to 512 tokens is as good as or better than embedding-based "semantic" chunking and LLM-guided chunking, at a tiny fraction of the cost.
- **LLM chunkers and late chunking win only in narrow regimes.** LLM chunkers (LumberChunker and similar) help for *in-document* needle search over long narrative text. Late chunking helps some embedders on some corpora but hurts others.

The best strategy depends on the embedder, the corpus and the metric. Chunking should therefore be a cheap, re-runnable, evaluated view over a structured document tree, not a fixed design decision.

### Cited Findings

**Method catalogue (how it works / developer / first release / evidence / cost / failure modes)**

- **Fixed-size and recursive splitting** (LangChain-style recursive separators; token windows) is the baseline in every study.
  - Chroma's July 2024 token-level evaluation *[vendor: vector DB; older: 2024]* covered 5 corpora (328k tokens, 472 queries) with text-embedding-3-large at n=5. RecursiveCharacterTextSplitter at about 200 tokens with no overlap gave recall 88.1, precision 7.0 and IoU 6.9.
  - The "OpenAI default" of 800 tokens with 400 overlap gave recall 87.9 but precision only 1.4.
  - Reducing overlap improved IoU. With the small MiniLM embedder, overlap was needed to keep recall up.

  — [Chroma Research, Evaluating Chunking](https://www.trychroma.com/research/evaluating-chunking)
- **Semantic chunking** places breakpoints where adjacent-sentence embedding distance spikes, or clusters sentences.
  - In Chroma's evaluation, the Kamradt breakpoint chunker had the *lowest* recall (83.6). ClusterSemanticChunker at 400 tokens reached 91.3 recall, and the GPT-4o LLMChunker 91.9. The best and worst strategies were 9 points apart. — [Chroma](https://www.trychroma.com/research/evaluating-chunking)
  - The Vectara and UW-Madison study *[independent-ish: Vectara sells RAG but no chunker; older: Oct 2024]* used stella_en_1.5B over 10 document-retrieval datasets, 5 evidence-retrieval datasets and answer generation.
    - Semantic chunkers won mainly on artificially "stitched" multi-topic documents, for example Miracl F1@5 81.89 vs 69.45 and NQ 63.93 vs 43.79.
    - Fixed-size usually won on original documents: HotpotQA 90.59, MSMARCO 93.58, Qasper 90.99.
    - Answer-generation BERTScore differences were around 0.01.
    - The authors conclude the compute cost is "not justified" and that embedding quality mattered more than the chunker.

    — [Qu, Tu, Bao 2024, arXiv 2410.13070](https://arxiv.org/abs/2410.13070)
- **Structure/element-aware chunking** chunks by parser-detected element types (titles, tables, list items, paragraphs) rather than by paragraphs alone.
  - Unstructured.io's study *[vendor; older: 2024]* reports that element-type-based chunking "largely improve[s]" RAG on financial reports and "yields the best chunk size without tuning". — [Jimeno Yepes et al. 2024, arXiv 2402.05131](https://arxiv.org/abs/2402.05131)
  - Docling's HierarchicalChunker emits one chunk per element and attaches heading and caption metadata. HybridChunker then splits over-limit chunks with the embedder's tokenizer, merges undersized peers that share headings and captions, and repeats table headers when a table spans chunks (`repeat_table_header=True`). — [Docling chunking docs](https://docling-project.github.io/docling/concepts/chunking/)
- **Page-level chunking:**
  - NVIDIA's June 2025 blog *[vendor: NeMo Retriever]* tested 5 datasets, token chunks of 128 to 2,048 with 15% overlap, page-level and section-level chunking, top-k 10 with a reranker, and RAGAS answer accuracy.
  - Page-level had the highest average (0.648) and the lowest standard deviation (0.107). Token-based scored 0.603 to 0.645.
  - Per-dataset winners differed: 1,024 tokens on FinanceBench (0.579) and RAGBattlePacket (0.804), 512 tokens on Earnings (0.681), page-level on KG-RAG (0.520). 128 tokens scored worst on KG-RAG (0.421).
  - Tables and charts were kept whole. The earlier notes dated this post 2024, but the page now shows June 18, 2025.

  — [NVIDIA Technical Blog](https://developer.nvidia.com/blog/finding-the-best-chunking-strategy-for-accurate-ai-responses/)
- **Late chunking** (Jina AI; arXiv Sep 2024) runs the long-context transformer over the whole document (up to 8k tokens) and mean-pools token embeddings per chunk span afterward, so chunk vectors carry document context. It needs no training. A fine-tuning recipe is also proposed. — [Günther et al. 2024, arXiv 2409.04701](https://arxiv.org/abs/2409.04701)
  - Jina's own BEIR results *[vendor/author]* with jina-v2-small and about 256-token chunks: late beat naive chunking on all 5 sets. Examples: NFCorpus 23.46 to 29.98 nDCG@10 (but "no chunking" 30.40), SciFact 64.20 to 66.10, Quora unchanged. Gains grow with document length. — [Jina blog, Aug 2024](https://jina.ai/news/late-chunking-in-long-context-embedding-models/)
  - Independent results are mixed to negative:
    - ECIR 2025 workshop, NFCorpus NDCG@5: late ≈ early for Stella-V5 (0.445 vs 0.443) and Jina-V3 (0.380 vs 0.374), but collapsed for BGE-M3 (0.070 vs 0.246). On MS MARCO with Stella, late scored 0.503 vs early 0.630. — [Merola & Singh 2025, arXiv 2504.19754](https://arxiv.org/abs/2504.19754)
    - A 2026 reproduction (4 embedders, BEIR plus GutenQA) found contextualized chunking helps in-corpus retrieval for propositions (+15.6% to +27.1%) and is neutral for paragraphs. It *degrades* in-document retrieval, with LumberChunker chunks dropping 3% to 62% depending on the model. — [Zhou, Wang, Koopman, Zuccon 2026, arXiv 2602.16974](https://arxiv.org/abs/2602.16974)
    - A preregistered 2026 study found late chunking (jina-v3) *lowered* Qasper recall by 11.4 points vs plain header-led chunks. — [Mangla 2026, arXiv 2603.23533](https://arxiv.org/abs/2603.23533)
    - A multi-objective scale study (CoRE and KILT, up to 1M docs) found late chunking had the worst or near-worst Recall@100 (for example Qwen KILT 88.79 vs token 94.03) and high indexing memory. — [Caspari et al. 2026, arXiv 2608.16586](https://arxiv.org/abs/2608.16586)
  - **Visual late chunking** (ColChunk, 2026) clusters ColPali-style patch embeddings into contextual multi-vectors. Across 24 visual document retrieval datasets *[author]* it reports more than 90% storage reduction and +9 nDCG@5 over single-vector models. — [Yan et al. 2026, arXiv 2604.10167](https://arxiv.org/abs/2604.10167)
- **LumberChunker** (Duarte et al., Jun 2024) iteratively prompts an LLM (Gemini) to find where content shifts within a group of passages. It reports +7.37% DCG@20 on the GutenQA narrative needle benchmark (100 books, 3,000 QA pairs) *[author]*. — [arXiv 2406.17526](https://arxiv.org/abs/2406.17526)
  - Independent reproduction: LumberChunker is best for *in-document* retrieval (GutenQA DCG@10 0.47 to 0.60 across 4 embedders). For *in-corpus* BEIR it is beaten by paragraph or fixed chunking, for example Jina-v3 0.469 vs 0.495.
  - Cost: about 1.11 docs/s vs about 1,854 docs/s for paragraph splitting (Gemini-2.5-Flash).

  — [arXiv 2602.16974](https://arxiv.org/abs/2602.16974)
- **Meta-Chunking** (Zhao et al., IAAR Shanghai, Oct 2024) uses small-LM perplexity ("Perplexity Chunking") and margin sampling to find logical boundaries, applies dynamic merging, then hierarchical summaries and chunk rewriting for "global information compensation" *[author]*. — [arXiv 2410.12788](https://arxiv.org/abs/2410.12788)
  - The same group's follow-ups:
    - **MoC** (Mar 2025) is a granularity-aware mixture of chunkers that has an LLM emit *regular expressions* rather than rewritten text. It adds the intrinsic metrics "Boundary Clarity" and "Chunk Stickiness". — [arXiv 2503.09600](https://arxiv.org/abs/2503.09600)
    - **QChunker** (Mar 2026) is a multi-agent debate (question-outline generator, segmenter, integrity reviewer, knowledge completer), distilled into small models with a "ChunkScore" metric. — [arXiv 2603.11650](https://arxiv.org/abs/2603.11650)

    All *[author]*; I found no independent replication.
- **Agentic/LLM-planned chunking**, cost-aware variants:
  - **D-RAC/W-RAC** (Sep 2026) parses documents into ID-addressable units, then has an LLM plan chunks over *identifiers* rather than regenerating text. Against agentic chunking with frontier LLMs it reports 95.7% fewer chunking-stage output tokens, 77.8% to 85.6% lower cost and 75% less time *[author]*. — [Allu et al. 2026, arXiv 2609.24220](https://arxiv.org/abs/2609.24220)
  - **TopoChunker** (NLPCC 2026) maps documents to a structured intermediate representation using Inspector and Refiner agents. On GutenQA/GovReport it reports +8.0% generation accuracy vs the best LLM baseline and 23.5% fewer tokens *[author]*. — [arXiv 2603.18409](https://arxiv.org/abs/2603.18409)
  - **Intent-Driven Chunking** (Feb 2026) has an LLM predict likely user intents, then uses dynamic programming for globally optimal boundaries. It reports +5% to +67% top-1 on 5 of 6 datasets with 40% to 60% fewer chunks *[author]*. — [arXiv 2602.14784](https://arxiv.org/abs/2602.14784)
  - **Adaptive Chunking** (LREC 2026) picks a chunker per document using 5 intrinsic metrics (references completeness, intrachunk cohesion, contextual coherence, block integrity, size compliance). It reports answer correctness of 72% vs 62% to 64% *[author]*. — [arXiv 2603.25333](https://arxiv.org/abs/2603.25333)

**Independent multi-method comparisons, 2025-2026**
- **Caspari et al. (Aug 2026)** compared 8 strategies × 2 corpora (CoRE from MS MARCO v2 and KILT-NQ, 10K to 1M+ docs) × 3 sub-1B embedders, with significance testing.
  - Computationally expensive methods "rarely provide consistent gains". Token chunking is the recommended default, and "Enriched (Title)" is a low-cost improvement.
  - Contextual (LLM) indexing ran at only 0.26 to 5.26 docs/s depending on LLM output speed. Contextual on KILT 10K cost about $9.6 to $14.7 via OpenRouter.

  — [arXiv 2608.16586](https://arxiv.org/abs/2608.16586)
- **Shaukat et al. (Mar 2026)** benchmarked 36 segmentation methods × 6 domains × 5 embedders with LLM-graded nDCG@5.
  - Paragraph Group Chunking was best (nDCG@5 about 0.459, P@1 about 24%, Hit@5 about 59%). Fixed-size *character* chunking was worst (nDCG@5 <0.244).
  - Dynamic token sizing was best in biology, physics and health. Paragraph grouping was best in legal and maths. Better chunking and bigger embedders are complementary.

  — [arXiv 2603.06976](https://arxiv.org/abs/2603.06976)
- **Bennani & Moslonka (Jan 2026)** ran an industrial setup (SPLADE plus Mistral-8B) on NQ.
  - Overlap gave "no measurable benefit" and increases indexing cost.
  - Sentence chunking is the most cost-effective and matches semantic chunking up to about 5k context tokens.
  - A "context cliff" appears beyond about 2.5k tokens.

  — [arXiv 2601.14123](https://arxiv.org/abs/2601.14123)
- **Bhat et al. (May 2025)** found the best chunk size depends on the answer type and the embedder:
  - 64 to 128 tokens is best for concise factoid answers; 512 to 1,024 for answers needing broader context.
  - Stella prefers larger chunks and Snowflake smaller ones.

  — [arXiv 2505.21700](https://arxiv.org/abs/2505.21700)
- Microsoft Azure AI Search *[vendor; older: Sep 2023]*, Ada-002, Recall@50 for vector-only retrieval:
  - Chunk size: 512 tokens 42.4 > 1,024 37.5 > 4,096 36.4 > 8,191 34.9.
  - Boundaries and overlap: preserving sentence boundaries 42.4 vs a hard token break 40.9; 10% overlap 43.1; 25% overlap 43.9.
  - Chunking vs a single vector per document: 45.7 vs 28.2 for answers in long documents.

  — [Microsoft Tech Community](https://techcommunity.microsoft.com/t5/azure-ai-foundry-blog/azure-ai-search-outperforming-vector-search-with-hybrid/ba-p/3929167)
- The FloTorch/Vecta Feb 2026 benchmark (50 academic papers, about 906k tokens) is available only via secondary posts; the primary URL now returns 404.
  - End-to-end accuracy: recursive 512 69%, fixed 512 67%, semantic 54% (semantic fragments averaged 43 tokens).

  — [premai summary](https://www.premai.io/blog/rag-chunking-strategies-the-2026-benchmark-guide/)
- The TREC 2024 RAG track's reference corpus (MS MARCO v2.1 segmented) uses 10-sentence sliding windows with a 5-sentence stride, giving 113,520,750 segments from 10,960,555 docs. Segments carry start/end character offsets back to the document. This is an example of a de facto community default. — [Pradeep et al. 2024, arXiv 2406.16828](https://arxiv.org/abs/2406.16828)

**Domain studies (policies, regulations, legal, enterprise manuals; closest to the "rules/policies/SOP" use case)**
- **German Civil Code (ICAIL 2026 workshop):** section and subsection chunks gave the highest recall. Methods that "override this structure" performed worse, including contextual chunking, semantic clustering, Lumber-style chunking and RAPTOR, and they were costlier. — [Prior et al. 2026, arXiv 2605.19806](https://arxiv.org/abs/2605.19806)
- **Oil and gas enterprise manuals, specs and P&IDs:**
  - Structure-aware chunking beat fixed, recursive and breakpoint-semantic chunking on top-K and had much lower compute cost.
  - All methods failed on P&ID diagrams, which points to the need for multimodal indexing.

  — [Taiwo & Yusoff 2026, arXiv 2603.24556](https://arxiv.org/abs/2603.24556)
- **Indian government regulatory documents:** a factorial study of 3 parsers × 3 chunkers × 5 embedders plus BM25, 800 questions, 72,000 rows and mixed-effects models.
  - No retriever family dominated, and parser and chunker interact significantly.
  - MPNet fails on table-derived questions.
  - Evidence preservation was above 98%, so differences come from *ranking*, not ingestion loss.

  — [Singh 2026, arXiv 2609.31660](https://arxiv.org/abs/2609.31660)
- **CDC policy QA:** two-stage retrieval with a cross-encoder raised faithfulness from 0.621 to 0.797 (Mistral-7B, MiniLM embedder). "Structural constraints in document segmentation remain a significant bottleneck for multi-step reasoning." — [Maharjan & Yadav 2026, arXiv 2601.15457](https://arxiv.org/abs/2601.15457)
- **Portuguese administrative docs** (36 docs, 1,706 pages, 21 configurations):
  - Docling with hierarchical splitting and image descriptions scored 94.1%, beating hand-curated Markdown (91.3%) and naive PDFLoader (86.2%).
  - Table questions showed a 33-point gap between basic and hierarchical splitting.
  - "Metadata enrichment and hierarchy-aware chunking contributed more to accuracy than the conversion framework alone."
  - An exploratory GraphRAG scored 82%.

  — [dos Santos et al. 2026, arXiv 2604.04948](https://arxiv.org/abs/2604.04948)
- **Financial PDFs:** a 2026 study of parsers × chunkers × overlap on two financial benchmarks, including the new TableQuest, gives practical guidelines; structure preservation matters for tables. — [El Bachyr et al. 2026, arXiv 2604.12047](https://arxiv.org/abs/2604.12047)
- **Academic theses:** cluster-based semantic chunking did not outperform fixed or recursive chunking, and RAGAS faithfulness was unreliable in this setup. — [Kreileder et al. 2026, arXiv 2607.01852](https://arxiv.org/abs/2607.01852)
- **Biomedical full text** (GraLC-RAG, 2,359 PMC articles):
  - Content-similarity methods had the highest MRR (0.517) but always retrieved from one section.
  - Structure-aware methods retrieved from up to 15.6× more sections.
  - Standard MRR "systematically undervalue[s] structural retrieval" for multi-section synthesis.

  — [Mortezaagha & Rahgozar 2026, arXiv 2603.22633](https://arxiv.org/abs/2603.22633)
- **Multilingual or low-resource settings:**
  - Turkish (9,000 judged QA): layout-aware Docling chunking helps table-heavy documents far more than text-heavy ones, and the top 3 embedders were statistically indistinguishable. — [Türkel et al. 2026, arXiv 2608.26192](https://arxiv.org/abs/2608.26192)
  - Khmer: recursive 300-character chunks with BGE-M3 were best, on a small set of 18 QA pairs. — [Chhoun et al. 2026, arXiv 2605.22203](https://arxiv.org/abs/2605.22203)

**Operational dimension: update cost**
- On 120 real Wikipedia revision pairs, fixed-size chunking re-embeds 57% to 68% of the new version's workload after an edit, because boundaries drift. Recursive chunking re-embeds 38% to 56% and content-defined chunking 43% to 54%. Evidence recall differs by less than 2 points across the three. — [Bian et al. 2026, arXiv 2610.31019](https://arxiv.org/abs/2610.31019)

### Inferences
- For a policy/SOP/domain-knowledge KB, the strongest evidence-backed default is **structure-led chunking**. Split at headings and sections first. Keep tables, lists and procedure steps atomic. Merge small siblings up to about 256 to 512 tokens and split oversized sections recursively at sentence boundaries. Legal, regulatory and enterprise-manual studies (2605.19806, 2603.24556, 2604.04948) consistently favor it.
- Drop overlap by default. Two independent 2026 studies found no benefit (2601.14123), and IoU studies found it wasteful (Chroma). The 2023 Azure result (+1.5 Recall@50 at 25% overlap) argues for keeping it only as a tunable.
- Do not adopt semantic (embedding-breakpoint), LLM, or late chunking as defaults. Offer LumberChunker-style LLM segmentation only for long unstructured narrative documents (transcripts, case narratives) with no headings, where in-document search matters.
- Content-aware boundaries (recursive or structure-led) also reduce re-embedding cost on edits (2610.31019), which matters for living policy documents.
- Measure on in-document and in-corpus tasks separately (2602.16974). Track section coverage, not only MRR, for synthesis questions (2603.22633).

### Gaps
- I could not open the primary FloTorch/Vecta 2026 report (404). Its numbers are second-hand.
- No independent replication exists for Meta-Chunking, MoC, QChunker, TopoChunker, IDC or D-RAC claims.
- No study isolates chunking for procedural documents (step lists, SOPs) specifically. The closest are the oil-and-gas manuals and legal codes.

---

## Q2. Enrichment: contextual retrieval, contextual chunk headers, document summaries, generated questions (doc2query, HyDE, HyPE), keyword/entity tagging, metadata extraction, "knowledge cards"

### Takeaway
Enrichment works mainly by restoring *document identity and missing vocabulary* to a chunk, which helps most for lexical (BM25) retrieval and for collections of near-duplicate documents (contracts, filings, policy versions).

The cheapest enrichment is deterministic: a title or heading-path prefix. It captures much of the gain:
- A 2026 preregistered study found LLM enrichment ≈ Anthropic-style contextual retrieval (which costs 5.8 to 8.7× more input tokens).
- Under a strong embedder or a reranker, neither beat a free section-path prefix.

Generated questions (doc2query, HyPE, QuOTE) give large gains on question-style queries, but they inflate the index and can hallucinate. Filter them and store them as separate vectors pointing to the parent chunk.

Adding metadata to the *reader's context* is not automatically good: a 2026 ECML study found most enrichment reduced answer accuracy.

### Cited Findings

**Contextual retrieval and its independent evaluations**
- Anthropic Contextual Retrieval *[vendor; older: Sep 2024]*:
  - **Method:** Claude 3 Haiku receives the whole document plus a chunk and writes 50 to 100 tokens of "succinct context", which is prepended before both embedding and BM25 indexing.
  - **Results:** top-20 failure rate fell from 5.7% to 3.7% (embeddings), 2.9% (plus BM25) and 1.9% (plus Cohere rerank of the top 150), across 4 domains.
  - **Cost:** about $1.02 per million document tokens with prompt caching.
  - **Skip-RAG rule:** below about 200k tokens (about 500 pages), put the whole KB in the prompt instead.
  - **Extras:** domain glossaries in the prompt may help.

  — [Anthropic](https://www.anthropic.com/news/contextual-retrieval)
- **ConTEB benchmark (2025)**, nDCG@10 averages:
  - "Anthropic Contextual" scored 72.4 vs 52.0 for plain ModernBERT. It reached 100 on Insurance, where chunks need document structure.
  - It ran at about 1,891 ms per document vs 15 ms for a trained contextual embedder (ModernBERT + InSeNT, 75.6).
  - BM25 scored 0.0 on Insurance.

  — [Conti et al. 2025, arXiv 2505.24782](https://arxiv.org/abs/2505.24782)
- **Mangla (2026, preregistered, v1-v2 results withdrawn)**, Qasper (951 questions) and FreshStack (235), 8 retrievers:
  - 7B-LLM enrichment (titles, summaries, keywords, questions in *one* call) beat a free section-path prefix by +5.5 recall on Qasper under hybrid retrieval. The +2.7 on FreshStack was not significant.
  - It was equivalent to contextual retrieval, which used 5.8 to 8.7× the input tokens.
  - Under BM25 alone enrichment gained +8.7. Under qwen3-embedding or a reranker the gain was within equivalence margins.
  - The free prefix under a strong retriever beat hybrid+enrichment by +3.4 to +6.3. The gain is attributed to document expansion (adding question terms) and to repairing poorly tuned rank fusion.
  - Add-ons (key dictionaries, key-based merging, related-key expansion, one call per field, late chunking) did no better than LLM-free controls.

  — [arXiv 2603.23533](https://arxiv.org/abs/2603.23533)
- **Caspari et al. 2026:** Enriched (Summary) was strongest for NDCG@10 but "rarely beats Enriched (Title)". Contextual chunking rarely achieved significant wins. — [arXiv 2608.16586](https://arxiv.org/abs/2608.16586)
- **ECIR 2025 workshop:** contextual retrieval slightly beat late chunking (NDCG@5 0.317 vs 0.309) at much higher compute (about 20 GB VRAM with Phi-3.5-mini). Reranking was "crucial for consistent gains". — [arXiv 2504.19754](https://arxiv.org/abs/2504.19754)
- **Cross-Document Topic-Aligned chunking** synthesizes topic chunks across documents. On HotpotQA *[author, faithfulness metric]* it reports faithfulness 0.93 vs 0.83 for contextual retrieval and 0.78 for semantic chunking, with higher indexing cost. — [Stankovic 2025, arXiv 2601.05265](https://arxiv.org/abs/2601.05265)

**Contextual chunk headers, title chains and document-summary augmentation**
- **Title-chain prefixes** reuse the document's own header hierarchy, with zero LLM calls. On a 1,600-query production Markdown KB, MRR@5 rose from 0.374 to 0.463 (+23.8%).
  - Measurement trap: in a prefix on/off ablation, annotator agreement collapsed from κ 0.45 to 0.04, because stripping the title chain removes the disambiguation annotators need.

  — [Yang 2026, arXiv 2608.00824](https://arxiv.org/abs/2608.00824)
- **HiQA** enriches chunks with cascading metadata (document title, section path) plus multi-route retrieval (semantic, lexical, keyword/entity). The gains are largest for "structured, domain-specific, highly similar document collections" (MasQA benchmark). — [Chen et al. 2024, arXiv 2402.01767](https://arxiv.org/abs/2402.01767)
- **Summary-Augmented Chunking** (legal, NLLP 2025) prepends a 150-character generic document summary (gpt-4o-mini, one call per *document*) to each 500-character chunk.
  - It roughly halves Document-Level Retrieval Mismatch. Baseline DRM on ContractNLI was above 95%; with SAC (500/150) it was 19.29%.
  - Generic summaries beat expert-guided legal-element summaries.

  — [Reuter et al. 2025, arXiv 2510.06999](https://arxiv.org/abs/2510.06999)
- **dsRAG** (D-Star AI, open source) *[author]*: "AutoContext" contextual chunk headers (document- and section-level context) plus query-time Relevant Segment Extraction, which merges adjacent relevant chunks into segments. FinanceBench claims are 96.6% vs a 32% baseline in current docs (83% vs 19% in older versions), not independently replicated. — [dsRAG docs](https://d-star-ai.github.io/dsRAG)
- **Financial filings (FinanceBench):** the largest gains came from "embedding chunk metadata directly with text ('contextual chunks')". A strong reranker was essential for precision. — [Dadopoulos et al. 2025, arXiv 2510.24402](https://arxiv.org/abs/2510.24402)

**Generated questions and document expansion (doc2query family)**
- **doc2query** (Nogueira, Yang, Lin, Cho, Apr 2019) predicts queries with seq2seq and appends them to documents for BM25. In a latency-critical regime it approaches neural re-ranker effectiveness *[older: 2019]*. — [arXiv 1904.08375](https://arxiv.org/abs/1904.08375)
- **Doc2Query--** (ECIR 2023) shows doc2query hallucinates. Filtering generated queries with a relevance model gave up to +16% effectiveness, −23% query time and −33% index size *[older: 2023]*. — [Gospodinov, MacAvaney, Macdonald, arXiv 2301.03266](https://arxiv.org/abs/2301.03266)
- **Doc2Query++** (Oct 2025) uses topic-model-guided keyword selection for diverse queries. It warns that concatenating queries adds noise for *dense* retrieval and proposes "Dual-Index Fusion", which keeps text and query signals in separate indexes. — [Kuo et al. 2025, arXiv 2510.09557](https://arxiv.org/abs/2510.09557)
- **TCDE** (Dec 2025) uses an LLM to distill documents into core "topic sentences" and pairs this with query-side sub-topic pseudo-docs. It reports +2.8% relative NDCG@10 on SciFact dense retrieval. — [Yang et al. 2025, arXiv 2512.17164](https://arxiv.org/abs/2512.17164)
- **HyDE** (Gao, Ma, Lin, Callan, Dec 2022; ACL 2023) generates a hypothetical *answer document* at query time and embeds it. It is zero-shot and strong vs Contriever, but adds an LLM call per query *[older: 2022]*. — [arXiv 2212.10496](https://arxiv.org/abs/2212.10496)
  - In QuOTE's comparison HyDE added about 1.2 s per query (1,274 ms vs 108 ms) and did not beat naive retrieval on SQuAD (C@1 76.6 vs 79.3). — [arXiv 2502.10976](https://arxiv.org/abs/2502.10976)
  - ARAGOG's independent comparison found HyDE and LLM reranking "significantly enhance retrieval precision" *[older: 2024]*. — [arXiv 2404.01037](https://arxiv.org/abs/2404.01037)
- **HyPE (Hypothetical Prompt Embeddings)** precomputes several hypothetical questions per chunk at indexing time, turning retrieval into question-question matching with no query-time latency. On 6 datasets *[author]* it reports up to +42 points context precision and +45 points claim recall. — [Vake, Vičič, Tošić, IEEE Access 2025; arXiv 2607.29402](https://arxiv.org/abs/2607.29402)
- **QuOTE** (Feb 2025) stores each generated question as its own vector with an `originalChunk` pointer, retrieves top-k×M, then deduplicates by chunk.
  - SQuAD C@1 gains were +6.8 to +17.2 across 5 embedders. NQ gains were small (+0.4 to +2.9).
  - There were some regressions: text-embedding-3-small on MultiHop-RAG Full@20 fell from 32.5 to 27.5.
  - Returns diminish beyond about 10 to 15 questions per chunk.
  - Index build took 170 s vs 10 s for naive indexing.

  — [Neeser et al. 2025, arXiv 2502.10976](https://arxiv.org/abs/2502.10976)
- **QuIM-RAG** (IEEE Access 2024) is a question-to-question inverted index over generated questions. — [Saha et al., arXiv 2501.02702](https://arxiv.org/abs/2501.02702)
- **HyQE** applies the inverse idea at re-ranking time: an LLM hypothesizes the query a retrieved context answers, then ranks by query-query similarity. — [Zhou et al. 2024, arXiv 2410.15262](https://arxiv.org/abs/2410.15262)
- **Question-based "knowledge compression" plus "paper-cards"** (Jun 2025, 109 scientific papers):
  - Question-encoded content reached Recall@3 0.84, +60% vs chunking.
  - Paper-cards (summaries under 300 characters) raised BM25 MRR@3 from 0.56 to 0.85 on simplified technical queries.
  - Vector storage fell by 80% *[author; small corpus]*.

  — [Eponon et al. 2025, arXiv 2506.13778](https://arxiv.org/abs/2506.13778)
- LangChain's MultiVectorRetriever operationalizes "summaries" and "hypothetical questions" as child vectors whose hits return the parent document from a separate docstore. Its examples use 3 questions per document. — [LangChain docs](https://python.langchain.com/docs/how_to/multi_vector)
- **Tool documentation** (an agent-relevant analogue of thin KB entries): structured LLM expansion of under-documented tool descriptions "substantially improves" tool retrieval (Tool-DE benchmark). — [Lu et al. 2025, arXiv 2510.22670](https://arxiv.org/abs/2510.22670)

**Keyword, entity and metadata tagging**
- **MetaGen Blended RAG** (IBM authors) generates key concepts, topics and acronyms as metadata, builds dense plus sparse indexes and boosts hybrid queries. Zero-shot PubMedQA: 82% retrieval accuracy, 77% RAG accuracy *[author]*. — [Sawarkar et al. 2025, arXiv 2505.18247](https://arxiv.org/abs/2505.18247)
  - The earlier **Blended RAG** (IEEE MIPR 2024) combined dense, sparse-encoder and BM25 indexes with hybrid queries on NQ and TREC-COVID *[older: 2024]*. — [arXiv 2404.07220](https://arxiv.org/abs/2404.07220)
- **Enterprise LLM metadata** (IEEE CAI 2026): a 3×3 matrix of chunkers × embedding strategies (content-only, TF-IDF-weighted, prefix-fusion).
  - Metadata-enriched variants consistently beat content-only: recursive + TF-IDF reached 82.5% precision and naive + prefix-fusion NDCG 0.813.
  - P95 latency stayed under 30 ms. Ground truth was silver (cross-encoder).

  — [Mishra et al. 2025, arXiv 2512.05411](https://arxiv.org/abs/2512.05411)
- **MCompassRAG** encodes topic metadata in the same embedding space as chunks, with a distilled lightweight retriever. It reports +8.24% information efficiency and more than 5× lower latency than efficient RAG baselines, with no query-time LLM call *[author]*. — [Abaskohi et al. 2026, arXiv 2606.18508](https://arxiv.org/abs/2606.18508)
- **SlimRAG** builds an entity-to-chunk table at index time instead of a knowledge graph and scores chunks by salient query entities. It beats flat and graph baselines with a far smaller index (RITU 16.31 vs 56+) *[author]*. — [Zhang et al. 2025, arXiv 2506.17288](https://arxiv.org/abs/2506.17288)
- **AMAQA:** using message metadata (timestamps, chat names) lifts GPT-4o accuracy from 0.50 to 0.86 and open models from 0.27 to 0.76. Metadata must be handled "throughout the entire RAG pipeline" (filters as well as text). — [Bruni et al. 2025, arXiv 2505.13557](https://arxiv.org/abs/2505.13557)
- **Counter-evidence (ECML-PKDD 2026):** across 6 benchmarks, 4 models and 5 enrichment levels (24k responses), "Most enrichment reduces accuracy" when metadata, structure or confidence scores are attached to *retrieved passages given to the model*. What matters is whether the model can act on the metadata. — [Zerhoudi, Granitzer, Mitrović 2026, arXiv 2606.29645](https://arxiv.org/abs/2606.29645)

### Inferences
- Separate **index-side enrichment** (text used to *find* a chunk) from **reader-side context** (text shown to the agent). Prefixes, summaries, keywords and generated questions help the former. Passing all of them to the reader can hurt (2606.29645). Anthropic also advises separating context from chunk text when generating answers.
- Recommended enrichment order by cost-effectiveness:
  1. Deterministic title / heading-path / document-type prefix (free).
  2. One per-document LLM summary of about 150 characters to 2 sentences, prepended to every chunk. One call per document (SAC, dsRAG, Enriched-Summary). Especially valuable when many documents are structurally similar (policy versions, contracts, SOP templates).
  3. One per-chunk LLM call producing keywords, entities, acronyms and 3 to 10 questions, stored as *separate* sparse fields and question vectors (Dual-Index Fusion, QuOTE dedup). This is worth it mainly for BM25 and for question-style agent queries.
  4. Full Anthropic-style contextual retrieval only if evaluation shows gains over options 1 to 3 with *your* retriever.
- Re-benchmark enrichment after upgrading the embedder or adding a reranker, because the gains shrink toward zero under strong retrievers (2603.23533).
- Filter generated questions for hallucination (Doc2Query--). Keep them versioned with the generator model so they can be regenerated.

### Gaps
- No public study found compares per-chunk generated questions vs per-document summaries vs contextual retrieval on the *same* policy/SOP corpus.
- "Knowledge cards" has no standard definition in the literature. The closest evidence is "paper-cards" (2506.13778) and RAPTOR-style summaries. CardRewriter (2510.10095) is a query-rewriting system, not KB indexing (title only seen; not cited).
- HyPE's arXiv posting (2607.29402) is a 2026 re-post of a 2025 IEEE Access paper. I read only its abstract.

---

## Q3. Granularity and multi-representation: propositions, parent-child / small-to-big, sentence-window, multi-vector, RAPTOR trees, MemTree, SiReRAG, document-summary indexes

### Takeaway
The robust pattern is **decoupling the retrieval unit from the reading unit**: match on small or derived representations (sentences, propositions, questions, summaries) and return a larger, structurally complete parent (section, page, segment).

Proposition indexing helps mainly weaker or unsupervised retrievers on open-domain factoid QA, at 6× the vectors.

RAPTOR-style LLM summary trees help long-document and thematic questions in the authors' tests. In independent 2025-2026 evaluations, however:
- they lose to strong flat dense retrieval on standard QA (HippoRAG 2 table);
- they lose to cheaper zero-LLM tree navigation (NavTree);
- they underperform structure-aligned chunks on legal codes.

Store multiple representations per node, but evaluate each one.

### Cited Findings

**Propositions**
- **Dense X Retrieval** (Tencent AI Lab and others, Dec 2023; EMNLP 2024):
  - **Method:** a Flan-T5-large "Propositionizer" distilled from GPT-4 decomposes Wikipedia into 256.9M propositions (11.2 words on average) vs 41.4M passages (6.3 propositions per passage).
  - **Retrieval gains:** Recall@5 rose +12.0 for SimCSE and +9.7 for Contriever (unsupervised), but only +2.6 for DPR and +2.8 for GTR (supervised), mostly on out-of-distribution sets.
  - **Downstream QA:** LLaMA-2 with a 100 to 500 token budget gained +2.4 to +4.1 EM.
  - **Costs:** about 500 P100 GPU-hours to decompose, about 6× more vectors (about 768 GB flat index), and the authors note propositions "struggle with multi-hop" questions.

  — [Chen et al., arXiv 2312.06648](https://arxiv.org/abs/2312.06648)
- In the 2026 reproduction, propositions were the *worst* pre-embedding in-corpus unit on BEIR (for example Jina-v3 0.389 vs paragraph 0.495). They benefited most from contextualized (late) chunking (+15.6% to +27.1%). — [arXiv 2602.16974](https://arxiv.org/abs/2602.16974)
- **Alternatives to materializing propositions:**
  - The Sub-Sentence Encoder (2023) produces per-proposition contextual embeddings at sentence-encoder cost. — [Chen et al., arXiv 2311.04335](https://arxiv.org/abs/2311.04335)
  - AGRaME (2024) ranks at sentence or proposition granularity using multi-vector embeddings while encoding only at passage level. It is useful for post-hoc citation. — [Reddy et al., arXiv 2405.15028](https://arxiv.org/abs/2405.15028)
  - ToPG (Idiap, 2026) builds a heterogeneous proposition-entity-passage graph traversed with LLM suggestion and selection. It is strong on simple, complex and abstract QA *[author]*. — [Delmas et al., arXiv 2601.04859](https://arxiv.org/abs/2601.04859)

**Parent-child, small-to-big and sentence-window**
- LangChain MultiVector and ParentDocument retrievers: child vectors (chunks, summaries, questions) are linked by ID to parents stored in a docstore, and child hits return the parent. — [LangChain docs](https://python.langchain.com/docs/how_to/multi_vector)
- **ARAGOG** *[independent; older: 2024]*: Sentence Window Retrieval was "the most effective for retrieval precision" (with variable answer similarity). The Document Summary Index was "a competent retrieval approach". MMR and multi-query did not help. — [Eibich et al., arXiv 2404.01037](https://arxiv.org/abs/2404.01037)
- **H-RAG** (SemEval-2026 Task 8, multi-turn RAG): sentence-based overlapping child chunks, full documents as parents, hybrid dense-sparse retrieval. nDCG@5 0.4271. — [arXiv 2605.00631](https://arxiv.org/abs/2605.00631)
- **SciRet** (CORD-19): sentence-window chunks + BM25 + BGE-M3 + RRF reached Recall@10 1.0 at 1K and 15K papers. An MS MARCO-trained cross-encoder *reduced* precision on the scientific corpus (domain mismatch). Labels are pseudo-relevance. — [arXiv 2608.03860](https://arxiv.org/abs/2608.03860)
- **Mix-of-Granularity** (COLING 2025) trains a router to pick the granularity per query and per knowledge source, with a graph variant (MoGG) for distant snippets *[author]*. — [Zhong et al., arXiv 2406.00456](https://arxiv.org/abs/2406.00456)
- **LongRAG** (2024) is the opposite extreme: about 4K-token retrieval units (grouped Wikipedia docs, or a whole document as one unit) read by a long-context LLM. It achieved NQ EM 62.7 and HotpotQA 64.3 with fewer than 8 units and no training *[older: 2024]*. — [Jiang, Ma, Chen, arXiv 2406.15319](https://arxiv.org/abs/2406.15319)
- **DICE** (2026) splits long documents into chunks, encodes them independently and aggregates them back into one document vector. On LongEmbed with the Dream backbone, Passkey >4k rose from 30.0 to 90.0 and Needle >4k from 23.3 to 74.0. — [Lyu et al., arXiv 2606.18781](https://arxiv.org/abs/2606.18781)

**Hierarchical summary trees**
- **RAPTOR** (Stanford: Sarthi, Manning et al., Jan 2024; ICLR 2024):
  - **Construction:** 100-token chunks → SBERT → UMAP + GMM soft clustering (number of clusters by BIC) → gpt-3.5 summaries, recursively. "Collapsed tree" retrieval, which flattens all nodes, beat top-down traversal.
  - **Results:** QASPER F1 55.7 vs DPR 53.0 (GPT-4). QuALITY with GPT-4 reached 82.6 (+20 absolute over the prior best). 18.5% to 57% of retrieved nodes came from non-leaf layers.
  - **Quality and cost:** 4% of sampled summary nodes contained hallucinations. Build cost is linear in document length.

  — [arXiv 2401.18059](https://arxiv.org/abs/2401.18059)
- **Independent evidence against RAPTOR as a default:**
  - HippoRAG 2 (ICML 2025), Llama-3.3-70B reader: RAPTOR's average F1 was 48.8 vs 57.0 for plain NV-Embed-v2 dense retrieval (NQ 50.7 vs 61.9; MuSiQue 28.9 vs 45.7). It edged ahead only on PopQA (56.2 vs 55.7). — [Gutiérrez et al., arXiv 2502.14802](https://arxiv.org/abs/2502.14802)
  - NavTree (2026) builds a *deterministic* balanced segment tree with zero LLM calls and uses it purely for navigation (a hybrid frontier walk that emits only leaves). It ties the strongest flat baseline and beats a matched-reader abstractive RAPTOR "at every multi-chunk budget". The benefit of summary trees "can come from navigation rather than the generated summary content". — [Jayraj et al., arXiv 2610.06902](https://arxiv.org/abs/2610.06902)
  - Semantic Compression Trees (2026) store only each node's *residual* information. They match dense retrieval when the document is given (F1 0.274 vs 0.277) with 30% fewer context tokens. Top-down descent fails at selecting the document (routing accuracy 20.2% vs 39.3% for flat retrieval): "the residual representation is worth keeping and top-down routing is not." — [Farooq, arXiv 2608.21610](https://arxiv.org/abs/2608.21610)
  - German Civil Code: RAPTOR underperformed section/subsection chunks at higher cost. — [arXiv 2605.19806](https://arxiv.org/abs/2605.19806)
- **Tree variants:**
  - Dynamic-dataset RAPTOR maintenance (2024) addresses re-clustering on insert or delete. — [Chucri et al., arXiv 2410.01736](https://arxiv.org/abs/2410.01736)
  - DTCRS (2026) builds trees only for question types that need them, seeded by sub-question embeddings, which reduces redundant summaries and build time. — [Luo et al., arXiv 2604.07012](https://arxiv.org/abs/2604.07012)
  - Ψ-RAG (ICML 2026) uses a "merging and collapse" abstract tree across documents plus an agentic multi-granular retriever: +25.9% F1 vs RAPTOR and +7.4% vs HippoRAG 2 on cross-document multi-hop QA *[author]*. — [Zhao & Yang, arXiv 2605.00529](https://arxiv.org/abs/2605.00529)
- **MemTree** (Oct 2024) is a dynamic tree memory. Each node holds aggregated text, an embedding and an abstraction level, and new items are inserted by embedding comparison, so no global re-clustering is needed. It improves multi-turn dialogue and document QA over flat memory *[author]*. — [Rezazadeh et al., arXiv 2410.14052](https://arxiv.org/abs/2410.14052)
- **SiReRAG** (Salesforce, ICLR 2025) indexes a *similarity tree* (RAPTOR-like recursive summaries) plus a *relatedness tree*: propositions grouped by shared entities, then summarized. Both are flattened into one pool. It reports +1.9% average F1 on MuSiQue, 2Wiki and HotpotQA, and up to +7.8% with rerankers *[author]*. — [Zhang et al., arXiv 2412.06206](https://arxiv.org/abs/2412.06206)

**Multi-vector (late interaction) as a representation**
- **ColBERT** (SIGIR 2020) encodes per-token vectors with MaxSim late interaction. **ColBERTv2** (NAACL 2022) adds residual compression that cuts the space footprint by 6 to 10×. **PLAID** (2022) brings latency to tens of ms on GPU and up to 45× faster on CPU vs vanilla ColBERTv2 at 140M passages *[older]*. — [Khattab & Zaharia, arXiv 2004.12832](https://arxiv.org/abs/2004.12832); [Santhanam et al., arXiv 2112.01488](https://arxiv.org/abs/2112.01488); [Santhanam et al., arXiv 2205.09707](https://arxiv.org/abs/2205.09707)
- **MUVERA** (Google, NeurIPS 2024) reduces multi-vector search to single-vector MIPS via Fixed Dimensional Encodings, matching recall while retrieving 2 to 5× fewer candidates. — [Dhulipala et al., arXiv 2405.19504](https://arxiv.org/abs/2405.19504)
- **LIMIT** (Google DeepMind, ICLR 2026):
  - Single-vector embedders are bounded in which top-k subsets they can represent. On the simple LIMIT task, Recall@100 was below 20 for all SOTA embedders (Qwen3 Embed 4.8, Gemini Embed 10.0), vs 54.8 for multi-vector GTE-ModernColBERT and 93.6 for BM25.
  - BM25 "dropped sharply" on a synonym variant.

  — [Weller et al., arXiv 2508.21038](https://arxiv.org/abs/2508.21038)

### Inferences
- Index each structural node (document, section, chunk) as a record with several representations:
  - text for BM25, plus a dense vector of prefix + chunk;
  - optional question vectors and a summary vector;
  - optional multi-vector or learned-sparse.

  Retrieve at small granularity, then expand to the parent section or page (small-to-big) at read time. This is cheap, uses the parser's tree, and matches the evidence for sentence-window and parent-child approaches.
- Treat RAPTOR-style abstractive summary trees as an *optional* layer for "overview/what-is-our-approach-to-X" questions over long documents.
  - The 2025-2026 evidence says the *tree as navigation scaffold* (deterministic, from headings) is the durable part. LLM summaries add cost and some hallucination (4% in RAPTOR's own sample).
  - For knowledge bases with headings, the document's own heading tree is a free RAPTOR.
- Propositions are worth it only for fact-dense reference content with weak retrievers, or as a re-ranking/citation granularity (AGRaME). Avoid them as the primary index at enterprise scale (6× vectors).

### Gaps
- No independent head-to-head comparison found of MemTree or SiReRAG against simple hierarchical-section indexing on enterprise documents.
- No public cost figures (USD) found for building RAPTOR or SiReRAG trees on large corpora, beyond "linear in length".

---

## Q4. Embedding and representation choices for domain knowledge: fine-tuning, SPLADE, BM25, ColBERT, hybrid, long-context, contextual chunk embeddings, multilingual

### Takeaway
For domain knowledge, the highest-leverage representation decisions are:
1. A strong modern embedder, often more impactful than chunking or enrichment (2410.13070, 2603.23533).
2. Always keeping a lexical channel (BM25 or learned sparse) for codes, acronyms, IDs and "exact snippet" queries.
3. A reranker, while checking that it is not domain-mismatched.

Domain fine-tuning with synthetic queries gives large gains where retrieval is the bottleneck (FinanceBench Recall@10 0.29 → 0.55), and little where it is not.

A new 2025-2026 model class, **contextualized chunk embeddings** (voyage-context-3, pplx-embed-context, InSeNT), builds document context into the embedder and makes chunk-level enrichment partly redundant. Evidence so far is mostly vendor or author.

### Cited Findings

**Lexical, learned-sparse, dense and hybrid**
- **BEIR** (NeurIPS 2021): BM25 is a robust zero-shot baseline. Reranking and late interaction are best on average but costly. Dense models often underperform out of domain *[older: 2021]*. — [Thakur et al., arXiv 2104.08663](https://arxiv.org/abs/2104.08663)
- **Azure AI Search** *[vendor; older: 2023]*:
  - NDCG@3 on customer data: keyword 40.6, vector 43.8, hybrid (RRF) 48.4, hybrid + semantic ranker 60.1.
  - Keyword queries: vector 11.7 vs keyword 79.2. Hybrid recovers to 61.0.

  — [Microsoft](https://techcommunity.microsoft.com/t5/azure-ai-foundry-blog/azure-ai-search-outperforming-vector-search-with-hybrid/ba-p/3929167)
- **SPLADE** (Naver Labs Europe; SIGIR 2021) learns sparse term weights plus expansion with an inverted index. SPLADE v2 improved TREC DL'19 by more than 9% nDCG@10. SPLADE-v3 (2024) is significantly better than BM25 and SPLADE++ across 40+ query sets, reaching more than 40 MRR@10 on MS MARCO and +2% on BEIR out of domain *[author; older]*. — [Formal et al., arXiv 2107.05720](https://arxiv.org/abs/2107.05720); [arXiv 2109.10086](https://arxiv.org/abs/2109.10086); [Lassance et al., arXiv 2403.06789](https://arxiv.org/abs/2403.06789)
- **Inference-free learned sparse** (document-side encoder only, query = token lookup), suited to the production latency of BM25-class engines:
  - OpenSearch/Amazon's IDF-aware penalty plus ensemble distillation (2024). — [Geng et al., arXiv 2411.04403](https://arxiv.org/abs/2411.04403)
  - Li-LSR (2025): the query encoder was "the bottleneck". — [Nardini et al., arXiv 2505.01452](https://arxiv.org/abs/2505.01452)
- **BGE-M3** (BAAI, 2024) produces dense, sparse and multi-vector outputs from one model, covers 100+ languages and handles inputs up to 8,192 tokens. That makes it a convenient single model for a multi-representation index. — [Chen et al., arXiv 2402.03216](https://arxiv.org/abs/2402.03216)
- **Jina-ColBERT-v2** (2024) is a multilingual late-interaction retriever. — [Jha et al., arXiv 2408.16672](https://arxiv.org/abs/2408.16672)
- **BRIGHT** (ICLR 2025) contains reasoning-intensive queries (economics, psychology, coding) where the MTEB leader (59.0 nDCG@10 on MTEB) performs poorly. This kind of query is relevant to "find the applicable rule" agent requests. — [Su et al., arXiv 2407.12883](https://arxiv.org/abs/2407.12883)

**Domain adaptation and fine-tuning**
- **GPL** (NAACL 2022) generates synthetic queries, mines hard negatives and uses cross-encoder pseudo-labels. It gave up to +9.3 nDCG@10 on 6 domain datasets *[older]*. — [Wang et al., arXiv 2112.07577](https://arxiv.org/abs/2112.07577)
  - R-GPL (2025), which re-mines hard negatives during distillation, improved 13 of 14 BEIR and 9 of 12 LoTTE datasets. — [arXiv 2501.14434](https://arxiv.org/abs/2501.14434)
- **Promptagator** (Google, 2022) builds task-specific retrievers from about 8 examples via LLM query generation *[older]*. — [Dai et al., arXiv 2209.11755](https://arxiv.org/abs/2209.11755)
- **Databricks (Feb 2025)** *[vendor-run, but reports a non-gain]*, Recall@10 from synthetic-query fine-tuning (Llama-3-405B generation, GPT-4o filter):
  - gte-large: FinanceBench 0.293 → 0.552.
  - e5-mistral: FinanceBench 0.479 → 0.670; ManufactQA 0.836 → 0.913.
  - DocsQA: no gain (0.899 → 0.899), where OpenAI 3-large scored 0.95.
  - "MTEB performance did not reliably predict performance on their internal enterprise tasks."

  — [Databricks blog](https://www.databricks.com/blog/improving-retrieval-and-rag-embedding-model-finetuning)
- **Mafin** fine-tunes a small trainable model *alongside* a black-box API embedder, which matters when the KB uses a closed embedding API. — [Zhang et al. 2024, arXiv 2402.12177](https://arxiv.org/abs/2402.12177)
- **ORPHEAS** (2026) shows a Greek-English domain fine-tune that beats multilingual SOTA without losing cross-lingual ability *[author]*. — [Livieris et al., arXiv 2604.20666](https://arxiv.org/abs/2604.20666)
- **Contextual Document Embeddings** (Morris & Rush, ICLR 2025) adds corpus-neighbor context to training and architecture. The gains are "especially pronounced out-of-domain", which helps specialized KBs without labels. — [arXiv 2410.02525](https://arxiv.org/abs/2410.02525)

**Long-context and contextualized chunk embeddings**
- **8k-context embedders:**
  - jina-embeddings-v2 (2023), the first open 8,192-token model, matched ada-002. — [Günther et al., arXiv 2310.19923](https://arxiv.org/abs/2310.19923)
  - nomic-embed-text-v1 (2024): open data and code, 8,192 tokens, Apache-2.0. — [Nussbaum et al., arXiv 2402.01613](https://arxiv.org/abs/2402.01613)
  - jina-v3 (2024): 570M parameters, task LoRA adapters, Matryoshka dimensions down to 32. — [Sturua et al., arXiv 2409.10173](https://arxiv.org/abs/2409.10173)
  - LongEmbed (EMNLP 2024) shows models still have "huge room for improvement" on long inputs and that training-free position interpolation extends context to 32k. — [Zhu et al., arXiv 2404.12096](https://arxiv.org/abs/2404.12096)
  - Azure's numbers (above) show recall *falls* as more tokens go into one vector (512 → 8,191: 42.4 → 34.9), so long context is not a substitute for chunking.
- **voyage-context-3** (Voyage AI / MongoDB, Jul 23, 2025) *[vendor]*:
  - **Method:** a whole-document single pass outputs one embedding per chunk. It is billed as a "drop-in replacement".
  - **Results:** on 93 datasets across 9 domains it claims +14.24% (chunk) / +12.56% (document) over OpenAI-v3-large, +20.54% / +2.40% over contextual retrieval and +23.66% / +6.76% over Jina late chunking. It also claims lower sensitivity to chunk size.
  - **Storage:** binary 512-dimension vectors were 0.73% better than OpenAI float-3072 at 99.48% lower storage.
  - **Caveat:** the page reports figures inconsistently between its TL;DR and body.

  — [Voyage blog](https://blog.voyageai.com/2025/07/23/voyage-context-3/)
  - Price is listed at $0.18 per million tokens, with up to 32k tokens per chunk and 120k per request. — [LiteLLM Voyage docs](https://docs.litellm.ai/docs/providers/voyage)
- **pplx-embed-context-v1** (Perplexity, Feb 2026) is a diffusion-pretrained bidirectional backbone with late-chunking-style pooling and "new records on ConTEB" *[vendor]*. — [Eslami et al., arXiv 2602.11151](https://arxiv.org/abs/2602.11151)
  - **pplx-embed-v2-context** (Oct 2026; 9B and 0.6B) is trained by distilling graded chunk relevance from a query-aware compressor, so it needs no gold-chunk labels and its targets are independent of chunking. It reports SOTA on ConTEB and a new Q2D-Chunk benchmark *[vendor]*. — [Eslami et al., arXiv 2610.38854](https://arxiv.org/abs/2610.38854)
- **InSeNT** (Illuin/CentraleSupélec) is in-sequence negative training plus late-chunking pooling. On ConTEB it scored 75.6 vs 52.0 for the base model, and its chunk embeddings "are more robust to suboptimal chunking strategies and larger retrieval corpus sizes". — [Conti et al., arXiv 2505.24782](https://arxiv.org/abs/2505.24782)
- **SitEmb** (ACL 2025) encodes short chunks conditioned on a broader window. The 1B SitEmb-v1 beats 7 to 8B embedders on a book-plot retrieval benchmark. — [Wu et al., arXiv 2508.01959](https://arxiv.org/abs/2508.01959)

**Multilingual and current open models**
- **MMTEB** (ICLR 2025): 500+ tasks and 250+ languages. The best *publicly available* model was multilingual-e5-large-instruct (560M), beating multi-billion-parameter LLM embedders on many subsets. — [Enevoldsen et al., arXiv 2502.13595](https://arxiv.org/abs/2502.13595); [Wang et al., arXiv 2402.05672](https://arxiv.org/abs/2402.05672)
- **MIRACL** has 18 languages and 700k native-speaker judgments, and is the standard multilingual retrieval test. — [Zhang et al., arXiv 2210.09984](https://arxiv.org/abs/2210.09984)
- **Open model sizes:**
  - Qwen3 Embedding (Jun 2025): 0.6B / 4B / 8B embedders plus matching rerankers. — [arXiv 2506.05176](https://arxiv.org/abs/2506.05176)
  - EmbeddingGemma (300M, Sep 2025): SOTA under 500M, robust to quantization and truncation. — [arXiv 2509.20354](https://arxiv.org/abs/2509.20354)
  - Gemini Embedding (Mar 2025): MMTEB SOTA (API). — [arXiv 2503.07891](https://arxiv.org/abs/2503.07891)
  - jina-embeddings-v4 (3.8B, Jun 2025): single- and multi-vector text+image, strong on tables, charts and diagrams. — [arXiv 2506.18902](https://arxiv.org/abs/2506.18902)
- The Turkish study found the top 3 embedders statistically indistinguishable and no advantage from language specialization. — [arXiv 2608.26192](https://arxiv.org/abs/2608.26192)

### Inferences
- Default representation per chunk:
  1. BM25 (or inference-free learned sparse) over prefix + chunk + generated keywords/questions;
  2. one dense vector from a strong open embedder (Qwen3-Embedding-0.6B/4B, BGE-M3 or EmbeddingGemma for CPU; multilingual-e5 or BGE-M3 when multilingual);
  3. RRF fusion, tuned (2603.23533 found untuned fusion to be a failure point);
  4. a cross-encoder reranker, validated on the domain (SciRet found an MS MARCO reranker can hurt).
- Make multi-vector (ColBERT or ColPali) an optional per-collection representation. LIMIT and the slide studies justify it for combinatorial or visual content, but the storage cost is about 10 to 100× a single vector.
- Treat contextualized chunk embedders (voyage-context-3, pplx-embed-context, InSeNT-style) as a promising *replacement* for LLM contextual enrichment, worth an A/B test. Independent confirmation beyond ConTEB is thin.
- Plan domain fine-tuning (GPL-style synthetic queries from the KB itself) as a later optimization once a labeled or LLM-judged eval set exists. Expect gains only where retrieval recall is weak.

### Gaps
- No independent benchmark of voyage-context-3 vs pplx-embed-context vs InSeNT on enterprise policy text was found.
- Learned-sparse vs BM25 evidence specifically on enterprise rule/policy corpora was not found.

---

## Q5. Indexing semi-structured knowledge (FAQs, tables, slide decks, wikis/HTML) and preserving hierarchy/breadcrumbs for navigation

### Takeaway
Semi-structured content needs **unit-specific indexing**:
- FAQs: index the question separately from the answer.
- Tables: keep the whole table or row groups with repeated headers, plus a text description or caption, plus table title and metadata.
- Slides: one unit per slide with VLM captions and/or page-image embeddings.
- Wikis and HTML: section-path breadcrumbs, with tables and infoboxes completed with their headers.

Breadcrumbs (title → section path) are the cheapest high-value signal for both retrieval and agent navigation. A deterministic heading tree also serves as a "table of contents" index that agents can browse.

### Cited Findings
- **FAQs:** combining unsupervised query-*question* similarity with a learned query-*answer* relevance model beat either alone (localgovFAQ, StackExchange) *[older: SIGIR 2019]*. — [Sakata et al., arXiv 1905.02851](https://arxiv.org/abs/1905.02851)
  - The same question-matching principle underlies generated-question indexes. — [QuIM-RAG](https://arxiv.org/abs/2501.02702); [HyPE](https://arxiv.org/abs/2607.29402)
- **Tables:**
  - Text retrievers work for tables when tables are *properly linearized*. On NQ-table, structure played "a negligible role in more than 70% of the cases", and DPR fine-tuned on linearized tables beat a table-specific retriever *[older: 2022]*. — [Wang et al., arXiv 2205.09843](https://arxiv.org/abs/2205.09843)
  - TARGET (2025): dense retrievers "far outperform" BM25 for table retrieval, unlike for text, and are sensitive to missing table titles and metadata. — [Ji et al., arXiv 2505.11545](https://arxiv.org/abs/2505.11545)
  - Multi-table questions need join-aware retrieval: up to +9.3% F1 (ACL 2024). — [Chen, Zhang, Roth, arXiv 2404.09889](https://arxiv.org/abs/2404.09889)
  - Large tables are better served by schema and cell retrieval than by chunking (TableRAG, NeurIPS 2024). — [Chen et al., arXiv 2410.04739](https://arxiv.org/abs/2410.04739)
  - Structure-aware tabular chunking for CSV and Excel encodes rows as key-value blocks in a "Row Tree" and merges greedily without overlap. On MAUD, hybrid MRR rose from 0.358 to 0.595 and BM25 Recall@1 from 0.366 to 0.754, with up to 56% fewer chunks *[author; WIP]*. — [Guttal et al. 2026, arXiv 2605.00318](https://arxiv.org/abs/2605.00318)
  - D-RAC rewrites tables "as self-contained prose statements" during multimodal Markdown conversion. — [arXiv 2609.24220](https://arxiv.org/abs/2609.24220)
  - Docling repeats table headers per chunk. — [Docling](https://docling-project.github.io/docling/concepts/chunking/)
  - Table-dependent questions drove a 33-point gap between basic and hierarchical splitting. — [arXiv 2604.04948](https://arxiv.org/abs/2604.04948)
  - Vision-guided chunking with an LMM over page batches preserves multi-page tables and procedures *[author; qualitative]*. — [Tripathi et al. 2025, arXiv 2506.16035](https://arxiv.org/abs/2506.16035)
- **Heterogeneous text, tables and graph:**
  - SAGE builds an offline chunk-level graph from metadata similarity and expands one hop from seeds: +5.7 / +8.5 recall on OTT-QA / STaRK. — [Titiya et al. 2026, arXiv 2602.16964](https://arxiv.org/abs/2602.16964)
  - NeuSym-RAG (ACL 2025) uses "multi-view chunking" with schema-based parsing into both a relational DB and a vector store for PDFs. — [Cao et al., arXiv 2505.19754](https://arxiv.org/abs/2505.19754)
- **Slide decks** (SlideVQA, 52k slides; LPM lecture slides):
  - BM25 on OCR: nDCG@10 54.3.
  - ColPali visual: 82.7, or 86.9 with the Jina reranker.
  - VLM captions (Gemma3) + BM25 + dense + BGE reranker: 83.9, at far less storage (captions dense 4.21 GB vs ColPali 12.9 GB for SlideVQA).
  - Rerankers added 7 to 14 s per query.

  — [arXiv 2509.15211](https://arxiv.org/abs/2509.15211)
  - ColPali (ICLR 2025) introduced page-image multi-vector retrieval and the ViDoRe benchmark. — [Faysse et al., arXiv 2407.01449](https://arxiv.org/abs/2407.01449)
- **HTML and wikis:**
  - HtmlRAG (WWW 2025): keeping HTML structure (headings, tables) beats plain text for RAG, with pruning to fit context. — [Tan et al., arXiv 2411.02959](https://arxiv.org/abs/2411.02959)
  - Tessera (2026) traced evidence over full English Wikipedia and found chunking separates tables and infoboxes from the headers that give them meaning. It rebuilds "fine-grained evidence units, each completed with its page title, section path, and table headers" and decouples the indexed unit from the read unit. — [arXiv 2610.37080](https://arxiv.org/abs/2610.37080)
  - SPIRE (2026) represents candidates as addressable sub-documents (paths and path sets) with "global contextualization" (titles, headers, list/table scaffolding) and local expansion. — [arXiv 2604.20849](https://arxiv.org/abs/2604.20849)
- **Breadcrumb and hierarchy evidence:**
  - Title-chain prefixes: +23.8% MRR@5 on a production Markdown KB. — [arXiv 2608.00824](https://arxiv.org/abs/2608.00824)
  - HiQA cascading section-path metadata. — [arXiv 2402.01767](https://arxiv.org/abs/2402.01767)
  - "Enriched (Title)" is a low-cost improvement. — [arXiv 2608.16586](https://arxiv.org/abs/2608.16586)
  - A free section-path prefix ≈ LLM enrichment under strong retrievers. — [arXiv 2603.23533](https://arxiv.org/abs/2603.23533)
- **Navigation indexes:**
  - PageIndex (VectifyAI, open source) builds a table-of-contents tree (title, node ID, page range, summary) and lets an LLM reason over it in context ("vectorless"). Its FinanceBench 98.7% claim is vendor-reported and unreplicated *[vendor]*. — [PageIndex GitHub](https://github.com/VectifyAI/PageIndex)
  - NavTree shows a deterministic tree used for navigation matches LLM-summary trees. — [arXiv 2610.06902](https://arxiv.org/abs/2610.06902)

### Inferences
- **Per-unit index rules:**
  - FAQ: question text → dense and sparse fields; answer → separate field and vector. Score as max(q-q, q-a) or fused.
  - Table: one record per table (caption + title + header + generated description) plus row-group chunks with repeated headers. Link to the structured table in the typed DB from the earlier track.
  - Slide: one record per slide (OCR text + VLM caption + optional page-image multi-vector). Deck title and section as breadcrumb.
  - Wiki/HTML: section-path breadcrumb, infobox → key-value record.
- Persist the **heading tree as first-class data** (node id, parent id, path, page range, optional summary). It serves three purposes at once:
  - the breadcrumb prefix for embedding;
  - the parent for small-to-big expansion;
  - a browsable table of contents that agents can traverse (`list_children`, `get_section`).

  This captures the "navigation" benefit of RAPTOR and PageIndex without LLM summaries.

### Gaps
- No rigorous FAQ-specific study with modern embedders comparing question-only vs question+answer indexing was found. WebFAQ (2502.20936, 2602.17327) was seen only by title.
- Evidence for indexing scanned diagrams (P&IDs, flowcharts) remains weak. Text methods fail (2603.24556), and visual methods are untested on these.

---

## Q6. Cost/latency of each enrichment and the most effective combination for a knowledge base (recommended indexing design)

### Takeaway
Most of the achievable gain comes from cheap or deterministic steps:
- structure-led chunks with breadcrumb prefixes;
- hybrid BM25 + strong dense with tuned fusion;
- a reranker;
- parent expansion.

LLM steps should be added in order of cost per document: per-document summary, then per-chunk keywords/questions, then full contextual retrieval or summary trees. Each step must pass an evaluation gate on the KB's own agent queries.

### Cited Findings (cost and latency data points)
| Technique | Index-time cost | Query-time cost | Source |
|---|---|---|---|
| Token/recursive/structure chunking | ~0; paragraph splitting ~1,854 docs/s | none | [2602.16974](https://arxiv.org/abs/2602.16974); [2608.16586](https://arxiv.org/abs/2608.16586) |
| Semantic (embedding-breakpoint) chunking | extra embedding pass; "much slower to index" | none | [2608.16586](https://arxiv.org/abs/2608.16586); [2410.13070](https://arxiv.org/abs/2410.13070) |
| LumberChunker (LLM) | ~1.11 docs/s (Gemini-2.5-Flash) | none | [2602.16974](https://arxiv.org/abs/2602.16974) |
| Agentic chunking vs ID-planned chunking | D-RAC −77.8% to −85.6% cost vs frontier agentic chunking | none | [2609.24220](https://arxiv.org/abs/2609.24220) |
| Anthropic contextual retrieval | ~$1.02 per million document tokens with caching (Haiku, 2024); 5.8 to 8.7× the input tokens of single-call enrichment; ~1.9 s per document; 0.26 to 5.26 docs/s on a local 80B model | none (plus reranker if used) | [Anthropic](https://www.anthropic.com/news/contextual-retrieval); [2603.23533](https://arxiv.org/abs/2603.23533); [2505.24782](https://arxiv.org/abs/2505.24782); [2608.16586](https://arxiv.org/abs/2608.16586) |
| Per-document summary (SAC / Enriched-Summary) | 1 LLM call per document | none | [2510.06999](https://arxiv.org/abs/2510.06999); [2608.16586](https://arxiv.org/abs/2608.16586) |
| Generated questions (QuOTE / HyPE) | 1 LLM call per chunk; build 170 s vs 10 s (QuOTE SQuAD subset); vectors × number of questions | ~+33 ms (dedup) | [2502.10976](https://arxiv.org/abs/2502.10976) |
| HyDE (query time) | none | +~1.2 s per query (LLM call) | [2502.10976](https://arxiv.org/abs/2502.10976) |
| Propositions | ~500 GPU-hours for Wikipedia; 6× vectors (~768 GB flat) | larger index | [2312.06648](https://arxiv.org/abs/2312.06648) |
| RAPTOR tree | LLM summary per cluster, linear in length; 4% of sampled nodes hallucinated | larger pool | [2401.18059](https://arxiv.org/abs/2401.18059) |
| Late chunking | one long-context forward pass; high indexing RAM | none | [2608.16586](https://arxiv.org/abs/2608.16586) |
| Contextualized embedder (voyage-context-3) | $0.18 per million tokens (list) | none | [LiteLLM](https://docs.litellm.ai/docs/providers/voyage) |
| Trained contextual embedder (InSeNT) | ~15 ms per document | none | [2505.24782](https://arxiv.org/abs/2505.24782) |
| Multi-vector (ColPali, slides) | 12.9 GB vs 0.11 GB single-vector DSE for 52k slides | MaxSim; PLAID tens of ms on GPU | [2509.15211](https://arxiv.org/abs/2509.15211); [2205.09707](https://arxiv.org/abs/2205.09707) |
| Cross-encoder / visual reranker | none | 7 to 14 s per query on slide sets (large rerankers); essential for consistent gains | [2509.15211](https://arxiv.org/abs/2509.15211); [2504.19754](https://arxiv.org/abs/2504.19754) |
| Filtered doc2query | generation + filter | −23% query time and −33% index vs unfiltered | [2301.03266](https://arxiv.org/abs/2301.03266) |

- Effectiveness ranking evidence:
  - "Upgrade the retriever first, chunk at headers, and enrich mainly for lexical retrieval." — [arXiv 2603.23533](https://arxiv.org/abs/2603.23533)
  - "Simple methods are strong defaults", and chunking is "a multi-objective design choice". — [arXiv 2608.16586](https://arxiv.org/abs/2608.16586)
  - Embedding quality mattered more than the chunker. — [arXiv 2410.13070](https://arxiv.org/abs/2410.13070)
  - Data preparation (hierarchy-aware splitting + metadata) was "the dominant factor". — [arXiv 2604.04948](https://arxiv.org/abs/2604.04948)
  - Hybrid + semantic reranker beat vector-only by 16 NDCG@3 points. — [Microsoft](https://techcommunity.microsoft.com/t5/azure-ai-foundry-blog/azure-ai-search-outperforming-vector-search-with-hybrid/ba-p/3929167)
  - Fine-tuning roughly doubled FinanceBench recall for a small embedder. — [Databricks](https://www.databricks.com/blog/improving-retrieval-and-rag-embedding-model-finetuning)

### Inferences: recommended indexing design for the toolkit
1. **Canonical tree first.** Keep the parser's document tree (from the earlier parsing track) as the source of truth. Each node has a stable content-hash ID, type (section, paragraph, list/steps, table, figure, FAQ pair, slide), heading path, page/bbox provenance, ACL tags and version. Chunks are a derived, re-runnable view.
2. **Chunking view (deterministic):**
   - Header-led segmentation with atomic tables, lists, procedure steps and FAQ pairs.
   - Merge peers under the same heading to about 256 to 512 tokens (tokenizer of the chosen embedder). Split oversized nodes recursively at sentence boundaries. No overlap by default.
   - Page-level units for slide decks and visually dense PDFs.
   - Content-defined or recursive boundaries to limit re-embedding on edits.
3. **Free enrichment (always on):**
   - Breadcrumb prefix "Doc title › Section › Subsection" plus doc type and date or version, used for both BM25 and dense input.
   - Metadata fields (source, owner, effective date, jurisdiction, product, language) stored as filterable fields, not in reader text.
4. **Cheap LLM enrichment (default on for curated KBs, gated by eval):**
   - (a) One call per document produces a 1 to 2 sentence summary (prepended to chunk embedding input), a document-level keyword/entity/acronym list, and a topic label.
   - (b) One call per chunk (all fields at once) produces keywords, entities, acronyms and 3 to 10 likely questions. Questions are stored as separate vectors pointing to the chunk (dedup at query time), with keywords in a sparse field. Filter hallucinated questions with a relevance check.
   - Use a small (7B to 30B class) or cheap API model. Keep generator and prompt version in lineage.
5. **Representations per chunk:** BM25 (or inference-free SPLADE); one dense vector (strong open model, multilingual where needed); question vectors; optional summary vector at section and document level; optional multi-vector (ColBERT/ColPali) per collection for visual or exact-combination content.
6. **Hierarchy index:**
   - Store section and document nodes with optional summaries, enabling small-to-big expansion (return the parent section or page) and agent tools for browsing the table of contents.
   - Build abstractive RAPTOR-style trees only for collections whose eval shows a gain on overview questions.
7. **Query-time defaults** (detail in other tracks): hybrid with tuned RRF, a cross-encoder reranker validated on domain data, parent expansion, and separating index-side enrichment from the text returned to the agent.
8. **Evaluation gates:**
   - Build a synthetic plus human-verified query set per KB, covering factoid, procedure-lookup, policy-applicability, overview and keyword/ID queries.
   - Report recall@k, nDCG, section coverage, index cost (LLM tokens, $) and update cost.
   - Enable each LLM step only if it beats the free baseline under the chosen retriever.
9. **Upgrade path:** A/B a contextualized chunk embedder (voyage-context-3 or pplx-embed-context-class) against "prefix + summary" enrichment. GPL-style domain fine-tuning once the eval set exists.

### Gaps
- I found no study that measures this full stack end to end on an SOP/policy KB with agent-style queries. The design is an inference from component-level evidence.
- Dollar costs for per-chunk question generation at scale (for example 1M chunks) are not reported in the papers. They must be estimated from token counts and current model prices.
- Most 2026 papers are single-author or small-team arXiv preprints without peer review (2603.23533 and 2608.16586 are the most rigorous). Weight their numbers accordingly.
