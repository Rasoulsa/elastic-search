from django.db import models
from django.db.models import Q


class Skill(models.Model):
    name = models.CharField(max_length=200, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Profile(models.Model):
    public_identifier = models.CharField(max_length=600, unique=True)
    full_name = models.CharField(max_length=500, blank=True, default="")
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    headline = models.CharField(max_length=500, blank=True)
    location = models.CharField(max_length=255, blank=True)
    summary = models.TextField(blank=True)
    linkedin_id = models.CharField(max_length=255, null=True, blank=True)
    linkedin_username = models.CharField(max_length=255, null=True, blank=True)
    profile_url = models.URLField(max_length=500, null=True, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    skills = models.ManyToManyField(Skill, related_name="profiles", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["linkedin_id"],
                condition=Q(linkedin_id__isnull=False),
                name="profiles_profile_linkedin_id_unique",
            ),
            models.UniqueConstraint(
                fields=["linkedin_username"],
                condition=Q(linkedin_username__isnull=False),
                name="profiles_profile_linkedin_username_unique",
            ),
            models.UniqueConstraint(
                fields=["profile_url"],
                condition=Q(profile_url__isnull=False),
                name="profiles_profile_url_unique",
            ),
        ]

    def __str__(self) -> str:
        return self.full_name or f"{self.first_name} {self.last_name}".strip()


class Experience(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="experiences")
    title = models.CharField(max_length=255)
    company = models.CharField(max_length=255)
    location = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    started_at = models.DateField(null=True, blank=True)
    ended_at = models.DateField(null=True, blank=True)
    source_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-started_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "source_order"],
                name="profiles_experience_profile_source_order_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} at {self.company}"


class Education(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="educations")
    school = models.CharField(max_length=255)
    degree = models.CharField(max_length=255, blank=True)
    field_of_study = models.CharField(max_length=255, blank=True)
    started_at = models.DateField(null=True, blank=True)
    ended_at = models.DateField(null=True, blank=True)
    source_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-started_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "source_order"],
                name="profiles_education_profile_source_order_unique",
            ),
        ]

    def __str__(self) -> str:
        return self.school
