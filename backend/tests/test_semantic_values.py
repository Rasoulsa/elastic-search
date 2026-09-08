import pytest

from apps.profiles.semantic_values import scalar_anomaly, validated_scalar

INVALID_VALUES = {
    "phone-shaped": "+1 (555) 010-0100",
    "integer-only": "123456",
    "decimal-only": "12.75",
    "date-shaped": "2020-12-01",
    "salary-range-shaped": "$70,000 - $85,000",
    "company-size-shaped": "201-500",
    "serialized-list": "['Synthetic']",
    "serialized-dictionary": "{'name': 'Synthetic'}",
}


@pytest.mark.parametrize(
    "field_name",
    ["industry", "location_country", "job_company_name", "location_name", "job_title"],
)
@pytest.mark.parametrize("invalid_value", INVALID_VALUES.values(), ids=INVALID_VALUES)
def test_scalar_boundaries_reject_structurally_invalid_values(field_name, invalid_value):
    assert scalar_anomaly(field_name, invalid_value)
    assert validated_scalar(field_name, invalid_value) == ""


@pytest.mark.parametrize(
    "invalid_value",
    [value for name, value in INVALID_VALUES.items() if name != "phone-shaped"],
    ids=[name for name in INVALID_VALUES if name != "phone-shaped"],
)
def test_summary_rejects_non_summary_structural_values(invalid_value):
    assert scalar_anomaly("summary", invalid_value)
    assert validated_scalar("summary", invalid_value) == ""


@pytest.mark.parametrize(
    "value",
    [
        "José García",
        "研究工程师",
        "R&D / Platform",
        "O'Reilly Media",
        "Senior Backend Engineer",
        "SRE",
        "Studio 54 Labs",
        "District 9, North",
        "Climate-technology",
    ],
)
@pytest.mark.parametrize(
    "field_name",
    ["industry", "location_country", "job_company_name", "location_name", "job_title", "summary"],
)
def test_unusual_valid_scalars_are_not_allowlist_filtered(field_name, value):
    assert scalar_anomaly(field_name, value) is None
    assert validated_scalar(field_name, value) == value
