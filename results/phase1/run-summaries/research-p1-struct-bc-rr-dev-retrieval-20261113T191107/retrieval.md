# Retrieval: research-p1-struct-bc-rr-dev-retrieval-20261113T191107

Corpus `research`, system `p1-struct-bc-rr`, split `dev`, 53 items. Settings: fusion linear, linear_w 0.9, w_bc 3, prefix True, rerank True. Index fingerprint `2bab116ff64eb92d0d626b3205ec3d6ee5d55c3c28104207a089e07998cfcfd2`. Metrics version 2. No model calls. Wall-clock 651.0 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 45 | 0.760 [0.639, 0.876] | 0.634 [0.515, 0.749] | 0.596 [0.472, 0.718] | 0.674 [0.552, 0.792] | 3306.8 [3212.2, 3399.8] | 0.000 |
| rarity head | 30 | 0.773 [0.620, 0.906] | 0.621 [0.480, 0.755] | 0.576 [0.430, 0.717] | 0.708 [0.557, 0.844] | 3335.7 [3211.3, 3456.3] | 0.000 |
| rarity tail | 15 | 0.733 [0.467, 0.933] | 0.659 [0.426, 0.867] | 0.636 [0.400, 0.867] | 0.607 [0.372, 0.826] | 3248.9 [3105.3, 3384.5] | – |
| qtype count_filter | 8 | 0.398 [0.102, 0.718] | 0.272 [0.062, 0.524] | 0.250 [0.042, 0.500] | 0.398 [0.102, 0.718] | 3461.0 [3346.0, 3578.1] | 0.000 |
| qtype factoid | 9 | 0.667 [0.333, 1.000] | 0.556 [0.278, 0.833] | 0.519 [0.222, 0.815] | 0.667 [0.333, 1.000] | 3122.2 [2881.6, 3342.0] | – |
| qtype id_lookup | 8 | 0.875 [0.625, 1.000] | 0.695 [0.437, 0.913] | 0.639 [0.354, 0.889] | 0.875 [0.625, 1.000] | 3446.8 [3241.5, 3667.9] | – |
| qtype overview | 11 | 0.818 [0.545, 1.000] | 0.650 [0.423, 0.865] | 0.594 [0.358, 0.821] | 0.711 [0.450, 0.935] | 3338.0 [3133.0, 3537.5] | – |
| qtype procedure | 9 | 1.000 [1.000, 1.000] | 0.959 [0.877, 1.000] | 0.944 [0.833, 1.000] | 0.705 [0.526, 0.873] | 3191.8 [3071.8, 3317.0] | – |

Chunks 9554; span containment 0.835.
