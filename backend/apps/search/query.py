import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_RESULT_WINDOW = 10_000
FACET_SIZE = 20

FILTER_FIELDS = {
    "skill": "skills.keyword",
    "job_title": "job_title.keyword",
    "industry": "industry.keyword",
    "country": "country.keyword",
    "company": "company.keyword",
}

FACET_FIELDS = {
    "skills": "skills.keyword",
    "job_titles": "job_titles.keyword",
    "industries": "industry.keyword",
    "countries": "country.keyword",
    "companies": "company.keyword",
}

SEARCH_FIELDS = [
    "full_name^4",
    "job_title^4",
    "job_titles^3",
    "skills^3",
    "company^2",
    "industry^2",
    "summary",
    "experience_text",
    "education_text",
]

SEARCH_RESULT_FIELDS = [
    "profile_id",
    "full_name",
    "job_title",
    "skills",
    "company",
    "industry",
    "country",
    "summary",
]


class SearchWindowError(ValueError):
    """The requested page exceeds the configured Elasticsearch result window."""


@dataclass(frozen=True)
class SearchCriteria:
    q: str | None = None
    filters: Mapping[str, Sequence[str]] = field(default_factory=dict)
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE


def normalize_filter_value(value: str) -> str:
    """Normalize only whitespace; Elasticsearch owns keyword case and folding."""
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _deduplication_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    unaccented = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return unaccented.casefold()


def normalize_filter_values(values: Sequence[str]) -> list[str]:
    normalized_values = []
    seen = set()
    for value in values:
        normalized = normalize_filter_value(value)
        deduplication_key = _deduplication_key(normalized)
        if normalized and deduplication_key not in seen:
            normalized_values.append(normalized)
            seen.add(deduplication_key)
    return normalized_values


def _exact_filter_clause(index_field: str, values: Sequence[str]) -> dict:
    return {
        "bool": {
            "should": [{"term": {index_field: value}} for value in values],
            "minimum_should_match": 1,
        }
    }


def build_profile_search_query(criteria: SearchCriteria) -> dict:
    offset = (criteria.page - 1) * criteria.page_size
    if offset < 0 or criteria.page_size < 1 or offset + criteria.page_size > MAX_RESULT_WINDOW:
        raise SearchWindowError("Requested page exceeds the supported search result window.")

    keyword_query = None
    if criteria.q:
        keyword_query = {
            "multi_match": {
                "query": criteria.q,
                "fields": SEARCH_FIELDS,
                "type": "best_fields",
                "operator": "and",
            }
        }

    exact_filters = []
    for parameter_name, index_field in FILTER_FIELDS.items():
        values = normalize_filter_values(criteria.filters.get(parameter_name, ()))
        if values:
            exact_filters.append(_exact_filter_clause(index_field, values))

    if exact_filters:
        query = {
            "bool": {
                "must": [keyword_query or {"match_all": {}}],
                "filter": exact_filters,
            }
        }
    elif keyword_query:
        query = {"bool": {"must": [keyword_query]}}
    else:
        query = {"match_all": {}}

    sort = []
    if keyword_query:
        sort.append({"_score": {"order": "desc"}})
    sort.extend(
        [
            {"full_name.keyword": {"order": "asc", "missing": "_last"}},
            {"profile_id": {"order": "asc"}},
        ]
    )

    aggregations = {
        response_name: {
            "terms": {
                "field": index_field,
                "size": FACET_SIZE,
                "order": [{"_count": "desc"}, {"_key": "asc"}],
            }
        }
        for response_name, index_field in FACET_FIELDS.items()
    }

    return {
        "from": offset,
        "size": criteria.page_size,
        "track_total_hits": True,
        "_source": SEARCH_RESULT_FIELDS,
        "query": query,
        "sort": sort,
        "aggs": aggregations,
    }
