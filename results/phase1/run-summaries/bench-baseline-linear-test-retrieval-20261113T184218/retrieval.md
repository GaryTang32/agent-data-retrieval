# Retrieval: bench-baseline-linear-test-retrieval-20261113T184218

Corpus `bench`, system `baseline-linear`, split `test`, 572 items. Settings: fusion linear, linear_w 0.7. Index fingerprint `62835d2b1430fbec6a7f0952a26ee6dd962fd787ff762a8b9a4e11d785ad46e0`. Metrics version 2. No model calls. Wall-clock 86.4 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 517 | 0.922 [0.900, 0.943] | 0.854 [0.829, 0.878] | 0.849 [0.821, 0.876] | 0.782 [0.755, 0.809] | 3352.0 [3322.8, 3380.4] | 0.684 |
| rarity head | 72 | 0.875 [0.792, 0.944] | 0.823 [0.738, 0.903] | 0.807 [0.716, 0.892] | 0.875 [0.792, 0.944] | 3208.2 [3117.5, 3295.1] | – |
| rarity none | 367 | 0.939 [0.916, 0.959] | 0.878 [0.852, 0.903] | 0.882 [0.852, 0.910] | 0.742 [0.712, 0.772] | 3401.0 [3368.6, 3432.2] | 0.684 |
| rarity tail | 78 | 0.885 [0.808, 0.949] | 0.769 [0.691, 0.844] | 0.731 [0.647, 0.813] | 0.885 [0.808, 0.949] | 3253.9 [3180.9, 3324.1] | – |
| qtype factoid | 325 | 0.954 [0.931, 0.975] | 0.883 [0.854, 0.910] | 0.866 [0.833, 0.897] | 0.771 [0.738, 0.803] | 3398.9 [3365.1, 3431.3] | 0.920 |
| qtype id_lookup | 34 | 0.971 [0.912, 1.000] | 0.956 [0.882, 1.000] | 0.951 [0.873, 1.000] | 0.971 [0.912, 1.000] | 3287.0 [3164.8, 3400.9] | – |
| qtype overview | 119 | 0.878 [0.827, 0.923] | 0.813 [0.762, 0.860] | 0.848 [0.789, 0.902] | 0.770 [0.712, 0.825] | 3312.4 [3244.2, 3376.4] | 0.569 |
| qtype procedure | 39 | 0.744 [0.590, 0.872] | 0.651 [0.512, 0.781] | 0.621 [0.477, 0.757] | 0.744 [0.590, 0.872] | 3138.4 [3044.4, 3232.3] | – |

Chunks 5587; span containment 0.202.
