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

Run the mounted private dataset twice for operational verification. The importer prints counts and
row-range reason codes only; it never prints source records or profile values:

```bash
make migrate
make import
make import
```

Do not encode the private dataset's observed counts as automated test expectations. Synthetic tests
cover parsing, normalization, duplicate consolidation, identity conflict handling, tri-state scalar
and collection updates, skills policy, rollback behavior, and database-change counters.

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
