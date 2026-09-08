#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
validator="$repository_root/scripts/validate-release-inputs.sh"
release_workflow="$repository_root/.github/workflows/release.yml"
ci_workflow="$repository_root/.github/workflows/ci.yml"
test_tmpdir="$(mktemp -d)"
trap 'rm -rf "$test_tmpdir"' EXIT

fail() {
    echo "FAIL: $1" >&2
    exit 1
}

assert_valid_release() {
    local tag="$1"
    local api_url="$2"
    local output
    local github_output="$test_tmpdir/github-output"

    : > "$github_output"
    output="$(GITHUB_OUTPUT="$github_output" "$validator" "$tag" "$api_url")" \
        || fail "expected valid release input: $tag / $api_url"
    grep -Fxq "version=1.2.3" <<<"$output" || fail "normalized version missing for $tag"
    grep -Fxq "major_minor=1.2" <<<"$output" || fail "major_minor output missing for $tag"
    grep -Fxq "api_base_url=$api_url" <<<"$output" || fail "API URL output missing for $tag"
    grep -Fxq "version=1.2.3" "$github_output" || fail "GITHUB_OUTPUT version missing"
    grep -Fxq "major_minor=1.2" "$github_output" || fail "GITHUB_OUTPUT major_minor missing"
    grep -Fxq "api_base_url=$api_url" "$github_output" || fail "GITHUB_OUTPUT API URL missing"
}

assert_invalid_release() {
    if "$validator" "$1" "$2" >/dev/null 2>&1; then
        fail "expected invalid release input: $1 / $2"
    fi
}

assert_valid_release v1.2.3 https://profiles.example.com
assert_valid_release v1.2.3 'http://profiles.example.com:8080/api?check=1'
assert_invalid_release "" https://profiles.example.com
assert_invalid_release 1.2.3 https://profiles.example.com
assert_invalid_release v1.2 https://profiles.example.com
assert_invalid_release v1..3 https://profiles.example.com
assert_invalid_release v1.2. https://profiles.example.com
assert_invalid_release v01.2.3 https://profiles.example.com
assert_invalid_release v1.02.3 https://profiles.example.com
assert_invalid_release v1.2.03 https://profiles.example.com
assert_invalid_release v1.2.3-rc.1 https://profiles.example.com
assert_invalid_release v1.2.3+build.1 https://profiles.example.com
assert_invalid_release v1.2.3 ""
assert_invalid_release v1.2.3 '   '
assert_invalid_release v1.2.3 relative/path
assert_invalid_release v1.2.3 ftp://profiles.example.com
assert_invalid_release v1.2.3 'https://[::1'
assert_invalid_release v1.2.3 'https://profiles.example.com/path with spaces'
assert_invalid_release v1.2.3 'https://user:password@profiles.example.com'
assert_invalid_release v1.2.3 'https://profiles.example.com/#fragment'

if output="$(cd "$repository_root" && make -s import 2>&1)"; then
    fail "missing DATASET_PATH was accepted"
fi
grep -Fq "Usage: make import DATASET_PATH=/data/profiles.txt" <<<"$output" \
    || fail "missing DATASET_PATH did not print usage"
! grep -Fq "docker compose" <<<"$output" \
    || fail "missing DATASET_PATH attempted Docker"

if output="$(cd "$repository_root" && make -s import DATASET_PATH='   ' 2>&1)"; then
    fail "whitespace-only DATASET_PATH was accepted"
fi
grep -Fq "Usage: make import DATASET_PATH=/data/profiles.txt" <<<"$output" \
    || fail "whitespace-only DATASET_PATH did not print usage"

grep -Fq -- '--path "$${DATASET_PATH}"' "$repository_root/Makefile" \
    || fail "Makefile does not pass DATASET_PATH as one quoted shell argument"
! grep -Fq '$(DATASET_PATH)' "$repository_root/Makefile" \
    || fail "Makefile inserts DATASET_PATH through direct Make expansion"
! rg -n '\beval\b' "$repository_root/Makefile" "$validator" \
    || fail "eval is forbidden in import or release validation"

fake_bin="$test_tmpdir/bin"
capture_file="$test_tmpdir/docker-arguments"
forbidden_file="$test_tmpdir/command-was-executed"
mkdir -p "$fake_bin"
cat > "$fake_bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" > "$CAPTURE_FILE"
EOF
chmod +x "$fake_bin/docker"

assert_import_path() {
    local expected_path="$1"

    rm -f "$capture_file" "$forbidden_file"
    PATH="$fake_bin:$PATH" CAPTURE_FILE="$capture_file" \
        make -s -C "$repository_root" import DATASET_PATH="$expected_path" \
        >/dev/null 2>&1 || fail "import recipe failed for sentinel path"
    [[ ! -e "$forbidden_file" ]] || fail "sentinel path executed a command"
    [[ "$(sed -n '9p' "$capture_file")" == "$expected_path" ]] \
        || fail "DATASET_PATH was not preserved as one argument"
    [[ "$(wc -l < "$capture_file" | tr -d ' ')" == "9" ]] \
        || fail "DATASET_PATH created extra Docker arguments"
}

assert_import_path /data/profiles.txt
assert_import_path '/data/profiles with spaces.txt'
metachar_path='`touch '"$forbidden_file"';$(touch '"$forbidden_file"');"quoted" * -leading'
assert_import_path "$metachar_path"

rm -f "$capture_file" "$forbidden_file"
if PATH="$fake_bin:$PATH" CAPTURE_FILE="$capture_file" \
    make -s -C "$repository_root" import DATASET_PATH='   ' >/dev/null 2>&1; then
    fail "blank DATASET_PATH reached Docker"
fi
[[ ! -e "$capture_file" ]] || fail "blank DATASET_PATH invoked Docker"

first_release_action="$(rg -n '^        uses:' "$release_workflow" | head -n 1)"
[[ "$first_release_action" == *"actions/checkout@"* ]] \
    || fail "release validation job does not begin with the immutable checkout"
! rg -n 'uses:.*@v[0-9]' "$release_workflow" \
    || fail "release workflow contains a mutable action tag"
while IFS= read -r action_line; do
    [[ "$action_line" =~ @[0-9a-f]{40} ]] \
        || fail "action is not pinned to a full SHA: $action_line"
    [[ "$action_line" == *"# v"* ]] \
        || fail "action SHA is missing its verified release comment: $action_line"
done < <(rg '^        uses:' "$release_workflow")
! rg -Fq 'localhost' "$release_workflow" \
    || fail "release workflow defaults or refers to localhost"
! rg -Fq 'ARG VITE_API_BASE_URL=http://localhost:8000' "$repository_root/frontend/Dockerfile" \
    || fail "production frontend Dockerfile defaults to localhost"
grep -Fq '      - "v*"' "$release_workflow" || fail "release trigger is not broad v*"
grep -Fq 'run: scripts/validate-release-inputs.sh "$RELEASE_TAG" "$RELEASE_API_BASE_URL"' "$release_workflow" \
    || fail "release workflow does not call the shared validator"
grep -Fq 'RELEASE_TAG: ${{ github.ref_name }}' "$release_workflow" \
    || fail "release tag is not passed through the environment"
grep -Fq 'RELEASE_API_BASE_URL: ${{ vars.VITE_API_BASE_URL }}' "$release_workflow" \
    || fail "release API URL is not passed through the environment"
! rg -n 'BASH_REMATCH|\^v\(0\|\[1-9\]' "$release_workflow" \
    || fail "release workflow contains duplicate inline SemVer validation"
grep -Fq '    needs: validate' "$release_workflow" \
    || fail "publishing job does not depend on validation"
for output_name in version major_minor api_base_url; do
    grep -Fq "      $output_name: \${{ steps.validate.outputs.$output_name }}" "$release_workflow" \
        || fail "missing validation job output: $output_name"
done
for downstream_output in version major_minor api_base_url; do
    grep -Fq "needs.validate.outputs.$downstream_output" "$release_workflow" \
        || fail "publishing job does not consume $downstream_output from validation"
done
validation_job="$(sed -n '/^  validate:/,/^  publish:/p' "$release_workflow")"
! grep -Fq 'packages: write' <<<"$validation_job" || fail "validation job has package-write permission"
! grep -Fq 'docker/login-action' <<<"$validation_job" || fail "validation job logs into a registry"
! grep -Fq 'docker/metadata-action' <<<"$validation_job" || fail "validation job generates image metadata"
! grep -Fq 'docker/build-push-action' <<<"$validation_job" || fail "validation job builds or pushes images"

grep -Fq 'github.run_id }}-${{ github.run_attempt' "$ci_workflow" \
    || fail "Compose project name is not run-scoped"
grep -Fq 'if: ${{ always() }}' "$ci_workflow" \
    || fail "Compose cleanup is not always-run"
grep -Fq -- '--connect-timeout 5 --max-time 15' "$ci_workflow" \
    || fail "CI HTTP probes are not explicitly bounded"
grep -Fq -- '--tail=200' "$ci_workflow" \
    || fail "Compose failure logs are not bounded"
grep -Fq -- '--timeout 20' "$ci_workflow" \
    || fail "Compose cleanup timeout is not explicit"

echo "Phase 4A focused checks passed."
