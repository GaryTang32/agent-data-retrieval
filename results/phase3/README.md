# Phase 3 results: the typed deterministic database

> **Work in progress.** This page holds the 3A results (the metadata tables and the frozen
> count questions, Q1) and the table probes (S1–S3 and the MCP leg of D1), recorded on
> 20 November 2026 under version 2 of the metric definitions, with golden sets v0.1. The 3B
> extraction table and its golden set come later. No model was called for anything here.

**Verdict for 3A.**
- **Q1 holds.** `p3-typed` answers 27 of 27 gov and 26 of 27 research test count questions from the typed tables. `baseline-linear` answered 2 of 27 and 16 of 27. Gov's paired McNemar p is 6.0 × 10⁻⁸ and research's is 0.0020. Both accuracies are at least 0.90, and gov's p is below 0.05.
- **Q1 was close to certain by construction** (spec §10.2). The generated queries are the baseline's own, read back from the model cache. They already returned the gold records on 27 of 27 gov and 26 of 27 research items, and only the baseline's answering step, which read retrieved chunks, failed. So Q1 tests that the typed tables and the query compiler reproduce the record semantics of `golden/records.py`. It does not show a new ability to understand questions.
- **The one miss is the `also_in` wording problem** (§4.2). The model read "also cited by" as membership, while the frozen gold compares the whole `;`-joined string. The tables keep the raw string, so they reproduce the gold. The miss belongs to the generated query, not to the tables.
- **The table probes pass** (S1–S3, D1 MCP leg): 0 leaks in 400 leak probes, of which 300 were compared with a reference store. Fail-closed passed 90 of 90 per corpus, the SQL guard 120 of 120 per corpus, table equivalence 1,000 of 1,000 and applicability 51 of 51. The MCP leg found 0 leaks in 60 probes, and 44 of 44 handle replays were identical.

Design: [`docs/superpowers/specs/2026-11-20-phase3-design.md`](../../docs/superpowers/specs/2026-11-20-phase3-design.md).
Phase 2 results: [`results/phase2/README.md`](../phase2/README.md).

## What was run

- **No model calls.** Every command ran with `HF_HUB_OFFLINE=1`. The two `p3-typed` runs ran with `--max-calls 0` and recorded `calls` 0. The model cache (`.cache/llm`) gained no entry.
- **Cache inputs checked first.** `adr_eval.phase3.cache_inputs_unchanged` returned `[]` for gov and for research. The check covers the query-generation prompt (SHA-256 `249b0449466c…`) and the record-schema text (gov `1a88b8fce387…`, research `01c9cd8529b8…`), byte for byte as in the baseline runs. The message is captured from `generate_query` itself, without calling a model.
- **Scratch stores.** Everything ran on the Phase 2 copies under `.cache/store-p2/`. `.cache/store` and `.cache/index` were only read: no file under them changed during this task. The only writes to the scratch stores were one `adr acl sync` per store before the runs (Phase 2 freshness limit: one hour).
- **Caller.** The runs searched as `user:auditor`, who sees every document: 180 of 180 in gov and 245 of 245 in research.

| Store | Content snapshot | Tables id (promoted `tables/HEAD`) | Applicability overlay | ACL snapshot of the runs |
|---|---|---|---|---|
| `.cache/store-p2/gov` | `f002821f2cb3…` | `2678b8da96338df9f72e3be98aa66d24b24164c290a422bb177f7095a9e1d5f8` | `4c81d25fe905…` | `1ceb7924a52b…` (sequence 20, entries `053acb4a6d76…`) |
| `.cache/store-p2/research` | `97c415b1aa71…` | `62604e913378c76bbb41921faba17478584fe519870c7b54e53f48910dafd41a` | – | `6b4d68836f4e…` (entries `7f8fb0e62d37…`) |

The full manifest of each build is in its run's `compile.json` (under [`run-summaries/`](run-summaries/)).

## 3A: the tables

Each build is a set of write-once table files named by their SHA-256, plus a manifest whose SHA-256 is the tables id. Both builds were promoted through the merge gate (Task 6) with 0 flips on the v0.1 count questions: gov 38 of 38, research 35 of 35. **No row was rejected** in any table.

| Corpus | Table | Kind | Rows | Rejected | Null cells (reason) |
|---|---|---|---|---|---|
| gov | `fr_documents` | data | 167 | 0 | `effective_on` 56 (absent); `title_state` 5 (absent), 113 (not_applicable) |
| gov | `fr_cfr_refs` | data | 221 | 0 | – |
| gov | `fr_agencies` | data | 278 | 0 | `parent_id` 167 (absent) |
| gov | `fr_dockets` | data | 171 | 0 | – |
| gov | `agencies` | entity | 278 | 0 | – |
| gov | `cfr_parts` | entity | 221 | 0 | – |
| gov | `dockets` | entity | 171 | 0 | – |
| gov | `waterways` | entity | 1,320 | 0 | – |
| research | `papers` | data | 2,570 | 0 | `licence_id` 2,336 (absent); `year` 19 (absent) |
| research | `paper_authors` | data | 9,683 | 0 | `author_id` 2 (absent) |
| research | `authors` | entity | 7,417 | 0 | – |
| research | `licences` | entity | 34 | 0 | – |
| research | `venues` | entity | 1,098 | 0 | – |

### Entity clusters

Clusters form by exact normalised keys only (ruling P11). Each per-type override file is empty, and no override applies. "Source rows" counts the (entity, raw form, source, document) rows the clusters were built from. "Merged" counts clusters that join more than one raw form.

| Corpus | Type | Clusters | Singletons | Merged | Source rows | Largest clusters (key: forms, source rows) |
|---|---|---|---|---|---|---|
| gov | agencies | 3 | 3 | 0 | 278 | coast guard 1, 111; homeland security department 1, 111; federal communications commission 1, 56 |
| gov | cfr_parts | 39 | 39 | 0 | 221 | 33 cfr 165 1, 57; 33 cfr 117 1, 56; 47 cfr 73 1, 56 |
| gov | dockets | 157 | 157 | 0 | 171 | uscg-2022-0222 1, 4; mb 22-227 1, 3; mb 17-105 1, 2 |
| gov | waterways | 467 | 435 | 32 | 1,416 | atlantic intracoastal waterway 2, 14; gulf intracoastal waterway 2, 11; miami river 2, 9 |
| research | venues | 905 | 836 | 69 | 2,570 | arxiv 16, 878; sigir 15, 23; acl 12, 52; iclr 10, 54 |
| research | licences | 33 | 32 | 1 | 234 | cc-by-4.0 2, 53 ("CC-BY-4.0", "CC BY 4.0") |
| research | authors | 7,413 | 7,409 | 4 | 9,681 | inc 2, 4; anton troynikov 2, 2; han xiao 2, 2 |

[`entity-samples.json`](entity-samples.json) holds a seeded sample (seed 20261120) of 50 clusters per type for inspection, or every cluster when a type has 50 or fewer. It also holds the ten largest clusters of each type. These come from the builds' operator-only reports, which are never served to callers.

Known weak spots, all from the exact-key rule:
- **Authors:** "Inc." and "Inc.)" form the author cluster `inc`, and a stray closing bracket gives a second form of several names ("Anton Troynikov)"). The cause is author strings split on commas.
- **Venues:** brackets that are not balanced stay in some keys, so "arXiv preprint (TIB)" becomes `arxiv (tib`. It is kept apart from `arxiv` by design.
- **Waterways:** the key `general` comes from the state-grouped section § 117.140 General (California). Title parts that name cities or counties ("osprey", "stratford") also become waterway entities.

### Waterway links

[`waterway-links.json`](waterway-links.json) lists every drawbridge FR title, each linked to its 33 CFR 117 sections or marked unlinked with a reason. It uses the newest eCFR version (2026-06-26: 424 sections, 38 states). A title links to the sections that match it on (waterway key, state), one title to many sections.

- **Linked: 47 of 54** drawbridge titles. Linking against all three eCFR versions gives the same 47.
- **Unlinked (5): no matching heading.** 2023-06925 (Cheboygan River, MI), 2024-03455 (Reynolds Channel, NY), 2024-03462 (Sloop Channel, NY), 2026-01398 (Inside Thorofare, NJ) and 2026-01400 (a technical amendment that names no waterway).
- **Unlinked (2): state mismatch.** 2024-02084 and 2026-00932 are Atlantic Intracoastal Waterway titles in Florida. The key appears only in NC, SC and VA headings, so the state check refuses them.

## 3A: Q1, the frozen count questions

`p3-typed` (§10.1) runs on `count_filter` items only. The runner refuses it unless `--qtype count_filter` is given. For each item it generates the query with the baseline's prompt and schema, so the cache hits. It compiles the query (`from_gold_query`) to one `query_table` call over the corpus's main table (`fr_documents`, `papers`), as `user:auditor`. Each answer is scored exactly as Phase 0 scores it: number closeness, set equality. There is no answer call, no judge and no fallback to chunks.

```
adr acl sync --store .cache/store-p2/gov        # and research
adr-eval run gov --system p3-typed --split test --qtype count_filter --repeats 1 --max-calls 0
adr-eval p3-q1 runs/gov-p3-typed-test-20261120T200702 runs/gov-baseline-linear-test-20261113T094503
```

| Corpus | Items | `p3-typed` | `baseline-linear` (Phase 0) | b (typed only) | c (baseline only) | McNemar p (exact) |
|---|---|---|---|---|---|---|
| gov | 27 | **27 (1.000)** | 2 (0.074) | 25 | 0 | 6.0 × 10⁻⁸ |
| research | 27 | **26 (0.963)** | 16 (0.593) | 10 | 0 | 0.0020 |

Each run ended `complete` with 27 rows and `calls` 0. Gov was run a second time in a fresh process (`…T201428`). Its rows and `compile.json` were byte-identical.

**Every miss and its cause.**
- **`p3-typed`, 1 miss: `research-count_filter-033` (op `list`).** The generated query used `also_in__contains: "04_reading_synthesis_citation"` with `status: "downloaded"`, which is the membership reading. It returned 23 ids. The gold compares the `also_in` string exactly and holds 14 ids. The same generated query gives the same 23 over the records (`query_exec_match` false), so the tables answered the query correctly. The cause is the question's wording against the frozen gold. This is the baseline's one generated-query miss, as §4.2 predicted.
- **`baseline-linear`, 25 gov misses.** 21 were wrong and 4 abstained. In all 25 the generated query was right (`query_exec_match` true), so every miss came from the answer the model gave from retrieved chunks.
- **`baseline-linear`, 11 research misses.** All 11 were wrong answers from retrieved chunks. In 10 of them the generated query was right. The 11th is item 033 above.

**The `also_in` readings (§4.2)**, over the v0.1 items whose gold compares `also_in` exactly. The table gives the count under each reading; a `list` item counts its ids.

| Item | Split | Op | Wording | String (frozen gold) | Membership |
|---|---|---|---|---|---|
| research-count_filter-005 | test | count | "an also_in value of exactly …" (three topics) | 1 | 3 |
| research-count_filter-010 | test | list | "an also_in value of …" (two topics) | 2 | 2 |
| research-count_filter-012 | dev | count | "also cited by …" | 14 | 22 |
| research-count_filter-020 | test | count | "also cited by …" | 2 | 2 |
| research-count_filter-033 | test | list | "also cited by …" | 14 | 23 |
| research-count_filter-035 | dev | count | "also cited by …" | 2 | 8 |

For a value with several topics, membership here means every topic of the value is among the record's topics. Items 005 and 010 ask for the value "exactly", so the string reading is the question's own. Item 005 differs only under the membership reading, which its wording rules out. Among the items worded as membership, three differ: dev 14 against 22, dev 2 against 8, and test 14 against 23 (item 033). These are the three items of §4.2. The tables expose both readings. `also_in` keeps the raw string, so the frozen gold reproduces, and `also_in_list` holds the topics for the membership reading.

## S1–S3 and D1: the table probes (Task 7)

All probes ran on the scratch stores after a fresh ACL sync, with no model calls. Each set ran twice in fresh processes, and its results were byte-identical both times. The numbers below are the final ones, after Task 7's review round.

| Criterion | Probe set | Result |
|---|---|---|
| S1 leaks | 400 leak probes: gov 300, each compared with a reference store of the caller's documents; research 100 `user:ghost` probes, each denied F4 (the research manifest is public, so no directory user has a hidden row) | **0 leaks**, 0 invalid; 300 compared with a reference store |
| S1 fail closed | 90 per corpus (target: gov `fr_documents` row of `7d10ca547e80…`, research `papers` row of `3fbd836906a9…`) | **90 of 90** per corpus |
| S2 SQL guard | 120 statements per corpus (writes, DDL, ATTACH, PRAGMA, budget and other cases) | **120 of 120** per corpus refused with a fixed message or bounded, the database intact afterwards |
| S3 equivalence | 500 gov and 500 research `query_table` and `sql` calls over 20 views, each against a reference store | **1,000 of 1,000** identical |
| S3 applicability | 51 cases, with a scan of the log for the probe's statement | **51 of 51**; log scan complete |
| D1 (MCP leg) | a seeded 60 of the 400 leak probes, each through an `adr mcp` server of its caller (16 as `user:ghost`, all research); handle replays | **0 leaks**, 0 invalid; **44 of 44** replays identical, each naming the tables; 196 calls, 196 log lines |

The bench and tools stores hold no tables, and their empty checks pass.

## Files

- [`run-summaries/`](run-summaries/) holds the two `p3-typed` runs (`config.json`, `compile.json`, `report.json`, `report.md`, and the `q1-<baseline>.json` from `adr-eval p3-q1`) and the table probe summaries (`probes-tables-*`, `tables-7-checks`). Per-item rows, golden items and probe sets stay local in `runs/`. The Q1 files report a list answer by its length only.
- [`entity-samples.json`](entity-samples.json) holds the entity cluster counts, the largest clusters and the seeded samples of both builds.
- [`waterway-links.json`](waterway-links.json) holds the linked and unlinked drawbridge titles.
