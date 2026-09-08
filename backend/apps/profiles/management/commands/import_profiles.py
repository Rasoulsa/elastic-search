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

from apps.profiles.models import Education, Experience, Profile, Skill

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
COMPANY_SIZE_RE = re.compile(r"\A\d+\s*-\s*\d+\Z")
NUMBER_RE = re.compile(r"\A\d+(?:\.\d+)?\Z")


@dataclass(frozen=True)
class SourceLayout:
    name: str
    canonical_to_source: tuple[int | None, ...]

    @property
    def unmapped_source_positions(self) -> tuple[int, ...]:
        mapped = {position for position in self.canonical_to_source if position is not None}
        return tuple(position for position in range(len(EXPECTED_HEADER)) if position not in mapped)


def _source_layout(name: str, source_order: list[int | None]) -> SourceLayout:
    canonical_to_source: list[int | None] = [None] * len(EXPECTED_HEADER)
    for source_position, canonical_position in enumerate(source_order):
        if canonical_position is None or canonical_to_source[canonical_position] is not None:
            continue
        canonical_to_source[canonical_position] = source_position
    return SourceLayout(name, tuple(canonical_to_source))


def _reordered_block_layout(block_start: int) -> SourceLayout:
    source_order = (
        list(range(0, block_start - 1))
        + [44]
        + list(range(45, 59))
        + list(range(block_start - 1, 44))
        + list(range(59, 77))
    )
    return _source_layout(f"reordered-block-{block_start}", source_order)


SOURCE_LAYOUTS = (
    _source_layout(
        "legacy-facebook-appended-77",
        list(range(0, 7)) + list(range(10, 77)) + list(range(7, 10)),
    ),
    *(_reordered_block_layout(start) for start in (25, 28, 39, 40, 41, 44, 45)),
    _source_layout(
        "reordered-block-46",
        list(range(0, 44)) + [None] + [44] + list(range(45, 59)) + list(range(59, 76)),
    ),
    _source_layout(
        "reordered-block-48",
        list(range(0, 44)) + [None, None, None] + [44] + list(range(45, 59)) + list(range(59, 74)),
    ),
)

LAYOUT_BY_NAME = {layout.name: layout for layout in SOURCE_LAYOUTS}


@dataclass
class ImportStats:
    logical_records: int = 0
    exact_width_records: int = 0
    malformed_width_records: int = 0
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
    skills_created: int = 0
    skills_reused: int = 0
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
            for plan in plans:
                self._persist_plan(plan, stats)
        self._write_summary(stats)

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
            layout, reason = self._detect_layout(row)
            if layout is None:
                if reason == "STRUCTURAL_LAYOUT_AMBIGUOUS":
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
            if not self._layout_has_required_shape(row, layout):
                continue
            strong_fields = sum(
                self._has_nonempty_literal_list(self._mapped(row, layout, name))
                for name in ("skills", "experience", "education", "profiles")
            )
            matches.append((layout, strong_fields))
        if not matches:
            return None, "STRUCTURAL_LAYOUT"
        strongest = max(score for _, score in matches)
        if strongest == 0:
            header_layout = LAYOUT_BY_NAME["reordered-block-45"]
            if any(layout == header_layout for layout, _ in matches):
                return header_layout, ""
            if len(matches) == 1:
                return matches[0][0], ""
            return None, "STRUCTURAL_LAYOUT_AMBIGUOUS"
        best = [layout for layout, score in matches if score == strongest]
        if len(best) != 1:
            return None, "STRUCTURAL_LAYOUT_AMBIGUOUS"
        return best[0], ""

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
            if layout.name != "reordered-block-45":
                if not self._valid_skills_structure(self._mapped(row, layout, "skills")):
                    return False
                if not self._valid_nested_structure(
                    self._mapped(row, layout, "experience"), "experience"
                ):
                    return False
                if not self._valid_nested_structure(
                    self._mapped(row, layout, "education"), "education"
                ):
                    return False
            else:
                for name in ("skills", "experience", "education"):
                    value = self._mapped(row, layout, name)
                    if is_null(value):
                        continue
                    parsed, valid_literal = literal_value(value)
                    if not valid_literal:
                        continue
                    if name == "skills" and not self._valid_skills_structure(value):
                        return False
                    if name == "experience" and not self._valid_nested_structure(value, name):
                        return False
                    if name == "education" and not self._valid_nested_structure(value, name):
                        return False
            summary = self._mapped(row, layout, "summary")
            if (
                layout.name != "reordered-block-45"
                and not is_null(summary)
                and (not isinstance(summary, str) or is_structured_text(summary))
            ):
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

    @classmethod
    def _has_nonempty_literal_list(cls, value) -> bool:
        parsed = cls._literal_list(value)
        return parsed is not None and bool(parsed)

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
        unmapped = {
            str(source_position): row[source_position]
            for source_position in layout.unmapped_source_positions
            if row[source_position]
        }
        if unmapped:
            payload["_unmapped_source_values"] = unmapped
        payload["_source_layout"] = layout.name
        return payload

    def _validate_row(
        self, row, layout, raw_payload, stats, logical_record, physical_start, physical_end
    ) -> ValidatedRow | None:
        source = {
            name: row[source_position]
            for name, source_position in zip(
                EXPECTED_HEADER, layout.canonical_to_source, strict=False
            )
            if source_position is not None
        }
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

        for source_name, model_name, max_length in (
            ("full_name", "full_name", 500),
            ("first_name", "first_name", 150),
            ("last_name", "last_name", 150),
            ("job_title", "headline", 500),
            ("location_name", "location", 255),
            ("summary", "summary", None),
        ):
            fields[model_name] = self._semantic_scalar_field(
                source[source_name], source_name, max_length, stats
            )
        if not any(
            fields[name].state == "value" and fields[name].value
            for name in ("full_name", "first_name", "last_name")
        ):
            stats.display_name_invalid_records += 1
            return None
        self._sanitize_metadata(raw_payload, stats)
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
    def _looks_like_date(value: str) -> bool:
        _, valid = source_date(value, end=False)
        return valid

    @staticmethod
    def _looks_like_salary_range(value: str) -> bool:
        parts = re.split(r"\s+-\s+", value)
        if len(parts) != 2 or not all(re.search(r"\d", part) for part in parts):
            return False
        return bool(re.search(r"[$€£]|\b(?:usd|eur|gbp|k|m)\b", value, re.IGNORECASE))

    @classmethod
    def _semantic_boundary_violation(cls, field_name: str, value: str) -> bool:
        if is_structured_text(value):
            return True
        if field_name in {"job_title", "industry", "location_country", "job_company_name"}:
            if COMPANY_SIZE_RE.fullmatch(value) or cls._looks_like_date(value):
                return True
            if cls._looks_like_salary_range(value):
                return True
        return field_name == "job_company_name" and bool(NUMBER_RE.fullmatch(value))

    def _sanitize_metadata(self, raw_payload, stats) -> None:
        invalid_values = {}
        for field_name in ("industry", "job_company_name", "location_country"):
            value = raw_payload.get(field_name)
            if not isinstance(value, str) or is_null(value):
                continue
            if self._semantic_boundary_violation(field_name, value):
                invalid_values[field_name] = value
                raw_payload[field_name] = ""
                stats.semantic_warnings[f"{field_name}_boundary"] += 1
        if invalid_values:
            raw_payload["_invalid_source_values"] = invalid_values

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
            if len(company) > 255:
                stats.oversized_fields["experience.company"] += 1
                return None
            values["company"] = company
            location = self._list_field(
                item.get("location_names"), ", ", 255, "experience.location_names", stats
            )
            self._put_nested_field(values, invalid_fields, "location_names", "location", location)
            summary = self._scalar_nested_field(item.get("summary"), "experience.summary", stats)
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
            for name, field_value in plan.fields.items():
                if field_value.state == "invalid":
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
            "skills_created",
            "skills_reused",
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
