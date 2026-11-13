# Phase 0 baseline results (1 repeat)

> **Work in progress.** These are the recorded numbers for the flat hybrid baseline under **version 2 of the metric definitions**. They are the yardstick later phases must beat, not a claim about the toolkit, which is not built yet. The version 1 numbers and their write-up are in [`v1/`](v1/README.md); the section "Version 1 to version 2" lists every headline number that moved and why.

## What was run

- **Recorded:** 13 November 2026, from saved model calls plus 362 new ones (all in the gov linear run, whose tuned weight changed). Metric definitions: version 2 (`docs/superpowers/specs/2026-11-13-metric-definitions-design.md`).
- **Split:** test. **Repeats:** 1.
- **Systems:** `baseline-rrf` (BM25 + dense, reciprocal rank fusion, k=60) and `baseline-linear` (BM25 + dense, linear fusion with a weight tuned on the dev split).
- **Generator:** `claude-sonnet-5-5`. **Judge:** `claude-opus-5-5`. Both ran through Claude Code on a subscription, so the recorded spend is $0. Sampling temperature is not pinned.
- **Golden sets:** v0.1. **Rows:** 2,072 across six runs; 1 ended in a model error; 135 used a recovered reply: the model wrote its JSON with a correction or a sentence around it, and the run took the last complete JSON object.

| Corpus | Test items | Chunks | Index fingerprint | Linear weight `w` |
|---|---|---|---|---|
| gov | 242 | 5,056 | `fe978fc9c5ee…` | 0.85 |
| research | 222 | 7,305 | `150af34ab34d…` | 1.00 |
| bench | 572 | 5,587 | `62835d2b1430…` | 0.70 |

`w` is the weight on BM25; `1 − w` is the weight on the dense index. A weight of 1.00 means the tuned system uses BM25 alone.

## End to end

Accuracy counts a row as correct only when the answer is fully correct. The penalised score gives +1 for correct, 0 for abstained and −t/(1−t) for a wrong **or partially correct** answer, so those cost 1, 3 or 9 points at t = 0.5, 0.75 and 0.9; error rows are left out of it. Brackets are 95% bootstrap intervals over items.

| Corpus | System | n | Accuracy | Wrong | Abstained | Partial | Error | Penalised t=0.5 | t=0.75 | t=0.9 |
|---|---|---|---|---|---|---|---|---|---|---|
| gov | RRF | 242 | 0.719 [0.661, 0.773] | 0.153 | 0.095 | 0.033 | 0.000 | 0.533 | 0.161 | -0.955 |
| gov | Linear | 242 | 0.752 [0.698, 0.806] | 0.169 | 0.045 | 0.033 | 0.000 | 0.550 | 0.145 | -1.070 |
| research | RRF | 222 | 0.712 [0.653, 0.770] | 0.158 | 0.113 | 0.018 | 0.000 | 0.536 | 0.185 | -0.869 |
| research | Linear | 222 | 0.806 [0.752, 0.856] | 0.131 | 0.041 | 0.023 | 0.000 | 0.653 | 0.347 | -0.572 |
| bench | RRF | 572 | 0.720 [0.682, 0.755] | 0.054 | 0.103 | 0.121 | 0.002 | 0.546 | 0.196 | -0.855 |
| bench | Linear | 572 | 0.801 [0.767, 0.834] | 0.042 | 0.056 | 0.101 | 0.000 | 0.657 | 0.371 | -0.490 |

## Retrieval (questions with evidence; `insufficient` excluded)

| Corpus | System | n | Recall@10 | nDCG@10 | MRR | Coverage@10 | Tokens in top 10 |
|---|---|---|---|---|---|---|---|
| gov | RRF | 213 | 0.706 [0.646, 0.765] | 0.614 [0.557, 0.669] | 0.591 [0.531, 0.648] | 0.706 [0.646, 0.765] | 3,543 |
| gov | Linear | 213 | 0.771 [0.715, 0.824] | 0.691 [0.637, 0.742] | 0.671 [0.616, 0.726] | 0.771 [0.715, 0.824] | 3,534 |
| research | RRF | 180 | 0.654 [0.582, 0.723] | 0.502 [0.438, 0.564] | 0.465 [0.399, 0.530] | 0.654 [0.582, 0.723] | 3,729 |
| research | Linear | 180 | 0.856 [0.802, 0.905] | 0.710 [0.654, 0.764] | 0.676 [0.616, 0.734] | 0.856 [0.802, 0.905] | 3,752 |
| bench | RRF | 517 | 0.859 [0.828, 0.887] | 0.766 [0.734, 0.796] | 0.756 [0.721, 0.789] | 0.698 [0.666, 0.728] | 3,343 |
| bench | Linear | 517 | 0.922 [0.900, 0.943] | 0.854 [0.829, 0.878] | 0.849 [0.821, 0.876] | 0.782 [0.755, 0.809] | 3,352 |

### Linear minus RRF (paired over the same items)

| Corpus | Metric | n | Mean difference | 95% CI | p (Holm) |
|---|---|---|---|---|---|
| gov | penalised@0.75 | 242 | -0.017 | [-0.149, 0.107] | 0.810 |
| gov | ndcg@10 | 213 | 0.077 | [0.045, 0.110] | < 0.0010 |
| gov | recall@10 | 213 | 0.065 | [0.027, 0.103] | 0.002 |
| gov | coverage@10 | 213 | 0.065 | [0.027, 0.103] | 0.002 |
| research | penalised@0.75 | 222 | 0.162 | [0.014, 0.315] | 0.037 |
| research | ndcg@10 | 180 | 0.208 | [0.157, 0.260] | < 0.0010 |
| research | recall@10 | 180 | 0.203 | [0.140, 0.266] | < 0.0010 |
| research | coverage@10 | 180 | 0.203 | [0.140, 0.266] | < 0.0010 |
| bench | penalised@0.75 | 571 | 0.173 | [0.088, 0.263] | < 0.0010 |
| bench | ndcg@10 | 517 | 0.088 | [0.067, 0.110] | < 0.0010 |
| bench | recall@10 | 517 | 0.062 | [0.040, 0.087] | < 0.0010 |
| bench | coverage@10 | 517 | 0.084 | [0.064, 0.106] | < 0.0010 |

Correct-versus-not, McNemar exact test (A = RRF, B = linear):

- **gov:** McNemar exact on correct vs not: only A correct 8, only B correct 16, p = 0.1516 (Holm 0.3032).
- **research:** McNemar exact on correct vs not: only A correct 4, only B correct 25, p = 0.0001 (Holm 0.0002).
- **bench:** McNemar exact on correct vs not: only A correct 12, only B correct 58, p = 2.2 × 10⁻⁸ (Holm 2.2 × 10⁻⁸).

## What the baseline shows

1. **Tuned linear fusion retrieves better than RRF on all three corpora.** Recall@10 is higher by 0.06 to 0.20, nDCG@10 by 0.08 to 0.21 and coverage@10 by 0.06 to 0.20, all significant after Holm correction. Accuracy is also significantly higher on research and bench (McNemar p = 0.0001 and p < 0.000001); on gov the accuracy difference is not significant (p = 0.15).
2. **Tuning puts most or all of the weight on BM25.** The tuned weight on BM25 is 1.00 on research, 0.85 on gov and 0.70 on bench. Under version 1 the gov weight was 1.00, and the earlier review found the version 1 dev score almost flat between 0.85 and 1.00. On the test split under version 2, a weight of 1.00 would score slightly higher than the tuned 0.85 (nDCG@10 0.700 against 0.691), so the move is tuning noise, not a gain. Read it as "the dense index adds little on gov and research".
3. **A flat baseline cannot count.** On gov, count and filter questions score 0 of 27 with RRF and 2 of 27 with linear. This is the gap the typed database (Phase 3) is meant to close.
4. **The model usually picks the right kind of query, and names entities loosely.** The generated query has the right route on 84% of gov questions, 66% on research and 87% on bench. Record queries return the right records on 27 of 27 gov questions and 26 of 27 on research. Entity names get about half credit (0.53 to 0.58). The weak spots are procedure questions routed as plain facts (31 of 35 route misses on gov, 23 of 61 on research), research identifier questions sent to the record store when the answer is in the prose (17 of 61), and, on bench, fact and overview questions routed as procedures (31 of 69).
5. **Rare-term questions are neither clearly harder nor easier.** Leaving out count and filter questions (all of which sit in the common tier), the rarest tier scores higher than the most common tier in two of the six runs and lower in four. The gaps are about 0.03 or less except on gov RRF (rare higher by 0.09) and bench linear (common higher by 0.07).
6. **Every run scores below zero at t = 0.9**, where a wrong or partial answer costs 9 points. On gov and research the loss comes mainly from wrong answers given where abstaining would have been better. On bench it comes mainly from partially correct answers, which are penalised like wrong ones.

## Accuracy by question type

| Corpus | Question type | n | RRF | Linear |
|---|---|---|---|---|
| gov | count_filter | 27 | 0.000 | 0.074 |
| gov | factoid | 37 | 0.892 | 0.865 |
| gov | id_lookup | 36 | 0.722 | 0.861 |
| gov | insufficient | 29 | 0.966 | 0.931 |
| gov | overview | 36 | 0.778 | 0.722 |
| gov | policy_asof | 34 | 0.676 | 0.706 |
| gov | procedure | 43 | 0.837 | 0.930 |
| research | count_filter | 27 | 0.222 | 0.593 |
| research | factoid | 40 | 0.875 | 0.975 |
| research | id_lookup | 39 | 0.821 | 0.872 |
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
| gov | RRF | 109 | 0.541 | 0.720 (82) | 18 | 0.944 | 86 | 0.814 |
| gov | Linear | 109 | 0.624 | 0.805 (82) | 18 | 1.000 | 86 | 0.802 |
| research | RRF | 113 | 0.655 | 0.791 (86) | 0 | – | 67 | 0.776 |
| research | Linear | 113 | 0.814 | 0.884 (86) | 0 | – | 67 | 0.851 |
| bench | RRF | 72 | 0.708 | 0.708 (72) | 0 | – | 78 | 0.718 |
| bench | Linear | 72 | 0.875 | 0.875 (72) | 0 | – | 78 | 0.808 |

## Other tracks

| Corpus | G1 span containment | Evidence spans with copies | Right kind of query (n) | Record match (n) | Entities, partial credit (n) |
|---|---|---|---|---|---|
| gov | 0.993 | 111 of 711 | 0.836 (213) | 1.000 (27) | 0.584 (213) |
| research | 1.000 | 0 of 367 | 0.661 (180) | 0.963 (27) | 0.565 (180) |
| bench | 0.202 | 0 of 741 | 0.867 (517) | – (0) | 0.526 (150) |

- **G1 span containment** is the share of gold evidence spans that fit inside one chunk. It is low on bench because the benchmark's own questions cite whole documents. For generated overview and procedure items the evidence is exactly one baseline chunk, so this figure is satisfied by construction for the baseline and would count against a different chunker.
- **Evidence spans with copies** counts the test questions' evidence spans whose text, with 200 characters of context either side, also appears in another document. Retrieving a copy counts as retrieving the evidence, except for questions with an as-of date.
- **Right kind of query** is whether the generated query has the same route as the gold query (a record count, list or lookup; a fact in prose; a procedure). Questions whose right answer is to abstain are left out. **Record match** is whether a record query returns the same records as the gold query. **Entities** gives partial credit for overlapping names, on questions whose gold query lists entities. All three are the same for both systems.
- **Determinism:** with one repeat, retrieval identity and answer agreement are not measured in these runs.

| Corpus | System | Judge vs exact scorer: agreement | κ (3 labels) | κ (partial counted as incorrect) | n | Judge self-consistency (n) | Citation precision | Evidence cited | Median latency (s) |
|---|---|---|---|---|---|---|---|---|---|
| gov | RRF | 1.000 | 0.766 | 1.000 | 49 | 0.979 (141) | 0.716 | 0.816 | – |
| gov | Linear | 0.982 | 0.664 | 0.962 | 55 | 0.986 (147) | 0.737 | 0.851 | 6.8 |
| research | RRF | 1.000 | 0.954 | 1.000 | 62 | 0.968 (93) | 0.591 | 0.761 | – |
| research | Linear | 1.000 | 1.000 | 1.000 | 75 | 0.990 (96) | 0.696 | 0.895 | – |
| bench | RRF | 0.967 | 0.318 | 0.651 | 30 | 0.988 (427) | 0.915 | 0.947 | – |
| bench | Linear | 0.974 | 0.000 | 0.000 | 38 | 0.991 (447) | 0.934 | 0.963 | – |

## Version 1 to version 2

Each cell shows the version 1 value, then the version 2 value; a single value means no change. Both recordings use the same golden sets and prompts, and the same saved model calls except on gov linear, where the 191 questions whose top 10 changed were answered again.

| Corpus | System | Accuracy | Recall@10 | nDCG@10 | MRR | Citation precision | Evidence cited | Penalised t=0.75 | Linear weight |
|---|---|---|---|---|---|---|---|---|---|
| gov | RRF | 0.702 → 0.719 | 0.683 → 0.706 | 0.500 → 0.614 | 0.447 → 0.591 | 0.465 → 0.716 | 0.695 → 0.816 | 0.095 → 0.161 | – |
| gov | Linear | 0.731 → 0.752 | 0.775 → 0.771 | 0.584 → 0.691 | 0.528 → 0.671 | 0.499 → 0.737 | 0.734 → 0.851 | 0.050 → 0.145 | 1.00 → 0.85 |
| research | RRF | 0.703 → 0.712 | 0.654 | 0.502 | 0.465 | 0.591 | 0.761 | 0.149 → 0.185 | – |
| research | Linear | 0.806 | 0.856 | 0.710 | 0.676 | 0.696 | 0.895 | 0.347 | 1.00 |
| bench | RRF | 0.720 | 0.859 | 0.458 → 0.766 | 0.756 | 0.915 | 0.947 | 0.196 | – |
| bench | Linear | 0.801 | 0.922 | 0.529 → 0.854 | 0.849 | 0.934 | 0.963 | 0.371 | 0.70 |

Why each number moved:

| Change in the definitions | What moved |
|---|---|
| **Identical copies of the evidence count** (not for questions with an as-of date). 111 of the 711 gov test evidence spans have a copy in another dated version; research and bench have none. | Gov only: Recall@10, MRR, nDCG@10, citation precision and evidence cited all rise. Gov MRR goes from 0.45 to 0.59 (RRF) and from 0.53 to 0.67 (linear); citation precision from 0.47 to 0.72 and from 0.50 to 0.74 |
| **nDCG@10 gives full credit to any chunk that touches the evidence.** Version 1 gave credit in proportion to the share of the evidence a chunk covered, which capped bench at about 0.65. | Bench nDCG@10 goes from 0.46 to 0.77 (RRF) and from 0.53 to 0.85 (linear). Research is unchanged because its evidence fits in one chunk; on gov the rise comes from the copies |
| **Coverage@10 and tokens in the top 10 are new.** Coverage is the share of the evidence's characters inside the top 10 chunks. | New columns; nothing to compare |
| **Identifier answers match as whole identifiers.** "47 CFR § 73.1740" is now correct for the gold "73.1740". | Accuracy and the penalised scores rise on gov RRF (4 answers) and research RRF (2 answers). The rule also accounts for the whole accuracy rise on gov linear (5 answers): its regenerated answers gained 5 correct and lost 5 |
| **The linear weight is tuned on the new nDCG.** | The gov weight moves from 1.00 to 0.85, so gov linear retrieves differently: 191 of its 242 questions have a different top 10 and were answered again (362 new model calls). Under the same version 2 rules the new weight scores slightly lower than 1.00 on every retrieval and citation figure (Recall@10 0.771 against 0.780, nDCG@10 0.691 against 0.700, MRR 0.671 against 0.681, citation precision 0.737 against 0.768). The rises shown for gov linear in the table above come from the copies rule, not from the new weight |
| **Query understanding is scored by route, record match and entities with partial credit.** Version 1 compared every field for exact equality. | The version 1 figures (whole query 0.2% to 7%) are replaced, not moved; they remain in each `report.json` as diagnostics |
| **Coverage@10 joins the system comparison.** | Coverage@10 is added as a fifth test. The comparison p-values also change because the outcomes and retrieval scores above changed: the research accuracy gap narrows (McNemar p 0.00003 to 0.0001) and the gov Recall@10 gap between the systems falls from 0.092 to 0.065 |

What did not change: retrieval itself for five of the six runs, every prompt, the golden sets, and all research linear figures.

## Limits that remain

- **Questions favour keyword search.** Generated questions were written by a model reading the source section, so they share its vocabulary. Findings 1 and 2 may not hold for questions written without seeing the text.
- **Coverage@10 rises with chunk size**, because larger chunks put more text in the top 10. Compare it only between systems whose tokens in the top 10 are similar.
- **Five gov passages (four in the test split) have copies that the rule misses**, because text next to them was amended between versions and the rule requires 200 matching characters of context.
- **The identifier rule also accepts a sub-paragraph** ("(b)(4)(i)" for the gold "(b)(4)") and an answer that lists several identifiers including the right one. In these runs no accepted answer is a sub-paragraph. Two gov answers carry a second identifier as a supporting citation, and the judge agrees they are correct; none hedges between alternatives.
- **Query scores are not tied to answer quality.** Nothing uses the generated query yet, so a better score here has not been shown to give better answers. The entity match is lenient: one name's words must contain the other's.
- **Same-family judge.** Sonnet generates and Opus judges. Agreement with human labels has not been measured, and the judge also helped select the free-text golden items.
- **Golden items are not human-vetted**, and only about 20 of the 50 gov "not in the corpus" questions were checked by hand. Six of the twenty gov policy pairs put the same question in both dev and test. The rarity tiers are uneven (gov 109 head, 18 torso, 86 tail; research has no torso).
- **One repeat, and answers vary between calls.** Answer agreement across repeats is not measured, and temperature is not pinned under Claude Code. When gov linear's 191 questions were answered again, 16 outcomes changed (5 became correct, 5 stopped being correct). That is the same size as the difference between the two gov systems (8 against 16 questions), which finding 1 reports as not significant.
- **The judge-agreement κ on bench cannot be read on its own.** Bench linear shows κ 0.000 with 97% raw agreement, because the judge gave almost every row the same label. Use the raw agreement column.
- **Median latency covers new calls only.** In this recording that means the 191 regenerated gov linear answers; the other runs reused saved calls.
- **Bench is a 2,000-document subset** of EnterpriseRAG-Bench with its own questions, so these numbers are not comparable to results on the full benchmark.
- **Reproducing these runs needs local data.** The research corpus needs the local PDF library, the research and bench golden sets are local only, and the gov corpus is fetched from live government sites that may change.

## Files

`v2/` holds the six runs under version 2 and `v1/` the six under version 1. Each run folder holds `config.json` (models, prompt hashes, snapshot, index fingerprint, golden-set hash, fusion settings, metrics version), `report.json`, `report.md` and `compile.json`. The RRF folders also hold the comparison against the linear run. Per-row results stay local in `runs/` because bench rows contain benchmark text. Runs with different metrics versions cannot be compared with `adr-eval report --compare`.

```
adr-eval run gov --system baseline-rrf --split test --repeats 1
adr-eval report <rrf_run_id> --compare <linear_run_id>
```
