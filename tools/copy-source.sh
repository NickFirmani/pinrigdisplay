#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s USER@HOST [NEW_DIRECTORY]\n' "${0##*/}"
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
    COPYFILE_DISABLE=1 tar -czf "$archive" --null -T -

# Remove an incomplete extraction so the same new directory can be used on retry.
ssh -- "$1" "set -e
cd \"\$HOME\"
mkdir -- '$destination'
trap 'rm -rf -- $destination' 0
tar -xzf - -C '$destination'
trap - 0" < "$archive"
