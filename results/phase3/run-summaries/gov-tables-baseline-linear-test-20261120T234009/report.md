# Report: gov-tables-baseline-linear-test-20261120T234009

Corpus `gov`, system `baseline-linear`, split `test`, 1 repeats, 97 rows, status `complete`. Generator `claude-sonnet-5-5`, no judge, linear w = 1.0. Metrics version 2.

Question types: count_filter only.

Golden set `gov-tables`: generated table queries, no judge call, exact scoring.

Values in brackets are 95% CIs (percentile bootstrap, 10,000 resamples). End to end: cluster bootstrap over items of the statistic shown, using every repeat (items are resampled with all their rows); none where fewer than 2 items contribute. G3 retrieval: bootstrap of the mean over items at repeat 0 (retrieval is deterministic); none where n < 2.

## End to end

| n | accuracy | error | abstained | partial | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|---|---|
| 97 | 0.237 [0.155, 0.320] | 0.000 | 0.588 | 0.000 | 0.062 [-0.062, 0.186] | -0.289 [-0.557, -0.031] | -1.340 [-2.062, -0.660] |

| stratum | n | accuracy | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|
| qtype count_filter | 97 | 0.237 [0.155, 0.320] | 0.062 [-0.062, 0.186] | -0.289 [-0.557, -0.031] | -1.340 [-2.062, -0.660] |
| rarity none | 97 | 0.237 [0.155, 0.320] | 0.062 [-0.062, 0.186] | -0.289 [-0.557, -0.031] | -1.340 [-2.062, -0.660] |
| none/count_filter | 97 | 0.237 [0.155, 0.320] | 0.062 [-0.062, 0.186] | -0.289 [-0.557, -0.031] | -1.340 [-2.062, -0.660] |

Citation precision 0.740, evidence cited 0.775. Tokens 1261179 in / 22911 out. Spent $0.0000 in total (authoritative: every call, including any row dropped at a budget stop); rows written sum to $0.0000. Latency p50 5.817 s, p95 8.973 s (uncached calls: 97). Errors: 0.

JSON recovered (a reply held several objects or prose; the last object with the required keys was used) in 2 row(s): answer 2.

## G3 retrieval (excluding `insufficient`)

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 97 | 0.283 [0.200, 0.368] | 0.209 [0.146, 0.277] | 0.234 [0.159, 0.314] | 0.283 [0.200, 0.368] | 3574.134 | 0.317 |
| rarity none | 97 | 0.283 [0.200, 0.368] | 0.209 [0.146, 0.277] | 0.234 [0.159, 0.314] | 0.283 [0.200, 0.368] | 3574.134 | 0.317 |
| qtype count_filter | 97 | 0.283 [0.200, 0.368] | 0.209 [0.146, 0.277] | 0.234 [0.159, 0.314] | 0.283 [0.200, 0.368] | 3574.134 | 0.317 |
| none/count_filter | 97 | 0.283 [0.200, 0.368] | 0.209 [0.146, 0.277] | 0.234 [0.159, 0.314] | 0.283 [0.200, 0.368] | 3574.134 | 0.317 |

## Determinism

Retrieval identity: not measured (1 repeat); answer agreement: not measured; pass^1 0.237.

## G2 query understanding

Route accuracy over rows whose gold op is not `abstain`; record match over rows whose gold query can be executed on the records; entity F1 over rows whose gold query lists entities. Per-field hits are kept in report.json as diagnostics.

| route accuracy | n | record match | n | entity F1 | n |
|---|---|---|---|---|---|
| – | 0 | – | 0 | – | 0 |

## G1 compile

Span containment 1.000; text fidelity –; empty documents 0; index fingerprint `fe978fc9c5ee87b300444934f7eee83288df0ee18af70a1e8a21fd6faf17119a`.

## Judge

No judge call: every answer is scored exactly.
