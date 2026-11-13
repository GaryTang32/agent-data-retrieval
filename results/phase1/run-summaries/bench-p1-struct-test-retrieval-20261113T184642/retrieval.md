# Retrieval: bench-p1-struct-test-retrieval-20261113T184642

Corpus `bench`, system `p1-struct`, split `test`, 572 items. Settings: fusion linear, linear_w 0.65, w_bc 0, prefix False, rerank False. Index fingerprint `5882fe1ba4424d7ef63db666cf21c89dcc9a0004a01d6622bd5f5aa54111aa88`. Metrics version 2. No model calls. Wall-clock 92.8 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 517 | 0.915 [0.891, 0.937] | 0.843 [0.818, 0.868] | 0.839 [0.810, 0.866] | 0.739 [0.711, 0.768] | 2916.7 [2867.1, 2964.8] | 0.658 |
| rarity head | 72 | 0.875 [0.792, 0.944] | 0.801 [0.716, 0.881] | 0.777 [0.687, 0.862] | 0.823 [0.736, 0.904] | 2621.1 [2488.3, 2753.4] | – |
| rarity none | 367 | 0.934 [0.911, 0.955] | 0.872 [0.845, 0.896] | 0.878 [0.849, 0.906] | 0.699 [0.667, 0.732] | 3002.0 [2943.7, 3056.7] | 0.658 |
| rarity tail | 78 | 0.859 [0.782, 0.936] | 0.749 [0.667, 0.827] | 0.712 [0.625, 0.796] | 0.851 [0.769, 0.923] | 2788.6 [2662.0, 2916.6] | – |
| qtype factoid | 325 | 0.951 [0.926, 0.972] | 0.876 [0.847, 0.903] | 0.859 [0.825, 0.890] | 0.741 [0.707, 0.774] | 3035.7 [2975.0, 3091.8] | 0.920 |
| qtype id_lookup | 34 | 1.000 [1.000, 1.000] | 0.935 [0.868, 0.989] | 0.915 [0.829, 0.985] | 1.000 [1.000, 1.000] | 2744.4 [2554.7, 2921.8] | – |
| qtype overview | 119 | 0.865 [0.813, 0.912] | 0.798 [0.747, 0.846] | 0.840 [0.781, 0.893] | 0.707 [0.641, 0.769] | 2725.9 [2610.8, 2836.3] | 0.529 |
| qtype procedure | 39 | 0.692 [0.538, 0.821] | 0.625 [0.482, 0.759] | 0.603 [0.457, 0.739] | 0.598 [0.451, 0.741] | 2657.7 [2491.2, 2817.2] | – |

Chunks 7400; span containment 0.178.
