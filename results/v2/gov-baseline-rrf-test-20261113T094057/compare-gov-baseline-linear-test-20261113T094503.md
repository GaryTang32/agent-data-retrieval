# Comparison: gov-baseline-linear-test-20261113T094503 minus gov-baseline-rrf-test-20261113T094057

Paired over 242 shared items (repeat 0); paired bootstrap 95% CIs; Holm-adjusted p across the metrics below.

| metric | n | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|
| penalised@0.75 | 242 | -0.017 | [-0.149, 0.107] | 0.810 | 0.810 |
| ndcg@10 | 213 | 0.077 | [0.045, 0.110] | < 0.0002 | < 0.0010 |
| recall@10 | 213 | 0.065 | [0.027, 0.103] | 0.001 | 0.002 |
| coverage@10 | 213 | 0.065 | [0.027, 0.103] | 0.001 | 0.002 |

McNemar exact on correct vs not: only A correct 8, only B correct 16, p = 0.1516 (Holm 0.3032).
