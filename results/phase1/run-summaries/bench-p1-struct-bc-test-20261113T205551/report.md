# Report: bench-p1-struct-bc-test-20261113T205551

Corpus `bench`, system `p1-struct-bc`, split `test`, 1 repeats, 572 rows, status `complete`. Generator `claude-sonnet-5-5`, judge `claude-opus-5-5`, linear w = 0.7. Metrics version 2.

> **Warning:** judge and generator share a model family

Values in brackets are 95% CIs (percentile bootstrap, 10,000 resamples). End to end: cluster bootstrap over items of the statistic shown, using every repeat (items are resampled with all their rows); none where fewer than 2 items contribute. G3 retrieval: bootstrap of the mean over items at repeat 0 (retrieval is deterministic); none where n < 2.

## End to end

| n | accuracy | error | abstained | partial | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|---|---|
| 572 | 0.813 [0.780, 0.844] | 0.000 | 0.049 | 0.091 | 0.675 [0.615, 0.733] | 0.399 [0.283, 0.510] | -0.430 [-0.720, -0.154] |

| stratum | n | accuracy | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|
| qtype factoid | 325 | 0.862 [0.822, 0.898] | 0.788 [0.723, 0.846] | 0.640 [0.517, 0.748] | 0.197 [-0.102, 0.462] |
| qtype id_lookup | 34 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| qtype insufficient | 55 | 0.927 [0.855, 0.982] | 0.855 [0.709, 0.964] | 0.709 [0.418, 0.927] | 0.273 [-0.455, 0.818] |
| qtype overview | 119 | 0.622 [0.538, 0.706] | 0.286 [0.118, 0.445] | -0.387 [-0.731, -0.067] | -2.403 [-3.252, -1.597] |
| qtype procedure | 39 | 0.667 [0.513, 0.821] | 0.385 [0.103, 0.641] | -0.179 [-0.769, 0.359] | -1.872 [-3.359, -0.564] |
| rarity head | 72 | 0.903 [0.833, 0.972] | 0.806 [0.667, 0.944] | 0.611 [0.333, 0.889] | 0.028 [-0.667, 0.722] |
| rarity none | 422 | 0.803 [0.763, 0.841] | 0.664 [0.592, 0.730] | 0.384 [0.249, 0.512] | -0.455 [-0.791, -0.135] |
| rarity tail | 78 | 0.782 [0.692, 0.872] | 0.615 [0.436, 0.782] | 0.282 [-0.064, 0.603] | -0.718 [-1.590, 0.064] |
| head/factoid | 16 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| head/id_lookup | 29 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| head/overview | 9 | 0.889 [0.667, 1.000] | 0.778 [0.333, 1.000] | 0.556 [-0.333, 1.000] | -0.111 [-2.333, 1.000] |
| head/procedure | 18 | 0.667 [0.444, 0.889] | 0.333 [-0.111, 0.778] | -0.333 [-1.222, 0.556] | -2.333 [-4.556, -0.111] |
| none/factoid | 287 | 0.850 [0.808, 0.892] | 0.774 [0.707, 0.836] | 0.620 [0.491, 0.742] | 0.160 [-0.153, 0.456] |
| none/insufficient | 55 | 0.927 [0.855, 0.982] | 0.855 [0.709, 0.964] | 0.709 [0.418, 0.927] | 0.273 [-0.455, 0.818] |
| none/overview | 80 | 0.550 [0.438, 0.662] | 0.138 [-0.075, 0.350] | -0.688 [-1.113, -0.250] | -3.163 [-4.250, -2.050] |
| tail/factoid | 22 | 0.909 [0.773, 1.000] | 0.818 [0.545, 1.000] | 0.636 [0.091, 1.000] | 0.091 [-1.273, 1.000] |
| tail/id_lookup | 5 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| tail/overview | 30 | 0.733 [0.567, 0.900] | 0.533 [0.233, 0.800] | 0.133 [-0.467, 0.667] | -1.067 [-2.467, 0.267] |
| tail/procedure | 21 | 0.667 [0.476, 0.857] | 0.429 [0.048, 0.762] | -0.048 [-0.762, 0.571] | -1.476 [-3.333, 0.048] |

Citation precision 0.931, evidence cited 0.961. Tokens 8390063 in / 298948 out. Spent $0.0000 in total (authoritative: every call, including any row dropped at a budget stop); rows written sum to $0.0000. Latency p50 6.654 s, p95 13.141 s (uncached calls: 572). Errors: 0.

JSON recovered (a reply held several objects or prose; the last object with the required keys was used) in 38 row(s): query 37, answer 2.

## G3 retrieval (excluding `insufficient`)

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 517 | 0.919 [0.896, 0.940] | 0.853 [0.827, 0.877] | 0.856 [0.828, 0.882] | 0.780 [0.753, 0.808] | 2911.112 | 0.632 |
| rarity head | 72 | 0.903 [0.833, 0.972] | 0.835 [0.757, 0.908] | 0.813 [0.728, 0.893] | 0.847 [0.765, 0.923] | 2638.056 | – |
| rarity none | 367 | 0.929 [0.905, 0.951] | 0.875 [0.849, 0.900] | 0.893 [0.864, 0.920] | 0.745 [0.713, 0.777] | 2980.891 | 0.632 |
| rarity tail | 78 | 0.885 [0.808, 0.949] | 0.762 [0.683, 0.838] | 0.723 [0.636, 0.805] | 0.881 [0.808, 0.949] | 2834.846 | – |
| qtype factoid | 325 | 0.949 [0.925, 0.971] | 0.886 [0.857, 0.913] | 0.874 [0.841, 0.904] | 0.788 [0.755, 0.820] | 3030.237 | 0.960 |
| qtype id_lookup | 34 | 1.000 [1.000, 1.000] | 0.940 [0.879, 0.989] | 0.921 [0.841, 0.985] | 1.000 [1.000, 1.000] | 2760.500 | – |
| qtype overview | 119 | 0.877 [0.832, 0.919] | 0.796 [0.747, 0.840] | 0.855 [0.797, 0.906] | 0.749 [0.688, 0.809] | 2669.176 | 0.471 |
| qtype procedure | 39 | 0.718 [0.564, 0.846] | 0.672 [0.531, 0.803] | 0.656 [0.513, 0.791] | 0.616 [0.467, 0.757] | 2787.923 | – |
| head/factoid | 16 | 1.000 [1.000, 1.000] | 0.934 [0.829, 1.000] | 0.914 [0.781, 1.000] | 1.000 [1.000, 1.000] | 2633.500 | – |
| head/id_lookup | 29 | 1.000 [1.000, 1.000] | 0.930 [0.860, 0.987] | 0.907 [0.814, 0.983] | 1.000 [1.000, 1.000] | 2720.793 | – |
| head/overview | 9 | 0.889 [0.667, 1.000] | 0.848 [0.626, 1.000] | 0.833 [0.611, 1.000] | 0.889 [0.666, 1.000] | 2551.222 | – |
| head/procedure | 18 | 0.667 [0.444, 0.889] | 0.587 [0.385, 0.785] | 0.560 [0.352, 0.769] | 0.445 [0.244, 0.656] | 2552.222 | – |
| none/factoid | 287 | 0.943 [0.915, 0.969] | 0.880 [0.848, 0.911] | 0.869 [0.833, 0.903] | 0.760 [0.723, 0.795] | 3069.666 | 0.960 |
| none/overview | 80 | 0.880 [0.838, 0.918] | 0.858 [0.820, 0.893] | 0.977 [0.948, 1.000] | 0.693 [0.623, 0.762] | 2662.412 | 0.471 |
| tail/factoid | 22 | 1.000 [1.000, 1.000] | 0.927 [0.859, 0.983] | 0.902 [0.811, 0.977] | 1.000 [1.000, 1.000] | 2804.409 | – |
| tail/id_lookup | 5 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 2990.800 | – |
| tail/overview | 30 | 0.867 [0.733, 0.967] | 0.614 [0.486, 0.738] | 0.534 [0.395, 0.676] | 0.858 [0.725, 0.967] | 2722.600 | – |
| tail/procedure | 21 | 0.762 [0.571, 0.905] | 0.744 [0.554, 0.905] | 0.738 [0.548, 0.905] | 0.762 [0.571, 0.905] | 2989.952 | – |

## Determinism

Retrieval identity: not measured (1 repeat); answer agreement: not measured; pass^1 0.813.

## G2 query understanding

Route accuracy over rows whose gold op is not `abstain`; record match over rows whose gold query can be executed on the records; entity F1 over rows whose gold query lists entities. Per-field hits are kept in report.json as diagnostics.

| route accuracy | n | record match | n | entity F1 | n |
|---|---|---|---|---|---|
| 0.867 | 517 | – | 0 | 0.526 | 150 |

## G1 compile

Span containment 0.178; text fidelity 1.000; empty documents 0; index fingerprint `8c7bb39d032b886872bf0d64c462a906c4ea0435712feae880018d0bfc121830`.

## Judge

Proxy κ 0.000 (n = 39; proxy, not human κ: judge vs the exact scorer on number/set/id items); raw agreement 0.949, binary κ 0.000 (judge "partial" counted as incorrect; n = 39). Self-consistency 0.987 (n = 450). Human κ: not yet measured.
