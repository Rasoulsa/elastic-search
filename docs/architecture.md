# Architecture

## Purpose and current scope

This repository is the platform foundation for a LinkedIn profile search application. It includes
an explicit, repeatable CSV importer, JWT authentication with public API documentation, and an
explicitly rebuildable Elasticsearch profile index. The search HTTP endpoint and full UI are not
implemented.

## Application architecture

The React and TypeScript frontend is served by Vite and is the client for the Django REST API. The
Django backend exposes health, authentication, and API documentation endpoints and owns the
relational user and profile data. PostgreSQL is the canonical source of truth. Elasticsearch is a
derived search index rebuilt explicitly from PostgreSQL. Profile writes and imports do not contact
Elasticsearch.

```mermaid
flowchart LR
    Browser[React + Vite frontend] -->|HTTP| API[Django REST API]
    API -->|planned canonical persistence| DB[(PostgreSQL)]
    DB -->|explicit rebuild command| ES[(Elasticsearch)]
```

## Current service responsibilities

- `frontend` runs the React, TypeScript, and Vite application shell.
- `backend` runs Django and Django REST Framework, including health endpoints, JWT authentication,
  OpenAPI/Swagger documentation, and the profile model foundation.
- `db` runs PostgreSQL 16, where application profile data will be canonical.
- `elasticsearch` runs Elasticsearch 8.17 and stores the derived `linkedin_profiles_v1` index.
  Django integrates through one small gateway for index lifecycle and bulk operations.

## Data-model foundation

- A `Profile` represents a person and has a unique public identifier. LinkedIn ID, username, and
  canonical profile URL are nullable dedicated identity aliases, each unique when present.
- `Profile.raw_payload` preserves the original source columns for diagnostics and future mapping
  work. Identity resolution never queries this JSON field.
- A `Profile` has many `Skill` records through a many-to-many relationship. A `Skill` can belong to
  many profiles and has a unique name.
- A `Profile` has many `Experience` records. Each experience belongs to one profile and is deleted
  with its profile.
- A `Profile` has many `Education` records. Each education belongs to one profile and is deleted
  with its profile.

The model includes basic identity, contact-free profile, experience, education, and timestamp
fields. Experience and education preserve zero-based source order with a unique position per
profile. Both import and index rebuild commands are explicit; there is no search API yet.

## Health endpoint semantics

- `GET /health/live/` returns `200` with `{"status":"ok"}` and does not access PostgreSQL. It
  indicates that the Django process can serve requests.
- `GET /health/ready/` executes `SELECT 1` through the default database connection. A successful
  connectivity check returns `200` with `{"status":"ok","database":"ok"}`.
- A Django `DatabaseError` returns a stable `503` response with
  `{"status":"unavailable","database":"unavailable"}`. Exception details are not returned.
- Readiness is limited to PostgreSQL connectivity. It does not check migration status or
  Elasticsearch availability.

## Authentication and API documentation

- `POST /api/v1/auth/register/` creates a user with Django's default user model and never issues a
  token.
- `POST /api/v1/auth/token/` and `POST /api/v1/auth/token/refresh/` are standard Simple JWT
  endpoints. Access tokens last 15 minutes and refresh tokens last 7 days. Refresh rotation and
  token blacklisting are disabled; tokens are not stored in the database.
- `GET /api/v1/auth/me/` requires a valid `Authorization: Bearer <access-token>` header and returns
  only the current user's id, username, and email.
- The default API permission is authenticated access. Health, registration, token, schema, and
  Swagger endpoints explicitly remain public.
- `GET /api/schema/` serves the OpenAPI schema and `GET /api/docs/` serves Swagger UI. CORS allows
  only the origins listed in `CORS_ALLOWED_ORIGINS`; credentials are disabled.

## Docker Compose topology

Compose runs `db`, `elasticsearch`, `backend`, and `frontend`. The backend uses the Compose service
hostnames `db` and `elasticsearch`; the frontend calls the backend through the host-published port.
The backend requires a healthy PostgreSQL container but has no startup dependency on Elasticsearch,
while the frontend waits for the backend health check. Explicit indexing commands and future search
requests require Elasticsearch. PostgreSQL and Elasticsearch data use named volumes.

## Import interface

```bash
python manage.py import_profiles --path /data/profiles.txt
```

The importer requires the exact 77-column CSV header, skips malformed-width records without repair,
and reports logical/physical row ranges using reason codes. It parses and normalizes every accepted
row before consolidating duplicates through all canonical aliases. Only then does one transaction
persist one final plan per profile. Tri-state values distinguish valid values, explicit empties, and
invalid input. Complete valid nested lists synchronize source positions and remove stale rows;
partial lists preserve invalid/unmatched positions, while invalid top-level collections are kept
unchanged. Diff-aware writes preserve unchanged profile timestamps and retained child primary keys.
Database counters report actual creates, updates, unchanged rows, and deletes.

## Search-index boundary

`apps/search` owns the Elasticsearch mapping, deterministic document projection, client gateway,
and management commands. `create_profile_index` idempotently creates the empty versioned index.
`rebuild_profile_index` deletes and recreates it, iterates PostgreSQL profiles with prefetched
relations, bulk-indexes bounded batches using stable profile primary-key IDs, and refreshes once on
success. This simple replacement removes stale documents but makes the index temporarily unavailable.
Failures are translated to stable command errors; raw Elasticsearch responses and profile values are
not printed. See `docs/search-index.md` for the exact contract.

No Django signals or application-startup hooks synchronize profile writes. This keeps PostgreSQL
writes independent from Elasticsearch and makes index state explicitly reproducible and observable.
Backend startup, migrations, imports, authentication, and ordinary tests remain available when
Elasticsearch is stopped. The readiness endpoint therefore remains PostgreSQL-only.

## Intentionally deferred

The search HTTP API and complete profile search UI are deferred to later slices. Zero-downtime alias
rotation and incremental synchronization are also intentionally outside the assignment-sized scope.
