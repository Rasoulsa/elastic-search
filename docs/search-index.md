# Profile search index

## Ownership and lifecycle

PostgreSQL is the source of truth. Elasticsearch stores the derived, rebuildable index
`linkedin_profiles_v1`; profile imports and ordinary database writes never depend on Elasticsearch.
There are no Django signals or startup hooks for indexing.

Configuration is intentionally small:

- `ELASTICSEARCH_URL` defaults to `http://localhost:9200` in Django and is set to the Compose service
  URL for the backend container.
- `ELASTICSEARCH_REQUEST_TIMEOUT` defaults to `10` seconds.
- `ELASTICSEARCH_INDEX` defaults to `linkedin_profiles_v1` and supports isolated environments while
  preserving the versioned production contract by default.

The Python client is constrained to Elasticsearch client 8.x, which is compatible with the Compose
Elasticsearch 8.17 server. The dependency is restricted to the tested 8.17 minor line.

Backend startup, migrations, profile imports, authentication, PostgreSQL profile detail, and ordinary
backend tests require PostgreSQL but not a live Elasticsearch service. Explicit index commands and
profile search require Elasticsearch.

After any corrected dataset import, rebuild `linkedin_profiles_v1` from PostgreSQL. The index is
derived state and must not be used to repair source data. During the Day 3 acceptance remediation,
two consecutive rebuilds each indexed 248 of 248 profiles with zero failures; sanitized PostgreSQL
and Elasticsearch document IDs matched, and match-all returned 248 hits. Country and industry facet
buckets contained no date, salary-range, or serialized-list artifacts, job-title buckets contained
no company-size/date artifacts, and all indexed summaries were scalar strings.

## Explicit mapping

Dynamic fields are rejected. Exact-filter subfields retain their original display value in `_source`
while their keyword terms use a lowercase and ASCII-folding normalizer.

```json
{
  "settings": {
    "analysis": {
      "normalizer": {
        "lowercase_ascii": {
          "type": "custom",
          "filter": ["lowercase", "asciifolding"]
        }
      }
    }
  },
  "mappings": {
    "dynamic": "strict",
    "properties": {
      "profile_id": {"type": "keyword"},
      "full_name": {"type": "text", "fields": {"keyword": {"type": "keyword", "normalizer": "lowercase_ascii"}}},
      "job_title": {"type": "text", "fields": {"keyword": {"type": "keyword", "normalizer": "lowercase_ascii"}}},
      "job_titles": {"type": "text", "fields": {"keyword": {"type": "keyword", "normalizer": "lowercase_ascii"}}},
      "skills": {"type": "text", "fields": {"keyword": {"type": "keyword", "normalizer": "lowercase_ascii"}}},
      "industry": {"type": "text", "fields": {"keyword": {"type": "keyword", "normalizer": "lowercase_ascii"}}},
      "location_name": {"type": "text"},
      "country": {"type": "text", "fields": {"keyword": {"type": "keyword", "normalizer": "lowercase_ascii"}}},
      "company": {"type": "text", "fields": {"keyword": {"type": "keyword", "normalizer": "lowercase_ascii"}}},
      "summary": {"type": "text"},
      "experience_text": {"type": "text"},
      "education_text": {"type": "text"}
    }
  }
}
```

## Projection rules and assumptions

Each saved PostgreSQL profile produces one document whose Elasticsearch `_id` and `profile_id` are
the decimal PostgreSQL profile primary key. The projection requires prefetched `skills`,
`experiences`, and `educations`, preventing accidental relation-by-relation queries.

- Blank and nullable scalar values become empty strings; blank collections become empty arrays.
- Display text is Unicode-normalized and internal whitespace is collapsed. Deduplication is
  case-insensitive and accent-insensitive, preserving the first deterministic display value.
- `full_name` uses the persisted full name, falling back to joined first and last names.
- Experiences and education are ordered by importer `source_order`, then primary key. Skills are
  sorted by their normalized value.
- Current experience is the first source-ordered experience with no end date, falling back to the
  first experience. `job_title` uses the imported profile headline because it represents the source
  record's current job title, then falls back to the current experience title.
- `job_titles` starts with `job_title`, followed by experience titles in source order. `company`
  starts with the imported current `job_company_name`, falling back to the current experience
  company, then includes all experience companies in source order.
- `experience_text` combines title, company, location, and description for each experience.
  `education_text` combines school, degree, and field of study for each education.
- `industry` whitelists the imported `industry` value, falling back to `job_company_industry`.
  `country` whitelists `location_country`. These fields currently live in the persisted import
  payload rather than stable model columns.
- The `raw_payload` object itself, contact fields, authentication data, and all non-whitelisted
  source columns are excluded.

## Commands and failure behavior

```bash
python manage.py create_profile_index
python manage.py rebuild_profile_index --batch-size 500
```

The rebuild batch size must be between 1 and 1000 inclusive and defaults to 500. Invalid values are
rejected before an Elasticsearch client is created or the existing index is modified.

`create_profile_index` creates the explicit empty index and reports whether it was created or already
existed. It never reads or indexes profiles.

`rebuild_profile_index` uses an assignment-sized delete-and-recreate strategy. It removes any old
index, creates the explicit mapping, iterates profiles in primary-key order with bounded prefetch and
bulk batches, and refreshes once only after every bulk item succeeds. Stable document IDs prevent
duplicates on repeat runs, and recreating the index removes documents for profiles no longer in
PostgreSQL.

The command reports four sanitized counters:

- `attempted`: documents consumed or submitted by the bulk operation;
- `indexed`: documents confirmed successful by Elasticsearch;
- `failed`: documents confirmed failed by an item response;
- `unprocessed`: documents known not to have been attempted, or `unknown` when the remaining
  PostgreSQL input cannot be determined reliably without continuing the failed rebuild.

After a transport interruption, `attempted - indexed - failed` may represent documents whose final
Elasticsearch outcome is unknown. They are never classified as successful or failed without a
response. Confirmed progress observed before the interruption is retained in the failure summary.
Profile values, raw documents, and raw Elasticsearch errors are never printed.

The tradeoff is temporary search unavailability and loss of the previous index as soon as deletion
succeeds. If recreation then fails, the index is missing. If bulk indexing fails, the recreated
index can be empty or partially populated. A transport failure or any bulk item failure makes the
command exit non-zero. Fix the underlying issue and rerun the complete rebuild from PostgreSQL to
recover.

The readiness endpoint deliberately remains PostgreSQL-only. An Elasticsearch outage affects index
lifecycle commands and search but does not change database readiness or profile ownership.

## Search query contract

`GET /api/v1/profiles/search/` is JWT-protected and executes one Elasticsearch request for results
and facets. Its query builder is independently testable and uses only the committed fields above.

- Blank `q` uses `match_all`. A present `q` uses AND `best_fields` multi-match with boosts
  `full_name^4`, `job_title^4`, `job_titles^3`, `skills^3`, `company^2`, `industry^2`, then unboosted
  `summary`, `experience_text`, and `education_text`.
- Exact filters map `skill` to `skills.keyword`, `job_title` to `job_title.keyword`, and the other
  filter categories to their corresponding normalized keyword fields.
- Repeated values in a filter become one `bool.should` clause with `minimum_should_match: 1` and
  therefore use OR semantics. Separate filter categories become separate `bool.filter` clauses and
  therefore use AND semantics.
- Filter values are Unicode-NFKC and whitespace-normalized, then deduplicated in first-seen order.
  Exact filters use `term` queries inside `bool.filter`; Elasticsearch applies the committed keyword
  normalizer at query time, so lowercase and supported ASCII folding remain owned by Elasticsearch.
  Display values are never modified, and no full Python/Lucene Unicode-equivalence claim is made.
- Keyword results sort by `_score`, `full_name.keyword`, and `profile_id`. Filter-only and match-all
  requests omit `_score` and retain the latter two deterministic keys.
- Pagination uses `from = (page - 1) * page_size`. Page size defaults to 20, is limited to 1 through
  100, and cannot cross the 10,000-result window.

The same request aggregates up to 20 buckets each for `skills`, `job_titles`, `industries`,
`countries`, and `companies`. Aggregation keys use the normalized keyword fields and counts reflect
the current keyword plus every applied filter.

The gateway returns its response only to the application service. That service accepts an explicit
source allowlist, translates document `profile_id` to public `id`, selects the current company from
the deterministic company list, and emits stable facet buckets with `value` and `count`. Raw hits,
index names, scores, source objects, sort arrays, shard information, timing, and aggregation internals
never cross the API boundary.

Expected connection, timeout, transport, and missing-index failures, plus an unexpected gateway
response shape, return `503` with `code=search_unavailable`. There is no PostgreSQL search fallback.
The PostgreSQL-backed profile-detail endpoint is independent and remains available during this
failure. Elasticsearch clients created for an HTTP search are closed after both success and failure.

The authenticated search HTTP endpoint and the authenticated React search and profile-detail
experience were implemented on Day 3. PostgreSQL remains the canonical source of profile data, while
Elasticsearch remains the derived search index.
