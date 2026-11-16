# Retrieval comparison: p1-struct minus baseline-linear

Run `gov-p1-struct-test-retrieval-20261113T184534` minus run `gov-baseline-linear-test-retrieval-20261113T184207` on `gov` / `test`, paired over 213 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 213 | 0.771 | 0.765 | -0.006 | [-0.039, 0.026] | 0.718 | 1.000 |
| ndcg@10 | 213 | 0.691 | 0.686 | -0.005 | [-0.037, 0.025] | 0.748 | 1.000 |
| mrr | 213 | 0.671 | 0.666 | -0.005 | [-0.042, 0.030] | 0.744 | 1.000 |
| coverage@10 | 213 | 0.771 | 0.715 | -0.057 | [-0.092, -0.022] | 0.002 | 0.009 |
