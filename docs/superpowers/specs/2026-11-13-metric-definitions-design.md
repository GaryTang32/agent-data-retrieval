# Metric Definitions v2 — Design

Date: 2026-11-13
Status: decisions taken with the user on 2026-11-12/13; opening step of Phase 1.
Source: the final review of Phase 0 (`results/README.md`, "Known artefacts in the metrics") and
the experiments summarised in section 8.

## 1. Purpose

Phase 0 recorded a baseline, and its final review found four places where the harness's own
scoring rules distort the numbers. Later phases are accepted only if they beat the baseline, so
the rules have to be settled before anything is measured against them. This design changes four
definitions, stamps every run with a metrics version, and records the baseline again.

Success means: each definition has a written rule and tests; the six baseline runs are recorded
again under version 2; `results/` shows every number that moved and why.

Out of scope: golden set v0.2, hardening the reply parser, the evidence store, and any change to
prompts or retrieval.

## 2. Decisions

| # | Topic | Decision |
|---|---|---|
| 1 | Identical text in several documents | Any identical copy of the evidence counts, except for questions with an as-of date |
| 2 | Evidence longer than a chunk | nDCG@10 gives full credit to any chunk that touches the evidence; coverage@10 is reported separately |
| 3 | Identifier answers | Correct if the answer contains the gold identifier as a whole identifier |
| 4 | Query-understanding scores | Three scores: route, record match, entities with partial credit |
| 5 | Rollout | Change in place, stamp a metrics version, record the baseline again from saved model calls |

## 3. Evidence groups (decision 1)

### 3.1 Definition

For a golden item whose `as_of` is null, each evidence span gets **copies**:

1. Take the span's text plus up to 200 characters before and after it in its own document
   (`CONTEXT_CHARS = 200`; fewer where the document starts or ends).
2. A copy exists in another document when that whole passage occurs there, comparing after
   whitespace normalisation (the `normalize_ws` rule used by `check_spans`).
3. The copy's span is the location of the evidence text inside that occurrence, as character
   offsets in the other document's extracted text. If the passage occurs more than once in the
   other document, every occurrence is a copy.

An **evidence group** is the original span plus its copies, original first, copies ordered by
`(doc_id, char_start)`. Items with an `as_of` date have groups of one: only the dated copy is
right.

### 3.2 Where it is computed

`src/adr_eval/scoring/evidence_groups.py`:

- `CONTEXT_CHARS = 200`
- `def build_groups(item: GoldenItem, docs: dict[str, Document]) -> list[list[Evidence]]`
- `def build_all(items: list[GoldenItem], docs: dict[str, Document]) -> dict[str, list[list[Evidence]]]`
  keyed by item id.

The runner calls `build_all` once after loading the corpus and the golden set. Nothing is written
to the golden files. `compile.json` gains `evidence_copies: {"spans": n, "spans_with_copies": n,
"copies": n}` over the run's items.

### 3.3 How metrics use groups

All retrieval and citation metrics take `groups: list[list[Evidence]]` instead of
`evidence: list[Evidence]`. A chunk **touches** a group if it overlaps any member (same document,
character ranges intersect). Each group is credited at most once.

Known gap, accepted: a passage whose neighbouring text was amended between versions has no
copies under the context rule (5 of 138 gov spans that recur).

## 4. Retrieval metrics (decision 2)

For a ranked list of chunks (top 10) and the item's groups:

| Metric | Definition |
|---|---|
| Recall@10 | Share of groups touched by at least one of the top 10 chunks |
| MRR | 1 / rank of the first chunk that touches any group; 0 if none |
| nDCG@10 | Walk the ranking; a chunk that touches a not-yet-credited group earns gain 1 and credits the first such group (group order); DCG = Σ gain / log2(rank + 1); ideal = Σ over the first min(10, #groups) ranks of 1 / log2(rank + 1). Duplicate chunk ids are skipped |
| Full coverage | Recall@10 == 1 |
| Coverage@10 | For each group: the largest value, over its members, of (characters of the member inside the union of the top 10 chunks) / (member length). Mean over groups |
| Tokens@10 | Total tokens of the top 10 chunks, counted with the harness tokenizer without dropping stop words |
| Citation precision | Share of cited chunks that touch any group; none if nothing is cited |
| Evidence cited | True if any cited chunk touches any group |

The proportional-gain nDCG of version 1 is removed. Each result row's `metrics` object gains
`coverage@10` and `tokens@10`. Reports show coverage@10 with a bootstrap interval and mean
tokens@10 next to it, pooled and per stratum, and the comparison table adds coverage@10.

## 5. Identifier answers (decision 3)

For gold answers of kind `id`, a prediction is correct when either holds:

1. (unchanged) its normalised form equals the normalised gold value or an accepted variant;
2. (new) the normalised gold value occurs in the prediction as a **whole identifier**.

Whole-identifier match, on NFKC-lowercased, whitespace-collapsed text; `g` is
`normalize_value(gold)` and must be non-empty. An occurrence of `g` qualifies when:

- the character before it is not a letter or digit, and is not `.` or `-` directly preceded by a
  letter or digit; and
- the character after it is not a letter or digit, and is not `.` or `-` directly followed by a
  letter or digit.

So `3.8` matches "Section 3.8 (Experimental Volume)" but not "13.8", "3.8.1" or "3.85".
Because `normalize_value` strips punctuation at both ends of the gold value, a sub-paragraph
also passes ("(b)(4)(i)" for `(b)(4)`, "73.1740(a)" for `73.1740`), and a gold value that
normalises to one letter would match ordinary words. No golden v0.1 item is affected (the
shortest identifier golds are `11` and `14`); golden v0.2 must not admit such values.
Accepted variants are not used for containment. List-valued predictions are unchanged (wrong for
kind `id`). The rule lives in `scoring/exact.py` (`contains_identifier`) and is used wherever
`exact_outcome` is.

## 6. Query-understanding scores (decision 4)

Per result row, from the generated query and the gold query:

**Route.** `route(q)`:

- store `typed_db`: `"records:" + op`
- any other store: `"prose:fact"` for op `lookup` or `explain`; `"prose:procedure"` for
  `procedure`; `"abstain"` for `abstain`; otherwise `"prose:" + op`

A row's route is right when `route(generated) == route(gold)`; a missing generated query is
wrong. Rows whose gold op is `abstain` are left out, because that cannot be known before
retrieval.

**Record match.** Unchanged: for gold queries on `typed_db`, whether executing the generated
query returns the same result as the gold query.

**Entities.** Only for rows whose gold query lists at least one entity and whose gold op is not
`abstain`. Each entity is reduced to its set of lowercase alphanumeric words. Two entities match
when one's set contains the other's and both are non-empty. Precision is the share of generated
entities that match some gold entity, recall the share of gold entities matched by some generated
entity, and the score is their F1 (0 when nothing is generated).

Rows gain `route_ok` (true, false or null when left out) and `entity_f1` (number or null).
The report's `g2` block gains `route_accuracy` with `route_n`, `entity_f1` with `entity_n`, and
keeps `exec_match`, `exec_n` and `per_field`. The markdown shows the three scores; the per-field
table and whole-query match stay in `report.json` as diagnostics only.

## 7. Versioning, golden sets, results

- `METRICS_VERSION = 2` in `src/adr_eval/scoring/__init__.py`. The runner writes it to
  `config.json` and the report copies it to `report.json` and prints it. A run without the field
  is version 1.
- `adr-eval report --compare` refuses two runs whose metrics versions differ, with exit code 2
  and a message naming both.
- **Golden v0.1 is frozen.** The item files are data: they are not regenerated for this change.
  Generating with the new identifier rule would admit different items, which is golden v0.2 and
  separate work. `adr-eval golden <corpus> --gen` refuses to write over an existing `items.jsonl`
  unless `--overwrite` is given; the golden READMEs say the files are frozen.
- The six baseline runs are recorded again with one repeat from the saved model calls. No
  prompt changes, so no new generator calls are expected.
- The current `results/<run>` folders and the current `results/README.md` move to `results/v1/`.
  The new runs go to `results/v2/`. A new `results/README.md` gives the version 2 tables and a
  table of every headline number under version 1 and version 2 with the cause of each change.

## 8. Evidence behind the decisions

Run on the pinned corpora and the recorded runs, without model calls.

- **Copies.** Evidence text recurs in another document for 138 of 178 undated gov spans, 5 of
  190 on research and 0 of 930 on bench. The 5 research matches are coincidences (a section
  heading, citation strings, a URL). With 200 characters of context required: 133, 0 and 0.
- **A perfect ranking.** Under version 1 it scores 0.30, 0.43, 0.65, 0.85 and 0.98 on bench at
  chunk sizes of 100, 200, 400, 800 and 1600 tokens, and 0.67 to 1.00 on gov. Under the new
  nDCG it scores 1.00 everywhere.
- **Same retriever, different chunk sizes** (BM25, the 367 bench questions that cite whole
  documents). A chunking-independent reference, "was the right document ranked early", stays
  between 0.83 and 0.88. Version 1 moves from 0.10 to 0.86; dividing by the attainable score
  from 0.67 to 0.88; the new nDCG from 0.82 to 0.88, within 0.01 of the reference at every size.
- **Predicting a correct answer** (AUC on the recorded bench runs, RRF and linear): version 1
  0.84 and 0.82, new nDCG 0.82 and 0.81, with overlapping intervals; coverage@10 0.89 and 0.85.
- **Coverage@10 depends on chunk size** (0.31 to 0.94 across the sizes), which is why tokens@10
  is reported with it.
- **Identifiers.** Of 161 identifier answers, the judge calls 158 correct. Version 1 agrees on
  91.9% (13 wrongly marked wrong, none wrongly marked correct); the whole-identifier rule agrees
  on all 161. Checked against the gold identifier of a different question, it matches 1 of 1,832
  pairs.
- **Query understanding.** The largest causes of version 1 misses are conventions: gold `lookup`
  against generated `explain` for facts in prose (97, 42 and 310 rows on gov, research and
  bench), `abstain` gold for questions that are not answerable (29, 42, 55), and empty gold
  entity lists (367 bench rows). With those removed and the route rule of section 6, route accuracy is 0.84, 0.66 and 0.87.

Limits: the chunk-size tests used BM25 only; the answer-prediction and disagreement tests rest
on bench, the only corpus where the nDCG variants differ today; the identifier test has only
three wrong answers; nothing uses the generated query yet, so the query scores cannot be tied to
answer quality.

## 9. Testing

- Evidence groups: a copy with matching context is found; a quote-only coincidence is not; an
  item with `as_of` gets no copies; several occurrences in one document; offsets re-slice to the
  evidence text.
- Retrieval metrics: a perfect ranking scores nDCG 1.0 when the evidence spans several chunks;
  retrieving a copy earns the same as the original and is credited once; coverage@10 on a span
  split across three chunks with one, two and three retrieved; tokens@10.
- Identifier rule: the 13 recorded cases as fixtures (gov and research text only), plus the
  boundary cases in section 5 and a list-valued prediction.
- Query scores: the route table, abstain rows left out, entity F1 cases including empty lists.
- Versioning: `config.json` and `report.json` carry the version; a report for a run without the
  field still builds and says version 1; `--compare` across versions exits 2.
- `golden --gen` refuses to overwrite without `--overwrite`.
