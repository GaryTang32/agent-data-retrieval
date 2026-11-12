# research: the repository's research corpus

| Source | Format | `source_version` | Licence |
|---|---|---|---|
| `reports/*.md` | md | `sha256:` + first 12 hex of doc_id | Apache-2.0 |
| `research_notes/**/*.md` | md | `sha256:` + first 12 hex of doc_id | Apache-2.0 |
| `papers/manifest.csv` | csv (one document) | `sha256:` + first 12 hex of doc_id | Apache-2.0 |
| 200 sampled PDFs under `papers/` | pdf | `sha256:` + first 12 hex of doc_id | the row's `license` column |

- `source_version` comes from the bytes alone, not from git, so the manifest does not depend
  on clone depth, history or uncommitted edits.

- Every `path` is repo-relative and every URI is `file://<path>`.
- The HTML brief in `reports/` is not included; the brief names only `*.md`.

## PDF sample

- Eligible PDFs are rows of `papers/manifest.csv` with `status == "downloaded"` whose
  `local_file` exists on disk. Eligible files are sorted by path.
- Then `random.Random(20261108).sample(eligible, 200)` picks the sample.
- PDFs are local only and never committed (their licences often forbid redistribution). The
  manifest pins their hashes. Other users rebuild them with `scripts/download_papers.py`.
- Warning: `scripts/download_papers.py` also rewrites the tracked `papers/manifest.csv`,
  which is itself a pinned document of this corpus. Rerunning it changes the research
  snapshot (and invalidates the research golden set). Restore the file afterwards with
  `git checkout papers/manifest.csv`.
- Without the PDFs, `adr-eval fetch research` (and `index`, `run`, `golden`) stop with a list
  of the missing files. The research golden set is local only for the same reason (see
  `golden/research/v0.1/README.md`).
- Building the manifest fails if fewer than 200 are present, and the research tests skip.

## Records

- `records()` returns one row per CSV row (2,570) with every catalog column, plus:
  - `id`: `arxiv_id`, else `doi`, else `url:` + the first 16 hex digits of the URL's SHA-256
  - `year`: int, or None when blank
  - `_doc_id`
  - `_span`: the row's line in the extracted CSV text
- One `url:` id repeats, because the same web source is catalogued twice.
- `version_pairs()` returns `[]`.

## Rebuild

```
python -m adr_eval.corpora.registry build research
```
