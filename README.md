# LinkedIn Profile Search

A small Day 1 platform foundation for a LinkedIn profile search technical assignment. PostgreSQL is
the planned canonical source of truth. Elasticsearch is running as infrastructure, but it is not
integrated with Django yet.

## Stack

- Django 5.2 and Django REST Framework
- PostgreSQL 16 and Elasticsearch 8
- React 19, TypeScript, Vite, React Router, and TanStack Query
- pytest, Ruff, Vitest, React Testing Library, and ESLint

Authentication, dataset import, indexing, the search API, and the complete profile search UI are
intentionally deferred.

## Run locally

Docker and Docker Compose are the only prerequisites for the container workflow.

```bash
cp .env.example .env
make setup
docker compose up -d
make migrate
curl http://localhost:8000/health/live/
curl http://localhost:8000/health/ready/
```

`docker compose up -d` starts the services in the background; use `docker compose up` or
`docker compose logs -f` when foreground logs are useful. Apply migrations after the services are
running, then verify both health endpoints.

The frontend is available at `http://localhost:5173`; the backend is available at
`http://localhost:8000`. The backend exposes:

- `GET /health/live/` for process liveness
- `GET /health/ready/` for PostgreSQL connectivity only

The readiness endpoint runs a small PostgreSQL connectivity query. It does not check migration
status or Elasticsearch, and it does not expose database exception details.

Use `make down` to stop the services. Named volumes preserve PostgreSQL and Elasticsearch data.

## Development commands

```bash
make migrate
make test
make lint
docker compose run --rm frontend npm run typecheck
docker compose run --rm frontend npm run build
```

Day 2 will add explicit `import_profiles` and `rebuild_profile_index` Django management commands.
They are not implemented or runnable in Day 1, so no import or reindex command is included here.

For checks outside Docker, install `backend/requirements.txt`, run backend commands from `backend/`,
and use `npm install` in `frontend/`. The `.env.example` values use Docker Compose service
hostnames (`db` and `elasticsearch`). Override them with local-host values such as
`POSTGRES_HOST=localhost` when running the backend outside Docker.

## Data safety

Keep the raw profile dataset outside the repository. Local `data/`, `dataset/`, and `datasets/`
directories and line-delimited JSON files are ignored by Git. Pass an absolute local path to the
future Day 2 import command; do not copy raw profile data into tracked source directories.
