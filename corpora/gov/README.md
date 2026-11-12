# gov: US government corpus

All sources are US federal government works, in the public domain (17 U.S.C. 105). Files are
fetched into `data/gov/` (git-ignored); `manifest.json` pins each file by SHA-256.

| Source | Files | `source_version` | URI |
|---|---|---|---|
| eCFR point-in-time XML | `ecfr/title-{T}/part-{P}/{date}.xml` | eCFR date | `https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{T}.xml?part={P}` |
| Internal Revenue Manual | `irm/part{N}/{slug}.html` | Manual Transmittal date (ISO) | `https://www.irs.gov/irm/part{N}/{slug}` |
| Federal Register API | `fr/{document_number}.json` | FR document number | `https://www.federalregister.gov/api/v1/documents/{n}.json?fields[]=…` (fields pinned in `config.json`) |

## How the CFR parts were chosen (2026-11-08)

1. Listed every non-reserved title with
   `versions/title-{T}.json?issue_date[gte]=2020-01-01`, paged, at 1 request/s.
2. Counted distinct `amendment_date`s on or after 2020-01-01 for each part.
3. Read part sizes from `structure/2026-11-01/title-{T}.json`.
4. The best 3 parts across at most 2 titles, each under 2 MB, were:

| Part | Agency | Amendment dates since 2020 | XML size | Dates pinned |
|---|---|---|---|---|
| 33 CFR 165 (regulated navigation areas) | Coast Guard | 444 | 1.71 MB | 2024-06-27, 2025-06-30, 2026-06-30 |
| 47 CFR 73 (radio broadcast services) | FCC | 227 | 1.69 MB | 2024-06-13, 2025-06-10, 2026-06-22 |
| 33 CFR 117 (drawbridge operation) | Coast Guard | 178 | 0.54 MB | 2024-06-27, 2025-06-27, 2026-06-26 |

Parts with more amendment dates were too large. For example, 40 CFR 52 has 962 dates but
is 17.5 MB, 40 CFR 180 is 3.7 MB, and 26 CFR 1 is 69.7 MB. For each part, the pinned dates
are the latest amendment dates on or before 30 June of 2024, 2025 and 2026.

`version_pairs()` splits each version into `<DIV8>` sections and pairs consecutive dates where
a section's text differs: 189 pairs (165: 78, 73: 61, 117: 50).

## IRM chapters

The IRM covers the IRS, and neither the Coast Guard nor the FCC has an IRM counterpart. So,
as the brief allows, these are general taxpayer-procedure chapters:

- 5.19.1 Balance Due
- 20.1.1 Introduction and Penalty Relief
- 21.4.1 Refund Research
- 21.5.1 General Adjustments

## Federal Register

- One query per pinned part and calendar-year window, 2020 to 2026-10-31:
  `conditions[agencies][]` = the part's agency, `conditions[cfr][title|part]` = the part,
  `order=oldest`, `per_page=8`.
- Results are de-duplicated by document number, and each document is fetched individually,
  with the pinned `fields[]`, as one JSON file. That gives 167 documents: 120 Rules and
  47 Proposed Rules.
- `records()` rows: `id` (document number), `type`, `agency` (most specific), `publication_date`,
  `year`, `title`, `cfr_parts`, `_doc_id`. No `_span`: each row is its whole document.

## Extraction note

eCFR uses inline markup inside words, for example `<I>Enforcement period</I>s.` Since
extractor version 2, the inline tags (`E`, `I`, `B`, `SU`, `FR`, `FTREF`, `sup`, `sub`,
`strong`, `em`, `b`, `i`) no longer start a new line. On the nine pinned XML files, a
boundary check found about 300 places where version 1 split a word.

## Rebuild

```
python -m adr_eval.corpora.registry build gov   # ~200 requests at 1 request/s per host
python -m adr_eval.corpora.registry fetch gov   # re-download files listed in manifest.json
```

The files are fetched from live government sites and are not committed. The four IRM pages
are pinned by their exact bytes, so `fetch gov` fails with a hash mismatch once irs.gov
changes any of them; from then on others cannot rebuild this snapshot or reproduce the gov
baseline. Build in a clean `data/` directory.
