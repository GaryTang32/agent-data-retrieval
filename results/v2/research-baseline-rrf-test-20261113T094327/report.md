# Report: research-baseline-rrf-test-20261113T094327

Corpus `research`, system `baseline-rrf`, split `test`, 1 repeats, 222 rows, status `complete`. Generator `claude-sonnet-5-5`, judge `claude-opus-5-5`. Metrics version 2.

> **Warning:** judge and generator share a model family

Values in brackets are 95% CIs (percentile bootstrap, 10,000 resamples). End to end: cluster bootstrap over items of the statistic shown, using every repeat (items are resampled with all their rows); none where fewer than 2 items contribute. G3 retrieval: bootstrap of the mean over items at repeat 0 (retrieval is deterministic); none where n < 2.

## End to end

| n | accuracy | error | abstained | partial | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|---|---|
| 222 | 0.712 [0.653, 0.770] | 0.000 | 0.113 | 0.018 | 0.536 [0.432, 0.635] | 0.185 [-0.018, 0.383] | -0.869 [-1.383, -0.378] |

| stratum | n | accuracy | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|
| qtype count_filter | 27 | 0.222 [0.074, 0.407] | -0.185 [-0.481, 0.111] | -1.000 [-1.667, -0.370] | -3.444 [-5.222, -1.704] |
| qtype factoid | 40 | 0.875 [0.775, 0.975] | 0.850 [0.700, 0.975] | 0.800 [0.550, 0.975] | 0.650 [0.100, 0.975] |
| qtype id_lookup | 39 | 0.821 [0.692, 0.923] | 0.744 [0.538, 0.923] | 0.590 [0.231, 0.897] | 0.128 [-0.821, 0.897] |
| qtype insufficient | 42 | 0.762 [0.619, 0.881] | 0.524 [0.238, 0.762] | 0.048 [-0.524, 0.524] | -1.381 [-2.810, -0.190] |
| qtype overview | 35 | 0.600 [0.429, 0.743] | 0.314 [0.000, 0.600] | -0.257 [-0.857, 0.314] | -1.971 [-3.458, -0.543] |
| qtype procedure | 39 | 0.821 [0.692, 0.923] | 0.718 [0.513, 0.897] | 0.513 [0.103, 0.846] | -0.103 [-1.128, 0.692] |
| rarity head | 113 | 0.655 [0.566, 0.743] | 0.487 [0.345, 0.619] | 0.150 [-0.124, 0.407] | -0.858 [-1.549, -0.212] |
| rarity none | 42 | 0.762 [0.619, 0.881] | 0.524 [0.238, 0.762] | 0.048 [-0.524, 0.524] | -1.381 [-2.810, -0.190] |
| rarity tail | 67 | 0.776 [0.672, 0.866] | 0.627 [0.448, 0.791] | 0.328 [-0.030, 0.657] | -0.567 [-1.448, 0.224] |
| head/count_filter | 27 | 0.222 [0.074, 0.407] | -0.185 [-0.481, 0.111] | -1.000 [-1.667, -0.370] | -3.444 [-5.222, -1.704] |
| head/factoid | 21 | 0.857 [0.714, 1.000] | 0.810 [0.571, 1.000] | 0.714 [0.286, 1.000] | 0.429 [-0.571, 1.000] |
| head/id_lookup | 34 | 0.853 [0.735, 0.971] | 0.824 [0.647, 0.971] | 0.765 [0.500, 0.971] | 0.588 [-0.059, 0.971] |
| head/overview | 12 | 0.583 [0.333, 0.833] | 0.333 [-0.167, 0.750] | -0.167 [-1.167, 0.667] | -1.667 [-4.167, 0.667] |
| head/procedure | 19 | 0.737 [0.526, 0.895] | 0.579 [0.211, 0.895] | 0.263 [-0.421, 0.842] | -0.684 [-2.316, 0.842] |
| none/insufficient | 42 | 0.762 [0.619, 0.881] | 0.524 [0.238, 0.762] | 0.048 [-0.524, 0.524] | -1.381 [-2.810, -0.190] |
| tail/factoid | 19 | 0.895 [0.737, 1.000] | 0.895 [0.737, 1.000] | 0.895 [0.737, 1.000] | 0.895 [0.737, 1.000] |
| tail/id_lookup | 5 | 0.600 [0.200, 1.000] | 0.200 [-0.600, 1.000] | -0.600 [-2.200, 1.000] | -3.000 [-7.000, 1.000] |
| tail/overview | 23 | 0.609 [0.391, 0.783] | 0.304 [-0.087, 0.652] | -0.304 [-1.087, 0.391] | -2.130 [-3.957, -0.391] |
| tail/procedure | 20 | 0.900 [0.750, 1.000] | 0.850 [0.600, 1.000] | 0.750 [0.300, 1.000] | 0.450 [-0.600, 1.000] |

Citation precision 0.591, evidence cited 0.761. Tokens 3509471 in / 87129 out. Spent $0.0000 in total (authoritative: every call, including any row dropped at a budget stop); rows written sum to $0.0000. Latency p50 – s, p95 – s (uncached calls: 0). Errors: 0.

JSON recovered (a reply held several objects or prose; the last object with the required keys was used) in 11 row(s): query 8, answer 4.

## G3 retrieval (excluding `insufficient`)

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 180 | 0.654 [0.582, 0.723] | 0.502 [0.438, 0.564] | 0.465 [0.399, 0.530] | 0.654 [0.582, 0.723] | 3729.311 | 0.118 |
| rarity head | 113 | 0.608 [0.520, 0.697] | 0.450 [0.375, 0.527] | 0.416 [0.338, 0.497] | 0.608 [0.520, 0.697] | 3691.823 | 0.118 |
| rarity tail | 67 | 0.731 [0.627, 0.836] | 0.590 [0.485, 0.689] | 0.546 [0.436, 0.651] | 0.731 [0.627, 0.836] | 3792.537 | – |
| qtype count_filter | 27 | 0.322 [0.166, 0.489] | 0.146 [0.067, 0.241] | 0.161 [0.057, 0.291] | 0.322 [0.166, 0.489] | 3455.333 | 0.118 |
| qtype factoid | 40 | 0.750 [0.600, 0.875] | 0.611 [0.480, 0.741] | 0.569 [0.430, 0.707] | 0.750 [0.600, 0.875] | 3774.300 | – |
| qtype id_lookup | 39 | 0.769 [0.641, 0.897] | 0.614 [0.484, 0.741] | 0.565 [0.429, 0.703] | 0.769 [0.641, 0.897] | 3782.897 | – |
| qtype overview | 35 | 0.629 [0.457, 0.771] | 0.447 [0.313, 0.584] | 0.390 [0.254, 0.532] | 0.629 [0.457, 0.771] | 3758.686 | – |
| qtype procedure | 39 | 0.692 [0.538, 0.821] | 0.573 [0.438, 0.708] | 0.534 [0.395, 0.673] | 0.692 [0.538, 0.821] | 3792.897 | – |
| head/count_filter | 27 | 0.322 [0.166, 0.489] | 0.146 [0.067, 0.241] | 0.161 [0.057, 0.291] | 0.322 [0.166, 0.489] | 3455.333 | 0.118 |
| head/factoid | 21 | 0.619 [0.429, 0.810] | 0.490 [0.305, 0.681] | 0.451 [0.265, 0.648] | 0.619 [0.429, 0.810] | 3740.905 | – |
| head/id_lookup | 34 | 0.824 [0.676, 0.941] | 0.682 [0.548, 0.809] | 0.638 [0.494, 0.779] | 0.824 [0.676, 0.941] | 3784.529 | – |
| head/overview | 12 | 0.583 [0.333, 0.833] | 0.391 [0.188, 0.599] | 0.326 [0.139, 0.535] | 0.583 [0.333, 0.833] | 3813.000 | – |
| head/procedure | 19 | 0.632 [0.421, 0.842] | 0.458 [0.282, 0.639] | 0.401 [0.230, 0.585] | 0.632 [0.421, 0.842] | 3731.211 | – |
| tail/factoid | 19 | 0.895 [0.737, 1.000] | 0.745 [0.575, 0.898] | 0.700 [0.509, 0.873] | 0.895 [0.737, 1.000] | 3811.211 | – |
| tail/id_lookup | 5 | 0.400 [0.000, 0.800] | 0.146 [0.000, 0.319] | 0.072 [0.000, 0.172] | 0.400 [0.000, 0.800] | 3771.800 | – |
| tail/overview | 23 | 0.652 [0.435, 0.826] | 0.476 [0.304, 0.649] | 0.424 [0.249, 0.604] | 0.652 [0.435, 0.826] | 3730.348 | – |
| tail/procedure | 20 | 0.750 [0.550, 0.900] | 0.682 [0.489, 0.863] | 0.660 [0.460, 0.850] | 0.750 [0.550, 0.900] | 3851.500 | – |

## Determinism

Retrieval identity: not measured (1 repeat); answer agreement: not measured; pass^1 0.712.

## G2 query understanding

Route accuracy over rows whose gold op is not `abstain`; record match over rows whose gold query can be executed on the records; entity F1 over rows whose gold query lists entities. Per-field hits are kept in report.json as diagnostics.

| route accuracy | n | record match | n | entity F1 | n |
|---|---|---|---|---|---|
| 0.661 | 180 | 0.963 | 27 | 0.565 | 180 |

## G1 compile

Span containment 1.000; text fidelity 1.000; empty documents 0; index fingerprint `150af34ab34d41a83f6fe552a8313c6a514f26b1567cb6205e3e633f21c6becc`.

## Judge

Proxy κ 0.954 (n = 62; proxy, not human κ: judge vs the exact scorer on number/set/id items); raw agreement 1.000, binary κ 1.000 (judge "partial" counted as incorrect; n = 62). Self-consistency 0.968 (n = 93). Human κ: not yet measured.
