# Retrieval comparison: p1-struct-bc minus baseline-linear

Run `gov-p1-struct-bc-test-retrieval-20261113T184730` minus run `gov-baseline-linear-test-retrieval-20261113T184207` on `gov` / `test`, paired over 213 shared items; paired bootstrap 95% CIs; Holm-adjusted p across the four metrics. Metrics version 2.

| metric | n | A | B | mean diff | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
| recall@10 | 213 | 0.771 | 0.802 | 0.031 | [0.006, 0.058] | 0.011 | 0.045 |
| ndcg@10 | 213 | 0.691 | 0.703 | 0.012 | [-0.015, 0.039] | 0.385 | 0.771 |
| mrr | 213 | 0.671 | 0.677 | 0.006 | [-0.029, 0.040] | 0.731 | 0.771 |
| coverage@10 | 213 | 0.771 | 0.746 | -0.025 | [-0.056, 0.007] | 0.118 | 0.355 |
