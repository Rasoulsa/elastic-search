# Dataset import

The local profile file is a private, read-only runtime input. It is mounted from `./data` on the
host to `/data` in the backend container and is not committed to Git.

## Contract

The importer accepts the exact 77-column CSV header and reads UTF-8 CSV with comma delimiters,
double quotes, and multiline quoted fields. The header is canonical vocabulary, not positional
proof. The supplied exact-width rows have a stable identity prefix and one of ten deterministic
structured-collection blocks, while scalar positions outside those blocks vary incompatibly even
within the same block-start group. The first alignment correction fixed the collection mappings but
incorrectly treated each block start as a complete scalar layout.

Rows are recognized by structural signatures, never by profile identity or content-specific
dictionaries. The current private file uses these recognized layouts:

- `reordered-block-{b}` for collection-block starts `b = 25, 28, 39, 40, 41, 44, 45, 46, 48`.
- `legacy-facebook-appended-77`, whose structured collection block starts at position 42.

For every contract, `summary` is at `b - 1`; `phone_numbers`, `skills`, `location_names`,
`countries`, `experience`, and `education` are at `b`, `b + 3`, `b + 4`, `b + 6`, `b + 8`, and
`b + 9`. Current job and company fields are canonicalized from the explicitly keyed primary/first
experience object. Profile location and country use the explicitly named `location_names` and
`countries` lists. The supported layouts do not provide an unambiguous keyed salary source, so no
salary is inferred from positional ranges. Ambiguous scalar positions, including `201-500` and
`70,000-85,000`, are preserved only under `_source_values` and never assigned a canonical field
name.

The relevant sanitized position mapping is:

| Layout | Rows | Summary | Phone | Skills | Location list | Country list | Experience | Education |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `legacy-facebook-appended-77` | 35 | 41 | 42 | 45 | 46 | 48 | 50 | 51 |
| `reordered-block-25` | 28 | 24 | 25 | 28 | 29 | 31 | 33 | 34 |
| `reordered-block-28` | 13 | 27 | 28 | 31 | 32 | 34 | 36 | 37 |
| `reordered-block-39` | 19 | 38 | 39 | 42 | 43 | 45 | 47 | 48 |
| `reordered-block-40` | 21 | 39 | 40 | 43 | 44 | 46 | 48 | 49 |
| `reordered-block-41` | 24 | 40 | 41 | 44 | 45 | 47 | 49 | 50 |
| `reordered-block-44` | 34 | 43 | 44 | 47 | 48 | 50 | 52 | 53 |
| `reordered-block-45` | 76 | 44 | 45 | 48 | 49 | 51 | 53 | 54 |
| `reordered-block-46` | 13 | 45 | 46 | 49 | 50 | 52 | 54 | 55 |
| `reordered-block-48` | 19 | 47 | 48 | 51 | 52 | 54 | 56 | 57 |

Rows with a known layout are mapped into canonical keys before normalization. Winning structural
scores must be at least 40 and exceed the runner-up by at least 20. Ambiguous exact-width rows are
quarantined as `AMBIGUOUS_LAYOUT`; unsupported or low-confidence exact-width rows are quarantined
as `UNKNOWN_LAYOUT`; repeated headers are `STRUCTURAL_REPEATED_HEADER`; non-77-column logical
records remain `STRUCTURAL_WIDTH`. The original row is private under positional `_source_values`.
Importer-owned version, layout, selected source order, and canonical paths are nested under the
strict `_importer` namespace. API serializers and search projections never expose this storage.

Run it explicitly:

```bash
python manage.py import_profiles --path /data/profiles.txt
```

PostgreSQL owns imported data. Elasticsearch is not written by this command.

## Repeat runs and diagnostics

The importer uses a parse -> normalize -> consolidate -> persist pipeline. Parsing performs no
database writes. Accepted candidates are consolidated in physical source order through all canonical
LinkedIn aliases before one final plan per profile is persisted. Conflicting alias groups are
quarantined without writes. Profile and child updates are diff-aware, so repeated input is strongly
idempotent: unchanged profiles and retained relation rows keep their timestamps and primary keys.

Fields have tri-state behavior: a valid value replaces the earlier value, a valid empty value clears
it, and an invalid value preserves the earlier valid value. A complete valid experience or education
list synchronizes positions and removes stale positions. A partial list updates valid positions while
preserving invalid and unmatched existing positions; an invalid top-level list preserves the complete
collection. Explicit empty lists clear their collection. `education.field_of_study` is the ordered,
deduplicated majors followed by minors, joined with ` | `; degrees use the same separator and
experience locations use `, `. Raw payloads retain source strings for the final merged candidate.

Skills use the same explicit states:

- A blank value or recognized null token (`null`, `none`, `nan`, `n/a`, or `na`, ignoring case and
  surrounding whitespace) is `VALID_EMPTY` and clears the profile's skill relationships.
- An explicit `[]` is also `VALID_EMPTY` and clears the relationships.
- A valid `list[str]` is whitespace-normalized, case-folded, and deduplicated in source order.
- A mixed list retains its valid strings and increments `skipped_skill_items` for invalid items.
- A non-empty list with no valid strings is `INVALID`; on update it preserves existing skill
  relationships.

Ordinary imports never delete global `Skill` rows merely because a relationship is cleared. During
this bounded correction only, unreferenced skill rows that were previously linked to a profile with
known broken-mapping provenance are removed; unrelated manually created skills are preserved.

The command reports logical and physical row ranges with reason codes and aggregate counters only. It
does not print private records or profile values and does not create a private-record quarantine
file.

The second investigation used a fresh isolated SQLite database; the existing development database
was not changed because PostgreSQL was unavailable. Corrected private verification observed 336
logical records, 283 exact-width records, one repeated-header record, 282 accepted rows, 53
malformed-width records, 35 duplicates, and 247 unique real profiles. These are operational results,
not automated-test assertions.

The corrected reimport procedure is:

1. Back up the PostgreSQL database or volume.
2. Run `python manage.py import_profiles --path /data/profiles.txt` twice and require zero profile,
   child, and relation creates/updates/deletes on the second run.
3. Run `python manage.py rebuild_profile_index` twice.
4. Compare sanitized PostgreSQL and Elasticsearch counts and document IDs, then inspect only
   allowlisted facets and structural anomaly counters.

Final live `canonical-v2` verification recorded 247 unique profiles on the first PostgreSQL import:
230 profiles were updated to the latest provenance contract, 17 were unchanged, and zero were
created or deleted. One repeated header and 53 malformed-width records were quarantined; unknown
and ambiguous layout counts were both zero. Three summary-boundary warnings caused invalid summaries
to be omitted safely rather than mapped from unrelated fields. The second import left all 247
profiles unchanged, with zero creates, updates, or deletes; 1,775 experiences and 707 education
records were unchanged. Both Elasticsearch rebuilds reported
`attempted=247 indexed=247 failed=0 unprocessed=0`, and the index count remained 247. Final human
browser acceptance then completed at desktop, approximately 768px, and approximately 375px widths;
authenticated rendering, corrected facets/results, simultaneous filters, URL persistence, pagination,
reload, Back/Forward, detail/return navigation, Elasticsearch outage/recovery, logout, no horizontal
overflow, and no console errors were confirmed.

This defect was discovered during Day 3 browser acceptance. The frontend was rendering shifted
PostgreSQL/Elasticsearch data; the corrective sequence is dataset mapping, PostgreSQL reimport,
idempotency verification, Elasticsearch rebuild, and only then browser acceptance again.

## Reported counters

Row counters describe source processing and consolidation:

- `logical_records`: CSV logical records read after the header, including malformed or rejected
  records.
- `exact_width_records`: records with exactly the required 77 columns.
- `malformed_width_records`: records rejected because their column count is wrong.
- `repeated_header_records`: exact-width body records rejected because they repeat the header.
- `identity_invalid_records`: exact-width records rejected because no valid LinkedIn alias exists.
- `identity_conflict_records`: accepted records quarantined because aliases would join conflicting
  identities, either during consolidation or against existing profiles.
- `display_name_invalid_records`: exact-width records rejected because no valid full, first, or last
  name exists.
- `accepted_profile_rows`: validated source rows entering consolidation.
- `duplicate_rows`: accepted rows beyond the first row in each consolidated identity group.
- `unique_profiles`: distinct persisted profile primary keys affected or confirmed by final plans.

Field-warning counters diagnose accepted and rejected field content without exposing values:

- `invalid_scalar_fields`: per-field counts for invalid scalar or alias values.
- `invalid_skills_fields`: per-field counts for invalid top-level skills values or non-empty skills
  lists with no valid strings.
- `skipped_skill_items`: invalid items discarded from otherwise parseable skills lists.
- `invalid_experience_fields`: per-field counts for invalid experience collections or mapped fields.
- `skipped_experience_items`: invalid experience list positions that could not produce a child row.
- `invalid_education_fields`: per-field counts for invalid education collections or mapped fields.
- `skipped_education_items`: invalid education list positions that could not produce a child row.
- `invalid_dates`: invalid experience or education start/end dates.
- `oversized_fields`: per-field values rejected for exceeding the persisted model limit.
- `detected_layouts`: sanitized counts by explicit source-layout contract.
- `semantic_warnings`: field-boundary warnings for structurally impossible canonical values.

Database counters represent persisted state, not source items:

- `profiles_created`, `profiles_updated`, `profiles_unchanged`, and `profiles_deleted`: final
  consolidated profile outcomes that respectively insert, change, retain, or remove a row. Deletion
  is bounded to a proven repeated-header profile created by the broken mapper.
- `skills_created`: new global `Skill` rows inserted while applying a changed relationship set.
- `skills_reused`: existing global `Skill` rows selected while applying a changed relationship set.
  It is a reuse counter, not a skill-row update counter. When the relationship set already matches,
  both skill counters remain zero and the through rows remain untouched.
- `skills_deleted`: unreferenced rows removed only from the set previously linked through proven
  broken-mapping provenance.
- `experiences_created`, `experiences_updated`, `experiences_unchanged`, and
  `experiences_deleted`: actual child rows inserted, changed in place, retained without changes, or
  deleted.
- `education_created`, `education_updated`, `education_unchanged`, and `education_deleted`: actual
  education rows inserted, changed in place, retained without changes, or deleted.

Semantic boundary validation runs after layout mapping and before persistence. It rejects structured
values, company-size-only ranges, dates, and salary ranges from job titles, industries, countries,
and company names; it rejects numeric-only company names and structured summaries. It does not use
an exhaustive country or title dictionary, so ordinary words remain valid skills or countries.
Invalid values preserve earlier valid duplicate values under the existing tri-state consolidation
contract. Rejected canonical values are not copied into canonical payload keys; the private
positional source-preservation structure remains available for local provenance checks.

Migration `0002` safely upgrades the initial schema by converting legacy `profile_url=""` values to
NULL before applying nullable unique aliases. It also backfills zero-based `source_order` separately
per profile in ascending historical primary-key order before adding the position constraints.
Migration `0003` expands `public_identifier` to 600 characters and is the latest profiles migration.
Raw data remains private and is never written to tracked files or printed by the command.

Confidence evidence for the private file was calculated without printing values or identities. Across
the 282 accepted non-header exact-width rows, winning scores were 67 or 77 and the weakest winning
margin was 34. The thresholds of 40 and 20 therefore retain a structural evidence gap below the
weakest observed genuine layout while still accepting the valid weakest layout. A unique winner below
40 is `UNKNOWN_LAYOUT`; a winner with a margin below 20 is `AMBIGUOUS_LAYOUT`.

The corrected fresh baseline is 247 real profiles, 2,348 linked/global skills, 7,078 profile-skill
links, 1,775 experiences, and 707 education rows. A corrected development database may retain 2,557
global skills because 209 unreferenced legacy rows lack safe ownership provenance; those rows remain
unlinked and are absent from documents, facets, and API responses.
