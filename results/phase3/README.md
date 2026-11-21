# Phase 3 results: the typed deterministic database

> This page holds the 3A results (the metadata tables and the frozen count questions, Q1) and
> the table probes (S1–S3 and the MCP leg of D1), recorded on 20 November 2026 under version 2
> of the metric definitions, with golden sets v0.1. It also holds the 3B results: the extraction
> run, gov-tables v0.1, Q2, E1, E2 and T1–T6, recorded on 20–21 November 2026. 3A made no model
> call. 3B made 1,411 of the 1,500 calls the user approved (§11), all in its model-call steps.
> Every check after those steps ran from the cache with `--max-calls 0`.

**Verdict for 3B.**
- **Q2 fails.** `p3-typed` answered 66 of 97 gov-tables test items (0.680), below the 0.80 bar fixed in §12. The margin part passes: `baseline-linear` scored 0.237, the difference is +0.443 with a 95% interval of [+0.330, +0.557], and McNemar p is 2.4 × 10⁻¹⁰. In 26 of the 31 misses the generated query equals the gold query. The table, built from the first extraction pass, gives a different value than the second-pass facts the gold was computed from. So most misses come from the two passes disagreeing. They are not query or compiler errors, and which pass is right is not known.
- **E1 fails on two columns and passes overall.** 5,401 of 5,452 non-null model values are grounded (99.1%). `closed_periods` (89.9%) and `seasonal` (94.6%) are below the 95% target per column (§7.3). The other seven columns are at 99.9% or 100%.
- **E2 passes.** The four required columns are at or above 0.85: `waterway` 0.979, `bridge` 0.921, `notice_hours` 0.950, `opens_on_signal` 0.956. The lowest unrequired columns are `closed_periods` (0.707) and `owner_or_agency` (0.797).
- **T1, T3, T4, T5 and T6 pass.** **T2 passes for every run made**: the Q1 and Q2 runs and the SQL-guard and applicability probe sets each gave byte-identical rows twice. The leak, equivalence, fail-closed and MCP probe sets were not re-run on the 3B build (below).
- **The gate promoted the 3B build with 0 flips.** It answered 126 of 158 gold cases: v0.1 38 of 38 and gov-tables 88 of 120.
- **The 3B probes (Step 9) were not run, because of a defect.** The probe CLI cannot build reference stores with the extraction tables, and cannot point the applicability probes at the drawbridge tables. Both need code changes. See "3B: probes".

**Verdict for 3A.**
- **Q1 holds.** `p3-typed` answers 27 of 27 gov and 26 of 27 research test count questions from the typed tables. `baseline-linear` answered 2 of 27 and 16 of 27. Gov's paired McNemar p is 6.0 × 10⁻⁸ and research's is 0.0020. Both accuracies are at least 0.90, and gov's p is below 0.05.
- **Q1 was close to certain by construction** (spec §10.2). The generated queries are the baseline's own, read back from the model cache. They already returned the gold records on 27 of 27 gov and 26 of 27 research items, and only the baseline's answering step, which read retrieved chunks, failed. So Q1 tests that the typed tables and the query compiler reproduce the record semantics of `golden/records.py`. It does not show a new ability to understand questions.
- **The one miss is the `also_in` wording problem** (§4.2). The model read the question as topic membership, while the frozen gold compares the whole `;`-joined string. The tables keep the raw string, so they reproduce the gold. The miss belongs to the generated query, not to the tables.
- **The table probes pass** (S1–S3, D1 MCP leg): 0 leaks in 400 leak probes, of which 300 were compared with a reference store. Fail-closed passed 90 of 90 per corpus, the SQL guard 120 of 120 per corpus, table equivalence 1,000 of 1,000 and applicability 51 of 51. The MCP leg found 0 leaks in 60 probes, and 44 of 44 handle replays were identical.

Design: [`docs/superpowers/specs/2026-11-20-phase3-design.md`](../../docs/superpowers/specs/2026-11-20-phase3-design.md).
Phase 2 results: [`results/phase2/README.md`](../phase2/README.md).

## 3A: what was run

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
adr-eval p3-q1 runs/gov-p3-typed-test-20261120T200702 runs/gov-baseline-linear-test-20261113T094503 \
    --summary results/phase3/run-summaries/gov-p3-typed-test-20261120T200702/q1-gov-baseline-linear-test-20261113T094503.json
```

`p3-q1` writes its full output, which names items, only into the typed run's directory under `runs/` (gitignored). The committed `q1-<baseline>.json` is the `--summary` form (`phase3.q1_summary`). It holds no item id and no filter value. It gives each typed miss by its cause and the shape of its query (op, store, filter keys), and baseline misses and the `also_in` readings as counts.

| Corpus | Items | `p3-typed` | `baseline-linear` (Phase 0) | b (typed only) | c (baseline only) | McNemar p (exact) |
|---|---|---|---|---|---|---|
| gov | 27 | **27 (1.000)** | 2 (0.074) | 25 | 0 | 6.0 × 10⁻⁸ |
| research | 27 | **26 (0.963)** | 16 (0.593) | 10 | 0 | 0.0020 |

Each run ended `complete` with 27 rows and `calls` 0. Gov was run a second time in a fresh process (`…T201428`). Its rows and `compile.json` were byte-identical.

**Every miss and its cause.**
- **`p3-typed`, 1 miss: one research test `list` item.** The generated query used `also_in__contains`, the membership reading, plus a status filter. It returned 23 ids, against the gold's 14. The gold compares the `also_in` string exactly. The same generated query gives the same 23 over the records (`query_exec_match` false), so the tables answered the query correctly. The cause is the question's wording against the frozen gold. This is the baseline's one generated-query miss, as §4.2 predicted.
- **`baseline-linear`, 25 gov misses.** 21 were wrong and 4 abstained. In all 25 the generated query was right (`query_exec_match` true), so every miss came from the answer the model gave from retrieved chunks.
- **`baseline-linear`, 11 research misses.** All 11 were wrong answers from retrieved chunks. In 10 of them the generated query was right. The 11th is the item of the typed miss above.

**The `also_in` readings (§4.2)**, over the v0.1 items whose gold compares `also_in` exactly. The table gives the count under each reading; a `list` item counts its ids. The wording class is "value" for a question that asks for an `also_in` value, else "membership".

| Split | Op | Wording | Topics in the value | String (frozen gold) | Membership |
|---|---|---|---|---|---|
| test | count | value | 3 | 1 | 3 |
| test | list | value | 2 | 2 | 2 |
| dev | count | membership | 1 | 14 | 22 |
| test | count | membership | 1 | 2 | 2 |
| test | list | membership | 1 | 14 | 23 |
| dev | count | membership | 1 | 2 | 8 |

For a value with several topics, membership here means every topic of the value is among the record's topics. The two value-worded items ask for the value itself, so the string reading is the question's own. One of them differs only under the membership reading, which its wording rules out. Among the membership-worded items, three differ: dev 14 against 22, dev 2 against 8, and test 14 against 23 (the typed miss). These are the three items of §4.2. The tables expose both readings. `also_in` keeps the raw string, so the frozen gold reproduces, and `also_in_list` holds the topics for the membership reading.

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

## 3B: the extraction run and its calls

The 3B table comes from 33 CFR part 117 in the gov store: 533 distinct section texts from
1,386 sections, 424 of them in the newest version. Two passes extracted the drawbridge facts:

| Pass | Profile | Prompt |
|---|---|---|
| first | `claude_code_sonnet` | `drawbridge-extract@2`: one JSON form per section, all 9 model columns in one group |
| second | `claude_code_opus` | `drawbridge-questions@2`: numbered questions, one call per section |

Each pass's served model is in its report and is the one §11 names. Prompt version 2 is ruling
P22. A 3-call check before the run found the model writing `seasonal: false` with no quote, so
the prompts now require a quote for a `false` too. The 3 calls of that check, made with prompt
version 1, are counted below. Their replies are not used.

**Calls per command against the shares of §11.** Budget units count every transport attempt,
retries included. No command failed, no transport attempt was retried, and no input was
rejected. The second pass's 538 calls include 5 parse retries, one for each reply that did not
parse (§7.2 check 1). One parsed on the retry. The other 4 stayed unparseable, so the model
columns of those 4 section texts are null `unparseable` in the facts.

| Command | Share | Runs (`--max-calls`) | Units used |
|---|---|---|---|
| `adr tables extract` (first pass) | 560 | check, prompt version 1 (3); check, prompt version 2 (3); full run (554) | 3 + 3 + 530 = **536** |
| `adr tables extract --second-pass` | 560 | check (3); full run (557) | 3 + 535 = **538** |
| `adr-eval golden tables --gen` | 140 | check (3); full run (137) | 3 + 117 = **120** |
| `adr-eval run … --system p3-typed` (query generation) | 125 | test (100); dev (25) | 97 + 23 = **120** |
| `adr-eval run … --system baseline-linear` (answers; its query calls all hit the cache) | 100 | test (100) | **97** |
| `adr tables build --with-extraction`, `adr tables gate`, `adr acl sync` | 0 | `--max-calls 0` where the command takes it | 0 |
| Steps 7–10: E1, E2, T1–T6, reruns, regeneration checks, this write-up | 0 | every command `--max-calls 0` | 0 |
| **Total** | **1,485** | | **1,411 of 1,500 approved** |

During Steps 7–10 the model cache `.cache/llm` held 12,010 files before and after: no call was
made.

## 3B: E1, grounding

E1 is the grounded share of non-null model values per column, from the first pass's extraction
report, before ungrounded values are dropped (§7.3, target ≥ 95%). A value counts as non-null
when the model gave one. Draw columns are counted per draw and section columns per section text.

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

- **Why the two columns fall short.** A "span" failure is check 3: the quote is not in the section text. A "type" failure is check 2: the value could not be read as the column's type.
  - `closed_periods` has 24 values that failed the type check, so they never reached the span check. On the span check alone it would be 365 of 382 (95.5%). The report counts them as not grounded, and so does this page.
  - `seasonal` is short by 9 quotes that are not in the section text.
- **Status of stored values.** 15,135 are `verified` and 27 are `auto-accepted`, because their number is not in the quote (check 4). No ungrounded value is stored: those are nulls with reason `ungrounded`, 25 in `drawbridge_sections` and 3 in `drawbridge_bridges`.
- **Second pass.** Its own report gives 5,478 of 5,529 grounded (99.1%).

## 3B: E2, agreement with the second pass

E2 is `agreement(first, second)` from `adr_store.tables.extract`. The first pass is read back
from the cache (`extract_all` behind a zero-call budget: 533 replies cached, 0 calls), and the
second pass from its facts file (`load_facts`, id `541f4c587ee9…`). All 533 section texts are
compared. Draws are matched by bridge-name key, then by mile: 1,215 matched, 24 in the first
pass only, 9 in the second only. Section columns are compared per section text and draw columns
per matched draw. `bridge` is the share of section texts whose sets of draw keys are equal.

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

**Regex cross-check (§7.2 check 5).** Three columns have a regular expression. The counts are
over grounded values. Agreement is reported, never used to reject.

| Column | First pass: agree / checked | Second pass: agree / checked | Regex finds nothing (first, second) |
|---|---|---|---|
| `mile` | 1,191 / 1,206 (98.8%) | 1,186 / 1,203 (98.6%) | 7, 7 |
| `vhf_channel` | 37 / 37 (100%) | 37 / 37 (100%) | 2, 1 |
| `notice_hours` | 278 / 394 (70.6%) | 283 / 393 (72.0%) | 328, 322 |

Both passes disagree with the `notice_hours` expression at the same rate. The expression only
finds digit forms like "24 hours notice". Its disagreements were not analysed one by one.

## 3B: the build and the merge gate

```
adr tables build --store .cache/store-p2/gov --with-extraction --max-calls 0
adr tables gate --store .cache/store-p2/gov --candidate fec2a2b12e318fcba0c350edac2e61acdbcc3bdccaad8f8d08c9290014270230 \
    --gold golden/gov-tables/v0.1 --gold golden/gov/v0.1 --max-flips 0
```

- **The build** made 10 tables and 6,919 rows, with 0 rejected and 0 calls. It holds the eight 3A tables of gov, the same files as the 3A build, plus `drawbridge_sections` (1,386 rows, one per section and version) and `drawbridge_bridges` (2,706 rows, one per draw). Tables id: `fec2a2b12e318fcba0c350edac2e61acdbcc3bdccaad8f8d08c9290014270230`.
- **The gate promoted it** over the 3A build `2678b8da9633…` with **0 flips**. The candidate answered 126 of 158 gold cases: v0.1 38 of 38 and gov-tables 88 of 120. HEAD had answered 38 of 158. It now sits at `tables/HEAD` of `.cache/store-p2/gov`.
- **Q1 is unchanged on the 3B build.** The gov and research Q1 runs, rerun with `--max-calls 0` after the promotion, gave per-item rows byte-identical to those above (gov 27 of 27, research 26 of 27).

## 3B: gov-tables v0.1

There are 120 items: 97 test and 23 dev, of which 53 are count, 57 list and 10 lookup. The facts
come from the second pass, a model words each question, and code computes each answer (ruling
P9). [`golden/gov-tables/v0.1/README.md`](../../golden/gov-tables/v0.1/README.md) gives:
- how the set was made;
- the draw and rejection counts (752 draws: 120 accepted, 170 repeats, 265 unusable, 197 rejected);
- the regex agreement of the gold facts;
- the limits of §10.3.

The items are committed: the sources are US government works. Regenerating the set from the
cache with `--max-calls 0` reproduced both files byte for byte.

## 3B: Q2, the drawbridge questions

```
adr acl sync --store .cache/store-p2/gov
adr-eval run gov --golden gov-tables --system p3-typed --split test --qtype count_filter --max-calls 100
adr-eval run gov --golden gov-tables --system p3-typed --split dev --qtype count_filter --max-calls 25
adr-eval run gov --golden gov-tables --system baseline-linear --split test --max-calls 100
adr-eval p3-q2 runs/gov-tables-p3-typed-test-20261120T233723 runs/gov-tables-baseline-linear-test-20261120T234009 \
    --summary results/phase3/run-summaries/q2-gov-tables.json
```

| System | Test items | Right | Accuracy |
|---|---|---|---|
| `p3-typed` | 97 | 66 | **0.680** |
| `baseline-linear` | 97 | 23 | 0.237 |
| `p3-typed`, dev (information only) | 23 | 19 | 0.826 |

- **Accuracy: fails.** 0.680 is below the 0.80 bar.
- **Margin: passes.** The paired difference (typed minus baseline) is +0.443. Its 95% interval, from `paired_bootstrap_ci` with seed 20261108 and 10,000 resamples, is [+0.330, +0.557], and the lower bound is above +0.02.
- **McNemar:** b = 47 (typed only), c = 4 (baseline only), exact p = 2.4 × 10⁻¹⁰.
- **Verdict:** Q2 needs both parts, so it fails. The bar is kept as §12 fixed it (ruling P13).

**Why it fails.** The typed system's 31 misses were all wrong answers: no errors and no refused
queries.
- **5 misses: the query differs from the gold query.** 4 differ in the filters only, and 1 in the table and the filters. These are query-understanding misses.
- **26 misses: the generated query equals the gold query, but the value is wrong.** The tables and the compiler ran the right query. The table holds the first pass's reading of the section, and the gold was computed from the second pass's reading, and the two differ. If the table agreed with the second pass on those 26, the accuracy would be 92 of 97 (0.948).
- **No pass is known to be right.** Neither pass was checked by a person (rulings P9, P10). So Q2's accuracy measures how well the two passes agree on the values the questions read, as much as whether the table is right.

The 26 misses below are attributed to columns. Each column's clauses, and a lookup's field, were
run on the promoted tables and on the second-pass facts, for the version in force. A miss counts
under every column whose result differs: 15 misses have one column and 11 have two, so the rows
add up to 37.

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
| draw set (a draw one pass has and the other lacks, seen through a `state` clause on `drawbridge_bridges`) | 1 |
| lookup that matches no row in the table | 1 |

The two columns that cause the most misses are the two E2 measures as least in agreement
(`closed_periods` 0.707, `owner_or_agency` 0.797).

**Baseline misses:** 74, of which 57 abstained and 17 were wrong. Its query calls all hit the
cache that the `p3-typed` runs had filled.

[`run-summaries/q2-gov-tables.json`](run-summaries/q2-gov-tables.json) is the `p3-q2 --summary`
form. It holds no item id, filter value or answer, and counts typed misses by cause and query
shape. The full output is only in the typed run's directory under `runs/`.

## 3B: T1–T6

Every check ran with `HF_HUB_OFFLINE=1`, each command in a fresh process, with no model call.

| # | Check | Result |
|---|---|---|
| T1 | `cp -a` of `.cache/store-p2/gov`, then `adr tables build --tables-for gov --with-extraction --max-calls 0` into the copy, deleting nothing | **Pass.** Tables id `fec2a2b12e31…` again. All 37 files of the snapshot's tables directory, including the per-table reports, had the same SHA-256 before and after. In a second copy, the 3B table files and the manifest were deleted, and the build wrote them again byte-identical (manifest SHA-256 = tables id). |
| T2 | Each suite run twice in fresh processes with `--max-calls 0` | **Pass for every set run.** Byte-identical `results.jsonl` and `compile.json` for: the Q2 runs (p3-typed test and dev, baseline-linear test), the Q1 runs (gov and research), and the SQL-guard (120 of 120) and applicability (51 of 51, `fr_documents`) probe sets on the 3B build. Against the original model-calling Q2 runs, every field of every row is equal except `notional_cost_usd`, and `latency_s` for the baseline: a cache hit records these as 0 and null. Re-running `p3-q2` on the reruns gives the same summary. The leak, equivalence, fail-closed and MCP probe sets were not re-run on the 3B build (see "3B: probes"). |
| T3 | Every provenance span of every table of the promoted build, re-sliced with `provenance.reslice` | **Pass: 32,889 of 32,889**, including all 15,162 model-value quotes |
| T4 | Every stored value carries a `spec_id` | **Pass: 60,295 of 60,295.** The 22,121 non-null values without a span are computed values (entity tables, FR agency and reference ids, `status`, and the drawbridge `version` and `draw`), each with its `spec_id`. |
| T5 | `tests/store/test_tables_extract.py::test_a_spec_change_reextracts_only_its_group` | **Pass** |
| T6 | `tests/store/test_tables_gate.py::test_gate_refuses_too_many_flips_and_keeps_head` | **Pass** |

## 3B: probes (Step 9, not run)

Step 9 asks for `tables-leak`, `tables-equivalence` and `tables-applicability` on gov with the 3B
build. The applicability set should include at least 50 probes on `drawbridge_sections` and
`drawbridge_bridges`, and the reference stores should read the extraction from the cache with
`--max-calls 0`. The probe CLI cannot do either without code changes, so these probes were not
run:

- **Reference stores lack the drawbridge tables.** `References.path_of` in `src/adr_eval/probes/tables.py` builds each view's reference store with `build_tables(path, corpus)`, a metadata-only build. No option builds the extraction tables there from the cache. A leak or equivalence call on a drawbridge table would compare the store with a reference that has no such table, so its verdict would mean nothing.
- **The applicability probes cover `fr_documents` only.** `adr-eval probes tables-applicability` calls `applicability_probes(store, n=…)` with the default `tables=("fr_documents",)`. No option adds the drawbridge tables. The function's docstring says they "join once they exist", but no later task added them.

Both are defects of the probe code (Task 7's). The fix would build reference stores with
`with_extraction=True` and a zero-call budget, and pass the drawbridge tables to
`applicability_probes`. After it, the three sets can be run from the cache with no calls.

The 3A probe results above still stand for the 3A tables. Two probe sets need no reference
store, and they were run on the 3B build twice each (T2). The SQL guard passed 120 of 120. The
applicability probes on `fr_documents` passed 51 of 51, byte-identical to the 3A run.

## Files

- [`run-summaries/`](run-summaries/) holds the run and probe summaries:
  - 3A: the two Q1 `p3-typed` runs and the table probe summaries (`probes-tables-*-20261120T19*`, `tables-7-checks`). Each Q1 run has `config.json`, `compile.json`, `report.json`, `report.md` and `q1-<baseline>.json`, the aggregated `adr-eval p3-q1 --summary` form.
  - 3B: the three gov-tables runs (`gov-tables-p3-typed-test-…`, `gov-tables-p3-typed-dev-…`, `gov-tables-baseline-linear-test-…`), each with `config.json`, `compile.json`, `report.json` and `report.md`.
  - 3B: `q2-gov-tables.json`, the aggregated `adr-eval p3-q2 --summary` form.
  - 3B: the two probe sets re-run on the 3B build (`probes-tables-sql-gov-20261120T235517`, `probes-tables-applicability-gov-20261120T235528`).
  - 3B: `tables-11-checks/checks.json`, the aggregate E1, E2, regex, Q2-attribution and T1–T6 figures.

  No committed file names an item. Per-item rows (`results.jsonl`), the full Q1 and Q2 outputs and the probe sets stay local in `runs/`.
- [`golden/gov-tables/v0.1/`](../../golden/gov-tables/v0.1/) holds the gov-tables items, which are committed like gov v0.1's (US government sources).
- [`entity-samples.json`](entity-samples.json) holds the entity cluster counts, the largest clusters and the seeded samples of both builds.
- [`waterway-links.json`](waterway-links.json) holds the linked and unlinked drawbridge titles.
