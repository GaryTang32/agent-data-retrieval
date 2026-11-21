# Phase 3: The Typed Deterministic Database — Design

Date: 2026-11-20
Status: written by the assistant from the user's decisions (section 1). Every other choice is
listed in section 14 as a ruling made without the user, with what it costs if it is wrong.
Nothing here is built yet. The model-call budget in section 11 needs the user's approval before
any call is made; part 3A makes no model calls and can be built first.
Sources: `reports/Agent data retrieval research summary.md` (the Phase 3 row of the roadmap, the
Store 2 paragraph, the access tiers T1/T2 and "What goes where"); the Phase 0–2 designs and code
(`docs/superpowers/specs/`, `src/adr_eval/`, `src/adr_store/`); `results/README.md`,
`results/phase2/README.md`; `golden/*/v0.1/`. The numbers in sections 4 and 6 come from a
read-only survey of the corpora and the Phase 2 stores, run on 2026-11-20; the survey scripts are
scratch files and are not committed.

## 1. Purpose

Phase 3 adds the second store of the roadmap: typed tables that agents query with exact
predicates instead of reading passages. It serves G1 (compile documents into typed data
products) and G3 (deterministic retrieval), and it closes the baseline's largest gap: a flat
retriever cannot count. On the gov test split, count and filter questions score 0 of 27 with RRF
and 2 of 27 with linear fusion (`results/README.md`, "Accuracy by question type").

It has two parts, built and measured in this order:

| Part | What it adds | Model calls |
|---|---|---|
| 3A Metadata tables | Typed tables loaded deterministically from the structured fields the corpora already carry (Federal Register metadata, the research papers manifest), entity tables with alias maps, a semantic layer, a parameterized query tool and guarded read-only SQL, all under the Phase 2 ACL, applicability filters and handles | None |
| 3B Grounded extraction | A typed table extracted by a model, once, from the text of one document family (33 CFR part 117, drawbridge operation regulations), where every value carries a verbatim quote that code re-slices from the stored text; cached so rebuilds make no calls | Within the budget of §11, after the user approves it |

The user's decisions (2026-11-20):

- **Both parts.** Load the metadata first with no model calls; then extract from one document
  family with a fixed, cached budget of model calls, estimated for approval before anything runs.
- **Dive in.** The assistant makes the remaining design choices and records them (§14).
- Standing constraints from earlier phases still hold: synthetic tenants (Phase 2), no spending
  beyond what the user approves, benchmark data and per-item rows never committed.

## 2. Scope

In scope: parts 3A and 3B, their harness support, their tests, a new golden set for the 3B
table (§10.3), and a write-up in `results/phase3/`.

Out of scope:

| Item | Why |
|---|---|
| Extraction from more than one text family | User decision: one family. The machinery is general; others follow if this one earns it |
| Human review of extracted values | No reviewer is available. Values get an automatic status (§7.4); the review step of the roadmap's QA ladder is left as a status value nobody sets |
| Conformal risk control, NLI checks | The roadmap's QA ladder names them. Phase 3 keeps the cheaper rungs (validators, span re-slice, regex cross-check, an independent second extraction) and reports agreement rates; the statistical rungs wait for a reviewed sample |
| Iceberg or DuckLake snapshots, external catalogs | Phase 6 (exporters). Tables are write-once overlay files here (§5.2) |
| LinkML as a dependency | The contracts are JSON files with a small validator (§5.1). LinkML can generate them later; the format maps one to one |
| Free text-to-SQL as the main interface | The roadmap's "defaults to avoid". SQL is the second tier, behind the parameterized tool (§8) |
| Graph tables, relation extraction between entities | Phase 5 |
| A new version of golden set v0.1 | v0.1 stays frozen; one known wording problem is reported, not fixed (§10.2) |
| Row-level ACLs | Access stays per document (Phase 2). A row inherits the access of the document it came from (§9) |

## 3. Constraints

1. **The canonical text, the Phase 1 records and the Phase 2 overlays do not change.** Tables
   are new write-once overlay files beside them, each naming the content snapshot it describes.
   No snapshot id, doc record, chunk id, index fingerprint or overlay id changes.
2. **Phases 1 and 2 stay reproducible.** Their systems, tools, commands and saved runs work
   unchanged; the five existing tools return identical results.
3. **Determinism.** Building a table from the same snapshot, contracts and cache gives
   byte-identical files. Queries sort with a total order. No wall-clock input except the Phase 2
   ACL freshness check, which only denies.
4. **Zero-call rebuilds.** After the one extraction run, rebuilding every table makes no model
   call (`--max-calls 0` proves it) and reproduces the same checksums.
5. **Model calls only inside the approved budget (§11)** and only for the purposes listed there.
   Part 3A, every probe, and every rebuild make none.
6. **Grounding is checked by code.** A value is stored as grounded only if its quote occurs
   verbatim in the stored text at the recorded character offsets.

## 4. What the corpora hold (survey, 2026-11-20)

### 4.1 Structured metadata

| Corpus | Source | Records | Fields |
|---|---|---|---|
| gov | Federal Register document JSON, one store document each (`data/gov/fr/*.json`) | 167 (120 Rule, 47 Proposed Rule) | `document_number`, `type`, `title`, `action`, `abstract`, `dates` (free text), `publication_date` (2020-01-03 to 2026-05-15), `effective_on` (56 null), `html_url`; lists `agencies` (DHS + Coast Guard 111, FCC 56), `cfr_references` (40 distinct title/part pairs; 1 to 20 per document), `docket_ids` (1 to 4) |
| research | `papers/manifest.csv`, one store document | 2,570 rows, 16 columns | `research`, `topic`, `also_in` (`;`-joined, 2,269 empty), `type`, `title`, `authors`, `year` (19 empty), `venue` (1,098 distinct), `url`, `pdf_url`, `arxiv_id`, `doi`, `license`, `status`, `local_file`, `relevance` |
| bench | markdown headers | 2,000 | `source_type`, `title` only; no count questions |
| tools | ToolRet catalog | 14,059 | already `ToolRecord`s (Phase 2) |

Messy values that entity resolution must handle (examples, not a complete list): CFR `part` as an
integer once; docket strings in several forms and several dockets in one string ("MB Docket Nos.
19-311, 13-249"); agency names in raw upper case and canonical form; venues "arXiv preprint",
"arXiv", "arXiv preprint (2026)", "arXiv 2026"; licences "CC-BY-4.0" and "CC BY 4.0"; authors as
one comma string with "et al." and stray punctuation; one duplicated paper id.

The FR document's canonical text is its JSON re-serialised with sorted keys and indent 2
(`src/adr_eval/corpora/extract.py`), so field provenance is located in that text, as the Phase 2
applicability deriver already does for `dates`. A manifest row's provenance is its line in the
CSV document.

### 4.2 The frozen count questions

Golden set v0.1 has 38 gov and 35 research `count_filter` items (gov test 27, research test 27),
all with `gold_query.store = "typed_db"` and op `count` or `list`. They were generated by code
from `adapter.records()` and executed by `golden/records.py`, a 75-line in-memory filter with
operators eq, `__in`, `__gte`, `__lte` and `__contains`. Fields used: gov `year`, `cfr_parts`,
`type`, `agency`; research `venue`, `topic`, `also_in`, `status`, `license`, `type`, `year`,
`research`. In the baseline, the model's generated query already matched the gold query's result
on 27 of 27 gov and 26 of 27 research test items; only the answering step, which read retrieved
chunks, failed.

One wording problem: research `also_in` is a string, and gold uses exact equality where the
questions say "also cited by topic X" (membership). On three items the two readings give
different counts (dev 14 against 22 and 2 against 8; test 14 against 23); one test item is
affected, and it is the baseline's one generated-query miss (the model wrote membership). Typed tables keep the raw string column, so the
frozen gold reproduces; the membership reading is exposed as a separate list column and the
mismatch is reported (§10.2).

### 4.3 The extraction family: 33 CFR part 117

| Property | Value |
|---|---|
| Versions in the store | 3 dated eCFR snapshots (chain `ecfr:33:117`) |
| Sections | 1,386 in all versions, **533 distinct section texts**; 424 in the newest version |
| Size | about 578k characters (about 144k tokens); newest version mean 1,009, median 566 characters per section |
| Regular phrases (newest version) | "mile N" 872, "open on signal" 758, "N hours notice" 360, "need not open" 234, "the draw of the X bridge" 381, FR citations 783 |
| Links to the FR table | 54 FR "Drawbridge Operation Regulation(s)" titles (42 distinct). Titles carry waterway, city and state; section headings carry the waterway only and the state sits in the enclosing structure (`DIV7` subject group, 38 states). Matching any comma-separated part of a title to a heading finds 45 of 54; links are made on (waterway key, state), one-to-many (§6) |
| Multiple draws per section | 92 of the newest version's 424 sections govern two or more draws (up to 10), often with different rules per draw |
| Golden overlap | 30 gov v0.1 items cite part 117 (12 factoid, 7 id_lookup, 6 procedure, others) |

Why this family: it is small enough to extract within a modest budget, regular enough that a
regex can cross-check a share of the values, versioned so that `as_of` applies to extracted rows
through the existing chain, and linked to the FR table by waterway and citation. Numbers written
as words ("four hours notice") defeat regular expressions, which is where a model earns its cost.
33 CFR 165 and 47 CFR 73 are each about three times larger and less uniform; the IRM chapters
have no reliable section boundaries in the store; research PDFs and bench are heterogeneous.

## 5. Tables

### 5.1 Contracts

Each table has a committed contract, `config/tables/<table>.json`:

- `table`, `version`, `description` (one line, used by the semantic layer).
- `columns`: name, type (`text`, `int`, `real`, `bool`, `date`, `text[]`, `real[]`), nullable,
  description, `spec_id` (§5.3), and for categorical columns the allowed values (listed in the
  semantic layer only up to 25 values, so it stays under 8 KB).
- `key`: the columns that identify a row; `order`: the total sort order.
- `source`: the corpus, the document selector, and the loader (`metadata` or `extraction`).
- `entities`: which columns are linked to which entity table (§6).

A small validator checks every row against its contract when a table is built; a row that fails
is rejected, counted and reported, never stored silently.

### 5.2 The table overlay

Tables follow the Phase 2 overlay pattern, with the table id in the file name (as dedup names
its files) so that a candidate build, the current build and a re-extraction after a spec change
can coexist: `<store>/tables/<content snapshot>/<table>-v<contract version>-<id[:16]>.jsonl`,
canonical JSON, one row per line, rows in the contract's order. The table id is the SHA-256 of the
file; an existing file with different bytes is refused (write-once). A separate unhashed
`.report.json` per table holds counts, rejections and null reasons by column. A build manifest
`tables-<id[:16]>.json` lists every table file of a build, including the entity tables (§6); its
SHA-256 is the **tables id** carried in handles (§9.3). `<store>/tables/HEAD` names the current
manifest and moves only through the merge gate (§7.6). List columns are stored as JSON arrays.
All Phase 3 builds and measurements use the Phase 2 scratch stores (`.cache/store-p2/`).

For queries, the JSONL files are loaded into an in-memory SQLite database (standard library) per
(tables id, caller view), described in §8. The SQLite file is a derived view, never the record:
SQLite files are not byte-stable across versions, the JSONL files are.

### 5.3 Provenance on every value

Every stored value carries its provenance in a parallel structure, so the row stays queryable:

```json
{"row": {"document_number": "2024-01234", "publication_date": "2024-01-17", ...},
 "prov": {"publication_date": {"doc_id": "…", "start": 1840, "end": 1850,
                               "spec_id": "fr.publication_date@1", "status": "verified"}}}
```

- `spec_id` names the extraction spec and its version (`fr.publication_date@1`,
  `bridge.notice_hours@1`). Changing a spec changes its version and re-extracts only the column
  group that contains it (§7.5).
- A list value carries one provenance entry per element.
- `status` is one of `verified` (span re-slices and every check passed), `auto-accepted`
  (span re-slices, a soft check failed and is recorded), `rejected` (not stored as a value; the
  column is null with a null reason) and `review-pending` (reserved; nothing sets it in Phase 3).
- A null value has a **null reason**: `absent` (the source has no such field or the text states
  nothing), `not_applicable`, `unparseable` (a value was present but failed its type),
  `ungrounded` (the model gave a value whose quote did not re-slice), `model_error` (the provider
  rejected the input itself; that failure is cached like a reply, so a zero-call rebuild
  reproduces it instead of stopping). Transient failures, usage limits, authentication or
  environment failures and budget stops are never cached: they stop the run, and a later run
  retries them (P21).

### 5.4 The 3A tables

| Table | Rows | Key | Notes |
|---|---|---|---|
| `fr_documents` | 167 | `id` (= `document_number`) | the v0.1 record fields `id`, `type`, `agency` (most specific), `publication_date`, `year`, `title`, `cfr_parts` (`text[]`, "33 CFR 117"); plus action, effective date and the Phase 2 envelope status |
| `fr_cfr_refs` | one per (document, title, part) | document, title, part | `cfr_part` text as in v0.1 and integer title and part (39 distinct pairs once the one integer part is normalised) |
| `fr_agencies` | one per (document, agency) | document, agency id | raw name and canonical agency id |
| `fr_dockets` | one per (document, docket) | document, docket | parsed from "Docket No(s)." / "Docket Number" strings only (one string can give several); other identifiers in `docket_ids` ("FCC 19-123", "FRS 16313", "DA 19-1303") go to an `other_ids` column of `fr_documents` |
| `papers` | 2,570 | `id` (the v0.1 record id: arXiv id, else DOI, else `url:` hash) and row number | every manifest column raw, plus `year` as int, `also_in_list` as `text[]`, canonical venue and licence ids |
| `paper_authors` | one per (paper, author position) | paper, position | raw author string and a normalised name; "et al." kept as a flag, not an author |

Raw columns are always kept next to normalised ones. The frozen v0.1 gold queries use raw
semantics (exact venue strings, `also_in` as one string), so the typed database must reproduce
them exactly; normalised columns serve new questions.

`query_table` reproduces the operator semantics of `golden/records.py` exactly, not SQLite's
defaults: case-folding through a registered Python function (SQLite's `lower()` is ASCII-only),
no type coercion (`year = '2020'` does not match an integer year), comparisons of mixed or null
types never match, `__contains` is case-folded substring on text and case-folded element
equality on lists, and `list` returns sorted unique ids. An unknown column is an error naming the
column (columns are public, §9.2).

### 5.5 The 3B table

Two tables, because a section often governs several draws with different rules (§4.3). Rows are
extracted once per distinct section text (533) and repeated for every version that contains the
same text, so each version's rows are complete; the default filter keeps only the version in
force (§8.3), so counts are never multiplied by versions.

`drawbridge_sections`, one row per (section, version):

| Column | Type | Source |
|---|---|---|
| `section` | text | structure: "117.1081" |
| `heading` | text | structure: the section heading |
| `state` | text | structure: the enclosing `DIV7` subject group ("North Carolina") |
| `waterway` | text | model |
| `seasonal` | bool | model: rules differ by season or date range |
| `owner_or_agency` | text | model: the entity to notify or that operates the draws |
| `vhf_channel` | int | model |

`drawbridge_bridges`, one row per (section, version, draw):

| Column | Type | Source |
|---|---|---|
| `section`, `version` | text | structure (join key) |
| `state`, `waterway` | text | repeated from the section row, so one `query_table` call can filter draws by place |
| `bridge` | text | model: the bridge's name as written |
| `mile` | real | model: the waterway mile, if stated |
| `notice_hours` | int | model: advance notice required to open, in hours, if any |
| `opens_on_signal` | bool | model: the draw opens on signal in at least one period |
| `closed_periods` | text[] | model: periods when the draw need not open, as quoted |

The model returns, for each section, the section-level values and a list of draws, each value
with a verbatim quote from the section; code locates every quote in the stored text and records
the offsets (as Phase 0 did for golden quotes). Structure columns carry structure provenance, not
a model spec. Rules stated once for all draws of a section are copied to each draw with the same
quote.

## 6. Entity resolution

Deterministic, no model calls. Each entity type has a table with a canonical id, a display name
and an alias map: `agencies`, `cfr_parts`, `dockets`, `venues`, `licences`, `waterways`,
`authors`.

- **Normalisation key:** Unicode NFKC, case-fold, collapse whitespace, strip surrounding
  punctuation, then per-type rules (for venues, a trailing year or "(year)" and the word
  "preprint" are removed; for licences, spaces and hyphens are unified; for dockets, the prefix
  "Docket No." / "Docket Number" is dropped and a list string is split).
- **Fixed-pivot clustering:** names with the same key form a cluster; the canonical id is the
  SHA-256 of the key. Clustering never chains through transitive fuzzy matches: only equal keys
  merge. The display name is computed per caller view, as the byte-smallest raw form among
  visible rows, so it never reveals a hidden row's spelling and per-view equivalence (§9.2)
  holds. Entity tables are listed in the build manifest (§5.2) and filtered per view like
  other tables.
- **Overrides:** an optional committed file `config/entities/<type>.json` can merge or split
  clusters by key. It starts empty; every override is listed in the report.
- **Waterway links** between `fr_documents` and `drawbridge_sections` use (waterway key,
  state), one-to-many, matched against each comma-separated part of a drawbridge FR title. The
  list of linked and unlinked titles is committed with the 3A results.
- **Measured:** clusters per type, the largest clusters, and singletons, in the report; for
  venues and authors a seeded sample of 50 clusters is listed for the user to inspect.

## 7. Extraction (3B)

### 7.1 Units and prompts

One call per distinct section text (533). The prompt gives the contracts' column descriptions,
the section text, and asks for JSON: the section-level columns and a list of draws, each value
with `value`, `quote`, and `null_reason` when no value is stated. A section's cache key is the SHA-256 of (adapter, model, prompt version, section
text, spec versions), through the existing `.cache/llm` cache, so a section that is unchanged
across versions costs one call in all.

### 7.2 Checks, in order (the QA ladder Phase 3 keeps)

1. **Parse:** JSON parsed with the existing recovering parser; an unparseable reply is retried
   once with the same prompt and repeat index 1, then the row's model columns are null with
   reason `unparseable`.
2. **Type and contract:** values coerced to the column type; allowed values checked.
3. **Span re-slice:** the quote must occur in the section text (after the same whitespace
   normalisation Phase 0 used); its offsets are recorded. Failing values become null with reason
   `ungrounded`.
4. **Value in quote:** for numeric columns, the number (as digits or as a number word) must appear
   inside the quote; otherwise the status is `auto-accepted` with the failed check recorded.
5. **Regex cross-check:** where a regular expression can find the value (for example
   "(\d+) hours? (advance )?notice", "mile (\d+(\.\d+)?)"), agreement is recorded per value;
   disagreement does not reject, it is counted.
6. **Independent second extraction:** a different model (Opus, against Sonnet for the first
   pass) with a structurally different prompt extracts the same facts from every section, in one
   call per section: numbered questions ("1. Which draws does this section govern? 2. For each,
   how many hours of notice…") answered in order with quotes, instead of one JSON form. Draws
   are matched between the passes by bridge-name key, then mile. Agreement per column is
   reported. The second extraction also feeds the 3B golden set (§10.3), so it is never used to
   fix the first.

### 7.3 What "grounded" means

A non-null model value is grounded when check 3 passes. Phase 3 reports, from the extraction
report (before ungrounded values are dropped), the grounded share of non-null model values per
column (criterion E1, target ≥ 95%), and requires that 100% of stored values re-slice (criterion
T3), which holds by construction because ungrounded values are not stored.

### 7.4 Statuses

`verified` when checks 1–4 pass; `auto-accepted` when 1–3 pass and 4 fails; values failing 1–3
are not stored. Regex and second-extraction agreement are reported, not used to change status, so
the status rule does not depend on the gold.

### 7.5 Changing a spec

Bumping one column's spec version (for example a clearer description of `notice_hours`) changes
only that column's cache keys: the extractor groups columns by spec, and each group is its own
cached call per section. A test changes one spec on a fixture and checks that only that group's
calls run (criterion T5). For the real run, the 9 model columns of the two tables are extracted
in one group, so a spec change costs one call per section; the grouping is what makes partial
re-extraction possible.

### 7.6 The merge gate

`adr tables gate --gold <set> --max-flips N` compares a candidate table build with the current
one on a gold set and refuses to promote the candidate (moving `tables/HEAD`) when more than N
gold items that were right become wrong ("negative flips"). Tested on fixtures; used once in the
3B run to promote the first build over an empty table (N = 0 flips possible).

## 8. Access: the semantic layer, the parameterized tool and guarded SQL

Three new tools in `adr_store.tools.Tools`, served over MCP like the five Phase 2 tools:

| Tool | Tier | What it does |
|---|---|---|
| `describe_tables` | T1 | The semantic layer, generated from the contracts: with no argument, an index of every table (columns as `name: type`, entity links, metrics `count` and `count_distinct` as an `sql` template, dimensions); with `table=…`, that table's full column descriptions and allowed values. Each response at most 8 KB |
| `query_table` | T1 | Parameterized: `table`, `filters` (the v0.1 operators plus `__ne`, `__isnull`, `__contains_any`), `op` (`count`, `list`, `lookup`, `count_by`), `fields`, `order`, `limit`, the Phase 2 applicability arguments (`as_of`, `include_superseded`, status), `handle`. Compiled to one parameterised SQL statement by code; the model never writes SQL here. Returns rows with their provenance |
| `sql` | T2 | Guarded read-only SQL: one `SELECT` statement over the caller's view of the tables under the same applicability arguments, with limits. Each table exposes `_doc_id` and one `_prov_<column>` JSON column per column, so a statement can select provenance |

The in-memory database is built per (tables id, caller view, applicability filters) and cached
like the Phase 2 per-view BM25. List columns are JSON arrays; the authorizer allows `json_each`
and `json_extract` so statements can unnest them.

### 8.1 The SQL guard

- The query runs on an in-memory database built from the caller's visible rows only (§9), opened
  for the call; nothing else is attached.
- `sqlite3` authorizer: allow only `SELECT`, `READ` on the table set, and a whitelist of pure
  functions (aggregates, string, date and math functions without side effects). Deny everything
  else: writes, DDL, `ATTACH`, `PRAGMA`, `load_extension`, transactions, temporary objects,
  recursive CTEs beyond a depth.
- One statement only (the parser rejects a trailing second statement).
- A progress handler stops a statement after a fixed budget of virtual-machine steps (no wall
  clock, so the cut-off is deterministic); results are capped at 1,000 rows and flagged as
  truncated.
- Errors return a fixed message per class (syntax, denied, budget, result too large: over 2 MB), never the
  database's internal text, so an error cannot reveal hidden rows or table internals.

### 8.2 Output and determinism

`query_table` results are sorted by the contract order (or the requested order, then the key).
For `sql`, a statement with its own `ORDER BY` keeps it as written; a statement without one is
wrapped as `SELECT * FROM (<statement>) ORDER BY <every output column>`, so the order is total
even for aggregates and statements that do not select the key. Same arguments, same tables id, same view: byte-identical
rows. Every result carries a handle.

### 8.3 Applicability

A row inherits the Phase 2 envelope of the document it came from. The default filter drops rows
of superseded documents (older eCFR versions); `as_of` selects rows of the version in force, as
for search. `include_superseded` exposes all versions.

## 9. Permissions and handles

### 9.1 Rows inherit document access

Each row records its source `doc_id`. A caller sees a row only if the Phase 2 ACL lets them see
that document (keyed by chain, as before). Research manifest rows all come from one document, so
they are visible all together or not at all; FR rows vary by caller; §117 rows follow the chain.

### 9.2 Hidden equals nonexistent, for tables

- The in-memory database for a call holds only visible rows, so counts, aggregates, `count_by`
  groups and errors are computed over the caller's view. A table with no visible rows exists and
  is empty; table and column names come from the contracts, which are not secret.
- Equivalence (as Phase 2's B2): for every view, `query_table` and `sql` results equal those
  over a store built from that view's documents alone.
- Each call goes through `acl.resolve` and the Phase 2 log line (caller, principals, ACL
  snapshot, decision, view, not_visible, handle), plus the tables id and, for `sql`, the
  statement's SHA-256 (not its text, which may contain values).

### 9.3 Handles

The Phase 2 handle gains one optional part, `tables` (the tables id, default null), so handles
saved before Phase 3 still validate. A handle naming a tables id that no longer exists fails
explicitly ("handle no longer available: tables"); the ACL is never part of a handle, so an old
handle is judged against the current ACL (ruling R15 of Phase 2 still holds). The five Phase 2
tools' results gain the new handle key; "unchanged" for them (constraint 2) means identical hits,
counts and messages.

## 10. What is measured

### 10.1 Systems

| System | Answers count and list questions by |
|---|---|
| `baseline-linear` (recorded, Phase 0) | reading retrieved chunks |
| `p3-typed` | the generated query (G2) compiled to `query_table` over the typed tables. It runs on `count_filter` items only (the runner gains a question-type filter); it never falls back to answering from chunks |

All Phase 3 harness runs search as `user:auditor` after a fresh ACL sync (the Phase 2 freshness
limit is one hour).

### 10.2 The frozen count questions (3A)

The 27 gov and 27 research test `count_filter` items, scored exactly as Phase 0 scores them
(number closeness, set equality). The generated queries are the baseline's: all 54 replies are in
the model cache under the same key (adapter, model, query-generation prompt, schema, question),
so 3A's measurement makes no model call, provided the query-generation prompt and the record
schema text stay byte-identical (checked before the run). Reported: accuracy for both systems,
the paired McNemar test, and every miss with its cause. The `also_in` wording problem (§4.2) is
reported with both readings.

Because those generated queries already return the gold records on 27 of 27 gov and 26 of 27
research items, Q1 is close to certain by construction: it tests that the typed tables and the
compiler reproduce the record semantics, not a new ability to understand questions. The
write-up says so.

### 10.3 A new golden set for the 3B table: `gov-tables v0.1`

Questions over drawbridge facts that a flat retriever finds hard: counts and lists across
sections ("How many drawbridges on the Atlantic Intracoastal Waterway in North Carolina require
advance notice?"), multi-constraint filters, and lookups.

- **Facts:** from the independent second extraction (§7.2 step 6), not from the table under test,
  with its own verbatim quotes re-sliced by code.
- **Questions:** drawn by code from those facts (one or two clauses from a sampled row, as v0.1's
  count_filter drawer does, extended to bool fields, numeric ranges and `__isnull`); the model
  only phrases them (one call per question; no evidence-only check call). The gold query is a
  `query_table` argument object (table, filters, op), a new gold format with its own prompt
  version, since v0.1's `gold_query` has no table or `count_by`. Answers are computed by code
  over the version in force. 120 items, split by the existing `assign_split` (20% dev): about
  24 dev and 96 test.
- **Limits, stated up front:** the gold comes from a model, not a person. A shared error of the
  two models (same wrong reading of a section) is invisible to this measurement. Agreement with
  the regex cross-check, where it applies, is reported as an independent check on the gold.

### 10.4 Probes (no model calls)

| Family | What it checks | Count |
|---|---|---|
| Table leak | for each user, `query_table` and `sql` over rows of hidden documents (by key, by filter, by aggregate, by `count_by` group, by error message) return what a store without those documents returns | ≥ 300 |
| SQL guard | writes, DDL, `ATTACH`, `PRAGMA`, `load_extension`, multiple statements, recursive CTE bombs, huge cross joins, functions outside the whitelist, comment and encoding tricks | ≥ 100 |
| Table equivalence | gov and research × 20 views × 25 queries against stores built from each view's documents (research rows are all-or-nothing per view, so its share tests little; gov carries the weight). Bench and tools have no tables and are checked empty | 1,000 |
| Fail closed | (F1–F5 and "no entry") × the three new tools × 5 callers | 90 |
| Applicability | default and `as_of` queries on the drawbridge tables and `fr_documents` return only rows of documents in force | ≥ 50 |

## 11. Model-call budget (needs the user's approval)

Models, both through the Claude Code adapter on the user's subscription with the model named on
every call: Sonnet is `claude-sonnet-5-5`, Opus is `claude-opus-5-5`. Every call records the model
the service reports as having answered.

`--max-calls` counts per command, so each command gets a fixed share; the shares sum to the cap.
Every transport attempt, retries included, counts against the share, so real use cannot exceed it.

| Command | Purpose | Model | Share (calls) |
|---|---|---|---|
| `adr tables extract` (first pass) | 533 distinct §117 sections, plus retries | Sonnet | 560 |
| `adr tables extract --second-pass` | the same sections, one numbered-question call each, plus retries | Opus | 560 |
| `adr-eval golden tables` | phrasing about 120 questions, plus redraws of malformed replies | Sonnet | 140 |
| `adr-eval run` (`p3-typed` and `baseline-linear`, one shared query-generation prompt, so one query call per item serves both) | query generation for the 120 questions | Sonnet | 125 |
| `adr-eval run` (`baseline-linear` answers) | answers from retrieved chunks, test split only (about 96 items) | Sonnet | 100 |
| | | **Total cap** | **1,485 of 1,500** |

Kept out of the budget by design: the proxy judge and self-consistency calls (gov-tables items
are counts, lists, numbers and yes/no lookups, all scored exactly), and v0.1's evidence-only
check call. Calls the provider rejects for their input are cached as failures (§5.3), so they are not
repeated; every other failure stops the run without being cached (P21), and each transport
attempt, retries included, counts against the cap.

At the cache's recorded medians (6.8 s per Sonnet call, 6.6 s per Opus call), about 2.8 hours of
calls serially, about 45 minutes at the configured concurrency of 4. Billed to the Claude
subscription; the notional cost at the recorded rates is about $40. Nothing is called before the
user approves; part 3A and all probes need no approval.

## 12. Exit criteria

Fixed now, before any Phase 3 result (as in Phase 2, ruling R10's margin of 0.02 where a
comparison is paired).

| # | Criterion | How it is measured | Threshold |
|---|---|---|---|
| T1 | Zero-call rebuild | Rebuild every table with `--max-calls 0` from the cache in a fresh process | Byte-identical table files and tables id |
| T2 | Identical result sets | The 3A and 3B question suites and every probe set run twice in fresh processes | Identical rows and results |
| T3 | Every stored value re-slices | Every provenance span of every table | 100% re-slice to the stored quote or field text |
| T4 | Every value traces to a spec | Every stored value | 100% carry a `spec_id` (or structure provenance) |
| T5 | A spec change re-extracts only affected fields | Fixture: change one column group's spec | Only that group's calls run; other cache keys and values unchanged |
| T6 | The merge gate blocks regressions | Fixture: a candidate with flips above the threshold | Refused, and `tables/HEAD` unchanged |
| Q1 | Typed tables answer the frozen count questions | `p3-typed` on 27 gov and 27 research test items | ≥ 0.90 accuracy on each corpus, and above `baseline-linear` with McNemar p < 0.05 on gov |
| Q2 | Typed tables answer the new drawbridge questions | `p3-typed` against `baseline-linear` on the test items of gov-tables v0.1 (about 96) | ≥ 0.80 accuracy, and the lower bound of the paired difference's 95% interval above +0.02 |
| E1 | Extraction is grounded | Non-null model values in the drawbridge tables, from the extraction report before ungrounded values are dropped | ≥ 95% grounded (re-slicing quotes) |
| E2 | Extraction agrees with an independent pass | Per column, against the Opus extraction (draws matched by bridge-name key, then mile) | Agreement reported for every column; ≥ 0.85 on `waterway`, `bridge` (draw set per section), `notice_hours`, `opens_on_signal` |
| S1 | No leak through tables | Table leak probes and table equivalence | 0 leaks; 1,000 of 1,000 equivalent |
| S2 | SQL is read-only and bounded | SQL guard probes | 100% refused or bounded, with the fixed messages |
| S3 | Fail closed and logged | Fail-closed probes; every log line of the table tools | No content in any case; 100% of lines carry the Phase 2 fields plus the tables id |
| D1 | Over MCP with handles | MCP tests for the three new tools; a handle replay | All pass; every result carries a handle with `tables` |
| X1 | Determinism | As T2, plus overlays and entity tables built twice | Identical |

## 13. Approaches considered

| Approach | For | Against | Decision |
|---|---|---|---|
| **JSONL overlay as the record, in-memory SQLite per caller view for queries** | Standard library only; byte-stable records; per-view databases make hidden-equals-nonexistent and B2-style equivalence exact; the authorizer gives a real read-only guard | Rebuilds the in-memory database per view (cached per tables id and view; tables are thousands of rows, milliseconds) | **Chosen** |
| DuckDB file as the record | Fast analytics, a path to DuckLake | New native dependency; the file is not byte-stable; per-view filtering inside one file needs row policies the engine does not enforce for us | Rejected for Phase 3; an exporter can write DuckDB later |
| Extend the in-memory filter of `golden/records.py`, no SQL | Smallest change; already reproduces v0.1 | No second tier for questions outside the parameterized operators; the roadmap names guarded SQL | Rejected; `query_table` keeps the same operator semantics |
| Row-level security inside one shared SQLite database (views with `WHERE doc_id IN …`) | One database | A guard bug leaks across callers; aggregates and errors over a shared file are harder to prove equal to an allowed-only store | Rejected in favour of physical per-view databases |

For 3B, the alternatives to model extraction were regular expressions alone (the cross-check of
§7.2 shows where they fail: numbers in words, multiple bridges per section, exceptions) and
extracting from 33 CFR 165 or 47 CFR 73 (three times the cost, less uniform text).

## 14. Rulings made without the user

| # | Ruling | Why | Cost if wrong |
|---|---|---|---|
| P1 | Model calls only for the purposes and cap of §11 | The user asked for a fixed, cached budget, approved before use | Fewer checks than an unlimited budget would allow |
| P2 | The extraction family is 33 CFR 117 | Smallest, most regular, versioned, linked to FR; a regex cross-check exists | A family with more varied facts might show more of the extractor's limits |
| P3 | Sonnet extracts, Opus checks | The configured generator and judge; different models make shared errors less likely than one model twice | Shared errors of the two models stay invisible (§10.3) |
| P4 | Raw columns kept beside normalised ones; v0.1 gold semantics reproduced exactly | v0.1 is frozen; changing semantics would change its answers | Agents may pick the raw column where the normalised one is meant; the semantic layer describes both |
| P5 | Rows inherit document access; no row-level policy | Phase 2's access model is per document; a row is never more visible than its source | The research manifest is all-or-nothing per caller |
| P6 | JSONL overlay is the record; SQLite is a per-call derived view | Byte-stable records and exact per-view equivalence | Some query latency per view (cached) |
| P7 | SQL errors return fixed messages per class | An engine's error text can name hidden values | Harder debugging for agents writing SQL |
| P8 | Deterministic SQL budget by virtual-machine steps, not time | Wall-clock limits make outcomes machine-dependent | A step budget can cut off a legitimate heavy query |
| P9 | gov-tables v0.1 gold comes from the second model's extraction, phrased by a model, answered by code | No human reviewer; the same pattern as v0.1's code-computed count items | Gold can share the extractor's errors; disclosed with regex agreement |
| P10 | No human review step; `review-pending` reserved | No reviewer | The roadmap's review rung is not exercised |
| P11 | Entity resolution by exact normalised keys only, with empty override files | Deterministic and auditable; no fuzzy chaining | Some true aliases stay separate (reported with samples) |
| P12 | The merge gate is built and tested, and used for every promotion (three in this phase: gov 3A, research 3A, gov 3B) | The roadmap's fourth invariant; HEAD moves only through it | Its threshold is untested on a real regression |
| P13 | Margins and thresholds of §12 fixed now | As in Phase 2 (R10) | A true small loss under the margin passes |
| P14 | Two drawbridge tables, sections and draws | 92 of 424 newest sections govern several draws with different rules; one row per section would lose them | One more table to query; questions about draws need a join or the draws table |
| P15 | The second extraction is one numbered-question call per section, not one call per column | Keeps the second pass inside the budget while its prompt stays structurally different | Less independence than separate per-column calls |
| P16 | `p3-typed` runs on count items only and never answers from chunks | Phases 1–2 never produced answers; a fallback would spend answer and judge calls | `p3-typed` is not a whole-system accuracy number |
| P17 | Entity display names are computed per caller view | A global most-frequent spelling can reveal hidden rows | Display names can differ between callers |
| P18 | `describe_tables` is an index plus per-table detail, each at most 8 KB | Fifteen-plus contracts with descriptions do not fit one 8 KB response; shortening descriptions would weaken the semantic layer | An agent needs a second call to read a table's column descriptions |
| P19 | A `sql` statement's own top-level `ORDER BY` gets positional tie-breakers on every output column | Constraint 3 requires a total order; keeping the statement's order alone leaves ties in scan order | Slightly different order than a database client would show for ties |
| P20 | `sql` bounds work per step: stored values limited to 8 KB and rows to 16 KB (as built in Task 5), and string-amplifying functions charged by result size against the step budget | A step budget alone does not bound CPU, memory or temporary disk when values are large | A legitimate query building very long strings is refused |
| P21 | Only failures caused by the input (`InputRejected`: HTTP 400/413/422, or a stub) are cached as `model_error`; retries exhausted, usage limits, other 4xx, a missing binary, malformed responses and budget stops propagate and stop the run | Caching a usage limit or outage would write permanent `model_error` rows for sections the model never saw, and Task 11 runs against a subscription limit | A section that fails for a non-input reason every time stops every run until fixed, rather than becoming a null |
| P22 | A bool value is non-null only with a quote that states it, `false` included; a `false` that would rest on the section's silence is null `absent` (prompts `drawbridge-extract@2`, `drawbridge-questions@2`) | Found in a 3-call check before the run: the model wrote `seasonal: false` with no quote, which check 3 rejects as ungrounded, so E1 would measure prompt wording rather than grounding | Few stored `false` values; a question about non-seasonal sections counts only those the text states |

## 15. Build order

1. Contracts, the table overlay writer and validator, provenance and statuses (fixtures).
2. 3A loaders for FR and the manifest; entity resolution; tables built for gov and research.
3. `describe_tables`, `query_table`, `sql` with the guard, under the ACL, applicability and
   handles; MCP; probes S1–S3, D1.
4. `p3-typed` in the harness; measure Q1 (no model calls); write up 3A.
5. The extractor, checks and gate, tested on fixtures with the stub model (no calls).
6. **After the user approves §11:** the 3B run; gov-tables v0.1; measure E1, E2, Q2, T1–T6; X1;
   write up `results/phase3/README.md`.
