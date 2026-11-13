# Comparison: gov-baseline-linear-test-20261112T012529 minus gov-baseline-rrf-test-20261112T012113

Paired over 242 shared items (repeat 0); paired bootstrap 95% CIs; Holm-adjusted p across the metrics below.

| metric | n | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|
| penalised@0.75 | 242 | -0.045 | [-0.182, 0.087] | 0.511 | 0.511 |
| ndcg@10 | 213 | 0.084 | [0.049, 0.120] | < 0.0002 | < 0.0008 |
| recall@10 | 213 | 0.092 | [0.052, 0.134] | < 0.0002 | < 0.0008 |

McNemar exact on correct vs not: only A correct 10, only B correct 17, p = 0.2478 (Holm 0.4956).
