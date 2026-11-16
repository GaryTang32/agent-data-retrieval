# Retrieval comparison: p1-struct-bc-rr minus baseline-linear

Run `research-p1-struct-bc-rr-dev-retrieval-20261113T191107` minus run `research-baseline-linear-dev-retrieval-20261113T184131` on `research` / `dev`, paired over 45 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 45 | 0.846 | 0.760 | -0.087 | [-0.210, 0.035] | 0.166 | 0.497 |
| ndcg@10 | 45 | 0.697 | 0.634 | -0.064 | [-0.168, 0.037] | 0.222 | 0.497 |
| mrr | 45 | 0.662 | 0.596 | -0.066 | [-0.175, 0.040] | 0.224 | 0.497 |
| coverage@10 | 45 | 0.846 | 0.674 | -0.172 | [-0.290, -0.061] | 0.002 | 0.009 |
