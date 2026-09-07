from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.search.gateway import SearchIndexError
from apps.search.query import DEFAULT_PAGE_SIZE, FACET_FIELDS, MAX_RESULT_WINDOW


def empty_aggregations():
    return {name: {"buckets": []} for name in FACET_FIELDS}


def search_response(
    *, count=1, hits=None, aggregations=None, include_metadata=False, relation="eq"
):
    if hits is None:
        hits = [
            {
                "_index": "private-index-name",
                "_score": 12.5,
                "sort": [12.5, "example person", "7"],
                "_source": {
                    "profile_id": "7",
                    "full_name": "Example Person",
                    "job_title": "Backend Engineer",
                    "company": ["Example Company", "Previous Company"],
                    "industry": "Software",
                    "country": "Finland",
                    "skills": ["Django", "Python"],
                    "summary": "Builds search systems.",
                },
            }
        ]
    total = {"value": count}
    if relation is not None:
        total["relation"] = relation
    response = {
        "hits": {"total": total, "hits": hits},
        "aggregations": aggregations if aggregations is not None else empty_aggregations(),
    }
    if include_metadata:
        response.update({"took": 4, "_shards": {"failed": 0}})
    return response


@pytest.fixture
def authenticated_client(db):
    user = get_user_model().objects.create_user(
        username="search-reviewer", password="test-password"
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    return client


@pytest.fixture
def gateway():
    gateway = Mock()
    gateway.search.return_value = search_response()
    return gateway


def test_search_requires_jwt_authentication():
    with patch("apps.search.services.get_gateway") as get_gateway:
        response = APIClient().get(reverse("profile-search"))

    assert response.status_code == 401
    get_gateway.assert_not_called()


@pytest.mark.django_db
def test_invalid_bearer_token_returns_401_without_search():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer invalid-access-token")
    with patch("apps.search.services.get_gateway") as get_gateway:
        response = client.get(reverse("profile-search"))

    assert response.status_code == 401
    get_gateway.assert_not_called()


@pytest.mark.django_db
def test_expired_bearer_token_returns_401_without_search(db):
    user = get_user_model().objects.create_user(username="expired-search-user")
    token = AccessToken.for_user(user)
    token["exp"] = int((timezone.now() - timedelta(minutes=1)).timestamp())
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    with patch("apps.search.services.get_gateway") as get_gateway:
        response = client.get(reverse("profile-search"))

    assert response.status_code == 401
    get_gateway.assert_not_called()


@pytest.mark.django_db
def test_keyword_only_search_returns_stable_application_response(authenticated_client, gateway):
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(reverse("profile-search"), {"q": " backend engineer "})

    assert response.status_code == 200
    assert response.json() == {
        "count": 1,
        "page": 1,
        "page_size": DEFAULT_PAGE_SIZE,
        "total_pages": 1,
        "results": [
            {
                "id": 7,
                "full_name": "Example Person",
                "job_title": "Backend Engineer",
                "company": "Example Company",
                "industry": "Software",
                "country": "Finland",
                "skills": ["Django", "Python"],
                "summary": "Builds search systems.",
            }
        ],
        "facets": {name: [] for name in FACET_FIELDS},
    }
    request = gateway.search.call_args.args[0]
    assert request["query"]["bool"]["must"][0]["multi_match"]["query"] == "backend engineer"


@pytest.mark.django_db
def test_filter_only_search_uses_exact_keyword_filter(authenticated_client, gateway):
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(reverse("profile-search"), {"skill": " Python "})

    assert response.status_code == 200
    request = gateway.search.call_args.args[0]
    assert request["query"] == {
        "bool": {
            "must": [{"match_all": {}}],
            "filter": [
                {
                    "bool": {
                        "should": [{"term": {"skills.keyword": "Python"}}],
                        "minimum_should_match": 1,
                    }
                }
            ],
        }
    }


@pytest.mark.django_db
def test_combined_keyword_and_filter_categories_use_and_semantics(authenticated_client, gateway):
    url = f"{reverse('profile-search')}?q=engineer&country=Finland&company=Example%20Company"
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(url)

    assert response.status_code == 200
    query = gateway.search.call_args.args[0]["query"]["bool"]
    assert query["must"][0]["multi_match"]["query"] == "engineer"
    assert query["filter"] == [
        {
            "bool": {
                "should": [{"term": {"country.keyword": "Finland"}}],
                "minimum_should_match": 1,
            }
        },
        {
            "bool": {
                "should": [{"term": {"company.keyword": "Example Company"}}],
                "minimum_should_match": 1,
            }
        },
    ]


@pytest.mark.django_db
def test_repeated_same_filter_values_use_or_and_are_deduplicated(authenticated_client, gateway):
    url = f"{reverse('profile-search')}?skill=Python&skill=Django&skill=PYTHON"
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(url)

    assert response.status_code == 200
    filters = gateway.search.call_args.args[0]["query"]["bool"]["filter"]
    assert filters == [
        {
            "bool": {
                "should": [
                    {"term": {"skills.keyword": "Python"}},
                    {"term": {"skills.keyword": "Django"}},
                ],
                "minimum_should_match": 1,
            }
        }
    ]


@pytest.mark.django_db
def test_blank_repeated_filter_values_are_absent_before_the_value_limit(
    authenticated_client, gateway
):
    blank_filters = "&".join("skill=%20" for _index in range(25))
    url = f"{reverse('profile-search')}?{blank_filters}"
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(url)

    assert response.status_code == 200
    assert gateway.search.call_args.args[0]["query"] == {"match_all": {}}


@pytest.mark.django_db
def test_no_results_has_zero_total_pages(authenticated_client, gateway):
    gateway.search.return_value = search_response(count=0, hits=[])
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(reverse("profile-search"))

    assert response.status_code == 200
    assert response.json()["count"] == 0
    assert response.json()["total_pages"] == 0
    assert response.json()["results"] == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("count", "page_size", "expected_total_pages"),
    [(5, 20, 1), (20, 20, 1), (40, 20, 2), (41, 20, 3)],
)
def test_valid_exact_totals_produce_exact_total_pages(
    authenticated_client, gateway, count, page_size, expected_total_pages
):
    gateway.search.return_value = search_response(count=count)
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(reverse("profile-search"), {"page_size": page_size})

    assert response.status_code == 200
    assert response.json()["count"] == count
    assert response.json()["total_pages"] == expected_total_pages


@pytest.mark.django_db
def test_pagination_uses_total_matching_count_and_correct_total_pages(
    authenticated_client, gateway
):
    gateway.search.return_value = search_response(count=41)
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(reverse("profile-search"), {"page": 3, "page_size": 20})

    assert response.status_code == 200
    assert response.json()["count"] == 41
    assert response.json()["page"] == 3
    assert response.json()["total_pages"] == 3
    assert gateway.search.call_args.args[0]["from"] == 40


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("parameters", "field"),
    [
        ({"page": 0}, "page"),
        ({"page": "not-a-number"}, "page"),
        ({"page_size": 0}, "page_size"),
        ({"page_size": 101}, "page_size"),
        ({"page": (MAX_RESULT_WINDOW // 100) + 1, "page_size": 100}, "page"),
    ],
)
def test_invalid_pagination_returns_stable_400_without_search(
    authenticated_client, gateway, parameters, field
):
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(reverse("profile-search"), parameters)

    assert response.status_code == 400
    assert field in response.json()
    gateway.search.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query_string",
    [
        "q=python&q=django",
        "q=%20&q=%20",
        "q=python&q=python",
        "page=1&page=2",
        "page=1&page=1",
        "page_size=20&page_size=50",
    ],
)
def test_repeated_scalar_parameters_return_400_without_search(
    authenticated_client, gateway, query_string
):
    with patch("apps.search.services.get_gateway", return_value=gateway) as get_gateway:
        response = authenticated_client.get(f"{reverse('profile-search')}?{query_string}")

    assert response.status_code == 400
    assert any(field in response.json() for field in ("q", "page", "page_size"))
    get_gateway.assert_not_called()
    gateway.search.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("parameters", "field"),
    [
        ({"q": "q" * 501}, "q"),
        ({"skill": "s" * 201}, "skill"),
    ],
)
def test_oversized_query_or_filter_returns_400(authenticated_client, gateway, parameters, field):
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(reverse("profile-search"), parameters)

    assert response.status_code == 400
    assert field in response.json()
    gateway.search.assert_not_called()


@pytest.mark.django_db
def test_facets_are_translated_to_stable_value_and_count_buckets(authenticated_client, gateway):
    aggregations = {
        "skills": {"buckets": [{"key": "python", "doc_count": 42}]},
        "job_titles": {"buckets": [{"key": "engineer", "doc_count": 20}]},
        "industries": {"buckets": []},
        "countries": {"buckets": [{"key": "finland", "doc_count": 8}]},
        "companies": {"buckets": []},
    }
    gateway.search.return_value = search_response(aggregations=aggregations)
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(reverse("profile-search"))

    assert response.status_code == 200
    assert response.json()["facets"]["skills"] == [{"value": "python", "count": 42}]
    assert response.json()["facets"]["countries"] == [{"value": "finland", "count": 8}]
    assert gateway.search.call_count == 1


@pytest.mark.django_db
def test_raw_elasticsearch_metadata_is_not_exposed(authenticated_client, gateway):
    gateway.search.return_value = search_response(include_metadata=True)
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(reverse("profile-search"))

    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"count", "page", "page_size", "total_pages", "results", "facets"}
    serialized = response.content.decode()
    assert all(name not in serialized for name in ("_index", "_score", "_shards", "sort", "took"))


@pytest.mark.django_db
@pytest.mark.parametrize(
    "error_message",
    ["Connection refused by http://private-host:9200", "index_not_found_exception: private-index"],
)
def test_elasticsearch_failures_return_safe_503_and_close_client(
    authenticated_client, gateway, error_message
):
    gateway.search.side_effect = SearchIndexError(error_message)
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(reverse("profile-search"))

    assert response.status_code == 503
    assert response.json() == {
        "code": "search_unavailable",
        "detail": "Profile search is temporarily unavailable.",
    }
    assert "private" not in response.content.decode()
    gateway.close.assert_called_once_with()


@pytest.mark.django_db
def test_malformed_gateway_response_returns_safe_503_and_closes_client(
    authenticated_client, gateway
):
    gateway.search.return_value = {"unexpected": "private implementation detail"}
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(reverse("profile-search"))

    assert response.status_code == 503
    assert response.json()["code"] == "search_unavailable"
    assert "private implementation detail" not in response.content.decode()
    gateway.close.assert_called_once_with()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "malformed_response",
    [
        {},
        {"hits": []},
        {"hits": {"total": {"value": 1, "relation": "eq"}}},
        {"hits": {"total": {"value": 1, "relation": "eq"}, "hits": {}}},
        {"hits": {"total": {"value": 1, "relation": "eq"}, "hits": []}},
        {"hits": {"total": {"value": 1, "relation": "gte"}, "hits": []}},
        {"hits": {"total": {"value": 1}, "hits": []}},
        {"hits": {"total": [], "hits": []}},
        {
            "hits": {
                "total": {"value": 1, "relation": "eq"},
                "hits": [{"_source": []}],
            }
        },
        {
            "hits": {
                "total": {"value": 1, "relation": "eq"},
                "hits": [{"_source": {"profile_id": "7"}}],
            },
            "aggregations": {},
        },
        {
            "hits": {
                "total": {"value": 1, "relation": "eq"},
                "hits": [{"_source": {"profile_id": "7"}}],
            },
            "aggregations": {"skills": {"buckets": "invalid"}},
        },
        {
            "hits": {
                "total": {"value": 1, "relation": "eq"},
                "hits": [{"_source": {"profile_id": "7"}}],
            },
            "aggregations": {
                **empty_aggregations(),
                "skills": {"buckets": [{"key": 7, "doc_count": 1}]},
            },
        },
        {
            "hits": {
                "total": {"value": 1, "relation": "eq"},
                "hits": [{"_source": {"profile_id": "7"}}],
            },
            "aggregations": {
                **empty_aggregations(),
                "skills": {"buckets": [{"key": "python", "doc_count": "1"}]},
            },
        },
    ],
)
def test_malformed_required_response_structures_return_safe_503(
    authenticated_client, gateway, malformed_response
):
    gateway.search.return_value = malformed_response
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(reverse("profile-search"))

    assert response.status_code == 503
    assert response.json() == {
        "code": "search_unavailable",
        "detail": "Profile search is temporarily unavailable.",
    }
    gateway.close.assert_called_once_with()


@pytest.mark.django_db
def test_optional_profile_fields_use_safe_defaults(authenticated_client, gateway):
    gateway.search.return_value = search_response(hits=[{"_source": {"profile_id": "7"}}])
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(reverse("profile-search"))

    assert response.status_code == 200
    assert response.json()["results"] == [
        {
            "id": 7,
            "full_name": "",
            "job_title": "",
            "company": "",
            "industry": "",
            "country": "",
            "skills": [],
            "summary": "",
        }
    ]


@pytest.mark.django_db
def test_internally_created_client_closes_after_success(authenticated_client, gateway):
    with patch("apps.search.services.get_gateway", return_value=gateway):
        response = authenticated_client.get(reverse("profile-search"))

    assert response.status_code == 200
    gateway.close.assert_called_once_with()


def test_openapi_documents_search_authentication_parameters_and_responses():
    response = APIClient().get(reverse("schema"), HTTP_ACCEPT="application/json")
    schema = response.json()
    operation = schema["paths"]["/api/v1/profiles/search/"]["get"]

    assert response.status_code == 200
    assert operation.get("security")
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert set(parameters) == {
        "q",
        "skill",
        "job_title",
        "industry",
        "country",
        "company",
        "page",
        "page_size",
    }
    assert parameters["skill"]["schema"]["type"] == "array"
    assert "OR semantics" in parameters["skill"]["description"]
    for name in ("q", "page", "page_size"):
        assert parameters[name]["schema"]["type"] in {"string", "integer"}
    assert parameters["q"]["schema"]["type"] == "string"
    assert parameters["page"]["schema"]["default"] == 1
    assert parameters["page_size"]["schema"]["default"] == DEFAULT_PAGE_SIZE
    assert parameters["page_size"]["schema"]["maximum"] == 100
    for name in ("skill", "job_title", "industry", "country", "company"):
        assert parameters[name]["schema"]["type"] == "array"
        assert "repeat" in parameters[name]["description"].lower()
    assert {"200", "400", "401", "503"}.issubset(operation["responses"])
    for response_status in ("200", "400", "401", "503"):
        assert "content" in operation["responses"][response_status]
    search_schema = schema["components"]["schemas"]
    response_schema_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]
    response_schema = search_schema[response_schema_ref["$ref"].rsplit("/", 1)[-1]]
    assert {"count", "page", "page_size", "total_pages", "results", "facets"}.issubset(
        response_schema["properties"]
    )
