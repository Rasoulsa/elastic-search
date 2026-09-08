import ast
from copy import deepcopy

import pytest

from apps.profiles.provenance import (
    FIELD_SOURCE_CONTRACTS,
    parse_source_path,
    validated_importer_metadata,
    validated_metadata_text,
)


def valid_payload():
    return {
        "experience": repr(
            [
                {
                    "title": {"name": "Earlier Engineer"},
                    "company": {
                        "name": "Earlier Company",
                        "size": "51-200",
                        "industry": "Earlier Industry",
                        "location": {"name": "Earlier Office"},
                    },
                    "end_date": "2020-01-01",
                },
                {
                    "is_primary": True,
                    "title": {"name": "研究工程师"},
                    "company": {
                        "name": "Société Exemple",
                        "size": "201-500",
                        "industry": "Énergie propre",
                        "location": {"name": "Zürich"},
                    },
                },
            ]
        ),
        "location_names": repr(["", "São Paulo"]),
        "countries": repr(["Brasil"]),
        "job_title": "研究工程师",
        "job_company_name": "Société Exemple",
        "job_company_size": "201-500",
        "job_company_industry": "Énergie propre",
        "industry": "Énergie propre",
        "job_company_location_name": "Zürich",
        "location_name": "São Paulo",
        "location_country": "Brasil",
        "summary": "Crée des systèmes fiables — à grande échelle.",
        "_source_values": {"44": "Crée des systèmes fiables — à grande échelle."},
        "_importer": {
            "mapping_version": "canonical-v2",
            "layout": "reordered-block-45",
            "canonical_sources": {
                "job_title": "experience[1].title.name",
                "job_company_name": "experience[1].company.name",
                "job_company_size": "experience[1].company.size",
                "job_company_industry": "experience[1].company.industry",
                "industry": "experience[1].company.industry",
                "job_company_location_name": "experience[1].company.location.name",
                "location_name": "location_names[1]",
                "location_country": "countries[0]",
                "summary": "_source_values[44]",
            },
            "selected_experience_source_order": 1,
        },
    }


def test_field_source_contract_is_exact_and_independently_asserted():
    expected = {
        "job_title": ("experience", ("title", "name"), True),
        "job_company_name": ("experience", ("company", "name"), True),
        "job_company_size": ("experience", ("company", "size"), True),
        "job_company_industry": ("experience", ("company", "industry"), True),
        "industry": ("experience", ("company", "industry"), True),
        "job_company_location_name": (
            "experience",
            ("company", "location", "name"),
            True,
        ),
        "location_name": ("location_names", (), False),
        "location_country": ("countries", (), False),
        "summary": ("_source_values", (), False),
    }

    assert {
        field: (contract.root, contract.members, contract.selected_experience)
        for field, contract in FIELD_SOURCE_CONTRACTS.items()
    } == expected


def test_every_supported_canonical_field_accepts_its_independently_declared_path():
    payload = valid_payload()

    assert validated_importer_metadata(payload) is not None
    assert {
        field: validated_metadata_text(payload, field)
        for field in payload["_importer"]["canonical_sources"]
    } == {
        "job_title": "研究工程师",
        "job_company_name": "Société Exemple",
        "job_company_size": "201-500",
        "job_company_industry": "Énergie propre",
        "industry": "Énergie propre",
        "job_company_location_name": "Zürich",
        "location_name": "São Paulo",
        "location_country": "Brasil",
        "summary": "Crée des systèmes fiables — à grande échelle.",
    }


@pytest.mark.parametrize(
    ("field", "path", "canonical"),
    [
        ("industry", "experience[1].company.name", "Société Exemple"),
        ("job_company_name", "experience[1].company.industry", "Énergie propre"),
        ("job_title", "experience[1].company.name", "Société Exemple"),
        ("location_country", "experience[1].company.size", "201-500"),
        ("location_name", "experience[1].company.size", "201-500"),
        ("summary", "experience[1].company.name", "Société Exemple"),
        ("job_title", "experience[0].title.name", "Earlier Engineer"),
        ("industry", "location_names[1]", "São Paulo"),
    ],
)
def test_cross_wired_or_non_selected_paths_fail_closed_despite_equal_values(field, path, canonical):
    payload = valid_payload()
    payload[field] = canonical
    payload["_importer"]["canonical_sources"][field] = path

    assert validated_importer_metadata(payload) is None
    assert validated_metadata_text(payload, field) == ""


def test_matching_valid_path_with_wrong_typed_value_fails_closed():
    payload = valid_payload()
    experiences = ast.literal_eval(payload["experience"])
    experiences[1]["company"]["size"] = 500
    payload["experience"] = repr(experiences)
    payload["job_company_size"] = 500

    assert validated_importer_metadata(payload) is None


def test_unknown_canonical_field_fails_closed():
    payload = valid_payload()
    payload["unknown_field"] = "Brasil"
    payload["_importer"]["canonical_sources"]["unknown_field"] = "countries[0]"

    assert validated_importer_metadata(payload) is None


@pytest.mark.parametrize(
    "path",
    [
        "experience[-1].title.name",
        "experience[01].title.name",
        "experience[0].title.*",
        "experience[0]..title.name",
        "experience[0].title.name.extra",
        "experience[0].title.name]",
        "experience[].title.name",
        "experience[0][title]",
        "experience[0].company\\.name",
        "../experience[0].title.name",
        "countries[0]trailing",
        "countries[00]",
        "countries[*]",
        "countries[]",
        ".countries[0]",
        "_source_values[+1]",
        "",
    ],
)
def test_source_path_parser_rejects_malformed_or_language_like_paths(path):
    assert parse_source_path(path) is None


def test_selected_experience_metadata_must_agree_with_shared_policy():
    payload = valid_payload()
    payload["_importer"]["selected_experience_source_order"] = 0

    assert validated_importer_metadata(payload) is None


def test_summary_position_must_agree_with_layout():
    payload = deepcopy(valid_payload())
    payload["_source_values"]["43"] = payload["summary"]
    payload["_importer"]["canonical_sources"]["summary"] = "_source_values[43]"

    assert validated_importer_metadata(payload) is None
