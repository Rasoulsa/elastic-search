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

All other API routes require a valid bearer access token by default. The profile search endpoints
are still deferred and do not exist yet.

## Errors

Validation failures use DRF's JSON serializer format and return `400 Bad Request`, for example:

```json
{
  "password": ["This password is too short. It must contain at least 8 characters."]
}
```

Missing, invalid, or expired bearer tokens return `401 Unauthorized` using DRF's standard `detail`
response. Internal tracebacks and database exception details are not exposed by the API.

## OpenAPI and Swagger

- Schema: `GET http://localhost:8000/api/schema/`
- Swagger UI: `GET http://localhost:8000/api/docs/`

Swagger documents registration, token, refresh, and current-user operations and declares bearer JWT
authentication.

## CORS

`CORS_ALLOWED_ORIGINS` is a comma-separated, whitespace-trimmed allowlist. The local default is
`http://localhost:5173`. Origins not in the allowlist do not receive an
`Access-Control-Allow-Origin` header. JWTs are sent in the `Authorization` header, so credentialed
CORS requests are not enabled.
