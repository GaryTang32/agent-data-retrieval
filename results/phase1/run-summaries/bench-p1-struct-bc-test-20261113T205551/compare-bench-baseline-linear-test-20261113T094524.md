# Comparison: bench-p1-struct-bc-test-20261113T205551 minus bench-baseline-linear-test-20261113T094524

Paired over 572 shared items (repeat 0); paired bootstrap 95% CIs; Holm-adjusted p across the metrics below.

| metric | n | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|
| penalised@0.75 | 572 | 0.028 | [-0.059, 0.114] | 0.522 | 1.000 |
| ndcg@10 | 517 | -0.001 | [-0.012, 0.009] | 0.764 | 1.000 |
| recall@10 | 517 | -0.003 | [-0.016, 0.009] | 0.621 | 1.000 |
| coverage@10 | 517 | -0.002 | [-0.018, 0.015] | 0.833 | 1.000 |

McNemar exact on correct vs not: only A correct 18, only B correct 25, p = 0.3604 (Holm 1.0000).
