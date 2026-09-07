from django.conf import settings

from apps.search.index import INDEX_MAPPING, INDEX_NAME, INDEX_SETTINGS, NORMALIZER_NAME


def test_index_contract_has_the_exact_versioned_name_and_explicit_mapping():
    assert INDEX_NAME == "linkedin_profiles_v1"
    assert settings.ELASTICSEARCH_INDEX == INDEX_NAME
    assert INDEX_MAPPING["dynamic"] == "strict"
    assert set(INDEX_MAPPING["properties"]) == {
        "profile_id",
        "full_name",
        "job_title",
        "job_titles",
        "skills",
        "industry",
        "location_name",
        "country",
        "company",
        "summary",
        "experience_text",
        "education_text",
    }
    assert INDEX_MAPPING["properties"]["profile_id"] == {"type": "keyword"}


def test_exact_filter_fields_use_the_lowercase_ascii_normalizer():
    normalizer = INDEX_SETTINGS["analysis"]["normalizer"][NORMALIZER_NAME]
    assert normalizer == {
        "type": "custom",
        "filter": ["lowercase", "asciifolding"],
    }

    for field_name in (
        "full_name",
        "job_title",
        "job_titles",
        "skills",
        "industry",
        "country",
        "company",
    ):
        field = INDEX_MAPPING["properties"][field_name]
        assert field["type"] == "text"
        assert field["fields"]["keyword"] == {
            "type": "keyword",
            "normalizer": NORMALIZER_NAME,
        }

    for field_name in ("location_name", "summary", "experience_text", "education_text"):
        assert INDEX_MAPPING["properties"][field_name] == {"type": "text"}
