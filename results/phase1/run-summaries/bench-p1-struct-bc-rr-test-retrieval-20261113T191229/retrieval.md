# Retrieval: bench-p1-struct-bc-rr-test-retrieval-20261113T191229

Corpus `bench`, system `p1-struct-bc-rr`, split `test`, 572 items. Settings: fusion linear, linear_w 0.7, w_bc 1, prefix True, rerank True. Index fingerprint `1bb41a01a6096d12ffb2e780780f4cd5730b40c7dcb27ec0925dfcf166183c41`. Metrics version 2. No model calls. Wall-clock 4108.8 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 517 | 0.901 [0.877, 0.924] | 0.825 [0.799, 0.851] | 0.830 [0.800, 0.857] | 0.747 [0.718, 0.776] | 2965.4 [2907.9, 3021.8] | 0.539 |
| rarity head | 72 | 0.875 [0.792, 0.944] | 0.818 [0.735, 0.896] | 0.800 [0.713, 0.883] | 0.820 [0.732, 0.903] | 2657.8 [2493.5, 2816.7] | – |
| rarity none | 367 | 0.907 [0.880, 0.931] | 0.844 [0.815, 0.872] | 0.864 [0.832, 0.895] | 0.701 [0.667, 0.733] | 3018.5 [2949.9, 3082.7] | 0.539 |
| rarity tail | 78 | 0.897 [0.821, 0.962] | 0.744 [0.668, 0.818] | 0.694 [0.609, 0.778] | 0.896 [0.821, 0.960] | 2999.3 [2863.1, 3125.8] | – |
| qtype factoid | 325 | 0.928 [0.898, 0.954] | 0.852 [0.819, 0.883] | 0.838 [0.803, 0.873] | 0.747 [0.711, 0.780] | 3100.3 [3036.7, 3159.0] | 0.760 |
| qtype id_lookup | 34 | 0.941 [0.853, 1.000] | 0.899 [0.802, 0.978] | 0.885 [0.782, 0.971] | 0.941 [0.853, 1.000] | 2787.2 [2516.2, 3034.3] | – |
| qtype overview | 119 | 0.851 [0.801, 0.899] | 0.792 [0.741, 0.840] | 0.868 [0.813, 0.918] | 0.711 [0.648, 0.773] | 2718.4 [2577.8, 2852.9] | 0.431 |
| qtype procedure | 39 | 0.795 [0.667, 0.923] | 0.640 [0.514, 0.759] | 0.590 [0.456, 0.720] | 0.690 [0.551, 0.824] | 2750.1 [2512.1, 2968.8] | – |

Chunks 7400; span containment 0.178.
