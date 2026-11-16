# Retrieval comparison: p1-struct minus baseline-linear

Run `gov-p1-struct-dev-retrieval-20261113T184437` minus run `gov-baseline-linear-dev-retrieval-20261113T184131` on `gov` / `dev`, paired over 43 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 43 | 0.735 | 0.737 | 0.001 | [-0.009, 0.014] | 0.925 | 1.000 |
| ndcg@10 | 43 | 0.710 | 0.708 | -0.002 | [-0.039, 0.037] | 0.915 | 1.000 |
| mrr | 43 | 0.734 | 0.727 | -0.007 | [-0.055, 0.046] | 0.789 | 1.000 |
| coverage@10 | 43 | 0.735 | 0.681 | -0.054 | [-0.110, -0.010] | 0.006 | 0.022 |
