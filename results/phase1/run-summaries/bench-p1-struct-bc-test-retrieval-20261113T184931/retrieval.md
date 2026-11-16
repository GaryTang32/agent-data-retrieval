# Retrieval: bench-p1-struct-bc-test-retrieval-20261113T184931

Corpus `bench`, system `p1-struct-bc`, split `test`, 572 items. Settings: fusion linear, linear_w 0.7, w_bc 1, prefix True, rerank False. Index fingerprint `8c7bb39d032b886872bf0d64c462a906c4ea0435712feae880018d0bfc121830`. Metrics version 2. No model calls. Wall-clock 90.3 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 517 | 0.919 [0.896, 0.940] | 0.853 [0.827, 0.877] | 0.856 [0.828, 0.882] | 0.780 [0.753, 0.808] | 2911.1 [2858.1, 2964.0] | 0.632 |
| rarity head | 72 | 0.903 [0.833, 0.972] | 0.835 [0.757, 0.908] | 0.813 [0.728, 0.893] | 0.847 [0.765, 0.923] | 2638.1 [2501.8, 2770.0] | – |
| rarity none | 367 | 0.929 [0.905, 0.951] | 0.875 [0.849, 0.900] | 0.893 [0.864, 0.920] | 0.745 [0.713, 0.777] | 2980.9 [2916.8, 3042.6] | 0.632 |
| rarity tail | 78 | 0.885 [0.808, 0.949] | 0.762 [0.683, 0.838] | 0.723 [0.636, 0.805] | 0.881 [0.808, 0.949] | 2834.8 [2707.5, 2962.2] | – |
| qtype factoid | 325 | 0.949 [0.925, 0.971] | 0.886 [0.857, 0.913] | 0.874 [0.841, 0.904] | 0.788 [0.755, 0.820] | 3030.2 [2965.7, 3090.3] | 0.960 |
| qtype id_lookup | 34 | 1.000 [1.000, 1.000] | 0.940 [0.879, 0.989] | 0.921 [0.841, 0.985] | 1.000 [1.000, 1.000] | 2760.5 [2536.7, 2965.9] | – |
| qtype overview | 119 | 0.877 [0.832, 0.919] | 0.796 [0.747, 0.840] | 0.855 [0.797, 0.906] | 0.749 [0.688, 0.809] | 2669.2 [2542.3, 2790.3] | 0.471 |
| qtype procedure | 39 | 0.718 [0.564, 0.846] | 0.672 [0.531, 0.803] | 0.656 [0.513, 0.791] | 0.616 [0.467, 0.757] | 2787.9 [2621.6, 2947.1] | – |

Chunks 7400; span containment 0.178.
