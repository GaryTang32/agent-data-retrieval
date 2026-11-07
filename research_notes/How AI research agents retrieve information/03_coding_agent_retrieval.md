# How coding agents retrieve information from codebases and documentation (Codex, Claude Code, Cursor, Copilot, Amp, Aider, Windsurf/Devin, Augment, research systems)

Scope note (written 2026-11-07). This track covers retrieval *inside* coding agents: codebase search, docs lookup, context/instruction files, memory and compaction. Web deep research and web-search backends are other tracks. Earlier notes already cover "Is Grep All You Need?" (arXiv 2605.15184), DCI/Dr-DCI/GrepSeek/RARG, Anthropic's context-engineering post and OpenAI's harness-engineering AGENTS.md lessons (`Agent ready data lake toolkit/storage_agent_retrieval.md`, `Searchable agent knowledge base construction/05_agentic_search_memory.md`). This file only refers to them where needed.

Labels: [vendor] = a company describing its own product. [primary-code] = read directly in source code. [community] = third-party write-up or reverse engineering. [older: YEAR] = information from before 2026.

**One-paragraph answer to the user's question.** No mainstream coding agent turns its corpus (let alone the internet) into a local vector DB at query time.
- **Codex (CLI, IDE, cloud):** ships no code index of any kind. The model runs `rg`/`rg --files`, `cat`/`sed` and similar commands in a sandboxed shell, edits with `apply_patch`, and is primed by AGENTS.md files capped at 32 KiB. When it needs the web, it calls a *hosted* `web_search` tool. By default that tool answers from "an OpenAI-maintained index of web results" on OpenAI's servers, not from anything on the user's machine.
- **Claude Code:** has used the same "agentic search" (glob/grep/read in a loop) since early 2025, after trying Voyage-embedding RAG. As of late 2026 it even folds Glob/Grep into the Bash tool on macOS/Linux, using embedded `bfs`/`ugrep`.
- **Cursor:** was the main embeddings champion. It published a +12.5% accuracy result for semantic search in Nov 2025, but in July 2026 it turned its semantic index down in favour of a local, git-anchored regex index ("Instant Grep"), and it removed @Docs crawling in 3.14.2.
- **Sourcegraph Cody:** dropped embeddings for keyword/BM25 search in 2024.
- **Counter-trend:** Copilot, Augment, JetBrains (Air Context) and Windsurf keep or add *server-side* semantic indexes, mostly offered as one tool among grep/LSP. Their vendor numbers show small (Copilot coding agent: -2% time) to large (Augment: +30–80% on its own benchmark) effects.
- **Research (2026):** shows that the answer depends on model strength, query type (identifier vs concept, hop depth), harness, and how results are delivered.

---

## 1. OpenAI Codex (CLI, IDE, cloud; codex-1, GPT-5-Codex and successors): tools, AGENTS.md, sandbox, exploration, compaction

### Takeaway
Codex retrieves code purely by letting a model trained with reinforcement learning (RL) run shell commands (preferring ripgrep) inside a sandbox. There is no embedding or codebase index anywhere in the open-source harness. Persistent project knowledge comes from concatenated AGENTS.md files (32 KiB budget by default). Web information comes from a hosted `web_search` tool that by default serves results from OpenAI's own cached web index. Long sessions survive through server-side compaction (`/responses/compact`) plus a "handoff summary" prompt. BM25 appears only for discovering *tools* (MCP/app connectors), not code.

### Cited Findings
**Search tools in the open-source CLI (source read at commit 57a808a, 2026-11-07)** [primary-code]
- The model prompts tell Codex: "When searching for text or files, prefer using `rg` or `rg --files` respectively because `rg` is much faster than alternatives like `grep`. (If the `rg` command is not found, then use alternatives.)" (`codex-rs/core/gpt_5_codex_prompt.md`, `gpt-5.2-codex_prompt.md`, `gpt_5_2_prompt.md`) — [openai/codex repo](https://github.com/openai/codex)
- The tool-handler directory (`codex-rs/core/src/tools/handlers/`) contains:
  - shell/`unified_exec` (a command runner)
  - `apply_patch`
  - `plan`
  - `view_image`
  - MCP and MCP-resource handlers
  - multi-agent handlers
  - `tool_search`
  - `request_user_input`
  - a few others

  There is no dedicated grep, read-file or semantic-search tool. Code exploration happens through shell commands — [openai/codex repo](https://github.com/openai/codex)
- A recursive grep for "embedding"/"vector store"/"semantic search" across `codex-rs/**/*.rs` finds no code index. The hits are unrelated uses of the word (for example "Embeddings" meaning hosts that embed the agent) — [openai/codex repo](https://github.com/openai/codex)
- `tool_search` uses the Rust `bm25` crate. Its description says it "Searches over apps/connectors tool metadata with BM25 and exposes matching tools for the next model call." In other words, BM25 is used for progressive disclosure of tools, not for code retrieval — [openai/codex repo](https://github.com/openai/codex)
- The `codex-file-search` crate is a fuzzy *filename* finder for the UI (the @-file picker). Its README says it uses the `ignore` crate ("which is what `ripgrep` uses") to walk the tree while honouring `.gitignore`, plus `nucleo-matcher` for fuzzy matching — [openai/codex repo](https://github.com/openai/codex)
- Web search is a hosted Responses-API tool (`ToolSpec::WebSearch`) with modes Cached → `external_web_access=false`, Indexed → `indexed_web_access=true`, Live, and Disabled (`codex-rs/core/src/tools/hosted_spec.rs`) — [openai/codex repo](https://github.com/openai/codex)

**Official docs**
- `web_search` modes: "`cached` (default) serves results from the web search cache"; "`indexed` permits external web access only when the search index gates the request"; "`live` fetches the most recent data from the web"; `disabled` turns the tool off.
  - The cache is "an OpenAI-maintained index of web results".
  - Cached mode "reduces exposure to prompt injection from arbitrary live content".
  - "Treat web results as untrusted".
  - With `--yolo`, search defaults to live.

  [vendor] — [Codex config basics](https://learn.chatgpt.com/docs/config-file/config-basic)
- AGENTS.md discovery:
  - Global `~/.codex/AGENTS.override.md` or `AGENTS.md` is read first.
  - Codex then walks from the project root (the git root) down to the current directory, taking at most one file per directory (override, then AGENTS.md, then any `project_doc_fallback_filenames`).
  - Files are concatenated root-first, so "Files closer to your current directory override earlier guidance because they appear later in the combined prompt".
  - `project_doc_max_bytes` defaults to 32 KiB.
  - The chain is rebuilt once per run.

  [vendor] — [Codex AGENTS.md guide](https://learn.chatgpt.com/docs/agent-configuration/agents-md.md). The code confirms this: `AGENTS_MD_MAX_BYTES = DEFAULT_PROJECT_DOC_MAX_BYTES; // 32 KiB` and "We do **not** walk past the project root" — [openai/codex repo](https://github.com/openai/codex)
- The model prompt includes an "AGENTS.md spec": "The scope of an AGENTS.md file is the entire directory tree rooted at the folder that contains it… For every file you touch in the final patch, you must obey instructions in any AGENTS.md file whose scope includes that file" — [openai/codex repo](https://github.com/openai/codex)

**Agent loop and context management (OpenAI engineering blog, Michael Bolin, Jan 23, 2026)**
- The loop works like this: the model either answers or emits tool calls, the harness executes them and appends their output, and this repeats.
  - The sandbox applies "only to the Codex-provided `shell` tool". MCP tools "are responsible for enforcing their own guardrails".
  - Prompt order is: sandbox developer message, then optional `developer_instructions`, then aggregated AGENTS.md user instructions, then the user message.
  - The old prompt "is an exact prefix of the new prompt", which enables caching. Mid-session config changes are therefore *appended* rather than edited in place.
  - Codex does not use `previous_response_id`, "primarily to keep requests fully stateless", which also eases Zero Data Retention.
  - Compaction calls the `/responses/compact` endpoint once `auto_compact_limit` is exceeded. It returns a `compaction` item that "preserves the model's latent understanding of the original conversation".

  [vendor; read via a mirror because openai.com returned 403] — [OpenAI: Unrolling the Codex agent loop](https://openai.com/index/unrolling-the-codex-agent-loop); [mirror](https://bittide.aicompass.dev/article/3400a5f3-b6cb-46f5-81ee-6d53ec65a81e?locale=en)
- The local fallback compaction prompt reads: "You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another LLM that will resume the task." It asks for progress and decisions, constraints, next steps, and "critical data, examples, or references". The resumed model is told: "Another language model started to solve this problem and produced a summary…" (`codex-rs/prompts/templates/compact/`). Config keys include `model_auto_compact_token_limit` — [openai/codex repo](https://github.com/openai/codex)

**Cloud Codex and the model**
- Codex launched May 16, 2025 as a cloud agent powered by codex-1, "a version of OpenAI's o3 optimized for programming", "trained using reinforcement learning on real-world examples".
  - Each task runs "in an isolated container without internet access or UI execution capabilities", preloaded with the repository.
  - It returns test outputs and terminal logs as evidence.
  - AGENTS.md files are "repository-level instructions that help guide the agent through project-specific practices and testing procedures".

  [vendor via press, older: 2025] — [InfoQ](https://infoq.com/news/2025/05/openai-codex)
- Codex Cloud (legacy) blocks internet during the agent phase by default. Setup scripts keep internet access to install dependencies. Optional allowlists include a "Common dependencies" preset (github.com, npmjs.com, pypi.org…) and GET/HEAD/OPTIONS-only methods. Documented risks are "Prompt injection from untrusted web content", exfiltration, malware and licensing — [Codex cloud internet access](https://learn.chatgpt.com/docs/cloud/internet-access)

### Inferences
- "Codex information retrieval" splits into two unrelated mechanisms:
  - **Local corpus:** model-driven `rg`/shell over the live filesystem. It needs zero ingestion and always reads the current checkout.
  - **Web:** a call to OpenAI's hosted search service, by default a pre-built cached index.

  The quality comes from (a) RL training of the model on exactly this tool loop, (b) fast exact-match tools, (c) AGENTS.md as a small always-loaded map, and (d) compaction for long runs. It does not come from a client-side semantic index.
- The one place Codex uses ranking-based retrieval (BM25 over tool metadata) is where the corpus is *descriptions* rather than files. That is a useful precedent for "tool lakes" in the user's toolkit.

### Gaps
- OpenAI has not published an ablation of Codex with vs. without any semantic search tool. I found no statement from OpenAI explaining *why* Codex has no code index (Anthropic and Cursor did explain their choices).
- The internals of the hosted web-search index (crawl, ranking) are not documented. That belongs to the search-backend track.
- The harness-engineering AGENTS.md post (Feb 2026) returned 403. It is summarized from secondary sources in the earlier notes.
- The GPT-5-Codex system-card addendum (Sep 15, 2025) also returned 403. Search snippets mention adaptive reasoning time (for example "93.7% fewer tokens" on easy requests), but I could not verify them, so they are not cited as findings.

---

## 2. Claude Code: agentic search, why not vector RAG, CLAUDE.md memory, subagents, compaction, MCP

### Takeaway
Claude Code deliberately uses no index. The model searches with grep/find-style tools in a loop (now usually via Bash with embedded `bfs`/`ugrep`), reads files in pages, and delegates broad exploration to a read-only Explore subagent so search noise stays out of the main context. Anthropic's stated reasons for dropping an early Voyage-embedding RAG prototype were:
- it performed better ("by a lot", per internal benchmarks plus "mostly vibes")
- the index drifts out of sync with the code
- the index has to live somewhere, which is a security problem

The admitted costs are latency and tokens. CLAUDE.md/AGENTS.md, auto memory, path-scoped rules, on-demand skills, deferred MCP tools and compaction make up the context-management layer.

### Cited Findings
**Why agentic search (primary and near-primary)**
- Boris Cherny on Hacker News (Feb 24, 2025): "Claude Code doesn't use RAG currently. In our testing we found that agentic search out-performed RAG for the kinds of things people use Code for." [primary, older: 2025] — [HN comment](https://news.ycombinator.com/item?id=43164253)
- Cherny in a talk (reported May 27, 2025):
  - "We indexed the code base, I think using Voyage, just off-the-shelf RAG, and that worked pretty well… Eventually, we landed on just agentic search."
  - "It outperformed everything else by a lot. By a lot. This was surprising."
  - Evidence: "some internal benchmarks also, but mostly vibes".
  - Downsides of the index: "the code drifts out of sync. Then there are security issues because this index has to live somewhere."
  - The trade: "at the cost of latency and tokens, you now have really awesome search without the security downsides."

  [secondary quoting a video, older: 2025] — [OfficeChai](https://officechai.com/ai/claude-researcher-explains-how-agentic-search-performed-better-than-rag-for-code-generation/)
- Anthropic's Agent SDK guidance (Sep 29, 2025):
  - Semantic search is "usually faster than agentic search, but less accurate, more difficult to maintain, and less transparent".
  - "start with agentic search, and only add semantic search if you need faster results or more variations".
  - "the folder and file structure of an agent becomes a form of context engineering".

  [vendor, older: 2025] — [Building agents with the Claude Agent SDK](https://claude.com/resources/articles/building-agents-with-the-claude-agent-sdk)

**Tools as of Nov 2026 (official docs)**
- The agentic loop is "gather context, take action, and verify results". Tool categories are File operations, Search ("Find files by pattern, search content with regex"), Execution, Web, and Code intelligence (LSP plugins) — [Claude Code: How it works](https://code.claude.com/docs/en/how-claude-code-works)
- "On macOS, Linux, and WSL, Claude Code leaves Glob and Grep out of the default tool set, and Claude searches with `find` and `grep` through the Bash tool instead. In Claude's shell those two commands run embedded versions of `bfs` and `ugrep`."
  - When present, Grep "is built on ripgrep", respects `.gitignore`, and has output modes `files_with_matches` (default), `content` and `count`, plus `head_limit`/`offset` paging.
  - Glob is "capped at 100 files" and sorted by mtime.
  - Read returns at most 25,000 tokens per call by default and refuses whole files over 256 KB, so larger files are paged with offset/limit.
  - Tool output over about 30,000 characters is saved to a file with a 2,000-character preview "and Claude reads or searches the file when it needs the rest".
  - No semantic or vector search tool exists.

  [vendor] — [Claude Code tools reference](https://code.claude.com/docs/en/tools-reference)
- Explore subagent: "A fast, read-only agent optimized for searching and analyzing codebases". Write and Edit are denied. Claude chooses a thoroughness level (quick / medium / very thorough).
  - It "keeps exploration results out of your main conversation context".
  - Explore and Plan start without CLAUDE.md "to keep research fast and inexpensive".
  - It uses the main conversation's model, but users can override it (e.g. `model: haiku`).

  [vendor] — [Claude Code subagents](https://code.claude.com/docs/en/sub-agents)
- Context management:
  - Auto-compaction "keeps your requests and key code snippets, but detailed instructions from early in the conversation may be lost". A "Compact Instructions" section in CLAUDE.md or `/compact <focus>` steers it.
  - "MCP tool definitions are deferred by default and loaded on demand via tool search."
  - Skills load in full only when used.
  - Subagent tool calls stay out of the main context, which gets back only a summary.

  [vendor] — [Claude Code: How it works](https://code.claude.com/docs/en/how-claude-code-works)
- Memory:
  - CLAUDE.md files above the working directory load at launch. Subdirectory CLAUDE.md files load "once Claude reads, writes, or edits another file in that subdirectory".
  - Target is "under 200 lines per CLAUDE.md file". `@path` imports "don't reduce its context cost".
  - `.claude/rules/` with `paths:` frontmatter load only for matching files.
  - AGENTS.md can be read in place of CLAUDE.md.
  - Auto memory: the first 200 lines or 25KB of MEMORY.md load each session, and further topic files are read on demand.

  [vendor] — [Claude Code memory docs](https://code.claude.com/docs/en/memory)

**Criticism (vendor-interested)**
- Zilliz (the Milvus vendor, Aug 2025) argues grep-only retrieval "burns too many tokens". Its "Claude Context" MCP server (AST chunking + Merkle change detection + hybrid BM25/vector in Milvus) claims "over 40%" token reduction "without any loss in recall". The article documents only one anecdotal scenario, with no methodology [vendor, older: 2025] — [Zilliz blog](https://zilliz.com/blog/why-im-against-claude-codes-grep-only-retrieval-it-just-burns-too-many-tokens)
- The earlier notes' "Is Grep All You Need?" result also applies here. The same Opus 4.6 scored 93.1 in a custom harness vs 76.7 inside Claude Code on a LongMemEval subset, so harness effects are as large as retriever effects — [arXiv 2605.15184](https://arxiv.org/abs/2605.15184)

### Inferences
- Claude Code and Codex have converged on the same design: shell plus fast grep, no index, read-only search subagents, compaction, a small always-loaded instruction file, and on-demand loading of everything else (nested instruction files, rules, skills, MCP tools).
- Anthropic's evidence is internal and partly "vibes". The strongest *public* evidence for the design comes from third-party 2026 studies (Section 5), and those are mixed.

### Gaps
- Anthropic has published no quantitative grep-vs-RAG ablation for Claude Code.
- The leaked March 2026 source snapshot that some community posts analyse was not used here.
- The exact auto-compaction trigger threshold for 2026 versions is not stated on the pages I read. A 2025 LangChain post cited in the earlier notes said 95%.

---

## 3. Cursor: from embeddings to "Instant Grep" (indexing pipeline, published evals, @Docs, rules)

### Takeaway
Cursor ran a full server-side semantic pipeline:
- tree-sitter-style syntactic chunks
- embeddings with its own model trained on agent traces
- Merkle-tree sync
- simhash-based index reuse across teammates

It published the most-cited pro-embedding result: +12.5% average accuracy offline, +0.3% code retention online (+2.6% on 1,000+-file repos). It also trained Composer 1–2 with semantic search in the loop. Then, in July 2026, Cursor staff announced that "Semantic/embeddings indexing is being turned down in favor of grep-based retrieval" because models had become good enough at grep that the semantic path "was rapidly no longer helping in a meaningful way". Its replacement is Instant Grep: a local sparse-n-gram regex index anchored to a git commit. The @Docs crawler was removed in 3.14.2 because "The agent is now much better at finding and reading documentation on its own." This is the clearest documented case of a major vendor moving *away* from vector indexes in 2026.

### Cited Findings
**The embedding era (2025 – early 2026)**
- "Improving agent with semantic search" (Nov 6, 2025; Heule, Jia, Jain):
  - Cursor trained its own embedding model from agent sessions: "an LLM ranks which content would have been most helpful at each step", and the embedder is trained to match those rankings.
  - On the Cursor Context Bench it reports an average +12.5% accuracy (6.5%–23.5% depending on model) "in every configuration".
  - In an online A/B test, code retention rose +0.3% (+2.6% on codebases with 1,000+ files), and there was a "2.2% increase in dissatisfied follow-up user requests when semantic search was not available".
  - The authors write that semantic search is "currently necessary to achieve the best results" in large codebases, and that "the combination" with grep is best.

  [vendor, older: 2025] — [Cursor blog: semsearch](https://cursor.com/blog/semsearch)
- "Securely indexing large codebases" (Jan 27, 2026; Stribling):
  - A Merkle tree of file/folder hashes syncs only changed branches.
  - Changed files are split into "syntactic chunks" and embedded asynchronously, with embeddings cached by chunk content.
  - Clones in an org average "92% similarity", so a new user's simhash is matched against teammates' indexes and copied. Results are filtered by Merkle "proof of possession" with "encrypted paths".
  - Semantic search is unavailable until about 80% of indexing completes.
  - Time-to-first-query fell from 7.87 s to 525 ms (median), 2.82 min to 1.87 s (p90), and 4.03 h to 21 s (p99).

  [vendor] — [Cursor blog: secure codebase indexing](https://cursor.com/blog/secure-codebase-indexing)
- Composer 2 Technical Report (Mar 25, 2026): the model "has access to a small set of general tools that allow it to read and edit files, run shell commands, search the codebase using grep or semantic search, and search the web". RL runs in the production harness, and "Some tools like semantic search have external dependencies and are handled outside of the environment". Self-summarization is learned via RL for long horizons [vendor] — [arXiv 2603.24477](https://arxiv.org/abs/2603.24477)

**The turn to grep (Mar–Nov 2026)**
- "Fast regex search: indexing text for agent tools" (Mar 23, 2026; Vicent Marti):
  - "the agents just _love_ to use `grep`".
  - Ripgrep runs of "more than 15 seconds" are routine in monorepos.
  - Cursor surveyed trigram (google/codesearch, zoekt), suffix-array (livegrep), masked-trigram (GitHub Blackbird) and sparse n-gram (ClickHouse, GitHub Code Search) designs.
  - The index is built and queried locally, "anchored to a Git commit, with user and agent changes stored as a layer on top".
  - "an index for regular expression search also needs to be _very fresh_". By contrast, semantic indexes tolerate staleness because re-embedding a modified file barely moves it.

  [vendor] — [Cursor blog: fast regex search](https://cursor.com/blog/fast-regex-search)
- Current docs (Nov 2026), the Agent → Search page:
  - "Cursor ships with Instant Grep, a custom search engine that outperforms ripgrep on large codebases."
  - "Instant Grep builds and queries its index on your machine. Cursor does not upload file paths or code to build a search index, and it does not store embeddings of your codebase for search."
  - The Explore subagent "runs in its own context window with a faster model… returning only the relevant findings".

  [vendor] — [Cursor docs: Search](https://cursor.com/docs/context/codebase-indexing)
- Forum (staff posts, Jul 21–31, 2026):
  - "the older dedicated semantic search path was rapidly no longer helping in a meaningful way". Cursor is "no longer computing embeddings of your code or storing them on our servers for search".
  - "Semantic/embeddings indexing is being turned down in favor of grep-based retrieval". The 250,000-file limit applied only to the semantic index.
  - The Instant Grep index lives in `.git/cursor/`. Non-git projects fall back to ripgrep.
  - User objections:
    - concept queries without a seed identifier ("where do we handle DTC ship updates") got worse
    - stale archive files now get grepped as "current product truth"
    - runaway `rg.exe` CPU
  - Other users reported no degradation with Opus 5.5 / Grok 4.7.

  [vendor staff + users] — [Cursor forum thread](https://forum.cursor.com/t/what-do-you-think-about-cursor-removing-the-codebase-indexing-settings/165899)
- @Docs: "the Docs feature… was removed on purpose starting in Cursor 3.14.2… The agent is now much better at finding and reading documentation on its own." Suggested replacements: paste doc URLs, "Keep the docs you rely on as local Markdown files in your workspace", and put guidelines into rules or skills (Colin, Sep 4, 2026) [vendor staff] — [Cursor forum: How to add documents](https://forum.cursor.com/t/how-to-add-documnets/170530)

### Inferences
- Cursor's arc is the strongest real-world data point:
  - Even a vendor with a custom agent-trace-trained embedder and a published +12.5% offline gain decided, about 8 months later, that with 2026 frontier models the semantic tool no longer paid for its cost, staleness and privacy surface.
  - The *online* gains were always small (+0.3% retention), which foreshadowed that decision.
  - Cursor kept an *index*, but changed what it indexes: exact text/regex rather than meaning.
- The tension in the user complaints ("grep needs a seed term"; stale archives) is exactly where a semantic or metadata layer still helps on non-code corpora. Concept-level queries and authority/currency filtering are both things grep cannot do.

### Gaps
- Cursor published no post-hoc evaluation showing semantic search's benefit had vanished. The only rationale is in forum statements.
- The exact release that disabled semantic search for all users is unconfirmed (forum users cite 3.12+). The privacy-policy change (Aug 2026) is reported only by a third-party diff tracker, which I did not read.
- Cursor rules (`.cursor/rules`) internals were not re-read here. The earlier notes cover rules files generally.

---

## 4. Other products: GitHub Copilot, Sourcegraph Cody → Amp, Aider, Windsurf/Devin, Augment, JetBrains, Zed, Cline, DeepWiki

### Takeaway
The industry has split into two camps:
- **No-index agentic search:** Codex, Claude Code, Cline, Zed, Amp's documented tools, Aider's map plus model-requested files, and (since 2026) Cursor.
- **Server-side semantic indexes offered as one more tool:** Copilot (GitHub-built remote indexes plus a new embedding model), Augment Context Engine (per-user real-time index, now sold as an MCP server), JetBrains Air Context (embeddings on JetBrains servers for Claude Code, Codex and Junie), and Windsurf/Devin (RAG "M-Query" plus RL-trained grep subagents).

Sourcegraph is the earliest example of abandoning embeddings (2024), and its reasons match Anthropic's: third-party data exposure, maintenance, scale and freshness. Its quality claim was only "equal or better", not a measured gain.

### Cited Findings
**GitHub Copilot**
- Semantic index build time dropped from "approximately five minutes" to seconds (worst case up to 60 s), on all tiers with no repo cap (Mar 12, 2025) [vendor, older: 2025] — [GitHub changelog](https://github.blog/changelog/2025-03-12-instant-semantic-code-search-indexing-now-generally-available-for-github-copilot/)
- New Copilot embedding model (Sep 24, 2025; Microsoft CoreAI):
  - Trained with contrastive InfoNCE + Matryoshka on hard negatives mined from public and internal repos, with LLMs surfacing "near misses".
  - Reported results: +37.6% retrieval quality (0.362 → 0.498 average score), about 2x throughput, about 8x smaller index, +110.7%/+113.1% code-acceptance lift for C#/Java.
  - It powers chat, agent, edit and ask modes.

  [vendor, older: 2025] — [GitHub blog](https://github.blog/news-insights/product-news/copilot-new-embedding-model-vs-code/)
- Copilot coding agent added a semantic code search tool that finds code "based on meaning rather than relying on exact text matches with tools like grep". Internal testing found "2% less time without any change in quality" (Mar 17, 2026) [vendor] — [GitHub changelog](https://github.blog/changelog/2026-03-17-copilot-coding-agent-works-faster-with-semantic-code-search/)
- VS Code docs (Nov 4, 2026):
  - Agents combine semantic search (`#codebase`), text search, grep, file search, usages (LSP), list directory and read file.
  - "An index helps find relevant snippets; it doesn't put the entire workspace into each model request" and "It doesn't guarantee that every relevant file is found."
  - GitHub builds a remote index "once per repository" (GitHub.com/GHEC, not GHES). Local folders can use "external ingest", which "uploads indexable workspace files to GitHub". Results "might be incomplete or out of date for local changes".
  - Without an index, agents fall back to text search, grep, file search and language intelligence. "For small projects, the entire workspace can be read directly into the agent's context."

  [vendor] — [VS Code: How Copilot understands your workspace](https://code.visualstudio.com/docs/agents/reference/workspace-context)
- Copilot cloud/coding agent sessions on GitHub Actions run up to 59 minutes, with the GitHub MCP server on by default (scoped to the repo). Chat "supports semantic code search, limited to default branches only" [vendor] — [GitHub docs: about Copilot coding agent](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)

**Sourcegraph Cody → Amp**
- Feb 15, 2024 (Alex Isken): Cody moved off embeddings. Reasons given:
  - "Your code has to be sent to a 3rd party (OpenAI) for processing"
  - embeddings add complexity "that Sourcegraph admins have to manage"
  - "searching vector databases for codebases with >100,000 repositories is complex and resource-intensive"
  - vectors must be "stored, maintained, and updated"

  The replacement pipeline is query tokenization → Sourcegraph search with "an adapted form of the BM25 ranking function alongside other signals" → local IDE snippets → global ranking to top-N. No benchmarks were given [vendor, older: 2024] — [Sourcegraph blog](https://testwww.sourcegraph.com/blog/how-cody-understands-your-codebase)
- Cody FAQ: embeddings were removed in v5.3, with Sourcegraph Search the primary context provider. "The most important aspect is getting the files from the codebase, not the specific algorithm used to find those files." Quality is described as "equal to or better" [vendor, older: 2024–25] — [Sourcegraph Cody FAQ](https://7.2.sourcegraph.com/cody/faq)
- Amp (Sourcegraph's agent):
  - The Librarian (Oct 20, 2025) is "a subagent for searching remote codebases", covering public GitHub and the user's private repos.
  - Task subagents run "the same model and reasoning effort as your thread, in its own context window", with read-only skills such as "Search code in your workspace" and "Research another repository… by cloning it and reading its code".
  - Its docs mention no embedding index.

  [vendor] — [Amp: The Librarian](https://ampcode.com/news/librarian); [Amp docs: tools](https://ampcode.com/docs/tools)

**Aider repo map**
- Aider parses code with tree-sitter to find definitions and references, then builds a file graph ("each source file is a node and edges connect files which have dependencies"). It ranks the graph and sends only the top-ranked identifiers and signature lines within `--map-tokens` (default 1k, expanded when no files are in chat). The LLM then asks for whole files [older: 2023 blog; docs current] — [Aider blog: repomap](https://aider.chat/2023/10/22/repomap.html); [Aider docs: repo map](https://aider.chat/docs/repomap.html)
- The source shows the ranking is NetworkX **personalized PageRank**. Personalization boosts files in chat, mentioned files and path components matching mentioned identifiers. Edge weights are multiplied by 10 for identifiers mentioned in chat [primary-code] — [aider repomap.py](https://github.com/Aider-AI/aider/blob/main/aider/repomap.py)

**Cline / Roo (no index)**
- "Why Cline Doesn't Index Your Codebase" (May 27, 2025). Its three reasons:
  - "Code doesn't think in chunks"
  - "An index, by definition, is a snapshot frozen in time"
  - embeddings are "a secondary representation of your most valuable IP"

  Cline instead follows imports file by file: "No index or embeddings. Just intelligent exploration" [vendor, older: 2025] — [Cline blog](https://cline.bot/blog/why-cline-doesnt-index-your-codebase-and-why-thats-a-good-thing)
- Nik Pash (Cline head of AI), interviewed by Jason Liu (Sep 2025), lists RAG's problems as security, maintenance, "distracting" snippets and tuning burden, and argues for "narrative integrity". Evidence is anecdotal; he concedes RAG fits cost-bound settings [opinion, older: 2025] — [jxnl.co](https://jxnl.co/writing/2025/09/11/why-i-stopped-using-rag-for-coding-agents-and-you-should-too/)

**Windsurf → Devin Desktop (Cognition)**
- The docs (now hosted on docs.devin.ai) say "We've implemented an optimized RAG approach to codebase context" (M-Query). It indexes the whole local codebase, and remote repos for Teams/Enterprise. Users are told: "Pinning too much may slow down or negatively impact model performance" [vendor] — [Devin Desktop: context awareness](https://docs.devin.ai/desktop/context-awareness/overview)
- SWE-grep / SWE-grep-mini (Oct 16, 2025):
  - Motivation: agents spent ">60% of their first turn retrieving context". Embedding search is fast but "can be inaccurate, especially for complex queries that require to jump across the codebase multiple times"; "embeddings can even be counterproductive". Agentic search is accurate but slow.
  - Training: RL with reward = weighted F-β (β=0.5, favouring precision because "polluting the main agent's context hurts more than omitting some context") on file and line-range retrieval against the internal Cognition CodeSearch Eval.
  - Tools are restricted to grep/glob/read, with 8 parallel calls per turn for at most 4 turns.
  - Speed: >2,800 tok/s (mini) and >650 tok/s, served on Cerebras.
  - Results: it matched frontier models' retrieval at "an order of magnitude less time". On hard SWE-bench Verified tasks with Sonnet 4.5, Fast Context solved the same number of tasks in less time.

  [vendor, older: 2025] — [Cognition: SWE-grep](https://cognition.com/blog/swe-grep)
- Fast Context docs: a subagent "up to 20x faster" than traditional agentic search, triggered automatically [vendor] — [Devin Desktop: Fast Context](https://docs.devin.ai/desktop/context-awareness/fast-context)
- Devin indexing powers Ask Devin ("powered by advanced code search") and DeepWiki ("auto-generated documentation for your repositories"). Default branch plus selected branches; the method is not documented [vendor] — [Devin docs: index repo](https://docs.devin.ai/onboard-devin/index-repo)

**Augment Code**
- Real-time per-user index: "Our goal is to update your personal search index within a few seconds of any change to your files".
  - Per-branch correctness is the motivation, since a main-branch index misses feature-branch code and invites hallucinated names.
  - Custom context models prioritize "helpfulness over relevance".
  - Proof of possession via hashes; self-hosted on Google Cloud (PubSub, BigTable).

  [vendor, older: 2025] — [Augment blog: real-time index](https://www.augmentcode.com/blog/a-real-time-index-for-your-codebase-secure-personal-scalable)
- Context Engine MCP (Feb 6, 2026, updated Jun 2026): semantic search exposed to any MCP agent, local (Auggie CLI) or remote.
  - Benchmark: 300 Elasticsearch PRs × 3 prompts, scored on correctness, completeness, best practices, reuse and docs.
  - Claimed improvements: Claude Code + Opus 4.5 +80%, Cursor + Opus 4.5 +71%, Cursor + Composer-1 +30%, with fewer tool calls and turns.
  - Self-reported on one repo; model labels differ across Augment pages.

  [vendor] — [Augment blog: Context Engine MCP](https://www.augmentcode.com/blog/context-engine-mcp-now-live)

**JetBrains and Zed**
- JetBrains Air Context (page dated Nov 5, 2026): "a semantic code search service for AI coding agents". It "computes the embeddings for your code on the Air Context server", indexes incrementally, and "preserves code privacy by storing vector representations of your code rather than the raw source". It is set up for Claude Code, OpenAI Codex and Junie CLI via the `jbcontext` CLI [vendor] — [JetBrains Air Context docs](https://www.jetbrains.com/help/jetbrains-console/getting-started-with-jetbrains-context.html)
- Zed's agent tools are `grep` (regex), `find_path` (glob), `read_file`, `list_directory`, `diagnostics`, `fetch` and `search_web` (Pro only). There is no semantic search tool [vendor] — [Zed docs: tools](https://zed.dev/docs/ai/tools)

### Inferences
- Vendors that *keep* semantic indexes are mostly platform or index owners: GitHub (owns the repos), Augment (sells the engine), JetBrains, Zilliz. Vendors that *dropped* them cited freshness, privacy and maintenance first, and quality second.
- The measured *agent-level* benefit of semantic tools in vendor posts, where measured at all, is small: Copilot -2% time with equal quality; Cursor +0.3% retention. The large numbers come from offline retrieval metrics or self-designed benchmarks (Augment +30–80%).
- A third pattern is emerging: **small RL-trained search subagents with grep/glob/read tools** (SWE-grep, Cursor Explore, Claude Explore, CodeGrep, CodeScout). These replace an embedding index with a fast learned searcher, keeping freshness and gaining speed.
- JetBrains' claim that storing vectors "rather than raw source" preserves privacy is a vendor framing. Embedding inversion is a known research topic, but I did not source it in this track, so this is flagged rather than asserted.

### Gaps
- No independent head-to-head evaluation of these products' retrieval layers was found.
- Copilot's index storage location, chunking and refresh cadence beyond the VS Code page are undocumented.
- DeepWiki's generation pipeline is undocumented by Cognition.
- Amp's built-in search tool names were not visible in its docs (`amp tools list` is required).

---

## 5. Research evidence: SWE-agent ACI, Agentless, AutoCodeRover, OpenHands, LocAgent, CodeRAG-Bench, RepoCoder, CoRNStack, embedding models, grep-vs-vector studies, context rot

### Takeaway
Classic results (2023–24) show:
- one-shot sparse or dense retrieval of whole files is weak for issue resolution (BM25 recall about 40–51% vs oracle files; resolve rates fall as more retrieved context is added)
- interface design matters more than tool count (SWE-agent)
- simple localization pipelines (Agentless) can rival agents

2026 studies are mixed and conditional:
- Agentic explorers beat one-shot retrievers on exploration coverage (SWE-Explore).
- Code embedders collapse on agentic-style retrieval (CORE-Bench) and cannot tell near-clone bugs apart (ExecRetrieval).
- Structured graph/embedding tools help small models a lot but frontier models little (+17–21 pts at 1.7–4B vs +4–5 at 32B).
- A structural index can still lift localization and resolve inside one harness.
- Semantic search beat delegated grep subagents on repository QA (65.2% vs 46.2%), because of silent hand-off failures.
- Retrieval helps downstream agents only above a precision threshold (about 0.45–0.68).

### Cited Findings
**Foundations (older)**
- SWE-bench (Oct 2023):
  - The authors chose BM25 because "Dense retrieval methods are ill-suited to our setting due to very long key and query lengths".
  - BM25 file recall vs oracle was 29.6% / 44.4% / 51.1% at 13k / 27k / 50k tokens. "In almost half of the instances with the 27,000-token limit, it retrieves none of the files from the 'oracle' context."
  - Claude 2 resolved 1.96% / 1.87% / 1.22% as BM25 context grew (more context hurt), vs 4.80% with oracle files.

  [older: 2023] — [arXiv 2310.06770](https://arxiv.org/abs/2310.06770)
- SWE-agent (May 2024):
  - The agent-computer interface (ACI) adds `find_file`, `search_file` and `search_dir`, which "return at most 50 results… if a search exceeds this number, we do not report the results and instead suggest that the agent write a more specific query".
  - Ablation (SWE-bench Lite subset, GPT-4 Turbo): Summarized search 18.0%, No search 15.7%, Iterative (one-result-at-a-time) search 12.0%. A badly designed search tool was worse than none.
  - File viewer: 100 lines scored 18.0% vs full file 12.7%.

  [older: 2024] — [arXiv 2405.15793](https://arxiv.org/abs/2405.15793)
- Agentless (Jul 2024): hierarchical localization (repo tree → files → class/function "skeletons" → edit lines). It combines LLM-ranked files with "embedding-based retrieval" of files and takes the files common to both. Results: 32.0% on SWE-bench Lite at $0.70 per issue, beating open-source agents at the time [older: 2024] — [arXiv 2407.01489](https://arxiv.org/abs/2407.01489)
- AutoCodeRover (Apr 2024): AST-aware code-search APIs over classes/methods, plus iterative search and spectrum-based fault localization [older: 2024] — [arXiv 2404.05427](https://arxiv.org/abs/2404.05427)
- OpenHands (Jul 2024): an open platform whose agents work through bash, an editor and a browser. Used as the baseline harness in later retrieval studies [older: 2024] — [arXiv 2407.16741](https://arxiv.org/abs/2407.16741)
- mini-SWE-agent: "Does not have any tools other than bash", about 100 lines, ">74% on the SWE-bench verified benchmark". Evidence that frontier models need no special retrieval tools for SWE-bench-style tasks [vendor/academic] — [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent)
- RepoCoder (Mar 2023): iterative retrieve-generate for repository completion, more than 10% over the in-file baseline [older: 2023] — [arXiv 2303.12570](https://arxiv.org/abs/2303.12570)
- CodeRAG-Bench (Jun 2024): retrieval from docs, StackOverflow, tutorials and repos helps code generation when retrieved context is high quality, but "current retrievers still struggle to fetch useful contexts" [older: 2024] — [arXiv 2406.14497](https://arxiv.org/abs/2406.14497)
- LocAgent (Mar 2025): a heterogeneous code graph (files/classes/functions; imports/calls/inheritance) used with agent tools. Up to 92.7% file-level localization, and a fine-tuned 32B model comparable to proprietary models at about 86% lower cost [older: 2025] — [arXiv 2503.09089](https://arxiv.org/abs/2503.09089)
- CodexGraph (Aug 2024): agents query a graph database built from the repo. Notes that "Similarity-based retrieval often has low recall in complex tasks" [older: 2024] — [arXiv 2408.03910](https://arxiv.org/abs/2408.03910)
- Code embedding models:
  - CoRNStack (Dec 2024): consistency-filtered contrastive data with hard negatives gives SOTA code retrieval and rerankers. Notes embedders "underperform… such as bug localization within GitHub repositories".
  - CoIR (Jul 2024): ten datasets across eight task types; even SOTA retrievers struggle.
  - Voyage-code-3 (Dec 2024): claims +13.80% / +16.81% over OpenAI-v3-large / CodeSage-large on 32 datasets, 32K context, Matryoshka 256–2048 dims.

  [older: 2024; Voyage = vendor] — [arXiv 2412.01007](https://arxiv.org/abs/2412.01007); [arXiv 2407.02883](https://arxiv.org/abs/2407.02883); [Voyage blog](https://blog.voyageai.com/2024/12/04/voyage-code-3/)
- SweRank (May 2025): a retrieve-and-rerank model trained on the SweLoc issue→code dataset. It outperforms agent systems that use Claude-3.5 on SWE-bench-Lite/LocBench localization at much lower cost [older: 2025] — [arXiv 2505.07849](https://arxiv.org/abs/2505.07849)

**2026 grep vs index vs graph studies**
- SWE-Explore (Jun 2026): 848 issues, 10 languages, line-budgeted exploration. "BM25, TF–IDF and the lightweight dense retriever remain close to Random on most metrics, while every agentic explorer is substantially higher". Agentic explorers tested: Claude Code, Codex, OpenHands, mini-SWE-agent and others. Caveat: the dense baseline was a weak static-embedding model (Potion) — [arXiv 2606.07297](https://arxiv.org/abs/2606.07297)
- CORE-Bench (Jun 2026): 180K queries. Embedding models show "a sharp drop from traditional code search to code retrieval in agentic coding settings"; SFT on PR-derived supervision helps but leaves a gap — [arXiv 2606.11864](https://arxiv.org/abs/2606.11864)
- ExecRetrieval (Sep 2026): 23 dense configurations plus BM25. With near-clone buggy variants in the pool, the top system reaches exec@10 = 1.00 but exec@1 = 0.331. Rank-1 misses are the buggy twin 91.5–99.4% of the time. Embeddings find the *topic*, not the *correct* code — [arXiv 2609.01865](https://arxiv.org/abs/2609.01865)
- "How Do Small Coding Agents Use Code Graphs and Embeddings?" (Oct 2026):
  - Setup: SWE-bench Verified, tool sets grep-only / +embedding / +graph / all, 79k episodes.
  - Structured tools "double grep-only accuracy for Qwen3-8B". The gain peaks at 17–21 points at 1.7–4B and falls to 4–5 points at 32B.
  - Each extra code-graph hop multiplies the odds of localization by 0.50–0.67, and no tool set flattens this. Agents chain graph expansions in only 12–14% of episodes.

  — [arXiv 2610.33958](https://arxiv.org/abs/2610.33958)
- "Code Isn't Memory" (Jun 2026):
  - Setup: SuperCoder harness on 91 SWE-PolyBench Verified / SWE-bench Pro instances, Opus 4.7, 3 seeds.
  - With vs without its structural index: acc@5 44.3% → 84.5%; resolve 41.9% → 50.4% (p=0.003); turns 28.3 vs 36.2.
  - Against OpenCode (agentic grep): resolve 50.4% vs 45.3% (p=0.087); $/solved $2.30 vs $2.92.
  - Authors built the harness, so this is a small and possibly interested study.

  — [arXiv 2606.22417](https://arxiv.org/abs/2606.22417)
- "Deep Agentic Search for Repository-Level Code QA" (Aug 2026): on SWE-QA, a vector-index semantic search agent answered 65.2% correctly vs 46.2% for a planner delegating grep search to a subagent, at less than half the cost per correct answer. 41.8% of delegated-search failures happened "at the hand-off between the planner and its sub-agent", usually silently, ending in "a fluent and confident answer that was wrong" — [arXiv 2608.01507](https://arxiv.org/abs/2608.01507)
- CodeGrep (Aug 2026):
  - Baseline cost: a 30B OpenHands agent averages 23 rounds and 631K tokens per resolved SWE-bench Verified issue.
  - A 14B GRPO-trained parallel grep/glob/read retriever keeps resolve (27.0% vs 25.8%) with 15% fewer rounds and 19% fewer tokens.
  - "BM25 with precision 0.375 degrades the agent, Jina with precision 0.445 is neutral, and CodeGrep with precision 0.677 crosses the threshold at which retrieval begins to reduce rollout cost."

  — [arXiv 2608.05886](https://arxiv.org/abs/2608.05886)
- CodeScout (Mar 2026): RL-trained agents with "nothing more than a standard Unix terminal" are competitive with 2–18x larger LLMs and with specialized scaffolds on SWE-Bench Verified/Pro/Lite localization — [arXiv 2603.17829](https://arxiv.org/abs/2603.17829)
- FuseSearch (Jan 2026): current agents have a "34.9% redundant invocation rate" in parallel search. A 4B model trained for efficiency reaches 84.7% file / 56.4% function F1 on SWE-bench Verified with 67.7% fewer turns and 68.9% fewer tokens — [arXiv 2601.19568](https://arxiv.org/abs/2601.19568)
- LSP vs grep (Jun 2026; Opus 4.8, Sonnet 4.6, Haiku 4.5): "The answer is conditional and usually negative."
  - On symbol-named localization the LSP costs +6% to +118% tokens, and models default to grep (0–6% semantic use).
  - On reference tasks they use the LSP about half the time.
  - "grep solves multi-file renames perfectly."

  — [arXiv 2608.13568](https://arxiv.org/abs/2608.13568)
- CodeNib (Jul 2026): compiles lexical, dense and structural views of one commit under one manifest.
  - Behind LocAgent, agents finished 78/90 runs vs 65.
  - Selected context policies use "50–87% fewer tokens than grep/read across five models".
  - Incremental index repair reproduced a full rebuild on only 13 of 24 changes ("An incremental code index can complete every update without error and still return the wrong graph half the time"). Vector reuse was exact on 27 of 30.

  — [arXiv 2607.25431](https://arxiv.org/abs/2607.25431)
- Codebase-Memory (Mar 2026): a tree-sitter knowledge graph exposed via MCP gives 83% answer quality vs 92% for a file-exploration agent, at 10x fewer tokens and 2.1x fewer tool calls — [arXiv 2603.27277](https://arxiv.org/abs/2603.27277)
- Keyword shortcut (Apr 2026): localization benchmarks are "saturated with keyword references (e.g. file paths, function names)". On KA-LogicQuery, which has no naming hints, SOTA approaches drop "catastrophically" — [arXiv 2604.16021](https://arxiv.org/abs/2604.16021)
- CABRA (Oct 2026): "LLM accuracy falls as task size grows, but agents stay near-perfect by offloading work to tools (e.g., grep)". Tool-call counts predict SWE-bench difficulty better than lines edited — [arXiv 2610.10610](https://arxiv.org/abs/2610.10610)
- Physical cost of context (Oct 2026): preloading ten retrieved blocks ("Eager") cut model calls by 35.7% and the GPU-energy proxy by 33.2% vs on-demand grep. Prefix caching cut Eager's uncached prefill by 67.7%. Deleting history (keep last 5 observations) raised uncached prefill by 608.5%. Context policies must respect cache prefixes — [arXiv 2610.34763](https://arxiv.org/abs/2610.34763)
- Repository history as retrieval:
  - Chronos (Oct 2026) distills merged PRs into "experience cards" in a typed graph. Semantic search finds entry cards, then multi-hop expansion follows. Mean SWE-bench Verified resolve with SWE-agent rose from 69.2% to 72.9%.
  - Repository memory from commits also improves LocAgent (Oct 2025).

  — [arXiv 2610.11578](https://arxiv.org/abs/2610.11578); [arXiv 2510.01003](https://arxiv.org/abs/2510.01003)
- Coding agents as general long-context processors (Mar 2026): off-the-shelf coding agents that organize text as files and use native tools beat published SOTA by 17.3% on average on long-context, RAG and open-domain QA tasks (corpora up to 3T tokens). The authors credit "native tool proficiency" and "file system familiarity" — [arXiv 2603.20432](https://arxiv.org/abs/2603.20432)

**Context rot (why retrieval precision matters even with 1M-token windows)**
- Lost in the Middle (2023): accuracy is highest when relevant information is at the start or end of the context [older: 2023] — [arXiv 2307.03172](https://arxiv.org/abs/2307.03172)
- NoLiMa (Feb 2025): with minimal lexical overlap, 11 of 13 models fall below 50% of their short-context baseline at 32K; GPT-4o drops from 99.3% to 69.7% [older: 2025] — [arXiv 2502.05167](https://arxiv.org/abs/2502.05167)
- Chroma "Context Rot" (Jul 14, 2025; 18 models): performance "grows increasingly unreliable" with input length, and distractors compound the drop. On LongMemEval, focused prompts (about 300 tokens) beat full prompts (about 113k) for all models [vendor research, older: 2025] — [Chroma](https://www.trychroma.com/research/context-rot)

### Inferences
- The evidence explains the vendor convergence:
  1. Frontier models plus grep reach high localization because benchmarks and real tasks are rich in identifiers (the keyword shortcut).
  2. Semantic and structural tools add most value for weaker models, concept-level questions, multi-hop structure and cost.
  3. Retrieval that is not precise enough *hurts* (SWE-bench BM25, SWE-agent iterative search, CodeGrep's precision threshold, SWE-grep's β=0.5 reward).
- Subagent delegation is not free. The SWE-QA study's 41.8% hand-off failures are a direct counterweight to the "Explore subagent" pattern.
- Index freshness is a real correctness risk, not just latency (CodeNib's 13 of 24 incremental-repair result). This backs Anthropic, Cline and Sourcegraph's freshness argument.

### Gaps
- No study compares Codex, Claude Code and Cursor's production retrieval stacks head to head on the same model.
- Most 2026 results are single-paper preprints, often from tool builders, on SWE-bench-family data that may be contaminated.
- No public SWE-bench leaderboard breakdown by retrieval approach exists. Top entries mostly use bash-centric harnesses (e.g. mini-SWE-agent >74%), but submissions rarely ablate retrieval.

---

## 6. Documentation retrieval for coding agents: llms.txt, Context7 and docs MCP servers, web search, instruction files

### Takeaway
Coding agents get API docs in four ways, all at query time:
- (a) hosted web search plus fetch (Codex's cached index, Claude WebSearch/WebFetch, Zed `search_web`/`fetch`)
- (b) docs MCP servers such as Context7, which keeps a private, version-specific docs index and exposes `resolve-library-id` → `query-docs`
- (c) site-published markdown maps (llms.txt and `.md` page variants)
- (d) local markdown in the repo, plus AGENTS.md/CLAUDE.md as a small always-loaded map

Cursor removed its own docs crawler in 2026 and told users to keep docs as local markdown or paste URLs. Evidence that llms.txt is actually fetched is weak. Evidence on instruction files shows that overviews don't help and stale files mislead.

### Cited Findings
- llms.txt (proposed Sep 3, 2024 by Jeremy Howard, Answer.AI): a markdown file with a required H1, a blockquote summary and H2 link lists. An "Optional" section holds skippable links, and pages should have clean `.md` variants. "llms.txt would mainly be useful for inference rather than training, and that is how it has been used" [older: 2024, page updated 2026] — [llmstxt.org](https://llmstxt.org/)
- Uptake evidence (Oct 2026): in a 15-tool study, there were "no automatic requests in 45 trials" for /llms.txt. A log study found "97% of domains with detected files received no recorded requests in May 2026". In a pilot, adversarial manifest content was adopted in 21/24 responses, a security risk — [arXiv 2610.38361](https://arxiv.org/abs/2610.38361)
- HTTP fingerprints of nine coding agents (Aider, Claude Code, Cline, Cursor, Copilot, Windsurf and others) on a docs portal show agents "compress multi-page navigation into a single or two requests" — [arXiv 2604.02544](https://arxiv.org/abs/2604.02544)
- Context7 (Upstash): `resolve-library-id(query, libraryName)` maps a name to an ID such as `/vercel/next.js`, then `query-docs(libraryId, query, language?)`. It "pulls up-to-date, version-specific documentation and code examples straight from the source" and matches versions mentioned in the prompt. It also ships a CLI+skill mode. The MCP server is MIT-licensed, but "the API backend, parsing engine, and crawling engine are private" [vendor] — [upstash/context7](https://github.com/upstash/context7)
- Cursor @Docs crawler removed in 3.14.2 (see Section 3) — [Cursor forum](https://forum.cursor.com/t/how-to-add-documnets/170530)
- Amp's Librarian researches dependencies by searching or cloning their source rather than their docs (Section 4) — [Amp: The Librarian](https://ampcode.com/news/librarian)
- Instruction-file evidence:
  - **ETH study (Feb 2026):** context files "do not generally improve task success rates, while increasing inference cost by over 20%". "Repository overviews… are not helpful"; they are useful for "non-standard coding practices".

    — [arXiv 2602.11988](https://arxiv.org/abs/2602.11988)
  - **Stale instruction files (Oct 2026):** 40 projects, 320 runs. 90.1% of choices followed a stale file over the code; Claude Code flagged the conflict in 79/80 runs and still followed the file; Codex rewrote existing code in 20/80 runs, breaking tests in 17. One sentence giving code precedence moved code-following from 4.2% to 91.4%.

    — [arXiv 2610.30571](https://arxiv.org/abs/2610.30571)
  - **Agent READMEs (Nov 2025):** across 2,303 files, the most common content is test procedures (75.9%), implementation details (70.8%) and architecture (68.1%); security appears in only 14.8%.

    — [arXiv 2511.12884](https://arxiv.org/abs/2511.12884)
  - **Instruction-file templates (Nov 2026):** 3,387 files in 1,000 repos. 42.2% of popular repos keep multiple formats, and 16.1% of corresponding sections diverge.

    — [arXiv 2611.02383](https://arxiv.org/abs/2611.02383)
  - **Context rot in instruction files (Jun 2026):** stale code references found in 23.0% of 356 repos.

    — [arXiv 2606.09090](https://arxiv.org/abs/2606.09090)

### Inferences
- For docs, the dominant production pattern is *someone else's index behind a tool* (OpenAI's web cache, Context7's private index, GitHub's code-search index), queried by the agent with short keyword queries. This is the real answer to "Codex can't vectorize the internet". The heavy indexing lives in shared server-side services, and the agent sees a search API.
- llms.txt is cheap to publish but there is little evidence agents fetch it automatically. Agents reach docs through search plus fetch or MCP. A toolkit should publish `.md` page variants *and* expose a search tool rather than rely on discovery.

### Gaps
- No controlled evaluation comparing Context7 vs web search vs local docs for API-correctness was found in this track.
- Context7's internal ranking (lexical vs vector) is not disclosed.

---

## 7. Lessons for non-code corpora (the user's agent-retrievable data lake)

### Takeaway
Coding agents show that *when the corpus is local, text-like, identifier-rich and changing*, a strong model with grep/glob/read plus a small map file beats or matches an embedding index. That setup has zero ingestion, perfect freshness, no second copy of sensitive data, and transparent results. Semantic or structural indexes still pay off in the following cases:
- concept queries with no seed term
- large or remote corpora
- weaker or cheaper models
- multi-hop structure
- token or latency budgets

The design that is winning is a *hybrid served through tools*: a fresh lexical/regex index, optional semantic and structural views over the same snapshot, a small always-loaded map, and fast read-only search subagents. All of it must stay precise, because low-precision retrieval hurts.

### Cited Findings
- **Grep suffices / is preferred when:**
  - identifiers exist and models are strong — [Cursor forum](https://forum.cursor.com/t/what-do-you-think-about-cursor-removing-the-codebase-indexing-settings/165899); [arXiv 2610.33958](https://arxiv.org/abs/2610.33958); [arXiv 2604.16021](https://arxiv.org/abs/2604.16021)
  - freshness matters ("An index, by definition, is a snapshot frozen in time") — [Cline blog](https://cline.bot/blog/why-cline-doesnt-index-your-codebase-and-why-thats-a-good-thing)
  - data must not leave the machine ("this index has to live somewhere") — [OfficeChai](https://officechai.com/ai/claude-researcher-explains-how-agentic-search-performed-better-than-rag-for-code-generation/); [Sourcegraph blog](https://testwww.sourcegraph.com/blog/how-cody-understands-your-codebase)
- **Semantic index helps when:**
  - repos are large (2.6% retention gain at 1,000+ files) — [Cursor semsearch](https://cursor.com/blog/semsearch)
  - questions are conceptual or QA-style (65.2% vs 46.2% on SWE-QA) — [arXiv 2608.01507](https://arxiv.org/abs/2608.01507)
  - models are small (+17–21 pts at 1.7–4B) — [arXiv 2610.33958](https://arxiv.org/abs/2610.33958)
  - token cost matters (Codebase-Memory 10x fewer tokens; CodeNib 50–87% fewer) — [arXiv 2603.27277](https://arxiv.org/abs/2603.27277); [arXiv 2607.25431](https://arxiv.org/abs/2607.25431)
- **Precision matters more than recall for injected context:** SWE-bench's more-BM25-context-hurts result; SWE-agent's 50-result cap; SWE-grep's β=0.5 reward; CodeGrep's 0.45–0.68 precision threshold — [arXiv 2310.06770](https://arxiv.org/abs/2310.06770); [arXiv 2405.15793](https://arxiv.org/abs/2405.15793); [Cognition](https://cognition.com/blog/swe-grep); [arXiv 2608.05886](https://arxiv.org/abs/2608.05886)
- **Freshness and consistency are first-class requirements:**
  - Cursor's regex index is anchored to a git commit plus an overlay, because grep "needs to be very fresh" — [Cursor fast regex](https://cursor.com/blog/fast-regex-search)
  - Augment targets index updates "within a few seconds" per user and branch — [Augment](https://www.augmentcode.com/blog/a-real-time-index-for-your-codebase-secure-personal-scalable)
  - Incremental graph repair silently diverges from a rebuild (13/24) — [arXiv 2607.25431](https://arxiv.org/abs/2607.25431)
- **Authority/currency filtering is needed, and grep doesn't provide it:** Cursor users report agents grepping stale handoff archives as "current product truth" — [Cursor forum](https://forum.cursor.com/t/what-do-you-think-about-cursor-removing-the-codebase-indexing-settings/165899). Stale instruction files override ground truth 90.1% of the time — [arXiv 2610.30571](https://arxiv.org/abs/2610.30571)
- **Cost:**
  - Agentic search trades tokens and latency for quality ("at the cost of latency and tokens") — [OfficeChai](https://officechai.com/ai/claude-researcher-explains-how-agentic-search-performed-better-than-rag-for-code-generation/)
  - 631K tokens per resolved issue for a 30B OpenHands agent — [arXiv 2608.05886](https://arxiv.org/abs/2608.05886)
  - Prefix-cache-aware context policies matter more than raw prompt length — [arXiv 2610.34763](https://arxiv.org/abs/2610.34763)
  - Codex keeps prompts append-only for cache hits — [OpenAI agent loop](https://openai.com/index/unrolling-the-codex-agent-loop)
- **Tool discovery is itself retrieval:** Codex uses BM25 over connector tool metadata; Claude Code defers MCP tool definitions behind ToolSearch — [openai/codex](https://github.com/openai/codex); [Claude Code docs](https://code.claude.com/docs/en/how-claude-code-works)
- **General corpora as files:** coding agents over file-organized corpora beat published SOTA by 17.3% on long-context, RAG and QA tasks — [arXiv 2603.20432](https://arxiv.org/abs/2603.20432). A BM25/grep-only harness answers 85% of BrowseComp-Plus, and compiled navigation artifacts cut tokens rather than raising accuracy — [arXiv 2610.41172](https://arxiv.org/abs/2610.41172)

### Inferences (design guidance for the toolkit)
1. **Materialize the lake as a file tree of markdown/text** with stable paths, plus a small always-loaded `AGENTS.md`-style map (≤200 lines or 32 KiB; evidence says overviews add little, so keep it to non-obvious conventions and pointers). This is the interface Codex, Claude Code and Cursor models are RL-trained on.
2. **Ship a fast, fresh lexical index** (sparse n-gram or trigram regex, plus BM25 for ranking) anchored to a snapshot ID with a change overlay, as Cursor's Instant Grep does. Return capped, summarized result lists (SWE-agent style) with paging.
3. **Offer semantic and structural views as optional tools over the same snapshot** (CodeNib-style single manifest), not as the only path. Their main value is concept queries, weak or cheap models, and cross-document hops. Check every view against a rebuild.
4. **Add authority and currency metadata** (status/effective-date/superseded) so search tools can filter. Grep alone cannot tell current truth from archives.
5. **Provide a read-only search subagent pattern** but make hand-offs return evidence (paths, line ranges, quotes) so planners can verify. The SWE-QA hand-off failures argue against summary-only returns.
6. **Aim for precision in anything injected automatically.** Prefer returning handles (paths, IDs, line ranges) and letting the agent read.
7. **Expose tools via MCP and CLI**, with BM25 tool search over tool descriptions when the toolset is large. Also publish `.md` and llms.txt for external agents, but don't rely on automatic discovery.

### Gaps
- Almost all evidence is on code. Transfer to prose-heavy, identifier-poor corpora (policies, research PDFs) is plausible but unmeasured here. The non-code agentic-search evidence is in the earlier notes (DCI, Dr-DCI, Is Grep All You Need).
- No study measured the operating cost (compute, ops time) of keeping embeddings fresh vs grep at enterprise scale. Vendor statements are qualitative.
