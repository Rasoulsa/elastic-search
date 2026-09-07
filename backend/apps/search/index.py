INDEX_NAME = "linkedin_profiles_v1"
NORMALIZER_NAME = "lowercase_ascii"


def normalized_text_field() -> dict:
    return {
        "type": "text",
        "fields": {
            "keyword": {
                "type": "keyword",
                "normalizer": NORMALIZER_NAME,
            }
        },
    }


INDEX_SETTINGS = {
    "analysis": {
        "normalizer": {
            NORMALIZER_NAME: {
                "type": "custom",
                "filter": ["lowercase", "asciifolding"],
            }
        }
    }
}

INDEX_MAPPING = {
    "dynamic": "strict",
    "properties": {
        "profile_id": {"type": "keyword"},
        "full_name": normalized_text_field(),
        "job_title": normalized_text_field(),
        "job_titles": normalized_text_field(),
        "skills": normalized_text_field(),
        "industry": normalized_text_field(),
        "location_name": {"type": "text"},
        "country": normalized_text_field(),
        "company": normalized_text_field(),
        "summary": {"type": "text"},
        "experience_text": {"type": "text"},
        "education_text": {"type": "text"},
    },
}
