# Retrieval: research-baseline-linear-dev-retrieval-20261113T184131

Corpus `research`, system `baseline-linear`, split `dev`, 53 items. Settings: fusion linear, linear_w 1.0. Index fingerprint `150af34ab34d41a83f6fe552a8313c6a514f26b1567cb6205e3e633f21c6becc`. Metrics version 2. No model calls. Wall-clock 308.8 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 45 | 0.846 [0.735, 0.935] | 0.697 [0.591, 0.799] | 0.662 [0.549, 0.774] | 0.846 [0.735, 0.935] | 3804.6 [3752.0, 3853.7] | 0.200 |
| rarity head | 30 | 0.836 [0.700, 0.967] | 0.689 [0.555, 0.810] | 0.659 [0.520, 0.787] | 0.836 [0.700, 0.967] | 3781.6 [3705.8, 3848.8] | 0.200 |
| rarity tail | 15 | 0.867 [0.667, 1.000] | 0.715 [0.515, 0.895] | 0.668 [0.449, 0.867] | 0.867 [0.667, 1.000] | 3850.4 [3793.4, 3900.8] | – |
| qtype count_filter | 8 | 0.511 [0.148, 0.875] | 0.431 [0.139, 0.727] | 0.479 [0.167, 0.792] | 0.511 [0.148, 0.875] | 3673.8 [3538.6, 3809.1] | 0.200 |
| qtype factoid | 9 | 1.000 [1.000, 1.000] | 0.799 [0.639, 0.944] | 0.731 [0.519, 0.926] | 1.000 [1.000, 1.000] | 3861.6 [3790.4, 3922.4] | – |
| qtype id_lookup | 8 | 1.000 [1.000, 1.000] | 0.774 [0.595, 0.954] | 0.701 [0.465, 0.938] | 1.000 [1.000, 1.000] | 3820.9 [3661.5, 3930.4] | – |
| qtype overview | 11 | 0.818 [0.545, 1.000] | 0.675 [0.428, 0.890] | 0.630 [0.373, 0.864] | 0.818 [0.545, 1.000] | 3875.6 [3809.8, 3925.8] | – |
| qtype procedure | 9 | 0.889 [0.667, 1.000] | 0.792 [0.556, 1.000] | 0.759 [0.500, 1.000] | 0.889 [0.667, 1.000] | 3762.4 [3634.9, 3877.6] | – |

Chunks 7305; span containment 1.000.
