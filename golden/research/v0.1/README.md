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

## Frozen data

The item files are frozen data. They are not regenerated when scoring rules change. The
generator's evidence-only check uses the harness's exact scorer, so regenerating with later
code (for example the whole-identifier rule of metrics version 2) can admit a different set;
that set would be a new version, not v0.1. `adr-eval golden research --gen` refuses to write
over an existing `items.jsonl` unless `--overwrite` is given.

## Regenerate

The research corpus needs the local PDF library (`scripts/download_papers.py`, then
`git checkout papers/manifest.csv`, because the script rewrites that pinned file).

```
adr-eval fetch research
adr-eval golden research --gen --generator claude_code_sonnet --judge claude_code_opus --max-calls 1500
adr-eval golden research --verify
```

Add `--overwrite` to `--gen` when the item files already exist. With the same cache and the
code that generated them (metrics version 1, up to commit `4063a0e`) the output is
byte-identical; later code may admit a different set (see "Frozen data"). From a cold
cache, model replies may differ (Claude Code does not pin temperature), so compare the
per-type counts above, not the hashes.
