# Retrieval: bench-baseline-rrf-test-retrieval-20261113T184420

Corpus `bench`, system `baseline-rrf`, split `test`, 572 items. Settings: fusion rrf, linear_w None. Index fingerprint `62835d2b1430fbec6a7f0952a26ee6dd962fd787ff762a8b9a4e11d785ad46e0`. Metrics version 2. No model calls. Wall-clock 77.4 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 517 | 0.859 [0.828, 0.887] | 0.766 [0.734, 0.796] | 0.756 [0.721, 0.789] | 0.698 [0.666, 0.728] | 3343.1 [3313.9, 3371.7] | 0.671 |
| rarity head | 72 | 0.694 [0.583, 0.806] | 0.612 [0.510, 0.717] | 0.586 [0.481, 0.694] | 0.694 [0.583, 0.806] | 3198.6 [3106.0, 3290.9] | – |
| rarity none | 367 | 0.905 [0.877, 0.931] | 0.824 [0.793, 0.854] | 0.826 [0.792, 0.859] | 0.677 [0.644, 0.710] | 3395.8 [3365.4, 3425.1] | 0.671 |
| rarity tail | 78 | 0.795 [0.705, 0.885] | 0.632 [0.541, 0.720] | 0.581 [0.484, 0.676] | 0.795 [0.705, 0.885] | 3228.2 [3139.6, 3309.3] | – |
| qtype factoid | 325 | 0.900 [0.866, 0.932] | 0.802 [0.765, 0.838] | 0.777 [0.736, 0.816] | 0.697 [0.659, 0.733] | 3393.8 [3362.2, 3424.0] | 0.920 |
| qtype id_lookup | 34 | 0.765 [0.618, 0.912] | 0.653 [0.506, 0.793] | 0.620 [0.467, 0.771] | 0.765 [0.618, 0.912] | 3330.1 [3242.9, 3414.5] | – |
| qtype overview | 119 | 0.846 [0.790, 0.898] | 0.773 [0.716, 0.825] | 0.818 [0.754, 0.878] | 0.698 [0.635, 0.760] | 3317.7 [3252.3, 3380.3] | 0.549 |
| qtype procedure | 39 | 0.641 [0.487, 0.795] | 0.537 [0.396, 0.675] | 0.505 [0.360, 0.649] | 0.641 [0.487, 0.795] | 3009.2 [2851.1, 3152.6] | – |

Chunks 5587; span containment 0.202.
