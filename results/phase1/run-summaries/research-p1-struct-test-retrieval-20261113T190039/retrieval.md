# Retrieval: research-p1-struct-test-retrieval-20261113T190039

Corpus `research`, system `p1-struct`, split `test`, 222 items. Settings: fusion linear, linear_w 0.75, w_bc 0, prefix False, rerank False. Index fingerprint `0b92bd70e9abe27f035e4962acf70f08bd1e8dca28992aaaa396feaec1197bd4`. Metrics version 2. No model calls. Wall-clock 192.4 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 180 | 0.848 [0.793, 0.897] | 0.692 [0.636, 0.746] | 0.652 [0.593, 0.709] | 0.765 [0.707, 0.820] | 3149.5 [3092.5, 3205.1] | 0.294 |
| rarity head | 113 | 0.846 [0.780, 0.907] | 0.663 [0.595, 0.729] | 0.619 [0.546, 0.689] | 0.795 [0.726, 0.859] | 3143.7 [3067.7, 3215.9] | 0.294 |
| rarity tail | 67 | 0.851 [0.761, 0.925] | 0.742 [0.650, 0.827] | 0.707 [0.609, 0.801] | 0.714 [0.620, 0.802] | 3159.4 [3069.7, 3243.3] | – |
| qtype count_filter | 27 | 0.651 [0.485, 0.807] | 0.359 [0.247, 0.475] | 0.331 [0.213, 0.460] | 0.651 [0.485, 0.807] | 3225.9 [3112.0, 3333.4] | 0.294 |
| qtype factoid | 40 | 0.950 [0.875, 1.000] | 0.833 [0.742, 0.915] | 0.795 [0.690, 0.893] | 0.950 [0.875, 1.000] | 3159.2 [3045.6, 3265.0] | – |
| qtype id_lookup | 39 | 0.846 [0.718, 0.949] | 0.766 [0.645, 0.876] | 0.740 [0.612, 0.855] | 0.846 [0.718, 0.949] | 3218.4 [3076.2, 3340.6] | – |
| qtype overview | 35 | 0.714 [0.571, 0.857] | 0.515 [0.382, 0.646] | 0.452 [0.314, 0.592] | 0.567 [0.423, 0.709] | 2942.8 [2791.5, 3089.9] | – |
| qtype procedure | 39 | 1.000 [1.000, 1.000] | 0.865 [0.802, 0.924] | 0.818 [0.733, 0.897] | 0.751 [0.660, 0.841] | 3203.3 [3097.5, 3305.3] | – |

Chunks 9554; span containment 0.835.
