import unicodedata

from apps.profiles.models import Profile
from apps.profiles.provenance import validated_metadata_text
from apps.profiles.semantic_values import validated_scalar


def profile_document_id(profile: Profile) -> str:
    if profile.pk is None:
        raise ValueError("A saved profile is required for search projection.")
    return str(profile.pk)


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _canonical_metadata(metadata: dict, key: str, destination: str | None = None) -> str:
    return validated_metadata_text(metadata, key, destination)


def _deduplication_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    unaccented = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return unaccented.casefold()


def _unique(values) -> list[str]:
    result = []
    seen = set()
    for raw_value in values:
        value = _text(raw_value)
        key = _deduplication_key(value)
        if value and key not in seen:
            result.append(value)
            seen.add(key)
    return result


def _prefetched(profile: Profile, relation: str):
    cache = getattr(profile, "_prefetched_objects_cache", {})
    if relation not in cache:
        raise ValueError(f"Profile relation '{relation}' must be prefetched.")
    return cache[relation]


def _experience_line(experience) -> str:
    return " | ".join(
        value
        for value in (
            validated_scalar("job_title", experience.title),
            validated_scalar("job_company_name", experience.company),
            validated_scalar("location_name", experience.location),
            validated_scalar("summary", experience.description),
        )
        if value
    )


def _education_line(education) -> str:
    return " | ".join(
        value
        for value in (
            _text(education.school),
            _text(education.degree),
            _text(education.field_of_study),
        )
        if value
    )


def project_profile(profile: Profile) -> dict:
    skills = sorted(
        _unique(skill.name for skill in _prefetched(profile, "skills")),
        key=_deduplication_key,
    )
    experiences = sorted(
        _prefetched(profile, "experiences"),
        key=lambda experience: (experience.source_order, experience.pk or 0),
    )
    educations = sorted(
        _prefetched(profile, "educations"),
        key=lambda education: (education.source_order, education.pk or 0),
    )

    metadata = profile.raw_payload if isinstance(profile.raw_payload, dict) else {}
    current_title = _canonical_metadata(metadata, "job_title")
    current_company = _canonical_metadata(metadata, "job_company_name")
    job_titles = _unique(
        [
            current_title,
            *(validated_scalar("job_title", experience.title) for experience in experiences),
        ]
    )
    companies = _unique(
        [
            current_company,
            *(
                validated_scalar("job_company_name", experience.company)
                for experience in experiences
            ),
        ]
    )

    full_name = _text(profile.full_name) or _text(f"{profile.first_name} {profile.last_name}")

    return {
        "profile_id": profile_document_id(profile),
        "full_name": full_name,
        "job_title": current_title,
        "job_titles": job_titles,
        "skills": skills,
        "industry": _canonical_metadata(metadata, "industry")
        or _canonical_metadata(metadata, "job_company_industry", "industry"),
        "location_name": _canonical_metadata(metadata, "location_name"),
        "country": _canonical_metadata(metadata, "location_country"),
        "company": companies,
        "summary": _canonical_metadata(metadata, "summary"),
        "experience_text": _unique(_experience_line(item) for item in experiences),
        "education_text": _unique(_education_line(item) for item in educations),
    }
