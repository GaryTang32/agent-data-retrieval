# Report: gov-p3-typed-test-20261120T200702

Corpus `gov`, system `p3-typed`, split `test`, 1 repeats, 27 rows, status `complete`. Generator `claude-sonnet-5-5`, judge `claude-opus-5-5`. Metrics version 2.

> **Warning:** judge and generator share a model family

Values in brackets are 95% CIs (percentile bootstrap, 10,000 resamples). End to end: cluster bootstrap over items of the statistic shown, using every repeat (items are resampled with all their rows); none where fewer than 2 items contribute. G3 retrieval: bootstrap of the mean over items at repeat 0 (retrieval is deterministic); none where n < 2.

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

## G3 retrieval (excluding `insufficient`)

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 0 | – | – | – | – | – | – |

## Determinism

Retrieval identity: not measured (1 repeat); answer agreement: not measured; pass^1 1.000.

## G2 query understanding

Route accuracy over rows whose gold op is not `abstain`; record match over rows whose gold query can be executed on the records; entity F1 over rows whose gold query lists entities. Per-field hits are kept in report.json as diagnostics.

| route accuracy | n | record match | n | entity F1 | n |
|---|---|---|---|---|---|
| 1.000 | 27 | 1.000 | 27 | 0.617 | 27 |

## G1 compile

Span containment –; text fidelity –; empty documents 0; index fingerprint `None`.

## Judge

Proxy κ – (n = 0; proxy, not human κ: judge vs the exact scorer on number/set/id items); raw agreement –, binary κ – (judge "partial" counted as incorrect; n = 0). Self-consistency – (n = 0). Human κ: not yet measured.
