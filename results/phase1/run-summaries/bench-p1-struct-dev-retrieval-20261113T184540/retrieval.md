# Retrieval: bench-p1-struct-dev-retrieval-20261113T184540

Corpus `bench`, system `p1-struct`, split `dev`, 156 items. Settings: fusion linear, linear_w 0.65, w_bc 0, prefix False, rerank False. Index fingerprint `5882fe1ba4424d7ef63db666cf21c89dcc9a0004a01d6622bd5f5aa54111aa88`. Metrics version 2. No model calls. Wall-clock 59.9 s.

Values in brackets are 95% CIs (percentile bootstrap of the mean over items, 10,000 resamples); none where n < 2. `insufficient` items carry no metrics.

| stratum | n | Recall@10 | nDCG@10 | MRR | coverage@10 | tokens@10 | full coverage |
|---|---|---|---|---|---|---|---|
| pooled | 141 | 0.971 [0.944, 0.993] | 0.884 [0.844, 0.920] | 0.872 [0.824, 0.917] | 0.770 [0.720, 0.818] | 2974.0 [2884.9, 3058.9] | 0.765 |
| rarity head | 16 | 1.000 [1.000, 1.000] | 0.887 [0.780, 0.977] | 0.849 [0.708, 0.969] | 0.952 [0.855, 1.000] | 2764.1 [2454.6, 3036.4] | – |
| rarity none | 103 | 0.980 [0.957, 0.998] | 0.895 [0.853, 0.934] | 0.890 [0.838, 0.936] | 0.725 [0.671, 0.778] | 3068.1 [2969.9, 3159.1] | 0.765 |
| rarity tail | 22 | 0.909 [0.773, 1.000] | 0.831 [0.679, 0.955] | 0.808 [0.645, 0.955] | 0.852 [0.702, 0.977] | 2686.3 [2466.0, 2882.0] | – |
| qtype factoid | 93 | 1.000 [1.000, 1.000] | 0.908 [0.865, 0.946] | 0.883 [0.826, 0.933] | 0.747 [0.692, 0.802] | 3092.3 [3003.7, 3175.1] | 1.000 |
| qtype id_lookup | 9 | 1.000 [1.000, 1.000] | 0.959 [0.877, 1.000] | 0.944 [0.833, 1.000] | 1.000 [1.000, 1.000] | 2908.9 [2386.1, 3313.7] | – |
| qtype overview | 30 | 0.865 [0.750, 0.963] | 0.810 [0.696, 0.910] | 0.854 [0.738, 0.954] | 0.746 [0.616, 0.864] | 2746.9 [2527.4, 2957.7] | 0.556 |
| qtype procedure | 9 | 1.000 [1.000, 1.000] | 0.807 [0.614, 1.000] | 0.747 [0.495, 1.000] | 0.859 [0.662, 1.000] | 2573.6 [2195.2, 2881.1] | – |

Chunks 7400; span containment 0.178.
