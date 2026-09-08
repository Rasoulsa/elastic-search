#!/usr/bin/env bash

set -euo pipefail

release_tag="${1-}"
api_base_url="${2-}"

if [[ ! "$release_tag" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
    echo "Invalid release tag: expected vMAJOR.MINOR.PATCH without leading zeros or suffixes." >&2
    exit 1
fi
major="${BASH_REMATCH[1]}"
minor="${BASH_REMATCH[2]}"
patch="${BASH_REMATCH[3]}"

if [[ -z "${api_base_url//[[:space:]]/}" ]]; then
    echo "VITE_API_BASE_URL repository variable must be non-empty." >&2
    exit 1
fi

API_BASE_URL="$api_base_url" python3 - <<'PY'
import os
import sys
from urllib.parse import urlsplit

value = os.environ["API_BASE_URL"]
try:
    parsed = urlsplit(value)
    parsed.port
except ValueError:
    print("VITE_API_BASE_URL must be an absolute HTTP(S) URL without credentials or a fragment.", file=sys.stderr)
    raise SystemExit(1)

if (
    any(character.isspace() for character in value)
    or parsed.scheme not in {"http", "https"}
    or not parsed.netloc
    or not parsed.hostname
    or parsed.username is not None
    or parsed.password is not None
    or parsed.fragment
    or parsed.netloc.endswith(":")
):
    print("VITE_API_BASE_URL must be an absolute HTTP(S) URL without credentials or a fragment.", file=sys.stderr)
    raise SystemExit(1)
PY

version="${major}.${minor}.${patch}"
major_minor="${major}.${minor}"

write_output() {
    local name="$1"
    local value="$2"

    if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
        printf '%s=%s\n' "$name" "$value" >> "$GITHUB_OUTPUT"
    fi
}

write_output version "$version"
write_output major_minor "$major_minor"
write_output api_base_url "$api_base_url"

printf 'version=%s\n' "$version"
printf 'major_minor=%s\n' "$major_minor"
printf 'api_base_url=%s\n' "$api_base_url"
