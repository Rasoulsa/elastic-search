# Day 4: Delivery readiness

## Phase 4A scope

Phase 4A adds repository-scoped GitHub Actions CI, stable-tag GHCR image publishing, a concise pull
request template, and bounded production-container hardening. Product behavior, authentication,
dataset import, PostgreSQL ownership, and explicit Elasticsearch indexing remain unchanged.

## Implemented

- Pull requests and pushes to `main` run independent backend and frontend quality/test jobs.
- Backend CI preserves SQLite for ordinary pytest and separately validates PostgreSQL-backed Django
  configuration, checks, and migrations against PostgreSQL 16. HTTP application startup and health
  verification occur in the separate Compose smoke job.
- Frontend CI runs the existing npm install, lint, type-check, Vitest, and Vite build commands.
- Dependent Buildx and Compose smoke jobs use synthetic values and never import the private dataset.
- The backend image runs Gunicorn as a non-root user with a live health check.
- The frontend image has a Vite development target for Compose and an nginx production target with
  SPA fallback and bounded cache behavior.
- Broad `v*` release triggers use an isolated read-only validation job that invokes the shared
  validator immediately after checkout, before publishing, with normalized image metadata and a
  required validated public API URL.
- Third-party actions are pinned to immutable full SHAs verified against current upstream stable
  releases.
- PR review reminders cover tests, migrations, secrets, raw data, credentials, Codex-local files,
  and documentation.

## Remediation verification

- The Make import target requires `make import DATASET_PATH=/data/profiles.txt` and fails before
  Docker for missing or whitespace-only paths.
- Both production Docker contexts exclude dataset, backup, secret, token, environment, database
  dump, cache, and development-only artifacts.
- Production Nginx keeps SPA fallback for application routes, returns 404 for missing static-looking
  resources, keeps `/healthz` dependable, and applies the required security headers with `always`.
- Compose smoke uses a unique project name containing `github.run_id` and `github.run_attempt` for
  startup, diagnostics, and always-run cleanup.
- Local focused shell checks cover release inputs, normalized versions, workflow wiring/order,
  release-workflow action pinning, import-path validation and shell safety, and bounded Compose
  controls. Dockerignore rules were source-reviewed and configuration-validated. Production-container
  probes previously verified the Nginx SPA routes, static-looking 404 behavior, `/healthz`, and the
  required security headers; those behaviors are not exercised by `tests/ci/test_phase_4a.sh`. The
  final read-only review could not rerun Docker/Nginx probes because local Docker access was
  unavailable.

## Release boundary

No image was pushed, no tag was created, and no external deployment was performed during this
phase. GHCR package permissions, GitHub-hosted workflow execution, branch protection, repository
variable configuration, and a real release tag remain post-push verification items. Application
dependency manifests retain bounded ranges; lock-pinning remains a reproducibility limitation.
