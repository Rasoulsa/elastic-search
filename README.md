# LinkedIn Profile Search

A small LinkedIn profile search technical assignment. PostgreSQL is the canonical source of truth.
Elasticsearch contains a derived, explicitly rebuildable profile index.

## Stack

- Django 5.2 and Django REST Framework
- PostgreSQL 16 and Elasticsearch 8
- React 19, TypeScript, Vite, React Router, and TanStack Query
- pytest, Ruff, Vitest, React Testing Library, and ESLint

The Day 2 backend includes JWT authentication, API documentation, dataset import, Elasticsearch
index lifecycle, authenticated profile search, and PostgreSQL profile detail. The Day 3 frontend
includes authentication, URL-driven profile search and facets, pagination, and profile detail.

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
- `GET /api/v1/profiles/search/` for authenticated Elasticsearch profile search and facets
- `GET /api/v1/profiles/{id}/` for authenticated PostgreSQL-backed profile detail
- `GET /api/schema/` and `GET /api/docs/` for the public OpenAPI schema and Swagger UI

Set `VITE_API_BASE_URL` to the backend origin used by the browser. It defaults to
`http://localhost:8000` in the example and Compose configuration. The frontend routes are `/login`,
`/register`, protected `/search`, and protected `/profiles/:profileId`. See
[`docs/frontend-auth.md`](docs/frontend-auth.md) for the client authentication lifecycle and token
storage policy, and [`docs/frontend-search.md`](docs/frontend-search.md) for the browser search
contract.

The readiness endpoint runs a small PostgreSQL connectivity query. It does not check migration
status or Elasticsearch, and it does not expose database exception details.

Backend startup, migrations, profile imports, authentication, profile detail, and the normal backend
test suite do not require a live Elasticsearch service. Explicit index commands and profile search
require Elasticsearch. Search returns a controlled `503` when it or the index is unavailable;
profile detail remains available from PostgreSQL.

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
The importer detects the supplied header-aligned and named legacy/reordered 77-value layouts using
structural signatures before it parses, normalizes, consolidates duplicate aliases, and writes one
diff-aware import plan per profile to PostgreSQL. Width-only validation is insufficient for this
dataset; malformed-width and ambiguous rows are quarantined with sanitized reason codes. Semantic
boundaries prevent shifted lists, dates, salary ranges, and company-size values from entering scalar
profile fields. A repeated unchanged import produces zero profile/child creates, updates, or deletes
while preserving profile, child, and skill-link primary keys. Rebuild Elasticsearch explicitly with
`make rebuild-index` after a corrected import. Profiles migration `0003` is the latest schema
migration.

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

## Profile API

Both profile endpoints require `Authorization: Bearer <access-token>`. Search supports optional
`q`, repeatable `skill`, `job_title`, `industry`, `country`, and `company` filters, plus `page` and
`page_size`. Repeated values in one filter are ORed; filter categories are ANDed. Exact filters use
the committed normalized keyword fields. The default page size is 20, the maximum is 100, and page
requests cannot cross Elasticsearch's 10,000-result window. Each search response includes up to 20
buckets for skills, job titles, industries, countries, and companies.

Search results are translated from an explicit source allowlist and never expose Elasticsearch
metadata or raw responses. Profile detail is read from PostgreSQL with prefetched skills,
experiences, and education; it excludes `raw_payload`, timestamps, and importer ordering fields.
See [`docs/api.md`](docs/api.md) for request and response examples.

## Data safety

Keep the raw profile dataset outside Git. The local `data/` directory is mounted read-only at
`/data` in the backend container and is ignored by Git. Do not copy raw profile data into tracked
source directories.
