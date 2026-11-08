# Track 05: How agents search and use knowledge bases (agentic RAG, file and markdown KBs, context engineering, agent memory)

Scope note (written 2026-11-06). This track covers the agent side only: how a searchable knowledge base (KB) should be shaped and exposed so that agents search it well, plus agent memory used as a KB. It deliberately leaves out indexing internals, SOP and rule authoring, taxonomies, lifecycle and product surveys, which other tracks cover. It builds on `Agent ready data lake toolkit/storage_agent_retrieval.md` (grep vs vector, MCP, tool search) and does not repeat it. Where that file already covers a source (Is Grep All You Need, Pi-Serini, Anthropic advanced tool use), this file adds only new detail.

Tags used below:
- [vendor] = self-reported by an interested party.
- [secondary] = I saw only a summary, not the primary document.
- [older: YYYY] = predates 2026.
- [single-study] = one benchmark or deployment, no replication.

Abstracts were read for every paper cited. Key papers were read in full HTML: Airbnb portable skill, Is Agentic RAG Worth It, Is Progressive Disclosure All You Need, KARL, Self-Route and MemoryAgentBench.

## 1. Agentic RAG: iterative retrieval, decomposition and reflection, RL-trained search agents, benchmarks, gains over single-shot RAG, and cost

### Takeaway
Iterative, agent-driven retrieval reliably beats single-shot RAG on multi-hop and "needle-composition" questions. Examples: FRAMES 0.40 to 0.66, IRCoT up to +15 QA points, and BrowseComp-Plus up to about 90% with frontier models. Most of the gain comes from a short loop (about 2 iterations), a good first move and a strong retriever with reranking, not from elaborate adaptive routing. On simple or single-hop queries, a well-tuned fixed pipeline ("enhanced RAG" with reranking) matches agentic RAG at roughly 1/3 the token cost. RL-trained small search agents (Search-R1 family, KARL) are now Pareto-competitive on cost, but their gains are reported mostly by their authors on Wikipedia-style QA.

### Cited Findings
**First-generation iterative and reflective RAG [older]**
- **IRCoT** (Stony Brook/AI2, Dec 2022, ACL 2023) interleaves retrieval with each chain-of-thought sentence, because "what to retrieve depends on what has already been derived." With GPT-3 it improves retrieval by up to 21 points and QA by up to 15 points on HotpotQA, 2WikiMultihopQA, MuSiQue and IIRC. It also works with Flan-T5-large without training [older: 2022] — [arXiv 2212.10509](https://arxiv.org/abs/2212.10509)
- **FLARE** (CMU, May 2023, EMNLP 2023) predicts the next sentence and, if it contains low-confidence tokens, uses that sentence as a query and regenerates. It was superior or competitive on 4 long-form tasks. Failure mode: confidence thresholds need tuning per model [older: 2023] — [arXiv 2305.06983](https://arxiv.org/abs/2305.06983)
- **Self-RAG** (UW/AI2/IBM, Oct 2023, ICLR 2024) trains a 7B/13B LM to emit reflection tokens that decide whether to retrieve and critique passage relevance and support. It beats ChatGPT and retrieval-augmented Llama2-chat on open QA, reasoning and fact verification, and improves citation accuracy. Cost: it requires a specially fine-tuned model [older: 2023] — [arXiv 2310.11511](https://arxiv.org/abs/2310.11511)
- **CRAG** (USTC, Jan 2024) adds a lightweight T5 retrieval evaluator that scores retrieved documents and triggers web search or "decompose-then-recompose" filtering when confidence is low [older: 2024] — [arXiv 2401.15884](https://arxiv.org/abs/2401.15884). An independent 2026 open-source reproduction matched performance on PopQA and ARC-Challenge. A SHAP analysis showed the evaluator relies mainly on named-entity alignment rather than semantics and transfers poorly to science questions — [arXiv 2603.16169](https://arxiv.org/abs/2603.16169)
- A survey (Singh et al., Jan 2025) gives a taxonomy of agentic RAG by agent cardinality, control structure, autonomy and knowledge representation [older: 2025] — [arXiv 2501.09136](https://arxiv.org/abs/2501.09136)

**Reasoning-model and RL-trained search agents (2025–2026)**
- **Search-o1** (RUC, Jan 2025) lets a large reasoning model issue searches when it is uncertain, mid-reasoning. A separate "Reason-in-Documents" module condenses verbose retrieved documents before injecting them, to protect the reasoning chain from noise [older: 2025] — [arXiv 2501.05366](https://arxiv.org/abs/2501.05366)
- **Search-R1** (UIUC/Google, Mar 2025, COLM 2025) trains multi-turn search with outcome-only RL. It masks retrieved tokens from the loss for stability. It reports +41% (Qwen2.5-7B) and +20% (3B) over RAG baselines on 7 QA datasets [older: 2025] — [arXiv 2503.09516](https://arxiv.org/abs/2503.09516)
- **R1-Searcher** (RUC, Mar 2025) uses two-stage outcome RL with no process reward or distillation cold start. It reports beating strong RAG methods and GPT-4o-mini [older: 2025] — [arXiv 2503.05592](https://arxiv.org/abs/2503.05592)
- **ReSearch** (Baichuan et al., Mar 2025) does RL without supervised reasoning traces. It was trained on one dataset, generalized across benchmarks, and showed emergent reflection and self-correction [older: 2025] — [arXiv 2503.19470](https://arxiv.org/abs/2503.19470)
- **DeepResearcher** (SJTU, Apr 2025) runs end-to-end RL against the live web, not a fixed corpus. It reports +28.9 points over prompt-engineered agents and +7.2 points over RAG-environment RL agents, plus emergent cross-validation and honesty when it cannot find an answer [older: 2025] — [arXiv 2504.03160](https://arxiv.org/abs/2504.03160)
- A controlled 2026 study of Search-R1 training found three things. A "fast thinking" template beats "slow thinking". F1 reward collapses through answer avoidance unless action penalties are added. REINFORCE beats PPO with fewer searches, and GRPO is least stable. The resulting Search-R1++ moves 0.403 to 0.442 (7B). This shows RL search gains are sensitive to recipe details — [arXiv 2602.19526](https://arxiv.org/abs/2602.19526)
- **KARL** (Databricks AI Research, Mar 2026) RL-trains an enterprise search agent whose only tool is vector search (k up to 20). KARLBench spans BrowseComp-Plus, TREC-Biogen, FinanceBench, QAMPARI, FreshStack and PMBench (internal notes). Scores: KARL 58.9 single-call, 67.5 with 10 parallel rollouts, against Claude 4.6 Opus 67.5, Sonnet 62.3, GPT-5 60.1 and GPT-5.2 52.8. A single call costs under $0.10 per query, and KARL matches Opus at about 33% lower cost. Self-summarization compression learned through RL matters: removing it drops BrowseComp-Plus from 0.570 to 0.389. Accuracy degrades sharply at 40 retrieved docs per search versus 10–20 [vendor] — [arXiv 2603.05218](https://arxiv.org/abs/2603.05218)

**Benchmarks and what they show about gains over single-shot RAG**
- **FRAMES** (Google, Sep 2024) has 824 multi-hop questions. State-of-the-art LLMs score 0.40 with no retrieval and 0.66 with a multi-step retrieval pipeline (>50% relative) [older: 2024] — [arXiv 2409.12941](https://arxiv.org/abs/2409.12941)
- **BrowseComp-Plus** (Waterloo et al., Aug 2025) uses a fixed curated corpus (about 100k docs) with human-verified evidence, so retriever and agent effects can be separated. Search-R1 with BM25 gets 3.86%. GPT-5 with BM25 gets 55.9%, and GPT-5 with Qwen3-Embedding-8B gets 70.1% with fewer search calls [older: 2025] — [arXiv 2508.06600](https://arxiv.org/abs/2508.06600)
- On the same benchmark, tuned BM25 with deep paginated results (Pi-Serini) and gpt-5.5 reaches 83.1% — [arXiv 2605.10848](https://arxiv.org/abs/2605.10848). **Question's Gambit** (Sep 2026) adds a "first move" that decomposes the question into clues, issues complementary searches, consolidates and reranks before the agent loop. This lifts gpt-5.5 from 83.1% to 90.5% — [arXiv 2609.14412](https://arxiv.org/abs/2609.14412)
- Retriever training for agents: **AgentIR-4B** embeds the agent's pre-search reasoning together with its query. It reaches 68% on BrowseComp-Plus with Tongyi-DeepResearch, against 50% for conventional embedders twice its size and 37% for BM25 — [arXiv 2603.04384](https://arxiv.org/abs/2603.04384). **ITER** adds the main question and prior sub-queries to the query representation, for +15.4% relative on BrowseComp-Plus over LRAT — [arXiv 2608.27912](https://arxiv.org/abs/2608.27912)
- Reranking is cheaper than more reasoning. On BrowseComp-Plus, "moderate reranking often yields larger gains than increasing search-time reasoning", reaching comparable accuracy at substantially lower effective token cost — [arXiv 2601.14224](https://arxiv.org/abs/2601.14224)
- **Stagnation:** most deep-research-agent iterations add little. A retrieval-aware controller that uses search-novelty and coverage signals cut search calls by an average of 14 per query and gave up to +10% accuracy (3% average) on BrowseComp-Plus — [arXiv 2608.15191](https://arxiv.org/abs/2608.15191). A POMDP framing ("context gathering decision process") with an explicit predicate belief state improved multi-hop by up to 11.4%, and an exhaustion gate saved up to 39% of tokens with no loss — [arXiv 2605.07042](https://arxiv.org/abs/2605.07042)
- **Context rot in long-horizon search:** under extensive context, flagship models "give up or provide uncertain incorrect answers long before exhausting the context window" (inconclusive search failures). The authors argue context-management methods work mainly by lowering peak context length — [arXiv 2606.29718](https://arxiv.org/abs/2606.29718)

**Head-to-head evidence on whether agentic RAG is worth the cost**
- **Is Agentic RAG worth it?** (Jan 2026) compares enhanced RAG (semantic router, HyDE, ELECTRA reranker) with a single-tool agentic RAG on FIQA, NQ, FEVER and CQADupStack, using Qwen3 0.6B–32B and GPT-4.1-nano.
  - Query rewriting: agentic wins on NDCG@10 (55.6 vs 52.8 average).
  - Out-of-scope routing: agentic wins on FIQA and CQADupStack but collapses on FEVER (F1 64.6 vs 87.9).
  - Document refinement: agentic loses (43.9 vs 49.5 with reranker). The agent re-retrieved only about 10% of the time.
  - Cost: agentic used about 3.3x input tokens, 1.9x output tokens and 1.5x latency, and up to 3.6x cost.
  - Authors' conclusion: "neither Enhanced nor Agentic RAG is universally superior."
  — [arXiv 2601.07711](https://arxiv.org/abs/2601.07711)
- **Component ablation with a local 7B model** (HotpotQA, 5,000 questions):
  - Full agentic pipeline EM 53.2 vs single-pass 43.1.
  - Fixed hybrid RRF beat rule-based adaptive routing by +1.8 EM.
  - Two retrieval iterations captured 95% of the gains of five.
  - Decomposition and cross-encoder reranking each gave smaller but significant gains.
  [single-study] — [arXiv 2606.21553](https://arxiv.org/abs/2606.21553)
- **Enterprise robustness:** EnterpriseRAG has 983 expert samples with retrieval noise, knowledge gaps and factual conflicts. LLMs satisfy 80% of individual constraints but only 26.8% of responses meet all of them, which the authors call a "57-point orchestration gap" — [arXiv 2608.11584](https://arxiv.org/abs/2608.11584)
- **Production retriever distribution shift:** first-stage retrievers in agentic RAG serve machine-written reformulations, not human queries. Q2D-Web (190M docs, 70k agent-reformulated queries in 10 languages) was built to evaluate retrievers on that distribution — [arXiv 2609.08887](https://arxiv.org/abs/2609.08887)
- **Vendor productization:** Azure AI Search "agentic retrieval" (GA REST API 2026-04-01 for minimal and extractive retrieval; query planning still preview in 2026-08-01-preview) has an LLM split a query into subqueries. These run in parallel as keyword, vector or hybrid search with semantic reranking, then merge into grounding data with references and an activity log. Billing is token-based. Microsoft's worked example is about $4.32 per 2,000 retrievals with gpt-4o-mini planning. The doc concedes that agentic retrieval "adds latency compared to a single-query pipeline" [vendor] — [Microsoft Learn](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview)
- Anthropic's multi-agent research system (Opus 4 lead with Sonnet 4 subagents) beat single-agent Opus 4 by 90.2% on an internal research eval. Agents use about 4x the tokens of chat and multi-agent systems about 15x. On BrowseComp, token usage explained 80% of performance variance. Prompting agents to "start with short, broad queries" and then narrow fixed early over-specific queries [vendor, older: Jun 2025] — [Anthropic Engineering](https://www.anthropic.com/engineering/multi-agent-research-system)

### Inferences
- For a domain KB (rules, policies, SOPs), the evidence supports a bounded loop: plan or decompose, then hybrid search plus rerank, read, and at most 1–2 more retrieval rounds. Unbounded deep research is unsupported. Adaptive routing heuristics and deep loops add cost with little measured gain (2606.21553, 2608.15191).
- The "first move" (clue decomposition, parallel queries, rerank) is a cheap server-side primitive the KB can offer as a `plan_and_search` tool. Azure's agentic retrieval productizes the same idea.
- RL-trained search agents are relevant mainly if the toolkit ships its own small model. Otherwise a frontier model plus good tools is the evidence-backed path. Treat RL-agent numbers as author-reported on Wiki-QA distributions.
- Measure tokens and calls per answer. Agentic gains are typically bought with 1.5–15x tokens.

### Gaps
- I found no independent benchmark of agentic search over enterprise policy or SOP corpora with cost accounting beyond the Airbnb case study (Section 2) and EnterpriseRAG (which is not agentic).
- Search-o1, R1-Searcher and ReSearch headline numbers beyond their abstracts were not extracted.
- FRAMES and HotpotQA-era gains may overstate benefits for modern frontier models that already decompose internally.

## 2. File-system and markdown knowledge bases: CLAUDE.md/AGENTS.md, llms.txt, Agent Skills with progressive disclosure, linked notes, grep/glob/read, context engineering; evidence against vector stores

### Takeaway
The 2025–2026 practitioner consensus is a "just-in-time" hybrid, popularized by Anthropic, Manus, LangChain and OpenAI Codex. It has three parts: (1) a small always-loaded map, either an index or a CLAUDE.md/AGENTS.md about 100–200 lines long; (2) a navigable file tree of markdown pages with descriptive names and frontmatter; and (3) grep/glob/read plus optional search tools to pull detail on demand.

Controlled evidence supports some of this and refutes some:
- An always-present compressed index beat on-demand skills (Vercel: 100% vs 79%).
- One level of progressive disclosure helps once the corpus is too big to navigate by reading. Deeper hierarchies hurt.
- An LLM-generated "wiki" navigation layer over an SOP corpus matched or beat a production RAG stack on evidence sufficiency, at about 10x the latency of the deployed assistant.
- Generic repository overviews in context files do not help coding agents and cost more than 20% extra tokens.
- Instruction files grow without bound and override contradicting evidence.

### Cited Findings
**Context engineering doctrine (vendor engineering blogs; practitioner evidence, not controlled)**
- Anthropic defines context engineering as "curating and maintaining the optimal set of tokens during LLM inference." It names "context rot" (recall declines as context fills) and recommends "just in time" retrieval, where agents keep lightweight identifiers (paths, queries, links) and load data with tools. Folder location, naming and timestamps act as relevance signals. Claude Code is the example hybrid: CLAUDE.md is loaded up front, and glob and grep fetch everything else. Anthropic suggests this hybrid suits "less dynamic" domains such as legal or finance. Long-horizon tools are compaction, structured note-taking and subagents returning summaries of about 1–2k tokens [vendor, older: Sep 2025] — [Anthropic Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- Manus lessons:
  - KV-cache hit rate is "the most important metric." Input-to-output ratio is about 100:1, and cached Sonnet input costs $0.30/MTok against $3 uncached.
  - Keep prefixes stable and append-only.
  - Mask tools rather than removing them.
  - Use the file system as unlimited, restorable external memory (drop page content but keep the URL).
  - Recite goals in todo.md over about 50 tool calls.
  - Keep errors in context.
  - Vary serialization to avoid few-shot ruts.
  [vendor, older: Jul 2025] — [Manus blog](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- LangChain frames four strategies: write (scratchpads, memories), select (CLAUDE.md, rules files, RAG over tools and knowledge), compress (Claude Code auto-compacts at 95% of the window) and isolate (subagents, sandboxes, state fields). It cites Breunig's failure modes: poisoning, distraction, confusion and clash. It also reports RAG over tool descriptions giving "3-fold" better tool selection [vendor, older: Jul 2025] — [LangChain blog](https://www.langchain.com/blog/context-engineering-for-agents)
- An academic framing (AIGNE framework) treats "everything is a file": heterogeneous context artifacts are mounted into a governed file system with metadata and access control, and assembled by a Constructor/Loader/Evaluator pipeline under token budgets — [arXiv 2512.05470](https://arxiv.org/abs/2512.05470)

**CLAUDE.md / AGENTS.md (always-loaded context files)**
- AGENTS.md is a plain-markdown "README for agents." It is now stewarded by the Agentic AI Foundation under the Linux Foundation and used by more than 60,000 projects. The nearest file in the tree takes precedence; the main OpenAI repo has 88 of them [vendor] — [agents.md](https://agents.md/)
- Claude Code docs (Nov 2026):
  - CLAUDE.md files above the working directory load at launch, and subdirectory files load on demand when Claude touches files there.
  - `@imports` recurse up to 4 hops but don't reduce context cost.
  - `.claude/rules/*.md` can be path-scoped so they load only for matching files.
  - Auto memory loads the first 200 lines or 25KB of MEMORY.md.
  - Guidance: "target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce adherence." Move multi-step procedures to skills.
  [vendor] — [Claude Code docs: memory](https://code.claude.com/docs/en/memory)
- OpenAI Codex "harness engineering" (Feb 2026): "one big AGENTS.md" failed because it crowds out the task and drifts. The team moved to a short AGENTS.md (about 100 lines) "as a map / table of contents", pointing to a structured `docs/` directory treated as the system of record (design-docs, exec-plans, product-specs, references, RELIABILITY.md, SECURITY.md), with mechanical checks and a doc-gardening agent [vendor; secondary, as the primary page returned 403 to my fetcher] — [OpenAI: Harness engineering](https://openai.com/index/harness-engineering/)
- **Controlled evidence that context files often don't help:**
  - ETH-style evaluation (Feb 2026): context files "do not generally improve task success rates, while increasing inference cost by over 20%." Instructions are followed, but repository overviews "are not helpful." Holds across LLMs, agents, and both generated and human-written files — [arXiv 2602.11988](https://arxiv.org/abs/2602.11988)
  - Two-agent ablation (Claude Code and Codex, 288 runs): context strategy does not move correctness (bounded at ≤10–15 pp). Failures were implementation skill, not missing repository knowledge — [arXiv 2607.27250](https://arxiv.org/abs/2607.27250)
- **Instruction files are treated as authority even when stale:**
  - With a deliberately stale file, 90.1% of agent choices followed it over the code. Claude Code flagged the conflict in 79 of 80 runs and still followed the file.
  - One user-level sentence giving code precedence moved code-following from 4.2% to 91.4%.
  - Explanation offered: the file arrives as instruction, the code as lower-ranked tool output.
  — [arXiv 2610.30571](https://arxiv.org/abs/2610.30571)
- **Wording matters:** conditional phrasing of a policy was followed less often than prescriptive or explanatory phrasing (86 tasks, 4 harness-model pairs) — [arXiv 2611.04367](https://arxiv.org/abs/2611.04367)
- **Growth and decay ("catastrophic remembering"):** across 247,694 instruction lifetimes in 1,867 repos, files more than triple over their lifetime (+226%, +4.9 net instructions per commit), and older instructions are less likely to be deleted. Adding rationale comments removed 99.3% of excess instructions in a synthetic setting — [arXiv 2608.11095](https://arxiv.org/abs/2608.11095). A formal assortment model proves an upper bound on optimal always-loaded file size and shows that appending every positively-valued instruction can be arbitrarily worse. Empirically, irrelevant rules taken from real files reduce compliance — [arXiv 2610.11007](https://arxiv.org/abs/2610.11007)
- **Census data:**
  - 22,854 repos: instruction files in 26.3% of repos (59.6% of the most-starred), and 74.0% of directives give no reason — [arXiv 2610.31715](https://arxiv.org/abs/2610.31715)
  - 2,303 files: they evolve like configuration code; test procedures appear in 75.9%, security in only 14.8% — [arXiv 2511.12884](https://arxiv.org/abs/2511.12884)

**Agent Skills and progressive disclosure**
- Anthropic Agent Skills (Oct 16, 2025; open standard Dec 18, 2025) are folders with a SKILL.md. Level 1 is name and description, always in the system prompt. Level 2 is the SKILL.md body, read when relevant. Level 3+ is linked files and scripts read or executed on demand. Bundled context is "effectively unbounded." Security: install only trusted skills [vendor] — [Anthropic Engineering](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- **Vercel evals** (Jan 27, 2026, Next.js 16 APIs absent from training data):
  - Baseline 53%.
  - Skill (default) 53%; the skill was never invoked in 56% of cases.
  - Skill with explicit instruction 79%.
  - An 8KB compressed docs index in AGENTS.md pointing to version-matched doc files: 100%.
  - Explanation offered: there is "no decision point" about whether to look things up.
  [vendor, single-study] — [Vercel blog](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals)
- **Is Progressive Disclosure All You Need?** (Jul 2026, ∞Bench; Codex, Pi and Claude Code harnesses; gpt-5.4-mini, qwen3.6-27b, haiku-4.5):
  - Single book: a flat one-level skill pack (SKILL.md index of chunk paths with summaries and entities) helps weak harnesses (Claude Code/haiku En.MC 0.745 to 0.867) but is neutral under Codex, which already greps.
  - Two-level hierarchy "never helps and sometimes breaks accuracy" (Pi En.MC 0.913 to 0.640).
  - Hybrid RAG trails flat in nearly every cell.
  - Multi-book (K=20): raw navigation collapses (Codex En.QA 0.257) while flat holds better (0.462) at about half the tokens (about 32.5M vs 68.3M per question, uncached).
  - Authors' summary: "progressive disclosure buys context, not intelligence."
  — [arXiv 2607.17598](https://arxiv.org/abs/2607.17598)
- **SkillJuror** (82 SkillsBench tasks): progressive disclosure versus a flat skill raised distinct resources touched from 1.18 to 3.85 per trajectory and gave +4.1% verifier-passing trials. It helps when resources guide implementation or checking, and is weaker for exact conventions or thresholds — [arXiv 2606.11543](https://arxiv.org/abs/2606.11543)
- **Workday deployment report:** lazy-loading skills improves skill-retrieval quality but marginally degrades latency [vendor] — [arXiv 2609.35692](https://arxiv.org/abs/2609.35692)
- **Skills in the wild:** when agents must retrieve from 34k real skills, gains degrade "approaching no-skill baselines." Query-specific refinement recovers much of the loss (Terminal-Bench 2.0, Opus 4.6: 57.7% to 65.5%) — [arXiv 2604.04323](https://arxiv.org/abs/2604.04323). SkillFlow, a multi-stage retriever over about 35K SKILL.md files, raised SkillsBench Pass@1 from 9.2% to 16.4% but gave no gain on Terminal-Bench where good skills were missing — [arXiv 2504.06188](https://arxiv.org/abs/2504.06188)
- **Skill survey:** 26.1% of community skills contain vulnerabilities, motivating provenance-gated permissions — [arXiv 2602.12430](https://arxiv.org/abs/2602.12430)

**Markdown wikis and navigation layers over document corpora (most relevant to this toolkit)**
- **Airbnb "Frustratingly Easy Agentic RAG via Portable Skills"** (Oct 2026):
  - Corpus: 2,881 customer-support SOP/policy articles.
  - Navigation layer: GPT-4.1 generated about 2,700 "Wikipedia-style" markdown pages in a single update-or-create pass with a running `index.md`. Pages carry intent summaries, typed links, merged entities and stable source IDs, and 96% of 3,168 links were audited as supported.
  - Skill: SKILL.md workflow plus deterministic scripts (`retrieve` = hybrid BM25+dense over the wiki, `get_article`, `save_output`) plus a validator that rejects any quoted snippet that is not a substring of its cited source article.
  - Generator: Claude Opus 4.7 in Claude Code.
  - Results on 132 real cases: guidance match 99.2% vs 96.2% for scripted production RAG (CIs overlap), and snippet sufficiency 83.3% vs 59.8% (CIs don't overlap). Median about 5 queries and 6 fetches.
  - Ablations: BM25-only 78.0%, dense-only 78.8%, hybrid 83.3%, no navigation layer 78.0%. None was significant (McNemar p ≥ 0.078).
  - Latency: about 90 s per case vs about 8–9 s for the deployed assistant.
  - Remaining failures were mostly knowledge missing from the corpus.
  - Built in 1–2 engineer days. Maintenance is "editing text and data rather than retraining."
  [vendor, single-study] — [arXiv 2610.14428](https://arxiv.org/abs/2610.14428)
- **Karpathy "LLM Wiki"** (Apr 2026 gist, an idea file rather than code):
  - Layers: immutable raw sources, an LLM-owned interlinked markdown wiki, and a schema file (CLAUDE.md/AGENTS.md).
  - Operations: ingest ("a single source might touch 10-15 wiki pages"), query (good answers filed back as pages) and lint (contradictions, stale claims, orphans).
  - `index.md` "works surprisingly well at moderate scale (~100 sources, ~hundreds of pages)", but "as the wiki grows you want proper search." He points to qmd, a local hybrid BM25/vector search with LLM rerank exposed over CLI and MCP.
  [opinion] — [GitHub gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- **Knowledge compounding:** a self-evolving wiki implementation (4 sequential queries) used 47K tokens against 305K for a RAG baseline (-84.6%), attributed to amortized ingest, writing answers back to synthesis pages and writing search results back to entity pages [single-study, very small n] — [arXiv 2604.11243](https://arxiv.org/abs/2604.11243)
- **Enterprise hierarchy:** VDGR-RAG (telecom product docs) combines vector search, table-of-contents directory routing, graph traversal and a directory-backtracking tool, and reports beating RAG baselines [single-study] — [arXiv 2608.07994](https://arxiv.org/abs/2608.07994)
- **Structured linked data:** entity pages with llms.txt-style agent instructions, breadcrumbs and interlinks gave +29.6% accuracy (standard RAG) and +29.8% (agentic) over plain HTML, while JSON-LD alone helped only modestly — [arXiv 2603.10700](https://arxiv.org/abs/2603.10700)

**llms.txt**
- llms.txt was proposed by Jeremy Howard (Sep 3, 2024; v2 page updated Aug 10, 2026). It is a `/llms.txt` with an H1, a blockquote summary and H2 lists of links to clean `.md` page versions, plus an "Optional" section. The v2 page reports thousands of sites, auto-generation by Mintlify and others, Lighthouse audits, and OpenAI, Anthropic and Gemini docs publishing one [vendor/advocate] — [llmstxt.org](https://llmstxt.org/)
- **Independent evidence is weak:**
  - A 2026 audit found no study isolating llms.txt's utility. A 15-tool probe saw no automatic fetches in 45 trials, and a log study found 97% of domains with the file received no recorded requests (May 2026).
  - An adversarial pilot showed manifest content can steer outputs (attacker target adopted in 21 of 24 adversarial responses).
  — [arXiv 2610.38361](https://arxiv.org/abs/2610.38361)
  - HTTP fingerprinting of 9 coding agents shows agents compress multi-page doc navigation into 1–2 requests. The authors recommend "tokenomics-aware documentation design" — [arXiv 2604.02544](https://arxiv.org/abs/2604.02544)

**Direct corpus interaction (grep/shell over raw files) versus retrievers (new 2026 evidence beyond the earlier notes)**
- **DCI** (May 2026): with only grep, file reads and shell scripts (no index), agents "substantially outperform strong sparse, dense, and reranking baselines" on several BRIGHT and BEIR sets and are strong on BrowseComp-Plus. The authors argue retrieval quality depends on "the resolution of the interface" — [arXiv 2605.05242](https://arxiv.org/abs/2605.05242)
- **Scale limits:** raw DCI "becomes unstable" as the corpus grows. **Dr-DCI** uses retrieval as an action that pulls documents into a local workspace and then greps there: 71.2% on BrowseComp-Plus (73.3% with workspace-preserving reset), effective from 100K to 10M docs where raw DCI fails — [arXiv 2606.14885](https://arxiv.org/abs/2606.14885)
- **GrepSeek** RL-trains a shell-based search agent and adds execution optimizations (up to 77x faster grep on a 14GB, 21M-doc corpus), for +5.7% over the best baseline across 8 open QA sets — [arXiv 2605.29307](https://arxiv.org/abs/2605.29307)
- **RARG** uses relevance to order ripgrep traversal and rerank matches, improving the accuracy-efficiency frontier — [arXiv 2607.24223](https://arxiv.org/abs/2607.24223)
- **SearchWeaver** jointly optimizes corpus artifacts, tools and instructions from trajectories: BrowseComp-Plus 71.6% to 78.4% with GPT-5.4-nano over plain DCI, and BRIGHT nDCG@10 45.7 to 55.0. Interface design is corpus-specific — [arXiv 2610.29250](https://arxiv.org/abs/2610.29250)
- Harness effects remain as large as retriever effects (the same model scored 93.1 vs 76.7 across harnesses) — [arXiv 2605.15184](https://arxiv.org/abs/2605.15184)

### Inferences
- The KB should be materialized as a markdown file tree with a generated navigation layer, not only as a vector index. Concretely:
  - entity, topic and procedure pages with intent summaries;
  - stable source IDs;
  - typed links (`applies_to`, `supersedes`, `exception_of`);
  - a compact `index.md` (≤ about 8–10KB) suitable for always-loading.
  The Airbnb and Vercel results point the same way; Karpathy's pattern is the same design.
- Use one level of disclosure (index, then page, then source). Avoid multi-level routing hierarchies.
- Keep always-loaded files tiny, give reasons for each rule, and lint them. Instruction files act as authority over retrieved evidence, so stale rules are actively harmful. Put KB content behind tools, not in the always-loaded prompt, except for the index.
- Grep/read over raw text is a must-have tool. At large scale it needs a retriever to scope a workspace first (Dr-DCI pattern).

### Gaps
- No controlled comparison of "LLM wiki navigation layer" versus "chunk index" across multiple domains. The Airbnb ablation is underpowered.
- I could not read the OpenAI harness-engineering primary text (HTTP 403).
- No measured benefit of llms.txt for agents was found.

## 3. Knowledge-base tool design for agents: signatures, filters, snippets vs full docs, pagination, citations, MCP KB servers, tool descriptions

### Takeaway
The highest-evidence design is a small set of consolidated, well-described tools:
- `search` returning compact ranked snippets with stable IDs and titles, with filters, pagination and a `response_format` switch;
- `read/fetch` returning a full document or section by ID or path, in markdown;
- optionally `grep`/regex over the text, and a structural navigation aid.

Commercial KB MCP servers (Glean, Notion, Azure) converge on exactly this search-then-fetch pair. Tool descriptions are high-leverage but fragile: 97% of MCP descriptions have defects, and edits can shift tool usage tenfold. Return format, citation contracts and delivery mode (inline vs file) measurably change outcomes.

### Cited Findings
- Anthropic's tool-writing guidance:
  - Prefer targeted tools (`search_contacts` over `list_contacts`) and consolidate multi-step calls.
  - Namespace tools (`asana_projects_search`).
  - Return high-signal fields and resolve UUIDs to names or 0-indexed IDs, which "improved Claude's retrieval precision."
  - Offer `response_format: concise|detailed` (72 vs 206 tokens in their example).
  - Paginate, filter and truncate with defaults. Claude Code caps tool responses at 25,000 tokens.
  - Write actionable errors and steer toward "many small targeted searches."
  - Write descriptions "as to a new hire."
  - Measure accuracy, runtime, call count, tokens and errors.
  [vendor, older: Sep 2025] — [Anthropic Engineering](https://www.anthropic.com/engineering/writing-tools-for-agents)
- A tool-testing agent that rewrote flawed MCP tool descriptions cut later agents' task time by 40% [vendor, older: 2025] — [Anthropic multi-agent post](https://www.anthropic.com/engineering/multi-agent-research-system)
- **MCP description quality:** across 856 tools on 103 servers, 97.1% of descriptions have at least one smell and 56% fail to state their purpose. Augmenting descriptions raised median task success by 5.85 pp, but steps rose 67.46% and 16.67% of cases regressed. Compact variants preserved reliability — [arXiv 2602.14878](https://arxiv.org/abs/2602.14878)
- Description edits can make a tool get more than 10x the usage from GPT-4.1 and Qwen2.5-7B when it competes with alternatives. Tool choice is "surprisingly fragile" — [arXiv 2505.18135](https://arxiv.org/abs/2505.18135)
- 9.93% of 19,200 description-code pairs from 2,214 real MCP servers are inconsistent (description says one thing, code does another) — [arXiv 2606.04769](https://arxiv.org/abs/2606.04769)
- Retrieving tool descriptions (RAG-MCP) cut prompt tokens by more than 50% and raised tool-selection accuracy from 13.62% to 43.13% [older: 2025] — [arXiv 2505.03275](https://arxiv.org/abs/2505.03275). Under tight context budgets (8K), compressed tool schemas restored RAG function (+20.5 pp EM). At 32K the effect vanished — [arXiv 2605.26165](https://arxiv.org/abs/2605.26165)
- **Snippets vs structure:** flat snippet lists from code search leave agents unable to tell siblings apart. Reorganizing hits into a file-centered navigation scaffold improved function-level localization, and ablations attribute this to structured evidence organization — [arXiv 2609.08355](https://arxiv.org/abs/2609.08355)
- **Result depth:** KARL's agent degraded sharply at 40 docs per search versus 10–20 [vendor] — [arXiv 2603.05218](https://arxiv.org/abs/2603.05218). Pi-Serini's deep cached-hit pagination added about 25 pp surfaced recall — [arXiv 2605.10848](https://arxiv.org/abs/2605.10848). Together these favor small pages with cheap "next page" over large top-k dumps.
- **Delivery mode:** inline results vs results written to a file the agent must read flipped grep-vs-vector winners (Codex/GPT-5.4 grep fell from 93.1 to 55.2 under file delivery) — [arXiv 2605.15184](https://arxiv.org/abs/2605.15184)
- **Citations:**
  - Airbnb enforces a code-level citation contract: every quoted snippet must be a normalized substring of the cited article, and non-conformant writes are rejected. 99.7% of 1,769 snippets were byte-identical [vendor] — [arXiv 2610.14428](https://arxiv.org/abs/2610.14428)
  - CITECHOICE: structured rendering of a document concentrated citation credit (+0.50 citations per answer). Rank-1 vs rank-5 citation gap was 42.3 pp observationally but only +7.9 pp under controlled reorder. 15% of binary citation decisions flip under re-decoding — [arXiv 2609.15164](https://arxiv.org/abs/2609.15164)
  - Evidence-based generation with line-level citations exposes grounding failures invisible to answer-only scoring — [arXiv 2610.26951](https://arxiv.org/abs/2610.26951)
- **Commercial KB MCP servers (2026):**
  - Glean's remote MCP server defaults to a managed toolset: `search`, `read_document`, `code_search`, `employee_search`, `user_activity`, `memory`, `memory_schema` and `web_search`. Optional tools include `chat` and `knowledge_graph_query`. Glean advises "avoid creating one server with all tools enabled" because it reduces tool-selection accuracy, and recommends purpose-scoped servers per audience [vendor] — [Glean docs](https://docs.glean.com/administration/platform/mcp/create-mcp-servers)
  - Notion's MCP exposes `notion-search`, `notion-connector-search` (Slack, Google Drive), `notion-fetch`, list tools and `notion-list-page-backlinks` [vendor] — [Notion developers](https://developers.notion.com/guides/mcp/tools-search)
  - Azure AI Search knowledge bases can be queried "using the retrieve action or MCP endpoint" [vendor] — [Microsoft Learn](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview)
- **Programmatic tool calling:** the model writes code that calls tools, so intermediate results never enter context. Anthropic reports -37% tokens and +2.9 pp on internal knowledge retrieval [vendor, older: Nov 2025; detailed in earlier notes] — [Anthropic advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use)

### Inferences
- **Minimal KB tool surface:**
  1. `kb_search(query, filters{doc_type, domain, effective_date, jurisdiction, status}, mode{hybrid|lexical|semantic}, limit=10, cursor, response_format)`, returning `[{id, title, path, section, snippet with highlights, score, effective_date, source_uri}]`.
  2. `kb_read(id|path, section?, range?)`, returning markdown with line numbers or anchors for citation.
  3. `kb_grep(pattern, path_glob)` over the materialized markdown.
  4. `kb_related(id, relation?)`, following typed links and backlinks.
  5. Optional `kb_plan_search(question)` as a first move.
- Keep descriptions compact but complete (purpose, when to use, formats, filters). Test variants with evals, because both tool choice and step count shift with description edits.
- Enforce citation validity in code (substring or anchor check), not by prompt.

### Gaps
- I found no controlled study comparing snippet length or page size (for example 200 vs 1,000 tokens) for agent search tools on domain KBs.
- I found no independent evaluation of Glean, Notion or Confluence MCP retrieval quality.

## 4. Agent memory systems as knowledge bases: MemGPT/Letta, A-MEM, Mem0, Zep/Graphiti, MemoryOS, MIRIX, LangMem, the memory taxonomy, benchmarks, vendor-claim reliability, and consolidation into knowledge

### Takeaway
Memory systems are KBs written by agents. Architectures range from OS-style tiers (MemGPT, MemoryOS) and Zettelkasten notes (A-MEM) to extracted facts (Mem0), temporal KGs (Zep/Graphiti) and multi-type stores (MIRIX), and in 2026 there is a strong convergence on plain files plus git (Letta MemFS, Claude memory tool, Claude Code auto memory).

Benchmark evidence is weak and contested:
- LoCoMo conversations fit in context, a full-context baseline beats several vendors, the judge is lenient, and the answer key is partly corrupted.
- Vendor numbers conflict: Mem0 66.9 vs Zep 75.1 vs Mem0's "Zep 58.4", and Mem0 later claims 92.5.
- Independent benchmarks (MemoryAgentBench, MemDerive, MemoryArena) show commercial memory layers often underperform BM25 or long context.
- A plain filesystem agent scored 74% on LoCoMo.
The durable lesson for a KB is consolidation: distilling episodes into reusable playbooks, workflows and procedures (ACE, ReasoningBank, AWM, Memp) improves agents, and that output is exactly an SOP and rules KB.

### Cited Findings
**Architectures (by first release)**
- **MemGPT** (UC Berkeley, Oct 2023; now Letta) does OS-style "virtual context management": in-context core memory plus archival and recall storage, paged in and out by the agent through function calls and interrupts [older: 2023] — [arXiv 2310.08560](https://arxiv.org/abs/2310.08560)
- **Zep/Graphiti** (Zep AI, Jan 2025) is a temporally aware knowledge graph that synthesizes conversations and business data with historical validity. It reports 94.8% vs MemGPT's 93.4% on DMR, and up to +18.5% accuracy with 90% lower latency on LongMemEval [vendor, older: 2025] — [arXiv 2501.13956](https://arxiv.org/abs/2501.13956)
- **A-MEM** (Rutgers et al., Feb 2025) uses Zettelkasten-style notes with keywords, tags and context descriptions, auto-linked to related notes. New notes can trigger "memory evolution" of old ones [older: 2025] — [arXiv 2502.12110](https://arxiv.org/abs/2502.12110)
- **Mem0** (Mem0, Apr 2025) extracts, consolidates (add, update, delete) and retrieves salient facts, with an optional graph variant. It reports +26% LLM-judge over OpenAI memory, 91% lower p95 latency and more than 90% token savings versus full context on LoCoMo [vendor, older: 2025] — [arXiv 2504.19413](https://arxiv.org/abs/2504.19413)
- **MemoryOS** (BUPT et al., Jun 2025) has short-, mid- and long-term tiers with FIFO and segmented-page promotion. It reports +49.11% F1 on LoCoMo with GPT-4o-mini [older: 2025] — [arXiv 2506.06326](https://arxiv.org/abs/2506.06326). MemOS (MemTensor) unifies parametric, activation and plaintext memory as "MemCubes" — [arXiv 2505.22101](https://arxiv.org/abs/2505.22101)
- **MIRIX** (Jul 2025) has six memory types (Core, Episodic, Semantic, Procedural, Resource, Knowledge Vault) managed by multiple agents. It reports 85.4% on LoCoMo and +35% over RAG on ScreenshotVQA [older: 2025] — [arXiv 2507.07957](https://arxiv.org/abs/2507.07957)
- **Taxonomy:** the 2026 survey organizes memory by substrate (parametric vs external), cognitive mechanism (sensory, working, episodic, semantic, procedural) and subject (user vs agent experience). It notes "hundreds of papers released in 2025" and a shift toward RL-learned memory operations and shareable skills — [arXiv 2602.06052](https://arxiv.org/abs/2602.06052). LangChain maps episodic memory to few-shot examples, procedural to instructions and semantic to facts [vendor] — [LangChain blog](https://www.langchain.com/blog/context-engineering-for-agents)
- **File-based memory in 2025–2026:**
  - Anthropic's memory tool (Sep 29, 2025) is client-side CRUD over a memory directory. Memory plus context editing gave +39% on an internal agentic-search eval, and context editing alone +29%. Context editing cut tokens by 84% on a 100-turn web-search eval [vendor] — [Claude blog](https://claude.com/blog/context-management)
  - Letta "Context Repositories" (Feb 12, 2026; now MemFS) keep git-backed memory files. The file tree is always in the prompt, files carry frontmatter descriptions, and `system/` files are pinned. Sleep-time reflection subagents write in worktrees, and a "defrag" skill restructures memory into 15–25 files. No evaluation numbers were given [vendor] — [Letta blog](https://www.letta.com/blog/context-repositories)
- **Hierarchical file-like memory:** HORMA organizes experience as summarized entities linked to raw trajectories and uses an RL-trained navigator. It uses at most 22.17% of baseline tokens on long conversations — [arXiv 2606.11680](https://arxiv.org/abs/2606.11680). LCM ("Lossless Context Management") keeps a hierarchical summary DAG with lossless pointers to originals and beats Claude Code on OOLONG from 32K to 1M tokens [vendor] — [arXiv 2605.04050](https://arxiv.org/abs/2605.04050)
- **Simple baselines:**
  - Event-centric EDU propositions (self-contained statements with normalized entities and source-turn attribution), held in a light graph, match or beat strong baselines on LoCoMo and LongMemEval-S with much shorter QA contexts — [arXiv 2511.17208](https://arxiv.org/abs/2511.17208)
  - Evidence-gap-driven iterative retrieval (EviMem) improves over MIRIX on LoCoMo multi-hop (65.9% to 85.2%) at 4.5x lower latency — [arXiv 2604.27695](https://arxiv.org/abs/2604.27695)
  - HippoRAG 2 (Personalized PageRank over passages) beats standard RAG on factual, sense-making and associative memory — [arXiv 2502.14802](https://arxiv.org/abs/2502.14802)

**Benchmarks**
- **LoCoMo** (Snap/UNC, Feb 2024, ACL 2024): about 300 turns and 9K tokens on average over up to 35 sessions [older: 2024] — [arXiv 2402.17753](https://arxiv.org/abs/2402.17753)
- **LongMemEval** (UCLA, Oct 2024, ICLR 2025): 500 questions on extraction, multi-session reasoning, temporal reasoning, knowledge updates and abstention. Commercial assistants and long-context LLMs drop 30%. Recommended designs: session decomposition, fact-augmented keys and time-aware query expansion [older: 2024] — [arXiv 2410.10813](https://arxiv.org/abs/2410.10813)
- **LongMemEval-V2** (May 2026): 451 questions over web-agent trajectories of up to 115M tokens (workflow knowledge, environment gotchas). Storing trajectories as files and letting a coding agent gather evidence (AgentRunbook-C) scored 72.5%, against the best RAG at 48.5% and an off-the-shelf coding agent at 69.3%. Latency is high — [arXiv 2605.12493](https://arxiv.org/abs/2605.12493)
- **MemoryAgentBench** (UCSD et al., Jul 2025; independent of vendors):
  - Accurate retrieval: HippoRAG-v2 65.1 and BM25 60.5, against Zep 37.5, MemGPT 34.3 and Mem0 32.6.
  - Long-range understanding: long-context models lead (GPT-5-mini 66.2), with Mem0 20.7.
  - Selective forgetting: "all methods fail on the multi-hop situation."
  - No system covers all four competencies.
  — [arXiv 2507.05257](https://arxiv.org/abs/2507.05257)
- **MemDerive** (Oct 2026): on derived state computed by rules over evolving events, "every memory system falls behind simple BM25 retrieval." The same reader reaches 96.01% when given the supporting events. Most failures are "ungathered" evidence. Recommendations: store rules with versions and maintain derived states through recorded dependencies — [arXiv 2610.25373](https://arxiv.org/abs/2610.25373)
- **MemoryArena** (Feb 2026): agents "near-saturated" on LoCoMo perform poorly on interdependent multi-session agentic tasks — [arXiv 2602.16313](https://arxiv.org/abs/2602.16313)

**Reliability of vendor claims**
- Letta (MemGPT authors, Aug 12, 2025): GPT-4o-mini agents storing LoCoMo histories in files, with `grep`, `search_files`, `open` and `close` tools, scored 74.0%, against Mem0's reported best of 68.5%. Letta said Mem0 did not explain how it ran MemGPT. They argue memory quality depends more on the agent's tool-use ability than on the memory mechanism [vendor, a competitor] — [Letta blog](https://www.letta.com/blog/benchmarking-ai-agent-memory)
- Zep (May 6, 2025) says Mem0 misconfigured Zep: both speakers were given the user role, timestamps were appended to text instead of `created_at`, and searches ran sequentially. Zep reports 75.14% ±0.17 against Mem0-Graph's 68.44%, and a full-context baseline of about 72.9% that beat Mem0's best. It also notes that LoCoMo conversations (16–26k tokens) fit in context and that the dataset has ground-truth errors [vendor, a competitor] — [Zep blog](https://www.getzep.com/blog/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/)
- Mem0's counter (GitHub issue, secondary): Zep's "84%" claim included the adversarial category, and the corrected figure is 58.44% [secondary, not verified] — [search summary of dispute; see D'Erme](https://dev.to/gde03/the-ai-memory-benchmark-everyone-quotes-forbids-saying-i-dont-know-o1n)
- Mem0 later claimed 92.5 on LoCoMo, 94.4 on LongMemEval, and 64.1 / 48.6 on BEAM at 1M / 10M tokens, at under 7k tokens per retrieval (page updated May 2026). The docs page (Nov 2026) now shows 92.5 / 94.4 at a top_200 retrieval budget with about 6.8–7.0k tokens per query. It says scores come from the managed platform with proprietary optimizations, carry ±1 point of judge variance, and that BEAM-10M temporal reasoning is only 16.3. Earlier PyPI and docs versions listed 91.6 / 93.4 [secondary for the older figures] [vendor] — [Mem0 research](https://mem0.ai/research-3); [Mem0 docs](https://docs.mem0.ai/core-concepts/memory-evaluation)
- An independent critique (D'Erme, 2026; citing the `dial481/locomo-audit` repo, which I did not verify) makes four points. Mem0's harness scores only categories 1–4, dropping the 446 adversarial abstention questions (22.5%). Its prompt says "NEVER say 'not specified'". The judge accepts ±14 days and ±50% durations. The judge over-accepted 62.8% of deliberately wrong answers, and the answer key caps achievable accuracy near 93.6 [secondary/independent blog] — [DEV Community](https://dev.to/gde03/the-ai-memory-benchmark-everyone-quotes-forbids-saying-i-dont-know-o1n)
- Chroma's context-rot report found models do far better on focused LongMemEval prompts (about 300 tokens) than on full ones (about 113k tokens), so memory benchmarks are partly benchmarks of context-length tolerance [vendor, older: Jul 2025] — [Chroma research](https://www.trychroma.com/research/context-rot)

**Consolidation: turning experience into knowledge (procedural and semantic)**
- **Agent Workflow Memory** (CMU, Sep 2024) induces reusable workflows from trajectories: +24.6% relative success on Mind2Web and +51.1% on WebArena [older: 2024] — [arXiv 2409.07429](https://arxiv.org/abs/2409.07429)
- **Dynamic Cheatsheet** (Apr 2025) keeps an adaptive test-time memory of strategies [older: 2025] — [arXiv 2504.07952](https://arxiv.org/abs/2504.07952)
- **ACE** (Stanford/SambaNova, Oct 2025) treats contexts as evolving "playbooks" with generator, reflector and curator roles. Incremental structured updates avoid "brevity bias" and "context collapse." It reports +10.6% on agents and +8.6% on finance, and matched the top AppWorld production agent with a smaller model [older: 2025] — [arXiv 2510.04618](https://arxiv.org/abs/2510.04618)
- **ReasoningBank** (Google, Sep 2025) distills generalizable strategies from both successes and failures. It beats raw-trajectory and success-only memories on web and SWE tasks [older: 2025] — [arXiv 2509.25140](https://arxiv.org/abs/2509.25140)
- **Memp** (ZJU, Aug 2025) builds procedural memory as step-by-step instructions plus script abstractions, with update and deprecation. Memory built from a strong model transfers to weaker models [older: 2025] — [arXiv 2508.06433](https://arxiv.org/abs/2508.06433)
- **AFTER benchmark** (Jun 2026; 382 enterprise tasks, 22 procedural skills): one refinement round gives +3.7 to 6.7 points. Skills evolved from multi-model traces reach 73.1% cross-model accuracy, but some skills overspecialize to roles — [arXiv 2606.23127](https://arxiv.org/abs/2606.23127)

### Inferences
- For this toolkit, "memory" should be modelled as KB write-back with provenance, not as a separate opaque service. Concretely:
  - agent-learned facts, gotchas and resolved Q&A become candidate pages in the same markdown KB, flagged `status: proposed` with source trajectory IDs;
  - a periodic consolidation pass (ACE/AWM-style) merges them into procedures and rules after review.
- Store rules with versions and validity intervals, and keep derived facts linked to their inputs. MemDerive and Zep both point to temporal and derivation metadata as what separates good memory from bad.
- Do not select a memory vendor based on LoCoMo or LongMemEval numbers. Run your own task-level eval, including abstention and knowledge updates.

### Gaps
- LangMem (LangChain) documentation was not read this pass, so it is not characterized beyond LangChain's memory-type framing.
- I found no independent replication of Mem0's 2026 92.5 / 94.4 claims or of Zep's latest figures.
- No study measures consolidation (episodes to SOP pages) quality against human-authored SOPs.

## 5. Long context vs retrieval for knowledge bases; context rot; prompt caching and CAG

### Takeaway
Long context often matches or beats chunk RAG when the whole KB fits and the model is strong (LOFT, Self-Route, LaRA), and it avoids RAG's "all required chunks" recall failure. But accuracy decays with length and especially with competing, similar content (context rot, NoLiMa, distractors), and cost scales with every token on every call. For a domain KB of policies, which is full of near-duplicate clauses and versions, that is exactly the bad case.

Caching changes the economics. Cached reads cost 0.1x (0.05x on the newest Claude models), so a stable, always-loaded prefix (index, core rules) is cheap. CAG (preload the whole KB into a cached KV) is viable only for small, static KBs.

### Cited Findings
- **LOFT** (Google DeepMind, Jun 2024): long-context LMs "rival state-of-the-art retrieval and RAG systems" on in-context retrieval up to millions of tokens, but struggle with compositional, SQL-like reasoning, and prompting strongly matters [older: 2024] — [arXiv 2406.13121](https://arxiv.org/abs/2406.13121)
- **Self-Route** (Google, EMNLP 2024 industry):
  - Long context beats RAG on average: Gemini-1.5-Pro 49.70 vs 37.33, GPT-4o 48.67 vs 32.60.
  - Predictions are identical for about 63% of queries.
  - Routing by self-reflection uses 38–61% of long-context tokens with comparable accuracy.
  - RAG fails on multi-step, vague, long or implicit queries.
  [older: 2024] — [arXiv 2407.16833](https://arxiv.org/abs/2407.16833)
- "Retrieval meets Long Context" (NVIDIA, Oct 2023): 4K plus retrieval is comparable to 16K fine-tuned, and retrieval helps even 32K models [older: 2023] — [arXiv 2310.03025](https://arxiv.org/abs/2310.03025)
- "LC vs RAG: An Evaluation and Revisits" (Dec 2024): long context generally beats RAG on Wikipedia QA. Summarization-based retrieval is comparable to long context and chunk retrieval lags. RAG has the advantage on dialogue and general queries [older: 2024] — [arXiv 2501.01880](https://arxiv.org/abs/2501.01880)
- **LaRA** (Alibaba, Feb 2025; 2,326 cases): "no silver bullet". The best choice depends on model size, long-context ability, context length, task type and chunk characteristics [older: 2025] — [arXiv 2502.09977](https://arxiv.org/abs/2502.09977)
- **DOS RAG** (Stanford, Jun 2025): simple retrieve-then-read that preserves original passage order matches or beats ReadAgent and RAPTOR under matched token budgets [older: 2025] — [arXiv 2506.03989](https://arxiv.org/abs/2506.03989)
- **The bottleneck is retrieval, not reading** (Oct 2026; 10 frontier and 3 open models): similarity retrieval surfaces any relevant chunk far more reliably than all required chunks for multi-fact queries, and chunking destroys document meta-information needed for identity-bearing queries. Long-context models avoid both failures — [arXiv 2610.26951](https://arxiv.org/abs/2610.26951)
- **Context rot evidence:**
  - Lost in the Middle (Stanford, 2023; TACL 2024): performance is highest when evidence sits at the start or end [older: 2023] — [arXiv 2307.03172](https://arxiv.org/abs/2307.03172)
  - NoLiMa (Adobe, Feb 2025; ICML 2025): with minimal lexical overlap, 11 of 13 models fall below 50% of their short-context baseline at 32K, and GPT-4o drops from 99.3% to 69.7% [older: 2025] — [arXiv 2502.05167](https://arxiv.org/abs/2502.05167)
  - Chroma (Jul 2025; 18 models): degradation with length even on simple tasks, compounding distractor effects, and shuffled haystacks beating coherent ones [vendor, older: 2025] — [Chroma](https://www.trychroma.com/research/context-rot)
  - "Length Is Cheap, Competition Is Not" (Nov 2026; 0.5–3B models): neutral filler costs nothing up to 32K (accuracy 0.97–1.00). Evidence-format distractors drop accuracy to 0.16–0.33, and a single rival value multiplies loss 9–110x. Attention mass on the evidence explains up to 58% of variance; log length explains at most 8% — [arXiv 2611.04169](https://arxiv.org/abs/2611.04169)
- **Recursive and folding alternatives:** Recursive Language Models (MIT, Dec 2025) treat the long prompt as an environment the model programmatically inspects and sub-calls. Median gains with GPT-5 are +26% over compaction and +13% over Claude Code at comparable cost — [arXiv 2512.24601](https://arxiv.org/abs/2512.24601). Context-Folding uses RL-learned branch-and-fold to match ReAct with a 10x smaller active context — [arXiv 2510.11967](https://arxiv.org/abs/2510.11967)
- **CAG** ("Don't Do RAG", Dec 2024) preloads all documents into the context and caches the KV state, eliminating retrieval latency and selection errors. It is suited to "a constrained knowledge base" [older: 2024] — [arXiv 2412.15605](https://arxiv.org/abs/2412.15605)
- **Prompt caching economics (Anthropic docs, Nov 2026):**
  - Cache writes cost 1.25x (5-min TTL) or 2x (1-hour).
  - Reads cost 0.1x base input, 0.05x on Opus/Sonnet 5.5, and 0.025x on Fable/Mythos 5.1.
  - Prefix order is tools, then system, then messages, and any change to tool definitions invalidates everything downstream.
  - Up to 4 breakpoints; minimum cacheable length is 512 tokens on current models.
  [vendor] — [Claude docs: prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching). Manus reports a 10x cached/uncached price gap and treats KV-cache hit rate as its key production metric [vendor] — [Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)

### Inferences
- Use long context as a working set, not as the KB:
  - always-load a cached prefix (KB index, core definitions, top rules), which is cheap under caching;
  - retrieve pages just in time;
  - when a question needs a whole document (for example a full policy), read the whole document rather than chunks, because document-level reading avoids the chunking failures in 2610.26951.
- Versioned policies are the worst case for context rot, because the old and new clause are rivals with the same format. The KB should expose only the effective version by default, with superseded versions behind an explicit filter.
- CAG fits only small, static sub-KBs (for example a 50-page handbook). For anything else, keep tool definitions stable so the cache prefix survives.

### Gaps
- No 2026 independent LOFT-style re-evaluation with current frontier 1M-token models on enterprise policy corpora was found.
- No cost-normalized comparison of CAG vs agentic retrieval on a real domain KB.

## 6. The most effective agent access design for a domain knowledge base (recommended design)

### Takeaway
Ship the KB as three synchronized views behind one small tool surface:
- (a) a markdown file tree with an LLM-generated navigation layer and an always-loadable index;
- (b) a hybrid lexical+semantic index with reranking and filters;
- (c) a typed link graph of supersedes, applies-to and exception relations.

Expose it through search, read, grep and related tools (via MCP and as plain files) plus an optional "first move" planner. Bound the agent loop and enforce citations in code. Write agent-learned knowledge back as proposed pages that are consolidated under review. Every element below has at least one controlled or deployment result behind it, but most results are single-study or vendor-reported.

### Cited Findings
- Navigation layer plus hybrid retrieval plus code-enforced citations matched production RAG on guidance and beat it on evidence sufficiency for SOP and policy corpora [vendor, single-study] — [arXiv 2610.14428](https://arxiv.org/abs/2610.14428)
- An always-present compact index (about 8KB) beat agent-decided lookups [vendor, single-study] — [Vercel](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals). One-level disclosure scales better than raw navigation, while two levels hurt — [arXiv 2607.17598](https://arxiv.org/abs/2607.17598)
- Hybrid beats BM25-only or dense-only in the agent loop (83.3 vs 78.0 / 78.8) [vendor] — [arXiv 2610.14428](https://arxiv.org/abs/2610.14428). Fixed RRF hybrid beats adaptive routing — [arXiv 2606.21553](https://arxiv.org/abs/2606.21553). Reranking is the most cost-effective accuracy lever — [arXiv 2601.14224](https://arxiv.org/abs/2601.14224)
- Grep/shell over raw text is strong but needs retrieval-scoped workspaces at scale — [arXiv 2605.05242](https://arxiv.org/abs/2605.05242); [arXiv 2606.14885](https://arxiv.org/abs/2606.14885)
- A first-move decompose, search and rerank step lifts accuracy — [arXiv 2609.14412](https://arxiv.org/abs/2609.14412). Two iterations give 95% of the gains — [arXiv 2606.21553](https://arxiv.org/abs/2606.21553). Stagnation controls cut 14 calls per query — [arXiv 2608.15191](https://arxiv.org/abs/2608.15191)
- Keep 10–20 results per search page — [arXiv 2603.05218](https://arxiv.org/abs/2603.05218). Use concise and detailed response formats and natural-language IDs — [Anthropic](https://www.anthropic.com/engineering/writing-tools-for-agents)
- Always-loaded instruction files must stay small, carry reasons and be linted, because agents obey stale files over evidence — [arXiv 2610.30571](https://arxiv.org/abs/2610.30571); [arXiv 2608.11095](https://arxiv.org/abs/2608.11095); [arXiv 2602.11988](https://arxiv.org/abs/2602.11988)
- File-based memory with git and consolidation subagents is the 2026 vendor direction [vendor] — [Letta](https://www.letta.com/blog/context-repositories); [Claude](https://claude.com/blog/context-management). Distilled playbooks and workflows improve agents — [arXiv 2510.04618](https://arxiv.org/abs/2510.04618); [arXiv 2409.07429](https://arxiv.org/abs/2409.07429)
- Interfaces are corpus-specific and can be auto-optimized from trajectories — [arXiv 2610.29250](https://arxiv.org/abs/2610.29250)
- Commercial KB MCP servers converge on search plus read/fetch, purpose-scoped servers and permission enforcement at query time [vendor] — [Glean](https://docs.glean.com/administration/platform/mcp/create-mcp-servers); [Notion](https://developers.notion.com/guides/mcp/tools-search)

### Inferences
**Recommended design (synthesis; my inference from the above, not a tested system).**

1. **Materialized KB layout (files are the system of record and the agent interface):**
   - `kb/index.md` is an always-loadable catalog (≤ about 8–10KB) listing domains, then page titles with one-line intents.
   - `kb/<domain>/<page>.md` holds topic, entity, procedure and rule pages. YAML frontmatter carries:
     - `id`, `type: policy|sop|rule|concept|faq`;
     - `status: effective|draft|superseded|proposed`;
     - `effective_from`, `effective_to`, `owner`, `jurisdiction/scope`;
     - `source_ids` (stable, pointing to raw documents and spans);
     - `links: {supersedes, superseded_by, applies_to, exception_of, see_also}`;
     - a one-paragraph `summary/intent`.
   - `raw/` holds immutable converted sources (markdown with anchors) for quoting.
   - `log.md` is an append-only change log.
   - A per-domain `AGENTS.md`/`SKILL.md` gives at most about 100 lines of usage rules, each with reasons.
2. **Indexes built from those files:** BM25 plus dense (optionally late-interaction) over page and section chunks, with document-level metadata kept on each chunk to avoid identity loss; a reranker; and a link graph for `related` traversal and "effective version" resolution.
3. **Tools (MCP server plus CLI, same semantics):** `kb_search` (hybrid, filters, 10 results per page, cursor, concise/detailed, default `status=effective`), `kb_read` (whole page or section, with line anchors), `kb_grep`, `kb_related`, `kb_plan_search` (first move), and `kb_propose` (write-back of learned knowledge as `status: proposed` with provenance). Keep tool definitions static to preserve the prompt cache.
4. **Agent policy:** load the index, run the first move, do at most 2–3 search or read rounds with stop criteria, answer with citations to `raw/` anchors, and validate citations as substrings or anchors in code. If evidence is missing, abstain and report the gap. The Airbnb data show most residual failures were missing corpus content, so gap reports feed curation.
5. **Lifecycle hooks (handled in other tracks):** lint for contradictions, orphans and stale pages; consolidate proposed pages; and regenerate the index after ingest.
6. **Evaluation:** task-level evals on held-out domain questions, measuring answer correctness and evidence sufficiency (two metrics, as Airbnb did), tokens, calls and latency, and comparing harnesses. Do not rely on public memory or RAG leaderboards.

### Gaps
- This design has not been tested end to end. The strongest supporting evidence (Airbnb, Vercel) is vendor-reported, single-domain and underpowered for ablations.
- Unknowns that need the toolkit's own evals: optimal page granularity, index size limits, and whether typed links measurably help agents (the Airbnb "weakened typed links" ablation showed only a non-significant drop from 110 to 107 of 132).
- Permission-aware filtering inside file-based KBs (as opposed to Glean-style query-time ACLs) is unaddressed in the agent-side literature I found.
