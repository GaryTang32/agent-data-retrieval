# Retrieval: bench-baseline-rrf-dev-retrieval-20261113T184348

Corpus `bench`, system `baseline-rrf`, split `dev`, 156 items. Settings: fusion rrf, linear_w None. Index fingerprint `62835d2b1430fbec6a7f0952a26ee6dd962fd787ff762a8b9a4e11d785ad46e0`. Metrics version 2. No model calls. Wall-clock 28.4 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 141 | 0.882 [0.829, 0.930] | 0.773 [0.716, 0.828] | 0.752 [0.688, 0.814] | 0.699 [0.642, 0.754] | 3365.0 [3315.3, 3413.0] | 0.647 |
| rarity head | 16 | 0.875 [0.688, 1.000] | 0.626 [0.447, 0.803] | 0.552 [0.351, 0.756] | 0.875 [0.688, 1.000] | 3148.1 [2945.4, 3339.3] | – |
| rarity none | 103 | 0.925 [0.876, 0.967] | 0.834 [0.777, 0.887] | 0.822 [0.757, 0.882] | 0.675 [0.616, 0.733] | 3430.8 [3384.1, 3474.5] | 0.647 |
| rarity tail | 22 | 0.682 [0.500, 0.864] | 0.598 [0.410, 0.774] | 0.570 [0.379, 0.752] | 0.682 [0.500, 0.864] | 3214.5 [3068.7, 3350.1] | – |
| qtype factoid | 93 | 0.909 [0.849, 0.962] | 0.803 [0.734, 0.867] | 0.773 [0.696, 0.847] | 0.666 [0.599, 0.733] | 3433.6 [3384.6, 3480.6] | 0.875 |
| qtype id_lookup | 9 | 0.889 [0.667, 1.000] | 0.603 [0.381, 0.811] | 0.513 [0.270, 0.759] | 0.889 [0.667, 1.000] | 3293.0 [3122.1, 3449.8] | – |
| qtype overview | 30 | 0.860 [0.748, 0.956] | 0.783 [0.672, 0.884] | 0.804 [0.683, 0.917] | 0.754 [0.633, 0.863] | 3289.0 [3187.4, 3381.3] | 0.444 |
| qtype procedure | 9 | 0.667 [0.333, 1.000] | 0.611 [0.278, 0.889] | 0.593 [0.259, 0.889] | 0.667 [0.333, 1.000] | 2980.9 [2659.0, 3294.1] | – |

Chunks 5587; span containment 0.202.
