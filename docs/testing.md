# Testing and verification

Commands below assume Docker Compose is running and should be executed from the repository root.

## Focused backend checks

Run the health tests for the readiness behavior:

```bash
docker compose run --rm backend pytest tests/test_health.py
```

Run the focused authentication, OpenAPI, CORS, and secret-configuration tests:

```bash
docker compose build backend
DJANGO_SECRET_KEY="$(python -c "import secrets; print(secrets.token_urlsafe(64))")" docker compose run --rm backend pytest tests/test_auth.py tests/test_security_config.py
```

Run the Day 2 model, importer, and migration tests when changing profile ingestion:

```bash
docker compose run --rm backend pytest tests/test_models.py
docker compose run --rm backend pytest tests/test_import_profiles.py
docker compose run --rm backend pytest tests/test_profile_migrations.py
```

Run the mapping, projection, gateway, and lifecycle-command tests. They do not contact a live
Elasticsearch service, and the backend Compose service does not start Elasticsearch as a dependency:

```bash
docker compose run --rm backend pytest tests/test_search_index.py tests/test_search_documents.py tests/test_search_gateway.py tests/test_search_commands.py
```

These tests mock only the Elasticsearch gateway or bulk-helper boundary. Django models, querysets,
prefetching, projection, batching, stale-document replacement, command output, and failure exits run
normally against the test database.

Run the focused Day 2 search API slices:

```bash
docker compose run --rm backend pytest tests/test_search_query.py
docker compose run --rm backend pytest tests/test_profile_search_api.py
docker compose run --rm backend pytest tests/test_profile_detail_api.py
```

The pure query-builder tests cover match-all and keyword queries, every exact filter, repeated OR
values, cross-category AND behavior, Elasticsearch-owned exact normalization, boosts, deterministic
sorting, offsets, bounded facets, and the 10,000-result window. API tests issue real JWT access tokens
and mock the Elasticsearch gateway only. They cover scalar repetition rejection, exact total-page
arithmetic, no results, facets, metadata exclusion, controlled unavailable and missing-index
responses, malformed gateway responses, safe optional-field defaults, and client closure. Detail tests
use the real serializer and PostgreSQL test database, including nested data, exclusions, 404,
Elasticsearch independence, and a bounded query count.

To verify dependency isolation, stop Elasticsearch and run an ordinary backend command without
`--no-deps`. PostgreSQL may start, but Elasticsearch must remain stopped:

```bash
docker compose stop elasticsearch
docker compose run --rm backend python manage.py check
docker compose ps
```

Run Ruff and format verification on the backend:

```bash
docker compose run --rm backend ruff check .
docker compose run --rm backend ruff format --check .
```

Run Django system and migration consistency checks:

```bash
docker compose run --rm backend python manage.py check
docker compose run --rm backend python manage.py makemigrations --check --dry-run
docker compose config -q
docker compose run --rm backend python manage.py spectacular --validate
```

Back up the PostgreSQL database or volume before correcting local imported state. Do not reset or
delete the named volumes for this check. Run the mounted private dataset twice for operational
verification. The importer prints counts and row-range reason codes only; it never prints source
records or profile values:

```bash
make migrate
make import
make import
make rebuild-index
make rebuild-index
```

The second Day 3 mapping investigation first imported into a clean isolated SQLite database. Corrected
verification observed 336 logical records, 283 exact-width records, 53 `STRUCTURAL_WIDTH`
quarantines, one `STRUCTURAL_REPEATED_HEADER`, 282 accepted rows, 35 duplicates, and 247 unique real
profiles. The final isolated second import reported 247 unchanged profiles, 1,775 unchanged
experiences, 707 unchanged education rows, and zero creates, updates, or deletes. Do not encode these
private dataset counts as automated test expectations.

Final live `canonical-v2` verification completed for PostgreSQL and Elasticsearch. The first import
found 247 unique profiles: 230 were updated to the latest provenance contract, 17 were unchanged,
and zero were created or deleted. It quarantined one repeated header and 53 malformed-width records;
unknown and ambiguous layout counts were both zero. Three summary-boundary warnings caused invalid
summaries to be omitted safely rather than mapped from unrelated fields.

The second import left all 247 profiles unchanged, with zero creates, updates, or deletes; all 1,775
experiences and 707 education records were unchanged. Both explicit Elasticsearch rebuilds reported
`attempted=247 indexed=247 failed=0 unprocessed=0`, and the index count remained 247. Final human
browser acceptance then completed at desktop, approximately 768px, and approximately 375px widths;
authenticated rendering, corrected facets/results, simultaneous filters, URL persistence, pagination,
reload, Back/Forward, detail/return navigation, Elasticsearch outage/recovery, logout, no horizontal
overflow, and no console errors were confirmed. Older screenshots that exposed corruption do not
satisfy that final check.

Synthetic tests cover all ten layout contracts, scalar extraction from keyed collections, canonical
raw-payload provenance, repeated-header quarantine, malformed/ambiguous layouts, semantic anomaly
classes, normal tri-state preservation versus provenance-aware cleanup, bounded orphan-skill cleanup,
full persisted-state idempotency, stable timestamps/IDs, projection fallback rejection, privacy-safe
output, rollback behavior, and truthful counters.

Provenance tests independently enumerate each canonical field's permitted parsed path. Equality is
necessary but cannot authorize a path from another field. Tests reject cross-wired paths, malformed
indices and traversal-like syntax, wrong destination types, unknown fields, and any current-experience
index that disagrees with importer metadata or the shared selection policy. These failures omit the
optional projection/detail field and do not expose raw values, provenance metadata, or exception
details.

This defect was discovered during Day 3 browser acceptance. The safe sequence is backup, corrected
PostgreSQL import, second-run idempotency check, two explicit Elasticsearch rebuilds, sanitized
count/ID/facet checks, and then browser acceptance again.

For manual index verification, compare the canonical and derived counts without printing documents:

```bash
docker compose exec backend python manage.py shell -c "from apps.profiles.models import Profile; print(Profile.objects.count())"
curl --fail http://localhost:9200/linkedin_profiles_v1/_count
curl --fail http://localhost:9200/linkedin_profiles_v1/_mapping
```

Run `make rebuild-index` twice and confirm both runs report the current PostgreSQL profile count with
`failed=0 unprocessed=0`, the count is unchanged, and sanitized document-ID sets match PostgreSQL. For
structural inspection, request only aggregate/facet data or an explicit safe `_source` allowlist;
do not print complete documents, raw payloads, contacts, summaries, or profile identities from the
private dataset.

The migration suite uses historical models from Django's migration app registry. It exercises a
fresh profiles schema from zero through the latest migration (`0003`) and upgrades an initial `0001`
database through `0003`. The upgrade assertions cover row and primary-key preservation, empty-URL
normalization, deterministic zero-based `source_order` backfill by historical primary key, active
source-order and nullable-alias uniqueness constraints, and the 600-character public identifier.
Each migration test restores the latest schema during cleanup.

The complete strong-idempotency test imports duplicate synthetic source rows with aliases, skills,
experience, education, raw payload, and a partial-invalid field. It snapshots every persisted profile,
skill, through-table, experience, and education field plus aggregate counts. The second import must
match exactly, including timestamps and every primary key, and all create/update/delete counters must
remain zero.

## Frontend checks

```bash
docker compose run --rm frontend npm test -- --run
docker compose run --rm frontend npm run lint
docker compose run --rm frontend npm run typecheck
docker compose run --rm frontend npm run build
```

The explicit type-check uses the repository's TypeScript project references with `tsc -b`.

The focused authentication suite can be run with:

```bash
docker compose run --rm frontend npm test -- --run \
  src/api/client.test.ts src/authentication.test.tsx
```

These tests mock `fetch` at the network boundary while retaining the real router, authentication
provider, TanStack Query client, and browser `sessionStorage`. They cover route guards and loading,
login and registration behavior, token placement, startup refresh plus `/me/`, protected request
headers, one-refresh/one-retry behavior, shared concurrent refresh, safe malformed errors, logout
cache clearing, and late refresh or `/me/` responses after logout.

The focused frontend search suites can be run with:

```bash
docker compose run --rm frontend npm test -- --run \
  src/search/searchState.test.ts \
  src/api/profiles.test.ts \
  src/pages/SearchPage.test.tsx \
  src/pages/ProfileDetailPage.test.tsx
```

The URL utility tests cover deterministic ordering, repeated filters, blank removal, the bounded
Unicode comparison policy, unknown-parameter removal, pagination normalization, criteria/page
transitions, and token-free query keys. API tests exercise runtime validation for all important
search, facet, result, detail, experience, and education structures, including pagination arithmetic,
request/response pagination consistency, legitimate out-of-range responses, exact repeated-parameter
URLs, profile IDs, abort-signal forwarding, and a sanitized live-shaped match-all response with blank
facet values.

Page integration tests retain the real router, authentication provider and guards, QueryClient, and
session lifecycle. They mock only the typed profile API boundary and the narrow startup authentication
requests. Search coverage includes initial match-all, restored URLs, explicit keyword/filter
submission, all filter categories, repeated skills and job titles, clear, navigation restoration,
facets and counts, selected values absent from facets, safe result rendering, count pluralization,
loading, empty/error/retry states, pagination, simultaneous same-category and cross-category
selection, preserved return URLs, and token-free cache keys.
Detail coverage includes loading, public and nested rendering, `404`, network/server/malformed errors,
bounded retry boundaries, safe and unsafe external URLs, return validation, malformed IDs, abort
handling, and exclusion of internal fields. Authentication coverage verifies that logout removes
actual search and profile-detail query entries and does not expose them to a later session.

Search page coverage also verifies delayed superseded requests, per-request abort signals, safe
out-of-range correction with criteria preservation, no invalid page flash, and correction-loop
termination.

For sanitized browser verification, use a synthetic local account and inspect only route changes,
status messages, and the presence or absence of storage keys. Do not copy token values into notes,
URLs, console output, screenshots, or documentation. Verify that reload uses the refresh token to
recover `/me/`, and that closing the tab or browser session removes the `sessionStorage` session.

## Compose and health checks

Validate the Compose file without starting services. Compose requires an explicitly supplied
non-empty key even for this configuration-only check:

```bash
DJANGO_SECRET_KEY="$(python -c "import secrets; print(secrets.token_urlsafe(64))")" docker compose config -q
```

After starting the services and applying migrations, inspect service health and endpoints:

```bash
docker compose ps
curl --fail http://localhost:8000/health/live/
curl --fail http://localhost:8000/health/ready/
```

The authentication tests cover registration validation and password hashing, JWT issue/refresh and
rejection behavior, current-user protection, public health and documentation routes, CORS origins,
and the generated bearer security scheme. They use synthetic users only and do not test Simple JWT
internals beyond the API contract.

## Sanitized live search checks

After migrations, a dataset import, and `make rebuild-index`, create a dedicated local reviewer user
and obtain an access token. Do not paste or print the token, profile values, summaries, contacts, raw
payloads, or complete Elasticsearch responses. Record only status codes, counts, top-level response
keys, facet names, and boolean assertions.

Exercise unauthenticated search, authenticated match-all pagination, keyword-only search, skill-only
and job-title-only filters, repeated scalar rejection, repeated skill acceptance, combined filters,
empty results, facets, and a PostgreSQL profile detail. Record only whether the exact hit relation is
`eq`; do not print the response body.
Then stop Elasticsearch and verify search returns the application-owned 503 while the same detail
request still returns 200:

```bash
docker compose stop elasticsearch
curl --output /dev/null --silent --write-out "%{http_code}\n" \
  "http://localhost:8000/api/v1/profiles/search/" \
  --header "Authorization: Bearer ${ACCESS_TOKEN}"
curl --output /dev/null --silent --write-out "%{http_code}\n" \
  "http://localhost:8000/api/v1/profiles/${PROFILE_ID}/" \
  --header "Authorization: Bearer ${ACCESS_TOKEN}"
docker compose start elasticsearch
```

Wait for Elasticsearch health after restart, then repeat authenticated search and confirm recovery.
The detailed command sequence and response-shape assertions should be run without shell tracing.

## Focused versus complete milestone verification

Focused checks exercise the smallest changed surface, such as importer, migration, or health tests.
The complete current milestone suite is broader:

```bash
make test
make lint
```

It includes all backend pytest tests and all frontend tests, plus the repository-wide backend Ruff
check and frontend lint. Django checks, migration consistency, Compose validation, and live service
health checks remain explicit commands because they validate runtime and configuration concerns.

## Troubleshooting

- If the backend cannot resolve `db` or `elasticsearch`, run it through Compose or override the
  Docker service hostnames in `.env` when running it on the host.
- If a port is already in use, stop the conflicting service or change the published ports in a
  local Compose override.
- If dependencies are stale, rebuild the relevant service image with `docker compose build` and
  rerun the command.
- If database state is inconsistent during local development, inspect `docker compose logs db` and
  apply `make migrate`. Avoid deleting named volumes unless the local data can be discarded.
- If health checks fail, inspect `docker compose ps` and the backend/database logs. Readiness only
  confirms PostgreSQL connectivity; it does not confirm migrations or Elasticsearch integration.
- If a rebuild fails after deleting the old index, fix Elasticsearch connectivity or the reported
  bulk failure and rerun `make rebuild-index`. The assignment-sized replacement strategy does not
  preserve the prior index during rebuilding. Recreation failure leaves the index missing; bulk
  failure can leave the new index empty or partially populated.
