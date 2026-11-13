# Retrieval: research-p1-struct-dev-retrieval-20261113T185738

Corpus `research`, system `p1-struct`, split `dev`, 53 items. Settings: fusion linear, linear_w 0.75, w_bc 0, prefix False, rerank False. Index fingerprint `0b92bd70e9abe27f035e4962acf70f08bd1e8dca28992aaaa396feaec1197bd4`. Metrics version 2. No model calls. Wall-clock 179.9 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 45 | 0.891 [0.800, 0.978] | 0.771 [0.670, 0.862] | 0.742 [0.634, 0.843] | 0.791 [0.683, 0.890] | 3228.5 [3134.9, 3322.5] | 0.200 |
| rarity head | 30 | 0.870 [0.739, 0.970] | 0.758 [0.627, 0.874] | 0.737 [0.598, 0.861] | 0.809 [0.673, 0.922] | 3277.6 [3150.7, 3400.3] | 0.200 |
| rarity tail | 15 | 0.933 [0.800, 1.000] | 0.797 [0.621, 0.933] | 0.754 [0.556, 0.933] | 0.756 [0.559, 0.925] | 3130.5 [3022.3, 3248.5] | – |
| qtype count_filter | 8 | 0.511 [0.148, 0.875] | 0.427 [0.135, 0.723] | 0.458 [0.146, 0.771] | 0.511 [0.148, 0.875] | 3447.6 [3357.4, 3553.1] | 0.200 |
| qtype factoid | 9 | 1.000 [1.000, 1.000] | 0.928 [0.785, 1.000] | 0.907 [0.722, 1.000] | 1.000 [1.000, 1.000] | 3134.9 [2869.3, 3385.9] | – |
| qtype id_lookup | 8 | 1.000 [1.000, 1.000] | 0.756 [0.569, 0.938] | 0.679 [0.437, 0.917] | 1.000 [1.000, 1.000] | 3336.8 [3156.6, 3551.4] | – |
| qtype overview | 11 | 0.909 [0.727, 1.000] | 0.815 [0.600, 1.000] | 0.786 [0.552, 1.000] | 0.688 [0.446, 0.902] | 3254.7 [3099.4, 3435.5] | – |
| qtype procedure | 9 | 1.000 [1.000, 1.000] | 0.877 [0.754, 1.000] | 0.833 [0.667, 1.000] | 0.772 [0.586, 0.930] | 2999.2 [2867.9, 3144.3] | – |

Chunks 9554; span containment 0.835.
