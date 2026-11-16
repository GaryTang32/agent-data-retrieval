# Retrieval: research-baseline-rrf-dev-retrieval-20261113T185141

Corpus `research`, system `baseline-rrf`, split `dev`, 53 items. Settings: fusion rrf, linear_w None. Index fingerprint `150af34ab34d41a83f6fe552a8313c6a514f26b1567cb6205e3e633f21c6becc`. Metrics version 2. No model calls. Wall-clock 171.9 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 45 | 0.728 [0.599, 0.846] | 0.549 [0.433, 0.664] | 0.497 [0.376, 0.619] | 0.728 [0.599, 0.846] | 3795.8 [3737.7, 3848.8] | 0.000 |
| rarity head | 30 | 0.725 [0.559, 0.870] | 0.530 [0.389, 0.669] | 0.474 [0.329, 0.619] | 0.725 [0.559, 0.870] | 3772.1 [3693.2, 3844.7] | 0.000 |
| rarity tail | 15 | 0.733 [0.467, 0.933] | 0.588 [0.368, 0.798] | 0.543 [0.311, 0.767] | 0.733 [0.467, 0.933] | 3843.3 [3774.8, 3903.9] | – |
| qtype count_filter | 8 | 0.345 [0.083, 0.667] | 0.184 [0.050, 0.351] | 0.160 [0.042, 0.292] | 0.345 [0.083, 0.667] | 3508.1 [3408.1, 3605.0] | 0.000 |
| qtype factoid | 9 | 0.778 [0.444, 1.000] | 0.626 [0.348, 0.877] | 0.574 [0.296, 0.833] | 0.778 [0.444, 1.000] | 3900.0 [3834.6, 3947.2] | – |
| qtype id_lookup | 8 | 0.625 [0.250, 0.875] | 0.404 [0.138, 0.679] | 0.337 [0.076, 0.639] | 0.625 [0.250, 0.875] | 3866.0 [3778.1, 3932.9] | – |
| qtype overview | 11 | 0.818 [0.545, 1.000] | 0.645 [0.409, 0.860] | 0.589 [0.342, 0.818] | 0.818 [0.545, 1.000] | 3840.2 [3749.7, 3912.5] | – |
| qtype procedure | 9 | 1.000 [1.000, 1.000] | 0.810 [0.619, 1.000] | 0.750 [0.500, 1.000] | 1.000 [1.000, 1.000] | 3830.8 [3706.9, 3923.6] | – |

Chunks 7305; span containment 1.000.
