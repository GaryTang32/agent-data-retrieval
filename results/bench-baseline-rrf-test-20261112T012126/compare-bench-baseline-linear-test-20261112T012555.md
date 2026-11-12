# Comparison: bench-baseline-linear-test-20261112T012555 minus bench-baseline-rrf-test-20261112T012126

Paired over 572 shared items (repeat 0); paired bootstrap 95% CIs; Holm-adjusted p across the metrics below.

| metric | n | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|
| penalised@0.75 | 571 | 0.173 | [0.088, 0.263] | < 0.0002 | < 0.0008 |
| ndcg@10 | 517 | 0.071 | [0.053, 0.089] | < 0.0002 | < 0.0008 |
| recall@10 | 517 | 0.062 | [0.040, 0.087] | < 0.0002 | < 0.0008 |

McNemar exact on correct vs not: only A correct 12, only B correct 58, p = 0.0000 (Holm 0.0000).
