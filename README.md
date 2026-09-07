# LinkedIn Profile Search

A small LinkedIn profile search technical assignment. PostgreSQL is the canonical source of truth.
Elasticsearch contains a derived, explicitly rebuildable profile index.

## Stack

- Django 5.2 and Django REST Framework
- PostgreSQL 16 and Elasticsearch 8
- React 19, TypeScript, Vite, React Router, and TanStack Query
- pytest, Ruff, Vitest, React Testing Library, and ESLint

JWT authentication, API documentation, dataset import, and the Elasticsearch index lifecycle are
implemented. The search HTTP API and complete profile search UI remain intentionally deferred.

## Run locally

Docker and Docker Compose are the only prerequisites for the container workflow.

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(64))"
# Replace the DJANGO_SECRET_KEY placeholder in .env with the generated value.
make setup
docker compose up -d
make migrate
curl http://localhost:8000/health/live/
curl http://localhost:8000/health/ready/
```

The key command prints a local non-production key. Replace the clearly marked placeholder in `.env`
before running any Docker Compose command; never commit `.env` or a real key. `docker compose up -d`
starts the services in the background; use `docker compose up` or
`docker compose logs -f` when foreground logs are useful. Apply migrations after the services are
running, then verify both health endpoints.

The frontend is available at `http://localhost:5173`; the backend is available at
`http://localhost:8000`. The backend exposes:

- `GET /health/live/` for process liveness
- `GET /health/ready/` for PostgreSQL connectivity only
- `POST /api/v1/auth/register/`, `POST /api/v1/auth/token/`, and
  `POST /api/v1/auth/token/refresh/` for JWT authentication
- `GET /api/v1/auth/me/` for the authenticated current user
- `GET /api/schema/` and `GET /api/docs/` for the public OpenAPI schema and Swagger UI

The readiness endpoint runs a small PostgreSQL connectivity query. It does not check migration
status or Elasticsearch, and it does not expose database exception details.

Backend startup, migrations, profile imports, authentication, and ordinary backend tests require
PostgreSQL but do not require Elasticsearch. Explicit index creation and rebuild commands require
Elasticsearch; future search requests will require it as well.

Use `make down` to stop the services. Named volumes preserve PostgreSQL and Elasticsearch data.

## Development commands

```bash
make migrate
make create-index
make rebuild-index
make test
make lint
docker compose run --rm frontend npm run typecheck
docker compose run --rm frontend npm run build
```

Import the mounted local dataset with:

```bash
make import
```

This runs `python manage.py import_profiles --path /data/profiles.txt` in the backend container.
The importer parses, normalizes, consolidates duplicate aliases, and then writes one diff-aware
import plan per profile to PostgreSQL. A repeated unchanged import produces zero profile/child
creates, updates, or deletes while preserving profile, child, and skill-link primary keys. Profiles
migration `0003` is the latest schema migration.

Create the empty versioned Elasticsearch index or rebuild it completely from PostgreSQL with:

```bash
make create-index
make rebuild-index
```

These targets run `create_profile_index` and `rebuild_profile_index` respectively. The index defaults
to `linkedin_profiles_v1`. A rebuild deletes and recreates the index, bulk-indexes profile batches
of 1 to 1000 documents (default 500) with stable PostgreSQL-derived document IDs, and refreshes once
after complete success. See [`docs/search-index.md`](docs/search-index.md) for the mapping,
projection rules, counters, and destructive-rebuild failure tradeoff.

For checks outside Docker, install `backend/requirements.txt`, run backend commands from `backend/`,
and use `npm install` in `frontend/`. The `.env.example` values use Docker Compose service
hostnames (`db` and `elasticsearch`). Override them with local-host values such as
`POSTGRES_HOST=localhost` and `ELASTICSEARCH_URL=http://localhost:9200` when running the backend
outside Docker. `ELASTICSEARCH_REQUEST_TIMEOUT` defaults to 10 seconds and `ELASTICSEARCH_INDEX`
defaults to `linkedin_profiles_v1`. `CORS_ALLOWED_ORIGINS` defaults to the local Vite origin
`http://localhost:5173` and accepts a comma-separated allowlist.

## Data safety

Keep the raw profile dataset outside Git. The local `data/` directory is mounted read-only at
`/data` in the backend container and is ignored by Git. Do not copy raw profile data into tracked
source directories.
