# bench: EnterpriseRAG-Bench subset

Open enterprise RAG benchmark by Onyx (DanswerAI, Inc.): about 512,000 synthetic internal
documents of a fictional company ("Redwood Inference") from nine source systems, with 500
questions. The first-choice benchmark was adopted; no substitute was needed.

## Findings (checked 2026-11-08)

- **Repository:** https://github.com/onyx-dot-app/EnterpriseRAG-Bench. Its `LICENSE` is the
  MIT License, "Copyright (c) 2026 DanswerAI, Inc." (read from raw.githubusercontent.com).
- **Dataset:** https://huggingface.co/datasets/onyx-dot-app/EnterpriseRAG-Bench, card licence
  `mit`, not gated. Pinned revision `69916e31c68aa5963c00248fd7f0bc12d04fd235`.
- **Format:** two parquet files.
  - `data/documents/test.parquet`: 1,409,893,131 bytes, one row group, 511,962 rows.
    Columns are `doc_id`, `source_type`, `title` and `content` (markdown-like text).
    Four `doc_id`s appear twice (8 rows); one of them is a gold document.
  - `data/questions/test.parquet` holds 500 questions with `question_id`, `question_type`,
    `source_types`, `question`, `expected_doc_ids`, `gold_answer` and `answer_facts`. It is
    identical to `questions.jsonl` in the GitHub repository.
- **Access from this sandbox:** github.com is refused (HTTP 403), so the release zips cannot
  be downloaded. raw.githubusercontent.com and huggingface.co work, and the parquet is
  served with HTTP Range support. The Hugging Face datasets-server cannot convert the
  `documents` config, so there is no row-level API. That is why the whole documents file is
  downloaded once (resumably) into `data/bench/_source/`. Both files are pinned by SHA-256
  in `config.json`.
- **Canary:** the upstream README asks that benchmark data never appear in training corpora.
  Documents and questions are therefore never committed; only hashes and URIs are.

## Subset (config.json)

- The subset keeps every row whose `doc_id` is in `expected_doc_ids` of a kept question:
  722 gold ids, 723 rows.
- It then fills up to `max_docs` = 2,000 with `random.Random(20261108).sample` over the
  remaining rows, taken in row order. The fill is uniform, so the source-type mix follows
  the full corpus (Slack-heavy).
- Each row is rendered to `data/bench/docs/{row:06d}_{doc_id}.md` as
  `# {title}\n\nSource: {source_type}\n\n{content}\n`.
- A document's URI is `<documents url>#row=<n>&doc_id=<id>`; `BenchAdapter.fetcher()`
  rebuilds the file from the cached parquet. `source_version` is the dataset revision.

## Native questions and qtype mapping

`bench.native_items()` returns 490 questions: the source fields, plus `qtype` and
`manifest_doc_ids` (our doc_ids for `expected_doc_ids`). Task 8 converts them with
`provenance.model = "native"`.

| Benchmark `question_type` | Count | Our `qtype` |
|---|---|---|
| basic | 175 | factoid |
| semantic | 125 | factoid |
| constrained | 30 | factoid |
| conflicting_info | 20 | factoid |
| miscellaneous | 20 | factoid |
| intra_document_reasoning | 40 | overview |
| project_related | 40 | overview |
| completeness | 20 | overview |
| info_not_found | 20 | insufficient |
| high_level | 10 | excluded: no gold documents, and the answer spans the full corpus, not the subset |

Notes:

- Answers stay valid on the subset because every gold document is kept.
- `info_not_found` answers are absent from the full corpus, so they are absent from the
  subset too.
- Near-duplicate distractors that are not gold documents are mostly left out. That makes
  `conflicting_info` and `constrained` easier than on the full corpus.

## Rebuild

```
python -m adr_eval.corpora.registry build bench   # downloads ~1.4 GB once, writes manifest.json
python -m adr_eval.corpora.registry fetch bench   # recreates data/bench/docs from the manifest
```
