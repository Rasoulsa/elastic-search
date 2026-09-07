# Architecture

## Purpose and Day 2 scope

This repository is the platform foundation for a LinkedIn profile search application. Day 2 adds an
explicit, repeatable CSV importer and the identity, raw-payload, and source-order fields needed for
future search. It does not implement indexing, searching, or user authentication.

## Application architecture

The React and TypeScript frontend is served by Vite and is the client for a future Django REST API.
The Django backend exposes health endpoints and owns the relational profile data. PostgreSQL is the
canonical source of truth. Elasticsearch is a derived search index that will be rebuilt explicitly
from PostgreSQL; it is running in Compose but is not integrated with Django in this phase.

```mermaid
flowchart LR
    Browser[React + Vite frontend] -->|HTTP| API[Django REST API]
    API -->|planned canonical persistence| DB[(PostgreSQL)]
    DB -.->|planned explicit reindex| ES[(Elasticsearch)]
```

## Current service responsibilities

- `frontend` runs the React, TypeScript, and Vite application shell.
- `backend` runs Django and Django REST Framework, including the health endpoints and profile model
  foundation.
- `db` runs PostgreSQL 16, where application profile data will be canonical.
- `elasticsearch` runs Elasticsearch 8 as infrastructure for the future derived search index. No
  Django client, mappings, or indexing code exists yet.

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
profile. The import command is explicit; there is no search API yet.

## Health endpoint semantics

- `GET /health/live/` returns `200` with `{"status":"ok"}` and does not access PostgreSQL. It
  indicates that the Django process can serve requests.
- `GET /health/ready/` executes `SELECT 1` through the default database connection. A successful
  connectivity check returns `200` with `{"status":"ok","database":"ok"}`.
- A Django `DatabaseError` returns a stable `503` response with
  `{"status":"unavailable","database":"unavailable"}`. Exception details are not returned.
- Readiness is limited to PostgreSQL connectivity. It does not check migration status or
  Elasticsearch availability.

## Docker Compose topology

Compose runs `db`, `elasticsearch`, `backend`, and `frontend`. The backend uses the Compose service
hostnames `db` and `elasticsearch`; the frontend calls the backend through the host-published port.
The backend waits for healthy database and Elasticsearch containers before starting, while the
frontend waits for the backend health check. PostgreSQL and Elasticsearch data use named volumes.

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

## Intentionally deferred

JWT authentication, Elasticsearch clients and mappings, index rebuilding, the search API, protected
API access, and the complete profile search UI are deferred to later slices. Django signals will not
be used for PostgreSQL-to-Elasticsearch indexing.
