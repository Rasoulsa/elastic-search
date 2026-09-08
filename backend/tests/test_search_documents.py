from datetime import date

import pytest

from apps.profiles.models import Education, Experience, Profile, Skill
from apps.profiles.serializers import ProfileDetailSerializer
from apps.search.documents import profile_document_id, project_profile


def prefetched_profile(profile_id):
    return Profile.objects.prefetch_related("skills", "experiences", "educations").get(
        pk=profile_id
    )


def valid_importer_payload():
    return {
        "experience": repr(
            [
                {
                    "title": {"name": "Engineer"},
                    "company": {
                        "name": "Example Co",
                        "industry": "Software",
                        "size": "201-500",
                    },
                },
                {
                    "title": {"name": "Earlier Engineer"},
                    "company": {"name": "Earlier Co", "industry": "Consulting"},
                    "end_date": "2020-01-01",
                },
            ]
        ),
        "location_names": "['Lisbon']",
        "countries": "['Portugal']",
        "location_name": "Lisbon",
        "location_country": "Portugal",
        "industry": "Software",
        "job_title": "Engineer",
        "job_company_name": "Example Co",
        "job_company_industry": "Software",
        "summary": "Builds search systems.",
        "_source_values": {"44": "Builds search systems."},
        "_importer": {
            "mapping_version": "canonical-v2",
            "layout": "reordered-block-45",
            "canonical_sources": {
                "industry": "experience[0].company.industry",
                "job_title": "experience[0].title.name",
                "job_company_name": "experience[0].company.name",
                "job_company_industry": "experience[0].company.industry",
                "location_name": "location_names[0]",
                "location_country": "countries[0]",
                "summary": "_source_values[44]",
            },
            "selected_experience_source_order": 0,
        },
    }


@pytest.mark.django_db
def test_complete_profile_projection_is_deterministic_and_excludes_raw_payload():
    profile = Profile.objects.create(
        public_identifier="complete",
        full_name="  José   Example ",
        headline="Principal Engineer",
        location=" Lisbon ",
        summary="Builds\nsearch systems",
        raw_payload={
            "experience": repr(
                [
                    {
                        "title": {"name": "Developer"},
                        "company": {"name": "Old Co", "industry": "Software"},
                    },
                    {
                        "is_primary": True,
                        "title": {"name": "Engineer"},
                        "company": {"name": "Current Co", "industry": "Software"},
                    },
                ]
            ),
            "location_names": "['Lisbon']",
            "countries": "['Portugal']",
            "location_name": "Lisbon",
            "industry": " Software ",
            "location_country": " Portugal ",
            "job_title": "Engineer",
            "job_company_name": "Current Co",
            "job_company_industry": "Software",
            "summary": "Builds\nsearch systems",
            "_source_values": {"44": "Builds\nsearch systems"},
            "_importer": {
                "mapping_version": "canonical-v2",
                "layout": "reordered-block-45",
                "canonical_sources": {
                    "industry": "experience[1].company.industry",
                    "job_title": "experience[1].title.name",
                    "job_company_name": "experience[1].company.name",
                    "job_company_industry": "experience[1].company.industry",
                    "location_country": "countries[0]",
                    "location_name": "location_names[0]",
                    "summary": "_source_values[44]",
                },
                "selected_experience_source_order": 1,
            },
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
        "job_title": "Engineer",
        "job_titles": ["Engineer", "Developer"],
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


@pytest.mark.django_db
def test_importer_projection_and_detail_share_selected_current_experience():
    profile = Profile.objects.create(
        public_identifier="selected-current",
        headline="Stale headline",
        location="Current City",
        raw_payload={
            "experience": repr(
                [
                    {
                        "title": {"name": "Old Title"},
                        "company": {"name": "Old Company", "industry": "Old Industry"},
                    },
                    {
                        "is_primary": True,
                        "title": {"name": "Selected Title"},
                        "company": {"name": "Selected Company", "industry": "Selected Industry"},
                    },
                ]
            ),
            "location_names": "['Current City']",
            "countries": "['Current Country']",
            "location_name": "Current City",
            "location_country": "Current Country",
            "industry": "Selected Industry",
            "job_title": "Selected Title",
            "job_company_name": "Selected Company",
            "_importer": {
                "mapping_version": "canonical-v2",
                "layout": "reordered-block-45",
                "canonical_sources": {
                    "industry": "experience[1].company.industry",
                    "job_title": "experience[1].title.name",
                    "job_company_name": "experience[1].company.name",
                    "location_name": "location_names[0]",
                    "location_country": "countries[0]",
                },
                "selected_experience_source_order": 1,
            },
        },
    )
    Experience.objects.create(
        profile=profile, title="Old Title", company="Old Company", source_order=0
    )
    Experience.objects.create(
        profile=profile,
        title="Selected Title",
        company="Selected Company",
        source_order=1,
    )

    projected = project_profile(prefetched_profile(profile.pk))
    detailed = ProfileDetailSerializer(profile).data

    assert projected["job_title"] == detailed["job_title"] == "Selected Title"
    assert projected["company"][0] == detailed["company"] == "Selected Company"
    assert projected["industry"] == detailed["industry"] == "Selected Industry"
    assert projected["location_name"] == detailed["location"] == "Current City"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("industry", "+1 (555) 010-0100"),
        ("industry", "123456"),
        ("industry", "[]"),
        ("location_country", "$50000 - $70000"),
        ("location_country", "201-500"),
        ("location_country", "2020-12-01"),
        ("location_country", "12.75"),
        ("job_company_name", "201-500"),
    ],
)
def test_projection_omits_structurally_invalid_canonical_metadata(field, value):
    profile = Profile.objects.create(
        public_identifier=f"invalid-{field}-{len(value)}",
        raw_payload={field: value, "_canonical_sources": {field: "synthetic"}},
    )

    projected = project_profile(prefetched_profile(profile.pk))

    if field == "industry":
        assert projected["industry"] == ""
    elif field == "location_country":
        assert projected["country"] == ""
    else:
        assert projected["company"] == []
    if value != "[]":
        assert value not in repr(projected)


@pytest.mark.django_db
def test_projection_rejects_corrupt_model_scalars_and_unvalidated_raw_fallbacks():
    profile = Profile.objects.create(
        public_identifier="invalid-model-scalars",
        headline="201-500",
        location="$50000 - $70000",
        summary="[{'school': {'name': 'Synthetic'}}]",
        raw_payload={
            "industry": "+1 (555) 010-0100",
            "location_country": "12.75",
            "job_company_name": "201-500",
        },
    )

    projected = project_profile(prefetched_profile(profile.pk))

    assert projected["job_title"] == ""
    assert projected["location_name"] == ""
    assert projected["summary"] == ""
    assert projected["industry"] == ""
    assert projected["country"] == ""
    assert projected["company"] == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "invalid_case",
    [
        "wrong-version",
        "missing-version",
        "unknown-layout",
        "non-allowlisted-path",
        "wrong-type",
        "inconsistent",
    ],
)
def test_projection_omits_derived_metadata_under_invalid_provenance(invalid_case):
    payload = valid_importer_payload()
    importer = payload["_importer"]
    if invalid_case == "wrong-version":
        importer["mapping_version"] = "canonical-v1"
    elif invalid_case == "missing-version":
        importer.pop("mapping_version")
    elif invalid_case == "unknown-layout":
        importer["layout"] = "reordered-block-999"
    elif invalid_case == "non-allowlisted-path":
        importer["canonical_sources"]["industry"] = "raw_payload.industry"
    elif invalid_case == "wrong-type":
        payload["experience"] = repr(
            [{"title": {"name": "Engineer"}, "company": {"name": ["Example Co"]}}]
        )
    else:
        payload["industry"] = "Different Industry"
    profile = Profile.objects.create(
        public_identifier=f"invalid-provenance-{invalid_case}",
        location="Lisbon",
        raw_payload=payload,
    )
    Experience.objects.create(profile=profile, title="Engineer", company="Example Co")

    projected = project_profile(prefetched_profile(profile.pk))

    assert projected["company"] == ["Example Co"]
    assert projected["industry"] == ""
    assert projected["country"] == ""
    assert "_importer" not in repr(projected)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "path", "value", "projected_field", "empty_value"),
    [
        ("industry", "experience[0].company.name", "Example Co", "industry", ""),
        (
            "job_company_name",
            "experience[0].company.industry",
            "Software",
            "company",
            ["Example Co"],
        ),
        ("job_title", "experience[0].company.name", "Example Co", "job_title", ""),
        ("location_country", "experience[0].company.size", "201-500", "country", ""),
        ("location_name", "experience[0].company.size", "201-500", "location_name", ""),
        ("summary", "experience[0].company.name", "Example Co", "summary", ""),
        ("job_title", "experience[1].title.name", "Earlier Engineer", "job_title", ""),
        ("industry", "location_names[0]", "Lisbon", "industry", ""),
    ],
)
def test_projection_rejects_cross_wired_provenance(
    field, path, value, projected_field, empty_value
):
    payload = valid_importer_payload()
    payload[field] = value
    payload["_importer"]["canonical_sources"][field] = path
    profile = Profile.objects.create(public_identifier=f"cross-wired-{field}", raw_payload=payload)
    Experience.objects.create(profile=profile, title="Engineer", company="Example Co")

    projected = project_profile(prefetched_profile(profile.pk))

    assert projected[projected_field] == empty_value
    assert "_importer" not in repr(projected)
    assert "canonical_sources" not in repr(projected)


@pytest.mark.django_db
@pytest.mark.parametrize("case", ["wrong-type", "unknown-field"])
def test_projection_invalid_provenance_types_and_fields_fail_closed(case):
    payload = valid_importer_payload()
    experiences = [
        {
            "title": {"name": "Engineer"},
            "company": {"name": "Example Co", "industry": "Software", "size": 500},
        }
    ]
    payload["experience"] = repr(experiences)
    payload["job_company_size"] = 500
    payload["_importer"]["canonical_sources"]["job_company_size"] = "experience[0].company.size"
    if case == "unknown-field":
        payload["unknown_field"] = "Example Co"
        payload["_importer"]["canonical_sources"]["unknown_field"] = "experience[0].company.name"
    profile = Profile.objects.create(
        public_identifier=f"invalid-projection-{case}", raw_payload=payload
    )

    projected = project_profile(prefetched_profile(profile.pk))

    assert all(
        projected[name] in ("", [])
        for name in ("job_title", "industry", "location_name", "country", "summary")
    )
    assert "_importer" not in repr(projected)
