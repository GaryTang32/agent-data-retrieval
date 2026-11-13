# Comparison: gov-p1-struct-bc-test-20261113T202800 minus gov-baseline-linear-test-20261113T094503

Paired over 242 shared items (repeat 0); paired bootstrap 95% CIs; Holm-adjusted p across the metrics below.

| metric | n | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|
| penalised@0.75 | 242 | -0.021 | [-0.165, 0.120] | 0.810 | 1.000 |
| ndcg@10 | 213 | 0.012 | [-0.015, 0.039] | 0.385 | 1.000 |
| recall@10 | 213 | 0.031 | [0.006, 0.058] | 0.011 | 0.056 |
| coverage@10 | 213 | -0.025 | [-0.056, 0.007] | 0.118 | 0.474 |

McNemar exact on correct vs not: only A correct 13, only B correct 8, p = 0.3833 (Holm 1.0000).
