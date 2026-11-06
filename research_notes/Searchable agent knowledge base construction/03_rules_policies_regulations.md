# Rules, policies, regulations and compliance knowledge as an agent-searchable, enforceable knowledge base

Scope: declarative rules (business rules, policies, regulations, statutes, contracts-as-rules, guidelines). Procedural SOPs and workflows belong to another track and are only mentioned where a source spans both. Current as of November 2026. Dates are given as arXiv first-submission dates unless stated otherwise. **[V]** marks results reported by a vendor or by the system's own authors in a product setting. **[I]** marks independent or third-party evaluation. Most academic numbers are author-reported on the authors' own benchmark, and this is noted where it matters.

---

## 1. Extraction: turning documents into rules (business rules, legal provisions, deontic norms, policy-to-code)

### Takeaway
LLM pipelines can now pull structured rule units (subject, condition, deontic modality, exception, cross-reference, source span) out of regulations with good fidelity. The reliable ones share four features: they segment along the document's structure, decompose into atomic rules, validate with a judge or verifier, and repair in a loop. Translating text into *executable* rules (Rego, Cedar, DMN, Prolog/ASP, SMT, Lean) is much less reliable. Single-shot correctness runs about 15-55% without verifiers, and pipelines reach about 80-100% only when they combine (a) a reviewed intermediate spec, (b) schema validation, (c) compilation and tests, and (d) solver feedback. The main failure modes are silent omissions and under-constrained rules, not syntax errors.

### Cited Findings

**Structured rule-unit extraction (natural-language rule cards with metadata)**
- De Jure (2026) is a fully automated, domain-agnostic pipeline. It normalises documents to structured Markdown, has an LLM decompose them into "structured rule units", scores each unit with an LLM judge on 19 dimensions (metadata, definitions, rule semantics), and repairs low scorers within a bounded budget. It needs no human annotation. Quality peaks within 3 judge-guided iterations on finance and generalises to healthcare and AI governance. In downstream compliance RAG, answers grounded in De Jure rules were preferred over prior work in 73.8% of cases at single-rule retrieval depth and 84.0% with broader retrieval. These are LLM-judge preferences reported by the authors — [De Jure, arXiv 2604.02276](https://arxiv.org/abs/2604.02276)
- RegReAct (EMNLP 2026 Findings) splits regulatory extraction into 7 agents, each with an Observe-Diagnose-Repair loop. The authors report that single-pass LLMs "hallucinate structural elements, lose hierarchical relationships, and fail to resolve inter-document dependencies". RegReAct builds a typed criterion graph and inlines summaries of referenced external legal content so each output stands alone. Applied to 3 EU Taxonomy Delegated Acts, it produced 242 activities with more than 4,800 hierarchical criteria and thresholds, and beat a GPT-4o single pass on every structural and semantic metric — [RegReAct, arXiv 2604.12054](https://arxiv.org/abs/2604.12054)
- ComplianceNLP (ACL 2026 Industry) does multi-task obligation extraction (NER + deontic classification + cross-reference resolution) on a shared LEGAL-BERT encoder, over a KG of 12,847 provisions from SEC, MiFID II and Basel III. It reports 87.7 F1 on gap detection (+3.5 over GPT-4o+RAG). KG re-ranking gave the largest ablation gain (+4.6 F1). In a 4-month parallel run at a financial institution it processed 9,847 updates at an estimated 96.0% recall and 90.7% precision [V] — [ComplianceNLP, arXiv 2604.23585](https://arxiv.org/abs/2604.23585)
- Compliance-to-Code (2025) has 1,159 clauses from 361 Chinese financial regulations. Each clause is annotated with four logical elements (subject, condition, constraint, contextual information) plus relations between regulations, and each has a deterministic Python mapping. FinCheck is its regulation-structuring → code → report pipeline — [Compliance-to-Code, arXiv 2505.19804](https://arxiv.org/abs/2505.19804)
- CODE-ACCORD (Scientific Data, 2024) has 862 self-contained building-regulation sentences from England and Finland. They carry 4,297 entities and 4,329 relations annotated by 12 annotators, as ground truth for converting rules into machine-readable form for automatic compliance checking — [CODE-ACCORD, arXiv 2403.02231](https://arxiv.org/abs/2403.02231)
- PolicyLR (2024) compiles privacy policies into valuations of atomic formulae using a two-stage translate-then-entail LLM procedure, grounded in policy segments. Compliance and consistency are then defined formally. It was evaluated on ToS;DR — [PolicyLR, arXiv 2408.14830](https://arxiv.org/abs/2408.14830)
- ARCCS (EMNLP 2026 Demo, open source) decomposes regulations into "atomic, traceable requirements" and checks a target document against each one, with retrieved evidence, a confidence score and a justification. It reports 98.8% accuracy on more than 1,200 rule checks on an EU public-procurement benchmark, and up to 96.67% legal and evidential consistency on GDPR per LLM judges (author-reported) — [ARCCS, arXiv 2610.01345](https://arxiv.org/abs/2610.01345)

**Deontic and logic formalisation**
- Horner, Governatori, Ciabattoni et al. (2025) translate legal text to Defeasible Deontic Logic in stages: segment into atomic snippets → extract deontic rules → check syntactic and semantic coherence → refinement step. On the Australian Telecommunications Consumer Protections Code, LLM output "aligns closely with expert-crafted representations" when guided well — [Horner et al., arXiv 2506.08899](https://arxiv.org/abs/2506.08899)
- DeonticBench (2026) has 6,232 tasks covering US federal tax (SARA), airline baggage, US immigration and state housing law, with reference Prolog programs for every instance. Best frontier hard-subset scores were 44.4% on SARA Numeric and 46.6 macro-F1 on Housing. SFT/RL improves Prolog generation, but "current RL methods still fail to solve these tasks reliably" — [DeonticBench, arXiv 2604.04443](https://arxiv.org/abs/2604.04443)
- Jurayj, Holzenberger and Van Durme (AAAI 2026) combine an LLM with a symbolic solver for tax obligations on SARA. Translating plain-text rules into logic programs *up front* and retrieving exemplars of formal case representations "dramatically" improves performance. Estimated deployment cost, including penalties for errors, falls below real-world averages — [Jurayj et al., arXiv 2508.21051](https://arxiv.org/abs/2508.21051)
- An LLM + SMT framework for Taiwan FSC enforcement cases reached 86.2% correct SMT code generation on 87 cases. The solver also computes the minimal factual change that restores legality (author-reported, ACM AIware 2026) — [Hsia et al., arXiv 2601.06181](https://arxiv.org/abs/2601.06181)
- AWS ARc (2025): the LLM formalises natural-language policies, with optional human guidance. At inference it autoformalises statements several times redundantly and checks the formalisations for semantic equivalence. Reported ">99% soundness" and "near-zero false positive rate" on AWS benchmarks [V] — [Bayless, Cook et al., arXiv 2511.09008](https://arxiv.org/abs/2511.09008)

**Policy-to-code (Rego/OPA, Cedar, ODRL, DMN)**
- Prose2Policy (2026) runs NL access policy → Rego with policy detection, component extraction, schema validation, linting, compilation, and automatic test generation and execution. On ACRE it reaches a 95.3% compile rate, 82.2% positive-test pass and 98.9% negative-test pass — [Prose2Policy, arXiv 2603.15799](https://arxiv.org/abs/2603.15799)
- The same authors later applied a strict end-to-end criterion (compiles + lints + passes positive and negative tests) to 372 ACRE statements. Correctness was 50.3% with structured decomposition versus 15.3% for a single prompt. Deny semantics were correct 87.5% of the time (baseline 37.5%) — [Gupta & Sreenivasamurthy, arXiv 2609.24036](https://arxiv.org/abs/2609.24036). *Note: these two papers report very different headline numbers (95% compile vs 50% end-to-end correct), which shows how much the choice of metric changes the picture.*
- RegoMender (ASE 2026) introduces RegoBench, 1,159 real Rego defects. Its multi-agent repair reaches 82.9% syntactic and 77.9% test-based semantic success, and repairs 86.4% of 132 real CVEs — [RegoMender, arXiv 2610.29456](https://arxiv.org/abs/2610.29456)
- ARPaCCino (2025) is agentic RAG + tool validation that generates Rego for Terraform IaC compliance and works with small open-weight LLMs — [ARPaCCino, arXiv 2507.10584](https://arxiv.org/abs/2507.10584)
- AutoCedar (2026) first turns requirements into reviewed "intent atoms" (claims about vocabulary and behaviour). The verifier then checks candidate Cedar against that approved target, and failures become repair signals (broaden/narrow/restructure). It converges on all 221 CedarBench tasks. The authors warn that "a generated policy can compile and read correctly while granting access that no one approved" — [AutoCedar, arXiv 2607.03656](https://arxiv.org/abs/2607.03656)
- RAISE / CedarInstruct (2026) has 5,800 verified scenarios across 44 domains. Verified SFT followed by RL on verifier counterexamples lets a 9B LoRA model beat zero-shot frontier models by about 13-16 points on verifiable Cedar synthesis (author-reported) — [RAISE, arXiv 2609.33796](https://arxiv.org/abs/2609.33796)
- Autoformalization of agent prompts, MCP tool descriptions and NL policy docs into Cedar via a generator-critic loop covered "substantially more" of the NL spec on MedAgentBench than hand-coded symbolic enforcement (ICML 2026 AIWILD workshop) — [Mondl et al., arXiv 2606.26649](https://arxiv.org/abs/2606.26649)
- AgentODRL (AAAI 2026) is an orchestrator-worker multi-agent system (generator, decomposer, rewriter) for NL → ODRL, with a validator-based syntax strategy and LoRA semantic reflection. It uses 770 data-space use cases — [AgentODRL, arXiv 2512.00602](https://arxiv.org/abs/2512.00602)
- BPMN → ODRL by deterministic graph traversal ("compliance-by-extraction"). It notes that LLM generation of ODRL "introduces well-documented risks of structural invalidity" — [Manab et al., arXiv 2608.02607](https://arxiv.org/abs/2608.02607)
- Legal text → executable decision models (ICAIL 2026) used 95 production decision models from the Dutch Omgevingsloket permit platform. Generated models matched gold outcomes on only 51-53% of test scenarios. Supplying I/O constraints gave +37-54% structural similarity. "Structural similarity does not guarantee outcome equivalence, and vice versa" [I-ish: real production gold] — [Graus, arXiv 2604.17153](https://arxiv.org/abs/2604.17153)
- DMN-guided prompting: decision logic is put in a DMN model rather than in the prompt, so end users can edit it. It beat CoT in a course-feedback case study — [Abedi & Jalali, arXiv 2505.11701](https://arxiv.org/abs/2505.11701)
- AWS Bedrock Automated Reasoning checks (GA 6 Aug 2025): upload a source document and it extracts rules, variables and custom types, plus a *fidelity report* with coverage and accuracy scores that grounds each rule in source statements. SMT-LIB is viewable. Limits are 122,880 tokens per build (about 100 pages) and 50,000 characters per document in the docs. Complex nested or contradictory documents "may not extract cleanly". Results include VALID, INVALID, SATISFIABLE, TRANSLATION_AMBIGUOUS and TOO_COMPLEX. It runs in detect mode only, English only, and has no streaming [V] — [AWS docs](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html); [AWS News Blog](https://aws.amazon.com/blogs/aws/minimize-ai-hallucinations-and-deliver-up-to-99-verification-accuracy-with-automated-reasoning-checks-now-available/)
- When AWS AR policy generation was used independently on τ²-bench airline policies, it produced about 600 lines of SMT-LIB with about 95% coverage per an LLM judge, but "some rules were underconstrained". Fully automatic generation was syntactically unreliable, and the authors needed custom prompting plus manual fixes (undefined variables, timestamp conversion, implicit negation such as "cancellation allowed within 24h" without forbidding cancellation outside the window) [I] — [Winston et al., arXiv 2603.20449](https://arxiv.org/abs/2603.20449)

**Rule mining from agent artefacts**
- AgenTest (2026) mines business rules from system prompts, tool definitions and domain knowledge into Given-When-Then specs. On τ²-bench it produced 551 specs and found violations of 89 and 121 distinct specs with two models, 3.4x and 2.5x the number found by all baselines combined. About 60% of bug-triggering runs could not be detected from the final state alone — [AgenTest, arXiv 2610.28116](https://arxiv.org/abs/2610.28116)
- CAP-CPT (2025) parses policy docs into factual, behavioural and conditional specifications and internalises them through continued pretraining. Prompt length drops 97.3%, and SFT on CoT trajectories "degrades sharply as policy complexity increases" — [Liu et al., arXiv 2510.11588](https://arxiv.org/abs/2510.11588)

### Inferences
- Use a two-tier extraction target. Tier 1 is always-on: an NL **rule card** (atomic rule text, modality, subject/role, conditions, exceptions, thresholds, definitions used, cross-refs, jurisdiction, effective dates, source span). Tier 2 is a selective **executable form** (Rego/Cedar/DMN/ASP/SMT) for rules that are crisp, high-stakes and decidable from structured facts. Tier 1 is reliably automatable. Tier 2 needs verifier loops and human sign-off.
- Self-reported "compile rate" and LLM-judge scores overstate deployable correctness. The toolkit should measure behavioural equivalence (positive and negative tests, scenario execution), following the strict criteria in arXiv 2609.24036 and arXiv 2604.17153.
- Under-specification (implicit negation, closed-world assumptions, default classes) is the dominant semantic error in policy-to-code. Extraction prompts and tests should probe the complement of each rule explicitly.

### Gaps
- There is no shared, cross-domain benchmark for NL → rule-card extraction fidelity. Each paper uses its own corpus and LLM-judge rubric.
- I found no independent replication of AWS's ">99% soundness" claim beyond the single τ²-bench case study above.
- No 2025-2026 LLM work on LegalRuleML or SBVR generation turned up in arXiv searches. Activity has moved to ODRL, Cedar and Rego.

---

## 2. Representation: rule cards vs decision tables vs logic programs vs knowledge graphs; neuro-symbolic; conflict and overlap detection

### Takeaway
No single representation wins. Standards split by job:
- **LegalRuleML, Akoma Ntoso and ELI-style identifiers** for provenance, defeasibility, temporal status and jurisdiction metadata.
- **ODRL** for permission/prohibition/duty over assets.
- **Cedar and Rego** for fast, analysable permit/forbid on actions.
- **DMN** for business decision tables.
- **Catala, Prolog/ASP and SMT** for computational statutes.

Evidence from 2026 consistently favours a **neuro-symbolic split**: the LLM does fact extraction, a symbolic engine evaluates the rules. This beats both policy-as-prompt and LLM-written policy-as-code on crisp rules, but gives no advantage on subjective rules. Production authorization engines (Cedar, Rego, XACML) cover only permit/forbid. Obligations, waivers and meta-policy conflict resolution need deontic or defeasible layers.

### Cited Findings

**Standards and engines (how it works / developer / first release / status)**

| Representation | Developer & status | What it encodes | Source |
|---|---|---|---|
| LegalRuleML Core 1.0 | OASIS Standard, 30 Aug 2021 | Obligation/permission/prohibition/right, violations, penalties, reparations; strict/defeasible/defeater rule strength with Override; temporal status ("in force"); jurisdiction; authority; many-to-many links between rules and source provisions | [OASIS spec](https://docs.oasis-open.org/legalruleml/legalruleml-core-spec/v1.0/legalruleml-core-spec-v1.0.html) |
| Akoma Ntoso 1.0 | OASIS Standard, 29 Aug 2018 | XML for legislative/judicial docs; FRBR Work/Expression/Manifestation/Item; `<lifecycle>` events; fragment `@start/@end/@status` for point-in-time validity | [OASIS spec](https://docs.oasis-open.org/legaldocml/akn-core/v1.0/akn-core-v1.0-part1-vocabulary.html) |
| ODRL 2.2 | W3C Recommendation, 15 Feb 2018 | Policy (Set/Offer/Agreement) of Permission/Prohibition/Duty over Asset/Party/Action with Constraints; conflict strategy `perm`/`prohibit`/`invalid` (default invalid) | [W3C ODRL](https://www.w3.org/TR/odrl-model/) |
| SBVR 1.5 | OMG, Dec 2019 | Business vocabulary + business rules for exchange; RuleSpeak annex | [OMG SBVR](https://www.omg.org/spec/SBVR) |
| DMN 1.6 | OMG, adopted Sep 2026 (1.7 beta) | Decision requirements graphs + executable decision tables; XML interchange; BPMN companion | [OMG DMN](https://www.omg.org/spec/DMN) |
| Cedar | AWS, open source (Rust), 2023; paper 2024 | permit/forbid over principal/action/resource/context; designed for sound and complete logical encoding; core properties proved in Lean; reported faster than OpenFGA and Rego | [Cutler et al., arXiv 2403.04651](https://arxiv.org/abs/2403.04651) |
| OPA / Rego | CNCF graduated | Declarative Datalog-like rules over JSON; decouples decision from enforcement; decisions can be arbitrary structured data | [OPA docs](https://www.openpolicyagent.org/docs/latest/) |
| Catala | Inria, Apache-2.0, 2021 | Literate programming of statutes, line by line against the legal text; default logic as a first-class feature; compiler core proved in F*; found a bug in the official French family-benefits implementation | [Merigoux et al., arXiv 2103.03198](https://arxiv.org/abs/2103.03198); [GitHub](https://github.com/CatalaLang/catala) |
| CQL 2.0 / CPG-on-FHIR 2.0 | HL7 (CQL STU, active Jul 2026; CPG STU2 Nov 2024) | Computable clinical logic (ELM canonical form) for CDS, quality measures and computable guidelines on FHIR R4 | [HL7 CQL](https://cql.hl7.org/); [CPG IG](https://hl7.org/fhir/uv/cpg/) |
| OSCAL | NIST | Machine-readable security control catalogs, baselines and implementation (XML/JSON/YAML); supports "policy-as-code" | [NIST OSCAL](https://pages.nist.gov/OSCAL/) |

**Neuro-symbolic evidence (LLM extracts facts, solver decides)**
- Policy-as-logic (IBM, 2026) works as follows. Claude Opus 4.7 translates the policy once into an answer-set program. Per query, an LLM extracts JSON facts using the schema only. Facts are deterministically grounded and clingo solves. On RuleArena, accuracy was Airline 0.61-1.00 (policy-as-prompt ≤0.38, LLM policy-as-code ≤0.40), Tax 0.31 (≤0.10) and NBA 0.36-0.50 (≤0.39). On subjective HR moderation it was 0.93-0.97, with no advantage. Under 6 perturbations, Airline was 0.62-0.98 versus ≤0.27 for baselines. Token use was about 10x lower on Airline, about 2.4x lower on Tax, and higher on HR. Remaining errors are almost all *extraction* errors (a digit misread as $29,314→$29,114; a Wuhan origin defaulted to "U.S."; stance blindness) — [Nair et al., arXiv 2608.11905](https://arxiv.org/abs/2608.11905)
- MedDEx (2026) separates LLM patient-state extraction from deterministic execution of guideline rules. It improves accuracy *and* lowers cost on several clinical-guideline benchmarks: "additional LLM reasoning does not necessarily translate into better guideline adherence" — [MedDEx, arXiv 2610.15912](https://arxiv.org/abs/2610.15912)
- GDGraph (2026) compiles radiology guidelines into an executable decision graph. A fast model answers local questions and deterministic traversal resolves the Boolean logic. On 347 cases accuracy rose from 57.3% to 90.8%, versus 80.1% for RAG GPT-4o and 82.7% for graph-guided CoT GPT-4o, at lower latency and cost — [GDGraph, arXiv 2610.40327](https://arxiv.org/abs/2610.40327)
- PolicyGuard (2026) turns organisational NDA playbooks into typed relational logic rules plus atom-level extraction questions. The LLM answers local questions from retrieved clauses and a symbolic evaluator decides non-compliance, which makes it "explicit, maintainable, and systematically testable" — [PolicyGuard, arXiv 2606.32004](https://arxiv.org/abs/2606.32004)
- Insurance coverage (2025): a *guided* LLM + logic encoding of the contract beat vanilla LLM and unguided encoding on Chubb and Aetna student health policies — [Kant et al., arXiv 2502.17638](https://arxiv.org/abs/2502.17638)
- CHAI (ICAIL 2026 workshop) uses the LLM only as a bounded conversational interface to a DCR-graph controller that executes legal provisions and obligations (deontic, defeasible and temporal) for eGovernment chatbots — [Chalkidis et al., arXiv 2608.01346](https://arxiv.org/abs/2608.01346)
- XAI-LAW (ICLP 2025) encodes Italian Criminal Code articles in ASP, handles contradictions, explains outcomes through stable-model supportedness, and learns rules from verdicts with ILP — [Dovier et al., arXiv 2601.03844](https://arxiv.org/abs/2601.03844)
- DeoGen (Oct 2026) autoformalises policies into FOL decision trees to generate benchmarks. Frontier models give the right verdict 89-92% of the time when facts are sufficient, but only 22-40% correctly *abstain* when facts are insufficient, even when told to abstain — [DeoGen, arXiv 2610.38687](https://arxiv.org/abs/2610.38687)

**Expressiveness limits of production engines**
- AgenticRei (IEEE ICWS 2026) argues that XACML, Rego and Cedar "address only the permit/prohibit subset". They lack obligation lifecycle management, dispensations (waivers), meta-policy conflict resolution and ontological class reasoning. AgenticRei expresses these in an OWL-based Rei deontic language evaluated outside the LLM, for both tool calls and A2A messages (examples only, no benchmark) — [Joshi, Finin et al., arXiv 2606.19464](https://arxiv.org/abs/2606.19464)

**Conflict, overlap and redundancy detection**
- Cedar Analysis encodes whole policy sets as formulas to detect conflicting or redundant policies and policies that allow or deny everything. AgentCore runs it during authoring and attachment [V] — [AWS Security Blog, May 2026](https://aws.amazon.com/blogs/security/why-policy-in-amazon-bedrock-agentcore-chose-cedar-for-securing-agentic-workflows/)
- Restricter (TACAS 2026) automatically tightens Cedar permit rules against access logs toward least privilege — [Restricter, arXiv 2601.14582](https://arxiv.org/abs/2601.14582)
- ODRL normalisation (ESWC 2026) rewrites policies into a permissions-only normal form whose semantics are preserved, so comparing policies reduces to an identity check. Output size is exponential in the number of attributes — [Salas et al., arXiv 2603.12926](https://arxiv.org/abs/2603.12926). A formally grounded ODRL evaluator (2026) notes that ODRL "has no mathematical formal semantics", so evaluators disagree — [Salas et al., arXiv 2607.15987](https://arxiv.org/abs/2607.15987). ODRE adds enforcement algorithms (Python/Java) to descriptive ODRL — [Cimmino et al., arXiv 2409.17602](https://arxiv.org/abs/2409.17602)
- A defeasible deontic calculus with inheritance is proven to resolve norm conflicts. It also shows one common resolution strategy to be "a red herring" — [Olson et al., arXiv 2407.04869](https://arxiv.org/abs/2407.04869)
- VEPA (2026) has an LLM propose guardrail policy patches, and a deterministic verifier accepts them only if they are "structurally valid and conflict-free" — [VEPA, arXiv 2610.12813](https://arxiv.org/abs/2610.12813)
- AWS AR checks generate test scenarios from extracted rules and show the rules causing a contradiction when a test fails [V] — [AWS News Blog](https://aws.amazon.com/blogs/aws/minimize-ai-hallucinations-and-deliver-up-to-99-verification-accuracy-with-automated-reasoning-checks-now-available/)

### Inferences
- A practical KB schema is the **rule card as the canonical node**. It is linked to (a) its source provision in a legal-document hierarchy (Akoma Ntoso/ELI-like Work→Expression IDs), (b) defined terms, (c) cross-referenced provisions, (d) overriding/exception rules (LegalRuleML-style Override), and (e) zero or more executable bindings (Cedar/Rego/DMN/ASP) with test suites. This keeps rules *searchable* (text + metadata) and *enforceable* (bindings) without forcing every rule into logic.
- Conflict detection is mature only where rules are formal (Cedar, ODRL normal forms, SMT). For NL rule cards, the realistic option is LLM-flagged candidate conflicts (same subject and action, opposite modality, overlapping validity) that a human resolves. I found no benchmarked tool for this.
- DeoGen's abstention result implies that an enforcement layer must represent "insufficient facts → ask or escalate" explicitly (three-valued outcome), as AWS AR's SATISFIABLE/ambiguous results do.

### Gaps
- No head-to-head study compares DMN vs Rego vs ASP vs NL rule cards on the same corpus for authoring cost, maintainability and accuracy.
- There is little empirical work on LLM-based conflict detection across NL policy corpora (e.g., HR handbook vs regional addenda).

---

## 3. Retrieval of applicable rules: regulatory and legal RAG, clause retrieval, hierarchical and cross-reference-aware indexing, applicability by jurisdiction, date and role

### Takeaway
Retrieving the *applicable* rule set is the main bottleneck, more than generation:
- Structure-aligned chunking (section/subsection/clause), hybrid BM25 + dense with reranking, and **citation/cross-reference closure** give the largest measured gains.
- Temporal validity must be a *hard filter*, not a ranking signal.
- Agentic benchmarks (τ-Knowledge) show frontier agents at about 25-37% pass^1 when they must retrieve policies from about 700 interlinked documents. Handing them the gold documents only lifts the ceiling to about 40%, so retrieval and policy reasoning both fail.
- Commercial legal RAG still hallucinates 17-33% of the time.

### Cited Findings

**Regulatory QA benchmarks (RegNLP)**
- ObliQA (2024) has 27,869 questions over Abu Dhabi Global Markets financial regulations (40 docs). It comes with the RIRAG task and the RePASs metric, which checks that answers capture all relevant obligations without contradictions — [Gokhan et al., arXiv 2409.05677](https://arxiv.org/abs/2409.05677)
- ObliQA-MP (NLLP 2025) has 2,976 multi-passage QA pairs. LLM validation removed about 20% of passages that NLI filtering had missed. Performance "drops notably" from single- to multi-passage retrieval. Learning-to-rank over lexical, semantic and graph features beats dense, hybrid and fusion baselines — [Gokhan & Briscoe, NLLP 2025](https://aclanthology.org/2025.nllp-1.10/)
- RIRAG-2025 shared-task systems:
  - LeSeR (lexical reranking of semantic retrieval): R@10 0.8201, MAP@10 0.6655 — [arXiv 2412.06009](https://arxiv.org/abs/2412.06009)
  - MST-R (hard-negative fine-tuning + RRF hybrid + reranker tuning) ranked top, and showed that "a trivial answering approach games the RePASs metric" — [arXiv 2412.10313](https://arxiv.org/abs/2412.10313)
  - AUEB found that concatenating extracted "obligations" scores well on RePASs, a "dubious" result — [arXiv 2412.11567](https://arxiv.org/abs/2412.11567)
  - Hybrid BM25 + fine-tuned sentence transformer beats either alone — [arXiv 2502.16767](https://arxiv.org/abs/2502.16767)
- Domain-adapted RAG on ObliQA (2026) used entailment tuning + contrastive tuning + BM25 fusion on LegalBERT and raised R@10 from 0.256 to 0.774 (BM25 0.678; E5-large-v2 0.758). However, a closed-book model scored within 0.011 RePASs of the full pipeline "while producing answers that cite nothing and misstate obligations". Their conclusion: RePASs does not measure grounding [I-ish critique] — [Deußer et al., arXiv 2609.30009](https://arxiv.org/abs/2609.30009)
- RegOps-Bench / RefWalk (EMNLP 2026 Findings) traverses cross-document citations from a shared topic anchor, enforcing "evidence-set closure" and per-rule attribution. Existing systems "saturate" on flat-structure rules (HIPAA) but fail on multi-tier authority structures — [Ju & Lee, arXiv 2605.29742](https://arxiv.org/abs/2605.29742)
- ViHERMES (2026) is multihop QA over Vietnamese healthcare regulations that requires amendment tracing and cross-document comparison, with graph-aware retrieval over legal units — [arXiv 2602.07361](https://arxiv.org/abs/2602.07361)

**Legal RAG benchmarks and structure-aware indexing**
- LegalBench-RAG (2024) has 6,858 expert-annotated query-snippet pairs over a 79M-character corpus. It targets *minimal precise snippets* rather than documents — [Pipitone & Alami, arXiv 2408.10343](https://arxiv.org/abs/2408.10343)
- CLERC (2024) covers case-law citation retrieval and analysis generation. Zero-shot IR reaches only 48.3% recall@1000, and GPT-4o hallucinates the most — [Hou et al., arXiv 2406.17186](https://arxiv.org/abs/2406.17186)
- StrucChunk (Oct 2026) treats documents as DAGs of provisions, keeps clause boundaries, resolves cross-references *before* embedding, and uses BM25 + BGE-M3 with RRF:
  - LegalBench-RAG Char-Recall@8: 48.18% vs 23.59% for the best baseline.
  - Indian CrPC R@5: 0.557→0.804.
  - GDPR R@5: 0.868.
  - Thai NitiBench-CCL HR@5: 0.856 vs 0.594 for naive chunking.
  - Chunking accounts for 73-88% of the gain. Cross-ref augmentation adds +2.3% on cross-ref queries.
  - Source: [StrucChunk, arXiv 2610.26313](https://arxiv.org/abs/2610.26313)
- On the German Civil Code (ICAIL 2026 ASAIL), section/subsection chunks gave the highest recall. Contextual chunking, RAPTOR and Lumber-style approaches that "override this structure perform worse" and cost more — [Prior et al., arXiv 2605.19806](https://arxiv.org/abs/2605.19806)
- GEMS-RAG (2026) handles engineering standards (MUTCD) with hierarchical parsing, a multimodal KG linking figures to normative provisions, and graph expansion. It beats text-only and graph RAG — [arXiv 2610.33277](https://arxiv.org/abs/2610.33277)
- Contract clause retrieval datasets: CUAD has more than 13,000 expert annotations of reviewable clause types — [Hendrycks et al., arXiv 2103.06268](https://arxiv.org/abs/2103.06268). ContractNLI (607 contracts) uses entailed/contradicted/not-mentioned labels with evidence spans, and found that "negations by exceptions" make it hard — [Koreeda & Manning, arXiv 2110.01799](https://arxiv.org/abs/2110.01799)

**Temporal and applicability filtering**
- German statutory temporal QA (ICAIL 2026, best-paper nominee) used 312 expert-validated pairs:
  - Post-cutoff amendment questions, Claude Sonnet 3.7: vanilla 24.35% → web search 63.48% → RAG with as-of date extraction + version hard-filter 83.48-86.96%.
  - Vanilla "version-application correctness" was 5-14%.
  - Web search showed recency bias on historical questions.
  - Removing the temporal filter caused a "substantial drop".
  - Conclusion: "treat temporal validity as a hard constraint".
  - Germany lacks an authoritative machine-readable historical consolidated database, so the authors used buzer.de.
  - Source: [Prior, Schultz, Grabmair, arXiv 2605.23497](https://arxiv.org/abs/2605.23497)
- SAT-Graph RAG (JURIX 2025) separates abstract legal Works from versioned Expressions (LRMoo-inspired), reuses unchanged component versions, and reifies legislative events as Action nodes. This enables deterministic point-in-time retrieval, hierarchical impact analysis and provenance (conceptual architecture, Brazilian Constitution case study) — [de Martim, arXiv 2505.00039](https://arxiv.org/abs/2505.00039)
- The US eCFR "versioner" API returns per-section content versions with `date`, `amendment_date`, `issue_date`, `substantive` and `removed` flags (verified by live call on 12 CFR 1026.18, Nov 2026). This is an authoritative point-in-time source for US federal regulations — [eCFR versioner API](https://www.ecfr.gov/api/versioner/v1/versions/title-12.json?part=1026&section=1026.18)
- Jev-Guard (2026) first *routes* over a policy tree spanning content moderation, cybersecurity, privacy and legal compliance to pick the applicable policy for the caller's audit context, then classifies. It reports 93.10% hierarchical routing accuracy and 93.72% safety accuracy at a mean of 58 ms — [Jev-Guard, arXiv 2610.18326](https://arxiv.org/abs/2610.18326)

**Agentic retrieval of policies during tasks**
- τ-Knowledge (Sierra, ICML 2026) has a τ-Banking domain with about 700 interlinked docs (698 docs, ~195K tokens, 21 product categories). Tasks need on average 18.6 docs and 9.5 tool calls. Frontier models score about 25.5% pass^1 with either embedding retrieval or terminal search — [Shi et al., arXiv 2603.04370](https://arxiv.org/abs/2603.04370). Sierra (13 May 2026) later reported:
  - The leader rose from GPT-5.2 at 25.5% pass^1 / 9.3% pass^4 at launch to GPT-5.5 xhigh at 37.4% / 20.6%.
  - A ceiling of about 40% pass^1 even when relevant docs are handed over, versus >80% on other τ-Bench domains.
  - Stronger agents re-search as the conversation evolves and search more precisely (9.1 vs 19.4 searches per task) rather than retrieving once [V].
  - Source: [Sierra blog](https://sierra.ai/blog/tau-knowledge)
- Portable "skill" agentic RAG (EMNLP 2026 Industry) used an LLM-generated "Wikipedia-style" navigation index over SOP/policy docs plus a retrieval API. It reached 99.2% procedural equivalence and 83.3% evidence sufficiency in customer support, about 10x slower than production (scoped to a curated corpus with human review) — [Bako et al., arXiv 2610.14428](https://arxiv.org/abs/2610.14428)

**Reliability of legal RAG products**
- A preregistered evaluation found that Lexis+ AI and Westlaw AI-Assisted Research / Ask Practical Law AI hallucinate 17-33% of the time, despite vendor claims of being "hallucination-free" [I] — [Magesh et al., arXiv 2405.20362](https://arxiv.org/abs/2405.20362)
- On LaborBench (all US state unemployment-insurance requirements, built by DOL attorneys), standard RAG scored about 70%. STARA (custom statutory tool) scored 83%, rising to 92% after correcting DOL omissions. Westlaw AI scored 58% and Lexis+ AI 64%. Errors came from confusing related concepts, misreading exceptions, and missed provisions [I] — [Afane et al., arXiv 2603.03300](https://arxiv.org/abs/2603.03300)

### Inferences
- Index design for rules:
  1. Use one chunk per provision or rule unit, with a breadcrumb path (Act > Part > Section > Subsection), never fixed windows.
  2. Store a cross-reference edge list and definitions. At query time, expand to *citation closure* (referenced provisions, definitions, exceptions, overriding rules).
  3. Run hybrid BM25 + dense with a reranker.
  4. Apply hard metadata pre-filters for jurisdiction, effective-from/effective-to (as-of the fact date, not the query date), entity type/role, product line and authority level.
  5. Use an LLM-built navigation layer (table of contents / topic index) for agentic browsing.
- RePASs-style reference-free metrics can be gamed. The toolkit should evaluate retrieval with gold provision IDs (recall@k on rule IDs) and evaluate answers with per-rule attribution checks.
- Since even gold-document agents cap at about 40% on τ-Banking, retrieval improvements alone will not deliver policy adherence. Enforcement (Section 4) is needed for actions.

### Gaps
- No public benchmark tests *jurisdiction* and *role* applicability filtering, as opposed to temporal filtering (e.g., the same obligation differing by US state or by customer segment).
- EU EUR-Lex/ELI and UK legislation.gov.uk point-in-time APIs were not checked in this pass.

---

## 4. Enforcement and adherence: policy-following benchmarks, guardrails, policy-as-prompt vs policy-as-code, runtime verification, auditability

### Takeaway
Policy-in-prompt is insufficient for actions:
- τ-bench-style agents follow policies inconsistently (pass^8 <25% at launch).
- Outcome-only scoring hides most process violations (CXBench: 80% of outcome-passing runs were false passes).
- Learned compliance detectors can be "rule-blind".

The strongest results come from **deterministic pre-execution gates on tool calls**: guard code compiled from policies, SMT/Cedar checks, and temporal-logic monitors, with LLMs used only to extract facts or propose policies. These cut violations sharply but impose a "verifier tax" (low recovery after blocks, longer conversations) and only cover what is checkable before a call. Content-level guardrails (NeMo, Guardrails AI, constitutional classifiers) are complementary and probabilistic.

### Cited Findings

**Benchmarks**
- τ-bench (Sierra, Jun 2024) simulates users and gives agents domain API tools plus *policy guidelines*, and scores by final DB state. It introduced pass^k. gpt-4o succeeded on <50% of tasks with pass^8 <25% in retail — [Yao et al., arXiv 2406.12045](https://arxiv.org/abs/2406.12045). τ²-bench (Jun 2025) added a dual-control telecom domain, where performance drops significantly when agents must guide users — [Barres et al., arXiv 2506.07982](https://arxiv.org/abs/2506.07982)
- ST-WebAgentBench (ICLR 2026) has 222 enterprise web tasks paired with ST policies. Its Completion-under-Policy (CuP) metric credits only policy-respecting completions, and agents' CuP was less than two-thirds of nominal completion — [Levy et al., arXiv 2410.06703](https://arxiv.org/abs/2410.06703)
- RuleArena (ACL 2025) covers airline baggage, NBA transactions and tax. LLMs "struggle to identify and apply the appropriate rules, frequently becoming confused by similar but distinct regulations", fail at the math even with the right rules, and improve with oracle math and logic tools — [Zhou et al., arXiv 2412.08972](https://arxiv.org/abs/2412.08972)
- A benchmark audit (Nov 2026) of 9 policy-decision benchmarks found unsupported targets and broken scorers. Fixing the LegalBench SARA-numeric scorer raised acceptance by more than 80 points, and restoring a zero floor changed 27 of 300 RuleArena Tax references [I] — [Xiao & Cai, arXiv 2611.07042](https://arxiv.org/abs/2611.07042)
- CXBench (Oct 2026) covers 6 regulated customer-experience domains, with **rule cards** linking cited regulatory obligations to observable trace evidence. The hybrid grader is deterministic for ordering and authority, with an LLM judge for semantics. 55.5% of 840 runs were false passes, which is 80.1% of outcome-passing runs. Only 13.8% passed both outcome and process checks — [CXBench, arXiv 2610.25954](https://arxiv.org/abs/2610.25954)
- τ-break / CRAFT (2025): policy-aware persuasive adversarial users beat DAN-style jailbreaks against policy-adherent agents, and simple defences "fall short" — [Nakash et al., arXiv 2506.09600](https://arxiv.org/abs/2506.09600). FraudBench (2026) runs 107 adaptive fraud scenarios on τ-Banking, where safety is history-dependent — [arXiv 2608.18136](https://arxiv.org/abs/2608.18136)

**Policy-as-code and runtime verification of tool calls**
- ToolGuard (IBM, EMNLP 2025 Industry) works at buildtime and at runtime. At buildtime, an LLM maps policy → per-tool atomic policies with compliance and violation examples, then generates test-driven Python guard code. At runtime, the guard runs before each tool call. Mapper F1 was 0.80 and guard test-pass 0.75-0.82. On 22 policy-violating τ-bench airline tasks, pass^1 went 0.450→0.685 and pass^10 0.227→0.500, while appending the policy to the prompt reached only 0.273 pass^10. It cannot catch *omitted* required actions — [Zwerdling et al., arXiv 2507.16459](https://arxiv.org/abs/2507.16459)
- Solver-aided checking (2026) translates τ²-bench airline policy into SMT-LIB and has Z3 check each planned write call. Invalid write calls fell to 29% of writes, with slightly lower recall and similar task success. Success dropped 26% from pass^1 to pass^4, versus 40% for the baseline — [Winston et al., arXiv 2603.20449](https://arxiv.org/abs/2603.20449)
- Agent-C (Dec 2025) adds a DSL for *temporal* properties (e.g., authenticate before data access), compiles them to FOL, and checks with SMT during token generation, using constrained decoding to produce compliant alternatives. It reports 100% conformance and 0% harm on retail and airline while improving utility — [Kamath et al., arXiv 2512.23738](https://arxiv.org/abs/2512.23738)
- AgentSpec (ICSE 2026) is a DSL of trigger/predicate/enforcement rules. It prevents >90% of unsafe code-agent executions with ms-level overhead. o1-generated rules reached 95.56% precision and 70.96% recall for embodied agents — [Wang et al., arXiv 2503.18666](https://arxiv.org/abs/2503.18666)
- Progent (2025) expresses privileges as symbolic rules over tool names and arguments, checked deterministically. LLM-proposed updates are classified by an SMT solver as narrowing (auto-applied) or expansion (needs approval) — [Shi et al., arXiv 2504.11703](https://arxiv.org/abs/2504.11703). ActGov (2026) builds policies from tool specs and failure traces with SMT counterexample checks, and enforces per action within task-scoped authorization — [arXiv 2609.24446](https://arxiv.org/abs/2609.24446)
- C-Trace (2026) expresses GDPR consent, purpose limitation, minimisation and erasure as predicates over agent traces, with a runtime monitor intercepting every tool call. Attack success was ≤12% with 10% extractor noise and 0% with perfect extraction; false positives were ≤16% — [Kahani et al., arXiv 2606.19242](https://arxiv.org/abs/2606.19242)
- ShieldAgent (2025) extracts verifiable rules from policy docs into probabilistic rule circuits and *retrieves the relevant circuits* per trajectory. It reports +11.3% over prior guards and 90.1% recall on ShieldAgent-Bench (3K pairs) — [Chen et al., arXiv 2503.22738](https://arxiv.org/abs/2503.22738). GuardAgent (ICML 2025) turns guard requests into a plan and then into executable guardrail code, with 98% accuracy on EICU-AC access control and 83% on Mind2Web-SC — [Xiang et al., arXiv 2406.09187](https://arxiv.org/abs/2406.09187)
- JevAct (IBM, 2026) compiles domain policies into executable state checks plus structured questions scored by a prefill-only decision model. It gives consistent gains on τ²-bench Telecom and BFCL, with mixed results on Airline — [arXiv 2610.38620](https://arxiv.org/abs/2610.38620)
- Amazon Bedrock AgentCore Policy enforces Cedar at the gateway for every agent tool call with default deny. It offers NL→Cedar authoring verified against MCP tool schemas plus Cedar Analysis, uses partial evaluation to hide always-denied tools, and logs to CloudWatch. The current docs (Nov 2026) also list "temporal policies" (session-scoped rules over earlier actions, e.g. approval before transfer, running budget totals) and authoring in the open-source Dogwood policy language, which combines input-based, temporal and guardrail-signal conditions under one permit/forbid model. A search snippet of earlier docs listed "no date/time comparisons" as a limitation, so check the current docs [V] — [AWS Security Blog](https://aws.amazon.com/blogs/security/why-policy-in-amazon-bedrock-agentcore-chose-cedar-for-securing-agentic-workflows/); [AgentCore docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html)
- The Lean-Agent Protocol (2026) auto-formalises institutional finance policies into Lean 4 and treats each action as a conjecture. It is a roadmap with demo code and no empirical evaluation, and its compliance claims are aspirational [flag] — [Rashie & Rashi, arXiv 2604.01483](https://arxiv.org/abs/2604.01483)

**Policy-as-prompt and learned guardrails**
- Policy-as-Prompt (NeurIPS 2025 RegML workshop) compiles PRDs, TDDs and code into a source-linked policy tree and then into prompt-based runtime classifiers with provenance and audit logs — [Kholkar & Ahuja, arXiv 2509.23994](https://arxiv.org/abs/2509.23994)
- NeMo Guardrails (NVIDIA, open source, EMNLP 2023 demo; v0.24.1 listed in late 2026) offers input, retrieval, dialog, execution and output rails defined in Colang/YAML, an OpenAI-compatible server, and a microservice — [Rebedea et al., arXiv 2310.10501](https://arxiv.org/abs/2310.10501); [NVIDIA docs](https://docs.nvidia.com/nemo/guardrails/latest/index.html)
- Guardrails AI (Apache-2.0, ~7.6k stars) composes Hub validators into input/output guards and provides Pydantic-structured outputs. As of Jul 2026 it is discontinuing hosted remote inference (cutoff 25 Aug 2026) [V] — [GitHub](https://github.com/guardrails-ai/guardrails)
- Constitutional Classifiers (Anthropic, Jan 2025) are trained on synthetic data generated from an NL constitution of permitted and restricted content. More than 3,000 hours of red teaming found no universal jailbreak, at +0.38% production refusals and 23.7% overhead — [Sharma et al., arXiv 2501.18837](https://arxiv.org/abs/2501.18837). CC++ (Jan 2026) adds exchange classifiers, a cascade and linear probes, for 40x lower compute and a 0.05% refusal rate [V] — [Cunningham et al., arXiv 2601.04603](https://arxiv.org/abs/2601.04603)
- FinGuard (2026) induces a compliance-risk taxonomy directly from Chinese financial regulations, trains Qwen3-8B with SFT + self-play RL, and beats much larger general LLMs on FinGuard-Bench — [Dou et al., arXiv 2605.29427](https://arxiv.org/abs/2605.29427)
- "Rule blindness" (Aug 2026): deleting, permuting or swapping the governing rule left accuracy *unchanged* for every guard model and activation probe tested, including a policy-conditioned guard that cites the clause. Step-by-step reasoning escaped the failure [I] — [Sadhu et al., arXiv 2608.16852](https://arxiv.org/abs/2608.16852)

**Costs, side-effects and auditability**
- Verifier tax (2026, τ-bench): safety mediation intercepted up to 94% of non-compliant actions, but strictly safe success stayed <5% in most settings. Recovery after a block ranged from 21% down to near 0, and agents hallucinated user IDs to bypass authentication — [Sah et al., arXiv 2603.19328](https://arxiv.org/abs/2603.19328)
- "Stop Means Stop" (2026): approval gates, cancellation and timeouts fail their barrier semantics in all 6 open-source agent frameworks tested (sibling side-effects leak during a pause; 215 of 1,200 live runs leaked). The fix is an environment-external gate with complete mediation — [Khan, arXiv 2607.14166](https://arxiv.org/abs/2607.14166)
- Auditable Agents (2026) defines five dimensions (action recoverability, lifecycle coverage, policy checkability, responsibility attribution, evidence integrity). Pre-execution mediation with tamper-evident records added 8.3 ms median overhead — [Nian et al., arXiv 2604.05485](https://arxiv.org/abs/2604.05485). Local coding agents can delete their own traces when asked, so logging must sit outside the agent's control — [Qin et al., arXiv 2609.30266](https://arxiv.org/abs/2609.30266)
- Cognitive Core (2026) uses a hash-chained audit ledger and makes human review a precondition of execution. On a tiny 11-case prior-authorization set it had 0 "silent errors" versus 5-6 for ReAct and Plan-and-Solve (very small sample) — [Seck, arXiv 2604.10658](https://arxiv.org/abs/2604.10658)

### Inferences
- Use a layered enforcement design:
  - **L0** retrieval-grounded prompting (rule cards injected, with citations) for advisory answers.
  - **L1** deterministic pre-execution gates on mutating tool calls (Cedar/Rego/compiled guards/SMT), fail-closed, outside the agent process.
  - **L2** trace monitors for temporal and obligation rules (authenticate-before, notify-after).
  - **L3** post-hoc process audit with rule-card → trace-evidence links (CXBench-style) for rules that cannot be decided before the call.
  - Content guardrails (NeMo/constitutional classifiers) are orthogonal and handle topic and safety policy.
- Every enforcement decision should log rule-ID, rule version, input facts and outcome, so audits can replay decisions against the rule version in force.
- Gates must return actionable denial explanations (rule text + missing fact), because agents recover poorly from bare denials (verifier tax).

### Gaps
- No benchmark measures end-to-end "retrieve applicable policy → act → enforce" on a large heterogeneous policy corpus with executable ground truth. τ-Knowledge comes closest but does not evaluate enforcement layers.
- Independent evaluations of NeMo Guardrails or Guardrails AI on *business-policy* adherence, as opposed to safety, were not found.

---

## 5. Domains with evidence: finance and banking, healthcare guidelines, tax, insurance, HR, IT security

### Takeaway
Finance and healthcare have the most evidence:
- **Finance:** extraction plus KG-RAG in production parallel runs; executable compliance code; regulation-derived guard models.
- **Healthcare:** LLM conversion of guidelines into executable models with expert review, and rule-executor separation that beats pure LLM reasoning.

Tax is the canonical case where pure LLMs fail and logic programs (Catala, Prolog/ASP) help. Insurance evidence is thin and mostly industry-reported. HR and IT security rely on generic access-control (Cedar/Rego/OSCAL) and AR-checks-style tooling.

### Cited Findings
- **Finance / banking:**
  - ComplianceNLP deployment: 96.0% estimated recall / 90.7% precision on 9,847 regulatory updates and a 3.1x analyst efficiency gain [V] — [arXiv 2604.23585](https://arxiv.org/abs/2604.23585)
  - Compliance-to-Code / FinCheck — [arXiv 2505.19804](https://arxiv.org/abs/2505.19804)
  - FSC SMT framework, 86.2% correct SMT — [arXiv 2601.06181](https://arxiv.org/abs/2601.06181)
  - ObliQA (ADGM) — [arXiv 2409.05677](https://arxiv.org/abs/2409.05677)
  - FinGuard — [arXiv 2605.29427](https://arxiv.org/abs/2605.29427)
  - τ-Banking at ~25.5% pass^1 — [arXiv 2603.04370](https://arxiv.org/abs/2603.04370)
  - AWS lists mortgage approvals, insurance eligibility and employee benefits as AR-checks use cases [V] — [AWS docs](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html)
- **Healthcare guidelines:**
  - NICE pancreatic and lung cancer guidelines were converted by stepwise LLM transformation into executable models. Experts saw strong alignment, discrepancies were "mostly partial omissions" with hallucinated rules rare, and F1 was 82.5% on 20 vignettes (Learning Health Systems 2026) — [Gupta et al., arXiv 2608.30022](https://arxiv.org/abs/2608.30022)
  - Stroke-care conformance checking without pre-built CIGs: LLMs extract 50 rules from the guideline, translate them into executable scripts, and check hundreds of discharge-letter traces (>86% conformant) at Alessandria Hospital — [Leonardi et al., arXiv 2606.09489](https://arxiv.org/abs/2606.09489)
  - MedDEx — [arXiv 2610.15912](https://arxiv.org/abs/2610.15912)
  - GDGraph, 57.3→90.8% — [arXiv 2610.40327](https://arxiv.org/abs/2610.40327)
  - ClinicBot extracts guidelines into semantic units (recommendations, tables, definitions, narrative) with provenance and ranks by guideline structure rather than similarity — [arXiv 2605.00846](https://arxiv.org/abs/2605.00846)
  - CliCARE aligns patient temporal KGs with a normative guideline KG (AAAI 2026 oral) — [arXiv 2507.22533](https://arxiv.org/abs/2507.22533)
  - Standards targets: CQL 2.0 and CPG-on-FHIR STU2 — [HL7 CQL](https://cql.hl7.org/); [CPG IG](https://hl7.org/fhir/uv/cpg/)
- **Tax:**
  - SARA + logic programs — [arXiv 2508.21051](https://arxiv.org/abs/2508.21051)
  - DeonticBench SARA Numeric hard subset at 44.4% best — [arXiv 2604.04443](https://arxiv.org/abs/2604.04443)
  - RuleArena Tax, where policy-as-logic reached only 0.31 — [arXiv 2608.11905](https://arxiv.org/abs/2608.11905)
  - Catala on US §121 and French family benefits — [arXiv 2103.03198](https://arxiv.org/abs/2103.03198)
  - Caution: SARA and RuleArena-Tax reference and scorer errors were found by audit — [arXiv 2611.07042](https://arxiv.org/abs/2611.07042)
- **Insurance:**
  - Munich Re "Rule AI" uses LLMs to turn underwriting manuals into rule trees. In an atrial-fibrillation PoC on synthetic cases, outcomes matched existing rules in ~87% of cases (accounting for referred declines) and saved 1-2 hours per impairment. Misses traced to source formatting and ambiguous guidance [V, Aug 2026] — [Munich Re](https://www.munichre.com/us-life/en/insights/future-of-risk/scaling-underwriting-expertise-with-rule-ai-.html)
  - Coverage reasoning with guided LLM+logic — [arXiv 2502.17638](https://arxiv.org/abs/2502.17638)
- **HR policies:**
  - Policy-as-logic gives no advantage on subjective HR moderation (0.93-0.97 vs 0.93-0.96) — [arXiv 2608.11905](https://arxiv.org/abs/2608.11905)
  - AWS positions AR checks for HR and employee-benefit rules [V] — [AWS docs](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html)
  - PolicyGuard covers organisation-specific playbooks (NDA) — [arXiv 2606.32004](https://arxiv.org/abs/2606.32004)
- **IT security / access control:**
  - Prose2Policy / structured decomposition (Rego) — [arXiv 2603.15799](https://arxiv.org/abs/2603.15799), [arXiv 2609.24036](https://arxiv.org/abs/2609.24036)
  - RegoMender — [arXiv 2610.29456](https://arxiv.org/abs/2610.29456)
  - ARPaCCino (Terraform) — [arXiv 2507.10584](https://arxiv.org/abs/2507.10584)
  - AutoCedar / RAISE — [arXiv 2607.03656](https://arxiv.org/abs/2607.03656), [arXiv 2609.33796](https://arxiv.org/abs/2609.33796)
  - NIST OSCAL for control catalogs — [NIST](https://pages.nist.gov/OSCAL/)
- **Privacy / GDPR:**
  - C-Trace runtime GDPR predicates — [arXiv 2606.19242](https://arxiv.org/abs/2606.19242)
  - PolicyLR — [arXiv 2408.14830](https://arxiv.org/abs/2408.14830)
  - ARCCS GDPR — [arXiv 2610.01345](https://arxiv.org/abs/2610.01345)
- **Public sector / building codes:**
  - Dutch permit decision models — [arXiv 2604.17153](https://arxiv.org/abs/2604.17153)
  - CHAI DCR graphs — [arXiv 2608.01346](https://arxiv.org/abs/2608.01346)
  - CODE-ACCORD — [arXiv 2403.02231](https://arxiv.org/abs/2403.02231)
  - LaborBench (unemployment insurance) — [arXiv 2603.03300](https://arxiv.org/abs/2603.03300)

### Inferences
- In domains with numeric thresholds and calculations (tax, benefits, fees, underwriting), the rule must execute symbolically, because LLMs miscompute even with correct rules (RuleArena). In domains with judgement-laden language (HR conduct, "reasonable", "material"), retrieval + LLM judgement + human escalation is the only workable option, and formalisation adds little.

### Gaps
- No peer-reviewed independent evaluation of LLM-based insurance *underwriting* rule extraction was found. Evidence is industry reports.
- No HR-handbook-specific RAG or compliance benchmark was found.

---

## 6. Recommended design: making rules both searchable and enforceable; where determinism is required vs where retrieval suffices

### Takeaway
Build a **dual-representation rule KB**:
- Every rule is an NL rule card indexed for structure-aware hybrid retrieval with hard applicability filters (jurisdiction, effective dates, role, product).
- The subset of crisp, high-stakes, action-gating rules also has an executable binding (Cedar/Rego for action authorization; DMN/ASP/Catala/SMT for eligibility and calculation; temporal monitors for sequencing).
- These bindings are compiled through verifier loops with tests, evaluated *outside* the LLM at tool-call time, and logged with rule IDs and versions.

Use determinism wherever an action has side effects, a numeric or threshold decision is made, or auditors need replay. Use retrieval + LLM wherever rules are advisory, interpretive or subjective, and make "insufficient facts" an explicit escalate outcome.

### Cited Findings
- Separating fact extraction (LLM) from rule evaluation (solver or executor) beats both policy-as-prompt and LLM-generated policy-as-code on crisp policies and is more robust to perturbation, but not on subjective ones — [arXiv 2608.11905](https://arxiv.org/abs/2608.11905); [arXiv 2610.15912](https://arxiv.org/abs/2610.15912); [arXiv 2610.40327](https://arxiv.org/abs/2610.40327)
- Compiled guards beat appending policies to prompts (pass^10 0.500 vs 0.273) — [arXiv 2507.16459](https://arxiv.org/abs/2507.16459)
- Deterministic gates reduce violations but cut task completion unless denial feedback enables recovery — [arXiv 2603.19328](https://arxiv.org/abs/2603.19328); [arXiv 2603.20449](https://arxiv.org/abs/2603.20449)
- Temporal validity must be a hard filter — [arXiv 2605.23497](https://arxiv.org/abs/2605.23497); [arXiv 2505.00039](https://arxiv.org/abs/2505.00039)
- Structure-aligned chunking + cross-ref resolution is the largest retrieval lever — [arXiv 2610.26313](https://arxiv.org/abs/2610.26313); [arXiv 2605.19806](https://arxiv.org/abs/2605.19806); citation closure — [arXiv 2605.29742](https://arxiv.org/abs/2605.29742)
- Learned compliance detectors can ignore the rule entirely — [arXiv 2608.16852](https://arxiv.org/abs/2608.16852)
- Models fail to abstain when facts are insufficient — [arXiv 2610.38687](https://arxiv.org/abs/2610.38687)
- AR-checks scope caveat: VALID covers only what the policy's variables capture — [AWS docs](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html)
- Rule cards that link obligations to trace evidence enable process audits that outcome-only checks miss (80.1% of outcome passes were false passes) — [arXiv 2610.25954](https://arxiv.org/abs/2610.25954)
- Executable bindings need verified generation: intent atoms + verifier — [arXiv 2607.03656](https://arxiv.org/abs/2607.03656); strict tests — [arXiv 2609.24036](https://arxiv.org/abs/2609.24036); production gold shows ~52% outcome equivalence without such loops — [arXiv 2604.17153](https://arxiv.org/abs/2604.17153)

### Inferences
**Recommended pipeline for the toolkit (rules track)**
1. **Ingest and structure.** Parse into a provision tree with stable IDs (Work/Expression versioning à la Akoma Ntoso/SAT-Graph). Capture effective-from/to, jurisdiction, issuing authority and authority tier. Pull point-in-time versions from authoritative APIs where they exist (e.g., eCFR versioner).
2. **Extract rule cards** (De Jure / RegReAct pattern). Produce atomic rules with modality (obligation/permission/prohibition/definition/exception), subject/role, conditions, thresholds, exceptions, cross-refs (resolved and inlined summaries), defined terms, source span and confidence. Run judge + repair loops and keep a fidelity report (coverage + grounding, as in AWS AR checks).
3. **Link** into a rule graph with edges: `cites`, `defines`, `exception_of`, `overrides`, `amends/supersedes` (with dates), `implements` (internal policy → external regulation, ComplianceNLP-style gap mapping), and `conflicts_with?` (LLM-flagged, human-resolved).
4. **Index** one chunk per rule card and per provision, with breadcrumbs. Use hybrid BM25 + dense + reranker. Add metadata pre-filters (as-of date, jurisdiction, role, product, authority). Retrieve by citation closure. Add an LLM-generated navigation/TOC layer for agentic browsing.
5. **Bind executable forms selectively**, where a rule gates an action, computes a number, or must be auditable:
   - Cedar/Rego for tool-call authorization.
   - DMN/ASP/Catala/SMT for eligibility and calculation.
   - An Agent-C-style temporal DSL for ordering rules.
   - Generate each through intent-atom review → synthesis → schema validation → compile → positive/negative tests → solver analysis for conflicts and redundancy. Keep a human sign-off flag per binding.
6. **Enforce** in a gate outside the agent process. Mutating tool calls are checked fail-closed with three outcomes (allow / deny + rule text + missing facts / escalate-insufficient-facts). Trace monitors handle obligations. Audit logs record rule ID + version + facts + decision in tamper-evident storage outside the agent's control.
7. **Evaluate**:
   - Retrieval: recall@k on gold rule IDs.
   - Answers: per-rule attribution.
   - Actions: pass^k + Completion-under-Policy + process-compliance (false-pass rate).
   - Robustness: perturbation and adversarial users (τ-break).
   - Scorer correctness: audit benchmarks first (BAR).

**Determinism vs retrieval decision rule**

| Rule characteristic | Treatment |
|---|---|
| Gates a side-effecting action (refund, data access, payment, config change) | Executable binding + pre-execution gate (required) |
| Numeric thresholds, fees, eligibility, tax/benefit calculations | Executable (DMN/ASP/Catala/SMT); LLM only extracts facts |
| Ordering/temporal ("verify identity before…", "notify within 72h") | Temporal monitor / trace predicate |
| Interpretive or subjective ("reasonable", "appropriate conduct") | Retrieval + LLM judgement with citation + human escalation |
| Advisory Q&A about what a rule says | Retrieval + grounded answer with per-rule citations |
| Version- or jurisdiction-dependent | Hard metadata filter before any retrieval or evaluation |

### Gaps
- Real costs (authoring hours per executable rule, maintenance under amendment) are reported only anecdotally: Munich Re's 1-2 hours saved per impairment and Catala's lawyer-programmer pairing. No systematic total-cost-of-ownership study exists.
- How to propagate amendments from source provisions to rule cards and executable bindings automatically (change impact analysis) is proposed (SAT-Graph RAG, ComplianceNLP's change monitoring) but not benchmarked.
