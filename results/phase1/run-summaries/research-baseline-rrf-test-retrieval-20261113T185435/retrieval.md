# Retrieval: research-baseline-rrf-test-retrieval-20261113T185435

Corpus `research`, system `baseline-rrf`, split `test`, 222 items. Settings: fusion rrf, linear_w None. Index fingerprint `150af34ab34d41a83f6fe552a8313c6a514f26b1567cb6205e3e633f21c6becc`. Metrics version 2. No model calls. Wall-clock 180.7 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 180 | 0.654 [0.582, 0.723] | 0.502 [0.438, 0.564] | 0.465 [0.399, 0.530] | 0.654 [0.582, 0.723] | 3729.3 [3694.0, 3763.0] | 0.118 |
| rarity head | 113 | 0.608 [0.520, 0.697] | 0.450 [0.375, 0.527] | 0.416 [0.338, 0.497] | 0.608 [0.520, 0.697] | 3691.8 [3647.3, 3735.4] | 0.118 |
| rarity tail | 67 | 0.731 [0.627, 0.836] | 0.590 [0.485, 0.689] | 0.546 [0.436, 0.651] | 0.731 [0.627, 0.836] | 3792.5 [3741.9, 3839.4] | – |
| qtype count_filter | 27 | 0.322 [0.166, 0.489] | 0.146 [0.067, 0.241] | 0.161 [0.057, 0.291] | 0.322 [0.166, 0.489] | 3455.3 [3388.8, 3522.3] | 0.118 |
| qtype factoid | 40 | 0.750 [0.600, 0.875] | 0.611 [0.480, 0.741] | 0.569 [0.430, 0.707] | 0.750 [0.600, 0.875] | 3774.3 [3705.5, 3835.9] | – |
| qtype id_lookup | 39 | 0.769 [0.641, 0.897] | 0.614 [0.484, 0.741] | 0.565 [0.429, 0.703] | 0.769 [0.641, 0.897] | 3782.9 [3715.8, 3846.2] | – |
| qtype overview | 35 | 0.629 [0.457, 0.771] | 0.447 [0.313, 0.584] | 0.390 [0.254, 0.532] | 0.629 [0.457, 0.771] | 3758.7 [3681.5, 3826.9] | – |
| qtype procedure | 39 | 0.692 [0.538, 0.821] | 0.573 [0.438, 0.708] | 0.534 [0.395, 0.673] | 0.692 [0.538, 0.821] | 3792.9 [3728.6, 3851.1] | – |

Chunks 7305; span containment 1.000.
