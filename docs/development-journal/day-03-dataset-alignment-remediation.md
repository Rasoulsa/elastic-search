# Day 3: Dataset alignment remediation

## Discovery

- Date: 2026-09-07
- Branch: `fix/linkedin-dataset-column-alignment`
- Scope: bounded backend importer correction discovered during Day 3 browser acceptance.

The browser showed company-size values as job titles, dates and salary ranges as countries,
serialized collections as industries or summaries, and country values as skills. The frontend was
rendering corrupted PostgreSQL and Elasticsearch state; no frontend change was required.

The root cause was treating `len(row) == len(header)` as proof of alignment. The private file has
336 logical records, including 283 exact-width records in ten deterministic row layouts and 53
malformed-width records. The exact-width layouts include a header-aligned order, a legacy order with
the three Facebook fields appended, and collection-block reorderings with block starts 25, 28, 39,
40, 41, 44, 45, 46, and 48.

## Corrective implementation

The importer now:

- detects layouts from structural signatures such as URL, list/dictionary, nested experience and
  education keys, date, numeric, and version-status shapes;
- maps rows through named source-layout contracts before normalization;
- rejects ambiguous or unknown layouts without persistence;
- validates scalar boundaries for job title, industry, country, summary, and company name;
- preserves invalid duplicate values according to the existing tri-state contract;
- keeps source layout metadata and unmapped/invalid source values private in `raw_payload`;
- leaves PostgreSQL as the source of truth and keeps Elasticsearch rebuild explicit.

The sanitized legacy mapping includes `industry 7 -> canonical industry`, `job_title 8`,
`summary 41`, `skills 45`, `countries 48`, `experience 50`, and `education 51`. Canonical header
positions are documented in `docs/dataset.md` without printing source values or identities.

## Verification

- Focused importer tests: 38 passed.
- Corrected import: 283 accepted rows, 35 duplicate rows, 248 unique profiles, 53 width
  quarantines, and no ambiguous exact-width rows.
- Second import: 248 unchanged profiles, 1,775 unchanged experiences, 707 unchanged education rows,
  and zero creates, updates, or deletes.
- PostgreSQL: 248 profiles, 1,775 experiences, and 707 education rows.
- Elasticsearch rebuild 1: 248 attempted, 248 indexed, 0 failed, 0 unprocessed.
- Elasticsearch rebuild 2: 248 attempted, 248 indexed, 0 failed, 0 unprocessed.
- PostgreSQL and Elasticsearch counts and sanitized document-ID sets matched.
- Match-all returned 248 hits. Country/industry/job-title facet artifact counts were zero, and all
  indexed summaries were scalar strings.
- PostgreSQL semantic anomaly counters after correction were zero for job-title size/date/salary,
  country date/salary/structured values, structured industries, structured summaries, and company
  size signatures.

The raw dataset remains local and untracked. A private PostgreSQL backup was created before the
corrective reimport. The frontend implementation was not modified.
