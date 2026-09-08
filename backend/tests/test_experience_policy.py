import pytest

from apps.profiles.experience_policy import select_source_experience


def source_experience(title, *, end_date=None, primary=False, company=None):
    item = {
        "title": {"name": title},
        "company": {"name": company or f"{title} Co"},
    }
    if end_date is not None:
        item["end_date"] = end_date
    if primary:
        item["is_primary"] = True
    return item


@pytest.mark.parametrize(
    ("items", "expected_title"),
    [
        (
            [source_experience("Old", end_date="2020"), source_experience("Primary", primary=True)],
            "Primary",
        ),
        ([source_experience("Open"), source_experience("Later", end_date="2020")], "Open"),
        ([source_experience("First"), source_experience("Second")], "First"),
        (
            [
                source_experience("First", end_date="2020"),
                source_experience("Second", end_date="2021"),
            ],
            "First",
        ),
        ([{"is_primary": True}, source_experience("Open")], "Open"),
        (
            [
                source_experience("Primary One", primary=True),
                source_experience("Primary Two", primary=True),
            ],
            "Primary One",
        ),
    ],
)
def test_source_current_experience_policy_is_deterministic(items, expected_title):
    _, selected = select_source_experience(items)

    assert selected["title"]["name"] == expected_title


def test_source_current_experience_policy_returns_none_without_experiences():
    assert select_source_experience([]) is None
