import ast
import re
import unicodedata

NULL_TEXT_VALUES = {"", "null", "none", "nan", "n/a", "na"}

DATE_TEXT_RE = re.compile(r"\A\d{4}(?:-\d{2}(?:-\d{2})?)?\Z")
NUMBER_TEXT_RE = re.compile(r"\A[+-]?(?:\d+(?:\.\d*)?|\.\d+)\Z")
NUMERIC_RANGE_RE = re.compile(
    r"\A\s*[$€£]?\s*\d[\d,]*(?:\.\d+)?(?:\s*[kKmM])?\s*(?:-|–|—|to)\s*"
    r"[$€£]?\s*\d[\d,]*(?:\.\d+)?(?:\s*[kKmM])?\s*\Z",
    re.IGNORECASE,
)
PHONE_TEXT_RE = re.compile(r"\A\+?[\d() .-]{7,}\Z")

SCALAR_BOUNDARY_FIELDS = {
    "industry",
    "location_country",
    "job_company_name",
    "job_company_location_name",
    "location_name",
    "job_title",
}


def normalize_scalar(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    return "" if normalized.casefold() in NULL_TEXT_VALUES else normalized


def is_serialized_collection(value: object) -> bool:
    if not isinstance(value, str) or not value.lstrip().startswith(("[", "{", "(")):
        return False
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError, TypeError, MemoryError):
        return True
    return isinstance(parsed, (list, dict, tuple, set))


def scalar_anomaly(field_name: str, value: object) -> str | None:
    normalized = normalize_scalar(value)
    if not normalized:
        return None
    if is_serialized_collection(normalized):
        return "serialized_collection"
    if field_name not in {*SCALAR_BOUNDARY_FIELDS, "summary"}:
        return None
    if DATE_TEXT_RE.fullmatch(normalized):
        return "date"
    if NUMERIC_RANGE_RE.fullmatch(normalized):
        return "numeric_range"
    if NUMBER_TEXT_RE.fullmatch(normalized):
        return "numeric"
    if field_name == "summary":
        return None
    if PHONE_TEXT_RE.fullmatch(normalized) and any(
        character in normalized for character in "+() .-"
    ):
        return "phone"
    return None


def validated_scalar(field_name: str, value: object) -> str:
    normalized = normalize_scalar(value)
    return "" if scalar_anomaly(field_name, normalized) else normalized
