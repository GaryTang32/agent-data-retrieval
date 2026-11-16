# Retrieval: bench-p1-struct-bc-dev-retrieval-20261113T184819

Corpus `bench`, system `p1-struct-bc`, split `dev`, 156 items. Settings: fusion linear, linear_w 0.7, w_bc 1, prefix True, rerank False. Index fingerprint `8c7bb39d032b886872bf0d64c462a906c4ea0435712feae880018d0bfc121830`. Metrics version 2. No model calls. Wall-clock 70.9 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 141 | 0.968 [0.940, 0.992] | 0.888 [0.848, 0.924] | 0.880 [0.834, 0.924] | 0.804 [0.756, 0.851] | 3004.1 [2905.1, 3097.0] | 0.706 |
| rarity head | 16 | 1.000 [1.000, 1.000] | 0.875 [0.757, 0.969] | 0.833 [0.677, 0.958] | 0.959 [0.878, 1.000] | 2840.4 [2508.4, 3118.5] | – |
| rarity none | 103 | 0.976 [0.950, 0.996] | 0.908 [0.867, 0.945] | 0.911 [0.863, 0.954] | 0.767 [0.713, 0.820] | 3098.8 [2994.4, 3197.8] | 0.706 |
| rarity tail | 22 | 0.909 [0.773, 1.000] | 0.805 [0.660, 0.933] | 0.770 [0.611, 0.909] | 0.867 [0.726, 0.981] | 2679.6 [2392.7, 2918.7] | – |
| qtype factoid | 93 | 1.000 [1.000, 1.000] | 0.926 [0.886, 0.962] | 0.907 [0.854, 0.953] | 0.792 [0.738, 0.844] | 3142.6 [3047.2, 3230.2] | 1.000 |
| qtype id_lookup | 9 | 1.000 [1.000, 1.000] | 0.959 [0.877, 1.000] | 0.944 [0.833, 1.000] | 1.000 [1.000, 1.000] | 2934.9 [2436.0, 3306.0] | – |
| qtype overview | 30 | 0.852 [0.733, 0.954] | 0.772 [0.657, 0.874] | 0.819 [0.700, 0.925] | 0.757 [0.624, 0.876] | 2713.1 [2472.8, 2943.9] | 0.444 |
| qtype procedure | 9 | 1.000 [1.000, 1.000] | 0.805 [0.611, 1.000] | 0.744 [0.489, 1.000] | 0.897 [0.747, 1.000] | 2612.3 [2061.7, 3024.1] | – |

Chunks 7400; span containment 0.178.
