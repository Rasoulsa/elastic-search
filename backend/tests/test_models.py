import pytest
from django.core.exceptions import ValidationError

from apps.profiles.models import Education, Experience, Profile, Skill


@pytest.mark.django_db
def test_profile_relations_are_persisted():
    profile = Profile.objects.create(
        public_identifier="ada-lovelace",
        first_name="Ada",
        last_name="Lovelace",
        headline="Mathematician",
    )
    skill = Skill.objects.create(name="Analytical engines")
    profile.skills.add(skill)
    Experience.objects.create(profile=profile, title="Writer", company="Independent")
    Education.objects.create(profile=profile, school="Private study")

    assert list(profile.skills.values_list("name", flat=True)) == ["Analytical engines"]
    assert profile.experiences.count() == 1
    assert profile.educations.count() == 1


@pytest.mark.django_db
def test_public_identifier_supports_the_full_declared_length():
    prefix = "linkedin:url:"
    identifier = prefix + "x" * (600 - len(prefix))
    profile = Profile(public_identifier=identifier, first_name="Boundary")
    profile.full_clean()
    profile.save()
    assert Profile.objects.get(pk=profile.pk).public_identifier == identifier
    with pytest.raises(ValidationError):
        Profile(public_identifier="x" * 601, first_name="Too long").full_clean()
