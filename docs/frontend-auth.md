# Frontend authentication

## Scope and routes

The React frontend implements the Phase 3A authentication foundation against the existing Django
JWT API. Phase 3B adds the authenticated profile search and profile-detail routes described below.

- `/login` is public and redirects authenticated users to `/search`.
- `/register` is public and redirects authenticated users to `/search`.
- `/search` and `/profiles/:profileId` are protected. Logged-out users are redirected to `/login`,
  with the safe local path and query preserved in router state.
- Unknown paths render a small not-found page.

Route guards show a session-loading state until startup authentication resolves, so protected
content does not flash before a redirect.

## Backend contract

The client uses `VITE_API_BASE_URL` plus the committed backend routes:

- `POST /api/v1/auth/register/` with username, optional email, and password;
- `POST /api/v1/auth/token/` with username and password;
- `POST /api/v1/auth/token/refresh/` with the refresh token;
- `GET /api/v1/auth/me/` with an access-token bearer header.

Registration returns public user fields and no tokens. The frontend therefore redirects successful
registration to login with a sign-in message. The backend has no password-confirmation field, so the
frontend does not send one.

## Token policy

The access token is memory-only. The refresh token normally uses `sessionStorage` through the
centralized token store, allowing a same-tab reload while clearing the persisted session when the tab
or browser session closes. If `sessionStorage` is unavailable or a write fails, the refresh token uses
an in-memory fallback for the current page only and cannot survive reload. A successful storage write
does not retain a second memory copy. Neither token is stored in `localStorage`, URLs, rendered
messages, logs, or TanStack Query keys.

Logout removes local tokens but does not revoke already-issued JWTs. Previously issued access and
refresh JWTs remain valid server-side until their expiration because this assignment does not provide
refresh-token rotation, a blacklist, or a logout endpoint. Storage-failure suppression prevents stale
local refresh-token reuse when a browser refuses to remove the old value. A later intentional login
replaces that logical session.

JavaScript-readable storage is exposed to any successful cross-site scripting attack. A production
deployment should prefer secure, `HttpOnly`, appropriately scoped cookies plus corresponding CSRF
protection. That requires a backend authentication contract change and is outside this assignment.

## Startup and refresh lifecycle

At provider startup, the client checks for a refresh token. When present it performs one controlled
refresh, stores the new access token in memory, and requests `/api/v1/auth/me/`. When absent, or when
refresh or current-user loading fails, it clears the session and resolves as unauthenticated.

Protected API requests attach the bearer access token. After an initial 401, all concurrent requests
share one in-flight refresh operation. Refresh remains shared even when one caller aborts; waiting and
retry cancellation are caller-scoped. Each original request retries at most once, preserves its
original `AbortSignal`, and a second 401 clears the session without another refresh. The public login,
registration, and refresh operations never receive the bearer header, and the refresh request cannot
recursively trigger refresh. `AbortError` remains a cancellation result rather than a generic network
error.

The token store and authentication provider track session generations. Logout changes the generation
before cancelling and clearing TanStack Query state. A refresh or `/me/` response that started under
an earlier generation is ignored and cannot restore the session. Session-expiry cleanup and its
notification are idempotent per authentication generation, so concurrent retried 401 responses cause
one cleanup transition. A later successful login starts a new generation.

## Errors and logout

The API client parses response text defensively and translates errors into stable categories for
field validation, invalid credentials, network failure, temporary server failure, unauthorized
access, and unexpected responses. HTML, malformed JSON, or empty errors never render raw response
content. Registration pages render supported field errors next to their inputs.

Logout is entirely client-side because the backend exposes no logout or token-revocation endpoint.
It removes local access and refresh tokens, clears the current user, cancels query work, clears the
query cache, and navigates to `/login`. HttpOnly secure cookies and server-side token revocation are
production hardening options outside this assignment's backend scope.

## Search and detail navigation

The search and detail pages use the same protected API client and do not duplicate token refresh.
Frontend search uses the authenticated API client. Logout remains client-side: it removes local
tokens, clears the current user, cancels query work, clears the authenticated cache, and navigates to
`/login`.
Result links place the complete canonical `/search?...` return location in the detail URL. Detail
passes it through the existing local-destination validator and additionally restricts it to the
`/search` path before rendering Back to results. Missing, unsafe, and non-search values fall back to
`/search`. Neither tokens nor authentication state are included in URLs or query keys. See
`docs/frontend-search.md` for the search-state contract.
