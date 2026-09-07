# Dataset import

The local profile file is a private, read-only runtime input. It is mounted from `./data` on the
host to `/data` in the backend container and is not committed to Git.

## Contract

The importer accepts the exact 77-column CSV header and reads UTF-8 CSV with comma delimiters,
double quotes, and multiline quoted fields. It resolves columns by the fixed header names. A
non-77-column logical record is skipped as `STRUCTURAL_WIDTH`; it is never repaired or reconstructed.

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

The importer never deletes global `Skill` rows merely because a profile relationship is cleared.

The command reports logical and physical row ranges with reason codes and aggregate counters only. It
does not print private records or profile values and does not create a private-record quarantine
file.

The observed private baseline is approximately 336 logical records, 283 exact-width accepted
profile rows, 53 malformed-width records, 35 duplicate rows, and 248 unique importable profiles.
These are operational expectations, not automated-test assertions.

## Reported counters

Row counters describe source processing and consolidation:

- `logical_records`: CSV logical records read after the header, including malformed or rejected
  records.
- `exact_width_records`: records with exactly the required 77 columns.
- `malformed_width_records`: records rejected because their column count is wrong.
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

Database counters represent persisted state, not source items:

- `profiles_created`, `profiles_updated`, and `profiles_unchanged`: final consolidated profile plans
  that respectively insert a row, change a row, or leave its persisted scalar and raw-payload state
  unchanged.
- `skills_created`: new global `Skill` rows inserted while applying a changed relationship set.
- `skills_reused`: existing global `Skill` rows selected while applying a changed relationship set.
  It is a reuse counter, not a skill-row update counter. When the relationship set already matches,
  both skill counters remain zero and the through rows remain untouched.
- `experiences_created`, `experiences_updated`, `experiences_unchanged`, and
  `experiences_deleted`: actual child rows inserted, changed in place, retained without changes, or
  deleted.
- `education_created`, `education_updated`, `education_unchanged`, and `education_deleted`: actual
  education rows inserted, changed in place, retained without changes, or deleted.

Migration `0002` safely upgrades the initial schema by converting legacy `profile_url=""` values to
NULL before applying nullable unique aliases. It also backfills zero-based `source_order` separately
per profile in ascending historical primary-key order before adding the position constraints.
Migration `0003` expands `public_identifier` to 600 characters and is the latest profiles migration.
Raw data remains private and is never written to tracked files or printed by the command.
