# Phase 2: Applicability, Permissions, Tools as Data and an MCP Server — Design

Date: 2026-11-16
Status: written by the assistant from the user's decisions and the reviewer's rulings (section
13). Every other choice is listed in section 14 as a ruling made without the user, with what it
costs if it is wrong. Nothing here is built yet.
Sources: `reports/Agent data retrieval research summary.md` (the Phase 2 row of the roadmap,
"Permissions", "Consolidated design defaults", "Defaults to avoid"); the Phase 1 design and code
(`docs/superpowers/specs/2026-11-13-phase1-evidence-store-design.md`, `src/adr_store/`);
`results/phase1/README.md`; `corpora/*/README.md`; `golden/gov/v0.1/`. The numbers in sections
4 to 6 come from read-only probes of the Phase 1 stores, run on 2026-11-16; the probe scripts are
scratch files and are not committed. Numbers marked **predicted** come from a prototype of the
filter, not from the code this spec describes.

## 1. Purpose

Phase 2 makes the evidence store safe and correct to serve to agents. It serves goal G3: the
right unit, deterministically, for the right caller, at the right date. It has four parts, built
and measured in this order:

| Part | What it adds | Why it comes here |
|---|---|---|
| 2A Applicability | Envelope fields per document; version chains; validity, status, jurisdiction and authority filters; exact and near-duplicate detection; canonical selection | A stale or duplicated passage costs more than a missing one. Validity filters beat recency ranking |
| 2B Permissions | Principals on every chunk, vector, tool record and log line; pre-filtering inside `search`, `grep`, `read`; a separate, fail-closed ACL sync with revocation | Hard to retrofit. Post-filtering is the documented anti-pattern |
| 2C Tools as data | `ToolRecord` from OpenAPI, MCP and ToolRet tool descriptions; `search_tools` and `load_tool` | Agents should load the few tools a task needs, not all of them |
| 2D MCP server | A stdio MCP server over `adr_store.tools.Tools` with explicit snapshot handles | Phase 1 left it out on purpose: the CLI fixed behaviour first |

The user's decisions:

- No sync from a real permission system. Synthetic tenants, groups and users get deterministic
  access lists. The filtering, the fail-closed behaviour, the sync and revocation mechanics and
  their tests are real.
- The user will evaluate the product. Exit criteria are few, measured and stated before the run.

## 2. Scope

In scope: the four parts above, their harness support, their tests, and a write-up in
`results/phase2/`.

Out of scope:

| Item | Why |
|---|---|
| Sync from a real identity or permission system (Entra, Google, Okta, SharePoint) | User decision: synthetic tenants for now |
| SQL, typed tables, SQL leak probes | Phase 3. The roadmap's criterion names SQL; it is deferred with the database |
| Graph tools and graph leak probes | Phase 5 |
| HTTP transport, OAuth, multi-user MCP sessions | stdio only. The principal is fixed per server process (§9.3) |
| MCP Tasks and Multi Round-Trip Requests | No Phase 2 tool runs long or needs input mid-call. The Python SDK does not implement the Tasks extension (§9.1) |
| Executing tools found by `search_tools` | `load_tool` returns a definition; calling the tool is the agent's own business |
| Element-level or row-level ACLs | Access is per document. Chunks inherit their document's access list |
| Timing side channels, filesystem access to the store | The store directory is the trust boundary (§7.1) |
| A new golden set | v0.1 stays frozen (ruling R3) |

## 3. Constraints

1. **The canonical text and the Phase 1 records do not change.** Envelope fields, duplicate
   clusters and access lists are overlays: new write-once files beside the Phase 1 records,
   each naming the content snapshot it describes. No Phase 1 snapshot id, doc record, chunk id
   or index fingerprint changes.
2. **Phase 1 stays reproducible.** The Phase 1 systems, commands and saved runs work unchanged.
   A Phase 2 path with an all-access caller, no filters and no dedup returns exactly the Phase 1
   ranking (ids and scores) (criterion A5).
3. **Determinism.** Every new path gives identical results run to run: no wall-clock input into
   any ranking, ties broken by id, sorted iteration, fixed seeds for MinHash. The only
   time-dependent decision is the ACL freshness check (§7.6), which denies; it never reorders.
4. **No model calls** in building or measuring Phase 2 (ruling R1). Everything below is
   computed from the corpora, the golden sets and published benchmark labels.

## 4. Part 2A: applicability

### 4.1 What gov contains (probe, 2026-11-16)

| Family | Documents | Versions | Dates in the corpus |
|---|---|---|---|
| eCFR point-in-time XML | 9 | 3 parts × 3 dated versions: 33 CFR 117, 33 CFR 165, 47 CFR 73 | The eCFR date of each file (`source_version`) |
| Internal Revenue Manual chapters | 4 | One version each | Manual Transmittal dates 2025-11-25 (20.1.1), 2026-02-03 (5.19.1), 2026-09-02 (21.4.1), 2026-09-15 (21.5.1) |
| Federal Register API documents (JSON) | 167 | One each; not a chain | `publication_date` 167, `effective_on` 111, `dates` text 167 |

- **Version chains:** 3 document-level chains of 3 versions, 6 supersession links.
- **Sections inside the chains** (`<DIV8>`): 1,289 distinct (117: 483, 165: 390, 73: 416).
  Between consecutive versions, 189 sections change text, 145 are removed and 41 are added.
  The 189 changes are the corpus adapter's `version_pairs()`.
- **Federal Register:** 120 Rules and 47 Proposed Rules. By `action`: 54 temporary rules, 59
  final rules, 44 proposed rules, 7 enforcement notices, 3 other. 43 of the 54 temporary rules
  state an end date in `dates` that a simple pattern ("effective from … through …") parses.
- **Chunks:** 6,783 `p1-struct-bc` chunks. 4,032 of them (59%) lie in superseded eCFR versions,
  leaving 2,751 in force.
- **Phase 1 top 10** (`p1-struct-bc`, gov test, 242 questions):
  - 52.9% of the 2,420 slots hold a chunk from a superseded version;
  - 40.7% hold an exact copy of a chunk ranked above it.
  - research and bench: 0% on both counts.

The `policy_asof` golden items:

- 40 items in 20 pairs (test 34, dev 6). Each pair asks one question at two dates.
- Every `as_of` equals one of the pinned eCFR dates (2025-06-30 ×14, 2026-06-30 ×13,
  2025-06-10 ×5, 2026-06-22 ×5, 2024-06-27 ×2, 2025-06-27 ×1).
- All 40 evidence spans lie in the version that the rule in §4.3 selects for the item's
  `as_of`. That version is superseded for 22 items and the chain's head for 18.
- Phase 1 retrieval without the date on the 34 test items: Recall@10 0.853, nDCG@10 0.567,
  MRR 0.471. The right passage is usually in the top 10, but below copies from the wrong
  version.

Non-as-of gov items:

- 179 test items have evidence.
- 158 of them have, for every evidence group, a member in an in-force document. For 60 of
  those 158, the gold span itself lies in a superseded version and is credited through its copy
  in force (metric definitions v2, §3).
- 21 test items (2 dev) have a group whose members all lie in superseded versions: sections
  later removed or changed. Default retrieval will not return them (§4.6).

### 4.2 The envelope record

A new write-once overlay, `adr_store/applicability.py`, holds one record per document:

| Field | Type | Meaning |
|---|---|---|
| `doc_id` | string | The document |
| `chain_id` | string or null | Documents that are versions of one source, e.g. `ecfr:33:117`, `irm:21.4.1` |
| `version_label` | string | The source's version label (the Phase 1 `source_version`) |
| `supersedes`, `superseded_by` | doc id or null | Neighbours in the chain, by `valid_from` |
| `valid_from` | date or null | First day the text is in force |
| `valid_to` | date or null | First day it is no longer in force (exclusive); null = open |
| `validity_basis` | enum | `ecfr_snapshot`, `fr_effective_on`, `fr_publication_date`, `fr_dates_text`, `irm_transmittal`, `unknown` |
| `status` | enum | `codified`, `final_rule`, `temporary_rule`, `proposed_rule`, `notice`, `guidance`, `unknown` |
| `jurisdiction` | string or null | `US-federal` for gov; null elsewhere |
| `issuer` | string or null | Most specific agency: Coast Guard, FCC, IRS |
| `authority_tier` | integer 1–4 or null | 1 codified regulation; 2 final or temporary rule as published; 3 agency guidance and notices; 4 proposals; null unknown |
| `provenance` | list | For each derived field: the source location it came from (`manifest.source_version`, `fr.effective_on`, `fr.dates` with the matched text range, `config.parts[i].agency`) |

`status` is time-independent: it says what the document is, not whether it is in force today.
Whether a document is in force is a function of `valid_from`, `valid_to` and a date, evaluated
at query time.

File layout, beside Phase 1's:

```
<store>/applicability/<snapshot_id>/<deriver>-<version>.json   canonical JSON: format_version,
                                                               snapshot, deriver, records (by doc_id)
```

- The overlay id is the SHA-256 of the file.
- `adr applicability derive [--store S]` writes the overlay for HEAD. It refuses to overwrite a
  file that differs.
- Deriving twice gives byte-identical files.

### 4.3 How the envelope is derived (deterministic, from the corpus only)

| Family | Rule |
|---|---|
| eCFR | `chain_id` from the URI (title, part); versions ordered by date. `valid_from` = the eCFR date; `valid_to` = the next pinned date in the chain, null for the head. `status` `codified`, tier 1, `jurisdiction` `US-federal`, `issuer` from the corpus config |
| Federal Register | No chain. `status`: `proposed_rule` if `type` is Proposed Rule; `notice` if `action` names an enforcement notice or notification; `temporary_rule` if `action` contains "temporary"; else `final_rule`. `valid_from` = `effective_on`, else `publication_date` (basis recorded). `valid_to` = the day after the "through" date for a temporary rule whose `dates` parse, else null (parse failures are counted in the compile report). Tier 2, or 4 for proposals, 3 for notices |
| IRM | `chain_id` `irm:<chapter>`, one version. `valid_from` = Manual Transmittal date; `valid_to` null; `status` `guidance`; tier 3; `issuer` IRS |
| research, bench | Every field `unknown` or null, `validity_basis` `unknown`. No dates are invented |

Caveats the compile report states:

- **The eCFR interval is the gap between pinned snapshots,** not the true amendment interval.
  33 CFR 117 had 178 amendment dates since 2020, and the corpus holds three of them. A snapshot
  is evidence of the text on its own date. For a date between snapshots, Phase 2 serves the
  latest snapshot on or before it and labels the basis `ecfr_snapshot`.
- **The IRM pages are current pages,** so a date before a chapter's transmittal finds no IRM
  version of it.

### 4.4 Filters and their semantics

`search`, `grep` and `read` accept the same filter arguments. All filters are hard pre-filters
(§6), never reranking.

| Argument | Meaning |
|---|---|
| (default) | Exclude documents with `superseded_by` set. A structural rule; it does not depend on today's date |
| `include_superseded=True` | Drop the default exclusion (the Phase 1 view) |
| `as_of=D` | Replace the default with "in force on D": `valid_from ≤ D` and (`valid_to` null or `D < valid_to`) and `status ≠ proposed_rule`. A document with unknown `valid_from` is excluded |
| `status=[…]` | Keep these statuses (naming `proposed_rule` lets proposals through `as_of`) |
| `jurisdiction=[…]` | Keep these jurisdictions |
| `max_tier=n` | Keep `authority_tier ≤ n` |

- **Unknown never matches.** A filter on a field excludes documents whose value is null or
  `unknown`, and the result reports how many documents of the caller's view the filters
  excluded. This keeps a nullable facet from silently filtering.
- **Expiry is not a default.** Expired temporary rules are not excluded by default: that would
  make results depend on the day the query runs. A caller who wants "in force today" passes
  `as_of` explicitly.
- **No overlay, no dates.** When a store has no applicability overlay for its snapshot,
  `as_of`, `status`, `jurisdiction` and `max_tier` are refused ("no applicability overlay; run
  `adr applicability derive`"). Default search then behaves as Phase 1 and its result says
  `applicability: null`.

### 4.5 Duplicates and canonical selection

Near-duplicate detection (`adr_store/dedup.py`) runs over the chunks of one index's chunker
configuration and writes a write-once overlay:

```
<store>/dedup/<snapshot_id>/<sha256(chunker config + dedup params)[:16]>.json
    clusters: [{cluster_id, members: [chunk_id…], kind: exact|near, min_jaccard}]
```

- **Exact:** SHA-256 of the chunk text (the body as stored, not normalised; whitespace
  normalisation finds no more duplicates on any corpus).
- **Near:** MinHash over word 5-shingles (lower-cased `\w+` tokens; a chunk with fewer than 5
  words is one shingle).
  - 128 hash functions `(a·h + b) mod 4,294,967,311`, where `h` is the first 4 bytes of the
    shingle's SHA-256 and `a`, `b` come from `random.Random(20261116)`.
  - LSH with 16 bands of 8 rows.
  - Every candidate pair is verified by exact Jaccard on the shingle sets. A pair joins a
    cluster at Jaccard ≥ **0.90**, and clusters are the connected components.
  - All parameters are recorded in the overlay and the compile report.
- **The near threshold is conservative on purpose.** The `policy_asof` pairs show that near
  duplicates can differ in exactly the fact asked about ("FCC Form 302" against "FCC Form
  2100, Schedule 302"). Version chains, not dedup, handle versions.

**Canonical selection.** The canonical member of a cluster is chosen at query time, among the
members that pass the caller's ACL view and filters:

1. in force at the query's reference point (`as_of` if given; otherwise the head of its chain,
   `superseded_by` null);
2. then the lower `authority_tier` (null last);
3. then the later `valid_from` (null last);
4. then the smaller `doc_id`, then the smaller `char_start`.

**Collapse.**

1. Fusion produces up to 200 ranked candidates.
2. Walking them in rank order, the first member of each cluster takes the slot. That slot shows
   the cluster's canonical member, with the score of the best-ranked member (`scored_by` names
   it).
3. `alternates` lists the other members that are visible and pass the filters (chunk id, doc
   id, `exact` or `near`, Jaccard).
4. The walk stops at `top` clusters.

Members the caller cannot see are never chosen and never listed. With dedup off, the ranking is
Phase 1's.

Measured now (probe, Phase 1 chunks):

| Corpus | Chunks | Exact clusters (chunks in them) | Redundant chunks (tokens) | Near pairs at J ≥ 0.9 (clusters) | Redundant at J ≥ 0.9 | Redundant at J ≥ 0.8 |
|---|---|---|---|---|---|---|
| gov (all versions) | 6,783 | 1,958 (5,430) | 3,472 = 51.2% (48.7%) | 366 (1,976) | 54.0% | 55.1% |
| gov (in-force view) | 2,751 | 0 | 0 | 1 (1) | 0.04% | 0.2% |
| research | 9,554 | 1 (3, within one document) | 2 | 3 (3) | 0.1% | 0.1% |
| bench | 7,400 | 1 (3, across documents) | 2 | 0 (1) | 0.0% | 0.1% |

- **Every gov exact cluster spans eCFR versions** (444 of size 2, 1,514 of size 3).
- **The version filter already removes them.** Once superseded versions are excluded, gov has
  no exact duplicates left.
- **Where dedup does matter here:** with `include_superseded` on gov, and in the mechanism
  tests (§12). Research and bench have almost none. The write-up must say this plainly, not
  present dedup as a retrieval gain.

### 4.6 Predicted effect on gov retrieval

A prototype of the default filter, the `as_of` rule and exact collapse was run on gov test
(`p1-struct-bc`: BM25 only, `w_bc` 2, per-view statistics as in §6.2). It ignores Federal Register
and IRM validity. Phase 2 minus Phase 1, with 95% paired bootstrap intervals:

| Items | n | Configuration | Recall@10 | nDCG@10 | MRR | Superseded / wrong-version slots |
|---|---|---|---|---|---|---|
| `policy_asof`, with `as_of` | 34 | applicability | 0.853 → 0.853 (+0.000) | 0.567 → 0.820 (+0.254 [+0.182, +0.325]) | 0.471 → 0.809 | wrong-version 213 → 0 |
| non-as-of, every group has an in-force member | 158 | applicability (default) | 0.784 → 0.807 (+0.023 [+0.004, +0.048]) | 0.727 → 0.762 (+0.035 [+0.021, +0.051]) | 0.717 → 0.752 | superseded 743 → 0 |
| non-as-of, a group only in superseded versions | 21 | applicability (default) | 0.857 → 0.000 | 0.746 → 0.000 | 0.709 → 0.000 | superseded 139 → 0 |
| non-as-of, evidence in force | 158 | dedup only (superseded kept) | +0.016 | +0.020 | 0.717 → 0.735 | duplicate slots → 0 |
| `policy_asof`, without `as_of` | 34 | dedup only | 0.853 → 0.588 | 0.567 → 0.434 | 0.471 → 0.380 | Collapse picks the head version; dated items need `as_of` |

Tokens@10 moves by less than 1% in every row: dedup swaps duplicates for other chunks of similar
length. Its effect shows in duplicate slots (40.7% → 0 on gov) and distinct evidence per 10
slots, which the write-up reports, not in tokens@10.

The 21 items lose by design: their gold passage is no longer in force, and the question carries
no date. They are reported separately and kept out of criterion A4 (ruling R3).

**A metric artefact to report.** The v2 copy rule credits a passage in another document only
when 200 characters of context on each side also match. So a chunk-identical copy at a section
edge is sometimes not credited. That is why "dedup only" loses on the 21 items. The metric is
not changed; the write-up states the effect.

## 5. Part 2B: permissions

### 5.1 Principals

- A principal is a string: `public`, `tenant:<t>`, `group:<t>/<g>` or `user:<id>`.
- A caller is a user id. The tools resolve it, through the synced directory in the ACL snapshot,
  to a principal set: the user, its groups, their tenants, and `public`.
- A caller never passes groups or tenants itself, so it cannot claim a membership.
- A document is visible to a caller when its access list intersects the caller's principal set.
- There is no wildcard principal. An all-access caller is an ordinary user who is a member of
  every group (`user:auditor`).

### 5.2 The synthetic directory and policy (committed)

```
config/acl/directory.json   tenants, groups, users, memberships (the stand-in permission system)
config/acl/policy.json      ordered assignment rules, seed, max sync age
```

**Directory.**

- **Tenants:** 3, `acme`, `globex` and `initech`.
- **Groups:** 4 per tenant, 12 in all (`group:acme/0` … `group:initech/3`).
- **Users:** 6 per tenant, 20 in all with the two below.
  - User `k` of a tenant is in group `k mod 4`; users 4 and 5 are also in group `(k+1) mod 4`.
  - `user:auditor` is in every group, which makes it the all-access caller.
  - `user:outsider` is in no tenant and sees `public` only.
- **Probes** also call as `user:ghost`, who is not in the directory.

**Policy.**

- Each document, and each tool record, gets an access list from a hash bucket.
- The key is the document's `chain_id` when it has one (all versions of a source share access),
  else its `doc_id`; for a tool record, its `tool_id`.
- `b = int(SHA-256("adr-acl-v1\nbucket\n" + key)[:8], 16) mod 100`, and the access list is:

| Bucket | Share | Access list |
|---|---|---|
| 0–19 | 20% | `public` |
| 20–29 | 10% | two tenants (shared) |
| 30–74 | 45% | one tenant |
| 75–99 | 25% | one group of one tenant (restricted) |

The tenant and group come from further salted hashes of the same key. Simulated on the current
stores:

| Corpus | Documents | public / shared / tenant / group | A tenant user sees (min–max) | `outsider` sees | Distinct views |
|---|---|---|---|---|---|
| gov | 180 | 39 / 17 / 90 / 34 | 43–51% | 22% | 20 |
| research | 245 | 46 / 24 / 100 / 75 | 38–46% | 19% | 20 |
| bench | 2,000 | 436 / 213 / 884 / 467 | 45–49% | 22% | 20 |

The policy file can also hold attribute rules (by format or URI prefix), applied before the
buckets. Phase 2 ships none.

### 5.3 The ACL snapshot (versioned and synced apart from content)

`adr acl sync [--store S] [--directory F --policy F]` runs one **sync cycle**:

1. Read the directory and the policy, and validate them against their schemas.
2. Compute the access list of every document of the store's HEAD content snapshot and of every
   tool record of its tool catalog.
3. Write the ACL snapshot.
4. Atomically replace `acl/HEAD`.

A failure at any step leaves the old HEAD in place.

```
<store>/acl/snapshots/<acl_snapshot_id>.json
    format_version, sequence (previous + 1), synced_at (UTC),
    content_snapshot, tool_snapshot, directory_sha256, policy_sha256,
    directory (users → principal sets), docs {doc_id: [principals]}, tools {tool_id: [principals]},
    entries_sha256 (SHA-256 of the canonical directory+docs+tools: equal for equal inputs)
<store>/acl/HEAD      the current ACL snapshot id
```

The snapshot id is the SHA-256 of the file. It includes `synced_at`, so every sync is a new
version; `entries_sha256` shows whether access changed.

**Projection.**

- Access lists are projected onto chunks and vectors when a tool loads an index.
- The projection is a boolean visibility mask over the index's chunk order, derived from the
  ACL snapshot and the caller.
- It is a pure function of (index, ACL snapshot, user), so revocation never re-embeds or
  re-indexes anything.
- `adr acl show --chunk ID` prints a chunk's principals.

### 5.4 Fail-closed rules

A tool call resolves its access on entry. Any of these means **no access** for the whole call;
tools return an error naming the reason, and the log records it:

| # | Condition |
|---|---|
| F1 | `acl/HEAD` missing, unreadable, unparsable, schema-invalid, or its file's SHA-256 is not its id |
| F2 | The ACL snapshot's `content_snapshot` is not the store's HEAD (content changed since the last sync: the ACL is older than the content) |
| F3 | `now − synced_at` exceeds `max_sync_age_s` from the policy (default 3,600), or `synced_at` is more than 300 s in the future |
| F4 | The caller's user id is not in the snapshot's directory, or no caller is given |
| F5 | A principal string that does not match the grammar of §5.1 |

Per-document rules:

- A document or tool with no entry, or an empty list, is visible to no one. There is no "public
  by default".
- A caller pinned to an older content snapshot (by handle, §9.2) is judged against the current
  ACL snapshot. A document that no longer has an entry is invisible.
- So revocation also applies to old handles.

Errors never reveal what is hidden:

- A document, chunk, element or tool the caller cannot see is reported exactly as one that does
  not exist: the same message, byte for byte.
- An id prefix resolves among visible ids only, so "ambiguous prefix" cannot reveal a hidden id.
- Counts in a result (matches, `truncated`, excluded-by-filter) cover the caller's view only.

### 5.5 Sync and revocation

- **Sync cycle:** one completed run of `adr acl sync`, from reading the directory to replacing
  `acl/HEAD`. Phase 2 runs it on demand (cron in deployment). F3 bounds how stale access may get.
- **Propagation:** every tool call re-reads `acl/HEAD` on entry, a stat and a cached parse by
  id, and uses one ACL snapshot for the whole call. So every call that starts after the swap
  honours it, including calls to a long-running MCP server. A call already in flight finishes
  under the snapshot it began with.
- **Lag:** "within one sync cycle" means that once the first sync after a directory change
  completes, no later call shows the revoked access. Between the change and that sync, access
  is the old one, for at most `max_sync_age_s`.
- **ACL-lag metric:** the sync duration, and the time from the directory file's change to the
  HEAD swap. Both are logged in the sync log.

### 5.6 The retrieval log

Every log line (Phase 1 format) gains these fields:

- `caller`: the user id given;
- `principals`: the resolved set;
- `acl_snapshot`;
- `acl_decision`: `allowed` or `denied:F1`…`denied:F5`;
- `view`: the SHA-256 of the sorted visible doc ids;
- `filters`, `applicability`, `dedup`;
- `not_visible`: requested ids that were invisible. Recorded for audit, and never returned to
  the caller.

The log is for the operator. No tool reads it.

## 6. Filtering inside the engine

### 6.1 Pre-filter, not post-filter

Phase 1 scores every chunk in both channels: BM25 with `bm25s.get_scores` over all chunks, and
dense as one matrix product. It then takes the top 100 per channel and fuses them. Phase 2 puts
the masks before the top-100 cut:

- **Lexical:** a BM25 index over the caller's view (§6.2), with the applicability mask applied
  to the scores before `top-k`.
- **Dense:** the shared vectors, with the view mask and the applicability mask applied to the
  cosine scores before `top-k`. No vector is copied, and no endpoint returns vectors.
- **Fusion:** min-max linear over the two masked candidate lists, the Phase 1 weights unchanged
  (no retuning per view).
- **Grep and read:** the document list sent to the grep worker is the visible, filtered list. A
  doc-scoped grep or a read of an invisible document is "not found".

A filter can never starve the result: the cut is taken after masking.

### 6.2 BM25 statistics under ACLs (the IDF choice)

- **Dense is exact with a mask.** Its scores do not depend on other documents.
- **BM25 is not.** IDF and the average document length depend on the whole indexed set. With
  global statistics and a mask, an allowed caller's scores would not equal those of an index of
  the allowed documents. They would also leak: the score of a rare term moves when a hidden
  document contains it, and that score difference is a membership-inference channel. The
  research summary reports membership inference against RAG in about 30 queries at under $0.02
  per document.

**Choice: BM25 statistics per ACL view.**

- A view is the set of documents a caller can see.
- Phase 2 builds one BM25 index per distinct view, over the view's chunks, lazily on the first
  call and cached in memory by (index fingerprint, view id).
- Users with the same view share it. Dense vectors stay shared.
- **Exact equivalence.** For any caller, `search` returns exactly the ranking (ids and scores to
  6 decimals) that the same system returns on a store holding only that caller's visible
  documents. Fusion weights are the store's tuned ones in both. This is tested bit for bit
  (criterion B2).
- **Applicability filters do not change the statistics.** They are masks within the view's
  statistics. They hide nothing secret, and per-filter statistics would multiply the indexes by
  the number of distinct dates. So with `as_of` or the default filter, BM25 statistics include
  the view's superseded versions; the prediction in §4.6 uses exactly this.
- **Cost.** BM25 builds in 1.4–1.7 s for 6,800–7,400 chunks. The synthetic directory has 20
  views, under 40 s per corpus if every user calls. A view cache holds at most 32 views (LRU).
- **Deployments with many distinct views** need persisted per-view statistics. That is noted
  for Phase 6, not built.

The alternatives are in §11.

## 7. Part 2B as data: where principals live

| Object | How it carries principals |
|---|---|
| Document | `docs[doc_id]` in the ACL snapshot |
| Chunk and vector | The projection mask (§5.3), computed from the chunk's `doc_id` |
| Tool record | `tools[tool_id]` in the ACL snapshot |
| Log line | `caller`, `principals`, `acl_snapshot`, `acl_decision`, `view` |
| Duplicate alternates | Filtered to the view at query time (§4.5) |

### 7.1 What is and is not a security boundary

- **The enforcement point is the `Tools` API,** reached through the MCP server. An agent served
  over MCP has no filesystem access to the store.
- **The CLI's `--as USER` is for tests and simulation.** Whoever can run the CLI can read the
  store directory, so the CLI is not a security boundary, and its help says so.
- **The roadmap's open problem**, "grep over materialized files needs per-principal views", is
  avoided, not solved: Phase 2 never materializes per-principal file trees, and grep runs over
  the store through the API.

## 8. Part 2C: tools as data

### 8.1 The tool record

`adr_store/tool_records.py`:

| Field | Type | Meaning |
|---|---|---|
| `tool_id` | string | SHA-256 of `source_uri`, `name` and the SHA-256 of the canonical `input_schema`, joined by newlines |
| `name`, `title` | string, string or null | As the source gives them |
| `description` | string | The source's description. Untrusted text, returned as data, never as instructions |
| `input_schema`, `output_schema` | JSON Schema, JSON Schema or null | MCP `inputSchema` / `outputSchema`; built from OpenAPI parameters and request body; built from ToolRet parameter lists |
| `source_kind` | enum | `mcp`, `openapi`, `toolret` |
| `source_uri`, `source_version` | string | Where the description came from |
| `operation` | object or null | OpenAPI: method, path, `operationId`. MCP: server name. ToolRet: category and API name |
| `license` | string | From the catalog manifest |
| `definition_tokens` | integer | Tokens of the MCP Tool definition (name, description, inputSchema) as the harness counts tokens |

**Adapters.**

- **MCP:** a `tools/list` result.
- **OpenAPI 3.x:** one record per operation. Local `$ref`s are resolved, depth-capped at 8.
- **ToolRet:** ToolBench-style documentation (`category_name`, `name`, `description`,
  `method`, `required_parameters`, `optional_parameters`). Parameters become an object schema
  with `required`.

**Store layout.** The catalog is a separate snapshot, so tools can change without a new content
snapshot.

```
<store>/tools/records/<tool_id[:2]>/<tool_id>.json
<store>/tools/snapshots/<tool_snapshot_id>.json      sorted tool ids with record hashes
<store>/tools/HEAD
```

### 8.2 Search and load

- **`search_tools(query, top=10, filters)`** returns, in rank order, `tool_id`, `name`, a
  one-line summary (the first sentence of the description, at most 200 characters), the source,
  the score and the handle. It does not return the schema.
- **`load_tool(tool_id)`** returns the full MCP Tool definition, ready to register.
- **Both filter by the caller's view.** An invisible tool does not exist for that caller.
- **The tool index** (`adr_store/retrieval/tool_index.py`) mirrors `StoreIndex`:
  - BM25 over a fielded text: the name split on case and underscores, repeated `w_name` times;
    the description; parameter names and descriptions.
  - Dense over "name: description. Parameters: …" with the Phase 1 embedding model.
  - Linear fusion. `w_name` and `w` are tuned on the tool dev split.
  - Per-view BM25 statistics, as in §6.2.

### 8.3 The tool corpus and test queries

**Pick: ToolRet, the `toolbench` subset.** ToolRet ([arXiv 2503.01763](https://arxiv.org/abs/2503.01763)) is a tool-retrieval benchmark of 44,453
tools and about 7.6k queries collected from 35 datasets, with gold tool labels. The `toolbench`
subset:

| | |
|---|---|
| Tools | 14,059 real RapidAPI endpoint descriptions from ToolBench (ids `toolbench_tool_*` in `mangopy/ToolRet-Tools`, revision `e06c38c75612b6536bd959e08cdd345894aba6a7`, config `web`) |
| Queries | 1,100 (`mangopy/ToolRet-Queries`, revision `b8c76ad3349ff17497b6bdb28bb5b8f61a0f6445`, config `toolbench`); 2.39 gold tools per query; every gold tool is in the 14,059 |
| Size | 1,227,462 tokens of raw documentation (mean 87, median 58 per tool) |
| Splits | dev = the queries whose SHA-256 of the id is 0 mod 5 (about 220), test = the rest; fixed before any tuning |
| Licence | ToolBench data: Apache-2.0 (its README: "distributed under Apache License 2.0"). ToolRet code repository: Apache-2.0. The ToolRet dataset cards declare no licence (open question Q2) |
| Handling | As bench: files fetched into `data/tools/` (git-ignored), pinned by SHA-256 in `corpora/tools/manifest.json`; never committed |

The query field is used; ToolRet's added `instruction` field is not.

**Measured now** (probe: BM25 over the raw documentation strings, the harness tokenizer):

- On the 14,059 toolbench tools: Completeness@10 **0.386**, Recall@10 0.581, over all 1,100
  queries.
- On all 44,453 ToolRet tools: Completeness@10 0.244.
- The top 10 raw documents average 1,114 tokens, 0.09% of the catalog.

**Conformance only, not measurement.** The MCP and OpenAPI adapters are checked on fixtures,
plus two small pinned real sources:

- twenty OpenAPI specs from the APIs.guru `openapi-directory` (CC0), at a pinned commit;
- `tools/list` snapshots captured from the MCP reference servers `mcp-server-time`,
  `mcp-server-fetch` and `mcp-server-git` (MIT), installed from PyPI at pinned versions.

### 8.4 Metrics

- **Completeness@10:** 1 if every gold tool of a query is in the top 10, else 0. Mean over
  queries, as ToolRet defines it. Also reported: Recall@10, nDCG@10.
- **Tool-context reduction:** `1 − loaded / catalog`.
  - `loaded` = tokens of the `search_tools` page plus the `load_tool` definitions of the top 10.
  - `catalog` = tokens of every definition in the catalog (an agent that loads all tools).
  - Mean over test queries.
  - Also reported: absolute `loaded` tokens, and the share of `loaded` spent on gold tools.
- **The 80% threshold is easy here.** With 14,059 tools the reduction will be above 99%, and it
  would be above 98% on a 1,000-tool sample. Completeness@10 against the BM25 baseline is the
  criterion that carries information.

## 9. Part 2D: the MCP server

### 9.1 Specification and SDK (checked 2026-11-16)

**Specification 2026-07-28** (final, released 28 July 2026, [MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28/)):

- **Stateless core.** `initialize` and `Mcp-Session-Id` are gone, and each request carries its
  version and capabilities in `_meta`. State is application-level: "mint an explicit handle from
  a tool and have the model pass it back as an argument", which is exactly §9.2.
- **Tasks** are now the official extension `io.modelcontextprotocol/tasks` (SEP-2663).
- **Multi Round-Trip Requests** replace server-initiated elicitation and sampling.
- **`Mcp-Method` and `Mcp-Name` headers** are for Streamable HTTP only.
- **Roots, Sampling and Logging** are deprecated.

**Python SDK:** `mcp` **2.3.0** on PyPI (2 October 2026, MIT, Python ≥ 3.10).

- Its v2 line implements 2026-07-28 and still serves 2025-era clients.
- High-level server class `mcp.server.MCPServer`; client `mcp.Client` with
  `StdioServerParameters`.
- The 2.2.0 notes say the Tasks extension is not implemented yet, and 2.3.0 does not add it.
- Its dependencies accept the repository's pinned `pydantic==2.14.3`.
- Pinned exactly, in a new optional extra `[mcp]`, so the core install is unchanged.

**Used:** 2026-07-28, stdio transport, `tools/list` and `tools/call` with output schemas and
structured content, tool annotations. **Not used:** Tasks, MRTR, subscriptions, resources,
prompts, logging, HTTP.

### 9.2 Snapshot handles

Every result carries a `handle` object:

```
{"snapshot": <content snapshot id>, "index": <index fingerprint>,
 "applicability": <overlay id or null>, "dedup": <overlay id or null>,
 "tools": <tool snapshot id or null>}
```

- Every tool accepts an optional `handle` argument.
- **Given:** the call runs on exactly those components, or fails with "handle no longer
  available: <component>". There is no silent fallback to HEAD.
- **Omitted:** HEAD is used, and the result's handle says which.
- **Never part of a handle:** the ACL snapshot. Access is always the current ACL (§5.4).
- **Stateless:** the server keeps no session state and writes nothing to resolve a handle.

### 9.3 Server

`adr mcp --store S --as USER` (`adr_store/mcp_server.py`) is a thin wrapper:

- One `MCPServer("adr")` with five tools: `search`, `read`, `grep`, `search_tools`,
  `load_tool`.
- Each takes the arguments of the `Tools` method of the same name, plus `filters` and `handle`.
- Each returns the method's dataclass as structured content, with a declared output schema and
  a short text rendering.
- Annotations: `readOnlyHint`, `idempotentHint`, and `openWorldHint: false`.
- Pages are small: `top` ≤ 50, and `cursor` for `search` (a rank offset) and `grep` (the last
  `doc_id`, offset).

**Principal.**

- stdio has no authentication, so the principal is fixed when the server starts (`--as`, or
  `ADR_CALLER`). A server without one refuses to start.
- No tool argument names a principal.
- Multi-user serving needs the HTTP transport and OAuth, which is out of scope.

**Errors.** A `ToolError` becomes a result with `isError: true` and the message. ACL failures
F1–F5 have their own messages. Invisible ids are "not found" (§5.4).

**No logic of its own.** The server holds no retrieval or ACL logic. Every call goes through
`Tools`, which logs it.

## 10. What is measured

### 10.1 Systems and configurations

All run with `adr-eval retrieval` (no model calls) on dev and test of all three corpora. The
Phase 1 weights (`w`, `w_bc`) are reused, not retuned, so each change is attributable.

| Configuration | ACL caller | Applicability | Dedup | Purpose |
|---|---|---|---|---|
| `p1-struct-bc` (recorded) | — | — | — | The Phase 1 reference, from `results/phase1/` |
| `p2-identity` | `auditor` | `include_superseded` | off | Regression guard: must equal Phase 1 exactly |
| `p2-appl` | `auditor` | default; `as_of` from the item | off | Applicability alone |
| `p2-dedup` | `auditor` | `include_superseded` | on | Dedup alone |
| `p2-default` | `auditor` | default; `as_of` from the item | on | The Phase 2 default |

**Harness changes.**

- `retrieve(question)` becomes `retrieve(question, as_of=None)`.
- For a `policy_asof` item, the harness passes the item's own `as_of`: the date is part of the
  question's input, not a guess.
- The retrieval report gains, per configuration:
  - superseded slots and wrong-version slots;
  - duplicate slots;
  - distinct evidence groups touched in the top 10;
  - the item subsets of §4.6.

**Tools.** `adr-eval tools-retrieval --system <name>` runs on the ToolRet split with three
systems:

- `tools-bm25-raw`: the baseline, BM25 over the raw documentation strings;
- `tools-bm25f`: fielded BM25 over tool records;
- `tools-hybrid`: fielded BM25 plus dense, linear fusion.

The best on dev goes to test.

**Probes.**

- `adr-eval probes acl <corpus>` and `adr-eval probes temporal gov` generate deterministic probe
  sets (seed 20261116), write them to `runs/` and report pass counts.
- The ACL probe set is also run through the MCP server.

### 10.2 Probe sets (no model calls)

**Leak probes.**

- Each probe is a (caller, target) pair: the target is a document, chunk or tool the caller
  cannot see, sampled by seeded hash over all callers, including `outsider` and `ghost`.
- A **leak** is any of the following:
  - a returned id outside the caller's view;
  - an alternate outside the view;
  - text of a hidden document;
  - a not-found message that differs from a nonexistent id's;
  - a count that includes hidden items;
  - a score that differs from the reference allowed-only index (B2).

| Family | Probe | Per corpus | Total |
|---|---|---|---|
| search | Query = the 10 rarest tokens (highest IDF over the whole corpus) of a hidden chunk | 100 | 300 |
| search | Query = a hidden document's title or breadcrumb | 50 | 150 |
| grep | Literal pattern = a 30-character substring unique to a hidden document | 50 | 150 |
| grep | Doc-scoped grep (`--doc`) on a hidden document | 20 | 60 |
| read | Read a hidden document by full id and by 8-character prefix; read a hidden chunk and element | 60 | 180 |
| search_tools / load_tool | Hidden tool's name and summary as the query; `load_tool` of a hidden id | — | 200 |
| fail closed | F1–F5 and "no entry", each × the 5 tools × 5 callers | — | 150 |
| total | | | **1,190** |

All 1,190 run against the Python API. A seeded subset of 300 also runs through the MCP server.
Synthetic fixtures add cases the corpora lack: an id prefix shared by a visible and a hidden
document, and an exact duplicate shared by a public and a restricted document.

**Equivalence probes (B2).**

- For each corpus: 20 views × 50 queries (the golden questions of that corpus, seeded sample).
- `search` and `grep` results must be identical to the same calls on a store built by ingesting
  only that view's documents.

**Temporal probes (gov).**

| Set | Default mode | `as_of` = the older date |
|---|---|---|
| T1: 40 `policy_asof` items | — | 0 chunks from documents not in force on `as_of` |
| T2: 189 changed sections, query = the section heading (`§ N Title.`) | 0 superseded chunks in the top 10; the head version's section chunk rank reported | 0 chunks from other versions; the old section's Recall@10 reported |
| T3: 145 removed sections, query = the heading | 0 chunks from superseded documents | The removed section is found (Recall@10 reported) |
| T4: all 297 gov golden questions, no date | 0 superseded chunks in the top 10 | — |
| T5: Federal Register and IRM, `as_of` before `valid_from` | — | The document is absent |

## 11. Approaches considered

| Choice | Alternatives | Trade-offs | Pick |
|---|---|---|---|
| Where envelope fields live | (a) new fields in `SourceRecord`; (b) write-once overlay per snapshot; (c) an SQLite side table | (a) changes every doc record and snapshot id and breaks constraint 1; (c) adds an engine before Phase 3 needs one | (b), like Phase 1 structure |
| Version granularity | (a) document chains; (b) section chains; (c) both | eCFR versions are whole-part snapshots, so (a) gets supersession right, removed sections included. (b) needs section identity across formats the other corpora lack | (a). Section pairs are used only for probes |
| Default temporal rule | (a) exclude superseded (structural); (b) exclude expired against today's date; (c) recency decay | (b) changes results from day to day, against constraint 3; (c) is on the avoid list | (a), with explicit `as_of` for date logic |
| BM25 statistics under ACLs | (a) global statistics with a mask; (b) per-view statistics, shared vectors; (c) a full physical index per principal set | (a) leaks document frequencies (membership inference) and breaks equivalence; (c) duplicates vectors per view | (b): exact equivalence, no IDF channel, about 1.5 s per view |
| Where filters apply | (a) post-filter the top k; (b) over-fetch c·k, then filter; (c) mask before the top-k cut in full-scan scoring | (a) is the anti-pattern and starves selective filters; (b) still starves at low selectivity | (c): exact search makes it free |
| Duplicates | (a) drop duplicates at index time; (b) cluster at write time, collapse at query time within the view; (c) exact only | (a) loses alternates and cannot respect per-caller views; (c) misses near copies | (b), with a conservative 0.90 threshold |
| ACL sync | (a) access lists inside the content snapshot; (b) a separate ACL snapshot with HEAD swap; (c) evaluate the directory live on every call | (a) makes revocation a re-ingest; (c) leaves no versioned record of what was enforced and cannot fail closed on staleness | (b) |
| Tool corpus | (a) ToolRet `toolbench` subset; (b) APIs.guru (CC0) with generated queries; (c) all 44k ToolRet tools; (d) MCP registry snapshots | (b) needs about 1,000 model calls for queries and gold, and those are circular; (c) mixes many licences; (d) few tools and no gold | (a); (b) and (d) as adapter conformance sources |
| MCP implementation | (a) `MCPServer` (high-level); (b) the low-level `Server`; (c) hand-written JSON-RPC | (c) re-implements a moving spec; (b) needs schemas and validation by hand | (a), falling back to (b) only if output schemas cannot be stated exactly |
| Snapshot handles | (a) server session state; (b) an explicit handle object in arguments; (c) a handle registry on disk | (a) is gone from the 2026-07-28 spec; (c) writes on reads | (b) |

## 12. Testing

**Applicability.**

- The deriver: on fixtures for every family, including a temporary rule whose `dates` does not
  parse. Byte-identical re-derivation.
- Interval semantics at the boundaries (`D = valid_from`, `D = valid_to`, null ends).
- Unknown never matches a filter.
- A missing overlay refuses `as_of`.

**Dedup.**

- Exact clusters equal the SHA-256 groups.
- MinHash is fixed by its seed: fixed signatures for fixture texts.
- Candidate pairs are verified.
- Canonical selection follows each tie-break in order.
- Collapse never shows two members of one cluster, and never shows or lists an invisible or
  filtered member.
- With dedup off, the ranking is Phase 1's.

**Permissions.**

- The directory and policy schemas.
- Bucket assignment is stable, and chains share access.
- The projection matches the ACL snapshot for every chunk.
- Per-view BM25 equals an index built over the view's chunks.
- B2 equivalence against a subset store.
- Each fail-closed rule F1–F5, and "no entry".
- Not-found byte equality; prefix resolution within the view; view-only counts.
- Log fields on allowed, denied and failed calls.

**Revocation.** One test per change kind, each checked on `search`, `grep`, `read`,
`search_tools` and `load_tool`:

- Change kinds: a user removed from a group; a document's rule changed in the policy; a user
  deleted.
- Steps:
  1. The caller can see the target.
  2. Edit the directory or policy copy.
  3. Before the sync: unchanged.
  4. Run one sync.
  5. The target is invisible, in a new process and in an MCP server process started before step 2.
- Plus: a new content snapshot denies all until a sync (F2).
- Plus: a stale snapshot denies all (F3, with an injected clock).

**Tools.**

- Adapters on MCP, OpenAPI and ToolRet fixtures, and on the pinned real sources.
- `tool_id` is stable.
- `load_tool` output validates as an MCP Tool.
- Tool search is deterministic.

**MCP.**

- Start the server as a subprocess with `mcp.Client(StdioServerParameters(...))`.
- `tools/list` returns the five tools with input and output schemas.
- 100 fixed calls return structured content equal to the Python API's results.
- Every result has a handle, and replaying a call with its handle gives the same result.
- A handle whose index was deleted fails explicitly.
- The 300-probe leak subset passes.

**Regression.** All Phase 1 tests pass unchanged. Criterion A5 runs in CI on the mini fixture
and in the measurement on the three corpora.

## 13. Exit criteria

| # | Criterion | How it is measured | Threshold |
|---|---|---|---|
| A1 | No superseded unit in default top-k | T2 (default), T3 (default), T4 on gov; every golden item on research and bench | 0 superseded chunks in any default top 10 |
| A2 | `as_of` selects the version in force | T1, T2 (`as_of`), T3 (`as_of`), T5 | 0 chunks from documents not in force on `as_of` |
| A3 | Dated questions are served at least as well | `policy_asof` test items (34), `p2-default` against `p1-struct-bc` | Lower bound of the 95% paired interval of the difference > −0.02 on Recall@10 and nDCG@10 (predicted: +0.000 and +0.254) |
| A4 | Applicability does not lower Phase 1 on non-as-of items | Per corpus, test, `p2-default` against `p1-struct-bc`, on non-as-of items whose every evidence group has a member visible under the default filters | Lower bound > −0.02 on Recall@10 and nDCG@10 (predicted gov: +0.023 and +0.035). The 21 gov items whose evidence is only superseded are reported, not counted |
| A5 | Regression guard | `p2-identity` against the recorded `p1-struct-bc` runs, all items, dev and test, three corpora | Identical ranked chunk ids and scores for every item |
| A6 | Dedup does what it says | `p2-dedup` and `p2-default` | 0 top-10 slots holding two members of one cluster (Phase 1 gov: 40.7%); clusters and parameters recorded; effect on metrics and tokens@10 reported |
| B1 | Zero leaks | 1,190 probes (§10.2), all through the API and 300 through MCP, covering search, grep, read, search_tools and load_tool; SQL is Phase 3 | 0 leaks; at least 500 probes; at least 100 in each family |
| B2 | Filtering equals an allowed-only index | 3 corpora × 20 views × 50 queries, against subset stores | Identical ids and scores |
| B3 | Revocation within one sync cycle | The revocation tests of §12 | All pass, including the already-running MCP server |
| B4 | Fail closed | F1–F5 and "no entry" × 5 tools | No content returned in any case |
| B5 | Every log line carries its principals | Every log line written during B1–B4 | 100% have `caller`, `principals`, `acl_snapshot`, `acl_decision` |
| C1 | At least 1,000 real tool records | The ToolRet `toolbench` catalog | 14,059 records ingested, 100% adapter conformance |
| C2 | Tool-context reduction | Mean over test queries (§8.4) | ≥ 80% (expected > 99%) |
| C3 | Tool search at least as complete as BM25 | Completeness@10 on the test queries, best Phase 2 tool system against `tools-bm25-raw` | Point estimate ≥ the baseline's, and the paired interval's lower bound > −0.02 |
| D1 | MCP server with snapshot handles | The MCP tests of §12 | All pass; every result carries a handle |
| X1 | Determinism | Every configuration of §10.1, the tool systems and the probe sets run twice in fresh processes; overlays derived twice; two syncs from the same inputs | Identical results; byte-identical overlays; equal `entries_sha256` |

Margins are fixed now, before any Phase 2 result exists (ruling R10). A3, A4 and C3 use the
paired bootstrap of `adr_eval.scoring.stats` (10,000 resamples, seed 20261108). Each is one
pre-declared comparison per corpus, so no Holm correction across them.

## 14. Rulings made without the user

| # | Ruling | Why | Cost if wrong |
|---|---|---|---|
| R1 | No model calls in Phase 2; no end-to-end answer run | No criterion needs one. An end-to-end gov run would cost about 730 subscription calls and could be added later | Answer accuracy under `as_of` is not shown, only retrieval |
| R2 | Phase 2 builds on `p1-struct-bc` with its Phase 1 weights, not on `baseline-linear` | Applicability and ACLs are store features; the baseline chunker is the harness's. Fixed weights make effects attributable | A retuned system might do better; `baseline-linear` remains the Phase 1 reference for answers |
| R3 | Golden v0.1 stays frozen. The 21 gov test items whose evidence is only in superseded versions are reported apart, not counted in A4 | Changing frozen data needs the user (Q1) | A4 is measured on 158 of 179 gov non-as-of evidence items |
| R4 | Document-level chains; the eCFR interval is the gap between pinned snapshots | It is all the corpus holds; the basis is recorded | A date between snapshots gets the earlier snapshot, which may predate an amendment |
| R5 | The default excludes superseded documents only; expiry applies only with an explicit `as_of` | Determinism | "Today" queries over expired temporary rules see them unless the caller passes `as_of` |
| R6 | Under `as_of`, proposals and documents of unknown validity are excluded unless named | `as_of` asserts that something was in force | Research and bench return nothing under `as_of`, which is the honest answer |
| R7 | Near-duplicate threshold Jaccard 0.90, word 5-shingles, 128 hashes, 16 × 8 bands | Conservative: near copies can differ in the asked fact | Some near copies stay uncollapsed (0.8 would add 1.1 points of redundancy on gov's all-version view) |
| R8 | Per-view BM25 statistics; applicability filters are masks within the view | Exact equivalence and no IDF side channel; per-date statistics would multiply indexes | BM25 under the default filter still counts superseded versions in IDF; a view cache rebuild costs about 1.5 s |
| R9 | 3 tenants, 12 groups, 20 users; buckets 20 / 10 / 45 / 25; access keyed by chain | Gives every corpus public, shared, tenant and restricted documents and 20 distinct views | Not a real organisation's shape; no evidence about large numbers of views |
| R10 | Non-inferiority margin 0.02 for A3, A4 and C3, fixed in advance | Phase 1 showed that "not lower" read as a point estimate was ambiguous | A true loss under 0.02 would pass |
| R11 | Fail closed denies the whole call for F1–F5; per-document absence denies that document | Partial answers under a broken ACL are leaks waiting to happen | Any sync failure is an outage until the next good sync |
| R12 | The principal is fixed per MCP server process; the CLI's `--as` is not a boundary | stdio has no authentication; HTTP and OAuth are out of scope | One process per caller |
| R13 | ToolRet `toolbench` subset as the tool catalog, local-only, not committed | Real tools with gold queries and no model calls; upstream Apache-2.0 | The ToolRet dataset cards state no licence (Q2) |
| R14 | `mcp==2.3.0` in an optional `[mcp]` extra; no Tasks | Current stable SDK implementing 2026-07-28; Tasks are unimplemented in it and unneeded | Tasks-dependent features wait for the SDK |
| R15 | The ACL never forms part of a snapshot handle | Revocation must reach old handles | A replayed handle can return fewer results after a revocation, by design |
| R16 | Tool descriptions are untrusted data; there is no poisoning defence beyond that | Poisoned-description drills are a roadmap "known unknown", not a Phase 2 criterion | A malicious description can still mislead an agent that loads it |

## 15. Questions settled without the user

The user asked to proceed without further questions ("synthetic tenants are enough for now,
just dive in"). The two open questions were settled as follows; both can be reversed later.

**Q1. Golden data.** Golden v0.1 stays frozen (ruling R3). The 23 non-as-of gov items whose
evidence exists only in superseded eCFR versions (21 test, 2 dev) are reported apart. Giving
them an `as_of` date belongs to golden v0.2, with the other v0.2 fixes.

**Q2. Tool corpus licence.** ToolRet is used local-only, like bench (ruling R13): nothing from
it is committed except its pinned revisions, hashes and counts. The fallback (APIs.guru with
about 1,000 model-generated queries) would be circular and is not used.

## 16. Build order

1. **2A.**
   1. Applicability overlay and deriver.
   2. Filters in `StoreIndex` and `Tools`.
   3. Dedup overlay and collapse.
   4. Harness `as_of` plumbing and the Phase 2 configurations.
   5. Temporal probes.
   6. Measure A1–A6.
2. **2B.**
   1. Directory and policy files.
   2. `adr acl sync` and the ACL snapshot.
   3. Projection and per-view BM25.
   4. Fail-closed rules and log fields.
   5. Leak, equivalence and revocation probes.
   6. Measure B1–B5.
3. **2C.**
   1. Tool records and the adapters.
   2. The ToolRet corpus adapter and manifest.
   3. The tool index, `search_tools` and `load_tool` (with ACLs).
   4. Measure C1–C3.
4. **2D.**
   1. MCP server and handles.
   2. MCP tests and the MCP leak subset.
   3. D1.
5. **Write-up.** X1 across everything, then `results/phase2/README.md`, in the Phase 1 format.

Each part ends with its criteria measured and written up before the next begins. A failed
criterion is reported as failed, with the component that caused it.
