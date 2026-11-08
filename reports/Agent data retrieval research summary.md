# Compile Once, Serve Every Agent Exactly

The toolkit should be an open, Apache-2.0 **agent context compiler**. It is not a parser, a vector database, a graph database or a chat app. It turns heterogeneous documents, data and tool catalogs into three coexisting stores that share one spine of stable IDs, source spans, access-control lists (ACLs) and validity/version fields. The first is an **immutable raw-evidence store** with span-level provenance. The second is a **typed, snapshot-pinned database** that an LLM fills once at ingestion and agents query with exact predicates. The third is a **searchable layer of typed knowledge units**: concepts, topic pages, rule cards with executable bindings, procedures and articles. Agents reach all three through a small tool surface over MCP and a markdown file tree. Access is tiered: parameterized tools and a semantic layer first, guarded read-only SQL/Cypher second, hybrid lexical-plus-dense search third, and a labelled fallback to raw text last. Rules that gate actions are enforced outside the agent. The evidence for this shape is consistent across all five research reports. Models cannot supply determinism: "deterministic" settings vary accuracy **by up to 15% across runs** ([Atil et al.](https://arxiv.org/abs/2408.04667)). Materialized extraction beats chunk RAG on set questions: **50.9 vs 6.0 recall** on intersections ([QO-Bench](https://arxiv.org/abs/2606.04646)). Cheap structure beats elaborate LLM pipelines on indexing ([Mangla](https://arxiv.org/abs/2603.23533)). Stale or conflicting content, not weak retrieval, causes most policy failures ([HoH](https://arxiv.org/abs/2503.04800)). Mainstream research and coding agents (Codex, Claude Code, Cursor, deep research products) rent a hosted index and spend inference reading it. Independent audits find them weak where a compiled lake is strong. Only **39–77% of their cited claims are supported** ([Cited but Not Verified](https://arxiv.org/abs/2605.06635)), and citation sets from identical runs overlap below **0.02 Jaccard** ([Pykälä & Kaski](https://arxiv.org/abs/2610.26421)). So the toolkit should be the exact, citable, permission-aware backend those agents call, not a competitor to their search loop. Theory places the guarantees in the store, not the ranker. The data processing inequality, the hallucination lower bounds, normal-form theorems and conformal methods back the store layer. The access layer rests on bounds and empirical laws, so its parameters must be tuned on each team's own golden set. The open ground to own is an **engine-neutral record format**, **versioned and grounded extraction**, **cost-bounded incremental graphs**, **tools stored as data**, **end-to-end ACL sync** and a **neutral evaluation harness**.

*Evidence base and labels.* This summary consolidates five reports and two method catalogs (the "where to read more" map at the end lists them). The project's source catalog, `papers/manifest.csv`, has **2,570 rows across four research folders**: 967 for deterministic conversion, 824 for the knowledge base, 400 for information theory and 379 for research agents. Normalizing arXiv versions, DOIs and URLs reduces this to about **2,567 distinct sources (1,791 paper rows and 779 web rows)**. **1,667 PDFs** are kept locally only and are rebuilt with `scripts/download_papers.py`. The first report, *Agent ready data lake toolkit*, predates the manifests, so its sources are cited inline but not counted there. The labels follow the source reports. **Independent** means measured by a party that did not build the winning system. **Author-reported** means from the method's own paper. **Vendor-reported** means from the seller or deployer, unaudited. **[P]/[S]/[I]** mark published theorems, the theory report's own sketches, and inferred mappings from a theorem to a toolkit method. Most 2026 sources are unreviewed arXiv preprints. Status is as of November 2026.

## One architecture reconciles five reports: three stores on one spine

### The three stores and why each exists

Each earlier report designed one part of the system. The data-lake report proposed a typed, versioned, permission-carrying intermediate representation on open formats. The deterministic-retrieval report froze LLM extractions into snapshot-pinned tables. The knowledge-base report compiled typed knowledge units behind a small tool surface. The research-agents report positioned all of it as a backend for external agents. The theory report showed why the raw store must stay. These designs fit together as three stores that divide the work by question type and share one spine.

**Store 1, raw evidence**, is immutable and content-addressed. It holds a source registry (`doc_id = sha256(bytes)`, URI, version, ACL) and a canonical document tree. The tree is a DoclingDocument-compatible superset with content-addressed element IDs, page, bounding box and character span (or time-code, cell range or commit SHA), parser and weight revision, and confidence. Theory makes this store non-negotiable. By the data processing inequality, no chunker, extractor or summarizer can add information about the source. Only a lossless representation is sufficient for every future question ([Polyanskiy & Wu](https://people.lids.mit.edu/yp/homepage/data/itbook-export.pdf)). A typed record is a sufficient statistic only for the questions its schema anticipated [I].

**Store 2, the typed deterministic database**, holds `FieldValue` rows and extracted tables. Each value carries `(doc_id, page, char_start, char_end, spec_id)`, a validation status (verified, auto-accepted, review-pending or rejected) and an extractor fingerprint. It also holds canonical entity tables with alias maps and mention tables, and statement-level relation tables with valid-time and transaction-time columns. A semantic model sits on top. All of this is published as immutable snapshots (Iceberg or DuckLake) that are tagged and protected from expiry. Two lower bounds back the choice of an external store over parametric memory. A calibrated model's closed-book error on arbitrary facts is at least the fraction of facts seen once in training ([Kalai & Vempala](https://arxiv.org/abs/2311.14648)). A $B$-bit model must lose every fact beyond roughly $B/\log M$ ([Nichani et al.](https://arxiv.org/abs/2412.06538)).

**Store 3, the searchable knowledge units**, shares one envelope across unit types. The envelope carries identity, provenance, applicability (status, `effective_from/to`, `supersedes`, jurisdiction, audience), governance (owner, verifier, authority tier, `review_due`), access (allow/deny principals, `synced_at`), change hashes for text, metadata and ACL, index-only retrieval aids, and usage counters. Six unit types carry bodies inside it. A **concept** is a SKOS entry with preferred, alternate and hidden labels, a definition with its span, and broader, narrower and related links. A **topic or entity page** is a set of atomic claims with verbatim spans plus a rendered narrative. A **rule card** holds modality, conditions, thresholds, exceptions, resolved cross-references, jurisdiction, effective dates and zero or more `bindings[]` (Cedar, Rego, DMN or ASP, each with tests and a sign-off flag). A **procedure** is a typed step graph with `when_to_use`, preconditions, tools, risk and escalation. An **article or FAQ** holds KCS fields or a question-answer pair. A **table record** points to rows in Store 2. **Tool records** sit beside these units. They hold the JSON schema, expanded description, synthetic queries, examples, side effects, auth scope and typed edges such as "tool X writes entity type Y". They live under the same ACLs and lineage. Deferred tool search cut tool-definition context by about 85% in Anthropic's own tests ([Anthropic](https://www.anthropic.com/engineering/advanced-tool-use)), and the data-lake report found no surveyed project that stores tools next to documents and entities.

```
 SOURCES  files (PDF, Office, HTML, email, sheets, audio/video, code) · SaaS connectors · databases
          MCP servers / OpenAPI specs (as tool sources) · public web via pluggable search_backend
     │    content hash + etag change detection │ separate ACL/identity sync (fail closed)
     ▼
 ┌─ STORE 1  RAW EVIDENCE (immutable, content-addressed) ────────────────────────────────┐
 │ source registry · canonical document tree (element IDs, page/bbox/char span/time-code,│
 │ parser + weights revision, confidence, license manifest)                              │
 └───────────────────────────────────────────────────────────────────────────────────────┘
     │  COMPILE  (the only place an LLM runs; memoized on extractor fingerprint; batch APIs)
     │  parse-route → classify → schema contract (LinkML) → cheapest adequate extractor
     │  → span grounding + validators → disagreement/conformal routing → human review
     │  → entity resolution → unit compilation (concepts, rule cards, procedures, pages)
     ├───────────────────────────────┬───────────────────────────────┬──────────────────────┐
     ▼                               ▼                               ▼                      │
 STORE 2  TYPED DB / SNAPSHOTS    STORE 3  KNOWLEDGE UNITS        TOOL RECORDS             │
 field values + spans + status    concepts · topic pages · rule   schema, expanded desc,   │
 entities, aliases, mentions      cards (+bindings) · procedures  examples, side effects,  │
 bitemporal statement tables      · articles/FAQs · table records reads/writes-entity edges │
 semantic model · Iceberg/DuckLake  envelope: status, validity, authority, owner, ACL, hashes│
     └──────────────┬────────────────┴───────────────────────────────┘                      │
                    ▼  VIEWS AND INDEXES (regenerable, tied to one snapshot)                │
   lexical BM25F + regex/trigram │ dense (+ question vectors; optional multi-vector/page    │
   images) │ structural: section tree, link graph, entity/statement graph (PPR)           │
   │ markdown file tree + ≤8–10 KB generated index │ semantic layer + verified queries      │
                    ▼                                                                       │
 AGENT ACCESS  MCP (stateless, snapshot handles) + CLI + Agent Skills export + file tree   │
   T1 parameterized tools / semantic layer → T2 guarded read-only SQL / typed graph tools  │
   → T3 hybrid search · read(range) · grep · related · define · find_procedure ·          │
     search_tools → T4 labelled fallback (raw text, cached web)                            │
   every call: ACL pre-filter · snapshot ID · total ORDER BY + PK tiebreak · re-slice span │
         │                                     │                                           │
         ▼                                     ▼                                           │
 ENFORCEMENT GATE (out of process)     CLIENTS: Codex, Claude Code, Cursor, deep research, │
 bindings on mutating tool calls →     custom agents (evidence-returning hand-offs)        │
 allow | deny + rule text | escalate                                                        │
 LIFECYCLE  content sync · permission sync · write-time gates · compile + review · lint ·  │
 gap mining → promote to schema · owner review · shadow re-extraction · ANN-recall + eval  ◄┘
```

### The ingestion and compilation pipeline

The pipeline merges the deterministic report's ten stages with the knowledge-base report's unit compilation. Every stage emits a frozen artifact keyed by its inputs, so rebuilding from cache costs zero model calls.

| Stage | What happens | Frozen artifact | Key evidence |
|---|---|---|---|
| 1. Register | Content-hash bytes; record URI, MIME, connector, ACL | `doc_id = sha256(bytes)` | Birthday bound; SHA-1 collisions are practical, so not SHA-1 ([SHAttered](https://shattered.io/static/shattered.pdf)) |
| 2. Parse | Per-page router: text-layer fast path for born-digital pages, compact VLM for scans, frontier repair only for charts and multi-page tables | Versioned IR keyed by doc hash + parser version | [PubTables-v2](https://arxiv.org/html/2512.10888v4); [OmniDocBench](https://github.com/opendatalab/OmniDocBench) |
| 3. Classify and locate | Page and document classes; extract only relevant pages | Page labels | Page retrieval added 16.8–24 points in industrial KYC ([Han et al.](https://arxiv.org/abs/2604.26462)) |
| 4. Schema contract | Sample → LLM proposes → human edits → freeze; LinkML generates Pydantic/JSON Schema (constrained-decoding subset), SHACL, PG-schema, DDL and a semantic README | Versioned contract plus alias and synonym tables | [Schema Contracts](https://arxiv.org/abs/2606.05415); [OntoGPT](https://pypi.org/project/ontogpt/0.3.2) |
| 5. Extract | Cheapest adequate method per field: native structure (XBRL, JSON-LD) → rules or synthesized code → span encoders → constrained LLM with evidence-first field order | Raw responses and records cached by fingerprint | [Evaporate](https://arxiv.org/html/2304.09433v3); [Chaganti](https://arxiv.org/abs/2610.00007) |
| 6. Ground and validate | Re-slice each evidence span; pinned NLI checker for derived values; type, arithmetic and reference rules | Validation results stored as data | [SafePassage](https://arxiv.org/abs/2510.00276); [LangExtract](https://github.com/google/langextract) |
| 7. Route to review | Disagreement between structurally different calls plus a version-keyed conformal threshold; humans see only failing fields | Versioned overrides | [ExtractConf](https://arxiv.org/abs/2606.24420); [conformal risk control](https://arxiv.org/abs/2208.02814) |
| 8. Resolve | Exact keys → probabilistic matching → LLM choice among blocked candidates → KB lookup; global clustering with a fixed pivot order | Entity IDs, alias map, match evidence | [SPIRES](https://arxiv.org/abs/2304.02711); [Bansal et al.](https://doi.org/10.1023/B:MACH.0000033116.57574.95) |
| 9. Compile units | Rule cards with citation closure, procedure IR, concept candidates, evidence-first pages; judge-and-repair; ambiguity flags to review | Units with `status` | [De Jure](https://arxiv.org/abs/2604.02276); [PAGED](https://arxiv.org/abs/2408.03630) |
| 10. Publish | Branch, run regression gates (gold-set negative flips, query-suite exact match), merge, tag snapshot; Merkle-root snapshot ID | Snapshot tag | [Iceberg](https://iceberg.apache.org/spec/); write-audit-publish |
| 11. Build views | Chunks, indexes, file tree, link graph, semantic layer, all from the snapshot | View version tied to snapshot | [NavTree](https://arxiv.org/abs/2610.06902) |

### Indexes: lexical first-class, dense validated, structure for free

Each chunk or unit carries a BM25F-weighted lexical representation (title, breadcrumb, identifiers, alternate labels, body). It also carries a dense vector over breadcrumb, summary and body, with generated questions held as separate vectors that point to the parent unit, plus optional multi-vector or page-image embeddings for slides and visual pages. Three structural views come for free from the parse. The section tree supports small-to-big expansion and `browse`. The typed link graph (cites, defines, exception_of, overrides, supersedes, subprocedure_of) supports citation closure and `related`. The entity and statement graph supports typed traversal and HippoRAG-style Personalized PageRank. A regex/trigram index anchored to the snapshot backs `grep`, following Cursor's commit-anchored design ([Cursor](https://cursor.com/blog/fast-regex-search)). Index-side enrichment never enters reader context, because attaching metadata to passages given to the model mostly *reduced* accuracy across 24,000 responses ([Zerhoudi et al.](https://arxiv.org/abs/2606.29645)). Approximate nearest-neighbour (ANN) search is treated as a service-level objective. Recall@k is measured against exact kNN on golden queries at every build. Exact kNN runs over pre-filtered candidate sets, because pgvector's HNSW post-filtering returned **about 4 rows** for a 10%-selective filter ([pgvector](https://github.com/pgvector/pgvector)), and graph indexes have no worst-case recall guarantee ([Indyk & Xu](https://arxiv.org/abs/2310.19126)).

### The agent access layer: choose queries, do not write them

| Tier | Tools | Determinism guarantee | Evidence |
|---|---|---|---|
| T1 Parameterized tools and semantic layer | Verified queries as tools (`tools.yaml`-style), metric × dimension × filter selection, `facts_about(entity, as_of)` | Same arguments and snapshot give identical rows; declines out-of-scope questions | Tool pack 0.939 vs 0.666 raw SQL on 3B–8B models (independent) ([Bogliolo](https://arxiv.org/abs/2608.22063)); semantic layer "fails by declining" (vendor) ([dbt](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026)) |
| T2 Guarded SQL and graph | Read-only SQL with schema injection, dry-run and repair; typed graph tools (`neighbors`, `path_between`, `community_summary`) before guarded Cypher | Non-deterministic generation; accepted query stored and re-executed | BIRD 83.40 vs BEAVER 10.8% ([BIRD](https://bird-bench.github.io/); [BEAVER](https://arxiv.org/abs/2409.02038)); CypherBench 61.6% ([ACL](https://aclanthology.org/2025.acl-long.438.pdf)) |
| T3 Hybrid search over units | `kb_search` (filters for type, jurisdiction, `as_of`, status), `kb_read(range)`, `kb_grep`, `kb_related`, `define`, `find_procedure`/`get_procedure`, `check_rules`, `search_tools`/`load_tool` | Retrieval reproducible per snapshot with frozen statistics and a primary-key tiebreak; generation is not | Five consolidated tools beat many connector tools ([Glean](https://docs.glean.com/administration/platform/mcp/create-mcp-servers); [Dropbox](https://dropbox.tech/machine-learning/vp-josh-clemm-knowledge-graphs-mcp-and-dspy-dash)) |
| T4 Labelled fallback | BM25 and exact kNN over raw text keyed by the same IDs; cached web via `search_backend` | Labelled approximate; logged and promoted into schema if it recurs | Router-plus-fallback 0.298 vs 0.268 for routing alone; agentic loop 0.240 at ~7× tokens ([DualGraph](https://arxiv.org/abs/2605.27164)) |

Every tool resolves principals from the MCP auth token and applies ACL pre-filters, intersected across all participants in the session. It returns snapshot-pinned handles, uses small pages with cursors, and offers concise and detailed formats. Results come back inline, not in files: file delivery dropped one grep harness **from 93.1 to 55.2** ([Is Grep All You Need?](https://arxiv.org/html/2605.15184v1)). The current MCP spec (2026-07-28) is stateless-first, with explicit handles, Multi Round-Trip Requests for clarification, `Mcp-Method`/`Mcp-Name` headers for gateway routing and a Tasks extension for long jobs ([MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28/)). Each of these maps onto a toolkit decision. The same semantics ship as a CLI and as an Agent Skills folder export, so file-native and tool-calling agents see one lake. The agent policy that ships with the tools is short. Decompose the question first. Run hybrid search with reranking. Read sections, not whole files. Stop on a rate-based rule. Re-search when the situation changes. Cite raw anchors that code validates. Abstain with a gap report when evidence is insufficient.

### Enforcement sits outside the agent

Retrieval cannot deliver compliance. Frontier agents reached only about **40% pass^1 even when handed the right policy documents** ([Sierra](https://sierra.ai/blog/tau-knowledge)). Compiled pre-call guards raised pass^10 from 0.227 to **0.500**, against 0.273 for putting the policy in the prompt ([ToolGuard](https://arxiv.org/abs/2507.16459)). Approval gates inside agent frameworks leaked side effects in 215 of 1,200 live runs, so the gate must run out of process ([Khan](https://arxiv.org/abs/2607.14166)). The gate reads the same rule records the knowledge base serves, so a rule card and its binding share one ID, version and owner. It returns three outcomes: allow; deny with the rule text and the missing facts; or "insufficient facts, escalate". Frontier models abstained correctly only **22–40%** of the time when facts were missing ([DeoGen](https://arxiv.org/abs/2610.38687)). Ordering and deadline rules run as trace monitors. Every decision is logged with rule ID, version, input facts and outcome.

### Lifecycle jobs keep the stores honest

| Job | Cadence | Output |
|---|---|---|
| Content sync | Webhooks; delta ~30 min; weekly full reconciliation with deletion safeguard | New, changed and deleted sources; hash-skipped no-ops ([Onyx](https://docs.onyx.app/admins/connectors/overview)) |
| Permission sync | Separate job, ~hourly plus change feeds; fail closed past a freshness threshold | Metadata-only ACL patches; ACL-lag metric ([Atlassian](https://support.atlassian.com/organization-administration/docs/how-connector-permissions-are-kept-in-sync/)) |
| Write-time gates | Every new or changed unit | SHA-256 + tuned MinHash dedup, version-chain detection, PII and hidden-text scan, required validity fields, source allow-list, contradiction check, quarantine of external text |
| Compile and review | After ingest | Units and extractions with confidence and ambiguity flags into review queues |
| Shadow re-extraction | On any model, prompt, schema or parser change | Field-level diff on a branch; merge only below a negative-flip threshold; recalibrate conformal thresholds |
| Lint | Nightly | Expired `review_due`, orphan concepts, dangling links, duplicates, contradictions, stale golden questions, facet exclusiveness and exhaustiveness |
| Gap mining and promotion | Weekly | Insufficient-context clusters, recurring fallback questions promoted into schema fields, `kb_propose` units consolidated under human approval ([Joren et al.](https://arxiv.org/abs/2411.06037)) |
| Index health | Every build | ANN recall@k vs exact kNN; Heaps-rate vocabulary growth; eval gates |

### What goes where

| Question or knowledge type | Store | Access path | Determinism guarantee |
|---|---|---|---|
| Count, group-by, "find all", multi-constraint filter, join | Typed DB | T1 tool or semantic layer → T2 guarded SQL | Byte-identical rows for same query, parameters and snapshot |
| Volatile facts (prices, statuses, balances) | Typed tables or live API, not indexed text | T1 tool | Exact per snapshot; live reads flagged as such |
| Multi-hop relational facts between entities | Typed statement graph (closed predicates, bitemporal) | Typed graph tools → guarded Cypher; PPR for ranked association | Exact for typed predicates and `as_of`; PPR is ranked |
| Definition, acronym, synonym | Concept unit (SKOS) | `define`, alias expansion | Deterministic lookup |
| Explanations, "how does X work", topics | Topic pages, articles | `kb_search` → `kb_read` | Retrieval reproducible per snapshot; generation varies |
| What a policy says, which clause applies | Rule cards with citation closure | `kb_search` with hard `as_of`/jurisdiction/status filters; `check_rules` | Filtering exact; interpretation by LLM with per-rule citations |
| Rule that gates an action, numeric threshold, eligibility | Executable binding on the rule card | Out-of-process gate on mutating tools | Deterministic three-outcome verdict, logged |
| How to do a task (SOP, runbook) | Procedure unit | `find_procedure` → `get_procedure(view)`; runtime for high-risk steps | Ranked retrieval; step state exact when a runtime enforces it |
| Table inside a document | Table record + typed rows | Search finds it; SQL filters it | Exact on rows |
| Related topics, themes, corpus-level summaries | Link graph, facet taxonomy, lazy community summaries | `kb_related`, `browse` | Ranked; summaries navigate, they do not answer |
| Which tool to call | Tool records | `search_tools` → `load_tool` | Ranked; ACL-filtered |
| "Where did this come from" | Raw evidence + provenance polynomial | `read(span)`; why/trust/count provenance by homomorphism | Exact re-slice against content hash |
| Out-of-schema question | Raw evidence | T4 labelled fallback | Approximate; logged for promotion |
| Open-world, external or recent facts | Public web | `search_backend` in cached, indexed or live mode | Untrusted, labelled; spotlighted |
| Agent-learned lessons | Proposed units | `kb_propose` | Not served by default until reviewed |

### Where the reports disagree, and which view this summary adopts

| Topic | Positions | Adopted view and why |
|---|---|---|
| Default chunking | Data-lake report cites recursive 512-token chunks beating semantic ones (69% vs 54%) ([Vecta](https://www.runvecta.com/blog/we-benchmarked-7-chunking-strategies-most-advice-was-wrong)); knowledge-base report prefers heading-first, atomic tables and steps, 256–512-token merges, no overlap | **Structure-led, heading-first chunking**, because the domain studies closest to policies and SOPs favor it ([StrucChunk](https://arxiv.org/abs/2610.26313); [dos Santos et al.](https://arxiv.org/abs/2604.04948)). Size is a tuned parameter: theory derives no optimum for 256–512 |
| LLM contextual enrichment | Data-lake report: optional LLM context for high-value corpora; knowledge-base report: a free breadcrumb prefix matches it under strong retrievers | **Breadcrumb prefix by default**; contextual retrieval only if it beats the prefix on the deployed retriever ([Mangla](https://arxiv.org/abs/2603.23533)) |
| Query router | Data-lake report: a question-type router is a core component; deterministic report: pre-retrieval routers cannot predict needs that appear only after searching ([Coverage Illusion](https://arxiv.org/abs/2605.27220)); knowledge-base report: fixed hybrid beat rule-based adaptive routing ([arXiv 2606.21553](https://arxiv.org/abs/2606.21553)) | **Routing by tool surface plus a cheapest-first cascade** that escalates on empty or insufficient results. Tool descriptions tell the agent which store answers which question shape. A classifier is a hint, not a gate |
| Role of graphs | Data-lake report: HippoRAG2 as default graph path, lazy communities; deterministic report: closed-vocabulary statement graphs for exact Cypher; knowledge-base report: graphs for "related topics", with compiled graphs accuracy-neutral under a strong harness ([RAGFlow/ECNU](https://arxiv.org/abs/2610.41172)) | **Canonical typed, bitemporal node and edge tables in the lake** for exact queries. PPR and community summaries are optional views kept only if they beat the flat hybrid baseline |
| Storage and search backend | Data-lake report: Lance + Iceberg/DuckLake with DuckDB; deterministic report: DuckDB + DuckLake or Postgres, Iceberg + Nessie/lakeFS at scale; knowledge-base report: Postgres + pgvector + full-text as reference, OpenSearch to scale | **Canonical data on open table formats** (DuckLake on one node, Iceberg at scale) with Lance for vectors and blobs. The search engine is a replaceable view. Postgres full-text is not true BM25 (ParadeDB adds BM25 under AGPL) ([ParadeDB](https://github.com/paradedb/paradedb)), so the BM25F requirement must be checked against the chosen engine |
| Embeddings vs grep | Research-agents report: coding agents dropped embedding indexes for grep; knowledge-base report: hybrid is mandatory | **Lexical and grep first-class; dense as a validated view over the same snapshot.** Embeddings still help concept questions with no seed identifier and weaker models ([arXiv 2608.01507](https://arxiv.org/abs/2608.01507); [arXiv 2610.33958](https://arxiv.org/abs/2610.33958)) |
| Semantic-layer study label | Data-lake report labels the 100-question study (arXiv 2604.25149) vendor-run (Cube); deterministic report labels it independent | **Treat it as vendor-affiliated.** Its direction agrees with AtScale (+20 to +31 points) and dbt, both vendor-run, so the conclusion holds while the effect size stays uncertain |
| Extraction drift | Data-lake report cites **26.5% of 2,064 re-extracted values changing** across model versions ([arXiv 2606.00994](https://arxiv.org/pdf/2606.00994)); deterministic report says no study measures churn under successive commercial versions | **One pipeline measurement exists; no systematic study does.** It stays a known unknown |
| Fusion, LIMIT, voting, round counts, conformal | Earlier reports used RRF, said LIMIT "proved" a bound, used cross-call agreement, fixed two to three rounds, and one conformal threshold per field type | **The theory report's narrower statements win** (see the nine corrections below), because they state the assumptions the earlier claims omitted |

## The decisive evidence, layer by layer

The tables keep each source report's labels. Where a number comes from an interested party the label says so. Comparisons across papers are not head-to-head unless stated.

### Parsing: small specialists win single pages, frontier models win multi-page, and charts and grounding still break

| Finding | Number | Label |
|---|---|---|
| Sub-10B document VLMs lead OmniDocBench v1.6 | PaddleOCR-VL-1.6 96.34, MinerU2.5-Pro 95.75 vs Gemini 3 Pro 92.91, GPT-5.2 86.59, Marker 78.44 ([OmniDocBench](https://github.com/opendatalab/OmniDocBench)) | Maintainer conflict (OpenDataLab builds MinerU) |
| Text-layer structure models beat frontier LLMs on tables | TATR 0.980 vs Gemini 3.1 Pro 0.924 GriTS (cropped); POTATR 0.965 page-level; frontier ahead only on multi-page tables (+0.354) ([PubTables-v2](https://arxiv.org/html/2512.10888v4)) | Benchmark authors |
| Cost spread | POTATR ~$47 per million pages vs $15,000–36,680 for frontier models; olmOCR-2 ~$178 per million on H100 ([POTATR](https://arxiv.org/html/2606.09788v2); [HF blog](https://huggingface.co/blog/ocr-open-models)) | Author |
| Enterprise failure modes | Most specialized parsers below 6% on charts; single-pass VLMs below 10% on visual grounding; content faithfulness tops out near 90% ([ParseBench](https://arxiv.org/html/2604.08538v2)) | LlamaIndex-authored |
| Robustness to skew | PP-StructureV3 table TEDS falls 79→25 while robust VLMs hold ([Real5-OmniDocBench](https://arxiv.org/abs/2603.04205)) | Independent |
| Images beat lossy Markdown for scans | Receipts 87.5% from images vs 46.5% via Markdown ([Berghaus et al.](https://arxiv.org/html/2509.04469v1)) | Independent of vendors |
| Throughput favors routing | Marker no-OCR 23.7 pages/s, Docling 2.1, MinerU 0.54 on one B200 ([Marker](https://github.com/datalab-to/marker)) | Vendor |
| Generative parsers fail silently | Nougat loops on 1.5% of pages; SmolDocling 958 parse failures; one report of GPT-5.5 "systematically" altering financial values ([PubTables-v2](https://arxiv.org/html/2512.10888v4); [Needl.ai](https://needl.ai/technical-notes/benchmarking-pdf-extraction-tools)) | Mixed; the last is a single-document vendor note |

Parse once, freeze the output, keep bounding boxes, and route by page. Markdown cannot be the stored truth, because it discards boxes and provenance.

### Extraction: decompose, constrain, ground, and expect drift

| Finding | Number | Label |
|---|---|---|
| Hard-domain extraction ceiling | F1 ≈0.85 on simple corpora, 0.51–0.66 on legal, finance and healthcare ([UDA-Bench](https://arxiv.org/abs/2510.27119)); best relation F1 72.33, DocETL relation F1 41.51 ([Doc2DB-Bench](https://arxiv.org/abs/2608.08459)) | Independent |
| Wide schemas collapse | 51% valid JSON across 12,867 fields; 0% on a 369-field 10-K schema; provider structured-output modes lowered validity to 37% ([ExtractBench, Contextual AI](https://arxiv.org/abs/2602.12247)) | Independent |
| Long documents drop records | Value F1 87.9 short vs 27.9 over 50 pages ([ExtractBench, LlamaIndex](https://arxiv.org/abs/2607.29677)) | Vendor-run |
| Cite-the-segment beats layout models on line items | LMDX 72.09 vs LayoutLMv3 24.51 F1 ([LMDX](https://arxiv.org/html/2309.10952v2)) | Author |
| Grounding gates cut hallucination | SafePassage up to 85% fewer hallucinations; DeBERTa checker beats a GPT-4.1 grader at ~1/2,000 cost ([SafePassage](https://arxiv.org/abs/2510.00276)); clinical grounding removed 14.59% of LLM positives ([Mahbub et al.](https://arxiv.org/abs/2604.06028)) | Author |
| Encoders never emit malformed spans | GLiNER zero malformed outputs vs up to 27% invalid for small generative models ([Chaganti](https://arxiv.org/abs/2610.00007)) | Independent |
| Synthesized code is cheapest | Evaporate-Code+ $39 vs $5,157 per 10,000 documents ([Evaporate](https://arxiv.org/html/2304.09433v3)); yet least accurate on complex documents in UDA-Bench | Author / independent |
| Absence needs its own value | Two sessions agreed on 94.1% of data points but 77.2% when information was not reported ([Jensen et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC11706374/)) | Study authors |
| Field specification beats model choice | Typed field definitions shaped quality "far more" than three frontier model families ([EviStreams](https://arxiv.org/abs/2609.27418)) | Author |
| Model lifetimes are short | Median 538 days from publication to retirement ([Wolfrath et al.](https://arxiv.org/abs/2609.04699)) | Study authors |

Constrained decoding guarantees syntax, not correctness. Order fields as evidence quote, optional reasoning, then value. Give every field an explicit null reason. Never depend on re-running a model to reproduce the database.

### Schema, entity resolution and query interfaces: statistics decide structure, LLMs decide meaning

| Finding | Number | Label |
|---|---|---|
| Keys from profiling, not the LLM | Removing statistical key/FK inference costs 2.1–6.8 exact-match points ([Schema Contracts](https://arxiv.org/abs/2606.05415)) | Author |
| LLMs invent poor relations | Best non-taxonomic relation discovery F1 0.078 ([LLMs4OL 2024](https://arxiv.org/abs/2409.10146)) | Independent challenge |
| Matching recall is the ceiling | MRR 0.86 but recall 0.36–0.54 on a 700-attribute standard ([Magneto](https://arxiv.org/abs/2412.08194)) | Author |
| IDs from lookups, never recall | 98/100 correct GO IDs via ontology grounding vs 3/100 by prompting ([SPIRES](https://arxiv.org/abs/2304.02711)) | Author |
| Small matchers are nearly as good | Within 4.4% of GPT-4 at 3,899× lower cost ([AnyMatch](https://arxiv.org/abs/2409.04073)) | Author |
| Semantic layers add more than model swaps | +17–23 points from a 4 KB semantic document ([arXiv 2604.25149](https://arxiv.org/abs/2604.25149)); +20 to +31 points across seven LLMs ([AtScale](https://www.atscale.com/blog/semantic-layer-text-to-sql-accuracy/)); 0% on "too many hops" questions ([dbt](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026)) | Labels disputed / vendor / vendor |
| Ontologies help most at runtime | GPT-4 16.7% on raw SQL → 54.2% over an ontology-mapped graph → 72.55% with query check and repair ([Sequeda et al.](https://arxiv.org/abs/2311.07509); [Allemang & Sequeda](https://arxiv.org/abs/2405.11706)) | As labelled in source reports |
| Enterprise text-to-SQL is fragile | BEAVER 10.8%; gold errors in 52.8% of BIRD Mini-Dev and 62.8% of Spider 2.0-Snow ([Jin et al.](https://arxiv.org/abs/2601.08778)) | Leaderboards / expert re-annotation |
| Generated graph queries trail SQL | CypherBench 61.6% (Claude 3.5 Sonnet), under 20% below 10B; CypherGuard repair to 94.68% ([CypherGuard](https://arxiv.org/html/2610.41755v1)) | Benchmark authors / author |
| Raw SQL tools are injectable | A read-only-wrapped reference Postgres MCP server accepted `COMMIT; DROP SCHEMA public CASCADE;` ([Datadog](https://securitylabs.datadoghq.com/articles/mcp-vulnerability-case-study-SQL-injection-in-the-postgresql-mcp-server/)) | Independent |

Determinism comes from persisting and re-executing accepted queries, never from regenerating them. Uber treats ~5% run-to-run variation in QueryGPT as noise ([Uber QueryGPT](https://www.uber.com/blog/query-gpt/)).

### Graphs: worth it for multi-hop and global questions, only with typed predicates and bounded cost

| Finding | Number | Label |
|---|---|---|
| Reranked vector RAG ties graphs on facts; graphs win reasoning | Fact 60.92 (vector + rerank) vs 60.14 (HippoRAG2); complex reasoning 53.38 HippoRAG2; summarization 64.40 MS-GraphRAG ([GraphRAG-Bench](https://arxiv.org/html/2506.05690)) | Independent |
| Token cost spans 1× to hundreds of × | HippoRAG2 ~1,008 prompt tokens; MS-GraphRAG local 38,707 and global 331,375 (the paper elsewhere says ~4×10⁴); ~1.15× to ~377× vector RAG | Independent; internal inconsistency noted |
| Indexing cost is the top complaint | LightRAG >757M tokens vs 62M for naive RAG on HotpotQA ([arXiv 2609.10239](https://arxiv.org/pdf/2609.10239)); LazyGraphRAG indexes at ~0.1% of GraphRAG ([Microsoft Research](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)) | Preprint / vendor |
| Published wins shrink under fair evaluation | LightRAG's 66.70% win rate fell to 39.06% ([arXiv 2506.06331](https://arxiv.org/abs/2506.06331)) | Independent |
| Open predicates block exact queries | 966 relation types for 981 edges ([KGGen](https://arxiv.org/pdf/2502.09956)); GraphRAG edges carry only a free-text description ([GraphRAG dataflow](https://github.com/microsoft/graphrag/blob/main/docs/index/default_dataflow.md)) | Author / documentation |
| Closed vocabularies fix it | EDC 0.956 precision vs 0.724 for CESI ([EDC](https://arxiv.org/pdf/2404.03868)); entity resolution removed ~40% of nodes and relations and improved four Graph-RAG methods ([DEG-RAG](https://arxiv.org/abs/2510.14271)) | Author |
| Extractors lose a third of facts | MINE recoverability ~66% (KGGen) vs ~48% (GraphRAG) ([KGGen](https://arxiv.org/pdf/2502.09956)) | Author-built benchmark |
| Compiled structures are accuracy-neutral under a strong harness | Uncompiled BM25/grep baseline 91.0% on FRAMES; wikis, RAPTOR and graphs cut query tokens 38% ([RAGFlow/ECNU](https://arxiv.org/abs/2610.41172)) | Vendor-run |

Graphs belong as portable node and edge tables in the lake, with bitemporal append-and-invalidate edges ([Graphiti](https://help.getzep.com/graphiti/graphiti/overview/)) and lazy community computation. Kuzu's archiving in October 2025 shows why graph engines should be replaceable accelerators ([The Data Quarry](https://thedataquarry.com/blog/from-kuzu-to-ladybug/)).

### Indexing and chunking: structure and a free prefix carry most of the gain

| Finding | Number | Label |
|---|---|---|
| Structure-led chunks dominate legal retrieval | Character recall@8 48.18% vs 23.59%; chunking explains 73–88% of the gain ([StrucChunk](https://arxiv.org/abs/2610.26313)) | Author |
| Hierarchical splitting beats curated Markdown | 94.1% vs 91.3% (curated) and 86.2% (naive); 33-point gap on table questions ([dos Santos et al.](https://arxiv.org/abs/2604.04948)) | Study authors |
| Expensive chunkers rarely pay | Significance-tested study up to 1M documents ([Caspari et al.](https://arxiv.org/abs/2608.16586)); semantic chunks fragment to ~43 tokens ([Vecta](https://www.runvecta.com/blog/we-benchmarked-7-chunking-strategies-most-advice-was-wrong)) | Independent |
| Free prefix ≈ LLM enrichment under strong retrievers | Title-chain prefix +23.8% MRR@5 ([Yang](https://arxiv.org/abs/2608.00824)); enrichment within equivalence margins under a strong embedder or reranker ([Mangla](https://arxiv.org/abs/2603.23533)) | Study authors; Mangla preregistered |
| Contextual retrieval | Top-20 failures −35%, −49% with BM25, −67% with rerank, ~$1.02 per M tokens ([Anthropic](https://www.anthropic.com/news/contextual-retrieval)) | Vendor |
| Summary trees navigate, not answer | RAPTOR 48.8 F1 vs 57.0 for plain dense ([HippoRAG 2](https://arxiv.org/abs/2502.14802)); a zero-LLM heading tree tied the best flat baseline ([NavTree](https://arxiv.org/abs/2610.06902)) | Independent (HippoRAG 2 table) / author (NavTree) |
| Boundaries affect maintenance | After real edits, fixed-size re-embedded 57–68% of a document vs 38–56% recursive ([Bian et al.](https://arxiv.org/abs/2610.31019)) | Study authors |
| Visual pages need images or captions | ColPali 82.7 vs 54.3 BM25-over-OCR; captions + hybrid + rerank 83.9 at ~1/3 storage ([arXiv 2509.15211](https://arxiv.org/abs/2509.15211)); ViDoRe v3 best 0.592 nDCG@5 ([HF blog](https://huggingface.co/blog/QuentinJG/introducing-vidore-v3)) | Study authors / benchmark authors |

### Retrieval and fusion: never drop the lexical channel, tune the fusion, validate the reranker

| Finding | Number | Label |
|---|---|---|
| Dense vectors miss combinatorial top-k sets | Every embedder below 20 Recall@100 on LIMIT vs BM25 93.6 ([LIMIT](https://arxiv.org/abs/2508.21038)); theorem holds only under margin or finite precision ([Okajima & Yoshida](https://arxiv.org/abs/2606.11780)) | LLM lab / theory correction |
| Keyword queries break vectors | Vector 11.7 vs keyword 79.2 NDCG@3 on keyword queries; hybrid + semantic rerank 43.8 → 60.1 ([Microsoft](https://techcommunity.microsoft.com/t5/azure-ai-foundry-blog/azure-ai-search-outperforming-vector-search-with-hybrid/ba-p/3929167)) | Vendor |
| Linear fusion beats RRF when tuned | BM25 0.3210 > small dense 0.3077; normalized linear 0.3423 > RRF 0.3233 ([Vespa](https://docs.vespa.ai/en/learn/tutorials/hybrid-search.html)) | Vendor tutorial |
| Rerankers matter most on hard queries but must be validated | BRIGHT 24.3 → ~46.8 nDCG@10 with multi-stage reranking ([DIVER](https://arxiv.org/pdf/2508.07995)); an MS MARCO cross-encoder reduced precision on a scientific corpus ([SciRet](https://arxiv.org/abs/2608.03860)) | Author / study authors |
| Query expansion hurts strong retrievers | "Strong negative correlation" between retriever strength and expansion gain across 11 methods and 24 retrievers ([Weller et al.](https://arxiv.org/abs/2309.08541)) | Study authors |
| Thesaurus expansion helps jargon | Up to +22.1% NDCG@10 over sparse baselines ([BMQExpander](https://arxiv.org/abs/2508.11784)) | Author |
| Tool retrieval is its own problem | All retrievers below 35% Completeness@10 on 43,215 tools ([ToolRet](https://arxiv.org/pdf/2503.01763)); expansion + Tool-Embed-4B 52.23 → 56.44 with rerank ([arXiv 2510.22670](https://arxiv.org/pdf/2510.22670)); Tool Search cut ~77K → 8.7K tokens and raised accuracy 49% → 74% ([Anthropic](https://www.anthropic.com/engineering/advanced-tool-use)) | Independent / author / vendor |

### Agent loops: a short, decomposed loop over files and a hybrid index

| Finding | Number | Label |
|---|---|---|
| Two rounds capture most loop gains | Two iterations captured 95% of five's gains in 5,000 questions ([arXiv 2606.21553](https://arxiv.org/abs/2606.21553)) | Study authors |
| Retriever and first move dominate | BrowseComp-Plus: GPT-5 55.9% with BM25, 70.1% with Qwen3 embedder ([BrowseComp-Plus](https://arxiv.org/abs/2508.06600)); tuned BM25 83.1% ([Pi-Serini](https://arxiv.org/abs/2605.10848)); clue decomposition 90.5% ([Question's Gambit](https://arxiv.org/abs/2609.14412)) | Benchmark authors / author |
| Agentic RAG is not free | ~3.3× input tokens, up to 3.6× cost; "neither … universally superior" ([arXiv 2601.07711](https://arxiv.org/abs/2601.07711)) | Study authors |
| Harness and delivery matter as much as retriever | Grep 93.1 vs ANN + rerank 83.6; same model 93.1 vs 76.7 across harnesses ([arXiv 2605.15184](https://arxiv.org/abs/2605.15184)) | Small single-benchmark study |
| Compiled markdown wiki matches production RAG | Guidance 99.2% vs 96.2%; evidence sufficiency 83.3% vs 59.8%; ~90 s vs 8–9 s per case ([Airbnb](https://arxiv.org/abs/2610.14428)) | Vendor-run, single study |
| Small always-loaded index beats on-demand skills | 8 KB index 100% vs 79% (invoked skill) and 53% (discretionary) ([Vercel](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals)) | Vendor-run |
| Deeper disclosure hurts | Two-level hierarchy dropped one harness 0.913 → 0.640 ([arXiv 2607.17598](https://arxiv.org/abs/2607.17598)) | Study authors |
| Stale instruction files override truth | 90.1% of choices followed a stale file ([arXiv 2610.30571](https://arxiv.org/abs/2610.30571)); context files add >20% cost without success gains ([arXiv 2602.11988](https://arxiv.org/abs/2602.11988)) | Study authors |
| Curated skills help, self-written ones hurt | +16.6 points curated; self-generated 8.1–11.5 points below no-skill ([SkillsBench](https://arxiv.org/abs/2602.12670)); 26.1% of community skills vulnerable ([Xu & Yan](https://arxiv.org/abs/2602.12430)) | Independent |
| Procedures need explicit structure | Exact-sequence match 0.656 → 0.333 from short to long procedures ([ProcBench](https://arxiv.org/abs/2410.03117)); gateway/flow extraction under 0.5 F1 ([PAGED](https://arxiv.org/abs/2408.03630)); procedure-as-unit +8.58 top-1 ([TSG Suggester](https://arxiv.org/abs/2609.35780)) | Independent / author |
| Memory is a KB written by agents | BM25 60.5 vs Zep 37.5, MemGPT 34.3, Mem0 32.6 on accurate retrieval ([MemoryAgentBench](https://arxiv.org/abs/2507.05257)) | Independent |
| Hand-offs lose evidence | 41.8% of delegated-search failures at the hand-off ([arXiv 2608.01507](https://arxiv.org/abs/2608.01507)); 84.7% of report errors originated at the orchestrator ([Hirsch et al.](https://arxiv.org/abs/2608.24306)) | Author |
| Long context is a working set | A single rival value multiplied loss 9–110× ([arXiv 2611.04169](https://arxiv.org/abs/2611.04169)) | Study authors |

### Quality, determinism and lifecycle: the knowledge itself is the failure point

| Finding | Number | Label |
|---|---|---|
| Inference is not reproducible | 80 distinct completions in 1,000 temperature-0 runs ([Thinking Machines](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)); KG extraction reruns overlapped at Jaccard 0.21–0.55 ([ATOM](https://arxiv.org/pdf/2510.22590)) | Vendor research / author |
| Query-time operators vary and cost | SemBench quality 0.59–0.73 with >100× cost spread ([SemBench](https://arxiv.org/abs/2511.01716)); persisted judgments let 3 of 8 queries run with zero LLM calls ([OCTOPUS](https://arxiv.org/abs/2610.32586)) | Independent / author |
| Raw confidence is a poor gate | Verbalized calibration error 0.53–0.94 ([Qian](https://arxiv.org/abs/2610.20417)); cross-call disagreement 99.1% accuracy at 80% coverage ([ExtractConf](https://arxiv.org/abs/2606.24420)); conformal ≥90% coverage at 9–13% rejection ([Shrestha & Kim](https://arxiv.org/abs/2603.00924)) | Independent / single author / author |
| Arithmetic checks catch semantic errors | Sum gate confirmed 933 of 934 testable sums ([TableVision](https://arxiv.org/abs/2610.17448)) | Author |
| One stale passage hurts | Llama-3.1-70B 89 → 73 ([HoH](https://arxiv.org/abs/2503.04800)); outdated evidence flipped 17–91% of correct answers, 66–75% when told to follow documents ([Stale-Document Poisoning](https://arxiv.org/abs/2609.31342)) | Benchmark authors |
| Validity filters beat recency ranking | As-of extraction plus version filter 83.5–87.0% vs 24.35% unaided ([Prior et al.](https://arxiv.org/abs/2605.23497)) | Study authors |
| Content cleanup moves outcomes | Salesforce agent "I don't know" rate 30% → under 10% after dedup and cleanup ([Salesforce](https://www.salesforce.com/news/stories/first-year-agentforce-customer-zero/)) | Vendor |
| Models believe wrong context | Adopted wrong retrieved content over a correct prior >60% of the time ([ClashEval](https://arxiv.org/abs/2404.10198)) | Benchmark authors |
| Poisoning is a write-path problem | Five passages → 90–99% attack success ([PoisonedRAG](https://arxiv.org/abs/2402.07867)); coordinated uploads: best ingest classifier 4.2% at 1% FPR vs 100% for a query-demand detector ([Coverage Is Not Containment](https://arxiv.org/abs/2608.16044)) | Independent / author |
| Outcome-only scoring hides violations | 80.1% of outcome passes were false passes ([CXBench](https://arxiv.org/abs/2610.25954)) | Benchmark authors |
| Executable rules work where crisp; compile rates mislead | Policy-as-logic 0.61–1.00 vs ≤0.38 policy-in-prompt ([Nair et al.](https://arxiv.org/abs/2608.11905)); NL-to-Rego 95.3% compile vs 50.3% strictly correct ([Gupta & Sreenivasamurthy](https://arxiv.org/abs/2609.24036)) | Author |
| Reprocessing is where costs run away | No checkpointing meant every run reprocessed every document ([Xebia](https://xebia.com/de/blog/versteckte-kosten-ki-dokumentenanalyse-produktion-databricks/)) | Independent practitioner |
| Judges need calibration | Judge–human κ 0.02 → 0.61 vs human–human 0.69 ([Shopify](https://shopify.engineering/building-production-ready-agentic-systems)); PPI on ~150–300 labels ([ARES](https://arxiv.org/abs/2311.09476)) | Company / author |

### Permissions: deterministic pre-filters on every row, synced separately and failing closed

| Finding | Number or statement | Label |
|---|---|---|
| Prompt defenses are probabilistic | Every retrieved chunk must be authorized for every principal, inside the engine ([Bhatt et al.](https://arxiv.org/abs/2509.14608)) | Microsoft Research position |
| ACLs must be projected per chunk; post-filtering is an anti-pattern | ([Azure](https://learn.microsoft.com/en-us/azure/search/search-document-level-access-overview); [Microsoft ISE](https://devblogs.microsoft.com/ise/?p=16628)) | Vendor guidance |
| Permission sync is the hard part | "Significantly harder than incremental sync of content" ([Truto](https://truto.one/blog/how-to-maintain-document-level-rbac-in-enterprise-rag-pipelines/)); Rovo hides results when sync is stale ([Atlassian](https://support.atlassian.com/organization-administration/docs/how-connector-permissions-are-kept-in-sync/)) | Practitioner / vendor |
| Leakage channels beyond ACLs | Membership inference in ~30 queries, under $0.02 per document ([Naseh et al.](https://arxiv.org/abs/2502.00306)); embedding inversion recovered 92% of 32-token inputs ([Vec2Text](https://arxiv.org/abs/2310.06816)); EchoLeak zero-click exfiltration, CVSS 9.3 ([The Hacker News](https://thehackernews.com/2025/06/zero-click-ai-vulnerability-exposes.html)) | Author; Vec2Text independently reproduced |
| Oversharing blocks deployments | 66% delayed or cancelled Copilot over SharePoint exposure ([CoreView](https://www.coreview.com/news/66-percent-of-enterprises-delay-microsoft-copilot)) | Vendor survey |
| Protocols cannot express document governance | MCP and A2A lack document-level governance ([arXiv 2606.31498](https://arxiv.org/pdf/2606.31498)) | Author |

Principals belong as indexed columns on every chunk, vector, node, edge, table row and tool record. Vectors are as sensitive as text. An immutable retrieval log records the query, principals, unit IDs with version hashes, the ACL decision, citations and model. Grep over materialized files needs per-principal views, which no report solved.

## Mainstream agents rent an index and read; the toolkit should be what they call

**No mainstream assistant embeds the web locally.** Codex's web tool answers by default from "an OpenAI-maintained index of web results" in a cached mode that OpenAI also justifies as reducing prompt-injection exposure ([Codex config basics](https://learn.chatgpt.com/docs/config-file/config-basic)). For code, Codex runs `rg` in a sandbox. Its harness contains no embedding or code index; the only ranked retrieval is a BM25 `tool_search` over tool metadata. Project knowledge arrives as concatenated `AGENTS.md` files capped at **32 KiB** ([openai/codex](https://github.com/openai/codex); [AGENTS.md guide](https://learn.chatgpt.com/docs/agent-configuration/agents-md.md)). Claude Code uses glob, grep and read with a read-only Explore subagent. Anthropic dropped a Voyage-embedding RAG prototype because agentic search "outperformed everything else by a lot", on "some internal benchmarks also, but mostly vibes" ([OfficeChai](https://officechai.com/ai/claude-researcher-explains-how-agentic-search-performed-better-than-rag-for-code-generation/)). Cursor is the strongest natural experiment. Semantic search gave **+12.5% offline accuracy but only +0.3% code retention online** ([Cursor](https://cursor.com/blog/semsearch)). Cursor then stopped computing embeddings and switched to a commit-anchored regex index, because frontier models had become good at grep ([Cursor forum](https://forum.cursor.com/t/what-do-you-think-about-cursor-removing-the-codebase-indexing-settings/165899)). GitHub Copilot keeps a server-side semantic index but measured only "2% less time without any change in quality" for its coding agent ([GitHub](https://github.blog/changelog/2026-03-17-copilot-coding-agent-works-faster-with-semantic-code-search/)). Windsurf/Devin's RL-trained SWE-grep subagents favor precision because "polluting the main agent's context hurts more than omitting some context" ([Cognition](https://cognition.com/blog/swe-grep)). Aider ranks a tree-sitter repo map with Personalized PageRank ([Aider](https://aider.chat/docs/repomap.html)).

The grep-over-embeddings verdict is conditional. Code benchmarks are saturated with identifiers, and localization drops "catastrophically" without naming hints ([arXiv 2604.16021](https://arxiv.org/abs/2604.16021)). A vector-index agent beat a grep-delegating planner on concept questions, 65.2% vs 46.2% ([arXiv 2608.01507](https://arxiv.org/abs/2608.01507)). Graph and embedding tools added 17–21 points for 1.7–4B models but only 4–5 at 32B ([arXiv 2610.33958](https://arxiv.org/abs/2610.33958)). Incremental index repair reproduced a full rebuild on only **13 of 24** changes ([CodeNib](https://arxiv.org/abs/2607.25431)). Cursor's own users reported the two remaining gaps: concept questions with no seed identifier, and agents grepping stale archives as "current product truth". A semantic view and validity metadata close exactly those gaps.

**Web and deep research products share one seven-stage pipeline.** They clarify or plan, fan out into many short keyword queries, hit a hosted index, let the LLM select, fetch and shrink pages just in time, iterate, then synthesize and cite. Gemini, Copilot and Perplexity search their own indexes. ChatGPT mixes its own index with scraped Google. Claude most likely uses Brave, by strong inference. Third-party APIs (Brave, Exa, Tavily) cost **$4–16 per 1,000 calls**, and grounding with Bing costs $35 per 1,000 ([PPC Land](https://ppc.land/microsoft-ends-bing-search-apis-on-august-11-alternative-costs-40-483-more/)). Gemini Deep Research runs ~80 queries and ~250k input tokens for $1–3, and its Max tier ~160 queries for $3–7 ([Gemini docs](https://aistudio.google.com/docs/deep-research)). Quality comes from two sources, and neither is a better embedding. The first is ranking evidence inherited from the engine. Navboost's 13 months of click data were found "equivalent to over 17 years of data on Bing" ([Mehta opinion](https://storage.courtlistener.com/recap/gov.uscourts.dcd.223205/gov.uscourts.dcd.223205.1033.0_3.pdf)). The second is persistent inference: token usage alone explains **80% of performance variance** on BrowseComp in Anthropic's tests ([Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system)). Embedding the web is not impossible. The research-agents report estimates about **$5M of GPU time** and 13 TB to 3.3 PB of vectors at Google's 2020 scale. The hard parts are the crawl, freshness, spam fighting and click signals.

The failures sit in evidence handling, which a compiled lake provides by construction. Links are valid more than 94% of the time, but cited claims are supported only 39–77% of the time. Citation fact-check accuracy drops about 42% as tool calls scale from 2 to 150 ([Cited but Not Verified](https://arxiv.org/abs/2605.06635)). Enumeration is weak (0.363 soft F1 on WANDR) ([arXiv 2608.14747](https://arxiv.org/abs/2608.14747)). Answers are unstable across identical runs. Poisoning works: one plausible false document caused 66–88-point accuracy drops ([DRNOISE](https://arxiv.org/abs/2607.17291)). Enterprise corpora are harder for these agents than the web. Microsoft's Researcher needed **30–50% more iterations** for equivalent coverage on enterprise queries ([Microsoft](https://techcommunity.microsoft.com/blog/microsoft365copilotblog/researcher-agent-in-microsoft-365-copilot/4397186)). Intranets lack the link graph and click log, and only about 10% of IBM's intranet formed a strongly connected core ([Fagin et al.](https://mccurley.org/papers/www2003/p641-mccurley.html)).

| Dimension | Rent-the-index-then-read (web research agents) | Compile-once (this toolkit) |
|---|---|---|
| Where cost is paid | Query time: 10–160+ searches, $1–7 and minutes per deep task | Ingestion: parsing, extraction, review; queries near-free |
| Exactness | Probabilistic; poor enumeration | Exact predicates on snapshots for operator questions |
| Provenance | URL plus span; pages rot and syndicate | Immutable span IDs re-sliceable by code |
| Permissions | Public web, domain allow/block lists | ACL pre-filters on every row |
| Determinism | Citation Jaccard <0.02 across runs | Identical repeat answers via snapshot pinning |
| Ranking signals | Links, clicks and spam systems inherited free | Must be manufactured: references, usage logs, owners, verification, validity |
| Best question | Open-world discovery of external or recent facts | "How many" (typed DB) and "what applies here" (knowledge units) |

**Positioning.** Treat these agents as clients. OpenAI's deep research API queries private stores through MCP ([OpenAI Cookbook](https://raw.githubusercontent.com/openai/openai-cookbook/main/examples/deep_research_api/introduction_to_deep_research_api.ipynb)), and Gemini's agent accepts `mcp_server` and `file_search` ([Gemini docs](https://aistudio.google.com/docs/deep-research)). The toolkit should serve the five loop primitives: search returning ranked snippets, open by ID, find in document, a notes store, and citation by span. It should ship a snapshot-tied lexical and regex index as a first-class tool and materialize a file tree with a small, generated, linted index. Authority and currency should be filterable fields. Hand-offs should return paths, unit IDs, spans and quotes, never summaries alone. Enumeration and counting should route to deterministic queries, and the tool descriptions should say so. Ingested external text should be treated as untrusted: spotlighting cut injection success from over 50% to under 2% ([Hines et al.](https://arxiv.org/abs/2403.14720)). Usage logs (opened, cited, succeeded, skipped, re-queried) are the private substitute for clicks. They should be normalized by exposure, because cumulative-advantage dynamics lock in early winners ([Price](https://garfield.library.upenn.edu/price/pricetheory1976.pdf)), and they stay an experiment until measured. When the toolkit needs the web, a pluggable `search_backend` with Codex-style cached, indexed and live modes keeps cost and injection exposure down. The lake can also serve as its own fixed-corpus research benchmark and training environment, in the BrowseComp-Plus mold ([Tongyi](https://arxiv.org/abs/2510.24701)).

## Theorems certify the store; bounds and tuning govern the access layer

The theory report's main finding is a split in epistemic standing. Rows about what to *store* and how to *gate* it are mostly backed by published theorems whose assumptions the toolkit can make true by construction. Rows about how to *rank* and how much to *read* are mostly bounds or empirical laws, and their parameters must be earned on a golden set. Nearly all theorem-to-method links are the theory report's inferred mappings [I], not claims by the theorems' authors.

| Backing | Design choices | Formal result |
|---|---|---|
| **Theorems** | Keep raw evidence; ground values to spans | Data processing inequality; sufficiency ⇔ DPI equality; only lossless representations are universally sufficient [S] ([Polyanskiy & Wu](https://people.lids.mit.edu/yp/homepage/data/itbook-export.pdf)) |
| | External typed store for long-tail facts; inverse lookups as indexes | Monofact hallucination bound ([Kalai & Vempala](https://arxiv.org/abs/2311.14648)); $B$-bit storage bound ([Nichani et al.](https://arxiv.org/abs/2412.06538)); ~2 bits/parameter measured capacity ([Allen-Zhu & Li](https://arxiv.org/abs/2404.05405)) |
| | Normalized canonical schema; repeated metadata only in views | BCNF/4NF ⇔ every position carries maximal information ([Arenas & Libkin](https://marceloarenas.cl/publications/jacm05.pdf)) |
| | Freeze extractions; pin snapshots; total ordering | Floating-point non-associativity; linear commit history; SQL/Lucene specifications ([Berenson et al.](https://arxiv.org/abs/cs/0701157); [PostgreSQL](https://www.postgresql.org/docs/current/queries-limit.html)) |
| | One provenance polynomial per answer | Semiring homomorphisms commute with positive relational algebra ([Green et al.](https://web.cs.ucdavis.edu/~green/papers/pods07.pdf)) |
| | SHA-256 content IDs, Merkle snapshot IDs, MinHash dedup | Birthday bound; MinHash unbiasedness and variance ([Broder](https://www.cs.princeton.edu/courses/archive/spring13/cos598C/broder97resemblance.pdf)) |
| | Fellegi–Sunter review band; conformal review thresholds; PPI judge calibration | ([Winkler](https://www.stat.cmu.edu/NCRN/PUBLIC/RLClassFiles/HW/Winkler1990.pdf); [Angelopoulos & Bates](https://arxiv.org/abs/2107.07511); [PPI](https://arxiv.org/abs/2301.09633)) |
| | Conflicts answered as certain answers | Consistent query answering; FO/P/coNP trichotomy ([Koutris & Wijsen](https://doi.org/10.1145/3068334)) |
| | Filter, never down-rank, superseded content | Diet-model zero-one rule ([Pirolli & Card](https://www.chi1995.chistatic.hosting.acm.org/proceedings/papers/ppp_bdy.htm)); passage weight scales with copies ([Tok-RAG](https://arxiv.org/abs/2406.00944)) |
| | Rule cards from normative text, not induced from data | Data is existential-conjunctive; rules need full first-order logic ([Frické](https://zenodo.org/record/904809)) |
| **Bounds, models and empirical laws** | Lexical channel always kept | Johnson–Lindenstrauss, margin and precision bounds ([Okajima & Yoshida](https://arxiv.org/abs/2606.11780)) |
| | BM25 with field weights | Fitted 2-Poisson model; BM25F combines fields before saturation ([Robertson & Zaragoza](https://doi.org/10.1561/1500000019)) |
| | Summaries and pages as navigation only | Rate–distortion converse; query-aware beats query-agnostic; strong DPI contraction (η unmeasured) ([Polyanskiy & Wu 2015](https://arxiv.org/abs/1508.06025)) |
| | Query-time compression | Information bottleneck: 21.5 EM with 12.7 words vs 14.7 with 517.6 raw words ([Zhu et al.](https://arxiv.org/abs/2406.01549)); V-information explains why views help bounded readers ([Xu et al.](https://arxiv.org/abs/2002.10689)) |
| | Short loops, verifiers first | Compounding per-step error ([Dziri et al.](https://arxiv.org/abs/2305.18654)); monotone stopping explains "a few rounds" but not the number two ([Ferguson](https://www.math.ucla.edu/~tom/Stopping/sr5.pdf)) |
| | Small index, `read(range)` | Marginal value theorem; information scent ([Charnov](https://doi.org/10.1016/0040-5809(76)90040-X)) |
| | Structure-led chunking | MDL boundary codes and head-to-head evidence; heading presence assumed |
| | Schema and taxonomy induction | MDL is an objective relative to an encoding ([Grünwald](https://arxiv.org/abs/math/0406077)); an LLM wiki is not a compression once parameters count (14,008% of raw size) ([Delétang et al.](https://arxiv.org/abs/2309.10668)) |
| | Long-tail coverage planning | Zipf, Heaps, Bradford, Lotka; exponents must be refitted per corpus ([Piantadosi](https://pmc.ncbi.nlm.nih.gov/articles/PMC4176592/)) |
| **Nothing** | RRF with k=60; 256–512-token chunk size; MMR; one-level progressive disclosure; SECI-style tacit-knowledge capture | Empirical defaults only; tune or measure |

### Nine corrections, folded into the recommendations

| # | Earlier claim or default | Correction | Recommendation now |
|---|---|---|---|
| 1 | LIMIT "proved" single-vector embedders cannot represent top-k sets | The bound binds only under a margin or finite precision; without them about 2k dimensions suffice ([Okajima & Yoshida](https://arxiv.org/abs/2606.11780)) | Keep the lexical channel for the empirical reasons (codes, IDs, negations, BM25 93.6 on LIMIT). In quantized stores, dimension and precision must grow with corpus size |
| 2 | Rank context by relevance (PRP) | PRP is optimal only for additive metrics; context assembly is a set problem ([Agrawal et al.](https://doi.org/10.1145/1498759.1498766)) | PRP for the first stage; budget-aware greedy coverage over sub-questions or claims for the final context |
| 3 | RRF k=60 as fusion default | No optimality theorem; tuned convex combination is normalization-robust ([Bruch et al.](https://arxiv.org/abs/2210.11934)) | Tuned linear fusion once a golden set exists; RRF only for unlabelled or score-drifting settings; run Lee's overlap test before adding a channel ([Lee](https://doi.org/10.1145/278459.258587)) |
| 4 | Cross-call agreement and self-consistency as validation | Correlated votes converge confidently to the wrong value; accuracy can be non-monotone in the number of calls ([SEP](https://plato.stanford.edu/entries/jury-theorems/); [Kim et al.](https://arxiv.org/abs/2506.07962)) | Structurally different calls (prompt, provider, OCR vs VLM); disagreement as a calibrated routing score; Dawid–Skene weights if voting; measure per-field error correlation ρ |
| 5 | One split-conformal threshold per field type | Guarantees are marginal and void after any extractor change; set coverage ≠ "accepted values are right" | Key calibration sets to the extractor fingerprint; recalibrate or use non-exchangeable conformal ([Barber et al.](https://arxiv.org/abs/2202.13415)); implement auto-accept as conformal risk control or FDR-controlled selection ([Jin & Candès](https://arxiv.org/abs/2210.01408)) |
| 6 | Pairwise matcher decisions as cluster IDs | Fellegi–Sunter optimality is pairwise; correlation clustering is NP-hard and pivot-dependent | Global clustering with a fixed pivot order (sorted record IDs); cutoffs from labelled pairs, not EM estimates |
| 7 | Trust HNSW defaults | Graph indexes have no worst-case recall guarantee ([Indyk & Xu](https://arxiv.org/abs/2310.19126)) | ANN recall@k against exact kNN is a build-time SLO; exact kNN below a benchmarked candidate count; full-precision rescoring |
| 8 | Score golden sets by accuracy | Binary grading makes abstention never optimal ([Kalai et al.](https://arxiv.org/abs/2509.04664)) | Explicit abstention penalty t/(1−t); report accuracy, error and abstention separately; include false and superseded statements |
| 9 | Bloom filters as "already seen" dedup checks | A false positive silently drops a *new* document (~0.82% at 10 bits/item, k=7) ([Broder & Mitzenmacher](https://www.eecs.harvard.edu/~michaelm/postscripts/im2005b.pdf)) | Bloom filters only as negative pre-filters; SHA-256 equality decides |

The theory report adds three smaller refinements that this summary adopts. "Temperature 0" should be documented as low-variance, not deterministic, and batch-invariant serving is worth enabling only for self-hosted shadow re-extraction. The fixed "two or three rounds" budget becomes a rate-based stopping rule: stop when marginal new claims per 1,000 tokens fall below the session average, or after k non-contributing reads, under a hard cap. Facets act as hard filters only when their values are exclusive and exhaustive, so null facets become an explicit `ALL` or `unspecified` value ([Satija](https://isko.org/cyclo/colon_classification)).

## Platforms converge on one pattern while licenses and churn set traps

**Convergence.** Every major document platform splits conversion from retrieval. They all parse to an intermediate table, classify, extract to a typed schema with confidence, validate with rules and human review, materialize governed tables, and expose a semantic layer with verified or trusted queries. Determinism comes only from the last two steps. Provenance varies. Databricks `ai_extract` v2.1 returns citations to text spans or bounding boxes ([Databricks](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_extract)), while Snowflake `AI_EXTRACT` returns strings without span citations ([Snowflake](https://docs.snowflake.com/en/sql-reference/functions/ai_extract)). No vendor publishes run-to-run variance for its extraction functions or accuracy for its agent query layer. Enterprise knowledge assistants (Glean, M365 Copilot, Gemini Enterprise, Rovo) share connectors with ACL and identity sync, hybrid indexes and query-time trimming, and they differ mainly in freshness and ACL strictness. Customer-service platforms (Agentforce, Fin, Decagon, Sierra) all pair natural-language procedures with deterministic guards and simulation tests. Salesforce's rule is "if you can express a decision as code, it should be written as logic" ([Salesforce Architects](https://architect.salesforce.com/docs/architect/fundamentals/guide/hybrid-reasoning-agentforce-builder-agent-script)). Outcome numbers are almost all self-reported. The UK cross-government Copilot trial reported 26 minutes a day saved, self-reported and without a control group ([GOV.UK](https://www.gov.uk/government/publications/microsoft-365-copilot-experiment-cross-government-findings-report/microsoft-365-copilot-experiment-cross-government-findings-report-html)).

| Price point (list, as published) | Range | Source |
|---|---|---|
| OCR | $1–2 per 1,000 pages (Mistral, Textract, DI Read, Google) | [Google](https://cloud.google.com/document-ai/pricing) |
| Layout parsing | $0.70 (Databricks simple) to $10 (Google, Azure) per 1,000 pages | [Databricks](https://www.databricks.com/product/pricing/ai-functions) |
| Schema extraction via API | $2.10–4.20 per 1,000 inputs (Databricks) to $40 (Reducto Deep Extract, BDA) and $70 (Textract Forms+Tables+Queries) per 1,000 pages | [Reducto](https://reducto.ai/pricing); [Bedrock](https://aws.amazon.com/bedrock/pricing/) |
| Self-hosted specialists vs frontier parsing | ~$47–178 vs $15,000–36,680 per million pages | [POTATR](https://arxiv.org/html/2606.09788v2) |
| One million pages, end to end (inference, not measured) | Parsing $50–200 self-hosted or $1,500–10,000 via APIs; extraction ~$2,000–70,000; human review dominant at ~10–20% of fields | Deterministic report estimate |
| Knowledge assistants | ~$20–50 per user per month plus metered credits (Glean, M365 $30, Gemini $21–30, Onyx $20) | [Glean](https://docs.glean.com/glean-enterprise-flex-pricing); [Office Watch](https://office-watch.com/2025/microsoft-365-copilot-business-ai-add-on/) |
| Per-outcome agents | Fin $0.99 per outcome; Agentforce Flex $0.10 per action; "resolution" defined differently by each vendor | [Fin](https://fin.ai/pricing); [CX Today](https://www.cxtoday.com/customer-engagement-journey-orchestration/salesforce-agentforce-contact-center/) |
| Web search for agents | $0.75–35 per 1,000 calls | [Perplexity](https://docs.perplexity.ai/getting-started/pricing); [OpenAI](https://developers.openai.com/api/docs/pricing) |

Consumption pricing makes agentic search itself billable, and a self-hosted lake with an MCP interface avoids that metering.

**Who builds which layer.** The two catalogs (about 470 and 460 entries) show a clear division of labor.

| Builder | Layer they own | Catalog evidence |
|---|---|---|
| Big tech | Parsing models and managed platforms; IT-ops procedures; production policy engines | 26 of 45 parsing entries are big tech or LLM labs; all 31 cloud-platform features are big tech or data platforms; Microsoft's troubleshooting-guide line; AWS Cedar and Automated Reasoning; IBM ToolGuard and policy-as-logic |
| LLM labs | Building blocks and agent conventions, mostly via engineering posts | Only ~20 of ~470 deterministic entries; Agent Skills (SKILL.md, now a Linux Foundation standard), context engineering, tool search, prompt caching, AGENTS.md; DeepMind's LMDX, UQE, LIMIT |
| Academia | The middle of the pipeline and the rigorous tests | 28 of 39 semantic-operator entries, 25 of 42 schema/ER entries, 21 of 39 KG entries; ~170 purely academic KB entries plus 73 co-developed; most independent tests of popular methods |
| Startups and data platforms | Commercial and glue layers | 21 of 22 IDP vendors; Instructor, CocoIndex, dlt, LlamaIndex, Unstructured, promptfoo; Snowflake, Databricks, dbt, Neo4j and Palantir own warehouse AI SQL and semantic layers |

**Licensing traps and churn.**

| Component | Trap | Source |
|---|---|---|
| MinerU | Custom license; commercial license above 100M MAU or $20M monthly revenue; attribution for hosted services | [MinerU LICENSE](https://raw.githubusercontent.com/opendatalab/MinerU/HEAD/LICENSE.md) |
| Marker/Surya weights | Modified OpenRAIL-M above $5M revenue or funding; competitor clause; remote restriction | [Particula Tech](https://particula.tech/blog/docling-vs-mineru-vs-marker-pdf-parser) |
| PyMuPDF; LayoutLMv3 weights | AGPL or commercial; non-commercial weights | [Particula Tech](https://particula.tech/blog/docling-vs-mineru-vs-marker-pdf-parser); [HF](https://huggingface.co/microsoft/layoutlmv3-base) |
| Graph servers | Neo4j Community GPLv3 single-instance; Memgraph BSL 1.1; FalkorDB SSPLv1; Kuzu archived | [ArcadeDB comparison](https://arcadedb.com/blog/open-source-knowledge-graph-graphrag-databases-compared/) |
| Search engines | Elasticsearch AGPLv3/SSPL/ELv2; ParadeDB AGPL; Weaviate and Meilisearch enterprise carve-outs | [Elasticsearch](https://github.com/elastic/elasticsearch/blob/main/LICENSE.txt) |
| RAG apps | Dify modified Apache with multi-tenant ban; Open WebUI custom; Onyx permission sync in paid EE | [Dify](https://github.com/langgenius/dify/blob/main/LICENSE); [Onyx](https://docs.onyx.app/admins/connectors/overview) |
| Connectors | Elastic connectors and Airbyte are ELv2: no permissive end-to-end source-ACL sync exists | [Elastic connectors](https://github.com/elastic/connectors); [Airbyte](https://github.com/airbytehq/airbyte) |
| Vendor churn | Glean bought Aryn and shut DocParse in five weeks; Coupa bought Rossum; ServiceNow bought Moveworks; Salesforce agreed to buy Fin for ~$3.6B; Dashworks shut three months after HubSpot's purchase; Amazon Q Business closed to new customers | [Aryn](https://www.aryn.ai/post/aryn-transition); [Trending Topics](https://www.trendingtopics.eu/salesforce-to-acquire-fin-ai-formerly-intercom-for-3-6-billion/); [Vantagepoint](https://vantagepoint.io/blog/hs/what-happened-to-dashworks-ai) |

The permissive default stack is Docling (MIT) plus PaddleOCR-VL (Apache-2.0) for parsing. Lance, DuckDB/DuckLake and Iceberg handle storage. Qdrant, Milvus, Vespa, OpenSearch (Apache-2.0) or pgvector (PostgreSQL License) serve as search views. MinerU and Marker ship as opt-in plugins, and a model-license manifest records every weight revision the toolkit downloads.

**Open gaps the toolkit can own.**

| Gap | Why it is open | Evidence |
|---|---|---|
| Open, engine-neutral record format | Every engine keeps its own state (GraphRAG parquet, LightRAG stores, Graphiti in Neo4j); proprietary intermediate schemas are where platform lock-in sits | Data-lake and deterministic reports |
| Versioned, grounded extraction | No surveyed library or catalog treats an extraction run as a versioned, diffable entity; DocWrangler users flagged "the need for better provenance tracking" | [DocWrangler](https://arxiv.org/abs/2504.14764); [arXiv 2606.00994](https://arxiv.org/pdf/2606.00994) |
| Cost-bounded incremental graphs | Community restructuring drives update cost; LightRAG 757M-token builds | [EraRAG](https://arxiv.org/pdf/2506.20963); [arXiv 2609.10239](https://arxiv.org/pdf/2609.10239) |
| Tools as data | Tool registries (SCOUT, MCP gateways) sit apart from documents and entities | [SCOUT](https://arxiv.org/abs/2608.23992) |
| End-to-end ACL sync | No permissive open implementation for Confluence, SharePoint, Drive and Slack | Knowledge-base report |
| Neutral evaluation harness | Every vendor benchmark ranks its author first (OmniParseBench, ParseBench, Nanonets) | [Datalab](https://www.datalab.to/benchmarks); [LlamaIndex](https://www.llamaindex.ai/blog/parsebench) |

Two uncertainties shape the bet. Demand for an open agent data format is inferred from product direction and complaint patterns, not measured. Hyperscalers bundling "good enough" pipelines are the main adoption risk, so exporters into their platforms (Azure AI Search, Unity/Databricks, Snowflake, Bedrock, Neo4j) are a survival feature. The data-lake report also leaves one check open: whether a Linux Foundation or MCP effort already targets a unified document, graph and tool format. That check belongs at the start of the build.

## One roadmap in six gated phases

The data-lake report's four phases, the deterministic report's risk-ordered build and four invariants, and the knowledge-base report's six phases reconcile into one sequence. The order follows a single principle: build what is hard to retrofit first. That means evaluation, then lineage, then permissions, then the two typed stores, then optional layers that must beat the baseline. Phases 3 and 4 can run in parallel tracks. The exit criteria are design targets drawn from the reports, not sourced findings, and each is chosen to be measurable in CI.

| Phase | Scope | Exit criteria (all must pass) |
|---|---|---|
| **0. Evaluation first** | Golden sets of a few hundred questions before any prompt work, mixing factoid, count/filter, procedure lookup, policy applicability with as-of dates, overview, ID lookup and insufficient-evidence questions. Golden documents with expected records and spans (≈50 expert-vetted per type, per [Nilenso](https://blog.nilenso.com/blog/2026/05/18/evals-before-prompts-building-an-llm-ocr-for-kyc/)). Candidate pools from BM25, dense, alias and browse paths. Judge from a different model family than any reranker. Abstention-aware scoring. Repeated-run harness | Flat hybrid baseline recorded with accuracy, error, abstention, tokens and dollars; paired tests chosen; judge κ against humans measured |
| **1. Evidence store and spec core** | Record spec v0.1 with conformance tests; DoclingDocument superset; SHA-256 registry; per-page parse router with ≥3 adapters; license manifest; structure-led chunks with breadcrumb; BM25F + dense + reranker; MCP/CLI `search`/`read(range)`/`grep`; retrieval log; snapshot-tied indexes | 100% lossless round-trip of a 1,000-document mixed corpus; ≥95% of born-digital elements carry page, bbox and char span; routed parse within 2 points of the best backend at ≤30% of all-VLM GPU time; a 1% edit re-embeds ≤2% of chunks; laptop install to 100 queryable PDFs in <10 minutes; ANN recall@k vs exact kNN above threshold |
| **2. Permissions, applicability and tools as data** | ACL principals on every row with separate, fail-closed sync; envelope fields; version chains; hard validity, jurisdiction and status filters; SHA-256 + MinHash dedup; canonical selection; `ToolRecord` ingestion from MCP and OpenAPI with `search_tools`/`load_tool`; MCP 2026-07-28 server with snapshot handles and Tasks | Zero leaks across ≥500 adversarial cross-tenant probes covering search, grep, SQL and tool search; ACL revocation propagates within one sync cycle; temporal probes pass with no superseded unit in default top-k; ≥80% tool-context reduction on ≥1,000 tool records with Completeness@10 ≥ BM25 baseline |
| **3. Typed deterministic database** | LinkML contracts and generators; `ExtractionSpec` registry; grounded extraction with null reasons; QA ladder (validators → span re-slice and NLI → structurally diverse disagreement + version-keyed conformal risk control → review → branch merge); entity resolution with fixed-pivot clustering; semantic layer, parameterized tools, guarded SQL; provenance polynomials | The four invariants: zero-call rebuild with byte-identical checksums; identical result sets on repeated question-suite runs; 100% of answer spans re-slice to stored quotes; merges blocked when gold-set negative flips exceed threshold. Plus ≥95% of values grounded; every value traces to a `spec_id`; schema changes re-extract only affected fields; shadow-diff agreement rates published |
| **4. Knowledge units and enforcement** | SKOS concepts and `define`; rule cards with citation closure; procedure IR with SKILL.md and Mermaid renderers; FAQ and table records; executable bindings through review, tests and solver analysis; out-of-process gate with three outcomes; procedure runtime enabled per model | Rule-ID recall and procedure top-5 retrieval beat Phase 1; pass^k and process false-pass rate improve in simulation without collapsing task success; every gate decision logged with rule ID and version |
| **5. Graph and navigation layers (each must earn its place)** | Closed-vocabulary, bitemporal statement graph; typed graph tools before guarded Cypher; optional PPR path; lazy communities under a token budget; markdown tree with ≤8–10 KB index; facet taxonomy where coherence passes; evidence-first pages for high-traffic concepts | Each layer kept only if it beats Phase 1–4 on accuracy or tokens at acceptable latency. On GraphRAG-Bench: within 1 point of reranked vector RAG on facts and within 2 points of the best graph method on reasoning; median graph-path tokens ≤1.5× vector RAG; index-build tokens ≤10% of MS-GraphRAG; a 1% update costs ≤3% of a full build; typed tools answer ≥90% of held-out graph questions without free Cypher |
| **6. Closed loop, interoperability and governance** | Lint, contradiction audits, gap mining, fallback-to-schema promotion, `kb_propose` with consolidation; exposure-normalized usage signals behind an eval gate; spec v1.0; exporters to Iceberg REST catalogs, DataHub/OpenMetadata, Neo4j/AGE, Azure AI Search, Bedrock, Unity/Snowflake; public neutral harness; foundation submission | Gap backlog shrinking and insufficient-context rate falling; lossless round-trip of lineage, ACL and `spec_id` through ≥4 external backends; published dollars-per-page at 10M pages; ≥2 independent organizations reproduce harness results; ≥10 non-founding committers |

### Consolidated design defaults

| Area | Default |
|---|---|
| Truth | Raw bytes and the canonical tree are the truth; chunks, records, pages, embeddings and file trees are regenerable views |
| Parsing | Docling text-layer path for born-digital pages; PaddleOCR-VL for scans; images, not Markdown, for invoices and receipts; frontier models only for multi-page tables and validation failures |
| Extraction | Native structure → synthesized code for templated families → encoders → constrained LLM with evidence-first fields; chunked multi-pass for lists; explicit null reasons |
| Validation | Deterministic checks first (types, arithmetic, keys, entropy-based FD checks); span re-slice; disagreement as routing; version-keyed conformal risk control; humans on rejected fields only |
| Identity | SHA-256 content IDs; Merkle-root snapshot IDs; entity IDs from lookups; persisted alias maps and clusters |
| Versioning | Full extractor fingerprint on every row; no floating model aliases; write-audit-publish branches; tagged snapshots |
| Chunking | Heading-first, atomic tables/steps/FAQ pairs, size tuned, no overlap; page units for slides |
| Enrichment | Breadcrumb prefix always; per-document summary; filtered generated questions as separate vectors; LLM context only if it wins |
| Retrieval | BM25F + dense + domain-validated reranker; tuned linear fusion; hard pre-filters on ACL, status and validity; parent expansion and citation closure; greedy coverage for final context |
| Access | Small stable tool surface; parameterized tools first; inline, paginated results; one level of disclosure; small generated, linted index; cache-friendly prefixes |
| Loop | Decompose first; rate-based stopping with a hard cap; evidence-returning hand-offs; code-validated citations; abstain with a gap report |
| Governance | Filter superseded content; authority tiers; allow-listed and signed sources; quarantine and spotlight external text; demand-anomaly monitoring; immutable retrieval log |

### Defaults to avoid

| Avoid | Reason |
|---|---|
| Markdown as stored truth; semantic, LLM or late chunking by default; chunk overlap | Loses boxes and provenance; independent studies favor structure ([Caspari et al.](https://arxiv.org/abs/2608.16586); [Bennani & Moslonka](https://arxiv.org/abs/2601.14123)) |
| Query-time LLM operators as the system of record; "temperature 0 is deterministic" | Variance and cost on every query ([SemBench](https://arxiv.org/abs/2511.01716)) |
| Free text-to-SQL or text-to-Cypher as the primary interface; raw SQL MCP servers | BEAVER 10.8%; injection risk |
| RAPTOR or GraphRAG as the backbone; open-predicate graphs for exact queries | Independent losses; untyped edges |
| Propositions as the primary index; vector-only retrieval | Weak in reproduction; LIMIT and keyword-query failures |
| RRF k=60 as a fixed default; trusting HNSW defaults; post-filtered ANN on selective filters | Corrections 3 and 7; pgvector ~4 rows |
| Same-model self-consistency votes; one conformal threshold reused across versions; Bloom filters as dedup | Corrections 4, 5 and 9 |
| Dozens of per-source tools; multi-level skill hierarchies; large always-loaded instruction files; results delivered as files | Tool confusion; 0.913 → 0.640; 90.1% stale obedience; 93.1 → 55.2 |
| Policy-in-prompt as the only control on actions; gates inside the agent process | ToolGuard; 215 of 1,200 leaked side effects |
| Recency decay instead of validity filters; post-retrieval ACL filtering; nullable facets used as filters | Stale-document flips; ACL anti-pattern; Ranganathan canons |
| Auto-published, model-written skills, rules or pages; fine-tuning facts into weights | SkillsBench; fine-tuned new facts raise hallucination ([Gekhman et al.](https://arxiv.org/abs/2405.05904)) |
| Plain-accuracy scoring; BM25-only gold pools; same-family judges | Correction 8; pooling bias and circularity |

## Known unknowns worth running as experiments

Every report closes on the same caveat. The components have evidence, but the assembly does not. The experiments below consolidate the gaps across all five reports, and several can run on the toolkit's own logs.

| Unknown | Why it matters | Experiment |
|---|---|---|
| Same agent over raw documents vs the structured lake | Tests the whole thesis; nobody has run it | Fixed corpus, one deep research agent, raw-doc MCP vs lake MCP, nugget-scored answers, repeated runs, cost and stability reported |
| End-to-end accuracy of a database built by LLM extraction from heterogeneous documents | No public benchmark measures it | Golden question suite with exact-result scoring over a lake built from mixed sources |
| Extraction drift across model versions | One pipeline saw 26.5% of values change; no systematic study; no vendor publishes run-to-run variance or calibration curves | Shadow re-extraction under successive versions with batch-invariant serving; field-level churn by type |
| Layered knowledge base vs flat hybrid baseline | No independent study shows the full layered design beating a strong flat hybrid on heterogeneous enterprise content | Phase 5 gates as a published ablation |
| Per-field error correlation ρ between extraction calls | Decides whether disagreement or voting helps | Two prompts and two providers on the same documents |
| Monotonicity of search yield; MVT stopping vs fixed caps | The stopping rule assumes non-increasing yield | Log per-round new-claim yield; A/B the rate rule against fixed budgets |
| Contraction η of LLM summarizers | The argument against deep summary trees is an unmeasured bound | QA-based distortion across summary depths |
| Zipf, Heaps and Bradford parameters of enterprise corpora | Long-tail cost estimates assume α≈1 | Fit per corpus at ingest |
| Usage logs as ranking signals for agents | Click substitutes are untested on private corpora; lock-in risk | Exposure-normalized signals with exploration slots behind an eval gate |
| Graph incremental cost at scale | Graphs must stay bounded under updates | 1%-update cost vs full build on a living corpus |
| Grep over materialized files under ACLs | Per-principal views unsolved | Prototype per-principal file trees; leak probes |
| Tool-record retrieval and poisoning | Colliding tools hurt more than noise; retrieved descriptions are an attack vector | ToolRet subsets plus poisoned-description drills |
| Demand for an open agent data format | Inferred, not measured | Track adoption of exporters and spec conformance |
| Theory gaps | No theorem for when RRF beats its best input; no worst-case theory for filtered graph ANN; no conformal guarantee for multi-field arithmetic dependencies; no bound linking RAG error to singleton rate and recall; no temporal-validity RAG theory; MDL never tried on LLM-extracted records; no distribution of top-two logit gaps for extraction outputs | Publish measurements from the toolkit's logs to turn inferred mappings into tested ones |

## Where to read more

| Section here | Detailed report and section |
|---|---|
| Bottom line, open gaps, record model | *Agent ready data lake toolkit.md*: "A reference architecture: an open agent-context compiler"; "Everyone owns a piece; nobody owns the format" |
| Parsing, licensing | *Agent ready data lake toolkit.md*: "Small document VLMs beat pipelines, but charts and grounding still break"; *Deterministic retrieval data conversion.md*: "Parsing: small specialized models beat frontier LLMs on single pages at 1/300th of the cost" |
| Extraction, schema, entity resolution, graphs | *Deterministic retrieval data conversion.md*: "Text to typed records…", "Schemas, entities and graphs…"; *Agent ready data lake toolkit.md*: "Graphs pay off only for multi-hop and corpus-level questions", "Schema engineering solved syntax but not semantics or versioning" |
| Compile-once pipeline, query interfaces, quality gates, enterprise IDP | *Deterministic retrieval data conversion.md*: "Extract once, query exactly…", "Agents should choose queries, not write them", "Quality gates, versioning and provenance…", "Enterprise platforms and vendors converge on one seven-step pattern", "A blueprint that makes determinism a testable property" |
| Knowledge units, rules, SOPs, lifecycle, KB platforms | *Searchable agent knowledge base construction.md*: "Concepts, rules and procedures each need their own unit, index and access path", "Stale, duplicated and conflicting content…", "Platforms have converged on one pattern…", "Blueprint: a knowledge-unit compiler…" |
| Indexing, agent loops, file trees | *Searchable agent knowledge base construction.md*: "Structure-led chunks, a free prefix and tuned hybrid retrieval…", "Agents search best with a short loop over files plus a hybrid index" |
| Codex, Claude Code, Cursor, deep research, positioning | *How AI research agents retrieve information.md*: "Nobody embeds the web locally…", "One pipeline runs from fan-out to citation…", "Coding agents abandoned embedding indexes for grep, with conditions", "Web research and the user's lakes solve opposite problems", "Ten design implications for the toolkit" |
| Theory cross-walk and corrections | *Information theory of agent retrieval.md*: "One table maps every method to its formal status", "Twenty-four design changes the theory implies", "Open theoretical gaps worth testing" |
| Method inventories by developer | *Deterministic retrieval methods catalog.md* and *Searchable agent knowledge base methods catalog.md*: "Methods from LLM labs and big tech", "Method families at a glance" |
| Sources | `papers/README.md` and `papers/manifest.csv`; PDFs rebuilt by `scripts/download_papers.py` |

## Conclusion

Taken together, the five reports move the problem from models to contracts. The variables that moved outcomes most were structural, not model choice. A 4 KB semantic document mattered more than switching frontier models. Typed field definitions mattered more than the extractor. Parameterized tools let 3B models match much larger ones. Validity filters mattered more than better rankers. Harness and result delivery mattered as much as the retriever. The theory report explains why. Guarantees attach to things the toolkit can fix by construction: retained sources, pinned snapshots, fixed hashes and version-keyed calibration. Ranking and reading parameters can only be earned empirically. The durable asset is therefore the versioned contract: schema, alias tables, rule cards with bindings, procedure graphs, ACL mappings, golden sets and verified queries. Extractors, embedders and vendors will all be swapped within about two years.

The strategic implication is that the toolkit wins by being the layer everyone else lacks, not by out-searching Codex or out-parsing MinerU. Research agents bring query skill and persistence. Platforms bring connectors and compute. Neither brings exact typed answers, re-sliceable citations, permission columns, currency metadata or a neutral way to prove any of it. The fastest route to credibility is the experiment nobody has published. Take one fixed corpus and one research agent. Serve the corpus once as raw documents and once as a compiled lake. Run it repeatedly, with nugget scoring and costs reported. If the lake wins on completeness, faithfulness and stability at comparable cost, the thesis holds. If it does not, the phase gates say which layer to cut.
