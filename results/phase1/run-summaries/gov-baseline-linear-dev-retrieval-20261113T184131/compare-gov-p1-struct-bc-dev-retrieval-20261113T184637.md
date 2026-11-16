# Retrieval comparison: p1-struct-bc minus baseline-linear

Run `gov-p1-struct-bc-dev-retrieval-20261113T184637` minus run `gov-baseline-linear-dev-retrieval-20261113T184131` on `gov` / `dev`, paired over 43 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 43 | 0.735 | 0.734 | -0.001 | [-0.020, 0.021] | 0.874 | 1.000 |
| ndcg@10 | 43 | 0.710 | 0.719 | 0.009 | [-0.026, 0.048] | 0.667 | 1.000 |
| mrr | 43 | 0.734 | 0.741 | 0.007 | [-0.038, 0.057] | 0.797 | 1.000 |
| coverage@10 | 43 | 0.735 | 0.674 | -0.062 | [-0.114, -0.015] | 0.006 | 0.022 |
