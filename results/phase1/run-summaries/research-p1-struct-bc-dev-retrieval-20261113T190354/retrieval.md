# Retrieval: research-p1-struct-bc-dev-retrieval-20261113T190354

Corpus `research`, system `p1-struct-bc`, split `dev`, 53 items. Settings: fusion linear, linear_w 0.9, w_bc 3, prefix True, rerank False. Index fingerprint `d3902b136e26732774bdfe4ffdcf6919f01308d5ede930baa79d9eaefac7f0a3`. Metrics version 2. No model calls. Wall-clock 197.3 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 45 | 0.872 [0.771, 0.956] | 0.769 [0.665, 0.862] | 0.737 [0.630, 0.837] | 0.790 [0.682, 0.891] | 3263.4 [3161.4, 3361.5] | 0.200 |
| rarity head | 30 | 0.841 [0.700, 0.967] | 0.742 [0.607, 0.864] | 0.714 [0.572, 0.844] | 0.780 [0.636, 0.902] | 3279.7 [3138.3, 3416.3] | 0.200 |
| rarity tail | 15 | 0.933 [0.800, 1.000] | 0.822 [0.658, 0.951] | 0.783 [0.600, 0.933] | 0.809 [0.626, 0.963] | 3230.9 [3109.4, 3350.8] | – |
| qtype count_filter | 8 | 0.528 [0.182, 0.875] | 0.421 [0.145, 0.717] | 0.406 [0.125, 0.688] | 0.528 [0.182, 0.875] | 3320.2 [3012.8, 3555.5] | 0.200 |
| qtype factoid | 9 | 1.000 [1.000, 1.000] | 0.937 [0.810, 1.000] | 0.917 [0.750, 1.000] | 1.000 [1.000, 1.000] | 3170.2 [2891.8, 3423.6] | – |
| qtype id_lookup | 8 | 0.875 [0.625, 1.000] | 0.766 [0.500, 0.954] | 0.729 [0.458, 0.938] | 0.875 [0.625, 1.000] | 3452.1 [3192.1, 3670.0] | – |
| qtype overview | 11 | 0.909 [0.727, 1.000] | 0.808 [0.617, 0.966] | 0.773 [0.545, 0.955] | 0.760 [0.528, 0.949] | 3264.8 [3124.2, 3402.1] | – |
| qtype procedure | 9 | 1.000 [1.000, 1.000] | 0.862 [0.725, 1.000] | 0.815 [0.630, 1.000] | 0.772 [0.586, 0.930] | 3136.7 [2973.4, 3286.9] | – |

Chunks 9554; span containment 0.835.
