# Procedural knowledge for agents: SOPs, workflows, runbooks, playbooks, how-tos (Track 02)

Scope: how to turn procedural documents (SOPs, runbooks/troubleshooting guides (TSGs), playbooks, how-tos, process descriptions) into a form agents can retrieve and follow; evidence on how well agents follow each form; and a recommended storage, indexing and exposure design for an open-source "agent-retrievable data lake" toolkit. Business rules/policies as standalone artifacts and generic chunking/indexing belong to other tracks and are covered here only where they touch procedures.

Status conventions: dates are first-arXiv-submission dates unless noted. "(author-reported)" means the numbers come from the paper's own authors on their own benchmark; "(vendor claim)" means a commercial source with no published method; "(independent)" means a third party evaluated a method or artifact it did not build. As of Nov 2026 most of this literature is arXiv preprints and has not been peer reviewed.

---

## 1. Representations: plain text vs step lists vs flowcharts/graphs vs pseudo-code vs code/DSL vs state machines vs BPMN — how well do LLM agents follow each?

### Takeaway
No representation wins everywhere. The controlled evidence points to a **hybrid**: a structured skeleton with explicit nodes, branches and preconditions (a flowchart or graph, or pseudo-code), with natural-language text inside each node. Structure helps most where the original prose is ambiguous, and the gains depend on the model: code-like forms help strong models and can hurt weak ones. Formal and executable forms (automata, state machines, compiled programs plus a runtime, code-enforced controllers) are what move compliance toward guarantees. They cost flexibility, so the field converges on "LLM interprets, structure or runtime enforces".

### Cited Findings
**Direct format comparisons**
- FlowBench (Alibaba/Tongyi, Jun 2024, Findings of EMNLP 2024) is the only benchmark that holds one workflow constant and varies its format. The formats were text (a natural-language document), code (Python pseudo-code) and flowchart (Markdown Mermaid). It covers 51 scenarios in 6 domains, and GPT-4 converted the text knowledge into code and flowchart form, with manual verification. The authors conclude that "flowcharts struck the best trade-off among performance, adaptability, and user-friendliness". The best model, GPT-4o, still reached only about 43.2% and 40.9% session success on some task settings — [FlowBench](https://arxiv.org/abs/2406.14884)
- FlowBench turn-level tool-invocation F1 for GPT-4o: none 66.3, text 69.1, code 69.0, flowchart 75.5. For GPT-4-Turbo: none 59.1, text 62.9, code 67.0, flowchart 73.6. At session level the formats are close. GPT-4-Turbo success rates: none 31.9, text 41.5, code 37.8, flowchart 40.6, and an ensemble of all three 45.3. "The code format is less effective on weaker LLMs… The text format… continues to perform well on different LLMs" (author-reported) — [FlowBench](https://arxiv.org/abs/2406.14884)
- Compile, Then Page (Jul 2026) separates representation from runtime on SOPBench, with three arms across six models: official prose, compiled pseudo-code text, and compiled program plus a program-guided stack-machine runtime. "Compiled text never significantly hurts and gains up to 16.0 points where official prose underperforms." The gain disappears where the prose was already good. The runtime is "capability-gated": two strong models improve across seven domains, while weak models lose 14–26 points on the Bank domain. On Bank, the three arms score 70.4 → 86.4 → 92.8, with 100% refusal correctness. Its practical rule is to "compile first; enable active-frame paging only after a model-level discipline check" (author-reported) — [Compile, Then Page](https://arxiv.org/abs/2607.11346)
- Agent Workflow Memory (CMU, Sep 2024, ICML 2025) compared code-format workflow steps (`CLICK({submit-id})`) with verbalized text on Mind2Web. Text was marginally higher on step success (45.4 vs 45.1) but lower on task success (3.6 vs 4.8). The authors read this as roughly a tie between text and code for memory — [AWM](https://arxiv.org/abs/2409.07429)
- Process-model representations (Jul 2025): nine representations compared on 55 process descriptions. Mermaid scored highest across six suitability criteria for LLM process modeling, while "BPMN text" gave the best generation similarity — [Brissard et al.](https://arxiv.org/abs/2507.11356)
- Pseudo-code prompting (IBM, May 2023): pseudo-code instructions beat natural language on 132 tasks by 7–16 absolute F1 points on classification and by 12–38% relative ROUGE-L. Comments, docstrings and structural cues all contributed. Only BLOOM and CodeGen were tested (2023 models) — [Mishra et al.](https://arxiv.org/abs/2305.11790)
- Skill-as-Pseudocode (May 2026) converts markdown skill prose into typed pseudocode contracts plus concrete action templates. On ALFWorld unseen with gpt-4o-mini, it won 82/402 paired games against 47/402 for a Graph-of-Skills baseline (p = 8.2e-5), with 22.8% fewer input tokens. The typed contract alone scored below the prose baseline; the gain comes from pairing the contract with concrete templates — [SaP](https://arxiv.org/abs/2605.27955)
- Skill presentation granularity (controlled SkillsBench study, May 2026): having a skill at all adds +18 to +36 pp. Switching between low- and high-abstraction wording or adding a worked example changes results by only about −6.7 to +1.3 pp, and every confidence interval crosses zero (independent of the SkillsBench authors) — [Xu & Wu](https://arxiv.org/abs/2605.31408)

**Graph and decision-tree forms**
- SOP-Agent (Jan 2025) writes SOPs as "pseudocode-style" natural language and compiles them into a decision graph that the agent traverses depth-first. At each node, only the SOP-relevant functions are exposed as tools. It reports 99.8% accuracy on its own Grounded Customer Service Benchmark (author-reported; the benchmark is simulated) — [SOP-Agent](https://arxiv.org/abs/2501.09316)
- Procedural Graphs (Sep 2026) store procedures as (procedure, relation, procedure) triplets. At each step the framework locates the active node, and a guidance model turns the surrounding subgraph into advice for the next step, which "biases the solver's next action without dictating it". The graph self-evolves from contrasts between failed and successful runs and reportedly matches hand-designed graphs — [Procedural Graphs](https://arxiv.org/abs/2609.09153)
- Hierarchical task networks (Nov 2025): hand-coded HTNs let 20B and 70B models outperform a 120B baseline. LLM-created HTNs also help, but less — [Hsiao et al.](https://arxiv.org/abs/2511.07568)
- WorfBench (ZJU, Oct 2024) found that LLMs are much worse at producing graph-structured workflows than linear ones: even GPT-4 shows about a 15% gap between sequence and graph planning — [WorfBench](https://arxiv.org/abs/2410.07869)

**Hybrid NL+code DSLs and formal control**
- FlowAgent (Feb 2025) proposes the Procedure Description Language (PDL), which "combines the adaptability of natural language with the precision of code". Controllers block actions whose preconditions are unmet; for example, the agent cannot announce a booking result before the booking API has run. The framework still lets the agent handle out-of-workflow (OOW) user turns — [FlowAgent](https://arxiv.org/abs/2502.14345)
- Formal-LLM (Rutgers, Feb 2024) states planning constraints as an automaton, and a stack-based generator only produces plans the automaton accepts. It reports more than 50% overall improvement and no invalid plans (author-reported) — [Formal-LLM](https://arxiv.org/abs/2402.00798)
- AutoFlow (Rutgers, Jul 2024) uses "natural language program" as the workflow format and optimizes it iteratively, by fine-tuning or in context — [AutoFlow](https://arxiv.org/abs/2407.12821); FlowMind (JPMorgan, Mar 2024) grounds generated workflows in a "lecture" of vetted APIs so the LLM never touches proprietary data directly, and shows users a high-level description of each workflow for feedback — [FlowMind](https://arxiv.org/abs/2404.13050)
- ChatSOP (Jul 2024) combines SOP prediction with MCTS planning in dialogue and reports +27.95% action accuracy over GPT-3.5 baselines — [ChatSOP](https://arxiv.org/abs/2407.03884)
- WorkflowLLM (Tsinghua/OpenBMB, Nov 2024, ICLR 2025) transcribed 106,763 Apple Shortcuts/RoutineHub workflows into Python-style code covering 1,503 APIs and fine-tuned Llama-3.1-8B on them. This is evidence that code is a convenient canonical form for *generated* workflows — [WorkflowLLM](https://arxiv.org/abs/2411.05451); ProAgent's "Agentic Process Automation" likewise represents workflows as code — [ProAgent](https://arxiv.org/abs/2311.10751)

**Execution substrate: who drives the steps?**
- Network procedures (May 2026): when the agent reasons through every step itself, latency and errors are higher than when the whole procedure is wrapped in one tool that orchestrates the sub-calls. All models degrade as procedures get longer — [Garigipati et al.](https://arxiv.org/abs/2605.02584)
- SKILL.state (Aug 2026) replaces the append-only chat history with an immutable skill specification plus an explicit, mutable execution state. Each step sees only the spec, the state and the latest observation. It reports higher accuracy and much lower cumulative tokens on long procedures — [SKILL.state](https://arxiv.org/abs/2608.26263)
- ProcBench (Oct 2024): the full procedure is given in the prompt, so the task is pure following. Exact-sequence match falls with length. o1-preview goes from 0.656 on short to 0.333 on long problems; GPT-4o goes from 0.396 to 0.204 — [ProcBench](https://arxiv.org/abs/2410.03117)
- CaT-Bench (Jun 2024): recovering step dependencies from recipe text is weak. The best zero-shot F1 is 0.59 and the best with prompting is 0.73, with models biased toward predicting a dependency — [CaT-Bench](https://arxiv.org/abs/2406.15823)

### Inferences
- When inferring step order and dependencies from prose (CaT-Bench) and following long sequences (ProcBench) are both weak, it pays to make order, branch conditions and preconditions explicit at ingestion time, once and with verification, rather than leaving the agent to work them out at every run.
- The evidence suggests storing procedures as a **graph/flowchart canonical form** (Mermaid or JSON nodes and edges, with NL text inside each node), with a **pseudo-code rendering** for strong models. The original prose should be kept for provenance and as a fallback for weak models, which FlowBench and Compile-then-Page both suggest.
- Enforcement should not rest on the representation alone. Runtime controllers, state machines or a "procedure-as-tool" wrapper are where most of the compliance gains appear (FlowAgent, Formal-LLM, Compile-then-Page runtime, network-procedure study).

### Gaps
- There is no head-to-head comparison of BPMN XML, state-machine YAML, Mermaid and JSON-graph *as agent execution guidance* using 2026 frontier models. FlowBench used 2024 GPT-4-class models and compared only three formats.
- Most format results come from the authors' own benchmarks. The only independent replication found is the SkillsBench granularity study, and it varies abstraction level, not structural format.

---

## 2. Extraction: converting SOP documents, manuals and runbooks into structured procedures (with accuracy)

### Takeaway
LLMs reliably extract the *elements* of a procedure (actors, actions, objects). They struggle with *logical structure* (gateways, parallelism, flow edges), and diagram-only procedures (flowchart images) are worse still. The pipelines that work generate an intermediate representation (code-like or graph), validate it with a structural or semantic checker or by executing it, repair it in a loop, and flag ambiguity for human clarification.

### Cited Findings
- PET (LREC 2022) is a gold corpus of business-process descriptions annotated with activities, gateways, actors and flows; it is the standard evaluation set for text-to-process — [PET](https://arxiv.org/abs/2203.04860)
- PAGED (ACL 2024), a procedural graph extraction benchmark: LLMs set state of the art on actor, action and constraint extraction, but "for gateway and flow predictions, all LLMs can hardly get >0.5 F1". A self-refine loop improves gateway F1 — [PAGED](https://arxiv.org/abs/2408.03630)
- Multi-agent procedural graph extraction (NEC Labs, Jan 2026) iterates three agents: a graph builder, a simulation agent that diagnoses structural defects, and a semantic agent that aligns flow logic with the source text. It improves both structural correctness and logical consistency over baselines — [Ying et al.](https://arxiv.org/abs/2601.19170)
- SOPStruct (JPMorgan AI Research, Mar 2025) turns SOPs into decision-tree representations and checks soundness deterministically with PDDL, with an LLM judging completeness — [SOPStruct](https://arxiv.org/abs/2504.00029)
- ProMoAI (van der Aalst group, Mar 2024) generates process models from text through a code-based intermediate with error handling, and exports BPMN or Petri nets — [Kourani et al.](https://arxiv.org/abs/2403.07541)
- Text-to-BPMN at scale (PARC/SRI, Apr 2026): of 750 public BPMN diagrams, 387 validated ground-truth models were built with SpiffWorkflow execution checks. Reconstruction from generated descriptions averaged above 0.75 similarity, with about 50 near-perfect results — [Matei et al.](https://arxiv.org/abs/2604.12105)
- Medical guidelines to executable BPMN (Apr 2026): 100% ground-truth match on well-structured policies and more than 92% per-patient decision agreement overall. An entropy score rises with document complexity, which flags documents that need human clarification — [Menaka Sekar et al.](https://arxiv.org/abs/2604.07817)
- InstruBPM (Dec 2025): a compact instruction-tuned open-weight model beat larger untuned and proprietary baselines on text-to-BPMN structural metrics, which matters for on-prem and privacy constraints — [InstruBPM](https://arxiv.org/abs/2512.12063)
- FLOW-BENCH/FLOW-GEN (IBM, May 2025) translates natural language into a Python-syntax intermediate representation, then into BPMN/DMN, evaluated across eight LLMs — [FLOW-BENCH](https://arxiv.org/abs/2505.11646)
- Procedural knowledge graphs (Nov 2024) extract steps, actions, objects, equipment and time into an ontology. A human study rated the output of "acceptable quality" — [Carriero et al.](https://arxiv.org/abs/2412.03589)
- Runbooks/TSGs: AutoTSG (Microsoft, May 2022) studied 4K+ TSGs mapped to thousands of incidents, plus feedback from 400+ on-call engineers. It identified TSG statements with 0.89 accuracy and parsed them for execution at precision 0.94 and recall 0.91 — [AutoTSG](https://arxiv.org/abs/2205.13457)
- StepFly (Microsoft, Oct 2025) studied 92 real TSGs and found quality problems, complex control flow and data-heavy queries. Offline, it extracts execution DAGs plus "Query Preparation Plugins"; online, a DAG-guided scheduler-executor runs them. It reports about 94% success on GPT-4.1 and 32.9–70.4% lower execution time on parallelizable TSGs. It also ships a "TSG Mentor" that helps engineers fix TSG quality first (author-reported) — [StepFly](https://arxiv.org/abs/2510.10074)
- Flowchart images: VLMs "frequently hallucinate nonexistent connections and decision paths". FlowPathAgent converts the image to a symbolic graph first and gains 10–14% on FlowExplainBench — [FlowPathAgent](https://arxiv.org/abs/2506.01344). FlowExtract (Apr 2026) uses YOLOv8 and OCR plus arrowhead tracing on ISO 5807 maintenance flowcharts and "substantially outperforms" VLM baselines on edges — [FlowExtract](https://arxiv.org/abs/2604.06770). A VLM study of industrial troubleshooting guides finds model-specific trade-offs between layout sensitivity and semantic robustness — [Gil de Avalle et al.](https://arxiv.org/abs/2601.22754)
- State machines from specifications: FlowFSM extracts FSMs from RFCs (FTP, RTSP) through prompt chaining with few hallucinated transitions — [FlowFSM](https://arxiv.org/abs/2507.11222)
- From behavior rather than documents: Task Model Induction (Aug 2026) recovers interleaved tasks from raw computer-use traces with 0.974 agreement and reconstructs 74.9% of execution steps. Skills derived from it raise held-out accuracy by 30% — [TMI](https://arxiv.org/abs/2608.20319). FixItFlow (Microsoft, 2026) generates TSGs from historical incidents with verified commands; 61.5% of 26 engineers rated them positively, and mitigation was 2.3x faster where a guide existed — [FixItFlow](https://arxiv.org/abs/2607.13035)
- Public how-to corpora: wikiHow supports goal-step and step-ordering datasets (2020), useful for pretraining or evaluating step-relation extraction — [Zhang et al.](https://arxiv.org/abs/2009.07690)

### Inferences
- A practical extraction pipeline:
  1. Parse the document, keeping its section hierarchy.
  2. Ask the LLM for a typed procedure IR (steps, conditions, gateways, preconditions, tools, escalation).
  3. Validate structurally: graph well-formedness, reachability, no dangling branches, PDDL or BPMN execution checks.
  4. Validate semantically by back-translating to text and comparing with the source.
  5. Flag ambiguity or low confidence for a human, using entropy or disagreement.
  6. Render the stored IR into Mermaid, pseudo-code and SKILL.md views.
- Gateways and parallelism are where errors concentrate (PAGED). Edge-level verification and human review should focus on branches.
- Diagram-heavy SOPs need a dedicated diagram-to-graph path (detection plus edge tracing), not a plain VLM caption.

### Gaps
- There are no numbers for end-to-end extraction from messy enterprise SOP PDFs (tables, screenshots, cross-references) to a *followable* agent procedure. Most results use clean process descriptions.
- No source measures how extraction errors propagate into downstream agent compliance.

---

## 3. Retrieval of procedures: plan/workflow retrieval, skill libraries, procedural memory, Agent Skills, tool docs, runbooks

### Takeaway
Two families have converged. (a) **Curated, human-authored procedures** are exposed as discoverable packages with short metadata and lazy-loaded bodies (Agent Skills / SKILL.md progressive disclosure, vendor "procedures", runbooks in a knowledge base). (b) **Induced procedural memory** is distilled from successful trajectories (Voyager, AWM, Memp, LEGOMem, Agent KB, plan caching). Retrieval quality depends heavily on keeping the procedure's structure: tree or graph indexing with LLM-written "problem abstractions" beats flat chunking for runbooks. Plain embeddings treat procedures as bags of words and generalize poorly to new contexts. A strong hybrid lexical-plus-dense ranker is hard to beat for skill selection.

### Cited Findings
**Skill libraries and induced workflows**
- Voyager (NVIDIA/Caltech, May 2023, TMLR 2024) keeps an ever-growing library of executable-code skills, indexed by embedded descriptions and retrieved for new tasks. It reports 3.3x more unique items and tech-tree milestones up to 15.3x faster in Minecraft — [Voyager](https://arxiv.org/abs/2305.16291)
- AWM induces reusable "workflows" from successful trajectories, each a textual description plus steps, either offline or online. It reports +24.6% and +51.1% relative success on Mind2Web and WebArena, and online AWM gains 8.9–14.0 absolute points as the train/test gap widens — [AWM](https://arxiv.org/abs/2409.07429)
- Memp (ZJU, Aug 2025) compares memory built from trajectories, scripts and both. Combining full retrieved trajectories with high-level scripts was best: GPT-4o on TravelPlanner/ALFWorld test scored 77.86 against 42.14 with no memory. Query-description keys and averaged keyword similarity ("AveFact") beat random retrieval. Memory built by a strong model transfers to weaker ones — [Memp](https://arxiv.org/abs/2508.06433)
- LEGOMem (Microsoft, Oct 2025) decomposes trajectories into memory units and gives them to the orchestrator for task decomposition and to task agents for fine-grained execution. Teams of small models narrow the gap with stronger ones on OfficeBench — [LEGOMem](https://arxiv.org/abs/2510.04851)
- Experience retrieval antecedents: ExpeL extracts insights and retrieves successful trajectories (AAAI 2024) — [ExpeL](https://arxiv.org/abs/2308.10144); Synapse uses trajectory-as-exemplar prompting with embedding retrieval, reaching 99.2% on MiniWoB++ (ICLR 2024) — [Synapse](https://arxiv.org/abs/2306.07863); AutoGuide extracts *conditional* guidelines ("in context X, do Y") — [AutoGuide](https://arxiv.org/abs/2403.08978); KnowAgent uses an action knowledge base to constrain plans — [KnowAgent](https://arxiv.org/abs/2403.03101)
- SkillWeaver (Apr 2025) turns explored website behaviors into reusable APIs: +31.8% and +39.8% relative on WebArena and real sites, and up to +54.3% when transferred to weaker agents — [SkillWeaver](https://arxiv.org/abs/2504.07079). EvoSOP (Jul 2026) packages extracted SOPs as callable higher-order tools with a construct/merge/evaluate/prune lifecycle — [EvoSOP](https://arxiv.org/abs/2607.07321)
- Agent KB (Jul 2025) is a cross-framework experience knowledge base with two-stage hybrid retrieval (planning workflows, then diagnostic fixes) and a disagreement gate. smolagents pass@3 on GAIA goes from 55.2% to 73.9%, and OpenHands SWE-bench from 24.3% to 28.3% — [Agent KB](https://arxiv.org/abs/2507.06229)
- Agentic Plan Caching (Stanford, Jun 2025) matches new requests to plan templates by keyword and adapts them with a small model. It reports 50.31% lower cost and 27.28% lower latency at maintained performance — [APC](https://arxiv.org/abs/2506.14852)
- Memory lifecycle management: ReMe adds scenario-aware indexing and utility-based pruning — [ReMe](https://arxiv.org/abs/2512.10696); MACLA compresses 2,851 trajectories into 187 procedures and tracks each one's reliability with Bayesian posteriors — [MACLA](https://arxiv.org/abs/2512.18950); the AFTER benchmark finds that one refinement round adds +3.7–6.7 points and that skills evolved from multi-model traces reach 73.1% cross-model accuracy — [AFTER](https://arxiv.org/abs/2606.23127)
- Retrieval-specific evidence: a procedural-memory retrieval benchmark (Nov 2025) finds that embedding retrieval does well on familiar contexts but hits a "generalization cliff" on new ones. Embeddings "treat procedures as unordered bags of words". LLM-generated procedural abstractions transfer reliably, and corpus scale helps more than richer representations — [Kohar & Krishnan](https://arxiv.org/abs/2511.21730)

**Agent Skills (SKILL.md) and progressive disclosure**
- Anthropic Agent Skills (Oct 16, 2025): a skill is a folder with `SKILL.md`, whose YAML frontmatter `name` and `description` are always loaded. The body loads when relevant, and linked files and scripts load or run only when needed ("progressive disclosure"). Scripts give deterministic operations without spending context (vendor source) — [Anthropic Engineering](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- Authoring rules: description of at most 1,024 characters saying what *and when*, written in third person; body under 500 lines; references one level deep; a table of contents for files over 100 lines; "degrees of freedom" matched to how fragile the task is (text for open tasks, pseudocode or parameterized scripts for preferred patterns, exact scripts for fragile sequences); copyable checklists; validate-then-execute loops; evaluations written first — [Anthropic docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
- Became an open standard (Dec 2025). Donated to the Linux Foundation's Agentic AI Foundation (Oct 2026), with Anthropic claiming 70+ integrating platforms and about 1M skills published (vendor claim) — [Anthropic news](https://www.anthropic.com/news/donating-agent-skills-to-the-agentic-ai-foundation); the spec is "deliciously tiny" and "quite heavily under-specified in places" (independent commentary) — [Simon Willison](https://simonwillison.net/2025/Dec/19/agent-skills)
- SkillsBench (Feb 2026; 87 tasks, 18 model-harness configurations): curated skills raise average pass rate from 33.9% to 50.5% (+16.6 pp; per configuration +4.1 to +25.7). One skill adds +18.0 pp, 2–3 skills +19.0 pp, and 4 or more only +10.1 pp. Compact skills add +19.0 pp against +0.7 pp for "comprehensive documentation". Skill discovery "is usually not the bottleneck". Self-generated skills (the agent writes them first with skill-creator) land *below* the no-skill baseline by 8.1 to 11.5 pp, while curated ones add 18.2 to 24.8 pp on the same configurations. Negative cases come from skills that prescribe "a single 'correct' pipeline without applicability boundaries or lightweight fallbacks" (independent of Anthropic) — [SkillsBench](https://arxiv.org/abs/2602.12670)
- SWE-Skills-Bench (Mar 2026; 98 public SWE skills, 3,920 paired runs): 92 of 98 skills had no significant effect, and the average pass ratio moved from 76.6% to 76.9%. Helpful skills supply steps the agent would otherwise omit (up to +17.7 points). Harmful ones "anchor the agent on their own templates and override the task's explicit instructions" (down to −17.0) — [SWE-Skills-Bench](https://arxiv.org/abs/2603.15401)
- Skill-induced failures (Aug 2026): 307 failures on SkillsBench and SWE-Skills-Bench. The largest source of efficiency regressions is "Excessive Procedure", where skills turn validation checklists into mandatory work. Functional failures come from *seemingly relevant* skills, not irrelevant ones — [Dong et al.](https://arxiv.org/abs/2608.11888)
- Shortening skills (Jul 2026, 40 SkillsBench tasks): cost did not drop, because the skill is a small and mostly cached part of the context. LLM rewriting lowered small-model success from 42.5% to 29.2–37.5%; extractive shortening kept success. The advice is to use curated skills as written — [Xu & Wu](https://arxiv.org/abs/2607.03048)
- Progressive disclosure in production (Workday, Sep 2026): lazy-loading skills *improves skill-retrieval quality* with a marginal latency cost — [Workday report](https://arxiv.org/abs/2609.35692)
- Skill retrieval at scale (Aug 2026; 690 skills, 117 realistic queries): a hybrid lexical-plus-dense ranker finds the right skill in the top 5 for 73.5% ± 8.0 of queries. A typed workflow knowledge graph (prerequisites, data flow, ordering) did *worse* at matched token budget (−11.2 points), and 98.6% of its edges joined skills the ranker had already surfaced together. Author-written queries overstate hit@5 by up to 44 points — [Kolluru & Sportsman](https://arxiv.org/abs/2608.06196). SPEM (Oct 2026) instead reports gains from reusable Skill-DAG templates of composed skills built from successful runs (87.1% ALFWorld) — [SPEM](https://arxiv.org/abs/2610.26995)
- Production compiled skills: Zep Agent Skills (Nov 2026) compiles *verified* traces into versioned Skills that cite their supporting events. Admission is gated, rank is adjusted by verified use outcomes, and retrieval is lexical with progressive disclosure over API or MCP. Skills compiled from a teacher's traces raise weaker executors by 4.5–18.8 points on τ³-bench banking, AppWorld and EnterpriseOps-Gym (vendor-authored paper) — [Zep](https://arxiv.org/abs/2611.01386)
- Quality and security: more than 99% of 238 real SKILL.md files contain at least one "skill smell" — [Hong et al.](https://arxiv.org/abs/2607.01456); skills enable "trivially simple" prompt injections hidden in long skill files and scripts — [Schmotz et al.](https://arxiv.org/abs/2510.26328); a survey reports 26.1% of community skills contain vulnerabilities — [Xu & Yan survey](https://arxiv.org/abs/2602.12430); models "vary widely in how closely they adhere to the instructions encoded in skills" across 500 skills and 19 configurations — [Shaposhnikov et al.](https://arxiv.org/abs/2606.17819)

**SOP, runbook and tool-documentation retrieval**
- SOPRAG (NTU, Feb 2026) replaces flat chunking with Entity, Causal and Flow graph "experts", a "Procedure Card" layer that prunes candidates, and LLM gating aligned to operator intent. It beats lexical, dense and graph RAG on four industrial domains (author-reported) — [SOPRAG](https://arxiv.org/abs/2602.01858)
- TSG Suggester (Microsoft, 2026; 314 incidents, 112 TSGs, 18 teams): turning each guide into a tree that keeps its section hierarchy, attaching LLM-written *problem abstractions* to internal nodes (to bridge solution-language guides and problem-language incidents), and fusing embeddings with per-guide entity KG matching gives 54.78% top-1 and 82.48% top-5. That is +8.58 top-1 over text RAG. Captioning screenshots *hurt*, by −22.64 top-5 points. "Structural alignment dominates" — [TSG Suggester](https://arxiv.org/abs/2609.35780)
- Nissist (Microsoft, Feb 2024) builds a knowledge base from TSGs and mitigation discussions and reports reduced time-to-mitigate — [Nissist](https://arxiv.org/abs/2402.17531). Flow-of-Action (Feb 2025) adds SOP retrieval, SOP generation when none exists, and SOP-to-code conversion for root-cause analysis: 64.01% accuracy against 35.50% for ReAct — [Flow-of-Action](https://arxiv.org/abs/2502.08224). AIOpsLab is an evaluation harness for incident-lifecycle agents — [AIOpsLab](https://arxiv.org/abs/2501.06706)
- Process-aware retrieval of APIs (Oct 2026): a typed property graph joins BPMN reference processes with OData schemas, and retrieval follows process edges to the next endpoints. Agent task completion is 38.7% against 10.3% for chunk-based retrieval, and full typed context cuts invalid calls to 3% — [Khan & Farea](https://arxiv.org/abs/2610.37242)
- Tool documentation alone enables zero-shot tool use on par with or better than demonstrations — [Hsieh et al.](https://arxiv.org/abs/2308.00675)
- τ-Knowledge / τ³ Banking (Sierra/Princeton, Mar 2026): about 700 interlinked documents (about 195K tokens); tasks average 18.6 documents and 9.5 tool calls. Frontier agents reached about 25.5% pass^1 at launch, and giving them the right documents raised the ceiling only to about 40% — [τ-Knowledge](https://arxiv.org/abs/2603.04370). By May 2026 the best was 37.4% pass^1 / 20.6% pass^4 (GPT-5.5 xhigh). Failure modes: retrieving once at the start instead of again when the context changes, scattershot queries, and unrequested extra actions (benchmark author is a vendor) — [Sierra blog](https://sierra.ai/blog/tau-knowledge)
- Organizational memory (SAP-affiliated, Jul 2026) argues for a shared, governed procedural-knowledge layer instead of per-agent prompts or retrieval, which create "knowledge silos and rule duplicates" — [Kirchdorfer et al.](https://arxiv.org/abs/2607.03228)

### Inferences
- For a data lake: index each procedure as one **unit**, not as arbitrary chunks. Give it a short "when to use" description, LLM-generated problem or symptom abstractions (FAQ-style questions it answers), entities (systems, products, error codes), and a structure tree. Retrieve with hybrid BM25 plus dense search over these fields, then load the body progressively.
- Adding a graph layer is justified for *execution* (next step, preconditions, process order between APIs). There is little evidence it extends *retrieval reach* beyond a strong hybrid ranker (690-skill study). SOPRAG and TSG Suggester show gains when structure is aligned with the document's own hierarchy and with entities.
- Curated or verified procedures beat model-authored ones (SkillsBench self-generated result). Induced memory should therefore pass through verification and admission gates (Zep, MACLA, ReMe) before entering the shared KB.
- Keep skill bodies compact and scoped, with applicability boundaries and fallbacks. Over-prescriptive or exhaustive procedures measurably hurt.

### Gaps
- No public benchmark directly compares SKILL.md-style progressive disclosure, RAG over procedure chunks and full-context loading on the same enterprise SOP corpus with compliance metrics. The Workday report is short and its corpus is proprietary.
- There is little evidence on retrieval when many near-duplicate SOP versions coexist (regional, product or date variants).

---

## 4. Adherence and compliance: benchmarks, failure modes, guardrails, verification, human-in-the-loop

### Takeaway
SOP and policy adherence is far from solved, even in 2026. Benchmarks show 25–90% pass^1 depending on domain, with sharp drops in reliability across repeated trials (pass^k). Recurring failure modes:
- route blindness (wrong branch or next action)
- skipped or omitted steps, and extra unrequested actions
- hallucinated steps or arguments
- single-shot retrieval
- policy loopholes caused by ambiguous policy text
- jailbreaks that make the agent ignore the SOP

Reliable compliance comes from moving checks *outside* the LLM: precondition controllers, solver- or DSL-based pre-call verification, state machines, and simulation test suites compiled from the SOP. Human checkpoints are kept for sensitive actions.

### Cited Findings
**Benchmarks**
- τ-bench (Sierra, Jun 2024): even GPT-4o succeeded on under 50% of tasks, with pass^8 under 25% in retail. 25% of failures were "wrong decision-making", meaning the agent failed to understand domain rules and made the wrong type of tool call. About 55% were wrong arguments or info, and 19% were partial resolution of compound requests (2024 models) — [τ-bench](https://arxiv.org/abs/2406.12045)
- τ²-bench (Jun 2025) adds dual control: in Telecom the user must also act. Performance drops sharply from no-user to dual-control — [τ²-bench](https://arxiv.org/abs/2506.07982). Late-2026 aggregator figures put the top τ²-bench overall pass^1 at about 85–88% (Qwen3.5-397B-A17B 87.9%, Claude Opus 4.5 85.3%), with harness settings that are not comparable across entries (aggregator, unverified) — [tau2-bench repo](https://github.com/sierra-research/tau2-bench)
- Policy ambiguity: auditing two τ²-bench domains found "policy loopholes" (silence, ambiguity, contradiction) that make scores unreliable and every model less consistent. "Policy specification quality sets the ceiling on evaluation quality" — [Cao](https://arxiv.org/abs/2609.14400)
- SOPBench (Mar 2025): 167 tools, 7 customer-service domains and 900+ tests. Each SOP is a code program turned into a directed graph of functions, and the code serves as the oracle verifier. Top non-reasoning models score 30–50% pass rates on some domains, and agents "can be easily jailbroken to overlook SOPs" — [SOPBench](https://arxiv.org/abs/2503.08669)
- SOP-Bench (Amazon, Jun 2025): 2,000+ tasks from expert-authored SOPs in 12 domains. Best results range from 57% to 100% by domain, and newer models are not always better (Claude 4 Opus 72.4% vs Claude 4.5 Sonnet 63.3% on ReAct) — [SOP-Bench](https://arxiv.org/abs/2506.08119)
- SOP-Maze (Meituan, Oct 2025): 397 instances from 23 real business SOPs. Error classes are route blindness, conversational fragility and calculation errors — [SOP-Maze](https://arxiv.org/abs/2510.08942)
- TOD-ProcBench (Amazon, Nov 2025) models instructions as multi-level condition-action statements from ABCD. Its tasks are retrieving the right statement and predicting the next action, detecting instruction-violating responses, and compliant generation; it also studies format and multilingual effects — [TOD-ProcBench](https://arxiv.org/abs/2511.15976)
- SAGE (Apr 2026) formalizes SOPs into dynamic dialogue graphs for verification. It finds an "Execution Gap" (intent classified correctly, wrong next action) and "Empathy Resilience" (polite facade over logical failure) across 27 LLMs — [SAGE](https://arxiv.org/abs/2604.09285)
- Hallucinated steps: low-rank-compressed models that pass perplexity, MMLU and fidelity checks still "invent procedure steps that were never in the instructions" when running an SOP. A canary test is needed before agentic deployment — [Kennedy & Kennedy](https://arxiv.org/abs/2607.28196)

**Guardrails and verification**
- FlowAgent controllers enforce preconditions over PDL nodes — [FlowAgent](https://arxiv.org/abs/2502.14345). Formal-LLM's automaton guarantees valid plans — [Formal-LLM](https://arxiv.org/abs/2402.00798)
- Solver-aided compliance (Mar 2026): natural-language tool-use policies are translated into SMT-LIB constraints by an LLM with human guidance. Z3 checks each planned tool call before it runs and blocks violations, which reduces violations on τ-bench at maintained accuracy — [Winston et al.](https://arxiv.org/abs/2603.20449)
- AgentSpec (SMU, Mar 2025) is a DSL of trigger, predicate and enforcement rules. It prevents unsafe execution in more than 90% of code-agent cases. o1-generated rules reached 95.56% precision and 70.96% recall for embodied agents — [AgentSpec](https://arxiv.org/abs/2503.18666)
- VIGIL (Jun 2026) turns skill-specification policies (temporal order, argument constraints, value flow) into SMT checks over traces, with more than 95% recall and under 10% false positives — [VIGIL](https://arxiv.org/abs/2606.26524). Agent Behavioral Contracts specify preconditions, invariants, governance and recovery, reaching 88–100% hard-constraint compliance with under 10 ms overhead (single author) — [ABC](https://arxiv.org/abs/2602.22302). GuardAgent turns guard requests into executable checking code, with 98% and 83% guardrail accuracy — [GuardAgent](https://arxiv.org/abs/2406.09187)
- NeMo Guardrails (NVIDIA, 2023) uses Colang dialogue rails to enforce predefined dialogue paths independently of the LLM — [NeMo Guardrails](https://arxiv.org/abs/2310.10501). Rasa CALM keeps business logic in predefined "flows": the LLM only emits commands (start, stop or resume a flow) and does not invent steps (vendor docs) — [Rasa CALM](https://rasa.com/docs/learn/concepts/calm/)
- Role-scoped skill discovery as access control: when tools reach the agent only through learned skills served by one MCP server, no unauthorized tool call or parameter violation executed in its evaluation — [skilder](https://arxiv.org/abs/2609.28693)
- Production loop: CARE (Nov 2026) versions Skills and SOPs, judges each failure against the policy in force at the time, and promotes models only after passing simulation tests compiled from the latest SOP plus human approval — [CARE](https://arxiv.org/abs/2611.02839)
- Ops practice: for AKS incident response, "permission level and run mode, not prompt quality" are the key controls, and custom instructions "do not replace RBAC" (vendor blog) — [Microsoft Tech Community](https://techcommunity.microsoft.com/t5/apps-on-azure-blog/autonomous-aks-incident-response-with-azure-sre-agent-from-alert/ba-p/4511343)

### Inferences
- Treat each stored procedure as both **guidance** (rendered for the LLM) and a **specification** (machine-checkable preconditions, allowed transitions and tool constraints). The spec drives runtime checks and auto-generated simulation tests, following the SOPBench and CARE pattern.
- Report pass^k, not just pass@1, and audit procedure text for ambiguity before using it as ground truth.
- Mark steps by risk class (read-only, reversible write, irreversible or financial) and require human approval or a deterministic check on the risky ones. The vendor platforms do this (section 5).

### Gaps
- No independent study measures real-world (production) SOP-adherence rates of deployed customer-support agents; all such numbers are vendor-reported.
- Little quantitative evidence on human-in-the-loop checkpoint placement (cost vs. error reduction).

---

## 5. Industry practice: SOP-based customer-support agents and IT-ops runbooks (vendor claims flagged)

### Takeaway
Every major customer-experience vendor has landed on the same pattern: **natural-language procedures written by operations staff, plus deterministic hooks** (code conditions, validated actions, transitions) **plus simulation testing and versioning**. Their names differ: Decagon AOPs, Intercom Fin Procedures, Sierra journeys/Agent SDK, Salesforce Agent Script, Rasa CALM flows. IT ops is converging on runbooks as Markdown in an agent knowledge base, permission-scoped execution, and runbooks generated or updated from incident history. Effectiveness numbers are almost entirely vendor claims.

### Cited Findings
- **Decagon AOPs (Agent Operating Procedures):** "natural language instructions that compile into validated workflows for AI agents." CX teams write logic in plain language; engineers maintain integrations and code-level guardrails for sensitive actions (refunds, identity verification). Every change is versioned with rollback and validated through simulations, unit tests and scheduled regression tests. The migration recipe is to audit SOPs, pick high-volume rule-based procedures, and translate each into triggers, actions, data points, decision branches, success criteria and escalation conditions. Vendor claims: 3–6 week implementation and "70–80% deflection rates" (Nov 2025) — [Decagon](https://decagon.ai/resources/from-sops-to-agent-operating-procedures). An independent but competing review says connecting AOPs to backends needs developers and that decision opacity is a recurring complaint — [eesel review](https://eesel.ai/blog/decagon-ai-review)
- **Intercom Fin Procedures** (2025–2026):
  - A trigger ("When to use this procedure", with inclusion and exclusion criteria and positive and negative training examples).
  - Step types: Instruction (NL), Condition (IF/ELSE, *either* code *or* NL, not mixed, no nesting), Run sub-procedure, Handoff to workflow, team or ticket, End, and Wait for Webhook.
  - Tools via @ (data connectors, attribute read/write, knowledge-base lookup), plus procedure-scoped guidance.
  - "Agentic Switch" lets Fin move to another procedure when intent changes.
  - Background simulations with mocked connectors and pass/fail criteria.
  - Intercom says NL instructions "guide behavior rather than guaranteeing it", with conditions and tools as the deterministic controls (vendor docs) — [Intercom](https://www.intercom.com/help/en/articles/13449439-building-fin-procedures)
- **Sierra Agent SDK / Agent OS:** customer journeys "as code", reusable composable skills (triage, respond, confirm), a tunable "degree of flexibility" per workflow, and simulations to catch regressions. There are no published technical or quantitative details (vendor page) — [Sierra](https://sierra.ai/product/agent-sdk). Sierra also authors the τ-bench family — [τ-bench](https://arxiv.org/abs/2406.12045)
- **Salesforce Agentforce:** topics (now "subagents") define scope, instructions guide behavior, and actions are tools. The Atlas reasoning engine classifies each turn to a topic. Agent Script is a declarative, compiled DSL producing an "Agent Graph" for "hybrid reasoning", mixing deterministic logic (conditionals, transitions) with LLM reasoning, and it can be versioned and reviewed like code (vendor sources) — [Agentforce Guide](https://www.salesforce.com/agentforce/guide); [Salesforce Developers](https://developer.salesforce.com/blogs/2025/10/introducing-hybrid-reasoning-with-agent-script)
- **Rasa CALM:** the LLM performs dialogue understanding and emits commands; predefined flows hold the business logic; responses are templated by default (vendor docs) — [Rasa](https://rasa.com/docs/learn/concepts/calm/)
- **IT ops:** Azure SRE Agent ingests existing runbooks "as .md files to the agent's knowledge base", runs CLI/REST actions through runbooks, subagents and hooks, and keeps a knowledge store of root causes and resolution steps (vendor) — [Microsoft Learn](https://learn.microsoft.com/en-us/azure/sre-agent/overview); [Tech Community](https://techcommunity.microsoft.com/blog/appsonazureblog/-/4479811). PagerDuty's SRE Agent analyzes runbooks, runs *approved* automations and generates "self-updating runbooks" with human oversight (vendor) — [PagerDuty](https://pagerduty.com/platform/ai-agents/sre). Microsoft Research's StepFly, AutoTSG, Nissist and TSG Suggester (section 3) are the research counterparts, and they report real TSG corpora.

### Inferences
- The shared industry abstraction maps cleanly onto a portable schema:
  - `procedure` = {trigger/when_to_use, inclusion and exclusion examples, steps[] (type ∈ instruction | condition | tool_call | subprocedure | handoff | wait | end), guidance, guardrails, escalation, tests[], version}.
  - An open toolkit could emit this schema and render it to SKILL.md, Mermaid, PDL-like pseudo-code, or vendor import formats.
- Vendors all pair procedures with simulation tests and versioning. An open toolkit should generate test scenarios from each extracted procedure (happy path plus each branch plus out-of-workflow turns).

### Gaps
- No independent, published head-to-head of vendor procedure systems; vendor deflection and resolution rates have no disclosed methodology.
- Agentforce and Sierra internals (exact DSL semantics) are not publicly documented in detail; the Salesforce developer blog returned 403 to direct fetch and was seen only via search snippets.

---

## 6. Most effective way to store, index and expose procedures to agents (recommended design)

### Takeaway
Store each procedure **once, as a canonical typed procedure IR** (graph of steps with NL text, conditions, preconditions, tool bindings, risk levels, provenance), and **render** it into agent-facing views. **Index** it as a unit with metadata, symptom/problem abstractions, entities and a structure tree, using hybrid lexical-plus-dense retrieval. **Expose** it by progressive disclosure: a catalog of short descriptions, then the body on demand, then references and scripts. **Execute** high-risk procedures under a runtime that tracks the active step and checks preconditions and tool constraints deterministically.

### Cited Findings (evidence behind each design decision)
- Canonical structured form plus multiple renderings. Flowcharts, compiled pseudo-code and NL each win in some settings, and an ensemble of formats was best in FlowBench (45.3 vs ≤41.5 success) — [FlowBench](https://arxiv.org/abs/2406.14884); compiled text never significantly hurts — [Compile, Then Page](https://arxiv.org/abs/2607.11346); typed contract plus concrete action template beats prose, though the contract alone does not — [SaP](https://arxiv.org/abs/2605.27955)
- Extraction with verification loops, because LLMs miss gateways and flows — [PAGED](https://arxiv.org/abs/2408.03630); simulation and semantic feedback agents help — [Ying et al.](https://arxiv.org/abs/2601.19170); execution checks and entropy-based ambiguity flags — [Matei et al.](https://arxiv.org/abs/2604.12105), [Menaka Sekar et al.](https://arxiv.org/abs/2604.07817); TSGs to DAGs offline — [StepFly](https://arxiv.org/abs/2510.10074)
- Structure-preserving indexing with problem abstractions: tree plus KG plus problem-abstraction nodes beat flat RAG, and multimodal captions hurt — [TSG Suggester](https://arxiv.org/abs/2609.35780); Procedure Card plus flow/causal/entity experts — [SOPRAG](https://arxiv.org/abs/2602.01858); LLM-generated procedural abstractions transfer better than raw embeddings — [Kohar & Krishnan](https://arxiv.org/abs/2511.21730)
- Hybrid ranker as the default selector, with the graph used for execution rather than recall — [Kolluru & Sportsman](https://arxiv.org/abs/2608.06196); process edges help select *next* APIs — [Khan & Farea](https://arxiv.org/abs/2610.37242)
- Progressive disclosure: metadata always loaded, body and resources on demand — [Anthropic](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills); improves skill retrieval in production — [Workday](https://arxiv.org/abs/2609.35692); a 1,024-char description and 500-line body cap — [Anthropic docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
- Compact, scoped procedures with applicability boundaries: 2–3 focused skills and compact length are best, exhaustive docs add about 0 — [SkillsBench](https://arxiv.org/abs/2602.12670); harmful skills override the task — [SWE-Skills-Bench](https://arxiv.org/abs/2603.15401); "Excessive Procedure" regressions — [Dong et al.](https://arxiv.org/abs/2608.11888); do not LLM-rewrite curated text — [Xu & Wu](https://arxiv.org/abs/2607.03048)
- Curated or verified over model-authored: self-generated skills fall below baseline — [SkillsBench](https://arxiv.org/abs/2602.12670); compile only from verified traces with admission gates — [Zep](https://arxiv.org/abs/2611.01386); Bayesian reliability and pruning — [MACLA](https://arxiv.org/abs/2512.18950), [ReMe](https://arxiv.org/abs/2512.10696)
- Runtime execution state and enforcement: explicit execution state over appended history — [SKILL.state](https://arxiv.org/abs/2608.26263); procedure-as-tool cuts errors and latency — [Garigipati et al.](https://arxiv.org/abs/2605.02584); pre-call solver checks — [Winston et al.](https://arxiv.org/abs/2603.20449); runtime policy enforcement from skill specs — [VIGIL](https://arxiv.org/abs/2606.26524); a runtime only for models that pass a discipline check — [Compile, Then Page](https://arxiv.org/abs/2607.11346)
- Agents must re-retrieve as the conversation evolves; one-shot retrieval at the start is a top failure — [Sierra τ-knowledge](https://sierra.ai/blog/tau-knowledge)
- Governance and security: shared organizational procedural memory rather than per-agent silos — [Kirchdorfer et al.](https://arxiv.org/abs/2607.03228); skill files are a prompt-injection vector — [Schmotz et al.](https://arxiv.org/abs/2510.26328); skill smells are ubiquitous — [Hong et al.](https://arxiv.org/abs/2607.01456)

### Inferences (recommended design for the toolkit)
1. **Canonical record** (one per procedure version), e.g. JSON/YAML:
   - `id, title, version, effective_dates, owner, source_doc + span offsets (provenance)`
   - `when_to_use` (≤1,024 chars), `not_for` (exclusions), `trigger_examples[]` / `negative_examples[]`
   - `inputs/required_data`, `preconditions`, `steps[]`. Each step has `{id, type, text, tool?, args_schema?, condition?, next[], risk_level, requires_approval?}`
   - `escalation`, `success_criteria`, `related_policies[]` (links into the policy track), `entities[]`, `symptoms/problem_abstractions[]`
   - `tests[]` (auto-generated branch-coverage scenarios), `verification_status`, `extraction_confidence/ambiguity_flags`
2. **Renderers:**
   - SKILL.md (agentskills.io-compatible: frontmatter description = `when_to_use`; body = compact steps/checklist; references = long details; scripts = deterministic sub-steps)
   - Mermaid flowchart
   - PDL/pseudo-code
   - optional BPMN export for process-mining and BPM tools
   - the original prose for weak models and for audit
3. **Index:**
   - Hybrid BM25 plus dense search over `title + when_to_use + problem_abstractions + entities + step headings`. Each procedure is one retrievable unit; steps are sub-documents for "what's the next step" lookups.
   - A tree index keeping the document's section hierarchy.
   - Optional graph edges (subprocedure-of, precedes, supersedes, applies-to-product) used for navigation, deduplication and versioning, not as the primary recall mechanism.
4. **Expose:**
   - A catalog tool (search procedures, returning id plus description), `get_procedure(id, view=skill|mermaid|pseudo)`, `get_step(id, step_id)`, and the procedure's tool bindings. These can ship as MCP tools and/or an Agent Skills folder export.
   - Agents should be instructed to re-search when context changes.
5. **Execute (optional):**
   - A lightweight runtime that keeps the active step and state, checks preconditions and transition legality before tool calls, and requires approval on high-risk steps.
   - Enable it per model after a discipline test, because it hurts weak models.
6. **Lifecycle:** versioning with effective dates; mining new or updated procedures from verified agent traces and incident history, routed through human review; per-procedure paired evaluation (with vs without) to detect harmful or ineffective procedures, as in SWE-Skills-Bench.

### Gaps
- The recommended design is a synthesis: no single study evaluates this end-to-end architecture against simpler baselines (e.g., plain RAG over SOP chunks) on the same corpus.
- Cost data is sparse. Only Agentic Plan Caching (−50% cost) and skill-shortening (no cost change) report cost explicitly, and no source reports extraction-pipeline cost per document.
