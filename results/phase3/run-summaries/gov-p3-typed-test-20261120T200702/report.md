# Report: gov-p3-typed-test-20261120T200702

Corpus `gov`, system `p3-typed`, split `test`, 1 repeats, 27 rows, status `complete`. Generator `claude-sonnet-5-5`, judge `claude-opus-5-5`. Metrics version 2.

Question types: count_filter only.

Answers from the typed tables `2678b8da96338df9f72e3be98aa66d24b24164c290a422bb177f7095a9e1d5f8` with the generated query: no retrieval, no answer or judge call, exact scoring.

Values in brackets are 95% CIs (percentile bootstrap, 10,000 resamples). End to end: cluster bootstrap over items of the statistic shown, using every repeat (items are resampled with all their rows); none where fewer than 2 items contribute.

## End to end

| n | accuracy | error | abstained | partial | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|---|---|
| 27 | 1.000 [1.000, 1.000] | 0.000 | 0.000 | 0.000 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |

| stratum | n | accuracy | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|
| qtype count_filter | 27 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| rarity head | 27 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| head/count_filter | 27 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |

Citation precision –, evidence cited –. Tokens 55027 in / 1757 out. Spent $0.0000 in total (authoritative: every call, including any row dropped at a budget stop); rows written sum to $0.0000. Latency p50 – s, p95 – s (uncached calls: 0). Errors: 0.

## Determinism

Retrieval identity: not measured (1 repeat); answer agreement: not measured; pass^1 1.000.

## G2 query understanding

Route accuracy over rows whose gold op is not `abstain`; record match over rows whose gold query can be executed on the records; entity F1 over rows whose gold query lists entities. Per-field hits are kept in report.json as diagnostics.

| route accuracy | n | record match | n | entity F1 | n |
|---|---|---|---|---|---|
| 1.000 | 27 | 1.000 | 27 | 0.617 | 27 |

## G1 compile

Tables `2678b8da96338df9f72e3be98aa66d24b24164c290a422bb177f7095a9e1d5f8` (8 tables; the manifest is in compile.json).

## Judge

No judge call: every answer is scored exactly.
