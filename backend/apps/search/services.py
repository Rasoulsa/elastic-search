from collections.abc import Mapping

from .gateway import SearchIndexError, get_gateway
from .query import FACET_FIELDS, SearchCriteria, build_profile_search_query


class SearchUnavailableError(Exception):
    """Search cannot currently return a trustworthy application response."""


def _mapping(value, name: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise SearchUnavailableError(f"Invalid {name} response shape.")
    return value


def _non_negative_integer(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SearchUnavailableError(f"Invalid {name} response value.")
    return value


def _text(value, name: str) -> str:
    if not isinstance(value, str):
        raise SearchUnavailableError(f"Invalid {name} response value.")
    return value


def _optional_text(mapping: Mapping, key: str, name: str) -> str:
    value = mapping.get(key)
    if value is None:
        return ""
    return _text(value, name)


def _text_list(value, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SearchUnavailableError(f"Invalid {name} response value.")
    return value


def _optional_text_list(mapping: Mapping, key: str, name: str) -> list[str]:
    value = mapping.get(key)
    if value is None:
        return []
    return _text_list(value, name)


def _translate_result(hit) -> dict:
    hit_mapping = _mapping(hit, "hit")
    source = _mapping(hit_mapping.get("_source"), "hit source")
    profile_id = _text(source.get("profile_id"), "profile id")
    try:
        public_id = int(profile_id)
    except (TypeError, ValueError) as exc:
        raise SearchUnavailableError("Invalid profile id response value.") from exc
    if public_id < 1:
        raise SearchUnavailableError("Invalid profile id response value.")

    companies = _optional_text_list(source, "company", "company")
    return {
        "id": public_id,
        "full_name": _optional_text(source, "full_name", "full name"),
        "job_title": _optional_text(source, "job_title", "job title"),
        "company": companies[0] if companies else "",
        "industry": _optional_text(source, "industry", "industry"),
        "country": _optional_text(source, "country", "country"),
        "skills": _optional_text_list(source, "skills", "skills"),
        "summary": _optional_text(source, "summary", "summary"),
    }


def _translate_facets(raw_response: Mapping) -> dict:
    aggregations = _mapping(raw_response.get("aggregations"), "aggregations")
    facets = {}
    for response_name in FACET_FIELDS:
        aggregation = _mapping(aggregations.get(response_name), f"{response_name} aggregation")
        buckets = aggregation.get("buckets")
        if not isinstance(buckets, list):
            raise SearchUnavailableError(f"Invalid {response_name} buckets response shape.")
        translated = []
        for bucket in buckets:
            bucket_mapping = _mapping(bucket, f"{response_name} bucket")
            translated.append(
                {
                    "value": _text(bucket_mapping.get("key"), f"{response_name} bucket key"),
                    "count": _non_negative_integer(
                        bucket_mapping.get("doc_count"),
                        f"{response_name} bucket count",
                    ),
                }
            )
        facets[response_name] = translated
    return facets


def translate_search_response(raw_response, criteria: SearchCriteria) -> dict:
    response = _mapping(raw_response, "search")
    hits = _mapping(response.get("hits"), "hits")
    total = _mapping(hits.get("total"), "total hits")
    if total.get("relation") != "eq":
        raise SearchUnavailableError("Invalid total hits relation.")
    count = _non_negative_integer(total.get("value"), "total hits")
    raw_hits = hits.get("hits")
    if not isinstance(raw_hits, list):
        raise SearchUnavailableError("Invalid hits response shape.")

    return {
        "count": count,
        "page": criteria.page,
        "page_size": criteria.page_size,
        "total_pages": (count + criteria.page_size - 1) // criteria.page_size,
        "results": [_translate_result(hit) for hit in raw_hits],
        "facets": _translate_facets(response),
    }


def search_profiles(criteria: SearchCriteria) -> dict:
    request = build_profile_search_query(criteria)
    gateway = get_gateway()
    try:
        raw_response = gateway.search(request)
        return translate_search_response(raw_response, criteria)
    except SearchIndexError as exc:
        raise SearchUnavailableError("Profile search is unavailable.") from exc
    finally:
        gateway.close()
