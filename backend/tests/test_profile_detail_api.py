from datetime import date
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.profiles.models import Education, Experience, Profile, Skill


@pytest.fixture
def authenticated_client(db):
    user = get_user_model().objects.create_user(
        username="detail-reviewer", password="test-password"
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    return client


@pytest.fixture
def complete_profile(db):
    profile = Profile.objects.create(
        public_identifier="synthetic-public-id",
        linkedin_id="synthetic-linkedin-id",
        linkedin_username="example-profile",
        profile_url="https://www.linkedin.com/in/example-profile",
        full_name="Example Person",
        headline="Principal Engineer",
        location="Helsinki",
        summary="Builds reliable systems.",
        raw_payload={
            "experience": repr(
                [
                    {
                        "title": {"name": "Backend Engineer"},
                        "company": {"name": "Example Company", "industry": "Software"},
                    }
                ]
            ),
            "location_names": "['Helsinki']",
            "countries": "['Finland']",
            "location_name": "Helsinki",
            "industry": "Software",
            "location_country": "Finland",
            "job_title": "Backend Engineer",
            "job_company_name": "Example Company",
            "summary": "Builds reliable systems.",
            "_source_values": {"44": "Builds reliable systems."},
            "_importer": {
                "mapping_version": "canonical-v2",
                "layout": "reordered-block-45",
                "canonical_sources": {
                    "industry": "experience[0].company.industry",
                    "job_title": "experience[0].title.name",
                    "job_company_name": "experience[0].company.name",
                    "location_country": "countries[0]",
                    "location_name": "location_names[0]",
                    "summary": "_source_values[44]",
                },
                "selected_experience_source_order": 0,
            },
            "email": "private@example.test",
            "internal_fingerprint": "must-not-appear",
        },
    )
    profile.skills.add(Skill.objects.create(name="Django"), Skill.objects.create(name="Python"))
    Experience.objects.create(
        profile=profile,
        title="Backend Engineer",
        company="Example Company",
        location="Helsinki",
        description="Built APIs.",
        started_at=date(2022, 1, 1),
        source_order=0,
    )
    Education.objects.create(
        profile=profile,
        school="Example University",
        degree="MSc",
        field_of_study="Computer Science",
        started_at=date(2018, 1, 1),
        ended_at=date(2020, 1, 1),
        source_order=0,
    )
    return profile


def test_profile_detail_requires_jwt_authentication():
    response = APIClient().get(reverse("profile-detail", args=[1]))

    assert response.status_code == 401


@pytest.mark.django_db
def test_profile_detail_returns_public_fields_and_nested_relations(
    authenticated_client, complete_profile
):
    response = authenticated_client.get(reverse("profile-detail", args=[complete_profile.pk]))

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "id": complete_profile.pk,
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
                "ended_at": None,
            }
        ],
        "education": [
            {
                "school": "Example University",
                "degree": "MSc",
                "field_of_study": "Computer Science",
                "started_at": "2018-01-01",
                "ended_at": "2020-01-01",
            }
        ],
    }


@pytest.mark.django_db
def test_profile_detail_excludes_raw_payload_and_import_bookkeeping(
    authenticated_client, complete_profile
):
    response = authenticated_client.get(reverse("profile-detail", args=[complete_profile.pk]))

    serialized = response.content.decode()
    assert response.status_code == 200
    assert set(response.json()) == {
        "id",
        "linkedin_id",
        "linkedin_username",
        "profile_url",
        "full_name",
        "job_title",
        "company",
        "industry",
        "location",
        "country",
        "summary",
        "skills",
        "experiences",
        "education",
    }
    assert "raw_payload" not in serialized
    assert "private@example.test" not in serialized
    assert "internal_fingerprint" not in serialized
    assert "source_order" not in serialized
    assert "created_at" not in serialized


@pytest.mark.django_db
def test_unknown_profile_returns_404(authenticated_client):
    response = authenticated_client.get(reverse("profile-detail", args=[999999]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_profile_detail_does_not_contact_elasticsearch(authenticated_client, complete_profile):
    with patch("apps.search.services.get_gateway", side_effect=AssertionError("must not run")):
        response = authenticated_client.get(reverse("profile-detail", args=[complete_profile.pk]))

    assert response.status_code == 200


@pytest.mark.django_db
def test_profile_detail_uses_bounded_query_count(
    authenticated_client, complete_profile, django_assert_num_queries
):
    with django_assert_num_queries(5):
        response = authenticated_client.get(reverse("profile-detail", args=[complete_profile.pk]))

    assert response.status_code == 200


@pytest.mark.django_db
def test_profile_detail_omits_structurally_corrupt_scalar_fallbacks(authenticated_client):
    profile = Profile.objects.create(
        public_identifier="synthetic-corrupt-detail",
        headline="201-500",
        location="$50000 - $70000",
        summary="[{'school': {'name': 'Synthetic'}}]",
        raw_payload={
            "industry": "+1 (555) 010-0100",
            "location_country": "12.75",
            "job_company_name": "201-500",
            "_canonical_sources": {
                "industry": "synthetic",
                "location_country": "synthetic",
                "job_company_name": "synthetic",
            },
        },
    )

    response = authenticated_client.get(reverse("profile-detail", args=[profile.pk]))

    assert response.status_code == 200
    assert response.json()["job_title"] == ""
    assert response.json()["company"] == ""
    assert response.json()["industry"] == ""
    assert response.json()["location"] == ""
    assert response.json()["country"] == ""
    assert response.json()["summary"] == ""


@pytest.mark.django_db
def test_profile_detail_omits_derived_values_when_importer_provenance_is_invalid(
    authenticated_client,
):
    profile = Profile.objects.create(
        public_identifier="invalid-detail-provenance",
        location="Lisbon",
        raw_payload={
            "experience": repr(
                [
                    {
                        "title": {"name": "Engineer"},
                        "company": {"name": "Example Co", "industry": "Software"},
                    }
                ]
            ),
            "industry": "Software",
            "job_company_name": "Example Co",
            "_importer": {
                "mapping_version": "canonical-v1",
                "layout": "reordered-block-45",
                "canonical_sources": {"industry": "experience[0].company.industry"},
                "selected_experience_source_order": 0,
            },
        },
    )
    Experience.objects.create(profile=profile, title="Engineer", company="Example Co")

    response = authenticated_client.get(reverse("profile-detail", args=[profile.pk]))

    assert response.status_code == 200
    assert response.json()["company"] == ""
    assert response.json()["industry"] == ""
    assert response.json()["country"] == ""


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "path", "value", "response_field"),
    [
        ("industry", "experience[0].company.name", "Example Company", "industry"),
        ("job_company_name", "experience[0].company.industry", "Software", "company"),
        ("job_title", "experience[0].company.name", "Example Company", "job_title"),
        ("location_country", "experience[0].company.size", "201-500", "country"),
        ("location_name", "experience[0].company.size", "201-500", "location"),
        ("summary", "experience[0].company.name", "Example Company", "summary"),
        ("job_title", "experience[1].title.name", "Earlier Engineer", "job_title"),
        ("industry", "location_names[0]", "Helsinki", "industry"),
    ],
)
def test_profile_detail_rejects_cross_wired_provenance(
    authenticated_client, field, path, value, response_field
):
    payload = {
        "experience": repr(
            [
                {
                    "is_primary": True,
                    "title": {"name": "Backend Engineer"},
                    "company": {
                        "name": "Example Company",
                        "industry": "Software",
                        "size": "201-500",
                    },
                },
                {
                    "title": {"name": "Earlier Engineer"},
                    "company": {"name": "Earlier Company", "industry": "Consulting"},
                    "end_date": "2020-01-01",
                },
            ]
        ),
        "location_names": "['Helsinki']",
        "countries": "['Finland']",
        field: value,
        "_importer": {
            "mapping_version": "canonical-v2",
            "layout": "reordered-block-45",
            "canonical_sources": {field: path},
            "selected_experience_source_order": 0,
        },
    }
    profile = Profile.objects.create(
        public_identifier=f"cross-wired-detail-{field}-{response_field}", raw_payload=payload
    )

    response = authenticated_client.get(reverse("profile-detail", args=[profile.pk]))
    body = response.json()

    assert response.status_code == 200
    assert body[response_field] == ""
    assert "detail" not in body
    assert "_importer" not in repr(body)
    assert "canonical_sources" not in repr(body)


@pytest.mark.django_db
@pytest.mark.parametrize("case", ["wrong-type", "unknown-field"])
def test_profile_detail_invalid_provenance_types_and_fields_fail_closed(authenticated_client, case):
    payload = {
        "experience": repr(
            [
                {
                    "is_primary": True,
                    "title": {"name": "Engineer"},
                    "company": {"name": "Example", "size": 500},
                }
            ]
        ),
        "job_company_size": 500,
        "_importer": {
            "mapping_version": "canonical-v2",
            "layout": "reordered-block-45",
            "canonical_sources": {"job_company_size": "experience[0].company.size"},
            "selected_experience_source_order": 0,
        },
    }
    if case == "unknown-field":
        payload["unknown_field"] = "Example"
        payload["_importer"]["canonical_sources"]["unknown_field"] = "experience[0].company.name"
    profile = Profile.objects.create(
        public_identifier=f"invalid-detail-{case}", raw_payload=payload
    )

    response = authenticated_client.get(reverse("profile-detail", args=[profile.pk]))
    body = response.json()

    assert response.status_code == 200
    assert all(body[name] == "" for name in ("job_title", "company", "industry", "country"))
    assert "detail" not in body
    assert "_importer" not in repr(body)


def test_openapi_documents_profile_detail_authentication_and_responses():
    response = APIClient().get(reverse("schema"), HTTP_ACCEPT="application/json")
    schema = response.json()
    operation = schema["paths"]["/api/v1/profiles/{id}/"]["get"]

    assert response.status_code == 200
    assert operation.get("security")
    assert {"200", "401", "404"}.issubset(operation["responses"])
    for response_status in ("200", "401", "404"):
        assert "content" in operation["responses"][response_status]
    response_schema_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]
    response_schema = schema["components"]["schemas"][
        response_schema_ref["$ref"].rsplit("/", 1)[-1]
    ]
    assert {
        "id",
        "full_name",
        "skills",
        "experiences",
        "education",
    }.issubset(response_schema["properties"])
