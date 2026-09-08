from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Education, Experience, Profile
from .provenance import validated_metadata_text


def _clean_text(value) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _metadata_text(profile: Profile, key: str, destination: str | None = None) -> str:
    return validated_metadata_text(profile.raw_payload, key, destination)


class ExperienceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Experience
        fields = (
            "title",
            "company",
            "location",
            "description",
            "started_at",
            "ended_at",
        )


class EducationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Education
        fields = ("school", "degree", "field_of_study", "started_at", "ended_at")


class ProfileDetailSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    job_title = serializers.SerializerMethodField()
    company = serializers.SerializerMethodField()
    industry = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    country = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    skills = serializers.SlugRelatedField(many=True, read_only=True, slug_field="name")
    experiences = ExperienceSerializer(many=True, read_only=True)
    education = EducationSerializer(many=True, read_only=True, source="educations")

    class Meta:
        model = Profile
        fields = (
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
        )

    @extend_schema_field(serializers.CharField())
    def get_full_name(self, profile: Profile) -> str:
        return _clean_text(profile.full_name) or _clean_text(
            f"{profile.first_name} {profile.last_name}"
        )

    @extend_schema_field(serializers.CharField())
    def get_job_title(self, profile: Profile) -> str:
        return _metadata_text(profile, "job_title")

    @extend_schema_field(serializers.CharField())
    def get_company(self, profile: Profile) -> str:
        return _metadata_text(profile, "job_company_name")

    @extend_schema_field(serializers.CharField())
    def get_industry(self, profile: Profile) -> str:
        return _metadata_text(profile, "industry") or _metadata_text(
            profile, "job_company_industry", "industry"
        )

    @extend_schema_field(serializers.CharField())
    def get_location(self, profile: Profile) -> str:
        return _metadata_text(profile, "location_name")

    @extend_schema_field(serializers.CharField())
    def get_country(self, profile: Profile) -> str:
        return _metadata_text(profile, "location_country")

    @extend_schema_field(serializers.CharField())
    def get_summary(self, profile: Profile) -> str:
        return _metadata_text(profile, "summary")
