# Retrieval comparison: p1-struct minus baseline-linear

Run `bench-p1-struct-dev-retrieval-20261113T184540` minus run `bench-baseline-linear-dev-retrieval-20261113T184131` on `bench` / `dev`, paired over 141 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 141 | 0.970 | 0.971 | 0.001 | [-0.020, 0.021] | 0.868 | 1.000 |
| ndcg@10 | 141 | 0.881 | 0.884 | 0.003 | [-0.021, 0.024] | 0.775 | 1.000 |
| mrr | 141 | 0.865 | 0.872 | 0.007 | [-0.020, 0.034] | 0.618 | 1.000 |
| coverage@10 | 141 | 0.811 | 0.770 | -0.040 | [-0.072, -0.013] | 0.002 | 0.009 |
