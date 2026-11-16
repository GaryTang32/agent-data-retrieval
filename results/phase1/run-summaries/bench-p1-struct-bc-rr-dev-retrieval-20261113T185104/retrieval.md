# Retrieval: bench-p1-struct-bc-rr-dev-retrieval-20261113T185104

Corpus `bench`, system `p1-struct-bc-rr`, split `dev`, 156 items. Settings: fusion linear, linear_w 0.7, w_bc 1, prefix True, rerank True. Index fingerprint `1bb41a01a6096d12ffb2e780780f4cd5730b40c7dcb27ec0925dfcf166183c41`. Metrics version 2. No model calls. Wall-clock 1283.0 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 141 | 0.903 [0.853, 0.947] | 0.807 [0.753, 0.858] | 0.793 [0.733, 0.850] | 0.742 [0.685, 0.797] | 3077.8 [2980.5, 3166.7] | 0.706 |
| rarity head | 16 | 0.875 [0.688, 1.000] | 0.805 [0.618, 0.962] | 0.783 [0.583, 0.950] | 0.827 [0.639, 1.000] | 2921.2 [2524.4, 3246.9] | – |
| rarity none | 103 | 0.935 [0.887, 0.975] | 0.838 [0.782, 0.891] | 0.831 [0.768, 0.889] | 0.733 [0.673, 0.792] | 3125.4 [3024.8, 3218.5] | 0.706 |
| rarity tail | 22 | 0.773 [0.591, 0.955] | 0.662 [0.480, 0.824] | 0.625 [0.439, 0.799] | 0.724 [0.540, 0.886] | 2968.6 [2698.4, 3199.2] | – |
| qtype factoid | 93 | 0.935 [0.882, 0.978] | 0.828 [0.766, 0.886] | 0.796 [0.725, 0.863] | 0.743 [0.676, 0.806] | 3192.2 [3109.4, 3270.4] | 1.000 |
| qtype id_lookup | 9 | 1.000 [1.000, 1.000] | 0.881 [0.714, 1.000] | 0.843 [0.620, 1.000] | 1.000 [1.000, 1.000] | 3117.0 [2511.7, 3498.0] | – |
| qtype overview | 30 | 0.776 [0.632, 0.904] | 0.729 [0.591, 0.856] | 0.784 [0.646, 0.913] | 0.654 [0.511, 0.792] | 2830.4 [2586.2, 3057.4] | 0.444 |
| qtype procedure | 9 | 0.889 [0.667, 1.000] | 0.778 [0.556, 1.000] | 0.741 [0.481, 1.000] | 0.771 [0.537, 1.000] | 2681.0 [2100.4, 3184.5] | – |

Chunks 7400; span containment 0.178.
