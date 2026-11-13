# gov golden set v0.1

Questions over the pinned `gov` corpus (eCFR parts at dated versions, Internal Revenue
Manual chapters, Federal Register metadata; see `corpora/gov/README.md`). The items are
committed: the sources are US government works in the public domain.

| File | Contents |
|---|---|
| `items.jsonl` | 297 accepted items |
| `rejected.jsonl` | 53 rejected items, each with the check it failed in `reject_reason` |
| `review_exclusions.json` | items removed after human review: item id -> one-line reason |

## How it was generated

Model-drafted and code-checked; no item is human-vetted.

- Generator profile `claude_code_sonnet` (served model `claude-sonnet-5-5`) drafts
  questions from sampled sections, record filters and version pairs; code locates every
  quote, computes count and list answers from the records and assigns splits and rarity.
- Judge profile `claude_code_opus` decides paraphrased text answers in the evidence-only
  check.
- Every model reply is cached in `.cache/llm` (not committed). With that cache and the
  code that generated them (metrics version 1, up to commit `4063a0e`),
  `adr-eval golden gov --gen --overwrite` reproduces these files byte for byte
  (`--max-calls 0` proves that no call reaches a model); later code may admit a different
  set (see "Frozen data"). From a cold cache the models may draft different
  questions (Claude Code does not pin temperature), so compare the counts below.
- The last step applies `review_exclusions.json`: listed items move to `rejected.jsonl`
  with `reject_reason: "review_excluded"`; every other item is unchanged.

The first version of this set had 302 items. Regenerating it from the cache (every call a
cache hit) after the review moved the 9 excluded items to `rejected.jsonl` and also
accepted 4 `factoid` items (gov-factoid-022, -029, -034, -044) that had failed the
evidence-only check: their answers are numbers with unit variants ("400 feet"), which the
exact scorer only matches since it honours `accepted_variants` for number answers. The
other 293 accepted items are byte-identical to the first version.

```
adr-eval fetch gov
adr-eval golden gov --gen --overwrite --generator claude_code_sonnet --judge claude_code_opus --max-calls 2000
adr-eval golden gov --verify
```

The gov corpus is fetched from live government sites, and four IRM pages are pinned by
exact bytes. If irs.gov changes those pages, `fetch gov` fails and this set cannot be
checked by others (the corpus bytes are not committed).

## Frozen data

The item files are frozen data. They are not regenerated when scoring rules change. The
generator's evidence-only check uses the harness's exact scorer, so regenerating with later
code (for example the whole-identifier rule of metrics version 2) can admit a different set;
that set would be a new version, not v0.1. `adr-eval golden gov --gen` refuses to write over
an existing `items.jsonl` unless `--overwrite` is given.

## Counts

| qtype | accepted |
|---|---|
| count_filter | 38 |
| factoid | 47 |
| id_lookup | 39 |
| insufficient | 41 |
| overview | 44 |
| policy_asof | 40 (20 pairs) |
| procedure | 48 |

Split: dev 55, test 242. Tail share among rated items: 0.40 (103 of 256).

Rejected: 18 `evidence_only`, 10 `dedup`, 9 `review_excluded`, 7 `gold_query_exec`,
5 `pair_rejected`, 4 `evidence_only_output`.

## Review exclusions

The final review found these `insufficient` questions answerable from the corpus, so their
gold answer (abstain) would be wrong:

| Item | Reason |
|---|---|
| gov-insufficient-002 | answerable: the LA 657 Larose bridge is in 33 CFR 117.465 |
| gov-insufficient-011 | answerable: Class C to Class C co-channel separation is in the 47 CFR 73 table |
| gov-insufficient-026 | answerable: Class B1 HAAT is in the 47 CFR 73 table |
| gov-insufficient-038 | answerable: horsepower table in 33 CFR 165.811(e) |
| gov-insufficient-044 | answerable: approach distance for an escorted HCPV is in 33 CFR 165 |
| gov-insufficient-006, -016, -025, -050 | partly answerable from the corpus |

## Known weak spots

- `insufficient`: the generator checks only that one key term is absent from the corpus.
  The review hand-checked only about 20 of the original 50 and excluded the 9 above; others
  may still be answerable.
- In the first version, 134 of the 149 eCFR-sourced items had identical evidence text in
  another dated version of the same part. Retrieval scored against the gold document may count the same passage
  retrieved from another version as a miss.
- 5 of the 20 `policy_asof` pairs ask about typography (formatting changes between
  versions) rather than a change in the rule.
- `overview` questions often refer to "this section" without naming it, which makes them
  hard to answer from a search over the whole corpus.
