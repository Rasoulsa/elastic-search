# Day 3: Authenticated Search UI

## Verification

- Date: 2026-09-07
- Branch: `feat/authenticated-search-ui`
- Scope: frontend authentication, URL-driven profile search and facets, pagination,
  PostgreSQL-backed profile detail, documentation, and Day 3 verification.

All acceptance evidence is sanitized. Profile values, dataset content, credentials, JWTs, raw
payloads, and search-engine responses are intentionally omitted.

## Implemented scope

- Protected `/search` and `/profiles/:profileId` routes within the Phase 3A application shell.
- Explicit-submit search state with deterministic, shareable URL parameters and repeated filters.
- Initial match-all browsing, all five facet groups, selected-value preservation, active filters,
  exact result counts, result cards, and bounded pagination.
- Runtime validation for search, facet, result, detail, experience, and education payloads.
- Search pagination arithmetic and request/response consistency validation, safe out-of-range page
  correction, and a compact adjusting state before replace navigation.
- TanStack Query cancellation, public normalized query keys, bounded retry, manual retry, and
  existing logout/session-expiry integration.
- Superseded-request protection tests, exact profile API URL and signal tests, authenticated search
  and detail cache removal tests, detail retry-boundary tests, and bounded Unicode deduplication.
- PostgreSQL-backed profile detail with safe external URL handling and validated local return
  navigation.
- Responsive one/two-column layouts, semantic form groups, status and alert regions, pagination
  announcements, focus management, and reduced-motion handling.

## Automated results

- Focused URL, API validation, search-page, profile-detail, and destination tests: passed.
- Existing Phase 3A authentication, client, token-store, and destination tests: passed.
- Complete frontend suite, run twice: 8 files and 169 tests passed on each run.
- ESLint: passed.
- TypeScript project type-check: passed.
- Production Vite build: passed.
- Docker Compose configuration validation: passed.
- Git whitespace validation: passed.

## Sanitized live evidence

The healthy local Compose stack was exercised through authenticated application endpoints using a
temporary synthetic reviewer account, which was removed after verification:

- Initial match-all search returned `200`, the documented top-level shape, a non-negative count,
  and all five facet arrays.
- Keyword, skill, job-title, combined, and filter-only requests returned `200`.
- A no-match query returned `200` with a zero count.
- A later result page returned `200` when applicable.
- PostgreSQL detail returned `200` with exactly the documented public top-level fields.
- An unauthenticated search returned `401`.
- With Elasticsearch stopped, search returned the stable `503` code while detail remained `200`.
- After Elasticsearch became healthy again, search returned `200` with the documented shape.

The final human browser acceptance completed after the live integration correction. At desktop,
approximately 768px, and approximately 375px widths, registration, login, protected-route
authentication, and logout succeeded. The match-all view rendered the corrected 247-profile result
count with meaningful corrected facets and result cards; simultaneous filters, URL persistence,
pagination, reload, Back/Forward navigation, detail and return navigation, and Elasticsearch outage
and recovery all behaved as documented. No horizontal overflow or console errors were observed.

## Accepted limitations and remaining risk

- Facet choices are limited to the backend's top 20 buckets for the applied search.
- Search is explicit-submit and intentionally has no autocomplete, live debounce, fuzzy matching,
  semantic search, or saved searches.
- ISO dates are displayed without locale formatting.
- The final human visual pass covered desktop, approximately 768px, and approximately 375px widths.
