# Retrieval comparison: p1-struct-bc-rr minus baseline-linear

Run `gov-p1-struct-bc-rr-test-retrieval-20261113T185744` minus run `gov-baseline-linear-test-retrieval-20261113T184207` on `gov` / `test`, paired over 213 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 213 | 0.771 | 0.780 | 0.009 | [-0.030, 0.049] | 0.645 | 0.645 |
| ndcg@10 | 213 | 0.691 | 0.643 | -0.048 | [-0.090, -0.004] | 0.033 | 0.094 |
| mrr | 213 | 0.671 | 0.609 | -0.062 | [-0.114, -0.011] | 0.017 | 0.070 |
| coverage@10 | 213 | 0.771 | 0.724 | -0.047 | [-0.090, -0.004] | 0.031 | 0.094 |
