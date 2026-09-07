# Day 2: Profile Search API

## Verification

- Date: 2026-09-07
- Branch: `feat/profile-search-api`
- Scope: dataset import, JWT authentication, Elasticsearch indexing and lifecycle, authenticated
  profile search, PostgreSQL-backed profile detail, API documentation, and Day 2 verification.

The following is the sanitized acceptance evidence supplied by the developer. Raw command logs,
dataset rows, profile content, credentials, and tokens are intentionally omitted.

## Commands and categories executed

- Docker Compose configuration validation.
- Backend and frontend image builds, service startup, and health checks.
- PostgreSQL migrations and Django migration-state checks.
- Complete backend pytest suite.
- Ruff lint and format checks, Django system checks, and migration-drift checks.
- Frontend Vitest, ESLint, TypeScript, and production-build checks.
- Two consecutive private dataset imports.
- Two consecutive Elasticsearch index rebuilds.
- Sanitized authentication, search, profile-detail, and Elasticsearch-outage API checks.

## Results

- Docker Compose configuration validated successfully.
- Backend and frontend images built successfully.
- PostgreSQL, Elasticsearch, backend, and frontend became healthy.
- All migrations were applied through profiles migration `0003`; Django reported no pending
  migrations.
- The complete backend pytest suite exited successfully.
- Ruff check and format check passed.
- Django system check passed.
- `makemigrations --check --dry-run` reported no changes.
- Frontend Vitest, ESLint, TypeScript, and production build passed.

Two consecutive private dataset imports demonstrated strong repeatability:

- 248 profiles were unchanged on the second import.
- 444 experiences were unchanged on the second import.
- 165 education records were unchanged on the second import.
- Profile and relation create, update, and delete counters were all zero on the second import.

Two consecutive Elasticsearch rebuilds each reported:

```text
attempted=248 indexed=248 failed=0 unprocessed=0
```

PostgreSQL and Elasticsearch counts both remained 248 after rebuilding.

Manual sanitized API checks confirmed:

- Registration, login, and JWT behavior succeeded.
- Unauthorized search returned `401`.
- Authenticated search returned `200`.
- Repeated scalar validation returned `400`.
- Profile detail returned `200`.
- A missing profile returned `404`.
- Search returned `503` while Elasticsearch was unavailable.
- Profile detail remained `200` during the Elasticsearch outage.
- Search recovered after Elasticsearch restarted.

## Accepted limitations

- An explicit index rebuild is required after PostgreSQL data changes.
- Delete-and-recreate rebuilds cause temporary search unavailability.
- Deep pagination beyond the 10,000-result window is rejected.
- React profile-search functionality remains deferred to Day 3.
