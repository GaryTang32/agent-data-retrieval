# gov-tables golden set v0.1

Questions over the drawbridge facts of 33 CFR part 117 in the pinned `gov` corpus: counts and
lists across sections, filters with one or two constraints, and lookups of one draw's value
(Phase 3 spec §10.3). The items are committed: the sources are US government works in the
public domain.

| File | Contents |
|---|---|
| `items.jsonl` | 120 accepted items |
| `rejected.jsonl` | 197 rejected draws, each with its query and the reason in `reason` |

Every item names the store's content snapshot (`f002821f2cb3…`) and the facts it was drawn
from (`541f4c587ee9a271068604a4a12fbe5584cc74392ff431f29e7683b45916707b`).

## How it was made (ruling P9)

The gold comes from the second extraction pass, the questions are phrased by a model, and the
answers are computed by code. No item is checked by a person.

- **Facts.** The facts are the second, independent extraction pass, never the table under test.
  That pass ran `adr tables extract --second-pass` with profile `claude_code_opus`, asking
  numbered questions with quotes, one call per distinct section text (533). Each value's quote
  is re-sliced from the section text by code, and a value whose quote is not found is dropped
  (null `ungrounded`). The facts are kept to the version in force, using the default
  applicability filters.
- **Questions.** Code draws one or two clauses from a sampled fact row of `drawbridge_sections`
  or `drawbridge_bridges`. A clause is an equality, a numeric bound or range, a list
  `__contains`, or `__isnull`. Code also picks the op: `count`, `list`, or `lookup` of a numeric
  or yes/no field that the clauses do not name. The gold query is a `query_table` argument object
  (`table`, `filters`, `op`, `field`). The model, profile `claude_code_sonnet`, only words the
  question: one cached call per item, prompt `tables_question@1`, with no evidence-only check
  call.
- **Answers.** Code runs the gold query over the fact rows of the version in force:
  - a count is a number;
  - a list is the sorted unique section numbers;
  - a numeric lookup is a number;
  - a yes/no lookup is `yes` or `no`, with `true` or `false` accepted as variants.
- **Evidence.** Each item's evidence is the quotes of the drawn columns in the matched rows, 723
  spans in all. A row with no such quote gives its section heading instead. Every span is
  re-sliced from the document text.
- **Split.** Splits come from the existing `assign_split(id)`, which puts 20% in dev.

Every model reply is cached in `.cache/llm`, which is not committed. With that cache, this
command reproduces both files byte for byte (checked on 2026-11-20: 0 calls made, 120 cached):

```
adr-eval golden tables --gen --overwrite --store .cache/store-p2/gov \
    --facts 541f4c587ee9a271068604a4a12fbe5584cc74392ff431f29e7683b45916707b \
    --generator claude_code_sonnet --max-calls 0
```

The original run used `--max-calls 140`. It made 117 calls, and 3 replies were already cached
from a 3-call check run, so 120 of the 140 calls in the command's share were used. No reply was
malformed, so nothing was redrawn. From a cold cache the model may word the questions
differently, because Claude Code does not pin temperature. The queries and answers come from
code and the facts, so they do not change.

## Counts

| Split | count | list | lookup | Total |
|---|---|---|---|---|
| test | 43 | 46 | 8 | 97 |
| dev | 10 | 11 | 2 | 23 |
| **all** | **53** | **57** | **10** | **120** |

- **By table:** `drawbridge_bridges` 82 (31 count, 41 list, 10 lookup), `drawbridge_sections` 38
  (22 count, 16 list).
- **Clauses:** 47 items have one clause and 73 have two.
- **Columns in clauses:** `state` 50, `waterway` 44, `mile` 21, `notice_hours` 21,
  `opens_on_signal` 16, `closed_periods` 12, `bridge` 11, `owner_or_agency` 8, `seasonal` 7,
  `vhf_channel` 5.
- **Lookup fields:** `mile` 5, `opens_on_signal` 3, `notice_hours` 2.
- **Answer kinds:** number 60, set 57, yes/no 3.

**Draws.** Code made 752 draws, and every draw was accepted or rejected by code with no call:

| Outcome | Draws |
|---|---|
| accepted | 120 |
| repeat of an earlier draw | 170 |
| unusable (a clause on a null value, two clauses on one column, a lookup with no field left) | 265 |
| rejected, kept in `rejected.jsonl` | 197 |

Rejected draws by reason:

| Reason | Draws |
|---|---|
| lookup matches more than one row | 82 |
| count over 50 | 59 |
| list over 25 | 56 |

## Limits

These are stated up front (spec §10.3).

- **The gold comes from a model, not a person.** The facts are one model's reading of each
  section, checked only to the extent that every quote is re-sliced by code.
- **A shared error is invisible.** The table under test comes from the first pass, run with a
  different model and a structurally different prompt. Where both passes read a section the
  same wrong way, the item's gold and the table agree, and the error is not seen.
- **Regex cross-check as an independent check on the gold.** Where a regular expression can find
  the value, the gold facts agree with it as follows. The counts are over the facts' grounded
  values, one per distinct section text:

  | Column | Agree | Disagree | Regex finds nothing |
  |---|---|---|---|
  | `mile` | 1,186 (98.6% of 1,203 checked) | 17 | 7 |
  | `notice_hours` | 283 (72.0% of 393 checked) | 110 | 322 |
  | `vhf_channel` | 37 (100% of 37 checked) | 0 | 1 |

  The other columns (`waterway`, `bridge`, `seasonal`, `owner_or_agency`, `opens_on_signal`,
  `closed_periods`) have no regex. The `notice_hours` disagreements were not analysed one by
  one. The regex only finds forms like "24 hours notice", so it is a weak check for this
  column. The first pass agrees with it at about the same rate (278 of 394).
- **The two passes disagree on many items.** The merge gate ran every item's gold query on the
  table under test. The table gave the gold answer on 88 of 120, so on 32 the two passes
  disagree about a value the query reads. Which pass is right was not checked. A miss on this
  set therefore means "the table disagrees with the second pass", not "the table is wrong".
- **Version in force only.** Answers are computed over the version in force. No question asks
  about an older version.
- **Yes/no values (ruling P22).** A yes/no fact is non-null only when a quote states it, and
  `false` follows the same rule. A question about sections that are, for example, not seasonal
  counts only the sections whose text says so.
