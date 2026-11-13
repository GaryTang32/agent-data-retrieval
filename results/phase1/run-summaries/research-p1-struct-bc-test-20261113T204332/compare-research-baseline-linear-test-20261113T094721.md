# Comparison: research-p1-struct-bc-test-20261113T204332 minus research-baseline-linear-test-20261113T094721

Paired over 222 shared items (repeat 0); paired bootstrap 95% CIs; Holm-adjusted p across the metrics below.

| metric | n | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|
| penalised@0.75 | 222 | -0.068 | [-0.234, 0.099] | 0.428 | 1.000 |
| ndcg@10 | 180 | 0.000 | [-0.027, 0.028] | 0.960 | 1.000 |
| recall@10 | 180 | -0.013 | [-0.045, 0.017] | 0.390 | 1.000 |
| coverage@10 | 180 | -0.093 | [-0.131, -0.058] | < 0.0002 | < 0.0010 |

McNemar exact on correct vs not: only A correct 15, only B correct 9, p = 0.3075 (Holm 1.0000).
