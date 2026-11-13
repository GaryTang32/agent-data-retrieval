# Report: research-baseline-linear-test-20261113T094721

Corpus `research`, system `baseline-linear`, split `test`, 1 repeats, 222 rows, status `complete`. Generator `claude-sonnet-5-5`, judge `claude-opus-5-5`, linear w = 1.0. Metrics version 2.

> **Warning:** judge and generator share a model family

Values in brackets are 95% CIs (percentile bootstrap, 10,000 resamples). End to end: cluster bootstrap over items of the statistic shown, using every repeat (items are resampled with all their rows); none where fewer than 2 items contribute. G3 retrieval: bootstrap of the mean over items at repeat 0 (retrieval is deterministic); none where n < 2.

## End to end

| n | accuracy | error | abstained | partial | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|---|---|
| 222 | 0.806 [0.752, 0.856] | 0.000 | 0.041 | 0.023 | 0.653 [0.554, 0.748] | 0.347 [0.153, 0.532] | -0.572 [-1.059, -0.113] |

| stratum | n | accuracy | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|
| qtype count_filter | 27 | 0.593 [0.407, 0.778] | 0.185 [-0.185, 0.556] | -0.630 [-1.370, 0.111] | -3.074 [-4.926, -1.222] |
| qtype factoid | 40 | 0.975 [0.925, 1.000] | 0.975 [0.925, 1.000] | 0.975 [0.925, 1.000] | 0.975 [0.925, 1.000] |
| qtype id_lookup | 39 | 0.872 [0.769, 0.974] | 0.846 [0.692, 0.974] | 0.795 [0.538, 0.974] | 0.641 [0.077, 0.974] |
| qtype insufficient | 42 | 0.714 [0.571, 0.833] | 0.429 [0.143, 0.667] | -0.143 [-0.714, 0.333] | -1.857 [-3.286, -0.667] |
| qtype overview | 35 | 0.686 [0.543, 0.829] | 0.457 [0.171, 0.714] | 0.000 [-0.571, 0.514] | -1.371 [-2.800, -0.143] |
| qtype procedure | 39 | 0.923 [0.846, 1.000] | 0.872 [0.718, 1.000] | 0.769 [0.462, 1.000] | 0.462 [-0.308, 1.000] |
| rarity head | 113 | 0.814 [0.743, 0.885] | 0.681 [0.549, 0.805] | 0.416 [0.150, 0.646] | -0.381 [-1.027, 0.212] |
| rarity none | 42 | 0.714 [0.571, 0.833] | 0.429 [0.143, 0.667] | -0.143 [-0.714, 0.333] | -1.857 [-3.286, -0.667] |
| rarity tail | 67 | 0.851 [0.761, 0.925] | 0.746 [0.582, 0.896] | 0.537 [0.224, 0.806] | -0.090 [-0.851, 0.627] |
| head/count_filter | 27 | 0.593 [0.407, 0.778] | 0.185 [-0.185, 0.556] | -0.630 [-1.370, 0.111] | -3.074 [-4.926, -1.222] |
| head/factoid | 21 | 0.952 [0.857, 1.000] | 0.952 [0.857, 1.000] | 0.952 [0.857, 1.000] | 0.952 [0.857, 1.000] |
| head/id_lookup | 34 | 0.912 [0.794, 1.000] | 0.912 [0.794, 1.000] | 0.912 [0.794, 1.000] | 0.912 [0.794, 1.000] |
| head/overview | 12 | 0.667 [0.417, 0.917] | 0.417 [-0.083, 0.833] | -0.083 [-1.083, 0.833] | -1.583 [-4.083, 0.833] |
| head/procedure | 19 | 0.895 [0.737, 1.000] | 0.842 [0.579, 1.000] | 0.737 [0.263, 1.000] | 0.421 [-0.684, 1.000] |
| none/insufficient | 42 | 0.714 [0.571, 0.833] | 0.429 [0.143, 0.667] | -0.143 [-0.714, 0.333] | -1.857 [-3.286, -0.667] |
| tail/factoid | 19 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| tail/id_lookup | 5 | 0.600 [0.200, 1.000] | 0.400 [-0.400, 1.000] | 0.000 [-1.600, 1.000] | -1.200 [-5.200, 1.000] |
| tail/overview | 23 | 0.696 [0.522, 0.870] | 0.478 [0.130, 0.783] | 0.043 [-0.652, 0.652] | -1.261 [-3.000, 0.391] |
| tail/procedure | 20 | 0.950 [0.850, 1.000] | 0.900 [0.700, 1.000] | 0.800 [0.400, 1.000] | 0.500 [-0.500, 1.000] |

Citation precision 0.696, evidence cited 0.895. Tokens 3571037 in / 88963 out. Spent $0.0000 in total (authoritative: every call, including any row dropped at a budget stop); rows written sum to $0.0000. Latency p50 – s, p95 – s (uncached calls: 0). Errors: 0.

JSON recovered (a reply held several objects or prose; the last object with the required keys was used) in 12 row(s): query 8, answer 4.

## G3 retrieval (excluding `insufficient`)

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 180 | 0.856 [0.802, 0.905] | 0.710 [0.654, 0.764] | 0.676 [0.616, 0.734] | 0.856 [0.802, 0.905] | 3751.633 | 0.353 |
| rarity head | 113 | 0.851 [0.785, 0.911] | 0.679 [0.610, 0.746] | 0.645 [0.571, 0.718] | 0.851 [0.785, 0.911] | 3722.124 | 0.353 |
| rarity tail | 67 | 0.866 [0.776, 0.940] | 0.761 [0.669, 0.847] | 0.729 [0.631, 0.823] | 0.866 [0.776, 0.940] | 3801.403 | – |
| qtype count_filter | 27 | 0.673 [0.505, 0.826] | 0.424 [0.295, 0.557] | 0.434 [0.287, 0.589] | 0.673 [0.505, 0.826] | 3563.185 | 0.353 |
| qtype factoid | 40 | 0.975 [0.925, 1.000] | 0.884 [0.804, 0.952] | 0.854 [0.760, 0.938] | 0.975 [0.925, 1.000] | 3773.100 | – |
| qtype id_lookup | 39 | 0.897 [0.795, 0.974] | 0.783 [0.670, 0.884] | 0.746 [0.623, 0.859] | 0.897 [0.795, 0.974] | 3771.897 | – |
| qtype overview | 35 | 0.686 [0.514, 0.829] | 0.509 [0.369, 0.646] | 0.455 [0.310, 0.600] | 0.686 [0.514, 0.829] | 3802.057 | – |
| qtype procedure | 39 | 0.974 [0.923, 1.000] | 0.836 [0.753, 0.912] | 0.789 [0.688, 0.885] | 0.974 [0.923, 1.000] | 3794.564 | – |
| head/count_filter | 27 | 0.673 [0.505, 0.826] | 0.424 [0.295, 0.557] | 0.434 [0.287, 0.589] | 0.673 [0.505, 0.826] | 3563.185 | 0.353 |
| head/factoid | 21 | 0.952 [0.857, 1.000] | 0.797 [0.666, 0.912] | 0.746 [0.595, 0.883] | 0.952 [0.857, 1.000] | 3733.476 | – |
| head/id_lookup | 34 | 0.941 [0.853, 1.000] | 0.850 [0.748, 0.935] | 0.819 [0.706, 0.919] | 0.941 [0.853, 1.000] | 3776.294 | – |
| head/overview | 12 | 0.667 [0.417, 0.917] | 0.440 [0.232, 0.661] | 0.369 [0.164, 0.599] | 0.667 [0.417, 0.917] | 3879.833 | – |
| head/procedure | 19 | 0.947 [0.842, 1.000] | 0.758 [0.620, 0.879] | 0.695 [0.534, 0.842] | 0.947 [0.842, 1.000] | 3738.895 | – |
| tail/factoid | 19 | 1.000 [1.000, 1.000] | 0.981 [0.942, 1.000] | 0.974 [0.921, 1.000] | 1.000 [1.000, 1.000] | 3816.895 | – |
| tail/id_lookup | 5 | 0.600 [0.200, 1.000] | 0.330 [0.063, 0.667] | 0.254 [0.025, 0.629] | 0.600 [0.200, 1.000] | 3742.000 | – |
| tail/overview | 23 | 0.696 [0.478, 0.870] | 0.545 [0.366, 0.720] | 0.500 [0.313, 0.688] | 0.696 [0.478, 0.870] | 3761.478 | – |
| tail/procedure | 20 | 1.000 [1.000, 1.000] | 0.910 [0.821, 0.982] | 0.879 [0.762, 0.975] | 1.000 [1.000, 1.000] | 3847.450 | – |

## Determinism

Retrieval identity: not measured (1 repeat); answer agreement: not measured; pass^1 0.806.

## G2 query understanding

Route accuracy over rows whose gold op is not `abstain`; record match over rows whose gold query can be executed on the records; entity F1 over rows whose gold query lists entities. Per-field hits are kept in report.json as diagnostics.

| route accuracy | n | record match | n | entity F1 | n |
|---|---|---|---|---|---|
| 0.661 | 180 | 0.963 | 27 | 0.565 | 180 |

## G1 compile

Span containment 1.000; text fidelity 1.000; empty documents 0; index fingerprint `150af34ab34d41a83f6fe552a8313c6a514f26b1567cb6205e3e633f21c6becc`.

## Judge

Proxy κ 1.000 (n = 75; proxy, not human κ: judge vs the exact scorer on number/set/id items); raw agreement 1.000, binary κ 1.000 (judge "partial" counted as incorrect; n = 75). Self-consistency 0.990 (n = 96). Human κ: not yet measured.
