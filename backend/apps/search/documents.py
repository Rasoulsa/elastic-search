import unicodedata

from apps.profiles.models import Profile

NULL_METADATA_VALUES = {"", "null", "none", "nan", "n/a", "na"}


def profile_document_id(profile: Profile) -> str:
    if profile.pk is None:
        raise ValueError("A saved profile is required for search projection.")
    return str(profile.pk)


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _metadata_text(value: object) -> str:
    normalized = _text(value)
    return "" if normalized.casefold() in NULL_METADATA_VALUES else normalized


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
            _text(experience.title),
            _text(experience.company),
            _text(experience.location),
            _text(experience.description),
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
    current_experience = next(
        (experience for experience in experiences if experience.ended_at is None),
        experiences[0] if experiences else None,
    )
    headline = _text(profile.headline)
    current_title = headline or (_text(current_experience.title) if current_experience else "")
    current_company = _metadata_text(metadata.get("job_company_name")) or (
        _text(current_experience.company) if current_experience else ""
    )
    job_titles = _unique([current_title, *(experience.title for experience in experiences)])
    companies = _unique([current_company, *(experience.company for experience in experiences)])

    full_name = _text(profile.full_name) or _text(f"{profile.first_name} {profile.last_name}")

    return {
        "profile_id": profile_document_id(profile),
        "full_name": full_name,
        "job_title": current_title,
        "job_titles": job_titles,
        "skills": skills,
        "industry": _metadata_text(metadata.get("industry"))
        or _metadata_text(metadata.get("job_company_industry")),
        "location_name": _text(profile.location),
        "country": _metadata_text(metadata.get("location_country")),
        "company": companies,
        "summary": _text(profile.summary),
        "experience_text": _unique(_experience_line(item) for item in experiences),
        "education_text": _unique(_education_line(item) for item in educations),
    }
