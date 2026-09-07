# Frontend profile search

## Scope and routes

The authenticated React application provides two protected profile routes:

- `/search` renders keyword search, facet filters, result cards, and pagination.
- `/profiles/:profileId` renders the PostgreSQL-backed public profile detail.

Both routes use the existing authentication guard and authenticated API client. The client owns JWT
attachment, one refresh attempt after a `401`, session-expiry cleanup, request cancellation, and
logout cache clearing. Search and detail query keys contain only public request state or a profile ID;
they never contain tokens.

## URL search contract

The browser URL is the committed and shareable search state. Parameters are written in this order:
`q`, repeated `skill`, repeated `job_title`, repeated `industry`, repeated `country`, repeated
`company`, `page`, and `page_size`. Default pagination is omitted from the browser URL but sent
explicitly to the API as `page=1&page_size=20`.

Whitespace is normalized, blank filter values are removed, and repeated filter values are
deduplicated in first-seen order. Frontend comparison uses NFKC whitespace normalization followed by
NFKD accent removal, lower casing, and supported backend-equivalent `ß`/`SS` and Greek normal/final
sigma mappings. This is a bounded cross-language comparison policy, not a claim of complete Unicode
CaseFolding parity; original first-seen spellings remain displayed. Filter values within one category remain repeated URL parameters,
matching the backend's OR semantics; different categories retain the backend's AND semantics.
Unknown parameters are removed and never reach the API. If a scalar parameter is repeated, the first
value is retained and the canonical URL contains it once.

Invalid, unsafe, or out-of-window pagination follows one normalization policy: `page` becomes 1 and
`page_size` becomes 20 when its value is not a supported positive integer; page sizes above 100 are
also reset to 20. A page whose requested range crosses the 10,000-result window becomes page 1. Once
a response establishes `total_pages`, a page above that total is replaced with the final valid page,
or page 1 when there are no results. Successful responses are checked before rendering: count,
total-pages arithmetic, page size, result bounds, and in-range page lengths must agree with the
request. A legitimate out-of-range response must be empty and is shown only as a short adjusting
state while replace navigation moves to the final page or page 1. Inconsistent metadata becomes the
recoverable malformed-response error and is never repaired or rendered.

Search inputs have draft state. Typing and selecting facets do not issue requests. Search, Enter, or
Apply writes normalized criteria to the URL, resetting the page only when criteria or page size have
changed. The URL then drives the TanStack Query key and API request. Browser navigation and reloads
restore the controls and request. Clear filters removes all search parameters and restores the first
match-all page at 20 results per page.

## Facets and results

The initial `/search` request is match-all, so profiles and all five facet groups are available
immediately. Skills, job titles, industries, countries, and companies are multi-select checkboxes.
Every facet displays its result count. Selected values are merged ahead of current buckets, remain
visible when missing from a later response, and can be removed from the filter or active-search
chips. Lists initially show six options and expose a small show-more control when needed.

The result heading uses the exact backend `count`, correct singular/plural wording, and the current
page when multiple pages exist. Cards render only the allowlisted full name, current job title,
company, country, industry, skills, and summary. Five skills are shown before a `+N more` indicator;
summary truncation is visual CSS only. Missing values omit their surrounding labels. All values are
normal React text.

Pagination uses Previous, a live current-page indicator, and Next. It does not create numbered-page
buttons. Bounds come from `page` and `total_pages`; navigation preserves criteria and page size. Once
the new page arrives, focus and scroll move to the results heading. Smooth scrolling is disabled when
the browser reports a reduced-motion preference.

## Profile detail and return navigation

Result links carry the complete canonical `/search?...` value in a `return_to` parameter. The detail
page validates it with the existing local-destination safety logic and further requires the path to
be exactly `/search`; any missing, external, malformed, or non-search destination falls back to
`/search`. Browser Back also continues to work normally.

Positive safe-integer profile IDs call the PostgreSQL detail endpoint. Malformed IDs show a safe
local error without making a request. Detail renders only the allowlisted name, role, company,
industry, location/country, summary, skills, experiences, education, and profile URL. Nested arrays
retain backend order. HTTP and HTTPS profile URLs become links with `target="_blank"` and
`rel="noreferrer noopener"`; other schemes are plain text.

## Loading and error behavior

Initial search and detail loading use stable skeleton regions. A same-key background fetch is marked
as updating. New URL criteria do not reuse a previous query's data as though it belonged to the new
request. TanStack Query forwards its `AbortSignal`, preventing superseded work from updating the
newer query. Each request owns its signal; when criteria change, an older request may be aborted or
finish later, but it cannot replace the newer query's visible results.

Search distinguishes invalid `400` input, search-unavailable `503`, network failure, generic server
failure, malformed successful responses, no results, and session expiry. Detail separately handles
`404`, network/server failure, and malformed success; it never describes a detail failure as search
unavailability. Network and search `503` failures receive at most one automatic retry after a short
delay. Detail network failures receive at most one automatic retry; detail `404`, `401`, server,
malformed-success, and aborted requests do not retry automatically. Manual Retry starts one new
query attempt. Every recoverable error also has a visible Retry action. Stable UI copy never displays
raw backend, database, or search-engine content. A `401` remains owned by the Phase 3A refresh/session
flow and ultimately redirects to login if refresh fails.

Logout removes both search and profile-detail query data with the existing authenticated cache clear,
so a later session cannot observe the previous session's profile data.

## Responsive and accessibility decisions

Desktop uses a compact filter sidebar with the results as the primary column. At tablet and mobile
widths the layout becomes one column; at narrow widths the keyword action stacks below the input.
Long names, companies, values, and URLs wrap, and controls retain at least a 44-pixel target where
appropriate. No large UI framework was introduced.

Inputs have associated labels, facet groups use fieldsets and legends, and the form submits with
Enter. Loading uses status semantics, errors use alerts, the results count is a heading, pagination
announces its current page, focus indicators remain visible, and decorative arrows are hidden from
assistive technology. Status is never communicated by color alone.

## Accepted limitations

- Facets are the backend's bounded top 20 buckets; this UI does not add autocomplete or request a
  separate global facet catalogue.
- Facets reflect the currently applied URL search, not unsaved draft selections.
- Search is explicitly submitted; there is no live, fuzzy, semantic, or saved search.
- Date strings use the backend's ISO representation to avoid locale-dependent ambiguity.
