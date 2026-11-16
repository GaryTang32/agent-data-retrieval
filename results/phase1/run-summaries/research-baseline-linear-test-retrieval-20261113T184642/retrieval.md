# Retrieval: research-baseline-linear-test-retrieval-20261113T184642

Corpus `research`, system `baseline-linear`, split `test`, 222 items. Settings: fusion linear, linear_w 1.0. Index fingerprint `150af34ab34d41a83f6fe552a8313c6a514f26b1567cb6205e3e633f21c6becc`. Metrics version 2. No model calls. Wall-clock 295.2 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 180 | 0.856 [0.802, 0.905] | 0.710 [0.654, 0.764] | 0.676 [0.616, 0.734] | 0.856 [0.802, 0.905] | 3751.6 [3720.6, 3781.6] | 0.353 |
| rarity head | 113 | 0.851 [0.785, 0.911] | 0.679 [0.610, 0.746] | 0.645 [0.571, 0.718] | 0.851 [0.785, 0.911] | 3722.1 [3681.8, 3760.9] | 0.353 |
| rarity tail | 67 | 0.866 [0.776, 0.940] | 0.761 [0.669, 0.847] | 0.729 [0.631, 0.823] | 0.866 [0.776, 0.940] | 3801.4 [3755.1, 3843.2] | – |
| qtype count_filter | 27 | 0.673 [0.505, 0.826] | 0.424 [0.295, 0.557] | 0.434 [0.287, 0.589] | 0.673 [0.505, 0.826] | 3563.2 [3504.6, 3626.3] | 0.353 |
| qtype factoid | 40 | 0.975 [0.925, 1.000] | 0.884 [0.804, 0.952] | 0.854 [0.760, 0.938] | 0.975 [0.925, 1.000] | 3773.1 [3715.3, 3827.3] | – |
| qtype id_lookup | 39 | 0.897 [0.795, 0.974] | 0.783 [0.670, 0.884] | 0.746 [0.623, 0.859] | 0.897 [0.795, 0.974] | 3771.9 [3697.6, 3841.9] | – |
| qtype overview | 35 | 0.686 [0.514, 0.829] | 0.509 [0.369, 0.646] | 0.455 [0.310, 0.600] | 0.686 [0.514, 0.829] | 3802.1 [3735.7, 3858.8] | – |
| qtype procedure | 39 | 0.974 [0.923, 1.000] | 0.836 [0.753, 0.912] | 0.789 [0.688, 0.885] | 0.974 [0.923, 1.000] | 3794.6 [3731.7, 3848.0] | – |

Chunks 7305; span containment 1.000.
