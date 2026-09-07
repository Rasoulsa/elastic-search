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
            "industry": "Software",
            "location_country": "Finland",
            "job_company_name": "Example Company",
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
        "job_title": "Principal Engineer",
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
