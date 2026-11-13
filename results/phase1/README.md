# Phase 1 results: evidence store

> **Work in progress.** These are the measured numbers for Phase 1 of the roadmap (the evidence
> store), recorded on 13 November 2026 under version 2 of the metric definitions. They compare
> Phase 1 retrieval with the Phase 0 baseline; they are not a claim about later phases.

**Verdict.** The evidence store works as specified:
- every document round-trips losslessly;
- every leaf element carries a character span;
- a 1% edit re-embeds at most 0.6% of chunks;
- 100 PDFs are searchable in 8.4 minutes;
- retrieval is identical from run to run.

As a retriever it does **not** meet the acceptance rule of the design (§10.5):
- The best Phase 1 system, `p1-struct-bc`, retrieves significantly better on gov (Recall@10 +0.031), but that gain is fragile.
- It is level on research and bench.
- No accuracy difference is significant on any corpus.

The baseline (`baseline-linear`) stays the reference. The reranker is switched off, because it
loses to the same system without it on every corpus.

Design: [`docs/superpowers/specs/2026-11-13-phase1-evidence-store-design.md`](../../docs/superpowers/specs/2026-11-13-phase1-evidence-store-design.md).
Plan: [`docs/superpowers/plans/2026-11-13-phase1-evidence-store.md`](../../docs/superpowers/plans/2026-11-13-phase1-evidence-store.md).
Phase 0 baseline: [`results/README.md`](../README.md).

## What was run

- **Systems.** Each adds one component to the one before it:

  | System | Chunks | Lexical | Dense | Reranker |
  |---|---|---|---|---|
  | `baseline-linear` | fixed 400 tokens | BM25 | body | no |
  | `p1-struct` | structure-led (≤400 tokens, headings travel with their body) | BM25 | body | no |
  | `p1-struct-bc` | structure-led | BM25 with the breadcrumb repeated `w_bc` times | breadcrumb + newline + body | no |
  | `p1-struct-bc-rr` | structure-led | as above | as above | `ms-marco-MiniLM-L-6-v2` over the top 50 |

- **Retrieval only**, with no model calls:
  - all five systems (the four above and `baseline-rrf`);
  - the dev and test splits of all three corpora, with `adr-eval retrieval`;
  - fusion weights `w` (BM25 share) and `w_bc` tuned on dev nDCG@10, then fixed for test.
- **End to end** (answers and judge, test split, one repeat), `p1-struct-bc` only:
  - It was chosen as the best Phase 1 system on dev. It is best on gov and bench and on the mean of the three corpora. On research dev, `p1-struct` is slightly higher.
  - It is paired with the recorded `baseline-linear` runs of [`results/v2/`](../v2/).
  - Generator `claude-sonnet-5-5`, judge `claude-opus-5-5`, through Claude Code on a subscription ($0 recorded).
  - 1,036 rows, 0 errors.
- **Golden sets:** v0.1, unchanged. **Metric definitions:** version 2.
- **Stores** (parser version 3): gov snapshot `f002821f2cb3…`, research `97c415b1aa71…`, bench
  `7d8d1f8adda6…`.

| Corpus | Test items scored | Baseline chunks | Phase 1 chunks | Tuned `w` (baseline / p1-struct / p1-struct-bc) | Tuned `w_bc` |
|---|---|---|---|---|---|
| gov | 213 | 5,056 | 6,783 | 0.85 / 0.95 / 1.00 | 2 |
| research | 180 | 7,305 | 9,554 | 1.00 / 0.75 / 0.90 | 3 |
| bench | 517 | 5,587 | 7,400 | 0.70 / 0.65 / 0.70 | 1 |

`w = 1.00` means the tuned system uses BM25 alone. So on gov, `p1-struct-bc` uses no dense search at all.

## Retrieval (test split)

Bold marks the best value per corpus and column.

| Corpus | System | Recall@10 | nDCG@10 | MRR | Coverage@10 | Tokens@10 |
|---|---|---|---|---|---|---|
| gov | `baseline-rrf` | 0.706 | 0.614 | 0.591 | 0.706 | 3,543 |
| gov | `baseline-linear` | 0.771 | 0.691 | 0.671 | **0.771** | 3,534 |
| gov | `p1-struct` | 0.765 | 0.686 | 0.666 | 0.715 | 3,128 |
| gov | `p1-struct-bc` | **0.802** | **0.703** | **0.677** | 0.746 | 3,171 |
| gov | `p1-struct-bc-rr` | 0.780 | 0.643 | 0.609 | 0.724 | 3,091 |
| research | `baseline-rrf` | 0.654 | 0.502 | 0.465 | 0.654 | 3,729 |
| research | `baseline-linear` | **0.856** | 0.710 | 0.676 | **0.856** | 3,752 |
| research | `p1-struct` | 0.848 | 0.692 | 0.652 | 0.765 | 3,150 |
| research | `p1-struct-bc` | 0.844 | **0.710** | **0.677** | 0.764 | 3,182 |
| research | `p1-struct-bc-rr` | 0.715 | 0.576 | 0.545 | 0.649 | 3,141 |
| bench | `baseline-rrf` | 0.859 | 0.766 | 0.756 | 0.698 | 3,343 |
| bench | `baseline-linear` | **0.922** | **0.854** | 0.849 | **0.782** | 3,352 |
| bench | `p1-struct` | 0.915 | 0.843 | 0.839 | 0.739 | 2,917 |
| bench | `p1-struct-bc` | 0.919 | 0.853 | **0.856** | 0.780 | 2,911 |
| bench | `p1-struct-bc-rr` | 0.901 | 0.825 | 0.830 | 0.747 | 2,965 |

On research, the nDCG@10 of `p1-struct-bc` (0.7103) and of the baseline (0.7098) round to the same value.

Tokens@10 is the mean number of tokens in the top 10 chunks. Phase 1 chunks are smaller, so its
top 10 is 10–16% shorter than the baseline's.

### Paired difference from `baseline-linear` (test split)

Phase 1 minus baseline, paired over items, with a 95% paired bootstrap interval. P-values are
Holm-adjusted across the four retrieval metrics of one corpus and system
(`adr-eval retrieval-compare`). **Bold** marks Holm p < 0.05.

| Corpus | System | Recall@10 | nDCG@10 | Coverage@10 | MRR |
|---|---|---|---|---|---|
| gov | `p1-struct` | −0.006 [−0.039, +0.026] | −0.005 [−0.037, +0.025] | **−0.057** (p 0.009) | −0.005 |
| gov | `p1-struct-bc` | **+0.031** [+0.006, +0.058] (p 0.045) | +0.012 [−0.015, +0.039] | −0.025 | +0.006 |
| gov | `p1-struct-bc-rr` | +0.009 | −0.048 [−0.090, −0.004] (p 0.094) | −0.047 | −0.062 |
| research | `p1-struct` | −0.009 [−0.042, +0.025] | −0.017 [−0.049, +0.013] | **−0.091** (p < 0.001) | −0.024 |
| research | `p1-struct-bc` | −0.013 [−0.045, +0.017] | +0.000 [−0.027, +0.028] | **−0.093** (p < 0.001) | +0.001 |
| research | `p1-struct-bc-rr` | **−0.141** | **−0.133** | **−0.208** | **−0.131** |
| bench | `p1-struct` | −0.007 [−0.019, +0.004] | −0.011 [−0.020, −0.002] (p 0.055) | **−0.043** (p < 0.001) | −0.010 |
| bench | `p1-struct-bc` | −0.003 [−0.016, +0.009] | −0.001 [−0.012, +0.009] | −0.002 | +0.007 |
| bench | `p1-struct-bc-rr` | −0.021 | **−0.029** (p 0.029) | **−0.035** (p 0.013) | −0.019 |

**The one significant gain is fragile.** The gov Recall@10 gain of `p1-struct-bc` (+0.031) is
significant only within that one comparison:
- No correction is made across the nine corpus–system pairs.
- Corrected across the five measures of the end-to-end comparison, its Holm p is 0.056.
- Part of it comes from dropping the dense channel (`w = 1.00`), not from breadcrumbs. The baseline with BM25 alone already reaches Recall@10 0.780 and nDCG@10 0.700 on gov test ([`results/README.md`](../README.md)). Against that, `p1-struct-bc` gains +0.022 [−0.001, +0.047] Recall@10 and +0.003 nDCG@10, neither significant.
- Against `p1-struct`, the breadcrumb field adds +0.037 Recall@10 on gov.

### Split by question type

Phase 0 drew the golden evidence of overview and procedure questions as exactly one baseline
chunk. On gov and research it therefore fits inside one baseline chunk every time. It fits inside
one Phase 1 chunk only 34% of the time on gov and 18% on research (all splits; 37% and 18% on
test). Fact evidence fits inside one chunk 99% of the time for both chunkers. This favours the
baseline on coverage@10 for those questions.

The table shows Phase 1 minus baseline on the test split. Intervals are 95% paired bootstrap
intervals (10,000 resamples), not adjusted for multiple comparisons:

| Corpus | System | Questions | n | Recall@10 | nDCG@10 | Coverage@10 |
|---|---|---|---|---|---|---|
| gov | `p1-struct-bc` | overview, procedure | 79 | +0.013 [−0.025, +0.063] | +0.006 [−0.042, +0.053] | −0.138 [−0.196, −0.085] |
| gov | `p1-struct-bc` | all other | 134 | +0.042 [+0.012, +0.077] | +0.016 [−0.017, +0.051] | +0.042 [+0.012, +0.077] |
| research | `p1-struct` | all other | 106 | −0.034 [−0.071, −0.005] | −0.042 [−0.077, −0.008] | −0.034 [−0.071, −0.005] |
| research | `p1-struct-bc` | overview, procedure | 74 | +0.014 [−0.041, +0.068] | +0.042 [−0.006, +0.091] | −0.181 [−0.253, −0.112] |
| research | `p1-struct-bc` | all other | 106 | −0.031 [−0.068, −0.003] | −0.029 [−0.060, +0.002] | −0.031 [−0.068, −0.003] |
| bench | `p1-struct-bc` | overview, procedure | 158 | −0.007 [−0.038, +0.025] | −0.008 [−0.031, +0.015] | −0.047 [−0.085, −0.009] |
| bench | `p1-struct-bc` | all other | 359 | −0.001 [−0.014, +0.011] | +0.001 [−0.010, +0.013] | +0.018 [+0.002, +0.035] |

The coverage@10 losses are mostly this evidence bias. On the other questions:
- **gov:** gains on Recall@10 and coverage@10.
- **bench:** level.
- **research:** structure-led chunks lose about 0.03 to 0.04 on all three measures. That holds both with breadcrumbs (two of three intervals exclude zero) and without (all three do). This is a weakness of the Phase 1 chunks on research, most likely the heuristic section boundaries in PDFs.

## End to end (test split, one repeat)

| Corpus | System | n | Accuracy | Abstained | Penalised t=0.75 |
|---|---|---|---|---|---|
| gov | `baseline-linear` | 242 | 0.752 [0.698, 0.806] | 0.045 | 0.145 [−0.062, 0.339] |
| gov | `p1-struct-bc` | 242 | 0.731 [0.674, 0.785] | 0.066 | 0.124 [−0.079, 0.318] |
| research | `baseline-linear` | 222 | 0.806 [0.752, 0.856] | 0.041 | 0.347 [0.153, 0.532] |
| research | `p1-struct-bc` | 222 | 0.779 [0.721, 0.833] | 0.054 | 0.279 [0.077, 0.468] |
| bench | `baseline-linear` | 572 | 0.801 [0.767, 0.834] | 0.056 | 0.371 [0.255, 0.484] |
| bench | `p1-struct-bc` | 572 | 0.813 [0.780, 0.844] | 0.049 | 0.399 [0.283, 0.510] |

| Corpus | Only the baseline correct | Only Phase 1 correct | McNemar p (Holm) | Penalised t=0.75 difference |
|---|---|---|---|---|
| gov | 13 | 8 | 0.38 (1.00) | −0.021 [−0.165, +0.120] |
| research | 15 | 9 | 0.31 (1.00) | −0.068 [−0.234, +0.099] |
| bench | 18 | 25 | 0.36 (1.00) | +0.028 [−0.059, +0.114] |

No accuracy difference is significant. Point accuracy is lower on gov (−0.021) and research
(−0.027) and higher on bench (+0.012). On gov the better recall did not turn into better answers.

## Acceptance (design §10.5)

The rule is checked on the test split:
- nDCG@10 and Recall@10 are not lower than `baseline-linear` on any corpus;
- both are significantly higher (paired bootstrap, Holm-corrected) on at least one corpus;
- retrieval identity is intact.

| Check | `p1-struct-bc` |
|---|---|
| Not lower on any corpus | Fails if "not lower" means the point estimate: research Recall@10 −0.013, bench −0.003 and −0.001. Passes if it means "not significantly lower" |
| Both significantly higher on at least one corpus | Fails: gov Recall@10 +0.031 (Holm p 0.045), but gov nDCG@10 +0.012 is not significant, and nothing is significant elsewhere |
| Retrieval identity | Holds, in two checks below |

Retrieval identity was checked two ways:
- **End to end vs retrieval only:** for all 1,036 test questions, the end-to-end runs of `p1-struct-bc` and `baseline-linear` retrieved exactly the rankings and scores of the retrieval-only runs.
- **Rebuilt indexes:** for `p1-struct` and `p1-struct-bc`, the rebuilt indexes gave the same dev rankings and scores as the first build for all 264 dev questions (528 rankings). The index fingerprint changed in between, because its definition was extended to cover chunk content.

**Result: not accepted** under either reading of "not lower", because the second check fails.
`baseline-linear` stays the reference.

No component delivered a gain on both metrics:

| Component | Effect | Decision |
|---|---|---|
| Structure-led chunks (`p1-struct`) | Level with the baseline on Recall@10 and nDCG@10 overall. Lower coverage@10, mostly from the evidence bias. About 0.03–0.04 lower on research questions other than overview and procedure. 10–16% fewer tokens in the top 10 | Kept in the store, which needs them for spans, breadcrumbs and cheap re-indexing. Not the retrieval reference |
| Breadcrumb field and prefix (`p1-struct-bc`) | Recovers what structure-led chunks lost. On gov, +0.037 Recall@10 over `p1-struct` and +0.031 over the baseline (fragile, above). Level on research and bench | Kept as the best Phase 1 system. Not the reference |
| Reranker (`p1-struct-bc-rr`) | Worse than `p1-struct-bc` on dev on every corpus: nDCG@10 −0.064 on gov, −0.135 on research, −0.081 on bench. Lower nDCG@10 than the baseline on test on all three corpora | **Failed; switched off** (design §8). Probably because a cross-encoder trained on web search queries does not suit these corpora; it also loses on bench. Only one reranker was tried |

## Compile track (design §10.3)

| Corpus | Documents | Conformance | Re-parse equals stored | Leaves with a span | PDF leaves with a page | Documents with a section | Headings aligned |
|---|---|---|---|---|---|---|---|
| gov | 180 | 100% | 100% | 100% | – | 7.2% (167 are one-record JSON files) | 89.1% (XML 100%, HTML 12 of 485) |
| research | 245 | 100% | 100% | 100% | 100% | 99.2% | 100% |
| bench | 2,000 | 100% | 100% | 100% | – | 100% | 100% |

Heading alignment is meaningful only for XML and HTML. There, headings are read from the markup
and then placed in the canonical text. For Markdown and PDF they are found in the canonical text
itself, so 100% holds by construction. The four Internal Revenue Manual HTML pages align only 12
of 485 headings, because text extraction drops their body headings. They have almost no sections.

Golden evidence inside one chunk (Phase 0 definition, all splits):

| Corpus | Baseline: fact / overview+procedure | Phase 1: fact / overview+procedure |
|---|---|---|
| gov | 99.2% / 100% | 99.2% / 33.7% |
| research | 100% / 100% | 99.7% / 18.1% |
| bench | 18.4% / 22.2% | 18.4% / 17.2% |

Bench evidence is mostly whole documents longer than one chunk, so neither chunker contains it.

## Exit criteria of the roadmap

| Criterion | Result | Status |
|---|---|---|
| Lossless round trip on a mixed corpus of at least 1,000 documents | 2,425 documents (gov, research, bench); conformance rule 1 passes on all | **Met** |
| At least 95% of born-digital elements carry page, bounding box and character span | Character span on 100% of leaves; page on 100% of PDF leaves; no bounding boxes | Partly met; boxes need a layout parser |
| A 1% edit re-embeds at most 2% of chunks | gov 0.03%, research 0.08%, bench 0.55% (both chunk variants); an unedited corpus needs 0 new embeddings | **Met** |
| Install to 100 queryable PDFs in under ten minutes | 8.4 minutes on an idle 4-core machine, with embedding on all cores (`--threads 0`): ingest 92 s, index 411 s (3,477 chunks embedded), first search 3 s | **Met** (with all cores) |
| Routed parse within two points of the best backend | Needs layout models | Deferred |
| Approximate search recall against exact search | Exact search is used | Not applicable |

How the edit test was run:
- **Documents:** 1% of each corpus, every 100th by sorted id: gov 2, research 3, bench 20.
- **Edit:** each got a new paragraph of about 65 words near the middle of its text. It went at a blank-line boundary where one lay in the middle half, otherwise at a line end. That was the case for all gov and research documents and 7 of the 20 bench documents.
- **Count:** the documents were re-parsed and re-chunked, and their embedded texts counted against the embedding cache.
- **Baseline chunker on the same edits:** about as many new texts on gov and bench (2 and 42, against Phase 1's 2 and 41), but 38 against 8 on research.
- **Largest research PDF alone:** an edit re-embeds 7 of its 96 Phase 1 chunks, against 43 of 84 baseline chunks.

How the install was timed:
- **PDFs:** the first 100 PDFs of the research corpus's sample, sorted by path (233 MB).
- **Commands:** `adr ingest --path <folder> --store <new store>`, then `adr index <store> --system p1-struct-bc --w-bc 3 --weight 0.9 --threads 0` with a new, empty embedding cache (`--emb-cache`), then one `adr search`. The weights are research's dev-tuned values.
- **Model download:** the embedding model was already downloaded, and downloading it is not counted.
- **Where the time goes:** embedding is most of it; the index step is 411 of 506 seconds.
- **Threads:** with 2 or 4 threads, the vectors are bit-identical to single-threaded ones (600 texts, several batch layouts). Here, the index built with all cores and an earlier single-threaded build of the same 100 PDFs have byte-identical vectors.
- **Single-threaded:** that earlier build, on a loaded machine and with a stand-in script for the ingest step, took 26.0 minutes.

## Limits

- **One repeat end to end:** answer agreement across repeats is not measured.
- **Small dev splits** (43, 45 and 141 items), so the tuned weights are noisy. They are fixed before the test split is read.
- **Golden-evidence bias:** the golden evidence of overview and procedure questions favours the baseline chunker (above).
- **One model each:** one embedding model (the baseline's) and one reranker were tried.
- **Same model family:** the judge and generator come from the same family.
- **One machine:** the install timing is for one 4-core machine.

## Files

`run-summaries/` holds the configuration and summary of each run:
- **Retrieval-only runs:** `retrieval.md`, and `retrieval.json` without per-item rows.
- **End-to-end runs:** `report.md`, `report.json` and `compile.json`.
- **The paired comparisons.**

Per-item rows stay local, as in Phase 0.
