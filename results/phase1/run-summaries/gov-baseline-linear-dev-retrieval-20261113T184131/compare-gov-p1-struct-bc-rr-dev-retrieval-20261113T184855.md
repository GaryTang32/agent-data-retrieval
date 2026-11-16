# Retrieval comparison: p1-struct-bc-rr minus baseline-linear

Run `gov-p1-struct-bc-rr-dev-retrieval-20261113T184855` minus run `gov-baseline-linear-dev-retrieval-20261113T184131` on `gov` / `dev`, paired over 43 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 43 | 0.735 | 0.720 | -0.015 | [-0.072, 0.024] | 0.662 | 0.662 |
| ndcg@10 | 43 | 0.710 | 0.655 | -0.055 | [-0.134, 0.016] | 0.136 | 0.273 |
| mrr | 43 | 0.734 | 0.647 | -0.087 | [-0.182, 0.001] | 0.052 | 0.157 |
| coverage@10 | 43 | 0.735 | 0.650 | -0.086 | [-0.168, -0.017] | 0.010 | 0.041 |
