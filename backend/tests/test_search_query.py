import pytest

from apps.search.query import (
    FACET_FIELDS,
    FACET_SIZE,
    MAX_RESULT_WINDOW,
    SEARCH_FIELDS,
    SearchCriteria,
    SearchWindowError,
    build_profile_search_query,
)


def build(**overrides):
    criteria = SearchCriteria(**overrides)
    return build_profile_search_query(criteria)


def test_no_keyword_uses_match_all_and_deterministic_sorting():
    request = build()

    assert request["query"] == {"match_all": {}}
    assert request["track_total_hits"] is True
    assert request["sort"] == [
        {"full_name.keyword": {"order": "asc", "missing": "_last"}},
        {"profile_id": {"order": "asc"}},
    ]


def test_keyword_uses_boosted_and_multi_match_and_score_sorting():
    request = build(q="search engineer")
    multi_match = request["query"]["bool"]["must"][0]["multi_match"]

    assert multi_match == {
        "query": "search engineer",
        "fields": SEARCH_FIELDS,
        "type": "best_fields",
        "operator": "and",
    }
    assert "full_name^4" in multi_match["fields"]
    assert "job_title^4" in multi_match["fields"]
    assert "skills^3" in multi_match["fields"]
    assert request["sort"][0] == {"_score": {"order": "desc"}}


@pytest.mark.parametrize(
    ("parameter", "field"),
    [
        ("skill", "skills.keyword"),
        ("job_title", "job_title.keyword"),
        ("industry", "industry.keyword"),
        ("country", "country.keyword"),
        ("company", "company.keyword"),
    ],
)
def test_each_exact_filter_uses_its_normalized_keyword_field(parameter, field):
    request = build(filters={parameter: ["  Café  SEARCH  "]})

    assert request["query"]["bool"]["filter"] == [
        {
            "bool": {
                "should": [{"term": {field: "Café SEARCH"}}],
                "minimum_should_match": 1,
            }
        }
    ]


def test_repeated_values_use_bool_should_or_semantics_and_deduplication():
    request = build(filters={"skill": [" Python ", "Django", "PYTHON", "  "]})

    assert request["query"]["bool"]["filter"] == [
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


def test_different_filter_categories_use_separate_and_filters_in_stable_order():
    request = build(filters={"company": ["Example Co"], "skill": ["Python"]})

    assert request["query"]["bool"]["must"] == [{"match_all": {}}]
    assert request["query"]["bool"]["filter"] == [
        {
            "bool": {
                "should": [{"term": {"skills.keyword": "Python"}}],
                "minimum_should_match": 1,
            }
        },
        {
            "bool": {
                "should": [{"term": {"company.keyword": "Example Co"}}],
                "minimum_should_match": 1,
            }
        },
    ]


def test_keyword_and_filters_share_one_bool_query():
    request = build(q="backend", filters={"country": ["Finland"]})

    assert request["query"]["bool"]["must"][0]["multi_match"]["query"] == "backend"
    assert request["query"]["bool"]["filter"] == [
        {
            "bool": {
                "should": [{"term": {"country.keyword": "Finland"}}],
                "minimum_should_match": 1,
            }
        }
    ]


def test_pagination_calculates_offset_and_size():
    request = build(page=3, page_size=25)

    assert request["from"] == 50
    assert request["size"] == 25


def test_facets_use_bounded_normalized_keyword_aggregations():
    request = build()

    assert request["aggs"] == {
        name: {
            "terms": {
                "field": field,
                "size": FACET_SIZE,
                "order": [{"_count": "desc"}, {"_key": "asc"}],
            }
        }
        for name, field in FACET_FIELDS.items()
    }


def test_last_page_inside_result_window_is_supported():
    request = build(page=MAX_RESULT_WINDOW // 100, page_size=100)

    assert request["from"] + request["size"] == MAX_RESULT_WINDOW


def test_page_beyond_result_window_is_rejected_before_execution():
    with pytest.raises(SearchWindowError, match="supported search result window"):
        build(page=(MAX_RESULT_WINDOW // 100) + 1, page_size=100)
