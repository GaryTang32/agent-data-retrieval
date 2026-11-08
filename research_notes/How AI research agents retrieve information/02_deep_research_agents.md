# Track 02: Deep research agents. How OpenAI, Anthropic, Google, Perplexity, xAI, Moonshot, Alibaba, Manus, Microsoft and open-source systems turn a question into a cited report: agent loop, planning, multi-agent orchestration, training, benchmarks and evidence (as of November 2026)

Scope: the research agent's control loop, architecture and training. Search backends, coding-agent code retrieval, page reading and citation mechanics, and ranking signals belong to other tracks and are mentioned only where a deep research system's design depends on them. The basics of agentic RAG, Search-R1-style RL, BrowseComp-Plus retriever effects and Anthropic's headline multi-agent numbers already appear in `Searchable agent knowledge base construction/05_agentic_search_memory.md` §1. This file adds product architectures, loop mechanics, budgets, training recipes, the 2026 evidence base and failure analyses.

Labels used: **[vendor]** means the vendor reports it about its own product. **[author]** means the paper's authors report it about their own method. **[independent]** means a third party measured it. **[older: YYYY]** marks information from before 2026 that may be superseded.

---

## 1. Product architectures: how each mainstream system is built (official sources)

### Takeaway
Every mainstream system is the same kind of thing. A reasoning model runs a long tool loop (search, open/fetch, read, Python) against an external **web search index**, then writes a report with inline citations. Nobody "vectorizes the internet" locally. The systems differ in four ways:
- **Single agent vs orchestrator-worker.** OpenAI's deep research is a single RL-trained agent. Claude Research, Kimi Agent Swarm, Tongyi Heavy and Manus Wide Research are multi-agent.
- **Training.** Some use end-to-end RL on browsing tasks: OpenAI, Gemini, Kimi, Tongyi. Others prompt a general frontier model: Claude Research at launch, Perplexity on Claude Opus, Microsoft Researcher.
- **Explicit plan steps.** Gemini shows an editable plan. ChatGPT clarifies first. Perplexity Pro Search plans before executing.
- **Budget.** It ranges from about 2–4 minutes (Perplexity) to 5–30 minutes (OpenAI) to as much as 60 minutes and about 160 queries (Gemini Max).

### Cited Findings

**OpenAI deep research (ChatGPT, Feb 2025 → GPT-5.2-based in Feb 2026)**
- Deep research "is powered by an early version of OpenAI o3 that is optimized for web browsing." Its training [older: 2025]:
  - It was trained on new browsing datasets and learned the core browsing actions ("searching, clicking, scrolling, interpreting files") and a sandboxed Python tool.
  - It learned to "reason through and synthesize a large number of websites… through reinforcement learning training on these browsing tasks."
  - Training tasks range "from objective auto-gradable tasks with ground truth answers, to more open-ended tasks with accompanying rubrics." Responses "are graded… using a chain-of-thought model as a grader."
  — [OpenAI Deep Research System Card, Feb 25 2025](https://cdn.openai.com/deep-research-system-card.pdf)
- In ChatGPT, a second, custom-prompted o3-mini summarizes the chains of thought shown to users. The Python tool has no internet access [vendor, older: 2025] — [System Card](https://cdn.openai.com/deep-research-system-card.pdf)
- Before research starts, ChatGPT uses "an intermediate model (like gpt-4.1)" to ask clarifying questions. The API skips this step: "the model expects fully-formed prompts up front." OpenAI recommends a lightweight prompt-rewriter model in front of the API. In the API the model "autonomously plans sub-questions, uses tools like web search and code execution," and returns inline citations (start/end index, title, URL) plus every intermediate reasoning step, web search call and code call [vendor, older: 2025] — [OpenAI Cookbook: Introduction to the Deep Research API](https://raw.githubusercontent.com/openai/openai-cookbook/main/examples/deep_research_api/introduction_to_deep_research_api.ipynb)
- **API (June 26 2025):**
  - Models are `o3-deep-research` ($10/$40 per M input/output tokens) and `o4-mini-deep-research` ($2/$8), with `background` mode and webhooks.
  - Web search costs $10 per 1K calls on o-series models.
  - A community reply notes that retrieved search content is also billed at the model's token rate.
  - MCP tools let deep research query private knowledge stores. The cookbook's example MCP server fronts OpenAI's vector-store file search.
  [vendor, older: 2025] — [OpenAI Developer Community announcement](https://community.openai.com/t/deep-research-in-the-api-webhooks-and-web-search-with-o3/1299919); [Cookbook](https://raw.githubusercontent.com/openai/openai-cookbook/main/examples/deep_research_api/introduction_to_deep_research_api.ipynb)
- OpenAI's deep research team says end-to-end training beats hand-built agent graphs, which "fall down pretty quickly in the real world." The model "is trained directly end-to-end to solve the kinds of tasks that users are using it to solve." Data quality "is probably the biggest determining factor." Runs take about 5–30 minutes [vendor interview, older: 2025] — [Sequoia Training Data podcast](https://sequoiacap.com/podcast/training-data-deep-research)
- **Timeline** [secondary, compiled with citations]:
  - April 2025: an o4-mini-based "lightweight" version for overflow and free users.
  - February 2026: a GPT-5.2-based model, site-restricted search, MCP connections and real-time steering.
  - March 26 2026: legacy o3 mode removed.
  — [Wikipedia: ChatGPT Deep Research](https://en.wikipedia.org/wiki/ChatGPT_Deep_Research)
- **ChatGPT agent (July 17 2025)** is "a new agentic model in the same family as OpenAI o3." It combines deep research's multi-step research with Operator's remote visual browser, a terminal with limited network access, and Connectors such as Google Drive [vendor, older: 2025] — [ChatGPT agent System Card](https://cdn.openai.com/pdf/839e66fc-602c-48bf-81d3-b21eacc3459d/chatgpt_agent_system_card.pdf). Press reports attribute to OpenAI 68.9% on BrowseComp, 17.4 points above earlier models, and 41.6% pass@1 on HLE, or 44.4% with parallel runs plus self-confidence selection [vendor via press, older: 2025] — [AI News, Jul 18 2025](https://www.ainews.com/p/chatgpt-agent-can-now-act-on-your-behalf-using-its-own-virtual-computer)
- **Codex** web search (relevant to the user's question):
  - Default mode `"cached"` "serves results from the web search cache," described as "an OpenAI-maintained index of web results."
  - `"indexed"` permits external access only when the index gates the request. `"live"` fetches current data (same as `--search`). Full-access sandboxes default to live.
  - Cached mode "reduces exposure to prompt injection from arbitrary live content." The docs also say "Treat web results as untrusted."
  [vendor] — [Codex config basics](https://learn.chatgpt.com/docs/config-file/config-basic)

**Anthropic Claude Research (Apr 2025) and the multi-agent system (June 2025)**
- At launch Research "operates agentically, conducting multiple searches that build on each other," "explores different angles… automatically," and covers the web plus Google Workspace (Gmail, Calendar, Docs) with citations [vendor, older: 2025] — [Claude blog: Research](https://claude.com/blog/research)
- The architecture is orchestrator-worker [vendor, older: 2025]:
  - A LeadResearcher (Claude Opus 4) analyzes the query and saves its plan to Memory, because context is truncated past 200K tokens.
  - It spawns subagents (Sonnet 4) that search in parallel with interleaved thinking and return condensed findings.
  - The lead decides whether to iterate. A separate CitationAgent then attaches claims to sources.
  - It beat single-agent Opus 4 by 90.2% on an internal eval.
  - Effort-scaling rules in the prompt: simple fact-finding uses 1 agent with 3–10 tool calls; comparisons use 2–4 subagents with 10–15 calls each; complex research uses more than 10 subagents.
  - Running 3–5 subagents in parallel, each issuing 3+ parallel tool calls, cut research time by up to 90%.
  - Early failures: spawning 50 subagents for simple queries, endless searching for nonexistent sources, and favoring SEO content farms (fixed with source-quality heuristics).
  - A tool-testing agent that rewrote flawed MCP tool descriptions cut task time by 40%.
  - Production: checkpoints and resume, rainbow deployments. The lead waits synchronously for each batch of subagents, which is a known bottleneck.
  — [Anthropic Engineering: How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
- **Claude API web search tool** (server-side) [vendor, current docs]:
  - "Claude determines when to search… The API runs the searches… This process can repeat multiple times throughout a single request."
  - `max_uses` caps searches per turn ("single-fact queries typically use 1–3 searches; comparative or multientity research can use 10 or more"). Domain allow and block lists are supported.
  - Citations are always on, with `cited_text` of up to 150 characters.
  - Pricing is $10 per 1,000 searches plus tokens for the results.
  - `web_search_20260209` added **dynamic filtering**: Claude writes and runs code that filters results "before they reach the context window."
  — [Claude Docs: Web search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)
- Dynamic filtering raised BrowseComp from 33.3% to 46.6% (Sonnet 4.6) and from 45.3% to 61.6% (Opus 4.6), and DeepsearchQA F1 from 69.8 to 77.3 (Opus 4.6). On average it gave +11% accuracy with 24% fewer input tokens. However, price-weighted tokens *rose* for Opus 4.6 [vendor] — [Claude blog: Improved web search with dynamic filtering, Feb 17 2026](https://claude.com/blog/improved-web-search-with-dynamic-filtering)
- Opus 4.6 BrowseComp settings: "web search, web fetch, programmatic tool calling, context compaction triggered at 50k tokens up to 10M total tokens, max reasoning effort." "Adding a multi-agent harness increased scores to 86.8%" [vendor] — [Anthropic: Claude Opus 4.6, Feb 5 2026](https://www.anthropic.com/news/claude-opus-4-6)

**Google Gemini Deep Research (Dec 2024 → Gemini 3 / 3.1 Pro)**
- The system first "formulates a detailed research plan" that the user can edit. It then decides which sub-tasks run in parallel and which run sequentially, and "at each step the model reasons over information available to decide its next move."
- It runs "multiple passes of self-critique" before writing.
- An **asynchronous task manager** keeps shared state between planner and task models, so one failure does not force a restart.
- It uses a "1 million token context window complemented with a RAG setup" for session memory and browses "up to hundreds of websites."
- Model history: Gemini 1.5 Pro, then 2.0 Flash Thinking, then Gemini 3.
[vendor] — [Gemini Deep Research overview](https://gemini.google/overview/deep-research/)
- **API agent (Dec 11 2025)** uses Gemini 3 Pro, trained by "scaling multi-step reinforcement learning for search." Google reports 46.4% on HLE (full set), 66.1% on DeepSearchQA and 59.2% on BrowseComp. DeepSearchQA (open-sourced) has "900 hand-crafted 'causal chain' tasks across 17 fields" that need exhaustive answer sets [vendor, older: 2025] — [Google blog: Build with Gemini Deep Research](https://blog.google/technology/developers/deep-research-agent-gemini-api/)
- **April 2026 agents** run on Gemini 3.1 Pro: `deep-research-preview-04-2026` and `deep-research-max-preview-04-2026`. They are available only through the Interactions API with `background=True`.
  - Default tools: `google_search`, `url_context`, `code_execution`. Optional: `mcp_server` and `file_search` over uploaded document stores.
  - Optional `collaborative_planning` returns a plan for approval first.
  - Maximum research time is 60 minutes; most tasks finish within about 20.
  - Published per-task budgets:

    | Agent | Search queries | Input tokens (50–70% cached) | Output tokens | Cost per task |
    |---|---|---|---|---|
    | Standard | ~80 | ~250K | ~60K | ~$1–3 |
    | Max | up to ~160 | ~900K | ~80K | ~$3–7 |

  [vendor] — [Gemini API docs: Deep Research](https://aistudio.google.com/docs/deep-research)
- Google DevRel reports Max at 93.3% on DeepSearchQA and 85.9% on BrowseComp [vendor via press] — [ETIH, Apr 22 2026](https://edtechinnovationhub.com/news/googles-new-ai-agent-will-run-160-searches-while-you-sleep-and-hand-you-the-report-by-morning)

**Perplexity (Pro Search, Deep Research, DRACO)**
- **Pro Search** separates planning from execution [vendor interview, older: 2024–25]:
  - It builds a step-by-step plan. Each step "generates and executes a set of search queries," and earlier steps feed later ones.
  - Results are grouped and filtered to the most relevant documents before the LLM writes.
  - Prompts are kept simple ("It's harder for models to follow the instructions of really complex prompts").
  - Evaluation used side-by-sides, LLM-as-judge and A/B tests on latency and cost. Showing plan progress made users tolerate waiting.
  — [LangChain Breakout Agents: Perplexity](https://www.langchain.com/breakoutagents/perplexity)
- **Deep Research (Feb 14 2025)** "iteratively searches, reads documents, and reasons about what to do next," "performs dozens of searches, reads hundreds of sources," and finishes most tasks "in under 3 minutes" (2–4 minutes). Perplexity reports 21.1% on HLE and 93.9% on SimpleQA [vendor, older: 2025] — [Perplexity blog](https://www.perplexity.ai/hub/blog/introducing-perplexity-deep-research)
- In Feb 2026 Perplexity released DRACO: 100 tasks sampled from de-identified Perplexity Deep Research requests across 10 domains, graded by rubric on accuracy, completeness, objectivity and citations — [arXiv 2602.11685](https://arxiv.org/abs/2602.11685). On a leaderboard aggregation, Perplexity Deep Research scored 70.5% on Opus 4.6 and 67.2% on Opus 4.5, against Gemini Deep Research 59.0%, OpenAI DR (o3) 52.1% and OpenAI DR (o4-mini) 41.9%, all under a Gemini-3-Pro judge. This implies Perplexity's Deep Research runs on Anthropic Claude models in 2026 [vendor paper, aggregated] — [Steel.dev DRACO leaderboard, Oct 2026](https://leaderboard.steel.dev/leaderboards/draco/)

**Microsoft 365 Copilot Researcher (Mar 2025 → multi-model Mar 2026)**
- The 2025 version used OpenAI's deep research model (o3) plus enterprise graph and connector retrieval [vendor, older: 2025]:
  - The loop: plan (P0) with optional clarification, then cycles of Reasoning (Rj), Retrieval (Tj) and Review (Vj) on a scratch pad, then synthesis with citations.
  - It "loops through iterative cycles until it hits diminishing returns," stopping when new insight ΔI falls below a threshold ε.
  - It starts with "broad but shallow retrieval across heterogenous data sources" and then goes deep.
  - Enterprise queries needed 30–50% more iterations than web queries for equivalent coverage.
  - It averaged about 10.1 sources per response. On 1K queries it beat Copilot Chat on accuracy (+88.5%) and completeness (+70.4%).
  — [Microsoft Tech Community: Researcher agent](https://techcommunity.microsoft.com/blog/microsoft365copilotblog/researcher-agent-in-microsoft-365-copilot/4397186)
- The 2026 version adds two modes [vendor; judge is GPT-5.2, which is not independent]:
  - **Critique**: one model (OpenAI or Anthropic) does planning, iterative retrieval and drafting. A second model reviews against a rubric covering source reliability, completeness and strict evidence grounding.
  - **Council**: an Anthropic and an OpenAI model each write a full report, and a judge reconciles agreements and divergences.
  - Critique scored +7.0 points on DRACO over single-model Researcher.
  — [Microsoft: Introducing multi-model intelligence in Researcher, Mar 30 2026](https://techcommunity.microsoft.com/blog/Microsoft365CopilotBlog/introducing-multi-model-intelligence-in-researcher/4506011)

**xAI Grok DeepSearch (Feb 2025)**
- xAI calls it "a lightning-fast AI agent" built to "reason about conflicting facts and opinions," whose "final summary trace results in a concise and comprehensive report." No architecture details or benchmarks were published [vendor, older: 2025] — [xAI: Grok 3 Beta](https://x.ai/news/grok-3). Independent measures: Grok DeeperSearch scored 0.52 partial completion on Mind2Web 2, second to OpenAI DR's 0.54 — [arXiv 2506.21506](https://arxiv.org/abs/2506.21506). On DeepResearch Bench it had the lowest citation count (8.15 effective citations per task) — [arXiv 2506.11763](https://arxiv.org/abs/2506.11763)

**Moonshot Kimi-Researcher (Jun 2025) and K2.5 Agent Swarm (Jan 2026)**
- Kimi-Researcher [vendor, older: 2025]:
  - Built by end-to-end agentic RL on an internal k-series model, with parallel internal search, a text browser and a code tool.
  - It averages 23 reasoning steps and more than 200 URLs per task, and 70+ queries per trajectory.
  - HLE pass@1 went from 8.6% to 26.9% (40.17% pass@4). It scored 69% on xbench-DeepSearch.
  - RL recipe: REINFORCE, strictly on-policy, discarding some negatives to avoid entropy collapse, outcome rewards plus a format penalty, and gamma decay r·γ^(T−i) to favor shorter correct trajectories.
  - Context management extends rollouts beyond 50 iterations. Partial rollouts gave at least 1.5x speedup.
  — [Kimi-Researcher](https://moonshotai.github.io/Kimi-Researcher/)
- K2.5 Agent Swarm [vendor]:
  - A trainable orchestrator spawns frozen sub-agents: up to 100 sub-agents and 1,500 steps, "without predefined roles or hand-crafted workflows."
  - **PARL** rewards: r_parallel counters "serial collapse" (falling back to single-agent execution). r_finish counters "spurious parallelism" (many sub-agents without real decomposition). Both are annealed to zero.
  - Cost is measured in **critical steps** (orchestration plus the slowest sub-agent at each stage), not total steps.
  — [Kimi K2.5 blog](https://www.kimi.com/blog/kimi-k2-5); [arXiv 2602.02276](https://arxiv.org/abs/2602.02276)
- K2.5 BrowseComp results [vendor]:

  | Setup | BrowseComp |
  |---|---|
  | Single agent | 60.6% |
  | With Discard-all context management | 74.9% |
  | Agent Swarm | 78.4% |
  | GPT-5.2 Pro (as reported) | 77.9% |

  WideSearch item-F1 rose from 72.7 to 79.0, and the swarm needed 3–4.5x less time to reach target F1 — [arXiv 2602.02276](https://arxiv.org/abs/2602.02276)

**Alibaba Tongyi DeepResearch (Sep–Oct 2025)**
- The model is 30.5B-A3B MoE, 128K context, built on Qwen3-30B-A3B. Training goes agentic CPT (32K, then 128K context), then SFT cold start, then on-policy RL [author/vendor, older: 2025]:
  - RL uses a customized GRPO with token-level loss, leave-one-out advantages, exclusion of some negatives and a **pure 0/1 correctness reward**.
  - RL runs partly in a simulated environment (offline 2024 Wikipedia plus local RAG tools) and partly in a cached and retried real tool sandbox.
  - Two modes: native ReAct, and "Heavy" (IterResearch: rounds that rebuild a compact workspace around an evolving central report, then n parallel agents plus a synthesis agent).
  - Results: HLE 32.9, BrowseComp 43.4, BrowseComp-ZH 46.7, GAIA 70.9, FRAMES 90.6, xbench-DeepSearch 75.0 (Avg@3, at most 128 tool calls). Heavy mode: HLE 38.3, BrowseComp 58.3, BrowseComp-ZH 58.1.
  — [arXiv 2510.24701](https://arxiv.org/abs/2510.24701); [Tongyi blog](https://tongyi-agent.github.io/blog/introducing-tongyi-deep-research/)

**Manus (2025)**
- Context-engineering lessons [vendor, older: 2025]:
  - Typical tasks take about 50 tool calls, with an input-to-output token ratio of about 100:1.
  - The "KV-cache hit rate is the single most important metric." Cached tokens cost $0.30/MTok against $3 uncached on Claude Sonnet.
  - Mask tools rather than removing them, use the file system as restorable external memory, recite goals via `todo.md`, and keep errors in context.
  — [Manus: Context Engineering for AI Agents](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- **Wide Research** (Jul 31 2025) fans out across "hundreds of items," where every sub-agent is "a fully capable, general-purpose Manus instance" rather than a role. No evaluations were published [vendor, older: 2025] — [Manus: Introducing Wide Research](https://manus.im/blog/introducing-wide-research)

### Inferences
- The answer to "how can Codex search well without a local vector DB of the internet" has two layers. Retrieval is outsourced to a web index: Google Search for Gemini, an "OpenAI-maintained index" for Codex cached mode, a $10-per-1K-call search API for Claude and OpenAI. Quality comes from spending *inference* on many cheap index lookups: about 80–160 queries per Gemini task, 70+ per Kimi trajectory, 3–10+ subagents for Claude. Reading, filtering and verifying happen in the loop. Search-backend internals are Track 01's subject.
- Every major vendor now exposes its deep research agent as an API that can call **MCP servers and file-search stores**: OpenAI DR API, Gemini `mcp_server`/`file_search`, Claude Managed Agents. An agent-retrievable data lake therefore plugs in as a *tool backend* for these agents, not as their replacement.

### Gaps
- OpenAI's launch page (openai.com/index/introducing-deep-research) returned HTTP 403. Its per-level GAIA numbers were not read directly. Microsoft's blog quotes "26.6% on HLE and a 72.6% average on GAIA" for the same model.
- No official architecture details exist for Grok DeepSearch/DeeperSearch, Perplexity Deep Research's 2026 orchestration, Comet, or ChatGPT Atlas's research behavior. Atlas and Comet coverage found was secondary or affiliate content, so it is excluded.
- The current (Nov 2026) OpenAI deep research model and its BrowseComp score were not found in an official OpenAI source.

---

## 2. The common loop: clarify → plan → query → search → select → read → note → reflect → iterate → synthesize → cite; parallelism, stopping and budgets

### Takeaway
All systems implement the same core loop. Gemini and Microsoft surface it explicitly; OpenAI and Kimi learn it implicitly through RL. Systems diverge on four engineering choices:
1. **Who decomposes**: a learned policy (OpenAI, Kimi PARL) or a prompted orchestrator (Claude, LangChain).
2. **Context management**: memory/plan files, compaction, sub-agent isolation, report-centric workspaces.
3. **Stopping rule**: diminishing-returns threshold, token budget plus forced answer, or learned.
4. **Budget**: from 3 tool calls to 10M tokens.

Measured evidence favors broad-then-narrow queries, parallel sub-tasks when work is separable, and writing *after* research.

### Cited Findings
- **Clarify.** ChatGPT runs an intermediate clarifier model before research. The API expects the developer to add a rewriter — [OpenAI Cookbook](https://raw.githubusercontent.com/openai/openai-cookbook/main/examples/deep_research_api/introduction_to_deep_research_api.ipynb). Independent evidence on why it matters: on UNDERSPEC-DR, underspecified queries "substantially reduce" how well answers meet user needs even though answers stay cited. Agents "conduct broader searches that draw less on the original user query but rely more on their learned prior" [independent, Oct 2026] — [arXiv 2610.39413](https://arxiv.org/abs/2610.39413)
- **Plan.**
  - Gemini builds a user-editable plan and schedules parallel vs sequential sub-tasks — [Gemini overview](https://gemini.google/overview/deep-research/). The API offers `collaborative_planning` — [Gemini API docs](https://aistudio.google.com/docs/deep-research)
  - Claude's lead agent saves its plan to Memory to survive truncation past 200K tokens — [Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system)
  - Perplexity Pro Search runs plan-then-execute — [LangChain/Perplexity](https://www.langchain.com/breakoutagents/perplexity)
  - LangChain's open_deep_research turns the chat into a **research brief** that guides later phases — [LangChain, Jul 16 2025](https://www.langchain.com/blog/open-deep-research)
  - LongCat-DeepResearch (Meituan, Sep 2026) uses multiple planning agents that explore sources to refine an actionable "ResearchSpec" before section-level parallel research. Combining planning perspectives helped, but "further planning refinement has mixed effects" [author] — [arXiv 2609.36071](https://arxiv.org/abs/2609.36071)
- **Query generation.** Anthropic found agents defaulted to overly long, specific queries. Prompting "start with short, broad queries, evaluate what's available, then progressively narrow" fixed this — [Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system). Microsoft Researcher starts with "broad but shallow retrieval across heterogenous data sources" — [Microsoft 2025](https://techcommunity.microsoft.com/blog/microsoft365copilotblog/researcher-agent-in-microsoft-365-copilot/4397186). DeepDive trains a **redundancy penalty** that "discourages repeated similar queries" [author, older: 2025] — [arXiv 2509.10446](https://arxiv.org/abs/2509.10446)
- **Search → select → read.**
  - Jina node-DeepResearch's loop picks one action per step (search, visit, reflect, answer). New URLs are queued, new sub-questions go into a de-duplicated "gaps" queue, and an action is disabled for the next step if it yielded nothing new — [GitHub jina-ai/node-DeepResearch](https://github.com/jina-ai/node-DeepResearch)
  - OpenResearcher reduces browsing to three primitives, **search, open, find**, over a 15M-doc offline corpus — [arXiv 2603.20278](https://arxiv.org/abs/2603.20278)
  - Claude dynamic filtering runs code over results before they enter context — [Claude blog](https://claude.com/blog/improved-web-search-with-dynamic-filtering)
- **Notes and context management.**
  - Anthropic subagents "write outputs to a filesystem and pass lightweight references to the coordinator." Agents "summarize completed phases and store essential information externally" — [Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system)
  - Manus uses the file system and `todo.md` recitation — [Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
  - WebResearcher/IterResearch "periodically consolidate findings into evolving reports while maintaining focused workspaces" to avoid "context suffocation and noise contamination" [author, older: 2025] — [arXiv 2509.13309](https://arxiv.org/abs/2509.13309)
  - ReSum periodically summarizes history: +4.5% over ReAct with no training, and +8.2% more with ReSum-GRPO [author, older: 2025] — [arXiv 2509.13313](https://arxiv.org/abs/2509.13313)
- **Reflect and identify gaps.** Gemini "reasons over information available to decide its next move" and runs self-critique passes — [Gemini overview](https://gemini.google/overview/deep-research/). Microsoft has a dedicated Review step (Vj) per cycle — [Microsoft 2025](https://techcommunity.microsoft.com/blog/microsoft365copilotblog/researcher-agent-in-microsoft-365-copilot/4397186). DeepRewind models the agent's epistemic state as a typed graph (sources, evidence, claims, hypotheses, commitments). It blocks risky early commitments and rolls back dependents when evidence changes: −59.1% premature commitments and +3.6 points insight recall versus Open Deep Research [author, Sep 2026] — [arXiv 2609.36344](https://arxiv.org/abs/2609.36344)
- **Parallelism.**
  - Claude: 3–5 parallel subagents with 3+ parallel tools each cut time by up to 90% — [Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system)
  - Kimi Swarm cut WideSearch time to target by 3–4.5x — [arXiv 2602.02276](https://arxiv.org/abs/2602.02276)
  - LangChain moved *writing* out of the parallel phase because parallel section-writing "produced disjointed reports." Research is multi-agent; the report is "one-shot" — [LangChain](https://www.langchain.com/blog/open-deep-research)
  - WebWeaver keeps a planner that interleaves evidence gathering with outline optimization into a cited memory bank. The writer retrieves only the evidence cited for each section, which reduces long-context and citation hallucination [author, older: 2025] — [arXiv 2509.13312](https://arxiv.org/abs/2509.13312)
- **Stopping criteria.**
  - Microsoft stops at diminishing returns (ΔI < ε) — [Microsoft 2025](https://techcommunity.microsoft.com/blog/microsoft365copilotblog/researcher-agent-in-microsoft-365-copilot/4397186)
  - Jina stops when a definitive answer is found or the token budget is exceeded, then enters "Beast Mode" to force a final answer — [Jina GitHub](https://github.com/jina-ai/node-DeepResearch)
  - Claude Research stops when the lead judges information sufficient, with effort rules (1 agent and 3–10 calls for simple tasks, up to more than 10 subagents) — [Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system)
  - Kimi's gamma-decayed reward teaches shorter correct paths — [Kimi-Researcher](https://moonshotai.github.io/Kimi-Researcher/)
- **Budgets in published configurations.**

  | System | Budget |
  |---|---|
  | Claude web search | `max_uses` per turn ([docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)) |
  | Claude Opus 4.6 on BrowseComp | up to 10M total tokens, compaction at 50K ([Anthropic](https://www.anthropic.com/news/claude-opus-4-6)) |
  | Gemini standard | ~80 queries / ~250K input tokens, 60-minute cap |
  | Gemini Max | ~160 queries / ~900K input tokens ([docs](https://aistudio.google.com/docs/deep-research)) |
  | Tongyi evaluation | ≤128 tool calls, 128K context ([arXiv 2510.24701](https://arxiv.org/abs/2510.24701)) |
  | MiroThinker v1.0 | up to 600 tool calls per task in 256K context ([arXiv 2511.11793](https://arxiv.org/abs/2511.11793)) |
  | ASearcher training | >100 tool turns, >400K output tokens ([arXiv 2508.07976](https://arxiv.org/abs/2508.07976)) |
  | Manus | ~50 tool calls ([Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)) |

- **Synthesize → cite.**
  - Claude uses a dedicated CitationAgent after research — [Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system)
  - OpenAI returns character-span URL annotations — [Cookbook](https://raw.githubusercontent.com/openai/openai-cookbook/main/examples/deep_research_api/introduction_to_deep_research_api.ipynb)
  - Claude web search citations carry `cited_text` — [docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)
  - GPT Researcher: a planner generates questions, crawler/execution agents gather sources per question (claims "over 20 sources"), each source is summarized and source-tracked, then a publisher aggregates (about 5 minutes and about $0.40 with o3-mini-high in deep mode, self-reported) — [GitHub assafelovic/gpt-researcher](https://github.com/assafelovic/gpt-researcher)

### Inferences
- The loop has five mechanical primitives a data lake can serve natively:
  1. **broad query → ranked snippets** (search);
  2. **open/expand by ID** (open);
  3. **in-document find** (find);
  4. **notes/workspace store** (memory);
  5. **citation by span**.

  OpenResearcher's search/open/find, CORE's snippet-plus-expand (Section 6) and Anthropic's filesystem references all converge on this shape.
- Stopping on information gain (Microsoft ΔI, Jina's "no new URLs/gaps → disable action") is cheap to implement if the data lake returns *novelty signals*, for example "N of these results were already returned this session."

### Gaps
- None of the vendors publishes stopping thresholds or the learned policy's average step counts for current (2026) models, except Gemini's query and token estimates.
- No controlled study was found that isolates the clarify step's effect on final quality in a commercial system. UNDERSPEC-DR measures the damage from underspecification, not the fix.

---

## 3. Training: RL for search agents, synthetic hard-question data, process vs outcome rewards

### Takeaway
Training has converged on four pieces:
1. **Synthetic, obfuscated, multi-hop questions with short verifiable answers** (BrowseComp-style), generated by agents from KGs, Wikipedia or the live web.
2. An SFT/RFT cold start on teacher trajectories, sometimes preceded by agentic continual pre-training.
3. **Outcome-reward RL** (0/1 correctness, sometimes with length/format shaping) in simulated or cached search environments, with long horizons (100+ calls) and context management inside the loop.
4. For long-form reports, **rubric rewards** (OpenAI's CoT grader on rubrics, DR Tulu's evolving rubrics, Step's checklist judger) and newer rubric-grounded process credit.

Process rewards help small models and sparse-reward settings but are not used by the strongest open systems (Tongyi, Kimi), which stick to outcome rewards.

### Cited Findings
**First-generation RL search agents (2025, Wiki-QA scale; see Track 05 notes for numbers)**
- Search-R1: outcome reward with retrieved-token masking — [arXiv 2503.09516](https://arxiv.org/abs/2503.09516)
- R1-Searcher: two-stage outcome RL with no process reward and no distillation cold start — [arXiv 2503.05592](https://arxiv.org/abs/2503.05592)
- ReSearch: RL with no supervised reasoning traces; reflection and self-correction emerge — [arXiv 2503.19470](https://arxiv.org/abs/2503.19470)
- DeepResearcher: the first end-to-end RL on the *live web*, with browsing agents extracting from pages; up to +28.9 points over prompted agents; emergent planning, cross-validation and honesty — [arXiv 2504.03160](https://arxiv.org/abs/2504.03160)
- Search-o1 (prompted, no RL) adds a "Reason-in-Documents" module that condenses retrieved pages before injection — [arXiv 2501.05366](https://arxiv.org/abs/2501.05366)

All [author, older: 2025].

**Hard synthetic data is the main lever**
- BrowseComp itself: human trainers wrote 1,266 "inverted" questions with short answers that GPT-4o, o1 and an early deep research could not solve. Trainers solved only 29.2% and gave up on 70.8% after two hours. OpenAI notes its deep research model "is trained on data that specifically teach the model to be good at BrowsingComp tasks" [vendor, older: 2025] — [arXiv 2504.12516](https://arxiv.org/abs/2504.12516)
- WebSailor (Alibaba, Jul 2025) creates "Level 3" tasks (high uncertainty, hard to reduce) by sampling KG subgraphs and **obfuscating** features (vague dates, ranges), then RFT cold start and DUPO RL. WebSailor-72B: BrowseComp-en 12.0, -zh 30.1 [author, older: 2025] — [arXiv 2507.02592](https://arxiv.org/abs/2507.02592); V2 — [arXiv 2509.13305](https://arxiv.org/abs/2509.13305)
- WebShaper formalizes information-seeking tasks in set theory ("Knowledge Projections"), and an agentic Expander grows seed questions step by step with retrieval and validation — [arXiv 2507.15061](https://arxiv.org/abs/2507.15061). WebDancer runs data construction → trajectory sampling → SFT → RL — [arXiv 2505.22648](https://arxiv.org/abs/2505.22648). WebExplorer uses "explore and evolve" long-to-short query evolution; its 8B model averages 16 turns and beats WebSailor-72B on BrowseComp-en/zh — [arXiv 2509.06501](https://arxiv.org/abs/2509.06501). DeepDive synthesizes questions from open KGs and adds multi-turn RL — [arXiv 2509.10446](https://arxiv.org/abs/2509.10446). ASearcher has a prompt-based agent that synthesizes hard QAs, fully asynchronous RL with >100-turn trajectories, and reports 58.7 on GAIA for QwQ-32B — [arXiv 2508.07976](https://arxiv.org/abs/2508.07976). All [author, older: 2025].
- Agentic continual pre-training (AgentFounder): post-training a general model "forces models… to simultaneously learn diverse agentic behaviors while aligning them to expert demonstrations." Agentic CPT first gives AgentFounder-30B 39.9% on BrowseComp-en and 31.5% on HLE [author, older: 2025] — [arXiv 2509.13310](https://arxiv.org/abs/2509.13310). Tongyi DeepResearch adopts it (32K → 128K) — [arXiv 2510.24701](https://arxiv.org/abs/2510.24701)
- Teacher-trajectory SFT alone goes far. OpenResearcher synthesized 97K trajectories with GPT-OSS-120B offline, including 100+-call tails. SFT of a 30B-A3B model reached 54.8% on BrowseComp-Plus (+34.0 points) [author, Mar 2026] — [arXiv 2603.20278](https://arxiv.org/abs/2603.20278)

**Environments**
- Tongyi trains in a simulated offline-Wikipedia environment with local RAG tools for "low-cost, high-efficiency" iteration, and in a real tool sandbox with caching, retries and provider fallback — [arXiv 2510.24701](https://arxiv.org/abs/2510.24701). DeepResearchGym provides a free, reproducible search API over ClueWeb22 and FineWeb (dense retriever plus DiskANN). Models trained in it "generalize to commercial search" — [arXiv 2505.19253](https://arxiv.org/abs/2505.19253)
- Glasseek (Oct 2026) addresses three problems: train-inference mismatch from context compression, solved with CM-GSPO (the same policy searches and summarizes, optimizing only execution sub-trajectories); opaque trajectory pipelines; and test-set leakage from the open web, solved with an anti-leakage plugin. Its 9B agent reportedly beats frontier proprietary agents on most benchmarks [author] — [arXiv 2610.16998](https://arxiv.org/abs/2610.16998)

**Outcome rewards and shaping in production-grade recipes**
- Tongyi: "a pure 0 or 1 signal of answer correctness," no format reward. It excludes some negatives (for example, length-limit failures) because unfiltered negatives "lead to policy collapse," and filters out tasks the model always solves or always fails — [arXiv 2510.24701](https://arxiv.org/abs/2510.24701)
- Kimi-Researcher: REINFORCE, outcome plus format penalty, gamma decay for efficiency, negative-sample control — [Kimi-Researcher](https://moonshotai.github.io/Kimi-Researcher/)
- Kimi K2.5 PARL: outcome reward plus annealed parallelism and finish-rate auxiliaries; the critical-steps budget makes parallelism pay off only if it shortens the critical path — [arXiv 2602.02276](https://arxiv.org/abs/2602.02276)
- Reward over compressed contexts: ReSum-GRPO "advantage broadcasting" across segmented trajectories — [arXiv 2509.13313](https://arxiv.org/abs/2509.13313)
- MiroThinker trains "interaction scaling": accuracy "improves predictably as the model engages in deeper and more frequent agent-environment interactions." Its 72B model reaches GAIA 81.9, HLE 37.7, BrowseComp 47.1 and BrowseComp-ZH 55.6 [author, Nov 2025] — [arXiv 2511.11793](https://arxiv.org/abs/2511.11793)

**Process and rubric rewards**
- StepSearch adds step-wise PPO with information-gain and redundancy rewards: +11.2 / +4.2 points (3B / 7B) over global-reward baselines with 19K training examples — [arXiv 2505.15107](https://arxiv.org/abs/2505.15107). Atom-Searcher uses reasoning-reward-model "atomic thought" rewards on a curriculum from process to outcome, citing "conflicting gradients and reward sparsity" in outcome-only RL — [arXiv 2508.12800](https://arxiv.org/abs/2508.12800). Both [author, older: 2025].
- DR Tulu (AI2, Nov 2025) introduces **RL with Evolving Rubrics (RLER)** for long-form reports [author]:
  - Rubrics are initialized from search, then new ones are generated from contrasting rollouts during training. Non-discriminative rubrics are pruned, and only the top-K are kept.
  - DR Tulu-8B (RL) averages 65.6 across SQAv2, HealthBench, ResearchQA and DeepResearch Bench, against 64.9 for OpenAI DR and 50.0 for Tongyi DR-30B.
  - Cost: OpenAI DR costs about $1.8 per query on SQAv2; DR Tulu is "almost three orders of magnitude" cheaper.
  — [arXiv 2511.19399](https://arxiv.org/abs/2511.19399)
- Step-DeepResearch (32B) uses agentic mid-training → SFT → RL with a "Checklist-style Judger" and scores 61.4% on Scale AI ResearchRubrics [author, older: 2025] — [arXiv 2512.20491](https://arxiv.org/abs/2512.20491)
- Dr.Credit (Sep 2026) gives intermediate tool turns credit when tool output adds *new* support toward a rubric item relative to that rubric's history, combined with GRPO outcome advantages. An 8B model is "competitive with the evaluated frontier proprietary models," with more efficient evidence acquisition under turn budgets [author] — [arXiv 2609.34296](https://arxiv.org/abs/2609.34296)
- SFR-DeepResearch (Salesforce) runs continual RL of *reasoning* models as autonomous single agents with minimal tools and synthetic data; its 20B model reaches 28.7% on HLE [author, older: 2025] — [arXiv 2509.06283](https://arxiv.org/abs/2509.06283)
- Prompt optimization instead of RL: GEPA on a multi-agent DR agent's two system prompts raised held-out citation reward from 0.702 to 0.781 under topic-disjoint splits. Decomposed per-dimension feedback was "the causal ingredient." Collapsing it to a scalar made transfer negative [independent-ish, Oct 2026] — [arXiv 2610.12601](https://arxiv.org/abs/2610.12601)

### Inferences
- For an open-source toolkit, the reusable assets are environments and data, not RL code:
  - an **offline, deterministic search/open/find environment over the user's own corpus** (like Tongyi's simulated wiki, OpenResearcher's 15M-doc corpus and DeepResearchGym);
  - **synthesized hard questions with verifiable answers** built from the user's data (WebSailor/WebShaper/DeepDive-style subgraph sampling and obfuscation over the data lake's own entity graph).

  These let anyone RL- or SFT-train a small domain search agent.
- For report-style outputs over a domain corpus, rubric rewards (DR Tulu/Dr.Credit) are the open recipe that matches proprietary quality at low cost. Outcome-only 0/1 rewards are proven mainly on short-answer tasks.

### Gaps
- OpenAI and Google disclose only "RL on browsing tasks" / "multi-step RL for search," with no reward designs or data volumes. Anthropic discloses nothing about search-specific training for Claude 4.x/5.x.
- I found no head-to-head that controls for data when comparing process and outcome rewards at frontier scale. The process-reward gains above come from 3B–8B models on QA or rubric benchmarks.

---

## 4. Open-source systems: GPT Researcher, STORM/Co-STORM, LangChain open_deep_research, HF Open Deep Research, Jina node-DeepResearch, MiroThinker/MiroFlow, WebThinker, OpenResearcher, Tongyi, DR Tulu

### Takeaway
There are two families:
- **Harnesses around any LLM**: GPT Researcher, STORM, LangChain open_deep_research, HF smolagents, Jina, MiroFlow. Quality is bounded by the base model, and they often fail on tool-format compliance.
- **Trained open models with their own harness**: Tongyi DR, MiroThinker, WebThinker, DR Tulu, OpenResearcher, Glasseek. In 2025–26 these close most of the gap on BrowseComp-style and long-form benchmarks at 8B–72B scale.

The best 2026 harness results come from open harnesses with careful context isolation (ArcticSwarm, CORE) running on frontier or strong open models.

### Cited Findings
- **STORM** (Stanford, Feb 2024) [author, older: 2024]:
  - Pre-writing: discover perspectives from related articles → simulate writer–expert conversations grounded in search → curate an outline. Then write with citations.
  - Against an outline-driven RAG baseline: +25% (absolute) more organized and +10% broader coverage.
  - Editors flagged "source bias transfer and over-association of unrelated facts."
  — [arXiv 2402.14207](https://arxiv.org/abs/2402.14207)
- **Co-STORM** adds a moderator agent and a dynamic mind map; 70% of participants preferred it over a search engine, 78% over a RAG chatbot [author, older: 2024] — [arXiv 2408.15232](https://arxiv.org/abs/2408.15232)
- The repo supports many retrievers, including **VectorRM for user-provided documents**. More than 70,000 people tried the preview, and the authors say outputs are not "publication-ready" — [GitHub stanford-oval/storm](https://github.com/stanford-oval/storm)
- **GPT Researcher**: planner → per-question execution/crawler agents → publisher. Deep mode does tree-like recursive exploration with configurable depth and breadth (about 5 minutes and about $0.40 per run, self-reported). A passage filter ("Jev") is claimed to keep 73% relevant passages against 46% for embeddings on 28 tasks [self-reported] — [GitHub assafelovic/gpt-researcher](https://github.com/assafelovic/gpt-researcher)
- **LangChain open_deep_research** (Jul 2025) has three phases: scope (clarify + brief) → research (supervisor + isolated-context sub-agents, which compress findings) → one-shot report. It ships with LangGraph and supports bring-your-own model, search tool and MCP — [LangChain blog](https://www.langchain.com/blog/open-deep-research). It is used as the baseline in 2026 papers (DeepRewind, CESS).
- **HF Open Deep Research** (smolagents, built in 24 hours, Feb 2025) [author, older: 2025]:
  - It uses a CodeAgent (actions as code), a text browser and a file inspector adapted from Magentic-One.
  - GAIA validation: 55.15% against OpenAI DR's 67.36%. The same setup with JSON actions averaged 33%; code actions used "30% fewer steps."
  — [HF blog](https://huggingface.co/blog/open-deep-research)
  - Independent: on Mind2Web 2 it showed "system errors (e.g., failures in adhering to system prompts to generate valid code to invoke the search tool)" and fabricated URLs — [arXiv 2506.21506](https://arxiv.org/abs/2506.21506)
- **Jina node-DeepResearch**: a single-agent loop over search, visit, reflect and answer, with a gap-question queue and token budget; Beast Mode forces an answer when the budget runs out. It "needs strong structured-output support" — [GitHub](https://github.com/jina-ai/node-DeepResearch)
- **WebThinker** (RUC, Apr 2025): a large reasoning model plus a Deep Web Explorer and "Think-Search-and-Draft." It drafts the report during reasoning and is trained with iterative online DPO. Evaluated on GPQA, GAIA, WebWalkerQA, HLE and Glaive reports [author, older: 2025] — [arXiv 2504.21776](https://arxiv.org/abs/2504.21776)
- **MiroThinker / MiroFlow**: MiroThinker v1.0 (72B, 256K, up to 600 tool calls) is quoted in Section 3 — [arXiv 2511.11793](https://arxiv.org/abs/2511.11793). MiroFlow is the open framework with an agent graph and an optional deep reasoning mode, reporting SOTA on GAIA, BrowseComp-EN/ZH, HLE, xBench-DeepSearch and FutureX [author, Feb 2026] — [arXiv 2602.22808](https://arxiv.org/abs/2602.22808)
- **OpenResearcher** (TIGER-Lab, Mar 2026): a fully offline trajectory-synthesis pipeline plus 30B-A3B SFT model at 54.8% on BrowseComp-Plus — [arXiv 2603.20278](https://arxiv.org/abs/2603.20278)
- **Independent cross-comparison** on long-form benchmarks, from DR Tulu Table 1. Averages over SQAv2, HealthBench, ResearchQA and DeepResearch Bench:

  | System | Average |
  |---|---|
  | DR Tulu-8B (RL) | 65.6 |
  | GPT-5 + Search | 65.8 |
  | OpenAI Deep Research | 64.9 |
  | Gemini 3 Pro + Search | 57.0 |
  | WebThinker-32B-DPO (report mode) | 50.2 |
  | Tongyi DR-30B | 50.0 |
  | WebExplorer-8B | 44.4 |
  | Search-R1-7B | 14.9 |
  | ASearcher-Web-7B | 10.3 |

  Short-answer-trained RL agents generalize poorly to report tasks [author-run comparisons] — [arXiv 2511.19399](https://arxiv.org/abs/2511.19399)
- **2026 open harness results on BrowseComp** [author]:
  - **ArcticSwarm** (Snowflake et al., Sep 2026) separates evidence gathering from integration. Subagents publish to a bulletin board, and **gated isolation** keeps some searches from reading peers' partial findings, which prevents early consensus.

    | Setup | Score |
    |---|---|
    | Qwen3.5-27B, BrowseComp-Plus | 82.6% |
    | Same, without gated isolation | 78.8% |
    | Same, also without structured review | 74.5% |
    | MiroFlow baseline | 70.6% |
    | GPT-5 on live BrowseComp (ArcticSwarm) | 73.6% |
    | GPT-5 on live BrowseComp (provider-reported) | 54.9% |

    — [arXiv 2609.01870](https://arxiv.org/abs/2609.01870)
  - **CORE** (Nov 2026) is a training-free harness: dense retrieval of long passages, late-interaction token similarities to return only the best snippet per passage, an "expand context" action and suppression of repeated snippets. It reports SOTA accuracy and evidence recall against Tongyi and OpenResearcher harnesses on BrowseComp-Plus variants with corpora up to 553M docs — [arXiv 2611.07859](https://arxiv.org/abs/2611.07859)

### Inferences
- Open-source harnesses differ mainly in context hygiene: isolated sub-agent contexts, compressed handoffs, snippet-then-expand reading and write-after-research. They differ little in "agent intelligence," and context hygiene is exactly what a retrieval toolkit can supply through its tool contracts.
- STORM's VectorRM and LangChain's MCP support show that open frameworks already accept private corpora. A data lake that exposes search/open/find over MCP becomes usable by all of them without integration work.

### Gaps
- No single independent benchmark run covers all the open harnesses (GPT Researcher, STORM, LangChain, Jina, HF) under the same model and search API in 2026. Comparisons are scattered across papers with different setups.
- MiroThinker's later versions (v1.5+) and Glasseek's exact scores were not extracted.

---

## 5. Benchmarks and evidence: scores by system, cost and latency, independent evaluations and failure analyses

### Takeaway
There are two benchmark families:
- **Short-answer "hard-to-find" benchmarks**: BrowseComp (+ZH, +Plus), GAIA, HLE, FRAMES, xbench, DeepSearchQA. These saturated quickly. BrowseComp went from 51.5% for deep research in Apr 2025 to roughly 85–92% vendor-reported for frontier models in late 2026.
- **Long-form report benchmarks**: DeepResearch Bench (RACE/FACT), ResearchRubrics, DRACO, Mind2Web 2, WANDR, WideSearch. These remain far from solved: under 70% rubric compliance, 0.36 soft F1 on WANDR, 50–70% of human performance on Mind2Web 2.

Independent studies consistently find:
- citations that link correctly but often do not support the claim (39–77% factual support);
- over-confident "smoothed" syntheses;
- run-to-run instability;
- evidence-selection bias;
- benchmark contamination via live search (up to +4%).

### Cited Findings
**Short-answer benchmarks**
- **BrowseComp** (Apr 2025) [vendor, older: 2025] — [arXiv 2504.12516](https://arxiv.org/abs/2504.12516):

  | Model | Accuracy | Calibration error |
  |---|---|---|
  | GPT-4o | 0.6% | |
  | GPT-4o + browsing | 1.9% | |
  | o1 | 9.9% | |
  | Deep Research | 51.5% | 91% (highest) |

  Accuracy "scales smoothly" with browsing effort. Running 64 samples with best-of-N, weighted or majority voting adds 15–25%, because BrowseComp is "easier to verify than to find."
- **BrowseComp-ZH**: 289 questions; the best system, OpenAI DR, scored 42.9% [independent, older: 2025] — [arXiv 2504.19314](https://arxiv.org/abs/2504.19314). **BrowseComp-Plus**: a fixed ~100K-doc corpus that separates retriever from agent effects — [arXiv 2508.06600](https://arxiv.org/abs/2508.06600). See the Track 05 notes for retriever numbers.
- Late-2026 BrowseComp scores (aggregator, setups not comparable; "multi-attempt results and single attempts are not interchangeable") — [BenchLM, Nov 6 2026](https://benchlm.ai/benchmarks/browsecomp):

  | Model | Score |
  |---|---|
  | GPT-5.6 Sol | 92.2% |
  | Kimi K3.1 Pro | 92.1% |
  | Claude Opus 5 | 90.8% |
  | GPT-5.5 Pro | 90.1% |
  | Claude Mythos 5 | 88% |

  Vendor-reported anchors: Opus 4.6 at 86.8% with a multi-agent harness — [Anthropic](https://www.anthropic.com/news/claude-opus-4-6); Gemini Deep Research Max at 85.9% — [ETIH](https://edtechinnovationhub.com/news/googles-new-ai-agent-will-run-160-searches-while-you-sleep-and-hand-you-the-report-by-morning); K2.5 Swarm at 78.4% and GPT-5.2 Pro at 77.9% — [arXiv 2602.02276](https://arxiv.org/abs/2602.02276)
- **GAIA** (466 questions; humans 92% vs GPT-4 with plugins 15%) [older: 2023] — [arXiv 2311.12983](https://arxiv.org/abs/2311.12983). OpenAI DR scored a 72.6% average per Microsoft's quote of OpenAI — [Microsoft](https://techcommunity.microsoft.com/blog/microsoft365copilotblog/researcher-agent-in-microsoft-365-copilot/4397186). Validation scores: OpenAI DR 67.36% and HF ODR 55.15% — [HF](https://huggingface.co/blog/open-deep-research). Open models: Tongyi 70.9 and MiroThinker-72B 81.9 [author].
- **HLE** (2,500 expert questions "that cannot be quickly answered via internet retrieval") — [arXiv 2501.14249](https://arxiv.org/abs/2501.14249). Reported scores:

  | System | HLE | Source |
  |---|---|---|
  | OpenAI DR (2025) | 26.6% | [Microsoft quoting OpenAI](https://techcommunity.microsoft.com/blog/microsoft365copilotblog/researcher-agent-in-microsoft-365-copilot/4397186) |
  | Perplexity DR | 21.1% | [Perplexity](https://www.perplexity.ai/hub/blog/introducing-perplexity-deep-research) |
  | Kimi-Researcher | 26.9% | [Kimi](https://moonshotai.github.io/Kimi-Researcher/) |
  | ChatGPT agent | 41.6% | [AI News](https://www.ainews.com/p/chatgpt-agent-can-now-act-on-your-behalf-using-its-own-virtual-computer) |
  | Gemini DR agent | 46.4% | [Google](https://blog.google/technology/developers/deep-research-agent-gemini-api/) |
  | Claude Opus 4.6 (with tools) | 53.0% | [Anthropic](https://www.anthropic.com/news/claude-opus-4-6) |

  All vendor-reported.
- **FRAMES** (824 multi-hop questions; 0.40 with no retrieval → 0.66 with a multi-step pipeline) [older: 2024] — [arXiv 2409.12941](https://arxiv.org/abs/2409.12941). Tongyi reports 90.6 [author].

**Long-form and report benchmarks**
- **DeepResearch Bench** (100 PhD-level tasks, 22 fields; RACE for report quality, FACT for citations) [independent, older: 2025] — [arXiv 2506.11763](https://arxiv.org/abs/2506.11763):

  | System | RACE | Citation accuracy | Effective citations per task |
  |---|---|---|---|
  | Gemini-2.5-Pro DR | 48.88 | 81.44% | 111.21 |
  | OpenAI DR | 46.98 | 77.96% | 40.79 |
  | Perplexity DR | 42.25 | 90.24% | 31.26 |
  | Grok Deeper Search | 40.24 | 83.59% | 8.15 |
  | Claude-3.7-Sonnet w/Search | 40.67 | 93.68% | 32.48 |

  The 2026 repo uses GPT-5.5 as the official RACE judge, with judge–human alignment of 71.82 against a 68.78 inter-annotator baseline — [GitHub deep_research_bench](https://github.com/Ayanami0730/deep_research_bench)
- **Mind2Web 2** (130 long-horizon live-web tasks, agent-as-judge with tree rubrics; judges 99% correct on human check) [independent, older: 2025] — [arXiv 2506.21506](https://arxiv.org/abs/2506.21506):

  | System | Partial completion | Success | Time |
  |---|---|---|---|
  | OpenAI DR | 0.54 | 0.28 | 8.4 min |
  | Grok DeeperSearch | 0.52 | | 5.7 min |
  | Gemini DR | 0.45 | | 7.4 min |
  | Perplexity DR | 0.42 | | 5.7 min |
  | Grok DeepSearch | 0.40 | | |
  | Claude Research | 0.32 | | 7.4 min |
  | Perplexity Pro Search | 0.28 | | |
  | ChatGPT Search | 0.26 | | |
  | Human | 0.79 | 0.54 | 18.4 min |

  Error types: incompleteness and "early termination… laziness" in non-DR systems; invalid or fabricated URLs (HF ODR, Operator); missing attribution; synthesis errors where Python tools were absent. Deep research systems "surpassed humans" on criteria violations.
- **ResearchRubrics** (Scale AI, Nov 2025; 2,500+ expert rubrics, 2,800+ hours of human work) [independent, older: 2025] — [arXiv 2511.07685](https://arxiv.org/abs/2511.07685):

  | System | Ternary compliance | Binary compliance |
  |---|---|---|
  | Gemini DR | 0.677 | 0.615 |
  | OpenAI DR | 0.664 | 0.597 |
  | Perplexity DR | 0.566 | 0.487 |

  "Implicit reasoning and synthesis jointly account for 45-50% of all failures." Agents "consistently fail to infer unstated requirements."
- **DRACO** (Perplexity, Feb 2026): see Section 1. The steel.dev aggregation stresses that judge choice "can shift scores by 10–25 points." For example, Opus 4.8 scores 80.4% under an Opus 4.6 judge and 58.8% under a Gemini 3.1 judge, and "each judge regime may favor its originator" [aggregator] — [Steel.dev DRACO leaderboard](https://leaderboard.steel.dev/leaderboards/draco/); [arXiv 2602.11685](https://arxiv.org/abs/2602.11685)
- **Breadth ("wide") benchmarks** [independent]:
  - WideSearch (200 tasks): most systems near 0% full-success, best 5% [older: 2025] — [arXiv 2508.07999](https://arxiv.org/abs/2508.07999)
  - WANDR (Aug 2026): 500 tasks from de-identified product logs, judged by refetching cited pages. The strongest of six production systems reaches 0.363 soft F1 and 0.133 hard F1, and performance degrades with target volume and hierarchy depth — [arXiv 2608.14747](https://arxiv.org/abs/2608.14747)
  - A-MapReduce recasts wide search as horizontal MapReduce, +5.1–17.5% item F1 [author] — [arXiv 2602.01331](https://arxiv.org/abs/2602.01331)
- **FutureSearch Deep Research Bench** (89 tasks; frozen "RetroSearch" web snapshot gives results comparable to the live web; evaluates commercial "Deep Research" products over time) [independent, older: 2025] — [arXiv 2506.06287](https://arxiv.org/abs/2506.06287)
- **DeepResearchGym** offers reproducible search plus LLM-judge evaluation, with rankings consistent with commercial-API runs — [arXiv 2505.19253](https://arxiv.org/abs/2505.19253)

**Independent failure analyses (2026)**
- **Citations are valid links but often do not support the claim.** Across 14 LLMs, frontier models keep link validity above 94% and relevance above 80%, yet "only 39-77% factual accuracy." Fact-check accuracy "drops by approximately 42%… as tool calls scale from 2 to 150," so "more retrieval does not produce more accurate citations" — [arXiv 2605.06635](https://arxiv.org/abs/2605.06635)
- **Claim smoothing**: across 7 systems and 4 datasets, "agents consistently produce stronger claims than warranted," collapsing conflicting evidence into decisive narratives — [arXiv 2610.35793](https://arxiv.org/abs/2610.35793)
- **Evidence-selection bias**: "early findings redirect later queries, document choices, and stopping, so the documents an agent reads form a selective sample." CESS reweighting cut estimate shift under opposing rankings by 87.2% on Open Deep Research trajectories — [arXiv 2609.39026](https://arxiv.org/abs/2609.39026)
- **Run-to-run instability**: ten identical prompts to one commercial DR system gave median pairwise entity Jaccard 0.12 and citation Jaccard below 0.02, with discovery curves that "do not visibly saturate" — [arXiv 2610.26421](https://arxiv.org/abs/2610.26421)
- **Search-time contamination**: agents retrieve benchmark metadata or answers online, inflating scores by up to 4% across six benchmarks — [arXiv 2606.05241](https://arxiv.org/abs/2606.05241). OpenAI's own card warns that "any publicly available information published online could contaminate the evaluation" and builds site blocklists and classifiers — [OpenAI DR System Card](https://cdn.openai.com/deep-research-system-card.pdf)
- **Meta-evaluation**: pairwise human preference is suited to system-level ranking. Metric-level validity needs expert, metric-wise annotation — [arXiv 2603.06942](https://arxiv.org/abs/2603.06942)
- **Error taxonomy**: system-level vs task-level error classes from intermediate traces (abstract only read) — [arXiv 2610.29346](https://arxiv.org/abs/2610.29346)
- **Hallucination and calibration** [vendor, older: 2025]: OpenAI reports a PersonQA hallucination rate of 0.13 for DR, against 0.30 for GPT-4o and 0.15 for o3-mini — [System Card](https://cdn.openai.com/deep-research-system-card.pdf). It also has the worst calibration error (91%) in its BrowseComp table — [arXiv 2504.12516](https://arxiv.org/abs/2504.12516)

**Cost and latency per task**

| System | Time | Cost / tokens | Source |
|---|---|---|---|
| OpenAI DR | 5–30 min | ~$1.8 per query on SQAv2 (measured by DR Tulu authors) | [Sequoia](https://sequoiacap.com/podcast/training-data-deep-research); [arXiv 2511.19399](https://arxiv.org/abs/2511.19399) |
| Perplexity DR | 2–4 min | | [Perplexity](https://www.perplexity.ai/hub/blog/introducing-perplexity-deep-research) |
| Gemini DR standard | ≤60 min (most ~20) | ~$1–3 per task | [Gemini docs](https://aistudio.google.com/docs/deep-research) |
| Gemini DR Max | ≤60 min | ~$3–7 per task | [Gemini docs](https://aistudio.google.com/docs/deep-research) |
| GPT Researcher deep mode | ~5 min | ~$0.40 (self-reported) | [GitHub](https://github.com/assafelovic/gpt-researcher) |
| Mind2Web 2 systems | 2.6–8.4 min (human 18.4) | | [arXiv 2506.21506](https://arxiv.org/abs/2506.21506) |
| Anthropic multi-agent | | ~15x chat tokens; single agent ~4x | [Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system) |

### Inferences
- Short-answer benchmarks reward persistence plus verification and are near saturation for frontier systems. Long-form, breadth and attribution benchmarks are where systems still fail. Those failures are mostly about **evidence handling**, not search reach: unsupported citations, smoothing, missed implicit requirements, incomplete enumeration. A data lake that returns structured, attributable records with stable IDs and spans addresses exactly these.
- Run-to-run citation Jaccard below 0.02 means one deep research run is a sample, not a census. For enumeration tasks over a closed corpus, a deterministic structured query (SQL or graph) will beat any web-style research agent on completeness and reproducibility.

### Gaps
- I found no independent, same-harness 2026 BrowseComp leaderboard. Aggregators mix vendor runs, attempt counts and harnesses, and Kaggle's BrowseComp page did not render.
- I found no independent per-task cost measurement of ChatGPT, Claude Research or Perplexity consumer products in 2026. Only Gemini publishes API budgets.
- The live DeepResearch Bench leaderboard (Hugging Face Space) did not render, so 2026 RACE scores by system are missing.

---

## 6. What specifically produces high quality: breadth via parallel subagents, persistence, learned query reformulation, verification, context hygiene (with evidence)

### Takeaway
The measured drivers, ranked by strength of evidence:
1. **More test-time compute and tokens**, meaning persistence. Token usage explains 80% of BrowseComp variance (Anthropic), and accuracy scales smoothly with browsing effort (OpenAI).
2. **A stronger base model**, worth more than doubling tokens (Anthropic). Agentic pre-training and RL also help (Tongyi, AgentFounder).
3. **Verification and selection across parallel attempts**: +15–25% from best-of-N on BrowseComp; Critique +7 on DRACO.
4. **Context hygiene**: filtering before context (+11% at −24% tokens), isolated sub-agent contexts, compaction, snippet-then-expand.
5. **Parallel breadth**, which mainly buys **speed** (up to 90% time cut, 3–4.5x) and helps on wide tasks. Its benefit to *yield* is bounded, and gated isolation from peers matters.
6. **Good first moves and query strategy**: broad then narrow, decomposition into clues, redundancy penalties.

More retrieval does *not* automatically improve citation faithfulness.

### Cited Findings
- **Persistence and compute.**
  - On BrowseComp, "three factors explained 95%" of variance; "token usage by itself explains 80%," with tool-call count and model choice the other two. "Upgrading to Claude Sonnet 4 is a larger performance gain than doubling the token budget on Claude Sonnet 3.7" [vendor, older: 2025] — [Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system)
  - OpenAI: performance "scales smoothly as a function of the amount of test-time compute" — [arXiv 2504.12516](https://arxiv.org/abs/2504.12516)
  - MiroThinker: performance "improves predictably" with interaction depth — [arXiv 2511.11793](https://arxiv.org/abs/2511.11793)
  - The most independent benchmark the earlier retrieval notes found: modern models need deep loops on BrowseComp-like tasks. But on enterprise-style QA, two iterations captured 95% of the gains (Track 05 §1).
- **Verification and selection.** Best-of-N on deep research's own confidence beat majority and weighted voting (+15–25% overall); "the model frequently 'knows' when it's right" — [arXiv 2504.12516](https://arxiv.org/abs/2504.12516). ChatGPT agent rose from 41.6% to 44.4% on HLE with parallel runs and confidence selection — [AI News](https://www.ainews.com/p/chatgpt-agent-can-now-act-on-your-behalf-using-its-own-virtual-computer). Microsoft's generator plus rubric reviewer (Critique) gave +7.0 on DRACO with p < 0.0001 [vendor] — [Microsoft 2026](https://techcommunity.microsoft.com/blog/Microsoft365CopilotBlog/introducing-multi-model-intelligence-in-researcher/4506011). Tongyi Heavy (parallel agents plus a synthesis agent over compressed reports) raised BrowseComp from 43.4 to 58.3 — [arXiv 2510.24701](https://arxiv.org/abs/2510.24701)
- **Context hygiene.**
  - Claude dynamic filtering: "context pulled in from search is often irrelevant, which degrades the quality of the response." +11% average at −24% input tokens — [Claude blog](https://claude.com/blog/improved-web-search-with-dynamic-filtering)
  - Kimi K2.5: context management alone moves BrowseComp from 60.6 to 74.9. The swarm, as "proactive context management," reaches 78.4 — [arXiv 2602.02276](https://arxiv.org/abs/2602.02276)
  - CORE: returning one best snippet per long passage, with expand-on-demand and duplicate suppression, gives SOTA evidence recall — [arXiv 2611.07859](https://arxiv.org/abs/2611.07859)
  - Search-o1's Reason-in-Documents condenses before injection — [arXiv 2501.05366](https://arxiv.org/abs/2501.05366)
- **Parallel subagents: what they do and don't buy.**
  - They buy speed: up to 90% time reduction (Anthropic), 3–4.5x (Kimi) — [Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system); [arXiv 2602.02276](https://arxiv.org/abs/2602.02276)
  - They buy accuracy on breadth: Claude multi-agent +90.2% on an internal breadth-heavy eval, and Opus 4.6 BrowseComp from 84% to 86.8% with a multi-agent harness — [Anthropic 4.6](https://www.anthropic.com/news/claude-opus-4-6)
  - They cost tokens: about 15x chat — [Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system)
  - They don't fit everywhere. Tasks needing shared context or many dependencies, "for example, most coding tasks," are poor fits — [Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system)
  - **Decomposition Buys Integrity, Not Yield** (Sep 2026) [single author, modeling plus production traces] — [arXiv 2609.17464](https://arxiv.org/abs/2609.17464):
    - On 600 production deep research traces, the per-hop retention exponent is δ = 0.34, so "flat is optimal for yield."
    - Each delegation tier costs alignment: one brief in sixteen goes off-target.
    - Depth limits root-context exposure (N → N^(1/k)) and is cheaper at scale: flat agents bill as N^1.39, and two tiers overtake flat at about 403 findings.
    - Only "0.7% to 11.3% of production sessions are worth delegating."
  - ArcticSwarm: letting parallel agents read peers' partial findings causes convergence on an early candidate. Gated isolation plus structured review took BrowseComp-Plus from 74.5% to 82.6% — [arXiv 2609.01870](https://arxiv.org/abs/2609.01870)
- **Query strategy and first moves.**
  - Broad-then-narrow prompting fixed over-specific queries — [Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system)
  - "Broad but shallow" first pass in enterprise retrieval — [Microsoft 2025](https://techcommunity.microsoft.com/blog/microsoft365copilotblog/researcher-agent-in-microsoft-365-copilot/4397186)
  - Redundancy penalties (DeepDive, StepSearch) — [arXiv 2509.10446](https://arxiv.org/abs/2509.10446); [arXiv 2505.15107](https://arxiv.org/abs/2505.15107)
  - Question's Gambit clue decomposition took gpt-5.5 from 83.1% to 90.5% on BrowseComp-Plus (Track 05 §1)
- **Tool and source quality.** Rewriting tool descriptions gave −40% task time. Source-quality heuristics stopped content-farm bias — [Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system). Restricting search to trusted domains is now a product feature: ChatGPT DR (Feb 2026) — [Wikipedia](https://en.wikipedia.org/wiki/ChatGPT_Deep_Research); Claude `allowed_domains` — [docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)
- **Planning and commitment control.**
  - DeepRewind's reversible commitments: −59% premature commitments — [arXiv 2609.36344](https://arxiv.org/abs/2609.36344)
  - LongCat's planning agents help, but extra plan refinement is mixed — [arXiv 2609.36071](https://arxiv.org/abs/2609.36071)
  - Writing after research, rather than in parallel, avoids disjointed reports — [LangChain](https://www.langchain.com/blog/open-deep-research)
  - Outline-linked evidence memory cuts citation hallucination — [arXiv 2509.13312](https://arxiv.org/abs/2509.13312)
- **Counter-evidence: more retrieval is not better attribution.** Fact-check accuracy falls about 42% from 2 to 150 tool calls — [arXiv 2605.06635](https://arxiv.org/abs/2605.06635). Smoothing persists across systems — [arXiv 2610.35793](https://arxiv.org/abs/2610.35793)

### Inferences
**How this differs from the user's data-lake approach.**
- Mainstream deep research is *index-light, inference-heavy*. A commodity web index (or OpenAI's cached index for Codex) returns snippets. Quality is bought at query time with 10–160+ searches, reading, filtering, cross-checking and RL-trained persistence, at roughly $1–7 and 3–30 minutes per task.
- The user's toolkit is *index-heavy, inference-light*. It converts documents and tools into structured, attributable records offline, so each lookup is precise and each citation is verifiable.
- The evidence says these are complementary:
  - Frontier agents already have the loop. They are weakest at faithful attribution, completeness on enumeration tasks, implicit requirements, run-to-run stability and context pollution.
  - A pre-structured data lake directly fixes enumeration (WANDR, WideSearch, Ko-WideSearch show agents "recover the set but not the rows"), attribution (stable IDs and spans) and context pollution (snippet plus expand, server-side filtering).
  - Microsoft's finding that enterprise queries need 30–50% *more* iterations than web queries indicates that unstructured internal corpora are harder for these agents, not easier.

**Concrete design implications for the toolkit, each traceable to the findings above:**
1. Expose search/open/find primitives with snippet-then-expand and duplicate suppression (OpenResearcher, CORE).
2. Return compact, filtered results, or allow server-side code filtering (Claude dynamic filtering).
3. Attach stable source IDs and character spans for citation agents (OpenAI annotations, Claude `cited_text`).
4. Provide novelty and coverage signals for stopping (Microsoft ΔI, Jina gap queue).
5. Offer deterministic structured queries for enumeration so agents do not have to "research" a closed set.
6. Serve over MCP so that OpenAI DR API, Gemini Deep Research, Claude agents and LangChain/STORM can all use it.
7. Optionally ship an offline environment and synthetic hard-question generator so users can train or evaluate small domain agents (Tongyi, OpenResearcher, DR Tulu recipes).

Parallel sub-agents are worth it mainly for breadth-heavy, separable requests. The "Decomposition buys integrity" data suggests most sessions should stay single-agent.

### Gaps
- No public ablation from OpenAI or Google separates the contribution of RL training from base-model strength, or measures the planning step's value.
- I found no study that measures deep research agents on a *pre-structured* corpus (tables, KG) against the same corpus as raw documents. That comparison would directly test the user's thesis, and it remains an open experiment.
- Multi-agent vs single-agent comparisons at equal token budgets are rare. Anthropic's 90.2% gain is not token-matched, and "Decomposition Buys Integrity" is a single-author study.
