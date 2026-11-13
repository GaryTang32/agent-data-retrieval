# Retrieval: bench-baseline-linear-dev-retrieval-20261113T184131

Corpus `bench`, system `baseline-linear`, split `dev`, 156 items. Settings: fusion linear, linear_w 0.7. Index fingerprint `62835d2b1430fbec6a7f0952a26ee6dd962fd787ff762a8b9a4e11d785ad46e0`. Metrics version 2. No model calls. Wall-clock 44.4 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 141 | 0.970 [0.943, 0.992] | 0.881 [0.842, 0.917] | 0.865 [0.819, 0.910] | 0.811 [0.765, 0.854] | 3372.4 [3326.3, 3417.5] | 0.765 |
| rarity head | 16 | 1.000 [1.000, 1.000] | 0.887 [0.780, 0.977] | 0.849 [0.708, 0.969] | 1.000 [1.000, 1.000] | 3275.2 [3149.0, 3410.3] | – |
| rarity none | 103 | 0.969 [0.936, 0.994] | 0.887 [0.844, 0.928] | 0.878 [0.827, 0.926] | 0.751 [0.698, 0.803] | 3426.0 [3380.3, 3469.0] | 0.765 |
| rarity tail | 22 | 0.955 [0.864, 1.000] | 0.848 [0.714, 0.966] | 0.817 [0.662, 0.955] | 0.955 [0.864, 1.000] | 3192.0 [3038.6, 3335.8] | – |
| qtype factoid | 93 | 0.989 [0.968, 1.000] | 0.907 [0.863, 0.947] | 0.881 [0.826, 0.931] | 0.767 [0.713, 0.819] | 3433.9 [3384.3, 3481.5] | 1.000 |
| qtype id_lookup | 9 | 1.000 [1.000, 1.000] | 0.959 [0.877, 1.000] | 0.944 [0.833, 1.000] | 1.000 [1.000, 1.000] | 3359.8 [3215.1, 3486.2] | – |
| qtype overview | 30 | 0.892 [0.789, 0.974] | 0.823 [0.725, 0.910] | 0.858 [0.758, 0.950] | 0.833 [0.719, 0.933] | 3259.2 [3159.9, 3355.5] | 0.556 |
| qtype procedure | 9 | 1.000 [1.000, 1.000] | 0.726 [0.518, 0.924] | 0.645 [0.375, 0.903] | 1.000 [1.000, 1.000] | 3126.4 [2866.0, 3348.8] | – |

Chunks 5587; span containment 0.202.
