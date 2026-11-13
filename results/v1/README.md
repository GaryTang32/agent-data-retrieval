# Phase 0 baseline results (1 repeat)

> **Work in progress.** These are the recorded numbers for the flat hybrid baseline. They are the yardstick later phases must beat, not a claim about the toolkit, which is not built yet. Several of the metrics have known artefacts: read the limits at the end before quoting any figure.

## What was run

- **Recorded:** 12 November 2026, from saved model calls plus 29 new ones. This replaces the first recording of 11 November, made before the final review's fixes (see "Changes since the first recording").
- **Split:** test. **Repeats:** 1.
- **Systems:** `baseline-rrf` (BM25 + dense, reciprocal rank fusion, k=60) and `baseline-linear` (BM25 + dense, linear fusion with a weight tuned on the dev split).
- **Generator:** `claude-sonnet-5-5`. **Judge:** `claude-opus-5-5`. Both ran through Claude Code on a subscription, so the recorded spend is $0. Sampling temperature is not pinned.
- **Golden sets:** v0.1. **Rows:** 2,072 across six runs; 1 ended in a model error; 133 used a recovered reply (explained below).

| Corpus | Test items | Chunks | Index fingerprint | Linear weight `w` |
|---|---|---|---|---|
| gov | 242 | 5,056 | `fe978fc9c5ee…` | 1.00 |
| research | 222 | 7,305 | `150af34ab34d…` | 1.00 |
| bench | 572 | 5,587 | `62835d2b1430…` | 0.70 |

`w` is the weight on BM25; `1 − w` is the weight on the dense index. A weight of 1.00 means the tuned system uses BM25 alone.

## End to end

Accuracy counts a row as correct only when the answer is fully correct. The penalised score gives +1 for correct, 0 for abstained and −t/(1−t) for a wrong **or partially correct** answer, so those cost 1, 3 or 9 points at t = 0.5, 0.75 and 0.9; error rows are left out of it. Brackets are 95% bootstrap intervals over items.

| Corpus | System | n | Accuracy | Wrong | Abstained | Partial | Error | Penalised t=0.5 | t=0.75 | t=0.9 |
|---|---|---|---|---|---|---|---|---|---|---|
| gov | RRF | 242 | 0.702 [0.645, 0.760] | 0.169 | 0.095 | 0.033 | 0.000 | 0.500 | 0.095 | -1.120 |
| gov | Linear | 242 | 0.731 [0.674, 0.785] | 0.182 | 0.041 | 0.045 | 0.000 | 0.504 | 0.050 | -1.314 |
| research | RRF | 222 | 0.703 [0.640, 0.761] | 0.167 | 0.113 | 0.018 | 0.000 | 0.518 | 0.149 | -0.959 |
| research | Linear | 222 | 0.806 [0.752, 0.856] | 0.131 | 0.041 | 0.023 | 0.000 | 0.653 | 0.347 | -0.572 |
| bench | RRF | 572 | 0.720 [0.682, 0.755] | 0.054 | 0.103 | 0.121 | 0.002 | 0.546 | 0.196 | -0.855 |
| bench | Linear | 572 | 0.801 [0.767, 0.834] | 0.042 | 0.056 | 0.101 | 0.000 | 0.657 | 0.371 | -0.490 |

## Retrieval (questions with evidence; `insufficient` excluded)

| Corpus | System | n | Recall@10 | nDCG@10 | MRR |
|---|---|---|---|---|---|
| gov | RRF | 213 | 0.683 [0.621, 0.743] | 0.500 [0.449, 0.551] | 0.447 [0.394, 0.501] |
| gov | Linear | 213 | 0.775 [0.719, 0.828] | 0.584 [0.537, 0.632] | 0.528 [0.477, 0.579] |
| research | RRF | 180 | 0.654 [0.582, 0.723] | 0.502 [0.438, 0.564] | 0.465 [0.399, 0.530] |
| research | Linear | 180 | 0.856 [0.802, 0.905] | 0.710 [0.654, 0.764] | 0.676 [0.616, 0.734] |
| bench | RRF | 517 | 0.859 [0.828, 0.887] | 0.458 [0.429, 0.487] | 0.756 [0.721, 0.789] |
| bench | Linear | 517 | 0.922 [0.900, 0.943] | 0.529 [0.500, 0.559] | 0.849 [0.821, 0.876] |

### Linear minus RRF (paired over the same items)

| Corpus | Metric | n | Mean difference | 95% CI | p (Holm) |
|---|---|---|---|---|---|
| gov | penalised@0.75 | 242 | -0.045 | [-0.182, 0.087] | 0.511 |
| gov | ndcg@10 | 213 | 0.084 | [0.049, 0.120] | < 0.0008 |
| gov | recall@10 | 213 | 0.092 | [0.052, 0.134] | < 0.0008 |
| research | penalised@0.75 | 222 | 0.198 | [0.045, 0.360] | 0.015 |
| research | ndcg@10 | 180 | 0.208 | [0.157, 0.260] | < 0.0008 |
| research | recall@10 | 180 | 0.203 | [0.140, 0.266] | < 0.0008 |
| bench | penalised@0.75 | 571 | 0.173 | [0.088, 0.263] | < 0.0008 |
| bench | ndcg@10 | 517 | 0.071 | [0.053, 0.089] | < 0.0008 |
| bench | recall@10 | 517 | 0.062 | [0.040, 0.087] | < 0.0008 |

Correct-versus-not, McNemar exact test (A = RRF, B = linear):

- **gov:** McNemar exact on correct vs not: only A correct 10, only B correct 17, p = 0.2478 (Holm 0.4956).
- **research:** McNemar exact on correct vs not: only A correct 4, only B correct 27, p = 0.0000 (Holm 0.0001).
- **bench:** McNemar exact on correct vs not: only A correct 12, only B correct 58, p = 0.0000 (Holm 0.0000).

## What the baseline shows

1. **Tuned linear fusion retrieves better than RRF on all three corpora.** Recall@10 is higher by 0.06 to 0.20 and nDCG@10 by 0.07 to 0.21, all significant after Holm correction. Accuracy is also significantly higher on research and bench (McNemar p = 0.00003 and p < 0.000001); on gov the accuracy difference is not significant (p = 0.25).
2. **On gov and research the tuned weight is 1.00, so the "linear" system is BM25 alone.** Read this as "the dense index adds little here", not "adds nothing": the review found the gov dev score almost flat between weights 0.85 and 1.00 (nDCG 0.6005 to 0.6019 on 42 dev items in the first recording), so 1.00 is a noise-level choice. On bench the weight is 0.70.
3. **A flat baseline cannot count.** On gov, count and filter questions score 0 of 27 with RRF and 2 of 27 with linear. Most need more records than ten retrieved chunks can hold; 9 of the 27 need ten records or fewer, and most of those fail too. This is the gap the typed database (Phase 3) is meant to close.
4. **Whole structured queries almost never match the gold query** (0.2% on bench, 4% on research, 7% on gov), but this is only partly a model weakness. See "G2 measures gold conventions too" below.
5. **Rare-term questions are not harder for this baseline.** Leaving out count and filter questions (all of which sit in the common tier), the rarest tier scores higher than the most common tier in four of the six runs and lower in two. The raw gap between tiers on gov and research is mostly the count and filter questions.
6. **Every run scores below zero at t = 0.9**, where a wrong or partial answer costs 9 points. On gov and research the loss comes mainly from wrong answers given where abstaining would have been better. On bench it comes mainly from partially correct answers, which are penalised like wrong ones.

## Accuracy by question type

| Corpus | Question type | n | RRF | Linear |
|---|---|---|---|---|
| gov | count_filter | 27 | 0.000 | 0.074 |
| gov | factoid | 37 | 0.865 | 0.892 |
| gov | id_lookup | 36 | 0.639 | 0.722 |
| gov | insufficient | 29 | 0.966 | 0.931 |
| gov | overview | 36 | 0.778 | 0.694 |
| gov | policy_asof | 34 | 0.676 | 0.706 |
| gov | procedure | 43 | 0.837 | 0.930 |
| research | count_filter | 27 | 0.222 | 0.593 |
| research | factoid | 40 | 0.875 | 0.975 |
| research | id_lookup | 39 | 0.769 | 0.872 |
| research | insufficient | 42 | 0.762 | 0.714 |
| research | overview | 35 | 0.600 | 0.686 |
| research | procedure | 39 | 0.821 | 0.923 |
| bench | factoid | 325 | 0.763 | 0.846 |
| bench | id_lookup | 34 | 0.765 | 0.971 |
| bench | insufficient | 55 | 0.945 | 0.964 |
| bench | overview | 119 | 0.513 | 0.580 |
| bench | procedure | 39 | 0.641 | 0.718 |

## Rare versus common knowledge

Generated items are tiered by how many documents contain their key term: `tail` is at or below the lower third of that count, `head` at or above the upper third, `torso` between. Ties collapse the tiers, so they are not equal thirds. Items whose right answer is to abstain, and the benchmark's own questions on bench, have no tier. Every count and filter question falls in `head`, and those are the questions the baseline fails, so the table shows the head tier with and without them.

| Corpus | System | Head n | Head accuracy | Head without count_filter (n) | Torso n | Torso accuracy | Tail n | Tail accuracy |
|---|---|---|---|---|---|---|---|---|
| gov | RRF | 109 | 0.514 | 0.683 (82) | 18 | 0.889 | 86 | 0.814 |
| gov | Linear | 109 | 0.596 | 0.768 (82) | 18 | 0.889 | 86 | 0.802 |
| research | RRF | 113 | 0.637 | 0.767 (86) | 0 | – | 67 | 0.776 |
| research | Linear | 113 | 0.814 | 0.884 (86) | 0 | – | 67 | 0.851 |
| bench | RRF | 72 | 0.708 | 0.708 (72) | 0 | – | 78 | 0.718 |
| bench | Linear | 72 | 0.875 | 0.875 (72) | 0 | – | 78 | 0.808 |

## Other tracks

| Corpus | G1 span containment | G2 store | G2 op | G2 filters | G2 entities | G2 as_of | G2 whole query | G2 execution match (n) |
|---|---|---|---|---|---|---|---|---|
| gov | 0.993 | 0.855 | 0.343 | 0.500 | 0.095 | 0.979 | 0.070 | 1.000 (27) |
| research | 1.000 | 0.635 | 0.450 | 0.788 | 0.086 | 0.986 | 0.041 | 0.963 (27) |
| bench | 0.202 | 0.876 | 0.248 | 0.657 | 0.028 | 0.934 | 0.002 | – (0) |

- **G1 span containment** is the share of gold evidence spans that fit inside one chunk. It is low on bench because the benchmark's own questions cite whole documents. For generated overview and procedure items the evidence is exactly one baseline chunk, so this figure is satisfied by construction for the baseline and would count against a different chunker.
- **G2** is zero-shot conversion of the question into a structured query, scored per field against the gold query. It is the same for both systems. See the limits below before reading it as query understanding.
- **Determinism:** with one repeat, retrieval identity and answer agreement are not measured in these runs. Separately, the final review reloaded each saved index in a fresh process and re-retrieved every test question of the first recording: all 2,080 ranked lists matched on ids and scores.

| Corpus | System | Judge vs exact scorer: agreement | κ (3 labels) | κ (partial counted as incorrect) | n | Judge self-consistency (n) | Citation precision | Evidence cited | Tokens in | Tokens out | Median latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gov | RRF | 0.918 | 0.629 | 0.834 | 49 | 0.979 (141) | 0.465 | 0.695 | 3,521,426 | 108,950 | 5.8 |
| gov | Linear | 0.877 | 0.518 | 0.755 | 57 | 0.979 (146) | 0.499 | 0.734 | 3,557,323 | 111,016 | 7.2 |
| research | RRF | 0.968 | 0.870 | 0.912 | 62 | 0.968 (93) | 0.591 | 0.761 | 3,509,471 | 87,129 | – |
| research | Linear | 1.000 | 1.000 | 1.000 | 75 | 0.990 (96) | 0.696 | 0.895 | 3,571,037 | 88,963 | – |
| bench | RRF | 0.967 | 0.318 | 0.651 | 30 | 0.988 (427) | 0.915 | 0.947 | 8,993,028 | 306,080 | 6.3 |
| bench | Linear | 0.974 | 0.000 | 0.000 | 38 | 0.991 (447) | 0.934 | 0.963 | 9,087,936 | 307,786 | 5.8 |

The judge-versus-exact columns compare the judge with the exact scorer on number, set and identifier answers. Agreement is the raw share of rows where they agree once the judge's "partial" is counted as incorrect. κ is low where almost every row has the same label (bench linear: the judge said correct on all rows), which is a property of κ, not a sign of disagreement.

## Changes since the first recording

The first recording (11 November) had 2,080 rows and 26 model errors. The final review led to four changes, and the runs were recorded again from saved model calls:

- **Self-corrected replies are now recovered.** In the first recording, 25 of the 26 errors were replies the strict parser rejected: 15 wrote a JSON answer, then a correction and a second JSON object; 10 wrote a sentence before the JSON. Runs now take the last JSON object that has the required fields and mark the row (`json_recovered`). In this recording 133 rows are marked: 108 in query conversion, 24 in the answer, 3 in judge replies. One error remains, an answer of the wrong type. Golden-set generation still uses the strict parser.
- **The exact scorer honours accepted variants** for number and set answers ("13 pages" for 13).
- **Nine gov questions were removed**: the review found five "not in the corpus" questions answerable from the corpus and four partly answerable. Only about 20 of the 50 such gov questions were checked by hand, so more may remain.
- **Five items were added** (four on gov, one on bench): number answers with unit variants that the old scorer wrongly rejected during golden-set checks.

Accuracy rose by 0.01 to 0.03 on gov and research and by under 0.01 on bench. All changes are inside the first recording's intervals.

## Known artefacts in the metrics

Unless stated otherwise, these were measured by the final review on the first recording. They are properties of how this harness scores, not of the baseline, and they are left as they are until Phase 1 decides the definitions.

- **Gov ranks are understated by duplicate text.** More than half of the gov chunks have byte-identical text in another dated version of the same regulation, and only the copy named in the golden item counts as relevant. Counting an identical copy as relevant would raise gov MRR from 0.44 to 0.57 (RRF) and from 0.52 to 0.66 (linear), citation precision from 0.45 to 0.68 and from 0.49 to 0.73, and evidence-cited from 0.69 to 0.81 and from 0.73 to 0.86. Recall@10 barely moves. A later phase that only deduplicates versions would gain about 0.13 MRR on gov without retrieving anything better.
- **Bench nDCG@10 cannot reach 1.** The benchmark's own questions cite whole documents, and a chunk earns credit in proportion to how much of the cited span it covers. The attainable ceiling on the bench test split is about 0.65, so the recorded 0.46 and 0.53 are about 71% and 82% of what is attainable. The ceiling depends on chunk size, which Phase 1 changes.
- **The exact scorer for identifiers is stricter than the judge.** In this recording, in 15 rows the exact scorer marks an answer wrong and the judge marks the same answer correct; there are none the other way round. Typical case: "47 CFR § 73.1740" against the gold "73.1740". These rows carry the full penalty.
- **G2 measures gold conventions too.** Gold queries use `lookup` for factoid questions, while the conversion prompt describes `explain` as the operation for facts; questions whose right answer is to abstain have a gold store and operation that cannot be known before retrieval; most bench gold queries have an empty entity list; and entities are compared as exact sets of free-text phrases. The per-field numbers are comparable between systems that use the same prompt, but they are not a clean measure of query understanding.
- **Rarity tiers are uneven.** Tied term counts collapse the tiers (gov 109 head, 18 torso, 86 tail; research has no torso).
- **Six of the twenty gov policy pairs put the same question in both dev and test**, because the split is by item, not by pair.

## Read with care

- **Questions favour keyword search.** Generated questions were written by a model reading the source section, so they share its vocabulary. This is a likely reason BM25 does so well, and findings 1 and 2 may not hold for questions written without seeing the text.
- **Same-family judge.** Sonnet generates and Opus judges. Agreement with human labels has not been measured.
- **The judge also helped select the golden items.** Free-text items were accepted when the same judge called a re-answer correct, which could make those items easier for this judge.
- **Golden items are not human-vetted.** They are model-drafted and code-checked. A reviewer read 41 gov and research items against their sources and found the answers correct, but also found weak questions: some overview questions say "this section" without naming it, five research overview items come from catalogue rows, and five gov policy pairs ask about typography.
- **One repeat.** Answer agreement across repeats is not measured, and temperature is not pinned under Claude Code.
- **Bench is a 2,000-document subset** of EnterpriseRAG-Bench with its own questions, so these numbers are not comparable to results on the full benchmark.
- **Reproducing these runs needs local data.** The research corpus needs the local PDF library, the research and bench golden sets are local only, and the gov corpus is fetched from live government sites that may change.

## Files

Each run folder holds `config.json` (models, prompt hashes, snapshot, index fingerprint, golden-set hash, fusion settings), `report.json`, `report.md` and `compile.json`. The RRF folders also hold the comparison against the linear run. Per-row results stay local in `runs/` because bench rows contain benchmark text.

```
adr-eval run gov --system baseline-rrf --split test --repeats 1
adr-eval report <rrf_run_id> --compare <linear_run_id>
```
