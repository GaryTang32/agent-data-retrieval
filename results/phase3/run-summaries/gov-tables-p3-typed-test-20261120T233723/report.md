# Report: gov-tables-p3-typed-test-20261120T233723

Corpus `gov`, system `p3-typed`, split `test`, 1 repeats, 97 rows, status `complete`. Generator `claude-sonnet-5-5`, no judge. Metrics version 2.

Question types: count_filter only.

Golden set `gov-tables`: generated table queries, no judge call, exact scoring.

Answers from the typed tables `fec2a2b12e318fcba0c350edac2e61acdbcc3bdccaad8f8d08c9290014270230` with the generated query: no retrieval, no answer or judge call, exact scoring.

Values in brackets are 95% CIs (percentile bootstrap, 10,000 resamples). End to end: cluster bootstrap over items of the statistic shown, using every repeat (items are resampled with all their rows); none where fewer than 2 items contribute.

## End to end

| n | accuracy | error | abstained | partial | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|---|---|
| 97 | 0.680 [0.588, 0.773] | 0.000 | 0.000 | 0.000 | 0.361 [0.175, 0.546] | -0.278 [-0.649, 0.093] | -2.196 [-3.124, -1.268] |

| stratum | n | accuracy | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|
| qtype count_filter | 97 | 0.680 [0.588, 0.773] | 0.361 [0.175, 0.546] | -0.278 [-0.649, 0.093] | -2.196 [-3.124, -1.268] |
| rarity none | 97 | 0.680 [0.588, 0.773] | 0.361 [0.175, 0.546] | -0.278 [-0.649, 0.093] | -2.196 [-3.124, -1.268] |
| none/count_filter | 97 | 0.680 [0.588, 0.773] | 0.361 [0.175, 0.546] | -0.278 [-0.649, 0.093] | -2.196 [-3.124, -1.268] |

Citation precision –, evidence cited –. Tokens 255701 in / 5802 out. Spent $0.0000 in total (authoritative: every call, including any row dropped at a budget stop); rows written sum to $0.0000. Latency p50 – s, p95 – s (uncached calls: 0). Errors: 0.

## Determinism

Retrieval identity: not measured (1 repeat); answer agreement: not measured; pass^1 0.680.

## G2 query understanding

Route accuracy over rows whose gold op is not `abstain`; record match over rows whose gold query can be executed on the records; entity F1 over rows whose gold query lists entities. Per-field hits are kept in report.json as diagnostics.

| route accuracy | n | record match | n | entity F1 | n |
|---|---|---|---|---|---|
| – | 0 | – | 0 | – | 0 |

## G1 compile

Tables `fec2a2b12e318fcba0c350edac2e61acdbcc3bdccaad8f8d08c9290014270230` (10 tables; the manifest is in compile.json).

## Judge

No judge call: every answer is scored exactly.
