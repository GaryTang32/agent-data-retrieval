# Where LLM search result quality comes from: query, ranking, selection, freshness and adversarial pressure (track 05)

Scope: the quality mechanisms in the query → ranking → selection chain when an LLM uses a web search engine, and what carries over to private corpora. Search backends, the deep-research loop, coding agents and page reading/citation are covered by other tracks. Research date: November 2026. Many 2026 items are arXiv preprints that have not been peer reviewed, and they are labelled as such. "Vendor" marks studies run by companies selling SEO or GEO tools.

Short answer to the user's framing: no LLM product turns the internet into a local vector DB. Systems like ChatGPT search, Codex web search, Perplexity and Google AI Mode/AI Overviews send many LLM-written sub-queries to a web-scale index that already exists. That index has crawl, freshness tiers, link analysis, spam demotion, and ranking learned from clicks and human ratings, built over about 25 years. The LLM then reranks, selects, reads and cites a small handful of results. Most of the quality is inherited from the search engine. The LLM adds query formulation, choosing among results, and synthesis, and it adds new failure modes of its own.

---

## 1. Ranking signals in web search, and why they give LLMs a large head start over a raw vector index

### Takeaway
Web ranking quality rests on evidence from outside the page. Link analysis and anchor text are "latent human judgment" (Kleinberg). Memorised click logs (NavBoost, Glue, QBST) cover 13 months of queries. Neural "generalization" rankers (RankBrain, DeepRank/BERT, RankEmbed, MUM) were trained on that user data and fill holes in it. Spam and quality systems are tuned against human-rater evaluations. When an LLM calls a search API it inherits all of this. A raw vector index has none of it: it ranks only by how similar a text chunk is to the query.

### Cited Findings
**Link analysis and anchor text (1998–1999, foundational)**
- Brin & Page (1998) saw the 1997 web problem as one of ranking, not coverage: "the completeness of the index is not the only factor in the quality of search results. 'Junk results' often wash out any results that a user is interested in." Google used "link structure and link text" for "relevance judgments and quality filtering." — [Brin & Page 1998, The Anatomy of a Large-Scale Hypertextual Web Search Engine](https://www.cs.uoi.gr/~tjortjis/google-white.txt)
- PageRank is described as a model of user behaviour, a "random surfer" who keeps clicking links and occasionally jumps to a random page with damping probability d. — [Brin & Page 1998](https://www.cs.uoi.gr/~tjortjis/google-white.txt)
- Anchor text is attached to the page a link points to, because "anchors often provide more accurate descriptions of web pages than the pages themselves" and they cover documents a text indexer cannot read, such as images, programs and databases. — [Brin & Page 1998](https://www.cs.uoi.gr/~tjortjis/google-white.txt)
- Brin & Page warned that "advertising funded search engines will be inherently biased towards the advertisers and away from the needs of the consumers." This is an early statement of the incentive problem that GEO now raises for LLM engines. — [Brin & Page 1998](https://www.cs.uoi.gr/~tjortjis/google-white.txt)
- Kleinberg (HITS, JACM 1999) named the "Abundance Problem": for broad queries the number of relevant pages "is far too large for a human user to digest", so you need the most "authoritative" ones. He argued "there is no purely endogenous measure of the page that would allow one to properly assess its authority". For example, www.harvard.edu does not use "Harvard" most often, and Honda's homepage does not say "automobile manufacturers." His answer is that "hyperlinks encode a considerable amount of latent human judgment", because a link from p to q "has in some measure conferred authority on q." Authority is computed from mutually reinforcing hubs and authorities, which relates to eigenvectors of the link matrix. — [Kleinberg 1999, Authoritative Sources in a Hyperlinked Environment](https://www.di.ens.fr/~busic/mar/ref/auth.pdf)

**Learning to rank (2010)**
- LambdaMART is "the boosted tree version of LambdaRank, which is based on RankNet". An ensemble of LambdaMART rankers won Track 1 of the 2010 Yahoo! Learning to Rank Challenge. This is the gradient-boosted framework for combining hundreds of features that dominated production ranking before neural rankers. — [Burges 2010, MSR-TR-2010-82](https://www.microsoft.com/en-us/research/publication/from-ranknet-to-lambdarank-to-lambdamart-an-overview/)

**Click and behavioural signals: DOJ v. Google (sworn testimony and court findings, 2023–2024)**
- The court found that Navboost "pairs queries and documents through memorizing user click data". It lets Google "remember which documents users clicked after entering a query" and spot when one document is clicked for many queries. Glue is a "relative" signal. Navboost was trained on 18 months of data before 2017 and 13 months since. "Thirteen months of user data acquired by Google is equivalent to over 17 years of data on Bing." (Findings of Fact ¶96, citing testimony from Lehman, Nayak and Giannandrea.) — [U.S. v. Google, Memorandum Opinion, Aug 5 2024 (Mehta, J.)](https://storage.courtlistener.com/recap/gov.uscourts.dcd.223205/gov.uscourts.dcd.223205.1033.0_3.pdf)
- QBST (Query-based Salient Terms) finds words that "should appear prominently on web pages that are relevant to that query." It is a "memorization system" trained on about 13 months of user data (¶95). — [Mehta opinion 2024](https://storage.courtlistener.com/recap/gov.uscourts.dcd.223205/gov.uscourts.dcd.223205.1033.0_3.pdf)
- The newer "generalization" systems are RankBrain, DeepRank, RankEmbed, RankBERT and MUM. They "may not be so good at memorizing facts, but they're really good at understanding language", are "designed to fill holes in [click] data", and are still trained on user data, at about 1 billion examples against up to 1 trillion for older signals (¶97–98). An internal Google document says: "Learning from this user feedback is perhaps the central way that web ranking has improved for 15 years." — [Mehta opinion 2024](https://storage.courtlistener.com/recap/gov.uscourts.dcd.223205/gov.uscourts.dcd.223205.1033.0_3.pdf)
- LLM signals "did not replace Navboost and QBST". Per Nayak, LLMs are "additional signals that get balanced both against each other as well as against other signals". Navboost can beat LLMs on aspects such as freshness (¶102–103). Generative AI has "not (or at least, not yet) eliminated or materially reduced the need for user data". Neeva's Ramaswamy testified that ranking "still benefits enormously from query click information" (¶115). — [Mehta opinion 2024](https://storage.courtlistener.com/recap/gov.uscourts.dcd.223205/gov.uscourts.dcd.223205.1033.0_3.pdf)
- User data also drives query understanding. Google learns spelling correction and synonym reformulation from how users re-type queries (¶93). Crawl frequency and index tiers are set by how fresh each page needs to be; "fresher tiers are rebuilt more frequently" (¶91–92). Google receives 9 times more queries than all rivals combined, and 19 times more on mobile. — [Mehta opinion 2024](https://storage.courtlistener.com/recap/gov.uscourts.dcd.223205/gov.uscourts.dcd.223205.1033.0_3.pdf)
- The September 2, 2025 remedies ruling orders Google to "make available to Qualified Competitors certain search index and user-interaction data" (not ads data) and to offer search and search-text-ads syndication "largely on ordinary commercial terms". This is a legal recognition that index and click data are the moat. — [Search Engine Roundtable, Sep 2 2025](https://www.seroundtable.com/google-monopoly-ruling-remedy-40041.html)

**2024 Content Warehouse API leak (authentic documents, uncertain use)**
- 2,596 modules with 14,014 attributes were committed to GitHub by a bot in March 2024, and Google confirmed authenticity on May 29, 2024. They reference NavBoost click metrics ("goodClicks", "badClicks"), Chrome-derived attributes, a site-level "siteAuthority", "hostAge", and topical focus scores (siteFocusScore, siteRadius). Caveats: there are no weights and no code, and it is unclear which attributes are live. — [Wikipedia: 2024 Google Search documentation leak](https://en.wikipedia.org/wiki/2024_Google_Search_documentation_leak)
- Fishkin's analysis notes "lastLongestClicks", flags that suggest whitelists ("isElectionAuthority", "isCovidLocalAuthority", a "Good Quality Travel Sites" module), and EWOK human-rater relevance ratings "typically only populated in the evaluation pipelines". He also cautions that "It's not quite proof. It's a strong indication." This is reporting and interpretation, not a Google statement. — [SparkToro, May 28 2024](https://sparktoro.com/blog/an-anonymous-source-shared-thousands-of-leaked-google-search-api-documents-with-me-everyone-in-seo-should-see-them/)

**Neural ranking in production (2019 onward)**
- Google BERT (Oct 25, 2019): it helps with "one in 10 searches in the U.S. in English", and it was the first time Google served search results on Cloud TPUs. Example: "2019 brazil traveler to usa need a visa", where "to" now matters. — [Google blog, Nayak 2019](https://blog.google/products/search/search-language-understanding-bert/)
- Bing (Nov 18, 2019): transformer models "are now applied to every Bing search query globally", using 2,000+ Azure GPU VMs for over 1M BERT inferences per second. Microsoft called it the "largest quality improvements … in the past year", without giving metrics (vendor claim). — [Azure blog, Zhu 2019](https://azure.microsoft.com/en-us/blog/bing-delivers-its-largest-improvement-in-search-experience-using-azure-gpus/)
- In research, a BERT cross-encoder reranker topped MS MARCO with +27% relative MRR@10 over the previous state of the art (2019). — [Nogueira & Cho 2019](https://arxiv.org/abs/1901.04085)
- Google's public list of ranking systems includes link analysis/PageRank, "query deserves freshness" systems, deduplication, site diversity (generally at most two results per site), original-content systems, reliable-information systems, the reviews system, passage ranking, RankBrain, neural matching, BERT, MUM (used for specific tasks, "not general ranking"), and SpamBrain. Panda, Penguin and the helpful content system have been folded into core ranking. — [Google Search Central, ranking systems guide](https://developers.google.com/search/docs/appearance/ranking-systems-guide)

**Quality raters and E-E-A-T**
- E-E-A-T means Experience, Expertise, Authoritativeness, Trustworthiness ("experience" was added Dec 2022). Raters' scores "don't directly influence ranking". They are used to evaluate ranking systems. — [Google Search Central blog, Dec 15 2022](https://developers.google.com/search/blog/2022/12/google-raters-guidelines-e-e-a-t)
- Bing uses LLMs as relevance labellers. Prompts tuned on first-party searcher feedback gave labels "as good as human labellers" and better than third-party workers "for a fraction of the cost", and those labels "let us train notably better rankers". — [Thomas, Spielman, Craswell, Mitra 2023 (SIGIR 2024)](https://arxiv.org/abs/2309.10621); open reproduction used in TREC 2024 RAG: [UMBRELA 2024](https://arxiv.org/abs/2406.06519)

**Spam fighting**
- With the March 2024 core update, Google said it would reduce "low-quality, unoriginal content in search results by 40%". On Apr 26, 2024 it reported "45% less". The policy now covers scaled content "whether automation, humans or a combination are involved." — [Google blog, Tucker, Mar 5 2024](https://blog.google/products/search/google-search-update-march-2024/)
- New spam policies cover scaled content abuse, site reputation abuse (third-party pages on a host "without close oversight") and expired domain abuse. — [Google Search Central blog, Mar 5 2024](https://developers.google.com/search/blog/2024/03/core-update-spam-policies)

**What carries into AI search**
- To be a supporting link in AI Overviews or AI Mode, a page must be "indexed and eligible to be shown in Google Search with a snippet". "All existing SEO fundamentals continue to be worthwhile". There are no special files or markup ("no … AI text files"). Both features use "query fan-out … issuing multiple related searches across subtopics and data sources." — [Google Search Central, AI features and your website](https://developers.google.com/search/docs/appearance/ai-features)
- BEIR (2021): over 18 zero-shot datasets, "BM25 is a robust baseline". Reranking and late-interaction models do best, while dense retrievers "often underperform". A bare embedding index is not a strong ranker on its own. — [Thakur et al. 2021 (NeurIPS D&B)](https://arxiv.org/abs/2104.08663)

### Inferences
- The head start is not "the web is big". It is that the backend's rank-1 to rank-10 already reflects (a) other people's links and anchors, (b) billions of past searchers' satisfied clicks for that query, (c) spam demotions, and (d) rater-tuned quality models. An LLM calling a search API gets these for free. A raw vector DB over the same pages would have only semantic similarity, which BEIR shows is a weak signal used alone, and which [source-bias work](https://arxiv.org/abs/2310.20501) shows is easy to game with LLM-written text (see §5).
- Kleinberg's point that page text cannot certify its own authority is the key structural argument for a private KB: authority and usefulness have to come from evidence outside the document.

### Gaps
- No public, quantitative breakdown of how much each signal (links, clicks, neural, quality) contributes to Google or Bing ranking today. The trial and the leak give existence and relative importance, not weights.
- Which backend (Bing, Google, in-house) each LLM product uses today, and with what ranking, belongs to the search-backends track and was not verified here.

---

## 2. LLM-side query skills: rewriting, expansion, fan-out, decomposition and learned search strategies

### Takeaway
LLMs add value before retrieval by rewriting vague prompts into several targeted keyword queries. Measured gains are real but conditional: pseudo-document expansion helps weak or lexical retrievers and can hurt strong ones. Production AI search now relies on multi-query fan-out, from dozens of queries to "hundreds" for Deep Search. RL-trained query policies (Search-R1, DeepRetrieval) beat prompting. The sub-queries an LLM writes, which often differ from what a human would type, now largely decide which pages can be cited at all.

### Cited Findings
- **Query2doc (2023):** few-shot LLM pseudo-documents appended to the query improve BM25 by 3–15% on MS MARCO/TREC DL without fine-tuning, and also help dense retrievers. — [Wang, Yang, Wei 2023](https://arxiv.org/abs/2303.07678)
- **HyDE (2022):** the LLM writes a hypothetical answer document, which is embedded with Contriever. The encoder's "dense bottleneck" filters out false details. It beats unsupervised Contriever and is comparable to fine-tuned retrievers across web search, QA and fact verification. — [Gao, Ma, Lin, Callan 2022](https://arxiv.org/abs/2212.10496)
- **LLM query expansion prompts (Google Research, 2023):** chain-of-thought prompts work best because they "break queries down step-by-step" and produce many related terms. They beat classic pseudo-relevance feedback on MS MARCO and BEIR. — [Jagerman et al. 2023](https://arxiv.org/abs/2305.03653)
- **Counter-evidence (2023):** across 11 expansion methods, 12 datasets and 24 retrievers there is "a strong negative correlation between retriever performance and gains from expansion". Expansion helps weak models and "generally harms stronger models" by adding noise. The recipe: use it for weak retrievers or out-of-domain formats only. — [Weller et al. 2023 (EACL Findings 2024)](https://arxiv.org/abs/2309.08541)
- **Rewrite-Retrieve-Read (2023):** the LLM writes the query, a web search engine retrieves, and a small rewriter is trained by RL from the reader LLM's feedback, with consistent gains on open-domain and multiple-choice QA. — [Ma et al. 2023 (EMNLP 2023)](https://arxiv.org/abs/2305.14283)
- **RaFe (2024):** trains query rewriting with no annotations, using a public reranker's scores as the reward. — [Mao et al. 2024](https://arxiv.org/abs/2405.14431)
- **Production query rewriting (Taobao, 2023):** the BEQUE LLM rewriter for long-tail queries was aligned with the offline search system's partial orders. It has been deployed since Oct 2023, and A/B tests show GMV and transaction gains for long-tail queries (author/company-reported). — [Peng et al. 2023](https://arxiv.org/abs/2311.03758)
- **Decomposition (Self-Ask, 2022):** measures a "compositionality gap": models answer the sub-questions but fail the composed question, and this does not shrink with scale. Explicit follow-up questions with a search engine plugged in improve accuracy. — [Press et al. 2022](https://arxiv.org/abs/2210.03350)
- **Multi-query fusion (RAG-Fusion, 2024):** several generated queries are fused with reciprocal rank fusion. Answers were more comprehensive (single-company manual evaluation, Infineon), but some "strayed off topic when the generated queries' relevance … is insufficient." — [Rackauckas 2024](https://arxiv.org/abs/2402.03367)
- **Google AI Mode fan-out (official, May 20 2025):** AI Mode is "breaking down your question into subtopics and issuing a multitude of queries simultaneously". Deep Search "can issue hundreds of searches." Google gives no per-query counts. — [Google blog, Reid, May 2025](https://blog.google/products/search/google-search-ai-mode-update/); also [Google Search Central](https://developers.google.com/search/docs/appearance/ai-features)
- **The sub-queries decide citation (2026, preprint, independent academics):** 158,099 answers with 468,037 citations were collected over 90 days. "Every page ChatGPT cites is one its own search retrieved". Which pages that search returns, "for sub-queries the model rewrites on every answer and that rarely coincide with Google's or Bing's results", explains 32% of citation variance, against 2.8% for page properties. ChatGPT also "writes brands it knows into its searches". — [Chen & Koudas 2026](https://arxiv.org/abs/2610.15033)
- **Learned search strategies (RL):** Search-R1 trains the LLM with outcome-only reward to issue multiple queries during reasoning (retrieved-token masking), improving 41% (Qwen2.5-7B) and 20% (3B) over RAG baselines on seven QA sets. — [Jin et al. 2025](https://arxiv.org/abs/2503.09516). DeepRetrieval RL-trains query generation against real search engines using retrieval metrics as reward, reaching 65.07% recall on publication search vs a prior state of the art of 24.68%. With 3B parameters it beats GPT-4o and Claude-3.5-Sonnet on 11 of 13 datasets (author-reported). — [Jiang et al. 2025](https://arxiv.org/abs/2503.00223)
- **WebGPT (2021):** GPT-3 was taught by imitation and human feedback to issue search commands, open results and quote references. Its answers were preferred 56% of the time over human demonstrators. It was an early example of learned query and selection behaviour. — [Nakano et al. 2021](https://arxiv.org/abs/2112.09332)
- **Query understanding inside the engine:** before any LLM sees results, Google already reformulates queries with spelling and synonym models learned from user re-typing (court finding ¶93). — [Mehta opinion 2024](https://storage.courtlistener.com/recap/gov.uscourts.dcd.223205/gov.uscourts.dcd.223205.1033.0_3.pdf)

### Inferences
- Fan-out pays off because each narrow sub-query lets the search engine's own ranking work on a well-posed short query. The LLM turns one long conversational prompt into many head-like queries the engine handles well. This is a strong reason a private KB should expose a keyword/BM25 or fielded search tool that an agent can call many times, not a single embedding lookup.
- Since stronger retrievers gain less from expansion (Weller), the right amount of LLM query rewriting depends on how good the underlying index is. For a typed, well-fielded KB, structured filters and decomposition likely matter more than HyDE-style expansion.

### Gaps
- No vendor has published fan-out counts, rewriting prompts, or ablations for ChatGPT search, Claude web search or Codex. Measured effects come from academic setups or reverse engineering.
- No rigorous public study was found measuring the effect of search operators (site:, quotes, date filters) on LLM agent outcomes. This is anecdotal only.

---

## 3. Selection and reranking: LLM rerankers, choosing what to open, credibility, domain preferences and diversity

### Takeaway
LLMs are strong zero-shot rerankers (listwise RankGPT, pairwise PRP, setwise), and open models now match GPT-4. They have position and recency biases, though, and they judge credibility mostly by topical relevance and institutional cues that repetition can flip. In practice, AI engines pick a concentrated, platform-specific set of domains: Wikipedia, Reddit, YouTube, LinkedIn and "earned media" generally. Their citations overlap only partly with the engine's own top results.

### Cited Findings
**LLM rerankers**
- RankGPT (2023): instructed ChatGPT/GPT-4 doing listwise permutation reranking are "competitive, even superior" to supervised rerankers. NovelEval was built to address contamination concerns. A distilled 440M model beats a 3B supervised model on BEIR. — [Sun et al. 2023 (EMNLP 2023)](https://arxiv.org/abs/2304.09542)
- PRP pairwise prompting (2023): Flan-UL2 (20B) matches GPT-4-based listwise reranking on TREC-DL and beats ChatGPT by 4.2% NDCG@10 on BEIR. Linear-complexity variants exist. — [Qin et al. 2023](https://arxiv.org/abs/2306.17563)
- Setwise (2023): pointwise is efficient but weak, and pairwise is effective but expensive. Setwise cuts LLM calls and tokens while keeping effectiveness. — [Zhuang et al. 2023 (SIGIR 2024)](https://arxiv.org/abs/2310.09497)
- Open listwise rerankers: RankVicuna (7B) comes close to GPT-3.5 ([Pradeep et al. 2023](https://arxiv.org/abs/2309.15088)). RankZephyr matches or exceeds GPT-4 and is robust to initial ordering ([Pradeep et al. 2023](https://arxiv.org/abs/2312.02724)).
- Reasoning rerankers: Rank1 distils over 600k R1 reasoning traces into a reranker using test-time compute, with gains on reasoning and instruction-following retrieval and explainable chains. — [Weller et al. 2025](https://arxiv.org/abs/2502.18418)
- Position bias: listwise LLM ranking depends on input order. Permutation self-consistency (shuffle and aggregate) improves results by 7–18% (GPT-3.5) and 8–16% (LLaMA-2 70B). — [Tang et al. 2023](https://arxiv.org/abs/2310.07712). Live ChatGPT is also order-sensitive: the Top-1 rate for the same GEO strategy was 73.8% vs 93.8% under two opposite fixed URL orders (2026 preprint). — [LIVE-GEO, Kong et al. 2026](https://arxiv.org/abs/2611.01126)

**Deciding whether results are good enough, and what to open**
- Corrective RAG: a lightweight retrieval evaluator scores the retrieved set and triggers actions such as falling back to web search, plus decompose-then-recompose filtering of documents. — [Yan et al. 2024](https://arxiv.org/abs/2401.15884)
- Models often answer from search snippets without opening the pages. This is "associated with higher rates of outdated answers and unfaithful citations" (2026 preprint, controlled facts that changed after the training cutoff). — [Walters, Chen, Toni 2026](https://arxiv.org/abs/2610.21731)

**Credibility judgment**
- On ConflictingQA, LLMs "rely heavily on the relevance of a website to the query, while largely ignoring stylistic features that humans find important such as whether a text contains scientific references or is written with a neutral tone." — [Wan, Wallace, Klein 2024 (ACL 2024)](https://arxiv.org/abs/2402.11782)
- Across 13 open-weight LLMs, models prefer institutionally corroborated sources (government, newspapers) over people and social media. These preferences "can be reversed by simply repeating information from less credible sources" (2026). — [Schuster, Gautam, Markert 2026](https://arxiv.org/abs/2601.03746)
- Source criticism as a task: "media background checks" (6,709, derived from Media Bias/Fact Check) help both humans and RAG models. — [Schlichtkrull 2024](https://arxiv.org/abs/2409.00781)
- Weighting retrieval by a source-type reliability prior, score = sim × λ(source), raised P@5 from 0.48 to 0.72 on a small health corpus (120 docs, 2026 preprint, small and controlled). — [Koganti & Garrido-Lestache 2026](https://arxiv.org/abs/2607.22584)

**Which domains AI search cites (mixed independent and vendor evidence)**
- Independent academic work (2025 preprint): AI search shows a "systematic and overwhelming bias towards Earned media". For example, in US consumer electronics AI search cited 92.1% earned media, while Google showed a mix with 32.9% brand and 15.4% social. Unbranded cola prompts named major brands 62.2% of the time. Wikipedia was about 19.7% of ChatGPT citations. Top-10 domain overlap with Google ranged from about 0% to over 50% by vertical. — [Chen, Wang, Chen, Koudas 2025](https://arxiv.org/abs/2509.08919)
- Vendor (Ahrefs, June 2025, about 78.6M queries): Wikipedia is top on all three platforms (ChatGPT 16.3%, Perplexity 12.5%, AI Overviews 8.4%). YouTube is 16.1% on Perplexity. Reddit (7.4%) and Quora (3.6%) are prominent only in AI Overviews. — [Ahrefs 2025](https://ahrefs.com/blog/top-10-most-cited-domains-ai-assistants)
- Vendor (Semrush, Jul–Oct 2025, about 230k prompts, over 100M citations): ChatGPT responses citing Reddit fell from about 60% to about 10%, and Wikipedia from about 55% to under 20%, in mid-September 2025. Google AI Mode leans on LinkedIn (about 15%), YouTube and Google-owned pages. The cause is unknown. — [Semrush, Nov 2025](https://www.semrush.com/blog/most-cited-domains-ai/)
- Across 10 AI-search platforms (17,211 citations, 6,356 domains), the top-20 domains capture 20.5–70.8% of each platform's citations (2026 preprint). — [Liu et al. 2026](https://arxiv.org/abs/2610.11932)
- AI Overviews: cited domains are more credible than the co-displayed first-page results, yet "nearly 30% do not appear in those results at all", which indicates "a source selection mechanism distinct from Google's ranking algorithm" (55,393 queries, Mar–Apr 2026, preprint). — [Xu, Iqbal, Montgomery 2026](https://arxiv.org/abs/2605.14021). Contradicting evidence: for health questions, AIOs cited only 44.4% of the top-5 organic results and "overrepresented commercial health publishers (e.g., WebMD, Healthline)", scoring lower on 4 of 6 credibility criteria (2026 preprint). — [Agnoli et al. 2026](https://arxiv.org/abs/2610.39339)
- Sources retrieved by Google search, AIO and Gemini differ greatly (Jaccard < 0.2). Generative engines more often retrieve Google-owned content, and sites blocking Google's AI crawler are less likely to be retrieved by AIOs (11,500 queries, 2026 preprint). — [Grossman et al. 2026](https://arxiv.org/abs/2604.27790)
- Health: over 75% of ChatGPT (5.2 Pro) health citations were established institutions such as Mayo Clinic, Cleveland Clinic, Wikipedia, NHS and PubMed (615 sources, 2026). — [Jacques et al. 2026](https://arxiv.org/abs/2601.17109)
- Chinese generative search: content fit, the number of sources a claim appears in, and semantic role predicted surfacing. The Baidu composite quality score "was not the leading predictor" (160,860 citation records, 2026 preprint). — [Zhen et al. 2026](https://arxiv.org/abs/2607.15771)

**Diversity**
- Google's classic stack enforces diversity explicitly: "site diversity" (generally at most two results from one site) and deduplication. — [Google ranking systems guide](https://developers.google.com/search/docs/appearance/ranking-systems-guide)
- Google says fan-out lets AI features "display a wider and more diverse set of helpful links." — [Google Search Central](https://developers.google.com/search/docs/appearance/ai-features). Independent audits nonetheless find citations concentrated in a few repeated domains plus a long tail of minimally cited ones. — [Allaham & Diakopoulos 2026](https://arxiv.org/abs/2605.23684); [Liu et al. 2026](https://arxiv.org/abs/2610.11932)

### Inferences
- LLM selection adds a second ranking layer on top of the engine's ranking. That layer has its own priors: Wikipedia and earned media, brands it already knows, institutional cues, recency, and position. This layer can raise source quality (the AIO credibility result) or lower it (the AIO health result). The evidence is mixed and differs by domain.
- LLM credibility judgment is shallow (relevance-driven, flipped by repetition). The authority signal has to come from metadata or priors supplied to the model, such as the domain, the owner, or a verified flag. It should not be left for the model to infer from the prose.

### Gaps
- No vendor documents its citation-selection policy or how much it weights the search engine's rank against its own reranking.
- Domain-share studies are mostly vendor-run, use different metrics (share of responses vs share of citations), and change month to month. Treat them as directional only.

---

## 4. Freshness and recency handling for time-sensitive queries, and temporal reasoning failures

### Takeaway
Web engines treat freshness as an infrastructure and ranking problem: index tiers rebuilt at different rates, "query deserves freshness" classifiers, and click memorisation that reacts quickly. LLM layers often fail at temporal reasoning. They answer from snippets, accept outdated pages that are still online, and are swayed by date stamps, a recency bias in reranking. Search augmentation fixes much but not all of this. The bottleneck is increasingly post-retrieval reasoning over conflicting old and new evidence.

### Cited Findings
- Court finding: "'Freshness,' or the recency, of information is an important factor in search quality." Google's index is tiered by "how fresh it needs to be, and the fresher tiers are rebuilt more frequently." Popular sites are crawled more often. Traditional systems such as Navboost "can also beat out LLMs … in certain aspects of SERP production, like freshness." — [Mehta opinion 2024](https://storage.courtlistener.com/recap/gov.uscourts.dcd.223205/gov.uscourts.dcd.223205.1033.0_3.pdf)
- Google's 2011 freshness update, built on the Caffeine index, affected about 35% of searches (meaning at least one result changed). It targets recent events and hot topics, regularly recurring events ("Apple earnings" implies the latest quarter), and frequently updated topics (2011). — [TechCrunch, Nov 3 2011](https://techcrunch.com/2011/11/03/googles-new-algorithm-update-impacts-35-of-searches/amp/)
- Google currently lists "various 'query deserves freshness' systems designed to show fresher content for queries where it would be expected." — [Google ranking systems guide](https://developers.google.com/search/docs/appearance/ranking-systems-guide)
- FreshQA (2023): every model, regardless of size, struggles with fast-changing knowledge and false premises. FreshPrompt (search-engine evidence in the prompt) beats Self-Ask and Perplexity.AI, and the number and order of evidence items "play a key role". — [Vu et al. 2023 (ACL Findings 2024)](https://arxiv.org/abs/2310.03214)
- RealTime QA (2022): GPT-3 updates its answers with new retrieval, but "tends to return outdated answers when retrieved documents do not provide sufficient information." — [Kasai et al. 2022](https://arxiv.org/abs/2207.13332)
- CRAG benchmark (Meta, 2024): accuracy is "much lower" for high-dynamism facts. Straightforward RAG lifts the best LLMs only from 34% or less to 44%, and the best industry RAG answers 63% of questions without hallucination. — [Yang et al. 2024 (NeurIPS 2024 D&B)](https://arxiv.org/abs/2406.04744)
- HoH (2025): outdated information sitting next to current information "substantially reduces response accuracy" and can mislead models "even when current information is available." — [Ouyang et al. 2025](https://arxiv.org/abs/2503.04800)
- TREK (2026 preprint): "the main bottleneck is post-retrieval reasoning rather than retrieval". Frontier models are misled by conflicting evidence even after retrieving everything needed, and benchmarks with outdated distractors underestimate difficulty. — [Hu et al. 2026](https://arxiv.org/abs/2610.25323)
- Snippet-only answering is associated with outdated answers and unfaithful citations (2026 preprint). — [Walters, Chen, Toni 2026](https://arxiv.org/abs/2610.21731)
- Present-anchored questions such as "who was the previous US president?" are hard for LLMs with and without RAG. Benchmark answers must be refreshed continuously, here by re-running SPARQL over a knowledge graph. — [Meem et al. 2024](https://arxiv.org/abs/2402.11034)
- Semantic-only retrieval cannot tell "who won Wimbledon" across years. Adding a temporal relevance term (TempRALM) improves results by up to 74% over the baseline RALM. — [Gade & Jetcheva 2024](https://arxiv.org/abs/2401.13222)
- Recency bias in LLM rerankers: prepending fake recent dates moves the Top-10's mean publication year forward by up to 4.78 years, shifts items by up to 95 ranks, and reverses pairwise preferences between equally relevant passages up to 25% of the time. Larger models reduce but do not remove this. — [Fang et al. 2025](https://arxiv.org/abs/2509.11353)
- Measured citation half-lives in Chinese generative search are about 39 days for high-timeliness queries and 68 days for low-timeliness queries (2026 preprint). — [Zhen et al. 2026](https://arxiv.org/abs/2607.15771)
- AI engines differ in freshness. Claude's consumer-electronics citations had a median age of 62 days and its automotive citations 148 days. Perplexity was "somewhat newer" (2025). — [Chen et al. 2025](https://arxiv.org/abs/2509.08919)
- For real-time structured needs (inventory, tickets), static web RAG is insufficient. Baidu's TURA routes to MCP-wrapped live APIs through intent-aware retrieval and a DAG planner, serving "tens of millions of users" (industry-reported). — [Zhao et al. 2025](https://arxiv.org/abs/2508.04604)

### Inferences
- In a private KB, freshness should be explicit metadata: valid-from/valid-to, superseded-by, last-verified-at. The agent should not have to infer it from text. HoH and TREK show that keeping stale versions retrievable without supersession markers actively hurts answers. Recency-bias results show that a bare date stamp can over-steer a reranker.
- Query-deserves-freshness is a classification step. A KB tool can expose it as a per-query or per-collection time-sensitivity flag that changes ranking, for example a decay applied only to volatile document types.

### Gaps
- No public detail on how ChatGPT search, Claude or Codex web search detect time sensitivity or apply date filters.

---

## 5. The adversarial side: SEO/GEO, ranking manipulation of LLM search, content farms and AI slop, poisoning, citation bias, and defenses

### Takeaway
Every signal an LLM engine relies on is now a target. GEO rewrites (adding quotes, statistics, citations) raised visibility by up to about 40% in controlled settings. Strategic text sequences and prompt injection push products to the top in production engines such as Perplexity, Bing and ChatGPT search. Cheap posts on low-barrier platforms (about $14) entered AI answers within hours or days. Neural retrievers prefer LLM-written text. Web-scale poisoning needs only small, nearly constant amounts of data. Defenses exist but remain partial. The classic web engine's adversarial hardening (spam systems, links, clicks) is a large part of what LLM search inherits.

### Cited Findings
**GEO and visibility manipulation**
- GEO (KDD 2024): Quotation Addition (+41% position-adjusted word count), Statistics Addition, Fluency and Cite Sources raise visibility "by up to 40%". Keyword stuffing does worse than baseline. Cite Sources raised visibility of rank-5 sources by 115.1% but lowered rank-1 sources by 30.3%. On live Perplexity, Quotation Addition gave +22%. — [Aggarwal et al. 2024](https://arxiv.org/abs/2311.09735)
- A critical survey of 45 GEO studies (2026 preprint) finds GEO gains "are valid within its experimental setting but conditional on a source already being present in a fixed context". "Topical relevance and context position are the most reproducible levers". "No reviewed technique shows a stable, longitudinal, cross-platform causal effect on organic discoverability." — [Martinez 2026](https://arxiv.org/abs/2607.14035)
- Live-web test (2026 preprint): GEO-rewritten pages for 80 fictional brands were published and tested on ChatGPT, Gemini and Grok. One strategy (CORE) reached a 66.3–76.3% Top-1 rate, but engines picked the same top product for only 48.8–66.3% of brands. 86 of 400 rewrites contained numerically unfaithful claims, including all 80 "Statistics Addition" rewrites. — [Kong et al. 2026](https://arxiv.org/abs/2611.01126)
- Repeated measurement is needed because AI answers vary across runs, prompts and time. Visibility is "a distribution rather than a single-point outcome." — [Schulte et al. 2026](https://arxiv.org/abs/2604.07585)
- Learned "engine preference rules" (AutoGEO) can rewrite content for more traction while "preserving search utility". The authors frame this as cooperative GEO. — [Wu et al. 2025](https://arxiv.org/abs/2510.11438)
- Strategic text sequences: an optimised string on a product page significantly raises the chance that an LLM lists that product first (fictitious coffee-machine catalogue). — [Kumar & Lakkaraju 2024](https://arxiv.org/abs/2404.07981)
- Preference manipulation attacks: crafted website or plugin content makes LLMs promote the attacker and discredit competitors, demonstrated on production Bing and Perplexity and on GPT-4 and Claude plugin APIs. It creates "a prisoner's dilemma" where everyone attacks and output quality falls for all. — [Nestaas, Debenedetti, Tramèr 2024](https://arxiv.org/abs/2406.18382)
- Tree-of-attacks prompt injections reliably promote low-ranked products and "transfer effectively to … perplexity.ai". LLMs differ widely in how they prioritise product name, content and context position. — [Pfrommer et al. 2024](https://arxiv.org/abs/2406.03589)
- Indirect prompt injection, the foundational work: retrieved data becomes instructions, demonstrated against Bing's GPT-4 Chat. — [Greshake et al. 2023](https://arxiv.org/abs/2302.12173)
- Guardian test (Dec 24 2024): hidden text on a fake product page turned ChatGPT search's "positive but balanced" summary into "almost entirely positive" even though negative reviews stayed on the page. The tool could also return malicious code (secondary reporting; Guardian original not fetched). — [OECD.AI incident record](https://oecd.ai/en/incidents/2024-12-24-656f)
- Low-barrier publication path (2026 preprint): 15 of 22 publication platforms tied to cited domains had low or medium barriers to entry. "8 of 10 platforms cited a fabricated concept within seven days". "A $14 GEO purchase produced 13 public posts, and one AI-search platform cited GEO-posted content … within one hour." — [Liu et al. 2026](https://arxiv.org/abs/2610.11932)
- Brand knowledge in the model is a manipulable channel too: "brand names reorder its rankings of products with identical facts." — [Chen & Koudas 2026](https://arxiv.org/abs/2610.15033)

**Content farms, AI slop and source bias**
- Over a year of Google (via Startpage), Bing and DuckDuckGo on 7,392 product-review queries, "all search engines have significant problems with highly optimized (affiliate) content". They "fall victim to large-scale affiliate link spam campaigns", updates help only temporarily, and engines "seem to lose the cat-and-mouse game that is SEO spam." — [Bevendorff et al. 2024 (ECIR 2024)](https://gwern.net/doc/technology/google/2024-bevendorff.pdf)
- Source bias: neural retrievers and rerankers "tend to rank LLM-generated documents higher". This is explained by LLM text having "more focused semantics with less noise." — [Dai et al. 2023 (KDD 2024)](https://arxiv.org/abs/2310.20501)
- "Spiral of Silence" simulation: LLM-generated text "consistently outperform[s] human-authored content in search rankings," which gradually sidelines human content. — [Chen et al. 2024 (ACL 2024)](https://arxiv.org/abs/2404.10496)
- About 16% of sources cited by ChatGPT, Copilot, Gemini and Perplexity showed evidence of being AI-generated (712 real queries on politics, health and environment, 2026 preprint). — [Allaham & Diakopoulos 2026](https://arxiv.org/abs/2605.23684)

**Poisoning**
- Split-view poisoning (web content changing after indexing) could have poisoned 0.01% of LAION-400M or COYO-700M for $60. Frontrunning poisoning targets periodic Wikipedia snapshots. — [Carlini et al. 2023 (IEEE S&P 2024)](https://arxiv.org/abs/2302.10149)
- Pretraining poisoning needs a "near-constant number" of documents: 250 poisoned documents compromised models from 600M to 13B parameters regardless of dataset size. — [Souly et al. 2025](https://arxiv.org/abs/2510.07192)
- PoisonedRAG: five malicious texts per target question in a knowledge base of millions reach 90% attack success, and the defenses tested were insufficient. — [Zou et al. 2024 (USENIX Security 2025)](https://arxiv.org/abs/2402.07867)

**Defenses**
- Spotlighting (marking the provenance of untrusted input through transformations such as delimiting, datamarking or encoding) cut indirect injection success from over 50% to under 2% on GPT models. — [Hines et al. 2024 (Microsoft)](https://arxiv.org/abs/2403.14720)
- Off-the-shelf guardrails (Granite Guardian, Llama Guard 3, NeMo self-check) reduce misinformation-GEO attack success by at most 5.7% relative. A dedicated C-GEO Guard cuts it by 47.6% (2026 preprint). — [Zheng et al. 2026](https://arxiv.org/abs/2609.02316)
- GEO Defender (a shield reranker learning a defensive residual over a frozen reranker, plus a natural-language experience library) cut attack success from 50.32% to 6.20% while keeping 94.12% of benign evidence use. The authors note that GEO documents stay factually consistent, so "fact verification and perplexity filtering [are] ineffective" (2026 preprint). — [Li et al. 2026](https://arxiv.org/abs/2609.02964)
- Repetition-bias mitigation for source preferences reduces repetition bias by up to 79.2%. — [Schuster et al. 2026](https://arxiv.org/abs/2601.03746)
- Engine-side spam policy against scaled content, site reputation abuse and expired domains. — [Google Search Central, Mar 2024](https://developers.google.com/search/blog/2024/03/core-update-spam-policies)

### Inferences
- The more an engine relies on the LLM reading page text, rather than on behavioural and link evidence that is costly to fake, the easier it is to manipulate. A private KB is mostly spam-free (see §7), but it is not immune to injection: ingested emails, tickets, web clips and tool descriptions are untrusted text. Provenance marking and trust tiers belong in the data model.
- "Cooperative GEO" for one's own corpus amounts to writing documents whose titles and paragraphs match the questions people actually ask. Chen & Koudas find this is the one content property that matters within a site.

### Gaps
- No vendor disclosure of anti-GEO or anti-injection measures in ChatGPT search, Perplexity, Claude or Gemini beyond general statements.
- Most 2026 GEO and defense papers are unreviewed preprints with synthetic brands. Their long-term effects on the live web are unknown, as the GEO survey itself notes.

---

## 6. Evaluations comparing AI search with traditional search, and how quality is measured

### Takeaway
Independent audits consistently find serious grounding and attribution gaps in AI search. These include roughly 50–57% of statements supported by citations in some audits, more than 60% wrong source identification in the CJR test, and 45% of news answers with a significant issue in the EBU/BBC study. Measured citation fidelity improved somewhat in later AIO studies (11% unsupported claims). AI answers also draw on different sources from the organic top results. Evaluation has moved from ranked-list metrics (nDCG) to nugget-based answer evaluation, using LLM assessors calibrated against humans.

### Cited Findings
**Audits**
- Liu, Zhang, Liang (2023): Bing Chat, NeevaAI, perplexity.ai and YouChat. Only 51.5% of sentences were fully supported by citations, and 74.5% of citations supported their sentence (2023 systems). — [Liu et al. 2023 (EMNLP Findings)](https://arxiv.org/abs/2304.09848)
- CJR Tow Center (Mar 6 2025): 8 tools and 1,600 queries. Collectively the tools answered more than 60% of queries incorrectly (identifying article, publisher and URL). Perplexity was wrong 37% of the time and Grok-3 94%. Premium tiers were more confidently wrong. More than half of Gemini's and Grok-3's citations were fabricated or broken URLs. Tools reached content blocked by robots.txt or cited syndicated copies. — [Jaźwińska & Chandrasekar, CJR 2025](https://www.cjr.org/tow_center/we-compared-eight-ai-search-engines-theyre-all-bad-at-citing-news.php)
- EBU/BBC (Oct 22 2025): 22 public-service media organisations, 18 countries, 14 languages, over 3,000 responses (ChatGPT, Copilot, Gemini, Perplexity). 45% had at least one significant issue, 31% had serious sourcing problems, and 20% had major accuracy errors including outdated information. Gemini was at 76%. — [Journalism.co.uk report](https://www.journalism.co.uk/nearly-half-of-ai-generated-answers-contain-an-error-ebu-bbc-report/)
- Google AIO at scale (Mar–Apr 2026, 55,393 trending queries): 13.7% activation, 64.7% for question-form queries. 11.0% of 98,020 atomic claims were unsupported by the cited pages, with omission the main failure. "Source quality and claim fidelity are largely independent" (preprint). — [Xu et al. 2026](https://arxiv.org/abs/2605.14021)
- AIO for medicine (3,611 questions, 2026 preprint): an estimated 56.7% of cited statements are supported by the cited page, 20.8% of statements are uncited factual claims, and the physician-rubric score is 38.2%. "The accuracy of AIOs was unrelated to the grounding of their statements." — [Agnoli et al. 2026](https://arxiv.org/abs/2610.39339)
- AIO and Featured Snippets on the same page disagreed in 33% of baby-care and pregnancy queries, and medical safeguards appeared in only 11% of AIOs. — [Hu et al. 2025](https://arxiv.org/abs/2511.12920)
- AIOs are less consistent across repeated runs and less robust to minor query edits than organic search. — [Grossman et al. 2026](https://arxiv.org/abs/2604.27790)
- Adversarial factual questions (subtly manipulated claims, black-box access) induce wrong answers from Bing Chat, PerplexityAI and YouChat. "Retrieval-augmented generation exhibits a higher susceptibility to factual errors compared to LLMs without retrieval" (2024, human evaluation). — [Hu et al. 2024](https://arxiv.org/abs/2403.12077)
- Behaviour: in a 900-adult US panel (Pew authors), clicks on sources cited in AIOs occur in about 1% of AIO visits, and AIOs are associated with fewer clicks and more sessions ending. — [Chapekis et al. 2026](https://arxiv.org/abs/2608.04831). AIO availability reduced English Wikipedia search referrals by about 5% (difference-in-differences). — [Khosravi & Yoganarasimhan 2026](https://arxiv.org/abs/2602.18455)

**How quality is measured**
- TREC 2024 RAG Track and AutoNuggetizer bring back the TREC QA 2003 nugget method. LLMs create nuggets and assign them to answers. Fully automatic and mostly manual scores correlate strongly (21 topics, 45 runs). — [Pradeep et al. 2024](https://arxiv.org/abs/2411.09607); framework, MS MARCO V2.1 corpus and baselines: [Ragnarök](https://arxiv.org/abs/2406.16828)
- LLM relevance assessors (Bing production, UMBRELA in TREC) replace or extend human qrels. — [Thomas et al. 2023](https://arxiv.org/abs/2309.10621); [UMBRELA](https://arxiv.org/abs/2406.06519)
- CRAG covers 4,409 QA pairs across five domains with mock web and KG APIs, stratified by popularity, dynamism and complexity. — [Yang et al. 2024](https://arxiv.org/abs/2406.04744)
- Attribution and verifiability metrics: citation recall and citation precision ([Liu et al. 2023](https://arxiv.org/abs/2304.09848)); survey of attribution mechanisms ([Li et al. 2023](https://arxiv.org/abs/2311.03731)).
- GEO visibility metrics: position-adjusted word count and subjective impression ([GEO](https://arxiv.org/abs/2311.09735)). A proposed "visibility vector" separates discoverability, citation, absorption and economic outcomes ([Martinez 2026](https://arxiv.org/abs/2607.14035)).

### Inferences
- The decline in grounding comes mostly from the selection and synthesis layers (omission, uncited claims, snippet-only answers), not the retrieval backend. AIO's cited domains can be more credible than organic results while claims still go unsupported. For a KB toolkit, this argues for returning citable spans with stable IDs and checking support, which the citations track covers.
- A KB can be evaluated cheaply in the TREC 2024 style: create nuggets per question, auto-assign them, and calibrate against a small human-labelled set.

### Gaps
- No head-to-head, independently run benchmark of ChatGPT search, Claude, Perplexity and Google AI Mode on the same nugget-scored question set was found for 2026.
- Audits age quickly as products change. The 2023–2025 numbers may overstate current error rates for some products, and no audit with the same method across years was found apart from the CJR and EBU series.

---

## 7. Transferable lessons: what a private KB lacks and how to substitute, and how typed DBs and searchable KBs differ

### Takeaway
A private KB or data lake has none of the web's free external quality evidence: no dense link graph, no click logs from millions of users, no rater programme, no spam team. It does have advantages the web lacks: known authors and owners, little spam, typed fields, explicit versions and access control. The quality stack has to be rebuilt from first-party signals: ownership and verification metadata, curated authority tiers, usage and feedback logs, explicit freshness and supersession, and fielded or lexical search tools the agent can call repeatedly. Do not rely on embedding similarity alone.

### Cited Findings
- Intranets differ structurally. IBM's intranet has a strongly connected core of about 10% of nodes, so PageRank and HITS discriminate poorly among mid-tier pages. Creators "have little reason" to build well-linked hubs. Many queries have "a small set of correct answers" (a "right answer", not the "best answer"). Because intranets are largely spam-free, anchor text, titles and headings are reliable, with "the amazing efficacy of anchortext" roughly doubling recall@20 for popular queries. — [Fagin et al. 2003, Searching the Workplace Web (WWW 2003)](https://mccurley.org/papers/www2003/p641-mccurley.html)
- Enterprise search survey: enterprise corpora "lack the highly hyperlinked nature of the web, hence the most successful techniques of the web, based on link analysis do not apply". Converting email and documents to HTML does not help "unless the converted documents are interlinked". Upstill et al. found PageRank gives no discernible benefit over indegree, and Hawking et al. found external web link evidence unnecessary for navigational enterprise search (2008 survey of 2001–2004 work). — [Mirza 2008, Enterprise Information Retrieval: A Survey](https://scitepress.org/PublishedPapers/2008/16742/16742.pdf)
- Even Google's language-understanding models were trained on click data, and clicks fill gaps that LLMs do not ("AI models [do not] eliminate that need"). For small engines, "even a small amount of data can result in meaningful improvements" (court finding ¶106, Oard). — [Mehta opinion 2024](https://storage.courtlistener.com/recap/gov.uscourts.dcd.223205/gov.uscourts.dcd.223205.1033.0_3.pdf)
- LLM labels can stand in for human relevance raters when tuned on first-party gold feedback. — [Thomas et al. 2023](https://arxiv.org/abs/2309.10621)
- A simple source reliability prior, score = sim × λ(source), improves precision and demotes adversarial documents when credibility is identifiable from metadata. — [Koganti & Garrido-Lestache 2026](https://arxiv.org/abs/2607.22584)
- Temporal metadata in ranking (TempRALM, up to +74%) and the documented harm of stale co-existing versions. — [Gade & Jetcheva 2024](https://arxiv.org/abs/2401.13222); [HoH 2025](https://arxiv.org/abs/2503.04800)
- Lexical and fielded baselines are robust zero-shot, and reranking adds most of the gain. — [BEIR](https://arxiv.org/abs/2104.08663); [RankZephyr](https://arxiv.org/abs/2312.02724)
- A PoisonedRAG-style attack works on any knowledge base that ingests untrusted text, and provenance marking reduces injection. — [PoisonedRAG](https://arxiv.org/abs/2402.07867); [Spotlighting](https://arxiv.org/abs/2403.14720)
- Live and structured data should go through tools (MCP), not static indexing. — [TURA 2025](https://arxiv.org/abs/2508.04604)
- RL-trained query generation reaches strong gains on SQL database search as well as on search engines, which shows that query skill transfers to typed stores. — [DeepRetrieval 2025](https://arxiv.org/abs/2503.00223)

### Inferences (mapping web signals to KB substitutes)
- **Link graph → explicit references.** Build the graph the web gets for free: citations between documents, "see also" links, code import graphs, ticket-to-commit links, and entity links. Store anchor-like text, meaning how other documents refer to this one, as a searchable field on the target. Fagin 2003 shows anchors and titles are the strongest intranet signals.
- **Clicks / NavBoost → agent and user usage logs.** Log which results an agent opened, cited, or used in a successful task, and which it skipped or followed with a re-query (the analogues of good and bad clicks). Memorise query→doc success for repeated query patterns (a small "NavBoost table"), and feed failures back into reranking. Google's own record says even small amounts of such data help.
- **siteAuthority / E-E-A-T → ownership and verification metadata.** Owner, team, review status, "verified-by/at", canonical vs draft, and source-system trust tier. Give these to the reranker as priors, because LLMs judge credibility shallowly ([Wan et al.](https://arxiv.org/abs/2402.11782)).
- **Quality raters → LLM judges calibrated on a small gold set**, plus nugget-style evaluation of answers ([TREC RAG](https://arxiv.org/abs/2411.09607)).
- **QDF / index tiers → typed temporal fields** (effective dates, superseded-by, last-verified), with time-sensitivity flags per collection. Exclude or down-weight superseded versions by default.
- **Spam team → provenance and trust tiers for ingested external content**, with injection-safe rendering (spotlighting) and quarantine for low-trust sources.
- **Fan-out → cheap, repeatable, fielded search tools.** Agents get quality by issuing many precise queries ([Google fan-out](https://blog.google/products/search/google-search-ai-mode-update/); [Search-R1](https://arxiv.org/abs/2503.09516)). Expose BM25 and field filters (type, owner, date, system) plus a reranker, not only top-k vector similarity.
- **How typed databases and searchable KBs differ from web search:** web search ranks an open, adversarial, unstructured corpus using crowd evidence. A typed DB or KB can answer "right answer" queries exactly through schema, keys and filters, which the web cannot. For those queries, quality comes from correct typing, entity resolution and freshness metadata, not from popularity. The web's lesson applies to the remaining unstructured, many-candidate part. There, a KB still needs the outside-the-document evidence Kleinberg described, and it has to create that evidence deliberately.

### Gaps
- No published controlled study was found that measures the value of usage and feedback signals for LLM agents retrieving over a private KB, as opposed to human enterprise search.
- Modern (post-2015) public evidence on enterprise link analysis is thin. The main sources date from 2003–2008.
