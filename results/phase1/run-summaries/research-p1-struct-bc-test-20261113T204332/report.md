# Report: research-p1-struct-bc-test-20261113T204332

Corpus `research`, system `p1-struct-bc`, split `test`, 1 repeats, 222 rows, status `complete`. Generator `claude-sonnet-5-5`, judge `claude-opus-5-5`, linear w = 0.9. Metrics version 2.

> **Warning:** judge and generator share a model family

Values in brackets are 95% CIs (percentile bootstrap, 10,000 resamples). End to end: cluster bootstrap over items of the statistic shown, using every repeat (items are resampled with all their rows); none where fewer than 2 items contribute. G3 retrieval: bootstrap of the mean over items at repeat 0 (retrieval is deterministic); none where n < 2.

## End to end

| n | accuracy | error | abstained | partial | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|---|---|
| 222 | 0.779 [0.721, 0.833] | 0.000 | 0.054 | 0.041 | 0.613 [0.509, 0.707] | 0.279 [0.077, 0.468] | -0.721 [-1.225, -0.248] |

| stratum | n | accuracy | penalised t=0.5 | penalised t=0.75 | penalised t=0.9 |
|---|---|---|---|---|---|
| qtype count_filter | 27 | 0.481 [0.296, 0.667] | 0.074 [-0.296, 0.407] | -0.741 [-1.481, -0.037] | -3.185 [-5.037, -1.370] |
| qtype factoid | 40 | 0.950 [0.875, 1.000] | 0.925 [0.800, 1.000] | 0.875 [0.650, 1.000] | 0.725 [0.200, 1.000] |
| qtype id_lookup | 39 | 0.897 [0.795, 0.974] | 0.897 [0.795, 0.974] | 0.897 [0.795, 0.974] | 0.897 [0.795, 0.974] |
| qtype insufficient | 42 | 0.786 [0.643, 0.905] | 0.571 [0.286, 0.810] | 0.143 [-0.429, 0.619] | -1.143 [-2.571, 0.048] |
| qtype overview | 35 | 0.486 [0.314, 0.657] | 0.086 [-0.229, 0.400] | -0.714 [-1.371, -0.086] | -3.114 [-4.771, -1.486] |
| qtype procedure | 39 | 0.949 [0.872, 1.000] | 0.897 [0.744, 1.000] | 0.795 [0.487, 1.000] | 0.487 [-0.282, 1.000] |
| rarity head | 113 | 0.770 [0.690, 0.841] | 0.619 [0.478, 0.743] | 0.319 [0.053, 0.566] | -0.584 [-1.257, 0.027] |
| rarity none | 42 | 0.786 [0.643, 0.905] | 0.571 [0.286, 0.810] | 0.143 [-0.429, 0.619] | -1.143 [-2.571, 0.048] |
| rarity tail | 67 | 0.791 [0.687, 0.881] | 0.627 [0.448, 0.791] | 0.299 [-0.075, 0.627] | -0.687 [-1.597, 0.179] |
| head/count_filter | 27 | 0.481 [0.296, 0.667] | 0.074 [-0.296, 0.407] | -0.741 [-1.481, -0.037] | -3.185 [-5.037, -1.370] |
| head/factoid | 21 | 0.905 [0.762, 1.000] | 0.857 [0.619, 1.000] | 0.762 [0.333, 1.000] | 0.476 [-0.524, 1.000] |
| head/id_lookup | 34 | 0.912 [0.794, 1.000] | 0.912 [0.794, 1.000] | 0.912 [0.794, 1.000] | 0.912 [0.794, 1.000] |
| head/overview | 12 | 0.583 [0.333, 0.833] | 0.333 [-0.167, 0.750] | -0.167 [-1.167, 0.667] | -1.667 [-4.167, 0.667] |
| head/procedure | 19 | 0.895 [0.737, 1.000] | 0.789 [0.474, 1.000] | 0.579 [-0.053, 1.000] | -0.053 [-1.632, 1.000] |
| none/insufficient | 42 | 0.786 [0.643, 0.905] | 0.571 [0.286, 0.810] | 0.143 [-0.429, 0.619] | -1.143 [-2.571, 0.048] |
| tail/factoid | 19 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| tail/id_lookup | 5 | 0.800 [0.400, 1.000] | 0.800 [0.400, 1.000] | 0.800 [0.400, 1.000] | 0.800 [0.400, 1.000] |
| tail/overview | 23 | 0.435 [0.261, 0.652] | -0.043 [-0.435, 0.348] | -1.000 [-1.826, -0.217] | -3.870 [-6.000, -1.826] |
| tail/procedure | 20 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |

Citation precision 0.708, evidence cited 0.875. Tokens 3237907 in / 87115 out. Spent $0.0000 in total (authoritative: every call, including any row dropped at a budget stop); rows written sum to $0.0000. Latency p50 6.184 s, p95 10.951 s (uncached calls: 222). Errors: 0.

JSON recovered (a reply held several objects or prose; the last object with the required keys was used) in 10 row(s): query 8, answer 2.

## G3 retrieval (excluding `insufficient`)

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 180 | 0.844 [0.789, 0.894] | 0.710 [0.654, 0.765] | 0.677 [0.617, 0.736] | 0.764 [0.706, 0.818] | 3181.717 | 0.353 |
| rarity head | 113 | 0.831 [0.762, 0.896] | 0.673 [0.604, 0.742] | 0.638 [0.564, 0.712] | 0.782 [0.710, 0.850] | 3149.062 | 0.353 |
| rarity tail | 67 | 0.866 [0.776, 0.940] | 0.772 [0.682, 0.855] | 0.743 [0.646, 0.833] | 0.733 [0.641, 0.819] | 3236.791 | – |
| qtype count_filter | 27 | 0.624 [0.447, 0.793] | 0.385 [0.256, 0.522] | 0.378 [0.236, 0.534] | 0.624 [0.447, 0.793] | 3181.519 | 0.353 |
| qtype factoid | 40 | 0.975 [0.925, 1.000] | 0.853 [0.769, 0.929] | 0.814 [0.712, 0.908] | 0.975 [0.924, 1.000] | 3192.050 | – |
| qtype id_lookup | 39 | 0.846 [0.718, 0.949] | 0.764 [0.642, 0.875] | 0.738 [0.609, 0.853] | 0.846 [0.718, 0.949] | 3233.667 | – |
| qtype overview | 35 | 0.686 [0.514, 0.829] | 0.558 [0.415, 0.700] | 0.517 [0.369, 0.664] | 0.567 [0.422, 0.710] | 3013.943 | – |
| qtype procedure | 39 | 1.000 [1.000, 1.000] | 0.871 [0.808, 0.930] | 0.827 [0.741, 0.906] | 0.738 [0.648, 0.827] | 3269.872 | – |
| head/count_filter | 27 | 0.624 [0.447, 0.793] | 0.385 [0.256, 0.522] | 0.378 [0.236, 0.534] | 0.624 [0.447, 0.793] | 3181.519 | 0.353 |
| head/factoid | 21 | 0.952 [0.857, 1.000] | 0.783 [0.655, 0.896] | 0.726 [0.575, 0.865] | 0.952 [0.856, 1.000] | 3125.619 | – |
| head/id_lookup | 34 | 0.912 [0.794, 1.000] | 0.838 [0.729, 0.930] | 0.813 [0.695, 0.916] | 0.912 [0.794, 1.000] | 3221.118 | – |
| head/overview | 12 | 0.583 [0.333, 0.833] | 0.474 [0.230, 0.719] | 0.438 [0.208, 0.688] | 0.544 [0.294, 0.794] | 2833.583 | – |
| head/procedure | 19 | 1.000 [1.000, 1.000] | 0.794 [0.692, 0.889] | 0.724 [0.588, 0.851] | 0.737 [0.596, 0.869] | 3199.158 | – |
| tail/factoid | 19 | 1.000 [1.000, 1.000] | 0.931 [0.827, 1.000] | 0.911 [0.777, 1.000] | 1.000 [1.000, 1.000] | 3265.474 | – |
| tail/id_lookup | 5 | 0.400 [0.000, 0.800] | 0.263 [0.000, 0.663] | 0.225 [0.000, 0.625] | 0.400 [0.000, 0.800] | 3319.000 | – |
| tail/overview | 23 | 0.739 [0.565, 0.913] | 0.602 [0.426, 0.767] | 0.558 [0.377, 0.732] | 0.579 [0.403, 0.753] | 3108.043 | – |
| tail/procedure | 20 | 1.000 [1.000, 1.000] | 0.945 [0.889, 1.000] | 0.925 [0.850, 1.000] | 0.739 [0.615, 0.852] | 3337.050 | – |

## Determinism

Retrieval identity: not measured (1 repeat); answer agreement: not measured; pass^1 0.779.

## G2 query understanding

Route accuracy over rows whose gold op is not `abstain`; record match over rows whose gold query can be executed on the records; entity F1 over rows whose gold query lists entities. Per-field hits are kept in report.json as diagnostics.

| route accuracy | n | record match | n | entity F1 | n |
|---|---|---|---|---|---|
| 0.661 | 180 | 0.963 | 27 | 0.565 | 180 |

## G1 compile

Span containment 0.835; text fidelity 1.000; empty documents 0; index fingerprint `d3902b136e26732774bdfe4ffdcf6919f01308d5ede930baa79d9eaefac7f0a3`.

## Judge

Proxy κ 0.948 (n = 72; proxy, not human κ: judge vs the exact scorer on number/set/id items); raw agreement 0.986, binary κ 0.948 (judge "partial" counted as incorrect; n = 72). Self-consistency 1.000 (n = 96). Human κ: not yet measured.
