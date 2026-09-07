from datetime import date

import pytest

from apps.profiles.models import Education, Experience, Profile, Skill
from apps.search.documents import profile_document_id, project_profile


def prefetched_profile(profile_id):
    return Profile.objects.prefetch_related("skills", "experiences", "educations").get(
        pk=profile_id
    )


@pytest.mark.django_db
def test_complete_profile_projection_is_deterministic_and_excludes_raw_payload():
    profile = Profile.objects.create(
        public_identifier="complete",
        full_name="  José   Example ",
        headline="Principal Engineer",
        location=" Lisbon ",
        summary="Builds\nsearch systems",
        raw_payload={
            "industry": " Software ",
            "location_country": " Portugal ",
            "job_company_name": "Current Co",
            "emails": "private@example.test",
            "secret": "must-not-appear",
        },
    )
    profile.skills.add(
        Skill.objects.create(name="Python"),
        Skill.objects.create(name="python"),
        Skill.objects.create(name="Café"),
        Skill.objects.create(name="Cafe"),
    )
    Experience.objects.create(
        profile=profile,
        title="Developer",
        company="Old Co",
        location="Paris",
        description="Legacy systems",
        started_at=date(2018, 1, 1),
        ended_at=date(2020, 1, 1),
        source_order=0,
    )
    Experience.objects.create(
        profile=profile,
        title="Engineer",
        company="Current Co",
        location="Lisbon",
        description="Search systems",
        started_at=date(2020, 2, 1),
        ended_at=None,
        source_order=1,
    )
    Education.objects.create(
        profile=profile,
        school="University B",
        degree="MSc",
        field_of_study="Computer Science",
        source_order=1,
    )
    Education.objects.create(
        profile=profile,
        school="University A",
        degree="BSc",
        field_of_study="Mathematics",
        source_order=0,
    )

    projected = project_profile(prefetched_profile(profile.pk))

    assert projected == {
        "profile_id": str(profile.pk),
        "full_name": "José Example",
        "job_title": "Principal Engineer",
        "job_titles": ["Principal Engineer", "Developer", "Engineer"],
        "skills": ["Cafe", "Python"],
        "industry": "Software",
        "location_name": "Lisbon",
        "country": "Portugal",
        "company": ["Current Co", "Old Co"],
        "summary": "Builds search systems",
        "experience_text": [
            "Developer | Old Co | Paris | Legacy systems",
            "Engineer | Current Co | Lisbon | Search systems",
        ],
        "education_text": [
            "University A | BSc | Mathematics",
            "University B | MSc | Computer Science",
        ],
    }
    assert "raw_payload" not in projected
    assert "private@example.test" not in repr(projected)
    assert profile_document_id(profile) == str(profile.pk)


@pytest.mark.django_db
def test_blank_and_nullable_profile_projection_uses_consistent_empty_values():
    profile = Profile.objects.create(
        public_identifier="minimal",
        first_name=" Ada ",
        last_name=" Lovelace ",
        raw_payload={
            "industry": "nan",
            "location_country": " null ",
            "job_company_name": "N/A",
        },
    )

    assert project_profile(prefetched_profile(profile.pk)) == {
        "profile_id": str(profile.pk),
        "full_name": "Ada Lovelace",
        "job_title": "",
        "job_titles": [],
        "skills": [],
        "industry": "",
        "location_name": "",
        "country": "",
        "company": [],
        "summary": "",
        "experience_text": [],
        "education_text": [],
    }


@pytest.mark.django_db
def test_projection_requires_prefetched_relations_to_prevent_accidental_n_plus_one_queries():
    profile = Profile.objects.create(public_identifier="not-prefetched", full_name="Test")

    with pytest.raises(ValueError, match="must be prefetched"):
        project_profile(profile)


def test_document_id_requires_a_saved_profile():
    with pytest.raises(ValueError, match="saved profile"):
        profile_document_id(Profile(public_identifier="unsaved"))
