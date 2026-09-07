# API

## Base URL

The local backend base URL is `http://localhost:8000`. API routes use the `/api/` prefix.

## Authentication

### Register

`POST /api/v1/auth/register/` is public and creates a Django user. It does not issue tokens.

Request:

```json
{
  "username": "reviewer",
  "email": "reviewer@example.com",
  "password": "ChangeThis-Test-Password-42!"
}
```

Response (`201 Created`):

```json
{
  "id": 1,
  "username": "reviewer",
  "email": "reviewer@example.com"
}
```

Email is optional and is returned as an empty string when omitted. Usernames must be unique. Email
format and Django's configured password validators are enforced. Passwords and password hashes are
never returned.

### Obtain tokens

`POST /api/v1/auth/token/` is public.

Request:

```json
{
  "username": "reviewer",
  "password": "ChangeThis-Test-Password-42!"
}
```

Response (`200 OK`):

```json
{
  "refresh": "<refresh-token>",
  "access": "<access-token>"
}
```

Access tokens expire after 15 minutes. Refresh tokens expire after 7 days. Refresh rotation and
blacklisting are disabled, and tokens are not stored in the database.

### Refresh an access token

`POST /api/v1/auth/token/refresh/` is public.

Request:

```json
{
  "refresh": "<refresh-token>"
}
```

Response (`200 OK`):

```json
{
  "access": "<new-access-token>"
}
```

### Current user

`GET /api/v1/auth/me/` requires an access token:

```http
Authorization: Bearer <access-token>
```

Response (`200 OK`):

```json
{
  "id": 1,
  "username": "reviewer",
  "email": "reviewer@example.com"
}
```

## Public and protected routes

Public routes are:

- `GET /health/live/`
- `GET /health/ready/`
- `POST /api/v1/auth/register/`
- `POST /api/v1/auth/token/`
- `POST /api/v1/auth/token/refresh/`
- `GET /api/schema/`
- `GET /api/docs/`

All other API routes require a valid bearer access token by default, including both profile routes.

## Profile search

`GET /api/v1/profiles/search/` queries the derived `linkedin_profiles_v1` Elasticsearch index.
PostgreSQL is not used as a fallback. Supply an access token and any optional parameters:

| Parameter | Contract |
| --- | --- |
| `q` | Scalar keyword query, provided at most once; maximum 500 characters. Blank is treated as absent. |
| `skill` | Exact skill filter, repeatable, maximum 20 values of 200 characters each. |
| `job_title` | Exact current job-title filter, with the same repeat limits. |
| `industry` | Exact industry filter, with the same repeat limits. |
| `country` | Exact country filter, with the same repeat limits. |
| `company` | Exact current or historical company filter, with the same repeat limits. |
| `page` | Scalar positive integer, provided at most once; default 1. Repetition returns `400`. |
| `page_size` | Scalar integer from 1 through 100, provided at most once; default 20. Repetition returns `400`. |

Surrounding whitespace is removed and blank optional values are ignored. Repeated values within one
filter category use OR semantics, while different categories use AND semantics. Values are
Unicode-NFKC and whitespace-normalized, then deduplicated in first-seen order. Elasticsearch applies
the committed keyword normalizer at exact-filter query time, including lowercase and supported ASCII
folding; displayed values are never modified. Repeated scalar parameters, including repeated
identical values or repeated blank `q`, return `400 Bad Request`. Values are never silently
truncated. Page requests whose offset plus page size exceed the supported 10,000-result window return
`400 Bad Request` without contacting Elasticsearch.

Keyword queries use an AND `best_fields` multi-match with the strongest weights on full name and
current job title, followed by job-title history and skills, company and industry, then summary,
experience, and education. Exact filters use normalized keyword fields in `bool.filter`; they are
not analyzed-text or PostgreSQL substring filters. Elasticsearch-owned normalization keeps case and
supported ASCII-folding behavior consistent with indexed keyword values. Keyword results sort by
score, normalized full name, and profile ID. Match-all and filter-only results sort by normalized full
name and profile ID.

Example:

```bash
ACCESS_TOKEN="<access-token>"
curl --get "http://localhost:8000/api/v1/profiles/search/" \
  --header "Authorization: Bearer ${ACCESS_TOKEN}" \
  --data-urlencode "q=backend engineer" \
  --data-urlencode "skill=Python" \
  --data-urlencode "skill=Django" \
  --data-urlencode "country=Finland" \
  --data-urlencode "page=1" \
  --data-urlencode "page_size=20"
```

Response (`200 OK`):

```json
{
  "count": 248,
  "page": 1,
  "page_size": 20,
  "total_pages": 13,
  "results": [
    {
      "id": 123,
      "full_name": "Example Person",
      "job_title": "Backend Engineer",
      "company": "Example Company",
      "industry": "Software",
      "country": "Finland",
      "skills": ["Django", "Python"],
      "summary": "Builds reliable search systems."
    }
  ],
  "facets": {
    "skills": [{"value": "python", "count": 42}],
    "job_titles": [{"value": "backend engineer", "count": 24}],
    "industries": [{"value": "software", "count": 18}],
    "countries": [{"value": "finland", "count": 12}],
    "companies": [{"value": "example company", "count": 8}]
  }
}
```

`count` is the exact total matching document count, not the number on the current page.
`total_pages` is zero when there are no matches. Facets are calculated in the same Elasticsearch
request from the current keyword and all applied filters. Each facet is bounded to 20 normalized
keyword buckets. The public response never contains `_index`, `_score`, `_source`, sort values,
shard details, timing data, or raw aggregation structures.

If Elasticsearch is unreachable, times out, returns a transport error, has no search index, or
returns an unexpected response shape, the endpoint returns this stable response (`503 Service
Unavailable`):

```json
{
  "code": "search_unavailable",
  "detail": "Profile search is temporarily unavailable."
}
```

There is no PostgreSQL fallback and no internal hostname, index name, exception, or query in the
response.

## Profile detail

`GET /api/v1/profiles/{id}/` reads from PostgreSQL, the canonical source of truth. It remains
available when Elasticsearch is stopped. The response includes only the public identity aliases,
profile fields, skills, experiences, and education selected by the application.

The scalar `company`, `industry`, and `country` fields are explicitly allowlisted values derived from
the imported `raw_payload` because dedicated relational model columns do not currently exist. The
`raw_payload` object is never serialized; arbitrary nested payload values and contact fields are not
returned.

```bash
ACCESS_TOKEN="<access-token>"
curl "http://localhost:8000/api/v1/profiles/123/" \
  --header "Authorization: Bearer ${ACCESS_TOKEN}"
```

Response (`200 OK`):

```json
{
  "id": 123,
  "linkedin_id": "synthetic-linkedin-id",
  "linkedin_username": "example-profile",
  "profile_url": "https://www.linkedin.com/in/example-profile",
  "full_name": "Example Person",
  "job_title": "Backend Engineer",
  "company": "Example Company",
  "industry": "Software",
  "location": "Helsinki",
  "country": "Finland",
  "summary": "Builds reliable systems.",
  "skills": ["Django", "Python"],
  "experiences": [
    {
      "title": "Backend Engineer",
      "company": "Example Company",
      "location": "Helsinki",
      "description": "Built APIs.",
      "started_at": "2022-01-01",
      "ended_at": null
    }
  ],
  "education": [
    {
      "school": "Example University",
      "degree": "MSc",
      "field_of_study": "Computer Science",
      "started_at": "2018-01-01",
      "ended_at": "2020-01-01"
    }
  ]
}
```

Unknown IDs return `404 Not Found`. The importer-owned canonical `public_identifier`, `raw_payload`,
private source fields, timestamps, source ordering, and authentication data are excluded.

## Errors

Validation failures use DRF's JSON serializer format and return `400 Bad Request`, for example:

```json
{
  "password": ["This password is too short. It must contain at least 8 characters."]
}
```

Missing, invalid, or expired bearer tokens return `401 Unauthorized` using DRF's standard `detail`
response. Invalid search parameters use stable DRF field errors and return `400 Bad Request`.
Internal tracebacks, database details, and Elasticsearch errors are not exposed by the API.

## OpenAPI and Swagger

- Schema: `GET http://localhost:8000/api/schema/`
- Swagger UI: `GET http://localhost:8000/api/docs/`

Swagger documents authentication, every search parameter, repeat semantics, response and facet
schemas, pagination errors, search unavailability, and profile detail. Use Swagger's **Authorize**
control with a JWT access token; the generated security scheme is HTTP bearer JWT.

## CORS

`CORS_ALLOWED_ORIGINS` is a comma-separated, whitespace-trimmed allowlist. The local default is
`http://localhost:5173`. Origins not in the allowlist do not receive an
`Access-Control-Allow-Origin` header. JWTs are sent in the `Authorization` header, so credentialed
CORS requests are not enabled.
