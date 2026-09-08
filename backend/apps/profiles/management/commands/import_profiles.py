import ast
import csv
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from apps.profiles.experience_policy import select_source_experience
from apps.profiles.models import Education, Experience, Profile, Skill
from apps.profiles.provenance import (
    IMPORTER_METADATA_KEY,
    MAPPING_VERSION,
    SOURCE_VALUES_KEY,
    SUPPORTED_LAYOUT_NAMES,
)
from apps.profiles.semantic_values import scalar_anomaly

EXPECTED_HEADER = (
    "full_name",
    "first_name",
    "last_name",
    "gender",
    "linkedin_url",
    "linkedin_username",
    "linkedin_id",
    "facebook_url",
    "facebook_username",
    "facebook_id",
    "industry",
    "job_title",
    "job_title_role",
    "job_title_levels",
    "job_company_id",
    "job_company_name",
    "job_company_website",
    "job_company_size",
    "job_company_founded",
    "job_company_industry",
    "job_company_linkedin_url",
    "job_company_linkedin_id",
    "job_company_facebook_url",
    "job_company_twitter_url",
    "job_company_location_name",
    "job_company_location_locality",
    "job_company_location_metro",
    "job_company_location_region",
    "job_company_location_geo",
    "job_company_location_country",
    "job_company_location_continent",
    "job_last_updated",
    "job_start_date",
    "location_name",
    "location_locality",
    "location_metro",
    "location_region",
    "location_country",
    "location_continent",
    "location_geo",
    "location_last_updated",
    "linkedin_connections",
    "inferred_salary",
    "inferred_years_experience",
    "summary",
    "phone_numbers",
    "emails",
    "interests",
    "skills",
    "location_names",
    "regions",
    "countries",
    "street_addresses",
    "experience",
    "education",
    "profiles",
    "certifications",
    "languages",
    "version_status",
    "work_email",
    "job_company_location_street_address",
    "job_company_location_postal_code",
    "job_summary",
    "location_street_address",
    "location_postal_code",
    "middle_initial",
    "middle_name",
    "birth_year",
    "birth_date",
    "twitter_url",
    "twitter_username",
    "github_url",
    "github_username",
    "mobile_phone",
    "location_address_line_2",
    "job_title_sub_role",
    "job_company_location_address_line_2",
)

NULL_TOKENS = {"", "null", "none", "nan", "n/a", "na"}
USERNAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,254}\Z")
DATE_RE = re.compile(r"\A(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?\Z")
MIN_ACCEPTED_LAYOUT_SCORE = 40
MIN_ACCEPTED_LAYOUT_MARGIN = 20


@dataclass(frozen=True)
class SourceLayout:
    name: str
    canonical_to_source: tuple[int | None, ...]


def _structured_layout(name: str, collection_start: int) -> SourceLayout:
    canonical_to_source: list[int | None] = [None] * len(EXPECTED_HEADER)
    for position in range(7):
        canonical_to_source[position] = position
    canonical_to_source[EXPECTED_HEADER.index("summary")] = collection_start - 1
    for offset, canonical_name in enumerate(EXPECTED_HEADER[45:59]):
        canonical_to_source[EXPECTED_HEADER.index(canonical_name)] = collection_start + offset
    return SourceLayout(name, tuple(canonical_to_source))


SOURCE_LAYOUTS = (
    _structured_layout("legacy-facebook-appended-77", 42),
    *(
        _structured_layout(f"reordered-block-{start}", start)
        for start in (25, 28, 39, 40, 41, 44, 45, 46, 48)
    ),
)

LAYOUT_BY_NAME = {layout.name: layout for layout in SOURCE_LAYOUTS}


@dataclass
class ImportStats:
    logical_records: int = 0
    exact_width_records: int = 0
    malformed_width_records: int = 0
    repeated_header_records: int = 0
    identity_invalid_records: int = 0
    identity_conflict_records: int = 0
    display_name_invalid_records: int = 0
    accepted_profile_rows: int = 0
    duplicate_rows: int = 0
    unique_profile_ids: set[int] = field(default_factory=set)
    invalid_scalar_fields: Counter[str] = field(default_factory=Counter)
    invalid_skills_fields: Counter[str] = field(default_factory=Counter)
    skipped_skill_items: int = 0
    invalid_experience_fields: Counter[str] = field(default_factory=Counter)
    skipped_experience_items: int = 0
    invalid_education_fields: Counter[str] = field(default_factory=Counter)
    skipped_education_items: int = 0
    invalid_dates: int = 0
    oversized_fields: Counter[str] = field(default_factory=Counter)
    detected_layouts: Counter[str] = field(default_factory=Counter)
    layout_ambiguous_records: int = 0
    unknown_layout_records: int = 0
    semantic_warnings: Counter[str] = field(default_factory=Counter)
    profiles_created: int = 0
    profiles_updated: int = 0
    profiles_unchanged: int = 0
    profiles_deleted: int = 0
    skills_created: int = 0
    skills_reused: int = 0
    skills_deleted: int = 0
    experiences_created: int = 0
    experiences_updated: int = 0
    experiences_unchanged: int = 0
    experiences_deleted: int = 0
    education_created: int = 0
    education_updated: int = 0
    education_unchanged: int = 0
    education_deleted: int = 0
    quarantine: list[tuple[int, int, int, str]] = field(default_factory=list)

    @property
    def unique_profiles(self) -> int:
        return len(self.unique_profile_ids)


@dataclass(frozen=True)
class FieldValue:
    state: str
    value: object = None


@dataclass(frozen=True)
class NestedItem:
    values: dict[str, object]
    invalid_fields: frozenset[str] = frozenset()


@dataclass(frozen=True)
class CollectionValue:
    state: str
    items: tuple[NestedItem, ...] = ()
    invalid_positions: frozenset[int] = frozenset()


@dataclass(frozen=True)
class ValidatedRow:
    fields: dict[str, FieldValue]
    aliases: dict[str, str]
    skills: FieldValue
    experience: CollectionValue
    education: CollectionValue
    raw_payload: dict[str, str]
    logical_record: int
    physical_start: int
    physical_end: int


@dataclass(frozen=True)
class ImportPlan:
    fields: dict[str, FieldValue]
    aliases: dict[str, str]
    skills: FieldValue
    experience: CollectionValue
    education: CollectionValue
    raw_payload: dict[str, str]
    rows: tuple[ValidatedRow, ...]


def is_null(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip().casefold() in NULL_TOKENS)


def normalized_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def collapsed_text(value: str) -> str:
    return " ".join(normalized_text(value).split())


def is_structured_text(value: object) -> bool:
    if not isinstance(value, str) or not value.lstrip().startswith(("[", "{", "(")):
        return False
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError, TypeError, MemoryError):
        return True
    return isinstance(parsed, (list, dict, tuple, set))


def canonical_id(value: object) -> str | None:
    if is_null(value) or not isinstance(value, str):
        return None
    normalized = normalized_text(value)
    if len(normalized) > 255 or any(char.isspace() for char in normalized):
        return None
    if any(character in normalized for character in ("/", "\\", ":")):
        return None
    return normalized.casefold() or None


def canonical_username(value: object) -> str | None:
    if is_null(value) or not isinstance(value, str):
        return None
    normalized = collapsed_text(value).casefold()
    return normalized if USERNAME_RE.fullmatch(normalized) else None


def canonical_url(value: object) -> str | None:
    if is_null(value) or not isinstance(value, str):
        return None
    normalized = normalized_text(value)
    if any(char.isspace() for char in normalized):
        return None
    candidate = normalized if "://" in normalized else f"https://{normalized}"
    try:
        parsed = urlsplit(candidate)
        host = parsed.hostname.casefold() if parsed.hostname else ""
        port = parsed.port
    except ValueError:
        return None
    if port is not None or parsed.username or parsed.password:
        return None
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        return None
    path_parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(path_parts) != 2 or path_parts[0].casefold() not in {"in", "pub"}:
        return None
    slug = collapsed_text(path_parts[1]).casefold()
    if USERNAME_RE.fullmatch(slug) is None:
        return None
    canonical = f"https://{host}/{path_parts[0].casefold()}/{slug}"
    return canonical if len(canonical) <= 500 else None


def source_date(value: object, *, end: bool) -> tuple[date | None, bool]:
    if is_null(value):
        return None, True
    if not isinstance(value, str):
        return None, False
    match = DATE_RE.fullmatch(normalized_text(value))
    if match is None:
        return None, False
    year, month, day = match.groups()
    try:
        if month is None:
            return date(int(year), 12 if end else 1, 31 if end else 1), True
        if day is None:
            last_day = (
                31
                if int(month) == 12
                else (date(int(year), int(month) + 1, 1) - date.resolution).day
            )
            return (
                date(int(year), int(month), last_day) if end else date(int(year), int(month), 1)
            ), True
        return date(int(year), int(month), int(day)), True
    except ValueError:
        return None, False


def literal_value(value: object) -> tuple[object | None, bool]:
    if is_null(value) or not isinstance(value, str):
        return None, False
    try:
        return ast.literal_eval(value), True
    except (SyntaxError, ValueError, TypeError, MemoryError):
        return None, False


class Command(BaseCommand):
    help = "Import LinkedIn profile records from the private 77-column CSV dataset."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--path", required=True, type=Path)

    def handle(self, *args, **options) -> None:
        path: Path = options["path"]
        if not path.is_file():
            raise CommandError(f"Dataset file not found: {path}")
        stats = ImportStats()
        try:
            with path.open("r", encoding="utf-8", newline="") as source:
                reader = csv.reader(source, delimiter=",", quotechar='"')
                try:
                    header = next(reader)
                except StopIteration:
                    raise CommandError(
                        "Invalid or missing header: expected exactly 77 columns."
                    ) from None
                if tuple(header) != EXPECTED_HEADER:
                    raise CommandError("Invalid or missing header: expected exactly 77 columns.")
                candidates = self._parse_rows(reader, header, stats)
        except UnicodeDecodeError as exc:
            raise CommandError("Dataset must be UTF-8 encoded.") from exc
        plans = self._consolidate(candidates, stats)
        with transaction.atomic():
            corrective_skill_ids = self._broken_mapping_skill_ids()
            self._remove_known_repeated_header_profile(stats)
            for plan in plans:
                self._persist_plan(plan, stats)
            if corrective_skill_ids:
                stale_skills = Skill.objects.filter(
                    pk__in=corrective_skill_ids, profiles__isnull=True
                )
                stats.skills_deleted = stale_skills.count()
                stale_skills.delete()
        self._write_summary(stats)

    @staticmethod
    def _broken_mapping_skill_ids() -> set[int]:
        skill_ids: set[int] = set()
        profiles = Profile.objects.prefetch_related("skills").exclude(raw_payload={})
        for profile in profiles.iterator(chunk_size=500):
            if Command._has_broken_mapping_provenance(profile.raw_payload):
                skill_ids.update(skill.pk for skill in profile.skills.all())
        return skill_ids

    def _remove_known_repeated_header_profile(self, stats) -> None:
        candidates = list(Profile.objects.select_for_update().order_by("pk"))
        proven = [profile for profile in candidates if self._is_historical_header_profile(profile)]
        if len(proven) > 1:
            raise CommandError("Repeated-header cleanup found multiple proven candidates.")
        if proven:
            proven[0].delete()
            stats.profiles_deleted += 1

    @staticmethod
    def _is_historical_header_profile(profile: Profile) -> bool:
        payload = profile.raw_payload
        if not isinstance(payload, dict):
            return False
        if set(payload) != {*EXPECTED_HEADER, "_source_layout"}:
            return False
        if payload.get("_source_layout") != "reordered-block-45":
            return False
        if any(payload.get(name) != name for name in EXPECTED_HEADER):
            return False
        return (
            profile.public_identifier == "linkedin:id:linkedin_id"
            and profile.full_name == "full_name"
            and profile.first_name == "first_name"
            and profile.last_name == "last_name"
            and profile.linkedin_id == "linkedin_id"
            and profile.linkedin_username == "linkedin_username"
            and profile.profile_url is None
        )

    def _parse_rows(self, reader, header: list[str], stats: ImportStats) -> list[ValidatedRow]:
        candidates: list[ValidatedRow] = []
        previous_physical_line = reader.line_num
        for row in reader:
            stats.logical_records += 1
            physical_start = previous_physical_line + 1
            physical_end = reader.line_num
            previous_physical_line = physical_end
            logical_record = stats.logical_records
            if len(row) != len(EXPECTED_HEADER):
                stats.malformed_width_records += 1
                stats.quarantine.append(
                    (logical_record, physical_start, physical_end, "STRUCTURAL_WIDTH")
                )
                continue
            stats.exact_width_records += 1
            if tuple(row) == EXPECTED_HEADER:
                stats.repeated_header_records += 1
                stats.quarantine.append(
                    (logical_record, physical_start, physical_end, "STRUCTURAL_REPEATED_HEADER")
                )
                continue
            layout, reason = self._detect_layout(row)
            if layout is None:
                if reason == "AMBIGUOUS_LAYOUT":
                    stats.layout_ambiguous_records += 1
                else:
                    stats.unknown_layout_records += 1
                stats.quarantine.append((logical_record, physical_start, physical_end, reason))
                continue
            stats.detected_layouts[layout.name] += 1
            raw_payload = self._map_raw_payload(row, layout)
            candidate = self._validate_row(
                row, layout, raw_payload, stats, logical_record, physical_start, physical_end
            )
            if candidate is None:
                stats.quarantine.append(
                    (logical_record, physical_start, physical_end, "IDENTITY_INVALID")
                )
                continue
            candidates.append(candidate)
        stats.accepted_profile_rows = len(candidates)
        return candidates

    def _detect_layout(self, row) -> tuple[SourceLayout | None, str]:
        matches: list[tuple[SourceLayout, int]] = []
        for layout in SOURCE_LAYOUTS:
            if self._layout_has_required_shape(row, layout):
                matches.append((layout, self._layout_score(row, layout)))
        if not matches:
            return None, "UNKNOWN_LAYOUT"
        matches.sort(key=lambda item: (-item[1], item[0].name))
        strongest = matches[0][1]
        runner_up = matches[1][1] if len(matches) > 1 else 0
        if strongest < MIN_ACCEPTED_LAYOUT_SCORE:
            return None, "UNKNOWN_LAYOUT"
        if strongest - runner_up < MIN_ACCEPTED_LAYOUT_MARGIN:
            return None, "AMBIGUOUS_LAYOUT"
        return matches[0][0], ""

    def _layout_score(self, row, layout) -> int:
        score = 0
        skills = self._mapped(row, layout, "skills")
        if self._literal_list(skills) is not None and self._valid_skills_structure(skills):
            score += 3
        experience = self._mapped(row, layout, "experience")
        parsed_experience = self._literal_list(experience)
        if parsed_experience is not None and self._valid_nested_structure(experience, "experience"):
            score += 20 if parsed_experience else 10
        education = self._mapped(row, layout, "education")
        parsed_education = self._literal_list(education)
        if parsed_education is not None and self._valid_nested_structure(education, "education"):
            score += 20 if parsed_education else 10
        for name in ("phone_numbers", "location_names", "regions", "countries"):
            value = self._literal_list(self._mapped(row, layout, name))
            if value is not None and all(isinstance(item, str) for item in value):
                score += 2
        for name in ("emails", "street_addresses", "profiles"):
            value = self._literal_list(self._mapped(row, layout, name))
            if value is not None and all(isinstance(item, dict) for item in value):
                score += 2
        version, valid = literal_value(self._mapped(row, layout, "version_status"))
        if valid and isinstance(version, dict):
            score += 20 if version else 5
        return score

    def _layout_has_required_shape(self, row, layout: SourceLayout) -> bool:
        try:
            identity_values = {
                name: self._mapped(row, layout, name)
                for name in ("linkedin_id", "linkedin_username", "linkedin_url")
            }
            if not any(
                canonicalizer(identity_values[name]) is not None
                for name, canonicalizer in (
                    ("linkedin_id", canonical_id),
                    ("linkedin_username", canonical_username),
                    ("linkedin_url", canonical_url),
                )
            ):
                return False
            for name in ("full_name", "first_name", "last_name"):
                value = identity_values.get(name) or self._mapped(row, layout, name)
                if is_null(value) or not isinstance(value, str) or is_structured_text(value):
                    return False
        except (IndexError, TypeError):
            return False
        return True

    @classmethod
    def _valid_skills_structure(cls, value) -> bool:
        if is_null(value):
            return True
        parsed = cls._literal_list(value)
        return parsed is not None and (not parsed or any(isinstance(item, str) for item in parsed))

    @classmethod
    def _valid_nested_structure(cls, value, kind: str) -> bool:
        if is_null(value):
            return True
        parsed = cls._literal_list(value)
        if parsed is None or not parsed:
            return parsed == []
        required_keys = {"title", "company"} if kind == "experience" else {"school"}
        return any(isinstance(item, dict) and required_keys.issubset(item) for item in parsed)

    @staticmethod
    def _literal_list(value):
        parsed, valid_literal = literal_value(value)
        return parsed if valid_literal and isinstance(parsed, list) else None

    @staticmethod
    def _mapped(row, layout: SourceLayout, canonical_name: str):
        canonical_position = EXPECTED_HEADER.index(canonical_name)
        source_position = layout.canonical_to_source[canonical_position]
        if source_position is None:
            return None
        return row[source_position]

    def _map_raw_payload(self, row, layout: SourceLayout) -> dict[str, object]:
        payload = {
            name: row[source_position]
            for name, source_position in zip(
                EXPECTED_HEADER, layout.canonical_to_source, strict=False
            )
            if source_position is not None
        }
        derived, source_paths, selected_order = self._derive_canonical_scalars(row, layout)
        payload.update(derived)
        payload[SOURCE_VALUES_KEY] = {
            str(source_position): value for source_position, value in enumerate(row)
        }
        payload[IMPORTER_METADATA_KEY] = {
            "mapping_version": MAPPING_VERSION,
            "layout": layout.name,
            "canonical_sources": {
                name: path for name, path in source_paths.items() if payload.get(name)
            },
            "selected_experience_source_order": selected_order,
        }
        return payload

    def _derive_canonical_scalars(
        self, row, layout
    ) -> tuple[dict[str, str], dict[str, str], int | None]:
        experience = self._literal_list(self._mapped(row, layout, "experience")) or []
        selection = select_source_experience(experience)
        selected_order, current = selection if selection else (None, {})
        company = current.get("company") if isinstance(current, dict) else None
        company = company if isinstance(company, dict) else {}
        company_location = company.get("location")
        company_industry = self._source_scalar(company.get("industry"))
        first_location, first_location_index = self._first_string_with_index(
            self._mapped(row, layout, "location_names")
        )
        first_country, first_country_index = self._first_string_with_index(
            self._mapped(row, layout, "countries")
        )

        values = {
            "job_title": self._nested_name(current.get("title")) if current else "",
            "job_company_name": self._nested_name(company),
            "job_company_size": self._source_scalar(company.get("size")),
            "job_company_industry": company_industry,
            "job_company_location_name": self._nested_name(company_location),
            "location_name": first_location,
            "location_country": first_country,
        }
        values["industry"] = company_industry
        source_paths = {}
        if selected_order is not None:
            source_paths.update(
                {
                    "job_title": f"experience[{selected_order}].title.name",
                    "job_company_name": f"experience[{selected_order}].company.name",
                    "job_company_size": f"experience[{selected_order}].company.size",
                    "job_company_industry": f"experience[{selected_order}].company.industry",
                    "job_company_location_name": (
                        f"experience[{selected_order}].company.location.name"
                    ),
                }
            )
        if company_industry and selected_order is not None:
            source_paths["industry"] = f"experience[{selected_order}].company.industry"
        if first_location_index is not None:
            source_paths["location_name"] = f"location_names[{first_location_index}]"
        if first_country_index is not None:
            source_paths["location_country"] = f"countries[{first_country_index}]"
        summary_position = layout.canonical_to_source[EXPECTED_HEADER.index("summary")]
        if summary_position is not None and self._source_scalar(row[summary_position]):
            source_paths["summary"] = f"{SOURCE_VALUES_KEY}[{summary_position}]"
        return {name: value or "" for name, value in values.items()}, source_paths, selected_order

    @staticmethod
    def _source_scalar(value) -> str:
        return collapsed_text(value) if isinstance(value, str) and not is_null(value) else ""

    @classmethod
    def _first_string_with_index(cls, raw_value) -> tuple[str, int | None]:
        values = cls._literal_list(raw_value) or []
        for index, value in enumerate(values):
            if isinstance(value, str) and not is_null(value):
                return collapsed_text(value), index
        return "", None

    def _validate_row(
        self, row, layout, raw_payload, stats, logical_record, physical_start, physical_end
    ) -> ValidatedRow | None:
        source = raw_payload
        aliases: dict[str, str] = {}
        fields: dict[str, FieldValue] = {}
        for name, canonicalizer in (
            ("linkedin_id", canonical_id),
            ("linkedin_username", canonical_username),
            ("linkedin_url", canonical_url),
        ):
            raw_value = source[name]
            canonical = canonicalizer(raw_value)
            target = "profile_url" if name == "linkedin_url" else name
            if canonical is not None:
                aliases[name] = canonical
                fields[target] = FieldValue("value", canonical)
            elif is_null(raw_value):
                fields[target] = FieldValue("empty", "")
            else:
                fields[target] = FieldValue("invalid")
                stats.invalid_scalar_fields[name] += 1
        if not aliases:
            stats.identity_invalid_records += 1
            return None

        rejected_sources = self._sanitize_metadata(raw_payload, stats)
        for source_name, model_name, max_length in (
            ("full_name", "full_name", 500),
            ("first_name", "first_name", 150),
            ("last_name", "last_name", 150),
            ("job_title", "headline", 500),
            ("location_name", "location", 255),
            ("summary", "summary", None),
        ):
            if source_name in rejected_sources:
                fields[model_name] = FieldValue("invalid")
            else:
                fields[model_name] = self._semantic_scalar_field(
                    source[source_name], source_name, max_length, stats
                )
        if not any(
            fields[name].state == "value" and fields[name].value
            for name in ("full_name", "first_name", "last_name")
        ):
            stats.display_name_invalid_records += 1
            return None
        return ValidatedRow(
            fields=fields,
            aliases=aliases,
            skills=self._validate_skills(source["skills"], stats),
            experience=self._validate_nested(source["experience"], "experience", stats),
            education=self._validate_nested(source["education"], "education", stats),
            raw_payload=raw_payload,
            logical_record=logical_record,
            physical_start=physical_start,
            physical_end=physical_end,
        )

    def _scalar_field(self, raw_value, source_name, max_length, stats) -> FieldValue:
        if is_null(raw_value):
            return FieldValue("empty", "")
        if not isinstance(raw_value, str) or is_structured_text(raw_value):
            stats.invalid_scalar_fields[source_name] += 1
            return FieldValue("invalid")
        value = normalized_text(raw_value)
        if not value:
            return FieldValue("empty", "")
        if max_length is not None and len(value) > max_length:
            stats.invalid_scalar_fields[source_name] += 1
            stats.oversized_fields[source_name] += 1
            return FieldValue("invalid")
        return FieldValue("value", value)

    def _semantic_scalar_field(self, raw_value, source_name, max_length, stats) -> FieldValue:
        field = self._scalar_field(raw_value, source_name, max_length, stats)
        if field.state == "value" and self._semantic_boundary_violation(source_name, field.value):
            stats.invalid_scalar_fields[source_name] += 1
            stats.semantic_warnings[f"{source_name}_boundary"] += 1
            return FieldValue("invalid")
        return field

    @staticmethod
    def _semantic_boundary_violation(field_name: str, value: str) -> bool:
        return scalar_anomaly(field_name, value) is not None

    def _sanitize_metadata(self, raw_payload, stats) -> set[str]:
        rejected_sources = set()
        importer_metadata = raw_payload.get(IMPORTER_METADATA_KEY)
        canonical_sources = (
            importer_metadata.get("canonical_sources")
            if isinstance(importer_metadata, dict)
            else {}
        )
        for field_name in (
            "industry",
            "job_title",
            "job_company_name",
            "job_company_industry",
            "job_company_location_name",
            "location_name",
            "location_country",
            "summary",
        ):
            value = raw_payload.get(field_name)
            if not isinstance(value, str) or is_null(value):
                continue
            reason = scalar_anomaly(field_name, value)
            if reason:
                raw_payload[field_name] = ""
                stats.semantic_warnings[f"{field_name}_boundary"] += 1
                rejected_sources.add(field_name)
                if isinstance(canonical_sources, dict):
                    canonical_sources.pop(field_name, None)
        return rejected_sources

    def _validate_skills(self, raw_value, stats) -> FieldValue:
        if is_null(raw_value):
            return FieldValue("empty", ())
        parsed, valid_literal = literal_value(raw_value)
        if not valid_literal or not isinstance(parsed, list):
            stats.invalid_skills_fields["skills"] += 1
            return FieldValue("invalid")
        if not parsed:
            return FieldValue("empty", ())
        accepted: list[str] = []
        seen: set[str] = set()
        max_length = Skill._meta.get_field("name").max_length
        for item in parsed:
            if not isinstance(item, str) or is_null(item):
                stats.skipped_skill_items += 1
                continue
            normalized = collapsed_text(item).casefold()
            if not normalized or len(normalized) > max_length:
                stats.skipped_skill_items += 1
                if len(normalized) > max_length:
                    stats.oversized_fields["skills"] += 1
                continue
            if normalized not in seen:
                accepted.append(normalized)
                seen.add(normalized)
        if not accepted:
            stats.invalid_skills_fields["skills"] += 1
            return FieldValue("invalid")
        return FieldValue("value", tuple(accepted))

    def _validate_nested(self, raw_value, kind, stats) -> CollectionValue:
        if is_null(raw_value):
            getattr(stats, f"invalid_{kind}_fields")[kind] += 1
            return CollectionValue("invalid")
        parsed, valid_literal = literal_value(raw_value)
        if not valid_literal or not isinstance(parsed, list):
            getattr(stats, f"invalid_{kind}_fields")[kind] += 1
            return CollectionValue("invalid")
        if not parsed:
            return CollectionValue("empty")
        valid_items: list[NestedItem] = []
        invalid_positions: set[int] = set()
        for source_order, item in enumerate(parsed):
            if not isinstance(item, dict):
                invalid_positions.add(source_order)
                setattr(stats, f"skipped_{kind}_items", getattr(stats, f"skipped_{kind}_items") + 1)
                continue
            nested = self._validate_nested_item(item, kind, source_order, stats)
            if nested is None:
                invalid_positions.add(source_order)
                setattr(stats, f"skipped_{kind}_items", getattr(stats, f"skipped_{kind}_items") + 1)
            else:
                if nested.invalid_fields:
                    invalid_positions.add(source_order)
                valid_items.append(nested)
        if not valid_items:
            getattr(stats, f"invalid_{kind}_fields")[kind] += 1
            return CollectionValue("invalid", invalid_positions=frozenset(invalid_positions))
        return CollectionValue("value", tuple(valid_items), frozenset(invalid_positions))

    def _validate_nested_item(self, item, kind, source_order, stats) -> NestedItem | None:
        required_key = "title" if kind == "experience" else "school"
        required = self._nested_name(item.get(required_key))
        if required is None:
            return None
        if kind == "experience" and scalar_anomaly("job_title", required):
            stats.invalid_experience_fields["experience.title"] += 1
            return None
        if len(required) > 255:
            stats.oversized_fields[f"{kind}.{required_key}"] += 1
            return None
        values: dict[str, object] = {"source_order": source_order}
        values["title" if kind == "experience" else "school"] = required
        invalid_fields: set[str] = set()
        if kind == "experience":
            company = self._nested_name(item.get("company"))
            if company is None:
                return None
            if scalar_anomaly("job_company_name", company):
                stats.invalid_experience_fields["experience.company"] += 1
                return None
            if len(company) > 255:
                stats.oversized_fields["experience.company"] += 1
                return None
            values["company"] = company
            location = self._list_field(
                item.get("location_names"), ", ", 255, "experience.location_names", stats
            )
            if location.state == "value" and scalar_anomaly(
                "location_name", ", ".join(location.value)
            ):
                stats.invalid_experience_fields["experience.location_names"] += 1
                location = FieldValue("invalid")
            self._put_nested_field(values, invalid_fields, "location_names", "location", location)
            summary = self._scalar_nested_field(item.get("summary"), "experience.summary", stats)
            if summary.state == "value" and scalar_anomaly("summary", summary.value):
                stats.invalid_experience_fields["experience.summary"] += 1
                summary = FieldValue("invalid")
            self._put_nested_field(values, invalid_fields, "summary", "description", summary)
            self._add_dates(item, values, invalid_fields, "experience", stats)
        else:
            degrees = self._list_field(item.get("degrees"), " | ", 255, "education.degrees", stats)
            self._put_nested_field(values, invalid_fields, "degrees", "degree", degrees)
            majors = self._list_field(item.get("majors"), " | ", 255, "education.majors", stats)
            minors = self._list_field(item.get("minors"), " | ", 255, "education.minors", stats)
            if majors.state == "invalid":
                invalid_fields.add("majors")
            if minors.state == "invalid":
                invalid_fields.add("minors")
            if majors.state != "invalid" and minors.state != "invalid":
                combined = list(majors.value or ())
                combined.extend(value for value in (minors.value or ()) if value not in combined)
                field_of_study = " | ".join(combined)
                if len(field_of_study) <= 255:
                    values["field_of_study"] = field_of_study
                else:
                    invalid_fields.add("field_of_study")
                    stats.oversized_fields["education.field_of_study"] += 1
            else:
                invalid_fields.add("field_of_study")
            self._add_dates(item, values, invalid_fields, "education", stats)
        return NestedItem(values, frozenset(invalid_fields))

    def _nested_name(self, value) -> str | None:
        if isinstance(value, dict):
            value = value.get("name")
        if not isinstance(value, str) or is_null(value):
            return None
        return collapsed_text(value) or None

    def _list_field(self, value, separator, max_length, warning_name, stats) -> FieldValue:
        if is_null(value):
            return FieldValue("empty", ())
        if isinstance(value, str):
            normalized_values = [collapsed_text(value)]
        elif isinstance(value, list):
            if not all(isinstance(item, str) for item in value):
                kind = "experience" if warning_name.startswith("experience") else "education"
                getattr(stats, f"invalid_{kind}_fields")[warning_name] += 1
                return FieldValue("invalid")
            normalized_values = [collapsed_text(item) for item in value]
        else:
            kind = "experience" if warning_name.startswith("experience") else "education"
            getattr(stats, f"invalid_{kind}_fields")[warning_name] += 1
            return FieldValue("invalid")
        unique_values = list(dict.fromkeys(value for value in normalized_values if value))
        joined = separator.join(unique_values)
        if len(joined) > max_length:
            stats.oversized_fields[warning_name] += 1
            return FieldValue("invalid")
        return (
            FieldValue("value", tuple(unique_values)) if unique_values else FieldValue("empty", ())
        )

    def _scalar_nested_field(self, value, warning_name, stats) -> FieldValue:
        if is_null(value):
            return FieldValue("empty", "")
        if not isinstance(value, str):
            kind = "experience" if warning_name.startswith("experience") else "education"
            getattr(stats, f"invalid_{kind}_fields")[warning_name] += 1
            return FieldValue("invalid")
        normalized = normalized_text(value)
        return FieldValue("value", normalized) if normalized else FieldValue("empty", "")

    def _put_nested_field(self, values, invalid_fields, source_name, model_name, field) -> None:
        if field.state == "invalid":
            invalid_fields.add(source_name)
        elif source_name in {"majors", "minors", "degrees"}:
            values[model_name] = " | ".join(field.value or ())
        elif source_name == "location_names":
            values[model_name] = ", ".join(field.value or ())
        else:
            values[model_name] = field.value

    def _add_dates(self, item, values, invalid_fields, kind, stats) -> None:
        for source_name, model_name, is_end in (
            ("start_date", "started_at", False),
            ("end_date", "ended_at", True),
        ):
            parsed, valid = source_date(item.get(source_name), end=is_end)
            if valid:
                values[model_name] = parsed
            else:
                invalid_fields.add(source_name)
                getattr(stats, f"invalid_{kind}_fields")[f"{kind}.{source_name}"] += 1
                stats.invalid_dates += 1

    def _consolidate(self, candidates, stats) -> list[ImportPlan]:
        if not candidates:
            return []
        parent = list(range(len(candidates)))

        def find(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left, right):
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        alias_owner = {}
        for index, candidate in enumerate(candidates):
            for name, value in candidate.aliases.items():
                key = (name, value)
                if key in alias_owner:
                    union(index, alias_owner[key])
                else:
                    alias_owner[key] = index
        grouped = {}
        for index, candidate in enumerate(candidates):
            grouped.setdefault(find(index), []).append(candidate)
        plans = []
        for group in sorted(grouped.values(), key=lambda rows: rows[0].physical_start):
            group.sort(key=lambda row: row.physical_start)
            stats.duplicate_rows += max(0, len(group) - 1)
            plan = self._merge_group(group)
            aliases_by_name = {
                name: {row.aliases[name] for row in group if name in row.aliases}
                for name in ("linkedin_id", "linkedin_username", "linkedin_url")
            }
            if any(len(values) > 1 for values in aliases_by_name.values()):
                self._quarantine_plan(plan, stats, "IDENTITY_CONFLICT")
            else:
                plans.append(plan)
        return plans

    def _merge_group(self, rows) -> ImportPlan:
        merged_fields = dict(rows[0].fields)
        merged_skills = rows[0].skills
        merged_experience = rows[0].experience
        merged_education = rows[0].education
        aliases = {}
        for row in rows:
            aliases.update(row.aliases)
            if row is not rows[0]:
                for name, field_value in row.fields.items():
                    if field_value.state != "invalid":
                        merged_fields[name] = field_value
                if row.skills.state != "invalid":
                    merged_skills = row.skills
                if row.experience.state != "invalid":
                    merged_experience = row.experience
                if row.education.state != "invalid":
                    merged_education = row.education
        return ImportPlan(
            merged_fields,
            aliases,
            merged_skills,
            merged_experience,
            merged_education,
            rows[-1].raw_payload,
            tuple(rows),
        )

    def _persist_plan(self, plan, stats) -> None:
        public_identifier = self._public_identifier(plan.aliases)
        query = Q(public_identifier=public_identifier)
        for name, value in plan.aliases.items():
            if name == "linkedin_id":
                query |= Q(linkedin_id=value)
            elif name == "linkedin_username":
                query |= Q(linkedin_username=value)
            else:
                query |= Q(profile_url=value)
        matches = list(Profile.objects.filter(query).order_by("pk").distinct())
        if len(matches) > 1:
            self._quarantine_plan(plan, stats, "IDENTITY_CONFLICT")
            return
        profile = matches[0] if matches else Profile(public_identifier=public_identifier)
        if profile.pk is None:
            for name, field_value in plan.fields.items():
                if field_value.state == "invalid":
                    continue
                value = self._stored_value(name, field_value)
                setattr(profile, name, value)
            profile.public_identifier = public_identifier
            profile.raw_payload = plan.raw_payload
            profile.save()
            stats.profiles_created += 1
        else:
            changed_fields = []
            repairing_broken_mapping = self._has_broken_mapping_provenance(profile.raw_payload)
            for name, field_value in plan.fields.items():
                if field_value.state == "invalid":
                    if (
                        repairing_broken_mapping
                        and name in {"headline", "location", "summary"}
                        and getattr(profile, name) != ""
                    ):
                        setattr(profile, name, "")
                        changed_fields.append(name)
                    continue
                value = self._stored_value(name, field_value)
                if getattr(profile, name) != value:
                    setattr(profile, name, value)
                    changed_fields.append(name)
            if profile.public_identifier != public_identifier:
                profile.public_identifier = public_identifier
                changed_fields.append("public_identifier")
            if profile.raw_payload != plan.raw_payload:
                profile.raw_payload = plan.raw_payload
                changed_fields.append("raw_payload")
            if changed_fields:
                profile.save(update_fields=[*dict.fromkeys(changed_fields), "updated_at"])
                stats.profiles_updated += 1
            else:
                stats.profiles_unchanged += 1
        stats.unique_profile_ids.add(profile.pk)
        self._write_skills(profile, plan.skills, stats)
        self._write_nested(profile, plan.experience, "experience", stats)
        self._write_nested(profile, plan.education, "education", stats)

    @staticmethod
    def _has_broken_mapping_provenance(payload) -> bool:
        if not isinstance(payload, dict):
            return False
        if payload.get("_source_layout") not in SUPPORTED_LAYOUT_NAMES:
            return False
        if any(key in payload for key in (IMPORTER_METADATA_KEY, SOURCE_VALUES_KEY)):
            return False
        if set(payload) - {*EXPECTED_HEADER, "_source_layout", "_unmapped_source_values"}:
            return False
        return len(set(payload).intersection(EXPECTED_HEADER)) >= 4

    def _stored_value(self, name, field_value):
        if field_value.state == "empty" and name in {
            "linkedin_id",
            "linkedin_username",
            "profile_url",
        }:
            return None
        return field_value.value

    def _quarantine_plan(self, plan, stats, reason) -> None:
        stats.identity_conflict_records += len(plan.rows)
        for row in plan.rows:
            stats.quarantine.append(
                (row.logical_record, row.physical_start, row.physical_end, reason)
            )

    def _write_skills(self, profile, skills, stats) -> None:
        if skills.state == "invalid":
            return
        desired = set(skills.value or ())
        current = set(profile.skills.values_list("name", flat=True))
        if desired == current:
            return
        if not desired:
            profile.skills.clear()
            return
        skill_objects = []
        for name in skills.value:
            skill, created = Skill.objects.get_or_create(name=name)
            skill_objects.append(skill)
            if created:
                stats.skills_created += 1
            else:
                stats.skills_reused += 1
        profile.skills.set(skill_objects)

    def _write_nested(self, profile, collection, kind, stats) -> None:
        relation = profile.experiences if kind == "experience" else profile.educations
        model = Experience if kind == "experience" else Education
        prefix = "experiences" if kind == "experience" else "education"
        if collection.state == "invalid":
            setattr(
                stats,
                f"{prefix}_unchanged",
                getattr(stats, f"{prefix}_unchanged") + relation.count(),
            )
            return
        if collection.state == "empty":
            deleted = relation.count()
            relation.all().delete()
            setattr(stats, f"{prefix}_deleted", getattr(stats, f"{prefix}_deleted") + deleted)
            return
        existing = {record.source_order: record for record in relation.all()}
        incoming_orders = {item.values["source_order"] for item in collection.items}
        touched_existing = set()
        for item in collection.items:
            source_order = item.values["source_order"]
            record = existing.get(source_order)
            if record is None:
                model.objects.create(profile=profile, **item.values)
                setattr(stats, f"{prefix}_created", getattr(stats, f"{prefix}_created") + 1)
                continue
            touched_existing.add(source_order)
            changed_fields = []
            for name, value in item.values.items():
                if (
                    name != "source_order"
                    and name not in item.invalid_fields
                    and getattr(record, name) != value
                ):
                    setattr(record, name, value)
                    changed_fields.append(name)
            if changed_fields:
                record.save(update_fields=changed_fields)
                setattr(stats, f"{prefix}_updated", getattr(stats, f"{prefix}_updated") + 1)
            else:
                setattr(stats, f"{prefix}_unchanged", getattr(stats, f"{prefix}_unchanged") + 1)
        if not collection.invalid_positions:
            stale_orders = set(existing) - incoming_orders
            if stale_orders:
                stale = relation.filter(source_order__in=stale_orders)
                deleted = stale.count()
                stale.delete()
                setattr(stats, f"{prefix}_deleted", getattr(stats, f"{prefix}_deleted") + deleted)
        elif existing.keys() - touched_existing:
            preserved = len(existing.keys() - touched_existing)
            setattr(stats, f"{prefix}_unchanged", getattr(stats, f"{prefix}_unchanged") + preserved)

    def _public_identifier(self, aliases) -> str:
        if "linkedin_id" in aliases:
            return f"linkedin:id:{aliases['linkedin_id']}"
        if "linkedin_username" in aliases:
            return f"linkedin:username:{aliases['linkedin_username']}"
        return f"linkedin:url:{aliases['linkedin_url']}"

    def _write_summary(self, stats) -> None:
        self.stdout.write("Row:")
        for name in (
            "logical_records",
            "exact_width_records",
            "malformed_width_records",
            "repeated_header_records",
            "unknown_layout_records",
            "layout_ambiguous_records",
            "identity_invalid_records",
            "identity_conflict_records",
            "display_name_invalid_records",
            "accepted_profile_rows",
            "duplicate_rows",
            "unique_profiles",
        ):
            self.stdout.write(f"  {name}: {getattr(stats, name)}")
        self.stdout.write("Fields:")
        for name in (
            "detected_layouts",
            "invalid_scalar_fields",
            "invalid_skills_fields",
            "skipped_skill_items",
            "invalid_experience_fields",
            "skipped_experience_items",
            "invalid_education_fields",
            "skipped_education_items",
            "invalid_dates",
            "oversized_fields",
            "semantic_warnings",
        ):
            value = getattr(stats, name)
            rendered = dict(sorted(value.items())) if isinstance(value, Counter) else value
            self.stdout.write(f"  {name}: {rendered}")
        self.stdout.write("Database:")
        for name in (
            "profiles_created",
            "profiles_updated",
            "profiles_unchanged",
            "profiles_deleted",
            "skills_created",
            "skills_reused",
            "skills_deleted",
            "experiences_created",
            "experiences_updated",
            "experiences_unchanged",
            "experiences_deleted",
            "education_created",
            "education_updated",
            "education_unchanged",
            "education_deleted",
        ):
            self.stdout.write(f"  {name}: {getattr(stats, name)}")
        if stats.quarantine:
            self.stdout.write("Quarantine:")
            for logical, physical_start, physical_end, reason in stats.quarantine:
                self.stdout.write(
                    f"  logical {logical}; physical {physical_start}-{physical_end}; {reason}"
                )
