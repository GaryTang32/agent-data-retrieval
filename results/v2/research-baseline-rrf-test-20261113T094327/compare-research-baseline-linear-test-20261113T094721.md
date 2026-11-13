# Comparison: research-baseline-linear-test-20261113T094721 minus research-baseline-rrf-test-20261113T094327

Paired over 222 shared items (repeat 0); paired bootstrap 95% CIs; Holm-adjusted p across the metrics below.

| metric | n | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|
| penalised@0.75 | 222 | 0.162 | [0.014, 0.315] | 0.037 | 0.037 |
| ndcg@10 | 180 | 0.208 | [0.157, 0.260] | < 0.0002 | < 0.0010 |
| recall@10 | 180 | 0.203 | [0.140, 0.266] | < 0.0002 | < 0.0010 |
| coverage@10 | 180 | 0.203 | [0.140, 0.266] | < 0.0002 | < 0.0010 |

McNemar exact on correct vs not: only A correct 4, only B correct 25, p = 0.0001 (Holm 0.0002).
