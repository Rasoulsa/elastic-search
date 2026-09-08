# CI/CD and container delivery

## CI workflow

`.github/workflows/ci.yml` runs for pull requests and pushes to `main`. It grants only
`contents: read` and cancels superseded runs for the same branch or pull request.

The jobs form this dependency graph:

```text
backend quality/tests ─┐
                       ├─> production Docker builds ─> Compose smoke test
frontend quality/tests ┘
```

The backend job uses Python 3.13, caches `backend/requirements.txt`, runs Ruff, Django system and
migration consistency checks, applies migrations to a PostgreSQL 16 service, and runs the complete
pytest suite. Pytest uses the committed `config.test_settings` SQLite contract, so the suite is
independent of PostgreSQL and live Elasticsearch. The PostgreSQL service verifies normal settings,
migration consistency, and database migrations; it is not presented as the database behind pytest.
HTTP application startup and health verification are performed by the separate Compose smoke job.
No step uses the private dataset.

The frontend job uses Node 22 and the committed `frontend/package-lock.json` cache. It runs
`npm ci`, ESLint, the TypeScript project-reference check, the one-shot Vitest suite, and the Vite
production build. It uses the public synthetic build value
`VITE_API_BASE_URL=http://localhost:8000`; it needs no backend, Elasticsearch, credentials, or
browser service.

The Docker job runs only after both quality/test jobs pass. It builds the backend image and the
default production target of the frontend image with Buildx and never pushes them. The backend and
frontend Dockerfiles exclude environment files, private/raw dataset formats, database backups,
Codex-local files, Git metadata, caches, `node_modules`, and generated frontend output from their
contexts.

The Compose smoke job validates the Compose file, builds and starts PostgreSQL, Elasticsearch, the
backend, and the development frontend with synthetic values, applies migrations, checks the public
backend liveness/readiness endpoints, and checks the frontend root plus the `/login`, `/register`,
`/search`, and `/profiles/1` SPA routes. Its Compose project name includes both
`github.run_id` and `github.run_attempt`; startup, diagnostics, and `always()` cleanup use that
same job-level value. It has bounded retries, prints Compose logs only after a failure, and always
removes its temporary containers and volumes. It does not import data.

## Development and production images

Local Compose explicitly selects the frontend `development` target, keeps the source bind mount,
and runs Vite on port 5173. This preserves edit-and-refresh usability. A plain production build
uses the final `production` target:

```bash
docker build -t profile-search-backend:local ./backend
docker build --build-arg VITE_API_BASE_URL=http://localhost:8000 \
  -t profile-search-frontend:local ./frontend
```

The backend production image runs Gunicorn as a non-root `app` user and has a Python-based
`/health/live/` health check. It does not run migrations, imports, or index rebuilds automatically.
Migrations and Elasticsearch index operations remain explicit commands. The frontend production
image builds with Node 22, serves static files from nginx on port 80, provides `/healthz`, caches
hashed assets immutably, and leaves `index.html` non-immutable. `VITE_API_BASE_URL` is public
build-time configuration; no runtime secret is injected into frontend assets.

## Tag-based GHCR publishing

`.github/workflows/release.yml` triggers broadly for `v*` because GitHub Actions tag filters are
globs, not regular expressions. Its isolated validation job has only contents-read permission,
checks out the repository, and immediately invokes the shared validator before the publishing job
can perform registry login, image metadata generation, Docker builds, or pushes. The validator accepts
only this strict rule: `vMAJOR.MINOR.PATCH`, where each numeric component is zero or a non-zero digit
followed by digits. It rejects leading-zero components and prerelease/build suffixes, and emits
normalized `1.2.3` and `1.2` values for image metadata.

The same validator requires the public repository variable `VITE_API_BASE_URL`. Configure it in
GitHub under `Settings -> Secrets and variables -> Actions -> Variables -> New repository variable`
with the exact name `VITE_API_BASE_URL` and an absolute HTTP(S) application URL, for example
`https://profiles.example.com`. Empty, relative, non-HTTP(S), credential-bearing, fragment-bearing,
or whitespace-containing values fail before any publishing side effect. Release images never default
this value to localhost.

After validation, the workflow authenticates to `ghcr.io` with the GitHub-provided `GITHUB_TOKEN`
and grants only `contents: read` and `packages: write`. A successful run would publish:

- `ghcr.io/<lowercase-owner>/<lowercase-repository>/backend`
- `ghcr.io/<lowercase-owner>/<lowercase-repository>/frontend`

Each image receives the full `1.2.3`, `1.2`, and stable `latest` tags. OCI source, revision, version,
and creation-time labels are included. No personal access token, production secret, dataset, or
deployment step is used. This repository does not claim that GitHub-hosted execution or GHCR
publication has occurred; those require a pushed commit, configured repository variable, and a real
valid tag run.

Third-party actions are pinned to immutable full commit SHAs beside comments naming the verified
upstream release: checkout v6.0.2, setup-python v7.0.0, setup-node v7.0.0, setup-buildx-action
v4.2.0, build-push-action v7.3.0, login-action v4.6.0, and metadata-action v6.2.0. The repository
keeps bounded dependency ranges in application manifests; dependency lock-pinning is a remaining
reproducibility limitation outside this Phase 4A pass.

GitHub repository/package settings should manually require the backend and frontend quality/test
checks, Docker build, and Compose smoke check before merging to `main`, as appropriate for the
repository's branch-protection policy. Enable Actions package write access for the repository and
choose the desired GHCR package visibility/retention policy. These settings are recommendations,
not workflow-enforced organization rules.

## Verification boundaries

Local verification can validate commands, Docker builds, Compose startup, health endpoints,
production SPA fallback/static 404 behavior, security headers, and the release validation logic
without creating a tag or publishing. Only a pushed pull request or `main` commit can verify
GitHub's hosted runner behavior and required-check names. Only a real valid `v1.2.3` tag, after
the repository variable is configured, can verify GHCR authentication, package permissions, final
image tags/labels, and publication. This repository does not claim an external deployment.
