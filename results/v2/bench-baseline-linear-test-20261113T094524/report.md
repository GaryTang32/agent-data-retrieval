# Report: bench-baseline-linear-test-20261113T094524

Corpus `bench`, system `baseline-linear`, split `test`, 1 repeats, 572 rows, status `complete`. Generator `claude-sonnet-5-5`, judge `claude-opus-5-5`, linear w = 0.7. Metrics version 2.

> **Warning:** judge and generator share a model family

Values in brackets are 95% CIs (percentile bootstrap, 10,000 resamples). End to end: cluster bootstrap over items of the statistic shown, using every repeat (items are resampled with all their rows); none where fewer than 2 items contribute. G3 retrieval: bootstrap of the mean over items at repeat 0 (retrieval is deterministic); none where n < 2.

## End to end

| n | accuracy | error | abstained | partial | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|---|---|
| 572 | 0.801 [0.767, 0.834] | 0.000 | 0.056 | 0.101 | 0.657 [0.598, 0.715] | 0.371 [0.255, 0.484] | -0.490 [-0.781, -0.206] |

| stratum | n | accuracy | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|
| qtype factoid | 325 | 0.846 [0.806, 0.886] | 0.766 [0.698, 0.828] | 0.606 [0.480, 0.723] | 0.126 [-0.182, 0.412] |
| qtype id_lookup | 34 | 0.971 [0.912, 1.000] | 0.971 [0.912, 1.000] | 0.971 [0.912, 1.000] | 0.971 [0.912, 1.000] |
| qtype insufficient | 55 | 0.964 [0.909, 1.000] | 0.927 [0.818, 1.000] | 0.855 [0.636, 1.000] | 0.636 [0.091, 1.000] |
| qtype overview | 119 | 0.580 [0.487, 0.664] | 0.185 [0.008, 0.361] | -0.605 [-0.958, -0.261] | -2.975 [-3.874, -2.126] |
| qtype procedure | 39 | 0.718 [0.564, 0.846] | 0.538 [0.282, 0.769] | 0.179 [-0.333, 0.615] | -0.897 [-2.179, 0.179] |
| rarity head | 72 | 0.875 [0.792, 0.944] | 0.792 [0.653, 0.917] | 0.625 [0.347, 0.861] | 0.125 [-0.556, 0.694] |
| rarity none | 422 | 0.787 [0.746, 0.827] | 0.633 [0.562, 0.701] | 0.325 [0.187, 0.462] | -0.600 [-0.945, -0.256] |
| rarity tail | 78 | 0.808 [0.718, 0.897] | 0.667 [0.500, 0.821] | 0.385 [0.064, 0.679] | -0.462 [-1.244, 0.282] |
| head/factoid | 16 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| head/id_lookup | 29 | 0.966 [0.897, 1.000] | 0.966 [0.897, 1.000] | 0.966 [0.897, 1.000] | 0.966 [0.897, 1.000] |
| head/overview | 9 | 0.889 [0.667, 1.000] | 0.778 [0.333, 1.000] | 0.556 [-0.333, 1.000] | -0.111 [-2.333, 1.000] |
| head/procedure | 18 | 0.611 [0.389, 0.833] | 0.333 [-0.111, 0.722] | -0.222 [-1.056, 0.500] | -1.889 [-4.056, -0.167] |
| none/factoid | 287 | 0.829 [0.784, 0.871] | 0.742 [0.672, 0.808] | 0.568 [0.432, 0.693] | 0.045 [-0.296, 0.359] |
| none/insufficient | 55 | 0.964 [0.909, 1.000] | 0.927 [0.818, 1.000] | 0.855 [0.636, 1.000] | 0.636 [0.091, 1.000] |
| none/overview | 80 | 0.512 [0.400, 0.625] | 0.037 [-0.175, 0.250] | -0.912 [-1.350, -0.475] | -3.763 [-4.875, -2.650] |
| tail/factoid | 22 | 0.955 [0.864, 1.000] | 0.909 [0.727, 1.000] | 0.818 [0.455, 1.000] | 0.545 [-0.364, 1.000] |
| tail/id_lookup | 5 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| tail/overview | 30 | 0.667 [0.500, 0.833] | 0.400 [0.067, 0.700] | -0.133 [-0.767, 0.467] | -1.733 [-3.367, -0.333] |
| tail/procedure | 21 | 0.810 [0.619, 0.952] | 0.714 [0.429, 0.952] | 0.524 [-0.048, 0.952] | -0.048 [-1.476, 0.952] |

Citation precision 0.934, evidence cited 0.963. Tokens 9087936 in / 307786 out. Spent $0.0000 in total (authoritative: every call, including any row dropped at a budget stop); rows written sum to $0.0000. Latency p50 – s, p95 – s (uncached calls: 0). Errors: 0.

JSON recovered (a reply held several objects or prose; the last object with the required keys was used) in 39 row(s): query 37, answer 2.

## G3 retrieval (excluding `insufficient`)

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 517 | 0.922 [0.900, 0.943] | 0.854 [0.829, 0.878] | 0.849 [0.821, 0.876] | 0.782 [0.755, 0.809] | 3351.977 | 0.684 |
| rarity head | 72 | 0.875 [0.792, 0.944] | 0.823 [0.738, 0.903] | 0.807 [0.716, 0.892] | 0.875 [0.792, 0.944] | 3208.208 | – |
| rarity none | 367 | 0.939 [0.916, 0.959] | 0.878 [0.852, 0.903] | 0.882 [0.852, 0.910] | 0.742 [0.712, 0.772] | 3401.022 | 0.684 |
| rarity tail | 78 | 0.885 [0.808, 0.949] | 0.769 [0.691, 0.844] | 0.731 [0.647, 0.813] | 0.885 [0.808, 0.949] | 3253.923 | – |
| qtype factoid | 325 | 0.954 [0.931, 0.975] | 0.883 [0.854, 0.910] | 0.866 [0.833, 0.897] | 0.771 [0.738, 0.803] | 3398.911 | 0.920 |
| qtype id_lookup | 34 | 0.971 [0.912, 1.000] | 0.956 [0.882, 1.000] | 0.951 [0.873, 1.000] | 0.971 [0.912, 1.000] | 3287.000 | – |
| qtype overview | 119 | 0.878 [0.827, 0.923] | 0.813 [0.762, 0.860] | 0.848 [0.789, 0.902] | 0.770 [0.712, 0.825] | 3312.370 | 0.569 |
| qtype procedure | 39 | 0.744 [0.590, 0.872] | 0.651 [0.512, 0.781] | 0.621 [0.477, 0.757] | 0.744 [0.590, 0.872] | 3138.359 | – |
| head/factoid | 16 | 1.000 [1.000, 1.000] | 0.932 [0.822, 1.000] | 0.912 [0.775, 1.000] | 1.000 [1.000, 1.000] | 3100.938 | – |
| head/id_lookup | 29 | 0.966 [0.897, 1.000] | 0.948 [0.862, 1.000] | 0.943 [0.851, 1.000] | 0.966 [0.897, 1.000] | 3258.897 | – |
| head/overview | 9 | 0.889 [0.667, 1.000] | 0.826 [0.588, 1.000] | 0.806 [0.528, 1.000] | 0.889 [0.667, 1.000] | 3394.333 | – |
| head/procedure | 18 | 0.611 [0.389, 0.833] | 0.522 [0.314, 0.732] | 0.494 [0.283, 0.711] | 0.611 [0.389, 0.833] | 3128.833 | – |
| none/factoid | 287 | 0.948 [0.920, 0.972] | 0.876 [0.845, 0.906] | 0.860 [0.824, 0.894] | 0.741 [0.706, 0.776] | 3422.707 | 0.920 |
| none/overview | 80 | 0.906 [0.866, 0.942] | 0.886 [0.849, 0.918] | 0.963 [0.925, 0.994] | 0.745 [0.685, 0.803] | 3323.225 | 0.569 |
| tail/factoid | 22 | 1.000 [1.000, 1.000] | 0.933 [0.866, 0.983] | 0.909 [0.818, 0.977] | 1.000 [1.000, 1.000] | 3305.182 | – |
| tail/id_lookup | 5 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 3450.000 | – |
| tail/overview | 30 | 0.800 [0.667, 0.933] | 0.617 [0.477, 0.751] | 0.556 [0.412, 0.703] | 0.800 [0.667, 0.933] | 3258.833 | – |
| tail/procedure | 21 | 0.857 [0.714, 1.000] | 0.761 [0.592, 0.904] | 0.730 [0.556, 0.889] | 0.857 [0.714, 1.000] | 3146.524 | – |

## Determinism

Retrieval identity: not measured (1 repeat); answer agreement: not measured; pass^1 0.801.

## G2 query understanding

Route accuracy over rows whose gold op is not `abstain`; record match over rows whose gold query can be executed on the records; entity F1 over rows whose gold query lists entities. Per-field hits are kept in report.json as diagnostics.

| route accuracy | n | record match | n | entity F1 | n |
|---|---|---|---|---|---|
| 0.867 | 517 | – | 0 | 0.526 | 150 |

## G1 compile

Span containment 0.202; text fidelity 1.000; empty documents 0; index fingerprint `62835d2b1430fbec6a7f0952a26ee6dd962fd787ff762a8b9a4e11d785ad46e0`.

## Judge

Proxy κ 0.000 (n = 38; proxy, not human κ: judge vs the exact scorer on number/set/id items); raw agreement 0.974, binary κ 0.000 (judge "partial" counted as incorrect; n = 38). Self-consistency 0.991 (n = 447). Human κ: not yet measured.
