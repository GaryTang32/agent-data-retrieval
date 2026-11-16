# Retrieval: research-p1-struct-bc-rr-test-retrieval-20261113T192200

Corpus `research`, system `p1-struct-bc-rr`, split `test`, 222 items. Settings: fusion linear, linear_w 0.9, w_bc 3, prefix True, rerank True. Index fingerprint `2bab116ff64eb92d0d626b3205ec3d6ee5d55c3c28104207a089e07998cfcfd2`. Metrics version 2. No model calls. Wall-clock 1907.1 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 180 | 0.715 [0.649, 0.779] | 0.576 [0.515, 0.637] | 0.545 [0.481, 0.609] | 0.649 [0.585, 0.712] | 3141.0 [3079.0, 3201.3] | 0.118 |
| rarity head | 113 | 0.679 [0.596, 0.760] | 0.542 [0.464, 0.617] | 0.519 [0.437, 0.598] | 0.634 [0.553, 0.713] | 3154.1 [3076.4, 3225.9] | 0.118 |
| rarity tail | 67 | 0.776 [0.672, 0.866] | 0.635 [0.538, 0.728] | 0.590 [0.488, 0.690] | 0.674 [0.575, 0.770] | 3118.8 [3010.6, 3221.6] | – |
| qtype count_filter | 27 | 0.398 [0.243, 0.562] | 0.240 [0.142, 0.348] | 0.276 [0.156, 0.410] | 0.398 [0.243, 0.562] | 3244.6 [3144.1, 3342.0] | 0.118 |
| qtype factoid | 40 | 0.825 [0.700, 0.925] | 0.714 [0.591, 0.829] | 0.679 [0.547, 0.802] | 0.820 [0.695, 0.925] | 3153.5 [3036.9, 3264.6] | – |
| qtype id_lookup | 39 | 0.744 [0.590, 0.872] | 0.610 [0.476, 0.742] | 0.568 [0.429, 0.706] | 0.744 [0.590, 0.872] | 3146.7 [2992.3, 3287.8] | – |
| qtype overview | 35 | 0.629 [0.457, 0.771] | 0.455 [0.321, 0.590] | 0.400 [0.267, 0.538] | 0.556 [0.403, 0.704] | 2918.3 [2754.5, 3079.7] | – |
| qtype procedure | 39 | 0.872 [0.769, 0.974] | 0.743 [0.624, 0.850] | 0.702 [0.574, 0.821] | 0.636 [0.520, 0.749] | 3250.5 [3147.8, 3355.1] | – |

Chunks 9554; span containment 0.835.
