# Day 3: Dataset alignment remediation

## Discovery

- Date: 2026-09-07 to 2026-09-08
- Branch: `feat/authenticated-search-ui`
- Scope: bounded backend importer and projection correction discovered through human browser
  acceptance.

The browser first showed company-size values as titles, dates and salary ranges as countries,
serialized collections as industries/summaries, and countries as skills. A first correction mapped
ten observed collection-block starts as complete row permutations. A second browser pass still showed
phone/numeric industries, salary/company-size countries, numeric locations, and displaced card data.
No frontend filtering was added.

## Second root cause

A clean isolated import reproduced the structural mapping cases without requiring the development
database. The first correction had correctly found the structured collection blocks, but rows with
the same block start do not share one safe scalar order. It therefore wrote shifted scalars under
canonical raw-payload keys. Elasticsearch then trusted those keys with null/text normalization only.
At this historical pre-live-verification stage, the development-database comparison was still
outstanding because PostgreSQL was unavailable.

The structural audit also found one exact-width body record identical to the 77-column header. The
old importer accepted it as a profile, explaining why the previously reported count was 248 rather
than 247 real profiles.

## Corrective implementation

The importer now:

- detects all ten layouts by weighted collection signatures and nested experience/education keys;
- maps the stable identity prefix, summary, and structured block by position;
- obtains current title/company/size/industry/location from explicit experience keys and profile
  location/country from explicit list fields;
- preserves every original source value privately under positional `_source_values` without assigning
  ambiguous scalar positions canonical names;
- records strict importer-owned `_importer` provenance with mapping version `canonical-v2`;
- applies shared structural scalar validation before persistence;
- quarantines repeated headers and removes only a prior repeated-header profile with proven broken
  provenance;
- clears invalid scalars only for known broken mapping provenance while preserving ordinary/manual
  valid values on invalid updates;
- removes only newly unreferenced skills that were linked through known broken provenance.

Search and detail projections trust only canonical provenance with a field-specific parsed path.
Value equality alone is insufficient: industry cannot borrow company name, company cannot borrow
industry, and title/location/country/summary cannot borrow unrelated paths. Unknown or cross-wired
fields fail closed. Experience-indexed current fields must reference the exact experience selected by
the shared policy and recorded in importer metadata. PostgreSQL remains authoritative; Elasticsearch
mapping, querying, authentication, and frontend behavior are unchanged.

## Sanitized verification

The clean corrected import observed 336 logical records, 283 exact-width records, 53 malformed-width
records, one repeated header, 282 accepted rows, 35 duplicates, and 247 unique real profiles. Layout
counts were 35, 28, 13, 19, 21, 24, 34, 76, 13, and 19 in documented layout order. It created 2,348
skills, 7,078 profile-skill links, 1,775 experiences, and 707 education rows. The second isolated run
reported 247 unchanged profiles and zero creates, updates, or deletes.

Final live `canonical-v2` verification recorded 247 unique profiles on the first PostgreSQL import:
230 profiles were updated to the latest provenance contract, 17 were unchanged, and zero were
created or deleted. One repeated header and 53 malformed-width records were quarantined; unknown
and ambiguous layout counts were both zero. Three summary-boundary warnings caused invalid summaries
to be omitted safely rather than mapped from unrelated fields.

The second import left all 247 profiles unchanged, with zero creates, updates, or deletes; 1,775
experiences and 707 education records were unchanged. Both explicit Elasticsearch rebuilds reported
`attempted=247 indexed=247 failed=0 unprocessed=0`, and the index count remained 247.

Final human browser acceptance completed after the live PostgreSQL and Elasticsearch verification.
At desktop, approximately 768px, and approximately 375px widths, authenticated search and detail
rendered the corrected 247-profile state with meaningful facets and results. Simultaneous filters,
URL persistence, pagination, reload, Back/Forward navigation, detail and return navigation,
Elasticsearch outage and recovery, and logout all behaved as documented. No horizontal overflow or
console errors were observed; earlier screenshots exposed pre-remediation corruption and are not
treated as evidence for this final state.

No private profile values, identities, source rows, raw documents, or facet values are included in
this journal.
