#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s USER@HOST [DIRECTORY]\n' "${0##*/}"
}

if [[ ${1-} == --help ]]; then
    usage
    exit 0
fi
if [[ $# -lt 1 || $# -gt 2 ]]; then
    usage >&2
    exit 2
fi

destination=${2-pinrig}
if [[ ! "$destination" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    printf 'Choose a directory name relative to the remote home directory.\n' >&2
    exit 2
fi

root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
archive=$(mktemp)
trap 'rm -f -- "$archive"' EXIT
cd "$root"
git ls-files -z --cached --others --exclude-standard -- README.md pyproject.toml shared rig stream tools |
    while IFS= read -r -d '' path; do
        if [[ -e "$path" || -L "$path" ]]; then
            printf '%s\0' "$path"
        fi
    done |
    COPYFILE_DISABLE=1 tar -czf "$archive" --null -T -

ssh -- "$1" "set -e
cd \"\$HOME\"
stage=\$(mktemp -d .pinrig-source.XXXXXXXX)
trap 'rm -rf -- \"\$stage\"' 0
tar -xzf - -C \"\$stage\"
python3 \"\$stage/tools/update_source.py\" \"\$stage\" \"\$(pwd -P)/$destination\"" < "$archive"
