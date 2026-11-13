# Report: bench-baseline-rrf-test-20261112T012126

Corpus `bench`, system `baseline-rrf`, split `test`, 1 repeats, 572 rows, status `complete`. Generator `claude-sonnet-5-5`, judge `claude-opus-5-5`.

> **Warning:** judge and generator share a model family

> **Warning:** 1 row(s) ended in a model error

Values in brackets are 95% CIs (percentile bootstrap, 10,000 resamples). End to end: cluster bootstrap over items of the statistic shown, using every repeat (items are resampled with all their rows); none where fewer than 2 items contribute. G3 retrieval: bootstrap of the mean over items at repeat 0 (retrieval is deterministic); none where n < 2.

## End to end

| n | accuracy | error | abstained | partial | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|---|---|
| 572 | 0.720 [0.682, 0.755] | 0.002 | 0.103 | 0.121 | 0.546 [0.482, 0.608] | 0.196 [0.070, 0.315] | -0.855 [-1.172, -0.559] |

| stratum | n | accuracy | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|
| qtype factoid | 325 | 0.763 [0.717, 0.809] | 0.643 [0.566, 0.714] | 0.403 [0.255, 0.538] | -0.317 [-0.680, 0.025] |
| qtype id_lookup | 34 | 0.765 [0.618, 0.912] | 0.765 [0.618, 0.912] | 0.765 [0.618, 0.912] | 0.765 [0.618, 0.912] |
| qtype insufficient | 55 | 0.945 [0.873, 1.000] | 0.891 [0.745, 1.000] | 0.782 [0.491, 1.000] | 0.455 [-0.273, 1.000] |
| qtype overview | 119 | 0.513 [0.428, 0.605] | 0.076 [-0.102, 0.254] | -0.805 [-1.161, -0.458] | -3.449 [-4.356, -2.576] |
| qtype procedure | 39 | 0.641 [0.487, 0.795] | 0.487 [0.231, 0.718] | 0.179 [-0.282, 0.590] | -0.744 [-1.974, 0.282] |
| rarity head | 72 | 0.708 [0.597, 0.819] | 0.625 [0.472, 0.764] | 0.458 [0.194, 0.694] | -0.042 [-0.708, 0.528] |
| rarity none | 422 | 0.723 [0.680, 0.765] | 0.539 [0.463, 0.613] | 0.169 [0.021, 0.314] | -0.943 [-1.316, -0.577] |
| rarity tail | 78 | 0.718 [0.615, 0.821] | 0.513 [0.333, 0.692] | 0.103 [-0.269, 0.449] | -1.128 [-2.038, -0.244] |
| head/factoid | 16 | 0.750 [0.500, 0.938] | 0.688 [0.375, 0.938] | 0.562 [0.000, 0.938] | 0.187 [-1.125, 0.938] |
| head/id_lookup | 29 | 0.759 [0.586, 0.897] | 0.759 [0.586, 0.897] | 0.759 [0.586, 0.897] | 0.759 [0.586, 0.897] |
| head/overview | 9 | 0.889 [0.667, 1.000] | 0.778 [0.333, 1.000] | 0.556 [-0.333, 1.000] | -0.111 [-2.333, 1.000] |
| head/procedure | 18 | 0.500 [0.278, 0.722] | 0.278 [-0.111, 0.611] | -0.167 [-0.944, 0.500] | -1.500 [-3.556, 0.167] |
| none/factoid | 287 | 0.760 [0.707, 0.808] | 0.641 [0.561, 0.718] | 0.404 [0.251, 0.554] | -0.307 [-0.690, 0.063] |
| none/insufficient | 55 | 0.945 [0.873, 1.000] | 0.891 [0.745, 1.000] | 0.782 [0.491, 1.000] | 0.455 [-0.273, 1.000] |
| none/overview | 80 | 0.438 [0.325, 0.550] | -0.076 [-0.278, 0.139] | -1.114 [-1.532, -0.684] | -4.228 [-5.266, -3.176] |
| tail/factoid | 22 | 0.818 [0.636, 0.955] | 0.636 [0.273, 0.909] | 0.273 [-0.455, 0.818] | -0.818 [-2.636, 0.545] |
| tail/id_lookup | 5 | 0.800 [0.400, 1.000] | 0.800 [0.400, 1.000] | 0.800 [0.400, 1.000] | 0.800 [0.400, 1.000] |
| tail/overview | 30 | 0.600 [0.433, 0.767] | 0.267 [-0.067, 0.600] | -0.400 [-1.100, 0.234] | -2.400 [-4.100, -0.733] |
| tail/procedure | 21 | 0.762 [0.571, 0.905] | 0.667 [0.381, 0.905] | 0.476 [-0.095, 0.905] | -0.095 [-1.524, 0.905] |

Citation precision 0.915, evidence cited 0.947. Tokens 8993028 in / 306080 out. Spent $0.0000 in total (authoritative: every call, including any row dropped at a budget stop); rows written sum to $0.0000. Latency p50 6.256 s, p95 6.256 s (uncached calls: 1). Errors: 1.

JSON recovered (a reply held several objects or prose; the last object with the required keys was used) in 42 row(s): query 37, answer 3, judge 1, judge_check 2.

## G3 retrieval (excluding `insufficient`)

| stratum | n | Recall@10 | nDCG@10 | MRR | full coverage |
|---|---|---|---|---|---|
| pooled | 517 | 0.859 [0.828, 0.887] | 0.458 [0.429, 0.487] | 0.756 [0.721, 0.789] | 0.671 |
| rarity head | 72 | 0.694 [0.583, 0.806] | 0.612 [0.510, 0.717] | 0.586 [0.481, 0.694] | – |
| rarity none | 367 | 0.905 [0.877, 0.931] | 0.391 [0.365, 0.418] | 0.826 [0.792, 0.859] | 0.671 |
| rarity tail | 78 | 0.795 [0.705, 0.885] | 0.632 [0.541, 0.720] | 0.581 [0.484, 0.676] | – |
| qtype factoid | 325 | 0.900 [0.866, 0.932] | 0.433 [0.400, 0.466] | 0.777 [0.736, 0.816] | 0.920 |
| qtype id_lookup | 34 | 0.765 [0.618, 0.912] | 0.653 [0.506, 0.793] | 0.620 [0.467, 0.771] | – |
| qtype overview | 119 | 0.846 [0.790, 0.898] | 0.446 [0.390, 0.502] | 0.818 [0.754, 0.878] | 0.549 |
| qtype procedure | 39 | 0.641 [0.487, 0.795] | 0.537 [0.396, 0.675] | 0.505 [0.360, 0.649] | – |
| head/factoid | 16 | 0.750 [0.500, 0.938] | 0.680 [0.462, 0.875] | 0.658 [0.429, 0.875] | – |
| head/id_lookup | 29 | 0.759 [0.586, 0.897] | 0.652 [0.491, 0.807] | 0.620 [0.450, 0.785] | – |
| head/overview | 9 | 0.889 [0.667, 1.000] | 0.735 [0.492, 0.928] | 0.685 [0.426, 0.907] | – |
| head/procedure | 18 | 0.444 [0.222, 0.667] | 0.424 [0.202, 0.646] | 0.417 [0.194, 0.639] | – |
| none/factoid | 287 | 0.911 [0.878, 0.943] | 0.395 [0.363, 0.427] | 0.789 [0.747, 0.830] | 0.920 |
| none/overview | 80 | 0.884 [0.836, 0.927] | 0.376 [0.328, 0.426] | 0.959 [0.918, 0.994] | 0.549 |
| tail/factoid | 22 | 0.864 [0.727, 1.000] | 0.743 [0.579, 0.892] | 0.706 [0.527, 0.869] | – |
| tail/id_lookup | 5 | 0.800 [0.400, 1.000] | 0.658 [0.258, 1.000] | 0.620 [0.220, 1.000] | – |
| tail/overview | 30 | 0.733 [0.567, 0.867] | 0.544 [0.399, 0.688] | 0.484 [0.334, 0.637] | – |
| tail/procedure | 21 | 0.810 [0.619, 0.952] | 0.634 [0.464, 0.795] | 0.580 [0.397, 0.759] | – |

## Determinism

Retrieval identity: not measured (1 repeat); answer agreement: not measured; pass^1 0.720.

## G2 query understanding

| store | op | filters | entities | as_of | exact | exec match |
|---|---|---|---|---|---|---|
| 0.876 | 0.248 | 0.657 | 0.028 | 0.934 | 0.002 | – |

## G1 compile

Span containment 0.202; text fidelity 1.000; empty documents 0; index fingerprint `62835d2b1430fbec6a7f0952a26ee6dd962fd787ff762a8b9a4e11d785ad46e0`.

## Judge

Proxy κ 0.318 (n = 30; proxy, not human κ: judge vs the exact scorer on number/set/id items); raw agreement 0.967, binary κ 0.651 (judge "partial" counted as incorrect; n = 30). Self-consistency 0.988 (n = 427). Human κ: not yet measured.
