import csv
import io
import re
from unittest.mock import Mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, IntegrityError, transaction

from apps.profiles.management.commands.import_profiles import (
    EXPECTED_HEADER,
    LAYOUT_BY_NAME,
    SOURCE_LAYOUTS,
    Command,
    ImportStats,
)
from apps.profiles.models import Education, Experience, Profile, Skill


def make_row(**overrides):
    row = {name: "" for name in EXPECTED_HEADER}
    row.update(
        {
            "full_name": "Ada Lovelace",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "linkedin_id": "123",
            "linkedin_username": "Ada.Lovelace",
            "linkedin_url": "https://www.linkedin.com/in/Ada.Lovelace/?trk=sample",
            "skills": "[]",
            "experience": "[]",
            "education": "[]",
        }
    )
    row.update(overrides)
    return [row[name] for name in EXPECTED_HEADER]


def write_csv(path, rows, header=EXPECTED_HEADER):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def source_row_for_layout(canonical_row, layout_name):
    layout = LAYOUT_BY_NAME[layout_name]
    source_row = [""] * len(EXPECTED_HEADER)
    for canonical_position, source_position in enumerate(layout.canonical_to_source):
        if source_position is not None:
            source_row[source_position] = canonical_row[canonical_position]
    return source_row


def run_import(path):
    output = io.StringIO()
    call_command("import_profiles", path=path, stdout=output)
    return output.getvalue()


def count(output, name):
    return int(re.search(rf"^  {name}: (\d+)$", output, re.MULTILINE).group(1))


def experience_item(title="Engineer", company="Analytical Engines", **values):
    item = {"title": {"name": title}, "company": {"name": company}}
    item.update(values)
    return item


def education_item(school="University", **values):
    item = {"school": {"name": school}}
    item.update(values)
    return item


def normalize_json(value):
    if isinstance(value, dict):
        return tuple((key, normalize_json(item)) for key, item in sorted(value.items()))
    if isinstance(value, list):
        return tuple(normalize_json(item) for item in value)
    return value


def ordered_snapshot_rows(model, fields, order_by):
    rows = model.objects.order_by(*order_by).values(*fields)
    return tuple(tuple((field, normalize_json(row[field])) for field in fields) for row in rows)


def persisted_import_snapshot():
    profile_fields = tuple(field.attname for field in Profile._meta.concrete_fields)
    skill_fields = tuple(field.attname for field in Skill._meta.concrete_fields)
    experience_fields = tuple(field.attname for field in Experience._meta.concrete_fields)
    education_fields = tuple(field.attname for field in Education._meta.concrete_fields)
    through = Profile.skills.through
    through_fields = tuple(field.attname for field in through._meta.concrete_fields)

    return {
        "profiles": ordered_snapshot_rows(Profile, profile_fields, ("pk",)),
        "skills": ordered_snapshot_rows(Skill, skill_fields, ("pk",)),
        "profile_skills": ordered_snapshot_rows(
            through, through_fields, ("profile_id", "skill_id", "pk")
        ),
        "experiences": ordered_snapshot_rows(
            Experience, experience_fields, ("profile_id", "source_order", "pk")
        ),
        "education": ordered_snapshot_rows(
            Education, education_fields, ("profile_id", "source_order", "pk")
        ),
        "counts": {
            "profiles": Profile.objects.count(),
            "skills": Skill.objects.count(),
            "profile_skills": through.objects.count(),
            "experiences": Experience.objects.count(),
            "education": Education.objects.count(),
        },
    }


def snapshot_values(snapshot, section, field):
    return tuple(dict(row)[field] for row in snapshot[section])


@pytest.mark.django_db
def test_header_and_missing_file_fail(tmp_path):
    invalid = tmp_path / "invalid.csv"
    write_csv(invalid, [], header=("full_name",))
    with pytest.raises(CommandError, match="Invalid or missing header"):
        run_import(invalid)
    with pytest.raises(CommandError, match="Dataset file not found"):
        run_import(tmp_path / "missing.csv")


@pytest.mark.django_db
def test_malformed_width_is_quarantined_without_persistence(tmp_path):
    path = tmp_path / "profiles.txt"
    write_csv(path, [make_row()[:-1]])

    output = run_import(path)

    assert Profile.objects.count() == 0
    assert "malformed_width_records: 1" in output
    assert "STRUCTURAL_WIDTH" in output


@pytest.mark.django_db
def test_legacy_reordered_layout_maps_canonical_fields_and_children(tmp_path):
    path = tmp_path / "profiles.txt"
    canonical_row = make_row(
        industry="Software",
        job_title="Principal Engineer",
        job_company_name="Analytical Engines",
        job_company_size="201-500",
        location_name="London",
        location_country="United Kingdom",
        summary="Builds reliable machines.",
        skills="['Python', 'SQL']",
        experience=str([experience_item("Principal Engineer")]),
        education=str([education_item("University")]),
    )
    write_csv(path, [source_row_for_layout(canonical_row, "legacy-facebook-appended-77")])

    output = run_import(path)
    profile = Profile.objects.get()

    assert profile.headline == "Principal Engineer"
    assert profile.location == "London"
    assert profile.summary == "Builds reliable machines."
    assert list(profile.skills.values_list("name", flat=True)) == ["python", "sql"]
    assert profile.experiences.get().title == "Principal Engineer"
    assert profile.educations.get().school == "University"
    assert profile.raw_payload["industry"] == "Software"
    assert profile.raw_payload["job_company_name"] == "Analytical Engines"
    assert profile.raw_payload["job_company_size"] == "201-500"
    assert profile.raw_payload["location_country"] == "United Kingdom"
    assert "legacy-facebook-appended-77" in output


@pytest.mark.parametrize("layout_name", [layout.name for layout in SOURCE_LAYOUTS])
def test_every_recognized_layout_maps_structured_fields_deterministically(layout_name):
    canonical_row = make_row(
        summary="A scalar summary",
        skills="['Python']",
        experience=str([experience_item()]),
        education=str([education_item()]),
    )

    row = source_row_for_layout(canonical_row, layout_name)
    layout, reason = Command()._detect_layout(row)

    assert reason == ""
    assert layout.name == layout_name


@pytest.mark.django_db
def test_corrected_import_repairs_existing_mis_mapped_profile_and_is_idempotent(tmp_path):
    profile = Profile.objects.create(
        public_identifier="linkedin:id:123",
        full_name="Ada Lovelace",
        first_name="Ada",
        last_name="Lovelace",
        headline="201-500",
        summary=str([education_item("Wrong Summary")]),
        linkedin_id="123",
        linkedin_username="ada.lovelace",
        profile_url="https://www.linkedin.com/in/ada.lovelace",
        raw_payload={
            "industry": "[]",
            "job_company_name": "201-500",
            "location_country": "2020-12-01",
        },
    )
    old_skill = Skill.objects.create(name="united states")
    profile.skills.add(old_skill)
    path = tmp_path / "profiles.txt"
    canonical_row = make_row(
        industry="Software",
        job_title="Principal Engineer",
        job_company_name="Analytical Engines",
        location_name="London",
        location_country="United Kingdom",
        summary="Corrected summary",
        skills="['Python']",
        experience=str([experience_item("Principal Engineer")]),
        education=str([education_item("University")]),
    )
    write_csv(path, [source_row_for_layout(canonical_row, "legacy-facebook-appended-77")])

    first = run_import(path)
    repaired = Profile.objects.get(pk=profile.pk)
    second = run_import(path)

    assert repaired.headline == "Principal Engineer"
    assert repaired.summary == "Corrected summary"
    assert repaired.raw_payload["industry"] == "Software"
    assert list(repaired.skills.values_list("name", flat=True)) == ["python"]
    assert count(first, "profiles_updated") == 1
    assert count(second, "profiles_created") == 0
    assert count(second, "profiles_updated") == 0
    assert count(second, "experiences_created") == 0
    assert count(second, "education_created") == 0


@pytest.mark.django_db
def test_semantic_boundaries_reject_shift_signatures_without_broad_dictionaries(tmp_path):
    path = tmp_path / "profiles.txt"
    write_csv(
        path,
        [
            make_row(
                job_title="201-500",
                industry="[]",
                job_company_name="2020-12-01",
                location_country="$50k - $70k",
                summary=str([education_item("University")]),
                skills="['United States', 'Leadership']",
            )
        ],
    )

    output = run_import(path)
    profile = Profile.objects.get()

    assert profile.headline == ""
    assert profile.summary == ""
    assert profile.raw_payload["industry"] == ""
    assert profile.raw_payload["job_company_name"] == ""
    assert profile.raw_payload["location_country"] == ""
    assert list(profile.skills.order_by("name").values_list("name", flat=True)) == [
        "leadership",
        "united states",
    ]
    assert "semantic_warnings" in output


def test_ambiguous_structural_layout_is_quarantined(monkeypatch):
    command = Command()
    monkeypatch.setattr(
        command,
        "_layout_has_required_shape",
        lambda row, layout: layout.name in {"reordered-block-39", "reordered-block-40"},
    )
    monkeypatch.setattr(command, "_has_nonempty_literal_list", lambda value: True)

    layout, reason = command._detect_layout(make_row())

    assert layout is None
    assert reason == "STRUCTURAL_LAYOUT_AMBIGUOUS"


@pytest.mark.django_db
def test_quoted_multiline_raw_payload_and_skill_warnings(tmp_path):
    path = tmp_path / "profiles.txt"
    write_csv(
        path,
        [
            make_row(
                full_name="Ada, Lovelace",
                summary="First line\nSecond line",
                skills="['Python', ' python ', {'bad': 'item'}]",
            )
        ],
    )
    output = run_import(path)
    profile = Profile.objects.get()
    assert profile.full_name == "Ada, Lovelace"
    assert profile.profile_url == "https://www.linkedin.com/in/ada.lovelace"
    assert profile.raw_payload["summary"] == "First line\nSecond line"
    assert list(profile.skills.values_list("name", flat=True)) == ["python"]
    assert "skipped_skill_items: 1" in output


@pytest.mark.django_db
def test_duplicate_rows_consolidate_with_tri_state_merge(tmp_path):
    path = tmp_path / "profiles.txt"
    write_csv(
        path,
        [
            make_row(job_title="Original", location_name="First"),
            make_row(job_title="['invalid', 'list']", location_name="  Later  "),
        ],
    )
    output = run_import(path)
    profile = Profile.objects.get()
    assert Profile.objects.count() == 1
    assert profile.headline == "Original"
    assert profile.location == "Later"
    assert count(output, "accepted_profile_rows") == 2
    assert count(output, "duplicate_rows") == 1
    assert count(output, "profiles_created") == 1


@pytest.mark.django_db
def test_duplicate_rows_form_one_plan_before_any_persistence(tmp_path, monkeypatch):
    path = tmp_path / "profiles.txt"
    write_csv(
        path,
        [
            make_row(job_title="Original", location_name="First", summary="Original summary"),
            make_row(
                job_title="['invalid', 'list']",
                location_name="Later",
                summary="",
            ),
        ],
    )
    command = Command()
    stats = ImportStats()
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.reader(source, delimiter=",", quotechar='"')
        header = next(reader)
        candidates = command._parse_rows(reader, header, stats)

    assert len(candidates) == 2
    assert Profile.objects.count() == 0
    plans = command._consolidate(candidates, stats)
    assert len(plans) == 1
    assert Profile.objects.count() == 0

    plan = plans[0]
    assert len(plan.rows) == 2
    assert plan.fields["headline"].state == "value"
    assert plan.fields["headline"].value == "Original"
    assert plan.fields["location"].value == "Later"
    assert plan.fields["summary"].state == "empty"
    assert plan.aliases == {
        "linkedin_id": "123",
        "linkedin_username": "ada.lovelace",
        "linkedin_url": "https://www.linkedin.com/in/ada.lovelace",
    }

    persist_spy = Mock(wraps=command._persist_plan)
    monkeypatch.setattr(command, "_persist_plan", persist_spy)
    for final_plan in plans:
        command._persist_plan(final_plan, stats)

    persist_spy.assert_called_once_with(plan, stats)
    profile = Profile.objects.get()
    assert profile.headline == "Original"
    assert profile.location == "Later"
    assert profile.summary == ""


@pytest.mark.django_db
def test_repeated_import_preserves_complete_persisted_snapshot(tmp_path):
    path = tmp_path / "profiles.txt"
    experience = str(
        [
            experience_item(
                "Engineer",
                start_date="2020-01-01",
                end_date="2021-03",
                location_names=["London", "Remote"],
                summary="Built machines",
            ),
            experience_item("Researcher", "Royal Society", start_date="2022"),
        ]
    )
    education = str(
        [
            education_item(
                "University of London",
                degrees=["MSc"],
                majors=["Mathematics"],
                minors=["Computing"],
                start_date="2015",
                end_date="2017",
            ),
            education_item("Independent Study", degrees=["Certificate"]),
        ]
    )
    write_csv(
        path,
        [
            make_row(
                job_title="Engineer",
                location_name="London",
                summary="First source row",
                skills="['Python', 'SQL']",
                experience=experience,
                education=education,
            ),
            make_row(
                job_title="['invalid', 'headline']",
                location_name="Remote",
                summary="Final source row",
                skills="[' python ', {'invalid': 'item'}, 'SQL', 'sql']",
                experience=experience,
                education=education,
                github_username="ada-source-payload",
            ),
        ],
    )
    first = run_import(path)
    first_snapshot = persisted_import_snapshot()
    second = run_import(path)
    second_snapshot = persisted_import_snapshot()

    assert set(dict(first_snapshot["profiles"][0])) == {
        "id",
        "public_identifier",
        "full_name",
        "first_name",
        "last_name",
        "headline",
        "location",
        "summary",
        "linkedin_id",
        "linkedin_username",
        "profile_url",
        "raw_payload",
        "created_at",
        "updated_at",
    }
    assert set(dict(first_snapshot["skills"][0])) == {"id", "name"}
    assert set(dict(first_snapshot["profile_skills"][0])) == {"id", "profile_id", "skill_id"}
    assert set(dict(first_snapshot["experiences"][0])) == {
        "id",
        "profile_id",
        "title",
        "company",
        "location",
        "description",
        "started_at",
        "ended_at",
        "source_order",
    }
    assert set(dict(first_snapshot["education"][0])) == {
        "id",
        "profile_id",
        "school",
        "degree",
        "field_of_study",
        "started_at",
        "ended_at",
        "source_order",
    }
    assert first_snapshot == second_snapshot
    assert snapshot_values(first_snapshot, "profiles", "id") == snapshot_values(
        second_snapshot, "profiles", "id"
    )
    assert snapshot_values(first_snapshot, "profiles", "updated_at") == snapshot_values(
        second_snapshot, "profiles", "updated_at"
    )
    assert snapshot_values(first_snapshot, "experiences", "id") == snapshot_values(
        second_snapshot, "experiences", "id"
    )
    assert snapshot_values(first_snapshot, "education", "id") == snapshot_values(
        second_snapshot, "education", "id"
    )
    assert first_snapshot["profile_skills"] == second_snapshot["profile_skills"]
    assert snapshot_values(first_snapshot, "profiles", "raw_payload") == snapshot_values(
        second_snapshot, "profiles", "raw_payload"
    )
    for alias in ("public_identifier", "linkedin_id", "linkedin_username", "profile_url"):
        assert snapshot_values(first_snapshot, "profiles", alias) == snapshot_values(
            second_snapshot, "profiles", alias
        )
    assert snapshot_values(first_snapshot, "experiences", "source_order") == (0, 1)
    assert snapshot_values(first_snapshot, "education", "source_order") == (0, 1)
    assert (
        first_snapshot["counts"]
        == second_snapshot["counts"]
        == {
            "profiles": 1,
            "skills": 2,
            "profile_skills": 2,
            "experiences": 2,
            "education": 2,
        }
    )

    assert count(first, "accepted_profile_rows") == 2
    assert count(first, "duplicate_rows") == 1
    assert count(first, "profiles_created") == 1
    assert count(first, "skills_created") == 2
    assert count(first, "experiences_created") == 2
    assert count(first, "education_created") == 2
    assert count(second, "profiles_unchanged") == 1
    for name in (
        "profiles_created",
        "profiles_updated",
        "skills_created",
        "skills_reused",
        "experiences_created",
        "experiences_updated",
        "experiences_deleted",
        "education_created",
        "education_updated",
        "education_deleted",
    ):
        assert count(second, name) == 0
    assert count(second, "experiences_unchanged") == 2
    assert count(second, "education_unchanged") == 2


@pytest.mark.django_db
def test_database_counters_report_actual_inserts_updates_and_skill_reuse(tmp_path):
    Skill.objects.create(name="python")
    path = tmp_path / "profiles.txt"
    write_csv(
        path,
        [
            make_row(
                job_title="Engineer",
                skills="['Python']",
                experience=str([experience_item(summary="Initial")]),
                education=str([education_item(degrees=["BSc"])]),
            )
        ],
    )
    created = run_import(path)
    assert count(created, "profiles_created") == 1
    assert count(created, "skills_created") == 0
    assert count(created, "skills_reused") == 1
    assert count(created, "experiences_created") == 1
    assert count(created, "education_created") == 1

    write_csv(
        path,
        [
            make_row(
                job_title="Senior Engineer",
                skills="['Python']",
                experience=str([experience_item(summary="Changed")]),
                education=str([education_item(degrees=["MSc"])]),
            )
        ],
    )
    updated = run_import(path)
    assert count(updated, "profiles_updated") == 1
    assert count(updated, "skills_created") == 0
    assert count(updated, "skills_reused") == 0
    assert count(updated, "experiences_updated") == 1
    assert count(updated, "education_updated") == 1
    assert count(updated, "experiences_created") == 0
    assert count(updated, "experiences_deleted") == 0
    assert count(updated, "education_created") == 0
    assert count(updated, "education_deleted") == 0


@pytest.mark.django_db
def test_full_collection_sync_preserves_retained_pks_and_counts_deletes(tmp_path):
    path = tmp_path / "profiles.txt"
    initial_experience = str(
        [experience_item("One"), experience_item("Two"), experience_item("Stale")]
    )
    initial_education = str([education_item("One"), education_item("Stale")])
    write_csv(path, [make_row(experience=initial_experience, education=initial_education)])
    run_import(path)
    profile = Profile.objects.get()
    retained_experience = dict(profile.experiences.values_list("source_order", "id"))
    retained_education = dict(profile.educations.values_list("source_order", "id"))
    write_csv(
        path,
        [
            make_row(
                experience=str([experience_item("One"), experience_item("Two")]),
                education=str([education_item("One")]),
            )
        ],
    )
    output = run_import(path)
    assert dict(profile.experiences.values_list("source_order", "id")) == {
        0: retained_experience[0],
        1: retained_experience[1],
    }
    assert dict(profile.educations.values_list("source_order", "id")) == {0: retained_education[0]}
    assert count(output, "experiences_created") == 0
    assert count(output, "experiences_updated") == 0
    assert count(output, "experiences_unchanged") == 2
    assert count(output, "experiences_deleted") == 1
    assert count(output, "education_deleted") == 1


@pytest.mark.django_db
def test_explicit_empty_lists_clear_relations_and_skills(tmp_path):
    path = tmp_path / "profiles.txt"
    write_csv(
        path,
        [
            make_row(
                skills="['Python']",
                experience=str([experience_item()]),
                education=str([education_item()]),
            )
        ],
    )
    run_import(path)
    write_csv(path, [make_row(skills="[]", experience="[]", education="[]")])
    output = run_import(path)
    profile = Profile.objects.get()
    assert profile.skills.count() == 0
    assert profile.experiences.count() == 0
    assert profile.educations.count() == 0
    assert count(output, "experiences_deleted") == 1
    assert count(output, "education_deleted") == 1


@pytest.mark.django_db
@pytest.mark.parametrize("empty_skills", ["", "NULL", " n/a "])
def test_blank_and_recognized_null_skills_clear_relationships(tmp_path, empty_skills):
    path = tmp_path / "profiles.txt"
    write_csv(path, [make_row(skills="['Python']")])
    run_import(path)
    profile = Profile.objects.get()
    assert list(profile.skills.values_list("name", flat=True)) == ["python"]

    write_csv(path, [make_row(skills=empty_skills)])
    run_import(path)
    assert profile.skills.count() == 0


@pytest.mark.django_db
def test_skills_are_normalized_and_deduplicated(tmp_path):
    path = tmp_path / "profiles.txt"
    write_csv(path, [make_row(skills="[' Python ', 'python', 'SQL', ' sql ']")])
    run_import(path)
    profile = Profile.objects.get()
    assert list(profile.skills.order_by("name").values_list("name", flat=True)) == [
        "python",
        "sql",
    ]
    assert Profile.skills.through.objects.count() == 2


@pytest.mark.django_db
def test_nonempty_skills_list_without_valid_strings_preserves_relationships(tmp_path):
    path = tmp_path / "profiles.txt"
    write_csv(path, [make_row(skills="['Python']")])
    run_import(path)
    profile = Profile.objects.get()
    through_rows = list(
        Profile.skills.through.objects.order_by("pk").values("id", "profile_id", "skill_id")
    )

    write_csv(path, [make_row(skills="[None, {'bad': 'item'}, '  ']")])
    output = run_import(path)
    assert list(profile.skills.values_list("name", flat=True)) == ["python"]
    assert (
        list(Profile.skills.through.objects.order_by("pk").values("id", "profile_id", "skill_id"))
        == through_rows
    )
    assert count(output, "skipped_skill_items") == 3
    assert "invalid_skills_fields: {'skills': 1}" in output


@pytest.mark.django_db
def test_repeated_skills_import_preserves_through_rows(tmp_path):
    path = tmp_path / "profiles.txt"
    write_csv(path, [make_row(skills="['Python', 'SQL']")])
    run_import(path)
    through = Profile.skills.through
    first_rows = list(
        through.objects.order_by("profile_id", "skill_id", "pk").values(
            "id", "profile_id", "skill_id"
        )
    )

    output = run_import(path)
    second_rows = list(
        through.objects.order_by("profile_id", "skill_id", "pk").values(
            "id", "profile_id", "skill_id"
        )
    )
    assert second_rows == first_rows
    assert count(output, "skills_created") == 0
    assert count(output, "skills_reused") == 0


@pytest.mark.django_db
def test_blank_malformed_and_invalid_top_level_collections_preserve_data(tmp_path):
    path = tmp_path / "profiles.txt"
    write_csv(
        path,
        [
            make_row(
                skills="['Python']",
                experience=str([experience_item()]),
                education=str([education_item()]),
            )
        ],
    )
    run_import(path)
    write_csv(path, [make_row(skills="", experience="", education="not-a-list")])
    output = run_import(path)
    profile = Profile.objects.get()
    assert profile.skills.count() == 0
    assert profile.experiences.count() == 1
    assert profile.educations.count() == 1
    assert count(output, "experiences_unchanged") == 1
    assert count(output, "education_unchanged") == 1


@pytest.mark.django_db
def test_partial_collection_preserves_invalid_positions_and_invalid_subfields(tmp_path):
    path = tmp_path / "profiles.txt"
    initial = str(
        [
            experience_item("Original", location_names=["London"], summary="Keep"),
            experience_item("Invalid position"),
            experience_item("Retained"),
        ]
    )
    write_csv(path, [make_row(experience=initial)])
    run_import(path)
    profile = Profile.objects.get()
    original = profile.experiences.get(source_order=0)
    original_pk = original.pk
    write_csv(
        path,
        [
            make_row(
                experience=str(
                    [
                        experience_item(
                            "Updated",
                            location_names=["New", {"bad": "value"}],
                            summary={"bad": "value"},
                        ),
                        {"title": {}, "company": {"name": "Skipped"}},
                    ]
                )
            )
        ],
    )
    output = run_import(path)
    original.refresh_from_db()
    assert original.pk == original_pk
    assert original.title == "Updated"
    assert original.location == "London"
    assert original.description == "Keep"
    assert profile.experiences.filter(source_order=2).exists()
    assert count(output, "experiences_deleted") == 0
    assert "experience.location_names" in output


@pytest.mark.django_db
def test_nested_list_normalization_and_separators(tmp_path):
    path = tmp_path / "profiles.txt"
    write_csv(
        path,
        [
            make_row(
                experience=str([experience_item(location_names=[" London ", "London", "Remote"])]),
                education=str(
                    [
                        education_item(
                            degrees=[" MSc ", "MSc"],
                            majors=[" Mathematics ", "Mathematics"],
                            minors=[" Computing ", "Mathematics"],
                        )
                    ]
                ),
            )
        ],
    )
    run_import(path)
    profile = Profile.objects.get()
    assert profile.experiences.get().location == "London, Remote"
    education = profile.educations.get()
    assert education.degree == "MSc"
    assert education.field_of_study == "Mathematics | Computing"


@pytest.mark.django_db
def test_mixed_string_dictionary_scalar_list_is_invalid_for_new_nested_item(tmp_path):
    path = tmp_path / "profiles.txt"
    write_csv(
        path,
        [
            make_row(
                experience=str([experience_item(location_names=["London", {"bad": "item"}])]),
                education=str([education_item(degrees=["MSc", {"bad": "item"}])]),
            )
        ],
    )
    output = run_import(path)
    profile = Profile.objects.get()
    assert profile.experiences.get().location == ""
    assert profile.educations.get().degree == ""
    assert "experience.location_names" in output
    assert "education.degrees" in output


@pytest.mark.django_db
def test_identity_alias_conflict_quarantines_without_writes(tmp_path):
    Profile.objects.create(public_identifier="existing-one", first_name="One", linkedin_id="one")
    Profile.objects.create(
        public_identifier="existing-two", first_name="Two", linkedin_username="two"
    )
    path = tmp_path / "profiles.txt"
    write_csv(path, [make_row(linkedin_id="one", linkedin_username="two")])
    output = run_import(path)
    assert Profile.objects.count() == 2
    assert "identity_conflict_records: 1" in output
    assert "IDENTITY_CONFLICT" in output


@pytest.mark.django_db
def test_fallback_identity_is_upgraded_without_changing_profile_pk(tmp_path):
    path = tmp_path / "profiles.txt"
    write_csv(
        path,
        [
            make_row(
                linkedin_id="",
                linkedin_username="Fallback.User",
                linkedin_url="linkedin.com/in/Fallback.User/",
            )
        ],
    )
    run_import(path)
    profile = Profile.objects.get()
    original_pk = profile.pk
    write_csv(
        path,
        [
            make_row(
                linkedin_id="987",
                linkedin_username="fallback.user",
                linkedin_url="https://linkedin.com/in/fallback.user",
            )
        ],
    )
    run_import(path)
    profile.refresh_from_db()
    assert profile.pk == original_pk
    assert profile.linkedin_id == "987"
    assert profile.public_identifier == "linkedin:id:987"


@pytest.mark.django_db
def test_oversized_values_are_not_truncated(tmp_path):
    path = tmp_path / "profiles.txt"
    write_csv(
        path,
        [
            make_row(
                full_name="F" * 501,
                first_name="Valid",
                skills=str(["S" * 201]),
                experience=str([experience_item(title="T" * 256)]),
            )
        ],
    )
    output = run_import(path)
    profile = Profile.objects.get()
    assert profile.full_name == ""
    assert profile.skills.count() == 0
    assert profile.experiences.count() == 0
    assert "full_name" in output
    assert "skills" in output
    assert "experience.title" in output


@pytest.mark.django_db
def test_database_error_rolls_back_phase_c_writes(tmp_path, monkeypatch):
    path = tmp_path / "profiles.txt"
    write_csv(path, [make_row()])

    def fail_save(*args, **kwargs):
        raise DatabaseError("synthetic database failure")

    monkeypatch.setattr(Profile, "save", fail_save)
    with pytest.raises(DatabaseError, match="synthetic database failure"):
        run_import(path)
    assert Profile.objects.count() == 0


@pytest.mark.django_db
def test_models_have_source_order_constraints_and_identity_nulls():
    profile = Profile.objects.create(public_identifier="null-identity", first_name="Name")
    assert profile.linkedin_id is None
    assert profile.linkedin_username is None
    assert profile.profile_url is None
    Experience.objects.create(profile=profile, title="One", company="Company", source_order=0)
    Education.objects.create(profile=profile, school="School", source_order=0)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Experience.objects.create(
                profile=profile, title="Duplicate", company="Company", source_order=0
            )
    assert Skill.objects.count() == 0
