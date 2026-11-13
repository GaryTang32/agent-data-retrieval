# Retrieval: research-p1-struct-bc-test-retrieval-20261113T190713

Corpus `research`, system `p1-struct-bc`, split `test`, 222 items. Settings: fusion linear, linear_w 0.9, w_bc 3, prefix True, rerank False. Index fingerprint `d3902b136e26732774bdfe4ffdcf6919f01308d5ede930baa79d9eaefac7f0a3`. Metrics version 2. No model calls. Wall-clock 231.4 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 180 | 0.844 [0.789, 0.894] | 0.710 [0.654, 0.765] | 0.677 [0.617, 0.736] | 0.764 [0.706, 0.818] | 3181.7 [3123.7, 3238.9] | 0.353 |
| rarity head | 113 | 0.831 [0.762, 0.896] | 0.673 [0.604, 0.742] | 0.638 [0.564, 0.712] | 0.782 [0.710, 0.850] | 3149.1 [3070.2, 3223.0] | 0.353 |
| rarity tail | 67 | 0.866 [0.776, 0.940] | 0.772 [0.682, 0.855] | 0.743 [0.646, 0.833] | 0.733 [0.641, 0.819] | 3236.8 [3148.1, 3321.6] | – |
| qtype count_filter | 27 | 0.624 [0.447, 0.793] | 0.385 [0.256, 0.522] | 0.378 [0.236, 0.534] | 0.624 [0.447, 0.793] | 3181.5 [3069.7, 3287.4] | 0.353 |
| qtype factoid | 40 | 0.975 [0.925, 1.000] | 0.853 [0.769, 0.929] | 0.814 [0.712, 0.908] | 0.975 [0.924, 1.000] | 3192.1 [3091.4, 3289.3] | – |
| qtype id_lookup | 39 | 0.846 [0.718, 0.949] | 0.764 [0.642, 0.875] | 0.738 [0.609, 0.853] | 0.846 [0.718, 0.949] | 3233.7 [3068.1, 3373.9] | – |
| qtype overview | 35 | 0.686 [0.514, 0.829] | 0.558 [0.415, 0.700] | 0.517 [0.369, 0.664] | 0.567 [0.422, 0.710] | 3013.9 [2871.9, 3152.5] | – |
| qtype procedure | 39 | 1.000 [1.000, 1.000] | 0.871 [0.808, 0.930] | 0.827 [0.741, 0.906] | 0.738 [0.648, 0.827] | 3269.9 [3160.3, 3376.5] | – |

Chunks 9554; span containment 0.835.
