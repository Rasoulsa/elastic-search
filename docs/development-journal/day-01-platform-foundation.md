# Day 1: Platform Foundation

## Objective

Establish a small, reviewable platform foundation for LinkedIn profile search: Django and Django
REST Framework on the backend, React and TypeScript on the frontend, PostgreSQL infrastructure and
models, Elasticsearch infrastructure, and basic service health checks.

## Branch

`chore/bootstrap-platform`

## Implemented scope

- Django 5.2 and Django REST Framework backend configuration.
- React, TypeScript, and Vite frontend application shell.
- PostgreSQL-backed profile, skill, experience, and education model foundation.
- Docker Compose services for PostgreSQL, Elasticsearch, backend, and frontend.
- Public liveness and PostgreSQL connectivity readiness endpoints.
- Focused backend and frontend test foundations, Ruff, ESLint, TypeScript checking, and production
  build commands.
- Day 1 README, architecture, testing, and development documentation.

## Architecture decisions

PostgreSQL is the planned canonical source of truth. Elasticsearch is a derived index and is kept
as a separately rebuildable concern. Day 1 starts Elasticsearch as infrastructure but does not add a
Django client, mappings, indexing behavior, or readiness dependency. PostgreSQL-to-Elasticsearch
synchronization will use explicit management commands rather than Django signals.

The liveness endpoint is independent of the database. The readiness endpoint performs only a small
database connectivity query, catches Django `DatabaseError`, uses a context-managed cursor, and
returns a stable response without exception details.

## Data-model foundation

`Profile` stores the initial person and profile fields. `Skill` has a unique name and relates to
profiles many-to-many. `Experience` and `Education` each belong to one profile through a foreign
key and are deleted with that profile. The initial migration captures these relationships.

## Infrastructure created

Docker Compose defines PostgreSQL 16, Elasticsearch 8, the Django backend, and the Vite frontend.
Database and Elasticsearch data are stored in named volumes. Compose health checks gate backend and
frontend startup. The example environment file uses Compose service hostnames and documents the
values that need local-host overrides when the backend runs outside Docker.

## Verification results

The focused verification completed successfully:

- Health tests: 3 passed, including liveness database isolation and stable readiness failure
  behavior.
- Model tests: 1 passed.
- Ruff on changed backend files: passed.
- Django system check: no issues.
- Migration consistency check: no changes detected.
- Frontend tests: 1 test passed.
- Frontend lint, explicit TypeScript type-check, and production build: passed.
- Git diff whitespace validation and Docker Compose configuration validation: passed.

The backend checks ran in the Compose backend container; the frontend checks ran with the installed
frontend dependencies.

## Review findings and corrections

- Readiness failure handling now catches Django `DatabaseError`, which includes operational database
  failures, and uses a context-managed cursor.
- Liveness remains database-independent, while readiness remains limited to PostgreSQL connectivity.
- Health tests cover successful and failed behavior without asserting Django internals or exposing
  the original exception message.
- Deferred import and reindex Makefile targets were removed because their management commands do not
  exist until Day 2.
- The frontend now exposes an explicit `npm run typecheck` command based on the referenced
  TypeScript project configuration.
- README and supporting documentation now describe only the implemented Day 1 scope and the
  planned Day 2 interfaces.

## Intentionally deferred features at the Day 1 checkpoint

JWT authentication, dataset parsing and import, Elasticsearch clients and mappings, explicit index
rebuilding, the search API, protected API access, and the complete profile search UI remain
deferred. No placeholder management commands were added.

## Remaining risks

- Elasticsearch is not yet connected to Django, so there is no indexing or search behavior to
  validate.
- The readiness endpoint does not detect unapplied migrations by design.
- Authentication and authorization are not implemented.
- The raw profile dataset and its import format are not yet integrated.
- The current frontend is an application shell rather than a search experience.

## Final acceptance checklist

- [x] Branch is `chore/bootstrap-platform`.
- [x] PostgreSQL is documented as the planned canonical source of truth.
- [x] Elasticsearch is documented as running infrastructure but not Day 1 Django integration.
- [x] Liveness and PostgreSQL readiness semantics are tested and documented.
- [x] Nonexistent Day 2 import and reindex targets are absent from the Makefile.
- [x] Frontend test, lint, type-check, and build commands are explicit.
- [x] Startup documentation includes environment setup, service startup, migrations, and health
      verification.
- [x] Deferred features and remaining risks are stated.
