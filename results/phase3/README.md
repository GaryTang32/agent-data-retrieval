# Phase 3 results: the typed deterministic database

> **Work in progress.** These are the measured numbers for Phase 3 of the roadmap, recorded on
> 20 and 21 November 2026 under version 2 of the metric definitions, with golden sets v0.1 and
> the new gov-tables v0.1. Part 3A (metadata tables) made no model call. Part 3B (extraction
> from 33 CFR part 117) made 1,411 of the 1,500 model calls the user approved (§11), all in its
> model-call steps; every check after those steps, this write-up's included, ran from the cache
> with `--max-calls 0`.

**Verdict.** 13 of the 15 exit criteria of the design (§12) pass, with the thresholds fixed before any result. **Q2 and E1 fail.**
- **Typed tables (T1–T6).** Every table rebuilds byte for byte from the cache with zero calls, every one of 32,889 provenance spans re-slices to its stored quote, every one of 60,295 stored values names its spec, a spec change re-extracts only its own group, and the merge gate refuses a regression and keeps `tables/HEAD`.
- **Q1 passes.** On the frozen count questions, `p3-typed` answers 27 of 27 gov and 26 of 27 research test items from the metadata tables, against `baseline-linear`'s 2 of 27 and 16 of 27 (McNemar p 6.0 × 10⁻⁸ on gov). Q1 was close to certain by construction (§10.2): it shows that the tables reproduce the record semantics, not a new ability to understand questions.
- **Q2 fails on accuracy.** On the 97 test items of gov-tables v0.1, `p3-typed` scores 0.680, below the 0.80 bar. Its margin over `baseline-linear` (0.237) passes: +0.443 [+0.330, +0.557]. In 26 of its 31 misses the generated query equals the gold query: the table, built from the first extraction pass, disagrees with the second pass the gold was computed from. Which pass is right in those cases is not known.
- **E1 fails on two columns.** 99.1% of the non-null model values are grounded overall, but `seasonal` (94.6%) and `closed_periods` (89.9%) are below the 95% bar, which applies per column. The other seven columns are at 99.9% or 100%.
- **E2 passes.** The four required columns agree with the independent second pass at 0.921 to 0.979. Two unrequired columns agree less: `owner_or_agency` 0.797 and `closed_periods` 0.707.
- **Access (S1–S3, D1) passes.** No leak in 700 leak probes over `query_table` and `sql` (400 on the 3A tables, 300 on the 3B tables, 65 of them on hidden drawbridge rows), nor in 60 of the leak probes re-run through MCP on each build. `query_table` and `sql` each equal a store built from the caller's documents alone in 1,500 of 1,500 calls. 120 of 120 SQL attacks per corpus were refused or bounded, every fail-closed case returned nothing, and every log line carried its principals and the tables id.
- **Determinism (X1) passes.** Every Phase 3 run and probe set gave identical rows and results in two fresh processes, and the gov and research tables, entity tables included, built twice from the same snapshot, contracts and cache gave the same files and tables ids. Phase 2 retrieval is unchanged (constraint 2): one `p2-default` run per corpus is identical to its Phase 2 run.

Points that need care when reading these numbers:
- **The gov-tables gold is a model's reading.** It comes from the second extraction pass (ruling P9); no person checked it. Errors shared by both passes are invisible, and in a disagreement nobody knows which pass is right.
- **Q1 is by construction.** Its generated queries are the baseline's, read back from the cache, and already returned the gold records.
- **The research tables test little about access.** Their only document, the papers manifest, is public, so every caller sees all of it or (as `user:ghost`) none: its leak probes can only be ghost denials.
- **The tenants are synthetic**, as in Phase 2.

Design: [`docs/superpowers/specs/2026-11-20-phase3-design.md`](../../docs/superpowers/specs/2026-11-20-phase3-design.md).
Plan: [`docs/superpowers/plans/2026-11-20-phase3.md`](../../docs/superpowers/plans/2026-11-20-phase3.md).
Phase 2 results: [`results/phase2/README.md`](../phase2/README.md).

## What was run

- **Model calls only in 3B's model-call steps:** 1,411 budget units of the 1,500 approved, every transport attempt counted (see [the ledger](#model-call-ledger)). Everything else ran with `--max-calls 0` from the model cache `.cache/llm`, which held 12,010 files after the model-call steps and 12,010 at the end of this write-up. Nothing was downloaded: every command ran with `HF_HUB_OFFLINE=1`.
- **Scratch stores.** Everything ran on the Phase 2 copies under `.cache/store-p2/`. `.cache/store` and `.cache/index` were only read: no file under them changed in any task, and the SHA-256 of the sorted path, size and modification time of all 7,320 files (`923ca5f71744…`) was the same before and after Task 7b and this task.
- **One machine:** a 4-core Intel Xeon at 2.10 GHz, 15 GB of memory, Python 3.13.18.

| Store | Content snapshot | Tables HEAD, 3A | Tables HEAD, 3B (current) | Applicability overlay | ACL `entries_sha256` |
|---|---|---|---|---|---|
| `.cache/store-p2/gov` | `f002821f2cb3…` | `2678b8da96338df9f72e3be98aa66d24b24164c290a422bb177f7095a9e1d5f8` | `fec2a2b12e318fcba0c350edac2e61acdbcc3bdccaad8f8d08c9290014270230` | `4c81d25fe905…` | `053acb4a6d76…` |
| `.cache/store-p2/research` | `97c415b1aa71…` | `62604e913378c76bbb41921faba17478584fe519870c7b54e53f48910dafd41a` | (unchanged: 3B adds no research table) | – | `7f8fb0e62d37…` |
| `.cache/store-p2/bench`, `.cache/store-p2/toolret` | as in Phase 2 | no tables | no tables | as in Phase 2 | `e1ca0a6ae0f1…`, `3906197e26ef…` |

- **Facts.** The second extraction pass is the facts file `541f4c587ee9a271068604a4a12fbe5584cc74392ff431f29e7683b45916707b` in the gov store's tables directory. gov-tables v0.1 is drawn from it.
- **ACL.** Every store syncs from the committed directory and policy (`config/acl/`, `directory_sha256` `d83f6043cffc…`, `policy_sha256` `0e3024f237fc…`), and every sync gave the access entries above, the same as in Phase 2. An ACL snapshot id changes with every sync. The measured runs used these snapshots: the Q1 runs gov `1ceb7924a52b…` (sequence 20) and research `6b4d68836f4e…` (sequence 22); the Q2 `p3-typed` runs gov `aa92a84fcb17…` (sequence 21). The `baseline-linear` runs search with no ACL layer, as in Phase 0. Each probe summary records the snapshots of its store and of every reference store.
- **Callers.** Every `p3-typed` run searches as `user:auditor` (§10.1), who sees every document: 180 of 180 in gov and 245 of 245 in research. The probes call as the directory's users, `user:ghost` and malformed callers.
- **The parts:**

  | Part | What | Criteria | Section |
  |---|---|---|---|
  | 3A | Metadata tables for gov and research, entity resolution, the merge gate; `p3-typed` on the frozen count questions | Q1; T1–T4, T6 for the 3A build | [3A](#3a-metadata-tables-and-q1) |
  | 3B | Two extraction passes over 33 CFR 117, the drawbridge tables, gov-tables v0.1, `p3-typed` and `baseline-linear` on it | Q2, E1, E2, T1–T6 | [3B](#3b-extraction-from-33-cfr-117-and-q2) |
  | Access | Leak, equivalence, SQL guard, fail-closed and applicability probes on both builds; the MCP leg | S1–S3, D1 | [Access](#access-s1s3-and-d1) |
  | X1 | Every run and probe set twice in fresh processes; tables built twice; the Phase 2 regression | X1, constraint 2 | [X1](#x1-determinism) |

**To reproduce** (after the Phase 2 stores of `results/phase2/README.md`, and with the model cache; the commands that call a model are marked):

```
# 3A: metadata tables, promoted through the gate on the v0.1 count questions
adr tables build --store .cache/store-p2/gov --tables-for gov
adr tables gate --store .cache/store-p2/gov --candidate 2678b8da96338df9… --gold golden/gov/v0.1 --max-flips 0
adr tables build --store .cache/store-p2/research --tables-for research      # and its gate
adr acl sync --store .cache/store-p2/gov                                       # and research
adr-eval run gov --system p3-typed --split test --qtype count_filter --repeats 1 --max-calls 0
adr-eval p3-q1 runs/gov-p3-typed-test-<ts> runs/gov-baseline-linear-test-20261113T094503 --summary <file>

# 3B (model calls: the two passes, the golden phrasing, the Q2 runs)
adr tables extract --store .cache/store-p2/gov --generator claude_code_sonnet --max-calls 554
adr tables extract --store .cache/store-p2/gov --second-pass --generator claude_code_opus --max-calls 557
adr tables build --store .cache/store-p2/gov --tables-for gov --with-extraction --max-calls 0
adr-eval golden tables --gen --store .cache/store-p2/gov --facts 541f4c587ee9… --generator claude_code_sonnet --max-calls 137
adr tables gate --store .cache/store-p2/gov --candidate fec2a2b12e318fcb… \
    --gold golden/gov-tables/v0.1 --gold golden/gov/v0.1 --max-flips 0
adr-eval run gov --golden gov-tables --system p3-typed --split test --qtype count_filter --max-calls 100
adr-eval run gov --golden gov-tables --system p3-typed --split dev --qtype count_filter --max-calls 25
adr-eval run gov --golden gov-tables --system baseline-linear --split test --max-calls 100
adr-eval p3-q2 runs/gov-tables-p3-typed-test-<ts> runs/gov-tables-baseline-linear-test-<ts> --summary <file>

# Access probes (no model calls), each store after `adr acl sync`
adr-eval probes tables-leak gov --store .cache/store-p2/gov                    # and research
adr-eval probes tables-equivalence gov --store .cache/store-p2/gov            # research, bench; tools on .cache/store-p2/toolret
adr-eval probes tables-sql gov --store .cache/store-p2/gov                     # and research
adr-eval probes tables-failclosed gov --store .cache/store-p2/gov              # and research
adr-eval probes tables-applicability gov --store .cache/store-p2/gov \
    --tables fr_documents drawbridge_sections drawbridge_bridges
adr-eval probes tables-mcp gov --store .cache/store-p2/gov --also research=.cache/store-p2/research
```

With the cache in place, every command above can be rerun with `--max-calls 0` and gives the same files; the run-summary configurations record the exact arguments. The 3B commands with a cap are the ones that made calls in Task 11; from a cold cache the model may answer differently, because Claude Code does not pin temperature.

## Exit criteria

Thresholds as fixed in spec §12 (ruling P13). Q2's interval is the paired bootstrap of
`adr_eval.scoring.stats` (10,000 resamples, seed 20261108); McNemar is exact. Every number is
in the named file under [`run-summaries/`](run-summaries/).

| # | Criterion | Threshold (§12) | Result | Pass | Summary files |
|---|---|---|---|---|---|
| T1 | Zero-call rebuild | Every table rebuilt with `--max-calls 0` from the cache in a fresh process: byte-identical table files and tables id | gov 3A and 3B and research, each built twice in fresh `cp -a` copies with the tables directory removed: 22 gov and 11 research files, all byte-identical to each other and to the promoted builds; tables ids `2678b8da9633…`, `fec2a2b12e31…`, `62604e913378…` reproduced. Task 11 also rebuilt the 3B build in a `cp -a` copy (37 of 37 files unchanged) | **Pass** | `tables-12-checks/checks.json`, `tables-11-checks/checks.json` |
| T2 | Identical result sets | The 3A and 3B question suites and every probe set twice in fresh processes: identical rows and results | 5 of 5 question runs and 12 of 12 probe sets identical (see X1) | **Pass** | `tables-11-checks`, `tables-7b-checks`, `tables-12-checks` |
| T3 | Every stored value re-slices | 100% of provenance spans re-slice to the stored quote or field text | 32,889 of 32,889 spans of all 10 tables of the 3B build, including 15,162 of 15,162 model-value quotes | **Pass** | `tables-11-checks/checks.json` |
| T4 | Every value traces to a spec | 100% carry a `spec_id` (or structure provenance) | 60,295 of 60,295 stored values | **Pass** | `tables-11-checks/checks.json` |
| T5 | A spec change re-extracts only affected fields | Only that group's calls run; other cache keys and values unchanged | `test_a_spec_change_reextracts_only_its_group` passes | **Pass** | `tests/store/test_tables_extract.py` |
| T6 | The merge gate blocks regressions | Refused, and `tables/HEAD` unchanged | `test_gate_refuses_too_many_flips_and_keeps_head` passes. The real gate was used three times, each with 0 flips | **Pass** | `tests/store/test_tables_gate.py` |
| Q1 | Typed tables answer the frozen count questions | accuracy ≥ 0.90 on each corpus, and above `baseline-linear` with McNemar p < 0.05 on gov | gov 27/27 = 1.000 against 2/27, p = 6.0 × 10⁻⁸; research 26/27 = 0.963 against 16/27, p = 0.0020. 0 model calls | **Pass** (by construction, §10.2) | `gov-p3-typed-test-20261120T200702`, `research-p3-typed-test-20261120T200924` |
| Q2 | Typed tables answer the drawbridge questions | ≥ 0.80 accuracy, **and** the lower bound of the paired difference's 95% interval above +0.02 | Accuracy 66/97 = **0.680**. Difference against `baseline-linear` (0.237): +0.443 [+0.330, +0.557]; McNemar b = 47, c = 4, p = 2.4 × 10⁻¹⁰ | **Fail** (accuracy fails, margin passes) | `q2-gov-tables.json`, `gov-tables-*-20261120T23*` |
| E1 | Extraction is grounded | ≥ 95% grounded (re-slicing quotes); per column as §7.3 states, before ungrounded values are dropped | Overall 5,401 / 5,452 = 99.1%. `seasonal` 157/166 = **94.6%** and `closed_periods` 365/406 = **89.9%**; the other seven columns 99.9–100% | **Fail** (two columns) | `tables-11-checks/checks.json` |
| E2 | Extraction agrees with an independent pass | Reported for every column; ≥ 0.85 on `waterway`, `bridge`, `notice_hours`, `opens_on_signal` | `waterway` 0.979, `bridge` (draw set) 0.921, `notice_hours` 0.950, `opens_on_signal` 0.956. Unrequired: `mile` 0.998, `vhf_channel` 0.992, `seasonal` 0.972, `owner_or_agency` 0.797, `closed_periods` 0.707 | **Pass** | `tables-11-checks/checks.json` |
| S1 | No leak through tables | 0 leaks; 1,000 of 1,000 equivalent (probe minimums from §10.4: ≥ 300 leak probes) | Leak: 0 in 400 probes on the 3A build (300 compared with a reference store, 100 `user:ghost`) and 0 in 300 on the 3B build (all compared; 65 on hidden drawbridge rows). Equivalence: 1,000 of 1,000 on the 3A build (gov and research), and 500 of 500 gov calls again on the 3B build | **Pass** | `probes-tables-leak-*`, `probes-tables-equivalence-*` |
| S2 | SQL is read-only and bounded | 100% refused or bounded, with the fixed messages | 120 of 120 per corpus on the 3A build, and 120 of 120 on the gov 3B build; the database intact after every case | **Pass** | `probes-tables-sql-*` |
| S3 | Fail closed and logged | No content in any case; 100% of table-tool log lines carry the Phase 2 fields plus the tables id | Fail closed 90 of 90 per corpus, on both builds, no content. Applicability 51 of 51 on the 3A build and 153 of 153 on the 3B build (102 on the drawbridge tables), only rows of documents in force. Every log scan complete | **Pass** | `probes-tables-failclosed-*`, `probes-tables-applicability-*` |
| D1 | Over MCP with handles | MCP tests for the three new tools; a handle replay: all pass, every result carries a handle with `tables` | The MCP tests of `tests/store/test_tables_mcp.py` pass. MCP leg: 60 leak probes through `adr mcp` servers on each build, 0 leaks; every handle replay identical and naming the tables | **Pass** | `probes-tables-mcp-*` |
| X1 | Determinism | As T2, plus overlays and entity tables built twice: identical | Every run and probe set identical twice; gov and research tables, entity tables included, built twice: identical files and tables ids | **Pass** | `tables-12-checks/checks.json` |

## Model-call ledger

The user approved 1,500 calls (§11), split into fixed shares per command that sum to 1,485.
Budget units count every transport attempt, retries included (Builder note 2), so real use could
not exceed a share. The two extraction passes and the golden generation each ran first as a 3-call check, then in full; the three `adr-eval run` commands ran in full directly.

| Command | Profile | Share | Runs (`--max-calls`) | Units used |
|---|---|---|---|---|
| `adr tables extract` (first pass) | `claude_code_sonnet` | 560 | check with prompt version 1 (3), check with prompt version 2 (3), full run (554) | 3 + 3 + 530 = **536** |
| `adr tables extract --second-pass` | `claude_code_opus` | 560 | check (3), full run (557) | 3 + 535 = **538** |
| `adr-eval golden tables --gen` (phrasing) | `claude_code_sonnet` | 140 | check (3), full run (137) | 3 + 117 = **120** |
| `adr-eval run … --system p3-typed` (query generation) | `claude_code_sonnet` | 125 | test (100), dev (25) | 97 + 23 = **120** |
| `adr-eval run … --system baseline-linear` (answers; its query calls all hit the cache) | `claude_code_sonnet` | 100 | test (100) | **97** |
| `adr tables build --with-extraction`, `adr tables gate`, `adr acl sync` | – | 0 | `--max-calls 0` where the command takes it | 0 |
| Everything after: E1, E2, T1–T6, Step 9, X1, regeneration checks, write-ups | – | 0 | `--max-calls 0` | 0 |
| **Total** | | **1,485** | | **1,411 of 1,500** |

- **No full command failed or stopped early** (the four 3-call checks stopped at their cap, as intended), no transport attempt was retried, and no input was rejected, so no failure was cached (ruling P21).
- **The 3 calls of the first check are lost to ruling P22.** That check, with prompt version 1, found the model writing `seasonal: false` with no quote, which the span check rejects. The prompts were changed (version 2: a `false` needs a quote that states it), and the check's replies are not used.
- **The second pass's 538 units include 5 parse retries**, one for each reply that did not parse (§7.2 check 1). One parsed on the retry; the other 4 stayed unparseable, so the model columns of those 4 section texts are null `unparseable` in the facts.
- **Each pass's served model is recorded** in its extraction report and in each run's configuration, and is the one §11 names.

## 3A: metadata tables and Q1

### The tables

Each build is a set of write-once table files named by their SHA-256, plus a manifest whose SHA-256 is the tables id. Both 3A builds were promoted through the merge gate with 0 flips on the v0.1 count questions: gov 38 of 38, research 35 of 35. **No row was rejected** in any table.

| Corpus | Table | Kind | Rows | Null cells (reason) |
|---|---|---|---|---|
| gov | `fr_documents` | data | 167 | `effective_on` 56 (absent); `title_state` 5 (absent), 113 (not_applicable) |
| gov | `fr_cfr_refs` | data | 221 | – |
| gov | `fr_agencies` | data | 278 | `parent_id` 167 (absent) |
| gov | `fr_dockets` | data | 171 | – |
| gov | `agencies` | entity | 278 | – |
| gov | `cfr_parts` | entity | 221 | – |
| gov | `dockets` | entity | 171 | – |
| gov | `waterways` | entity | 1,320 | – |
| research | `papers` | data | 2,570 | `licence_id` 2,336 (absent); `year` 19 (absent) |
| research | `paper_authors` | data | 9,683 | `author_id` 2 (absent) |
| research | `authors` | entity | 7,417 | – |
| research | `licences` | entity | 34 | – |
| research | `venues` | entity | 1,098 | – |

### Entity clusters

Clusters form by exact normalised keys only (ruling P11); every override file is empty. "Source rows" counts the (entity, raw form, source, document) rows the clusters were built from; "merged" counts clusters that join more than one raw form.

| Corpus | Type | Clusters | Singletons | Merged | Source rows |
|---|---|---|---|---|---|
| gov | agencies | 3 | 3 | 0 | 278 |
| gov | cfr_parts | 39 | 39 | 0 | 221 |
| gov | dockets | 157 | 157 | 0 | 171 |
| gov | waterways | 467 | 435 | 32 | 1,416 |
| research | venues | 905 | 836 | 69 | 2,570 |
| research | licences | 33 | 32 | 1 | 234 |
| research | authors | 7,413 | 7,409 | 4 | 9,681 |

[`entity-samples.json`](entity-samples.json) holds the ten largest clusters of each type and a seeded sample (seed 20261120) of 50 clusters per type, or every cluster when a type has 50 or fewer. They come from the builds' operator-only reports, which are never served to callers. Known weak spots, all from the exact-key rule: author strings split on commas leave a cluster for company suffixes and a second form of some names with a stray bracket; unbalanced brackets stay in some venue keys; the stateless general section of § 117.140 gives a waterway key `general`, and title parts that name cities or counties also become waterway entities.

**Waterway links.** [`waterway-links.json`](waterway-links.json) links each drawbridge FR title to its 33 CFR 117 sections on (waterway key, state), in the newest eCFR version (2026-06-26: 424 sections, 38 states). 47 of 54 titles link (the same 47 against all three versions). 5 have no matching heading and 2 are refused by the state check; the file lists each with its reason. There is no link table (Builder note 14): a row drawn from two documents would need both documents' access.

### Q1, the frozen count questions

`p3-typed` (§10.1) runs on `count_filter` items only. For each item it generates the query with the baseline's prompt and schema, so the cache hits, compiles it to one `query_table` call over the corpus's main table (`fr_documents`, `papers`) as `user:auditor`, and scores the answer exactly as Phase 0 does. There is no answer call, no judge and no fallback to chunks. `adr_eval.phase3.cache_inputs_unchanged` first confirmed that the query-generation prompt and the record-schema text are byte-identical to the baseline runs'.

| Corpus | Items | `p3-typed` | `baseline-linear` (Phase 0) | b (typed only) | c (baseline only) | McNemar p (exact) |
|---|---|---|---|---|---|---|
| gov | 27 | **27 (1.000)** | 2 (0.074) | 25 | 0 | 6.0 × 10⁻⁸ |
| research | 27 | **26 (0.963)** | 16 (0.593) | 10 | 0 | 0.0020 |

Each run ended `complete` with 27 rows and 0 calls, and gave the same rows again on the 3B build.

- **The one `p3-typed` miss is the `also_in` wording problem (§4.2).** A research `list` item: the generated query used `also_in__contains`, the membership reading, and returned 23 ids against the gold's 14, which compares the whole `;`-joined string. The same query gives 23 over the records too (`query_exec_match` false), so the tables answered the query correctly; the miss belongs to the question's wording against the frozen gold.
- **`baseline-linear` misses:** gov 25 (21 wrong, 4 abstained), each with a correct generated query, so all came from answering from retrieved chunks; research 11 wrong, 10 with a correct query and the 11th the item above.
- **Q1 is close to certain by construction** (§10.2). The generated queries already returned the gold records on 27 of 27 gov and 26 of 27 research items; only the baseline's answering step failed. Q1 shows that the tables and the compiler reproduce the record semantics of `golden/records.py`.

**The two `also_in` readings.** Over the six v0.1 count items whose gold compares `also_in` exactly, the count under the string reading (the frozen gold) and the membership reading:

| Split | Op | Wording | Topics in the value | String | Membership |
|---|---|---|---|---|---|
| test | count | value | 3 | 1 | 3 |
| test | list | value | 2 | 2 | 2 |
| dev | count | membership | 1 | 14 | 22 |
| test | count | membership | 1 | 2 | 2 |
| test | list | membership | 1 | 14 | 23 |
| dev | count | membership | 1 | 2 | 8 |

Three membership-worded items differ (the three of §4.2). The two value-worded items ask for the value itself, so the string reading is theirs. The tables keep both: `also_in` holds the raw string, so the frozen gold reproduces, and `also_in_list` holds the topics.

## 3B: extraction from 33 CFR 117 and Q2

### The two passes

The extraction family is 33 CFR part 117 in the gov store (ruling P2): 533 distinct section texts from 1,386 sections over three eCFR versions, 424 sections in the newest.

| Pass | Profile | Prompt | Calls |
|---|---|---|---|
| first (the table) | `claude_code_sonnet` | `drawbridge-extract@2`: one JSON form per section text, all 9 model columns in one group | 533 replies, 0 failed |
| second (the facts) | `claude_code_opus` | `drawbridge-questions@2`: numbered questions with quotes, one call per section text (P15) | 533 replies plus 5 parse retries; 4 texts unparseable |

### E1, grounding

E1 is the grounded share of non-null model values per column, from the first pass's extraction report, before ungrounded values are dropped (§7.3). Draw columns count per draw, section columns per section text.

| Column | Grounded / non-null | Share | Failed | ≥ 95% |
|---|---|---|---|---|
| `waterway` | 503 / 503 | 100% | – | yes |
| `seasonal` | 157 / 166 | **94.6%** | 9 span | **no** |
| `owner_or_agency` | 145 / 145 | 100% | – | yes |
| `vhf_channel` | 39 / 39 | 100% | – | yes |
| `bridge` | 1,239 / 1,239 | 100% | – | yes |
| `mile` | 1,213 / 1,213 | 100% | – | yes |
| `notice_hours` | 722 / 723 | 99.9% | 1 span | yes |
| `opens_on_signal` | 1,018 / 1,018 | 100% | – | yes |
| `closed_periods` | 365 / 406 | **89.9%** | 17 span, 24 type | **no** |
| **all** | **5,401 / 5,452** | **99.1%** | | |

- A "span" failure is check 3: the quote is not in the section text. A "type" failure is check 2: the value could not be read as the column's type, so it never reached the span check. On the span check alone `closed_periods` would be 365 of 382 (95.5%); the report and this page count the type failures as not grounded.
- No ungrounded value is stored: those become nulls with reason `ungrounded` (25 in `drawbridge_sections`, 3 in `drawbridge_bridges`, in `seasonal` and `notice_hours`). The 41 failed `closed_periods` values are dropped from that list column with no `ungrounded` record. Of the stored values, 15,135 are `verified` and 27 `auto-accepted` (their number is not in the quote, check 4).
- The second pass's own report gives 5,478 of 5,529 grounded (99.1%).

### E2, agreement with the second pass

E2 is `agreement(first, second)` from `adr_store.tables.extract`. The first pass is read back from the cache behind a zero-call budget (533 replies cached, 0 calls), the second from its facts file. Draws are matched by bridge-name key, then by mile: 1,215 matched, 24 in the first pass only, 9 in the second only. `bridge` is the share of section texts whose sets of draw keys are equal.

| Column | Compared | Agree | Share | Required ≥ 0.85 |
|---|---|---|---|---|
| `waterway` | 533 | 522 | 0.979 | **pass** |
| `bridge` (draw set per section) | 533 | 491 | 0.921 | **pass** |
| `notice_hours` | 1,215 | 1,154 | 0.950 | **pass** |
| `opens_on_signal` | 1,215 | 1,161 | 0.956 | **pass** |
| `mile` | 1,215 | 1,212 | 0.998 | – |
| `seasonal` | 533 | 518 | 0.972 | – |
| `vhf_channel` | 533 | 529 | 0.992 | – |
| `owner_or_agency` | 533 | 425 | 0.797 | – |
| `closed_periods` | 1,215 | 859 | 0.707 | – |

**Regex cross-check (§7.2 check 5),** over grounded values; reported, never used to reject:

| Column | First pass: agree / checked | Second pass: agree / checked | Regex finds nothing (first, second) |
|---|---|---|---|
| `mile` | 1,191 / 1,206 (98.8%) | 1,186 / 1,203 (98.6%) | 7, 7 |
| `vhf_channel` | 37 / 37 (100%) | 37 / 37 (100%) | 2, 1 |
| `notice_hours` | 278 / 394 (70.6%) | 283 / 393 (72.0%) | 328, 322 |

Both passes disagree with the `notice_hours` expression at about the same rate; the expression finds only digit forms such as "24 hours", and its disagreements were not analysed one by one.

### The 3B build and the gate

- **The build** made 10 tables and 6,919 rows with 0 rejected and 0 calls: the eight 3A gov tables (the same files as the 3A build) plus `drawbridge_sections` (1,386 rows, one per section and version) and `drawbridge_bridges` (2,706 rows, one per draw; ruling P14). Tables id `fec2a2b12e318fcba0c350edac2e61acdbcc3bdccaad8f8d08c9290014270230`.
- **The gate promoted it** over the 3A build with **0 flips** (ruling P12). The candidate answered 126 of 158 gold cases (v0.1 38 of 38, gov-tables 88 of 120); HEAD had answered 38.
- **Q1 is unchanged on the 3B build**: rerun with `--max-calls 0` after the promotion, both Q1 runs gave rows byte-identical to the 3A runs.

### gov-tables v0.1

120 items, 97 test and 23 dev: 53 count, 57 list and 10 lookup. The facts come from the second pass, a model words each question, and code computes each answer (ruling P9). [`golden/gov-tables/v0.1/README.md`](../../golden/gov-tables/v0.1/README.md) gives how the set was made, the draw counts (752 draws: 120 accepted, 170 repeats, 265 unusable, 197 rejected), the regex agreement of the gold facts and the limits of §10.3. The items are committed, as gov v0.1's are (US government works). Regenerating the set from the cache with `--max-calls 0` reproduced both files byte for byte.

### Q2, the drawbridge questions

| System | Test items | Right | Accuracy |
|---|---|---|---|
| `p3-typed` | 97 | 66 | **0.680** |
| `baseline-linear` | 97 | 23 | 0.237 |
| `p3-typed`, dev (information only) | 23 | 19 | 0.826 |

- **Accuracy: fails.** 0.680 is below the 0.80 bar.
- **Margin: passes.** The paired difference is +0.443 [+0.330, +0.557]; its lower bound is far above +0.02. McNemar: b = 47, c = 4, p = 2.4 × 10⁻¹⁰.
- **Verdict:** Q2 needs both parts, so it fails. The bar stays as §12 fixed it (ruling P13).

**Why it fails.** All 31 typed misses were wrong values: no errors and no refused queries.
- **5 misses: the query differs from the gold query** (4 in the filters, 1 in the table and the filters). These are query-understanding misses.
- **26 misses: the query equals the gold query, but the value differs.** The tables and the compiler ran the right query. The table holds the first pass's reading of the section and the gold the second pass's, and the two differ. Had the table agreed with the second pass on those 26, accuracy would be 92 of 97 (0.948).
- **No pass is known to be right.** Neither pass was checked by a person (P9, P10), so Q2's accuracy measures how well the two passes agree on the values the questions read, as much as whether the table is right.

Each of the 26 was attributed by running each column's clauses (and a lookup's field) on the promoted tables and on the facts, for the version in force. A miss counts under every column whose result differs (15 misses have one column, 11 have two, so the rows add up to 37):

| Disagreeing column | Misses |
|---|---|
| `closed_periods` | 9 |
| `owner_or_agency` | 6 |
| `notice_hours` | 5 |
| `opens_on_signal` | 5 |
| `seasonal` | 4 |
| `mile` | 2 |
| `vhf_channel` | 2 |
| `bridge` (`__isnull`) | 1 |
| `waterway` | 1 |
| draw set (a draw one pass has and the other lacks, through a `state` clause) | 1 |
| lookup matching no row in the table | 1 |

The two columns behind most misses are the two E2 measures as least in agreement. **`baseline-linear`** missed 74: 57 abstained and 17 were wrong. Its query calls all hit the cache the `p3-typed` runs had filled.

[`run-summaries/q2-gov-tables.json`](run-summaries/q2-gov-tables.json) is the `p3-q2 --summary` form: no item id, filter value or answer, typed misses counted by cause and query shape.

### T1–T6

| # | Check | Result |
|---|---|---|
| T1 | Zero-call rebuild | **Pass.** In Task 11, `adr tables build --tables-for gov --with-extraction --max-calls 0` into a `cp -a` copy reproduced `fec2a2b12e31…` with all 37 files of the snapshot's tables directory unchanged; in a second copy with the 3B files and the manifest deleted, it wrote them again byte-identical. In this task, every build was repeated from scratch (see X1). |
| T2 | Each suite and probe set twice in fresh processes | **Pass** (see X1). |
| T3 | Every provenance span of the promoted 3B build, re-sliced with `provenance.reslice` | **Pass: 32,889 of 32,889**, including all 15,162 model-value quotes. |
| T4 | Every stored value carries a `spec_id` | **Pass: 60,295 of 60,295.** The 22,121 non-null values without a span are computed values (entity tables, FR agency and reference ids, `status`, the drawbridge `version` and `draw`), each with its `spec_id`. |
| T5 | `test_a_spec_change_reextracts_only_its_group` | **Pass** |
| T6 | `test_gate_refuses_too_many_flips_and_keeps_head` | **Pass** |

## Access: S1–S3 and D1

All probes ran on the scratch stores after a fresh ACL sync, with no model call, with seed 20261120. The 3A probes (Task 7) ran on the 3A builds; after the 3B promotion, every set that reads gov tables was run again on the 3B build (Task 7b, Task 11 and this task). The research tables did not change.

**Reference stores.** A leak or equivalence probe compares a call with the same call, by the same caller, on a reference store built from that caller's documents alone. On the 3B build each reference store builds its drawbridge tables from the cached first-pass replies with a zero-call budget (the cache key holds no store-specific input, so a subset store finds the same replies); a missing reply would stop the run without a call (P21), and a reference whose extraction would differ from the store's is refused. 7 views see the drawbridge rows and 13 have empty drawbridge tables.

| Criterion | Probe set | 3A build | 3B build (gov `fec2a2b12e31…`) |
|---|---|---|---|
| S1 leaks | 5 families (by key, filter, aggregate, `count_by` group, error message) × the caller's hidden rows | **0 leaks in 400**: gov 300, all compared with a reference store; research 100, all `user:ghost` F4 denials | **0 leaks in 300**, all compared; 65 on hidden drawbridge rows (34 `drawbridge_sections`, 31 `drawbridge_bridges`), over all five families and 13 callers |
| S1 equivalence | 20 views × 25 calls (15 `query_table`, 10 `sql`) per corpus | **1,000 of 1,000** identical (gov 500, research 500); bench and tools hold no tables and refuse alike (60 of 60, 3 of 3, not counted) | **500 of 500** gov; 32 calls are drawbridge `count_by`, only 9 of them in views that see drawbridge rows |
| S2 SQL guard | 120 statements per corpus: writes, DDL, ATTACH, PRAGMA, extensions, schema tables, recursive and cross-join bombs, clock and amplifying functions, error-text leaks, comment tricks | **120 of 120** per corpus refused with a fixed message or bounded; database intact | **120 of 120**, the same outcomes |
| S3 fail closed | (F1–F5, no entry) × 3 tools × 5 callers, per corpus | **90 of 90** per corpus, no content | **90 of 90** gov, no content |
| S3 applicability | default and `as_of` | **51 of 51** on `fr_documents` | **153 of 153**: 51 on `fr_documents`, 51 on each drawbridge table, every probe at most one eCFR version |
| S3 logs | every line the probes wrote | complete: every line has caller, principals, ACL snapshot, decision and `tables`; no `sql` line holds statement text | complete |
| D1 MCP leg | a seeded 60 of the leak probes (gov and research), each through an `adr mcp` server of its caller, then replayed with its handle | **0 leaks**; 44 of 44 replays identical, each naming the tables; 196 calls, 196 log lines | **0 leaks** in 60 (gov 44, 5 of them on drawbridge rows; research 16 `user:ghost`); 44 of 44 replays identical, each naming its store's tables (gov `fec2a2b12e31…`); 196 calls, 196 log lines. Run twice in this task |

- **The applicability probes on the drawbridge tables** start with each eCFR version's first day in force and the day before it, then take seeded Federal Register dates. Of the 50 `as_of` dates per drawbridge table, 14 return rows and **36 fall before the first eCFR version** (27 June 2024) and correctly return nothing, so only 14 per table test the choice of version. The default returns the newest version (424 sections, 835 draws).
- **D1 tests.** `tests/store/test_tables_mcp.py` checks the three table tools over MCP (listing, results with a `tables` handle, replay, refusals); its 5 tests (the tool list with handles, thirty fixed calls equal to the Python API, SQL refusals as error results with the fixed messages, a handle replay, text rendering) pass, alone and in the full suite.

## X1: determinism

**Verdict.** X1 passes. Every Phase 3 run and probe set was run twice in fresh processes and gave identical rows and results, and the gov and research tables built twice from the same inputs gave the same files and tables ids. Where an earlier task already ran a set twice in fresh processes on the current build and code, its evidence is reused; every other set was run twice in this task.

**What counts as identical.** For runs, `results.jsonl` and `compile.json` byte for byte. For probe sets, `probes.json` and `results.json` byte for byte (the per-item files, kept under `runs/`). Only fields that record when, or under which ACL snapshot, a run happened differ between two runs, and those are in the summaries only.

| Set | Build | Runs compared | Where | Result |
|---|---|---|---|---|
| Q1 `p3-typed` gov and research | 3B HEAD | Task 11, two fresh processes each; also equal to Task 8's runs on the 3A build | reused | **Identical** |
| Q2 `p3-typed` test and dev, `baseline-linear` test | 3B HEAD | Task 11, two fresh processes each (`--max-calls 0`) | reused | **Identical** |
| tables-leak gov | 3B | Task 7b, two fresh processes, reference stores built afresh in each | reused | **Identical** |
| tables-equivalence gov | 3B | Task 7b | reused | **Identical** |
| tables-applicability gov (3 tables) | 3B | Task 7b | reused | **Identical** |
| tables-sql gov | 3B | passes A and B of this task | rerun | **Identical**; also byte-identical to Task 7's (3A) and Task 11's (3B) runs |
| tables-sql research | 3A | passes A and B | rerun | **Identical**; equal to Task 7's run |
| tables-failclosed gov | 3B | passes A and B | rerun | **Identical**; equal to Task 7's run on the 3A build (the fail-closed outcomes do not depend on the drawbridge tables) |
| tables-failclosed research | 3A | passes A and B | rerun | **Identical**; equal to Task 7's run |
| tables-leak research | 3A | passes A and B | rerun | **Identical**; equal to Task 7's run |
| tables-equivalence research | 3A | passes A and B, 20 reference stores with dense indexes built afresh in each | rerun | **Identical**; equal to Task 7's run |
| tables-equivalence bench and tools (no tables) | – | passes A and B | rerun | **Identical**; equal to Task 7's runs |
| tables-mcp (gov 3B with research) | 3B | passes A and B, 17 gov reference stores built from the cache in each | rerun | **Identical** (differs from Task 7's 3A run, as it should: the gov leak probes changed with the build) |

In all: **5 of 5 question runs and 12 of 12 probe sets identical.** The two passes' summaries differ only in the ACL snapshot and sequence of the syncs before them. Approximate pass wall times (from run start and summary file times, not recorded by the runs): SQL guard about 10 s (gov) and 16 s (research), fail closed about 13 s and 30 s, research leak 6–7 s, bench equivalence 33–36 s, MCP leg 214–219 s, research equivalence 570–580 s.

The question runs and the three Task 7b sets are reused because no code on their path changed after them: the only later changes (Task 7b's) are in the probe code and the `probes` command, and the Task 7b sets ran on that code. Task 7's earlier pairs on the 3A build (all 12 sets) and Task 11's pairs of the SQL-guard and `fr_documents` applicability sets on the 3B build are superseded by the rows above, and all were identical too.

### Tables built twice

In two `cp -a` copies of each scratch store, the whole tables directory was removed and the tables built again in fresh processes with `--max-calls 0`: gov metadata only, then gov with extraction, and research.

| Corpus | Build | Tables id (both copies) | Files | Result |
|---|---|---|---|---|
| gov | 3A (8 tables: 4 data, 4 entity) | `2678b8da96338df9…` | 22 files in all for gov: 10 tables, each with its report, and the 2 manifests | **Byte-identical** between the copies, and to the promoted builds' files |
| gov | 3B (10 tables: + `drawbridge_sections`, `drawbridge_bridges`) | `fec2a2b12e318fcb…` | | |
| research | 3A (5 tables: 2 data, 3 entity) | `62604e913378c76b…` | 11 | **Byte-identical**, likewise |

Each manifest's SHA-256 equals its tables id. The extraction build made 0 calls: its 533 replies came from the cache. The applicability overlay is Phase 2's, unchanged (its double derivation is Phase 2's X1).

### Phase 2 regression (constraint 2)

Constraint 2 asks that Phases 1 and 2 stay reproducible: the five Phase 2 tools return identical hits. One `p2-default` test run per corpus was made again with `adr-eval retrieval <corpus> --system p2-default --split test`, which makes no model call (as in Phase 2, R1), and compared with `adr-eval retrieval-identical` against the local rows of the Phase 2 run whose summary is committed:

| Corpus | Items | Against the Phase 2 run as `user:auditor` (the 2B re-run) | Summary against the committed one |
|---|---|---|---|
| gov | 242 | **identical** (`…20261116T090659`): ranked chunk ids and exact scores | equal |
| research | 222 | **identical** (`…20261116T090011`) | equal |
| bench | 572 | **identical** (`…20261116T091038`) | equal |

`p2-default` searches as `user:auditor` since Phase 2B. Against the earlier Phase 2 runs made before the ACL layer existed (`…T0607*`, `…T0616*`, `…T0610*`), gov is identical too, and research and bench keep every ranked id while scores differ in the last float32 bits (at most 3e-06 and 1.8e-05), the effect Phase 2 recorded under ruling R17; their summaries are equal to the committed ones. The new runs' configurations differ only in run id, times and the ACL snapshot. So the Phase 3 build left Phase 2 retrieval unchanged.

## Rulings

Spec §14 lists the rulings made without the user. P1–P17 were fixed with the design; **P18–P22 were made during the build** and added to the spec then.

| # | Ruling (short) |
|---|---|
| P1 | Model calls only for the purposes and cap of §11 |
| P2 | The extraction family is 33 CFR 117 |
| P3 | One model extracts, a second checks |
| P4 | Raw columns kept beside normalised ones; v0.1 gold semantics reproduced exactly |
| P5 | Rows inherit document access; no row-level policy |
| P6 | The JSONL overlay is the record; SQLite is a per-call derived view |
| P7 | SQL errors return fixed messages per class |
| P8 | A deterministic SQL budget in virtual-machine steps, not time |
| P9 | gov-tables gold from the second extraction, phrased by a model, answered by code |
| P10 | No human review step; `review-pending` reserved |
| P11 | Entity resolution by exact normalised keys only |
| P12 | The merge gate is built and tested, and used for every promotion: three builds (gov 3A, research 3A, gov 3B) |
| P13 | The margins and thresholds of §12 fixed before any result |
| P14 | Two drawbridge tables: sections and draws |
| P15 | The second pass is one numbered-question call per section |
| P16 | `p3-typed` runs on count items only and never answers from chunks |
| P17 | Entity display names computed per caller view |
| **P18** | `describe_tables` is an index plus per-table detail, each at most 8 KB (Task 5) |
| **P19** | A `sql` statement's own `ORDER BY` gets positional tie-breakers on every output column (Task 5) |
| **P20** | `sql` bounds work per step: a per-value length limit, and string-amplifying functions charged against the step budget (Task 5). Limits: 8 KB per stored value and 16 KB per row, enforced at build and at read |
| **P21** | Only failures caused by the input are cached as `model_error`; retries exhausted, usage limits, other errors and budget stops stop the run uncached (Task 9) |
| **P22** | A bool value needs a quote that states it, `false` included; prompts `drawbridge-extract@2` and `drawbridge-questions@2` (Task 11, after the first 3-call check) |

## Limits

- **The gov-tables gold comes from the model's second pass** (P9), and no person checked either pass (P10). Where the passes disagree, which one is right is not known; Q2's 26 value misses are exactly such disagreements.
- **Errors shared by both passes are invisible** (§10.3). Two models reading a section the same wrong way agree in E2 and in Q2.
- **Synthetic tenants.** Three tenants, twelve groups and twenty users give 20 views per corpus, as in Phase 2. On gov, the eCFR §117 chain is visible to one tenant only, so 13 of the 20 views hide every drawbridge row.
- **Research access is all-or-nothing** (P5). The research tables come from one document, the public papers manifest, so no directory user has a hidden research row: research's 100 leak probes can only be `user:ghost` denials, and its equivalence compares views that all see everything. Gov carries the leak measurement.
- **Raw versus normalised columns** (P4). Tables keep raw values (for example `also_in`, venue and author strings) beside normalised ones (`also_in_list`, entity keys), so the frozen gold reproduces; an agent may pick the raw column where the normalised one is meant. The semantic layer describes both.
- **Q1 is by construction** (§10.2): it tests that the tables reproduce the record semantics, not query understanding.
- **The `also_in` wording.** Three v0.1 research count items are worded as topic membership while their frozen gold compares the whole string; one of them is `p3-typed`'s only Q1 miss.
- **Thin drawbridge equivalence coverage.** On the 3B build only 9 of the 500 equivalence calls touch drawbridge rows a view can see (32 are drawbridge `count_by`, 23 of them in views with empty drawbridge tables). The 65 drawbridge leak probes carry most of the drawbridge comparison.
- **Most drawbridge `as_of` dates fall before the first version.** 36 of the 50 `as_of` dates per drawbridge table precede 27 June 2024 and return nothing; 14 per table test version selection.
- **3 calls lost to P22.** The first-pass check with prompt version 1 used 3 units whose replies are not used.
- **E1 and Q2 fail as measured.** The bars were not moved (P13). `closed_periods` is the weakest column on every measure: E1 89.9%, E2 0.707, and 9 of the 26 Q2 value misses.
- **The merge gate's threshold is untested on a real regression** (P12): every real promotion had 0 flips.
- **The SQL guard's residual cost.** A recursive copy of a stored value is bounded only by the step budget (about 13 s and 4 GB of temporary disk in the worst probe; documented in `sqlguard.py`).
- **Number words in quotes** (check 4, `number_in_quote`). The reader of numbers in a quote has quirks: "three-quarter-hour" reads as 3, "eleven hundred" gives {11, 100} rather than 1,100, and "twenty- four" (a hyphen then a space) reads as 20 and 4. Check 4 is soft: a failure turns `verified` into `auto-accepted` and never rejects a value. A read-only scan of the 3B build found no stored `notice_hours` or `mile` value whose quote has such a phrase. The reader was left as it is, because changing it could change statuses, and so the table bytes and ids.
- **A `query_table` lookup has no byte cap.** `sql` refuses a result over 2 MB, but a `lookup` returns up to 1,000 rows (`limit`) whatever their size: one lookup on `papers` with limit 1,000 returned 6.1 MB, and the worst case is about 16 MB (1,000 rows at the 16 KB row bound). Nothing leaks, since the rows are the caller's view, but one call can fill an agent's context.
- **Contracts must not change under a running server.** `describe_tables` re-reads the contracts on every call and refuses once one differs from the build's. `query_table` and `sql` keep answering from the view databases they already hold until those are evicted or a new view is opened. Edit a contract only with no `adr mcp` server running.
- **One machine.**

## Files

`run-summaries/` holds, without per-item rows, probe lists, queries or corpus text:

| Part | Files |
|---|---|
| 3A | the two Q1 runs (`gov-p3-typed-test-20261120T200702`, `research-p3-typed-test-20261120T200924`: `config.json`, `compile.json`, `report.json`, `report.md`, and `q1-<baseline>.json` in `p3-q1 --summary` form); the Task 7 probe summaries (`probes-tables-*-20261120T19*`) and `tables-7-checks/checks.json` |
| 3B | the three gov-tables runs (`gov-tables-*-20261120T23*`); `q2-gov-tables.json` (`p3-q2 --summary`); the Task 11 SQL-guard and applicability summaries (`…T235517`, `…T235528`); the Task 7b summaries (`probes-tables-*-20261121T002*`) and `tables-7b-checks/checks.json`; `tables-11-checks/checks.json` (E1, E2, regex, the Q2 attribution, T1–T6) |
| X1 | the probe summaries of both passes of this task (`probes-tables-*-20261121T004*` and `…T005*` for pass A, `…T010*` for pass B; 9 sets each) and `tables-12-checks/checks.json` (pairs, hashes, table builds, the Phase 2 regression, cache counts) |

No committed file names a golden item. Per-item rows (`results.jsonl`), the full Q1 and Q2 outputs and the probe sets stay local in `runs/`. [`golden/gov-tables/v0.1/`](../../golden/gov-tables/v0.1/) holds the gov-tables items; [`entity-samples.json`](entity-samples.json) and [`waterway-links.json`](waterway-links.json) hold the cluster samples and the link list.
