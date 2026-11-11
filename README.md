# agent-data-retrieval

> **Status: work in progress.** This repository is under active development and is not
> ready for use. The `main` branch holds the research and the plan. The Phase 0 evaluation
> harness is being built on a working branch and is not merged yet. The toolkit itself
> (Phases 1–6 below) has not been started. Anything here may change without notice.

An all-in-one toolkit that turns unstructured documents and tools into a data lake that AI
agents can retrieve from deterministically, built on schema engineering and graph
engineering. It targets domain-specific and rare knowledge, where general-purpose search
is weakest.

## Vision

An agent that answers a question about a rule, a procedure or an obscure fact should get
the same, best-supported evidence every time, and be able to show where it came from.

Today most retrieval stacks are tuned for popular knowledge, return different results from
run to run, and cannot say which version of which document an answer rests on. This project
aims for the opposite: one open toolkit that compiles any raw material into versioned data
products, turns each question into a structured query over those products, and retrieves
from a pinned snapshot so that the same question on the same data always returns the same
result, with every answer traceable to a stored span.

## Objectives

| Goal | What it means |
|---|---|
| **G1 Compile** | From raw documents in any form, build the data products that make later search work: a data lake of evidence with hashes and character spans, typed tables, typed relations, searchable knowledge units (rules, procedures, concepts, FAQs) and tool records. |
| **G2 Query understanding** | From a user's input, produce the structured form that best matches the G1 data products: which store, which operation, which filters and entities, and as of which date. |
| **G3 Retrieval** | Deterministically retrieve the best related results from those products, with quality measured separately for domain-specific and rare knowledge. |

Two terms are used precisely:

- **Deterministic** means: identical question + identical data snapshot ⇒ identical
  results. This is guaranteed by construction (pinned snapshots, fixed tie-breaks, no
  language-model call inside retrieval) and tested on every run.
- **Best related result** cannot be proven, only measured. That is why the evaluation
  harness comes first: every later component is accepted only if it beats the recorded
  baseline on its track without breaking determinism.

## Plan

The roadmap runs from Phase 0 to Phase 6, and each phase is gated. The order follows one
principle: build what is hard to retrofit first. A phase is done only when its exit criteria pass in CI. The criteria are
design targets taken from the research, not results.

| Phase | Scope | Status |
|---|---|---|
| **0. Evaluation first** | Golden question sets over three corpora, an evaluation harness with five tracks (compile, query understanding, retrieval, determinism, end-to-end), and a recorded flat hybrid baseline (BM25 + dense). | **In progress** (see below) |
| **1. Evidence store and spec core** | Record spec with conformance tests, content-hash registry, per-page parse routing, structure-led chunks, hybrid search with reranking, `search` / `read` / `grep` tools, snapshot-tied indexes. | Not started |
| **2. Permissions, applicability and tools as data** | Access-control principals on every row, version chains, validity and jurisdiction filters, deduplication, tool records ingested from MCP and OpenAPI. | Not started |
| **3. Typed deterministic database** | Schema contracts, grounded extraction with span checks, entity resolution, a semantic layer with guarded SQL, zero-call rebuilds with identical checksums. | Not started |
| **4. Knowledge units and enforcement** | Concepts, rule cards with citations, procedure records, FAQ and table records, executable rule bindings behind review and tests. | Not started |
| **5. Graph and navigation layers** | Bitemporal statement graph with typed graph tools, markdown navigation tree, facet taxonomy. Each layer is kept only if it beats the earlier phases on accuracy or tokens. | Not started |
| **6. Closed loop, interoperability and governance** | Gap mining and audits, spec v1.0, exporters to external catalogs and graph stores, a public neutral harness. | Not started |

Phases 3 and 4 can run in parallel. The full roadmap with exit criteria is in
[`reports/Agent data retrieval research summary.md`](reports/Agent%20data%20retrieval%20research%20summary.md).

### Phase 0 status

Phase 0 is being developed on the branch `claude/magical-lamport-n94rs3` and will be merged
when its baseline is recorded and reviewed.

| Item | Status |
|---|---|
| Design spec and implementation plan | Written (on the working branch) |
| Evaluation harness `adr-eval`: corpora, chunking, BM25 + dense index, golden generation and verification, scoring, statistics, runner, reports | Built and tested (on the working branch) |
| Golden question sets v0.1 over three corpora (US government regulations, this repo's research, an open enterprise benchmark) | Generated and verified automatically (on the working branch) |
| Baseline recorded (RRF and linear fusion, all five tracks) | Not yet recorded |
| Judge agreement with human labels | Open: needs a human-labelled sample |
| Judge from a different model family than the generator | Open: needs a second provider |
| Human-vetted golden items | Open: items are model-drafted and code-checked only |

No retrieval results have been published yet. Nothing in this repository should be read as
a performance claim.

## What is in the repository

| Path | Contents |
|---|---|
| `reports/` | Five research reports, two methods catalogs, a combined summary and an HTML brief. Start with [`Agent data retrieval research summary.md`](reports/Agent%20data%20retrieval%20research%20summary.md). |
| `research_notes/` | Working notes behind the reports. |
| `papers/` | Catalog of about 2,570 sources (`README.md`, `manifest.csv`). The PDFs are kept local only; rebuild them with `scripts/download_papers.py`. |

## License

Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
