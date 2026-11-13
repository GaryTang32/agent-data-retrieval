# Metric Definitions v2 — Implementation Plan

Spec: `docs/superpowers/specs/2026-11-13-metric-definitions-design.md`. Read it first; the
section numbers below refer to it. Work test-first. `pytest -q -W error` and `ruff check .` must
pass after every task. No model calls in any task except the re-record in Task 3. Do not
regenerate or edit golden item files.

## Task 1: Evidence groups and retrieval metrics

**Files:** create `src/adr_eval/scoring/evidence_groups.py`; modify
`src/adr_eval/scoring/retrieval_metrics.py`, `src/adr_eval/scoring/compile_metrics.py`,
`src/adr_eval/scoring/__init__.py`, `src/adr_eval/pipeline.py`, `src/adr_eval/runner.py`,
`src/adr_eval/report.py`; tests in `tests/test_evidence_groups.py`,
`tests/test_retrieval_metrics.py` (or the existing metrics test file), `tests/test_runner.py`.

- `METRICS_VERSION = 2` in `scoring/__init__.py`; the runner writes `metrics_version` to
  `config.json`; the report copies it to `report.json` and prints it; a run without the field is
  reported as version 1 (spec §7).
- `evidence_groups.build_groups` / `build_all` (spec §3.1, §3.2). Reuse `normalize_ws` and
  `find_quote`-style matching from `golden/verify.py`; offsets must re-slice to the evidence
  text in the other document.
- Every function in `retrieval_metrics.py` takes `groups: list[list[Evidence]]` and follows the
  table in spec §4. Add `coverage_at_k` and `tokens_at_k`.
- `pipeline.retrieval_scores` and the citation scores use the item's groups; rows gain
  `coverage@10` and `tokens@10` in `metrics`. The runner builds the groups once and passes them
  through the context. `compile.json` gains `evidence_copies` (spec §3.2).
- `report.py`: G3 blocks gain `coverage@10` (with interval) and mean `tokens@10`, pooled and per
  stratum; the markdown tables show them; `compare()` adds `coverage@10`; `--compare` refuses
  runs with different metrics versions (exit code 2, message names both versions).
- Tests: spec §9, first, second and fifth bullets. Include a perfect ranking over evidence that
  spans several chunks (nDCG 1.0) and a copy credited once.

## Task 2: Identifier rule, query-understanding scores, golden overwrite guard

**Files:** modify `src/adr_eval/scoring/exact.py`, `src/adr_eval/pipeline.py`,
`src/adr_eval/report.py`, `src/adr_eval/cli.py`, `golden/*/v0.1/README.md`; tests in the
existing exact-scorer, pipeline, report and CLI test files.

- `exact.contains_identifier(pred, gold)` and its use for kind `id` (spec §5).
- `pipeline`: `route()`, `route_ok`, `entity_f1` per row (spec §6).
- `report.py`: `g2` gains `route_accuracy`, `route_n`, `entity_f1`, `entity_n`; markdown shows
  route accuracy, record match and entity F1; `per_field` and whole-query match stay in JSON.
- `cli.py`: `golden --gen` refuses to overwrite an existing `items.jsonl` unless `--overwrite`
  (exit code 2, message says the set is frozen). The three golden READMEs gain one sentence: the
  item files are frozen data and are not regenerated when scoring rules change.
- Tests: spec §9, third, fourth and sixth bullets. Use these recorded identifier cases as
  fixtures (gold → answer, all must score correct): `73.1740` → `47 CFR § 73.1740`;
  `IRM 21.10.1` → `IRM 21.10.1, Embedded Quality (EQ) for Accounts Management`;
  `(b)(4)` → `Paragraph (b)(4) of § 73.3598`; `CGD 13-98-004` →
  `CGD 13-98-004, 64 FR 72561, Dec. 28, 1999`; `3.8` → `Section 3.8 (Experimental Volume)`;
  `2508.06600` → `arXiv 2508.06600`. And these must stay wrong: `4.2` → `Section 4.4, titled
  "Evaluation Metrics"`; `3.8` → `13.8`; `3.8` → `3.8.1`; `3.8` → `3.85`; `11` → `Table 110`.

## Task 3: Record the baseline again and write the results

- Move the six `results/<run>` folders and `results/README.md` to `results/v1/`.
- Run both systems on the test split of gov, research and bench with one repeat, from the saved
  model calls. Generate reports and comparisons. Copy them (not `results.jsonl`) to
  `results/v2/`.
- Write `results/README.md`: the version 2 tables, a version 1 → version 2 table of every
  headline number with the cause of each change, the findings re-checked against the new
  numbers, and the limits. Update the README status table and the status page.

## Review

Each task gets an independent review against the spec before the next starts. After Task 3 a
reviewer checks every number in `results/README.md` against the report files.
