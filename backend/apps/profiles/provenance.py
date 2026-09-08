"""Validation for importer-owned canonical provenance."""

import ast
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .experience_policy import select_source_experience
from .semantic_values import scalar_anomaly

IMPORTER_METADATA_KEY = "_importer"
SOURCE_VALUES_KEY = "_source_values"
MAPPING_VERSION = "canonical-v2"
SUPPORTED_LAYOUT_NAMES = frozenset(
    {
        "legacy-facebook-appended-77",
        *(f"reordered-block-{start}" for start in (25, 28, 39, 40, 41, 44, 45, 46, 48)),
    }
)
_LAYOUT_COLLECTION_STARTS = MappingProxyType(
    {
        "legacy-facebook-appended-77": 42,
        **{f"reordered-block-{start}": start for start in (25, 28, 39, 40, 41, 44, 45, 46, 48)},
    }
)
_METADATA_FIELDS = frozenset(
    {"mapping_version", "layout", "canonical_sources", "selected_experience_source_order"}
)
_NULL_VALUES = {"", "null", "none", "nan", "n/a", "na"}
_INDEX_PATTERN = r"(?:0|[1-9]\d{0,5})"
_COLLECTION_PATH_RE = re.compile(
    rf"\A(?P<root>location_names|countries|{re.escape(SOURCE_VALUES_KEY)})"
    rf"\[(?P<index>{_INDEX_PATTERN})\]\Z"
)
_EXPERIENCE_PATH_RE = re.compile(
    rf"\Aexperience\[(?P<index>{_INDEX_PATTERN})\]\."
    r"(?P<members>title\.name|company\.name|company\.size|company\.industry|"
    r"company\.location\.name)\Z"
)


@dataclass(frozen=True)
class ParsedSourcePath:
    root: str
    index: int
    members: tuple[str, ...] = ()


@dataclass(frozen=True)
class FieldSourceContract:
    root: str
    members: tuple[str, ...]
    semantic_field: str
    selected_experience: bool = False
    first_scalar: bool = False
    layout_summary_position: bool = False


FIELD_SOURCE_CONTRACTS = MappingProxyType(
    {
        "job_title": FieldSourceContract(
            "experience", ("title", "name"), "job_title", selected_experience=True
        ),
        "job_company_name": FieldSourceContract(
            "experience", ("company", "name"), "job_company_name", selected_experience=True
        ),
        "job_company_size": FieldSourceContract(
            "experience", ("company", "size"), "job_company_size", selected_experience=True
        ),
        "job_company_industry": FieldSourceContract(
            "experience", ("company", "industry"), "industry", selected_experience=True
        ),
        "industry": FieldSourceContract(
            "experience", ("company", "industry"), "industry", selected_experience=True
        ),
        "job_company_location_name": FieldSourceContract(
            "experience",
            ("company", "location", "name"),
            "job_company_location_name",
            selected_experience=True,
        ),
        "location_name": FieldSourceContract(
            "location_names", (), "location_name", first_scalar=True
        ),
        "location_country": FieldSourceContract(
            "countries", (), "location_country", first_scalar=True
        ),
        "summary": FieldSourceContract(
            SOURCE_VALUES_KEY, (), "summary", layout_summary_position=True
        ),
    }
)
CANONICAL_SOURCE_FIELDS = frozenset(FIELD_SOURCE_CONTRACTS)


def _normalize(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _parse_literal(value: object):
    if not isinstance(value, str) or value.strip().casefold() in _NULL_VALUES:
        return None
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError, TypeError, MemoryError):
        return None


def parse_source_path(path: object) -> ParsedSourcePath | None:
    """Parse only the bounded source paths emitted by the importer."""

    if not isinstance(path, str):
        return None
    match = _EXPERIENCE_PATH_RE.fullmatch(path)
    if match:
        return ParsedSourcePath(
            root="experience",
            index=int(match.group("index")),
            members=tuple(match.group("members").split(".")),
        )
    match = _COLLECTION_PATH_RE.fullmatch(path)
    if match:
        return ParsedSourcePath(root=match.group("root"), index=int(match.group("index")))
    return None


def _source_collection(payload: Mapping, root: str):
    if root == SOURCE_VALUES_KEY:
        values = payload.get(root)
        return values if isinstance(values, Mapping) else None
    values = _parse_literal(payload.get(root))
    return values if isinstance(values, list) else None


def _resolve_source_path(payload: Mapping, path: ParsedSourcePath):
    if path.root == "experience":
        values = _source_collection(payload, path.root)
        if values is None or path.index >= len(values):
            return None
        value = values[path.index]
        for member in path.members:
            if not isinstance(value, Mapping) or member not in value:
                return None
            value = value[member]
        return value
    values = _source_collection(payload, path.root)
    if values is None:
        return None
    if isinstance(values, list):
        return values[path.index] if path.index < len(values) else None
    return values.get(str(path.index))


def _first_scalar_index(payload: Mapping, root: str) -> int | None:
    values = _source_collection(payload, root)
    if not isinstance(values, list):
        return None
    return next(
        (
            index
            for index, value in enumerate(values)
            if isinstance(value, str)
            and _normalize(value)
            and _normalize(value).casefold() not in _NULL_VALUES
        ),
        None,
    )


def _selected_source_order(payload: Mapping) -> int | None:
    experiences = _source_collection(payload, "experience")
    if not isinstance(experiences, list):
        return None
    selection = select_source_experience(experiences)
    return selection[0] if selection else None


def _path_matches_contract(
    payload: Mapping,
    layout: str,
    selected_order: int | None,
    path: ParsedSourcePath,
    contract: FieldSourceContract,
) -> bool:
    if path.root != contract.root or path.members != contract.members:
        return False
    if contract.selected_experience and path.index != selected_order:
        return False
    if contract.first_scalar and path.index != _first_scalar_index(payload, path.root):
        return False
    if contract.layout_summary_position:
        return path.index == _LAYOUT_COLLECTION_STARTS[layout] - 1
    return True


def validated_importer_metadata(payload: object) -> dict | None:
    """Return validated importer metadata, or ``None`` for any invalid contract."""

    if not isinstance(payload, Mapping):
        return None
    metadata = payload.get(IMPORTER_METADATA_KEY)
    if not isinstance(metadata, Mapping) or set(metadata) != _METADATA_FIELDS:
        return None
    if metadata.get("mapping_version") != MAPPING_VERSION:
        return None
    layout = metadata.get("layout")
    if layout not in SUPPORTED_LAYOUT_NAMES:
        return None
    selected_order = metadata.get("selected_experience_source_order")
    if selected_order is not None and (
        isinstance(selected_order, bool)
        or not isinstance(selected_order, int)
        or selected_order < 0
    ):
        return None
    if selected_order != _selected_source_order(payload):
        return None
    sources = metadata.get("canonical_sources")
    if not isinstance(sources, Mapping) or not set(sources).issubset(CANONICAL_SOURCE_FIELDS):
        return None
    for field_name, raw_path in sources.items():
        contract = FIELD_SOURCE_CONTRACTS[field_name]
        path = parse_source_path(raw_path)
        if path is None or not _path_matches_contract(
            payload, layout, selected_order, path, contract
        ):
            return None
        resolved = _resolve_source_path(payload, path)
        canonical = payload.get(field_name)
        if not isinstance(resolved, str) or not isinstance(canonical, str):
            return None
        if _normalize(resolved) != _normalize(canonical):
            return None
        if scalar_anomaly(contract.semantic_field, canonical):
            return None
    return dict(metadata)


def validated_metadata_text(
    payload: object, field_name: str, destination: str | None = None
) -> str:
    metadata = validated_importer_metadata(payload)
    if metadata is None or field_name not in metadata["canonical_sources"]:
        return ""
    value = payload.get(field_name) if isinstance(payload, Mapping) else None
    normalized = _normalize(value) if isinstance(value, str) else ""
    return "" if scalar_anomaly(destination or field_name, normalized) else normalized
