import pytest
from django.db import IntegrityError, connections, transaction
from django.db.migrations.executor import MigrationExecutor

LATEST = ("profiles", "0003_profile_public_identifier_length")
INITIAL = ("profiles", "0001_initial")


@pytest.fixture
def migrate_profiles():
    connection = connections["default"]

    def migrate(target):
        executor = MigrationExecutor(connection)
        executor.migrate([target])
        if target[1] is None:
            return None
        executor = MigrationExecutor(connection)
        return executor.loader.project_state([target]).apps

    try:
        yield connection, migrate
    finally:
        MigrationExecutor(connection).migrate([LATEST])


def table_columns(connection, table_name):
    with connection.cursor() as cursor:
        return {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }


def table_constraints(connection, table_name):
    with connection.cursor() as cursor:
        return connection.introspection.get_constraints(cursor, table_name)


def has_constraint(connection, table_name, *, columns, attribute):
    constraints = table_constraints(connection, table_name)
    return any(
        details[attribute] and details["columns"] == list(columns)
        for details in constraints.values()
    )


def has_foreign_key(connection, table_name, column, target_table):
    constraints = table_constraints(connection, table_name)
    return any(
        details["columns"] == [column] and details["foreign_key"] == (target_table, "id")
        for details in constraints.values()
    )


@pytest.mark.django_db(transaction=True)
def test_profiles_migrate_from_zero_to_latest(migrate_profiles):
    connection, migrate = migrate_profiles
    migrate(("profiles", None))
    apps = migrate(LATEST)

    executor = MigrationExecutor(connection)
    assert executor.loader.graph.leaf_nodes("profiles") == [LATEST]

    profile = apps.get_model("profiles", "Profile")
    skill = apps.get_model("profiles", "Skill")
    experience = apps.get_model("profiles", "Experience")
    education = apps.get_model("profiles", "Education")
    through = profile.skills.through

    expected_columns = {
        profile._meta.db_table: {
            "id",
            "public_identifier",
            "linkedin_id",
            "linkedin_username",
            "profile_url",
            "full_name",
            "first_name",
            "last_name",
            "headline",
            "location",
            "summary",
            "raw_payload",
            "created_at",
            "updated_at",
        },
        skill._meta.db_table: {"id", "name"},
        through._meta.db_table: {"id", "profile_id", "skill_id"},
        experience._meta.db_table: {
            "id",
            "profile_id",
            "title",
            "company",
            "location",
            "description",
            "started_at",
            "ended_at",
            "source_order",
        },
        education._meta.db_table: {
            "id",
            "profile_id",
            "school",
            "degree",
            "field_of_study",
            "started_at",
            "ended_at",
            "source_order",
        },
    }
    assert set(expected_columns) <= set(connection.introspection.table_names())
    for table_name, columns in expected_columns.items():
        assert table_columns(connection, table_name) == columns

    expected_constraints = {
        profile._meta.db_table: {
            "profiles_profile_linkedin_id_unique",
            "profiles_profile_linkedin_username_unique",
            "profiles_profile_url_unique",
        },
        experience._meta.db_table: {"profiles_experience_profile_source_order_unique"},
        education._meta.db_table: {"profiles_education_profile_source_order_unique"},
    }
    for table_name, names in expected_constraints.items():
        constraints = table_constraints(connection, table_name)
        assert names <= constraints.keys()
        assert all(constraints[name]["unique"] for name in names)

    for table_name in expected_columns:
        assert has_constraint(connection, table_name, columns=("id",), attribute="primary_key")
    for table_name, columns in (
        (profile._meta.db_table, ("public_identifier",)),
        (profile._meta.db_table, ("linkedin_id",)),
        (profile._meta.db_table, ("linkedin_username",)),
        (profile._meta.db_table, ("profile_url",)),
        (skill._meta.db_table, ("name",)),
        (through._meta.db_table, ("profile_id", "skill_id")),
        (experience._meta.db_table, ("profile_id", "source_order")),
        (education._meta.db_table, ("profile_id", "source_order")),
    ):
        assert has_constraint(connection, table_name, columns=columns, attribute="unique")
    assert has_foreign_key(connection, through._meta.db_table, "profile_id", profile._meta.db_table)
    assert has_foreign_key(connection, through._meta.db_table, "skill_id", skill._meta.db_table)
    assert has_foreign_key(
        connection, experience._meta.db_table, "profile_id", profile._meta.db_table
    )
    assert has_foreign_key(
        connection, education._meta.db_table, "profile_id", profile._meta.db_table
    )

    assert profile._meta.get_field("public_identifier").max_length == 600


@pytest.mark.django_db(transaction=True)
def test_profiles_upgrade_from_0001_preserves_rows_and_backfills_source_order(
    migrate_profiles,
):
    _, migrate = migrate_profiles
    old_apps = migrate(INITIAL)
    old_profile = old_apps.get_model("profiles", "Profile")
    old_experience = old_apps.get_model("profiles", "Experience")
    old_education = old_apps.get_model("profiles", "Education")

    profiles = [
        old_profile.objects.create(
            public_identifier=f"legacy-{index}",
            first_name=f"First {index}",
            last_name=f"Last {index}",
            headline=f"Headline {index}",
            location=f"Location {index}",
            summary=f"Summary {index}",
            profile_url="",
        )
        for index in range(3)
    ]
    experiences = [
        old_experience.objects.create(
            profile=profiles[0], title=f"Role {index}", company=f"Company {index}"
        )
        for index in range(3)
    ]
    educations = [
        old_education.objects.create(profile=profiles[0], school=f"School {index}")
        for index in range(2)
    ]
    profile_ids = [record.pk for record in profiles]
    experience_ids = [record.pk for record in experiences]
    education_ids = [record.pk for record in educations]

    new_apps = migrate(LATEST)
    profile = new_apps.get_model("profiles", "Profile")
    experience = new_apps.get_model("profiles", "Experience")
    education = new_apps.get_model("profiles", "Education")

    migrated_profiles = list(profile.objects.filter(pk__in=profile_ids).order_by("pk"))
    assert [record.pk for record in migrated_profiles] == profile_ids
    assert [record.profile_url for record in migrated_profiles] == [None, None, None]
    assert [record.headline for record in migrated_profiles] == [
        "Headline 0",
        "Headline 1",
        "Headline 2",
    ]
    assert [
        (
            record.public_identifier,
            record.first_name,
            record.last_name,
            record.location,
            record.summary,
        )
        for record in migrated_profiles
    ] == [
        (
            f"legacy-{index}",
            f"First {index}",
            f"Last {index}",
            f"Location {index}",
            f"Summary {index}",
        )
        for index in range(3)
    ]

    migrated_experiences = list(experience.objects.filter(pk__in=experience_ids).order_by("pk"))
    migrated_educations = list(education.objects.filter(pk__in=education_ids).order_by("pk"))
    assert [record.pk for record in migrated_experiences] == experience_ids
    assert [record.pk for record in migrated_educations] == education_ids

    # Migration 0002 assigns zero-based source_order by historical primary key per profile.
    assert [record.source_order for record in migrated_experiences] == [0, 1, 2]
    assert [record.source_order for record in migrated_educations] == [0, 1]
    assert len({record.source_order for record in migrated_experiences}) == 3
    assert len({record.source_order for record in migrated_educations}) == 2

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            experience.objects.create(
                profile_id=profile_ids[0],
                title="Duplicate order",
                company="Company",
                source_order=0,
            )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            education.objects.create(
                profile_id=profile_ids[0], school="Duplicate order", source_order=0
            )

    identifier = "linkedin:url:" + "x" * (600 - len("linkedin:url:"))
    boundary = profile.objects.create(public_identifier=identifier, first_name="Boundary")
    assert boundary.public_identifier == identifier
    assert profile._meta.get_field("public_identifier").max_length == 600


@pytest.mark.django_db(transaction=True)
def test_latest_alias_constraints_allow_nulls_and_reject_duplicate_values(migrate_profiles):
    _, migrate = migrate_profiles
    apps = migrate(LATEST)
    profile = apps.get_model("profiles", "Profile")

    for index in range(2):
        profile.objects.create(
            public_identifier=f"null-aliases-{index}",
            first_name="Null",
            linkedin_id=None,
            linkedin_username=None,
            profile_url=None,
        )
    assert (
        profile.objects.filter(
            linkedin_id__isnull=True,
            linkedin_username__isnull=True,
            profile_url__isnull=True,
        ).count()
        == 2
    )

    duplicate_aliases = (
        ("linkedin_id", "duplicate-id"),
        ("linkedin_username", "duplicate.username"),
        ("profile_url", "https://www.linkedin.com/in/duplicate"),
    )
    for index, (field_name, value) in enumerate(duplicate_aliases):
        profile.objects.create(
            public_identifier=f"unique-alias-{index}-one",
            first_name="First",
            **{field_name: value},
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                profile.objects.create(
                    public_identifier=f"unique-alias-{index}-two",
                    first_name="Second",
                    **{field_name: value},
                )
