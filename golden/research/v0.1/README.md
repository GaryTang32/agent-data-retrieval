# research golden set v0.1 (items not committed)

The item files are kept local. Their evidence quotes include verbatim excerpts from the
research PDFs, whose licences often forbid redistribution (the PDFs themselves are local
only; see `corpora/research/README.md`). This file pins what the local files contain so a
regenerated set can be checked against it.

| File | Items | SHA-256 |
|---|---|---|
| `items.jsonl` | 275 | `fdebe3f0b207df3278c6d44b2aba1060fd7fab5beec7dae22c2d978df6dd5dd4` |
| `rejected.jsonl` | 25 | `52275655a561491982ef1518f77ce79f469790ed0cb7b6cc333c54a211695602` |

| qtype | accepted |
|---|---|
| count_filter | 35 |
| factoid | 49 |
| id_lookup | 47 |
| insufficient | 50 |
| overview | 46 |
| procedure | 48 |

The corpus has no dated versions, so there are no `policy_asof` items. Rejected: 23
`evidence_only`, 1 `evidence_only_output`, 1 `dedup`.

Split: dev 53, test 222. Tail share among rated items: 0.36 (82 of 225).

## Regenerate

The research corpus needs the local PDF library (`scripts/download_papers.py`, then
`git checkout papers/manifest.csv`, because the script rewrites that pinned file).

```
adr-eval fetch research
adr-eval golden research --gen --generator claude_code_sonnet --judge claude_code_opus --max-calls 1500
adr-eval golden research --verify
```

With the same cache the output is byte-identical; from a cold cache, model replies may
differ (Claude Code does not pin temperature), so compare the per-type counts above, not
the hashes.
