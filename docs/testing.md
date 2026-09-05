# Testing and verification

Commands below assume Docker Compose is running and should be executed from the repository root.

## Focused backend checks

Run the health tests for the Day 1 readiness behavior:

```bash
docker compose run --rm backend pytest tests/test_health.py
```

Run the model tests when changing the profile model foundation:

```bash
docker compose run --rm backend pytest tests/test_models.py
```

Run Ruff on changed backend files:

```bash
docker compose run --rm backend ruff check apps/search/views.py tests/test_health.py
```

Run Django system and migration consistency checks:

```bash
docker compose run --rm backend python manage.py check
docker compose run --rm backend python manage.py makemigrations --check --dry-run
```

## Frontend checks

```bash
docker compose run --rm frontend npm test -- --run
docker compose run --rm frontend npm run lint
docker compose run --rm frontend npm run typecheck
docker compose run --rm frontend npm run build
```

The explicit type-check uses the repository's TypeScript project references with `tsc -b`.

## Compose and health checks

Validate the Compose file without starting services:

```bash
docker compose config -q
```

After starting the services and applying migrations, inspect service health and endpoints:

```bash
docker compose ps
curl --fail http://localhost:8000/health/live/
curl --fail http://localhost:8000/health/ready/
```

## Focused versus complete milestone verification

Focused checks exercise the smallest changed surface, such as the health tests, the changed Ruff
files, and the explicit frontend checks. The complete Day 1 milestone suite is broader:

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
