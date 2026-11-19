#!/bin/sh
set -eu

role=$1
shift
usage() {
    printf 'Usage: %s/installation/build.sh RELEASE [OUTPUT_DIRECTORY]\n' "$role"
}

if [ "${1-}" = --help ]; then
    usage
    exit 0
fi
if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    usage >&2
    exit 2
fi
if [ "$(uname -s)" != Linux ]; then
    printf 'Build on a Linux host that matches the target.\n' >&2
    exit 1
fi

root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
release=$1
output=${2:-"$HOME/$role-$release"}
if [ ! -x "$root/.venv/bin/python" ]; then
    python3 -m venv "$root/.venv"
fi
PYTHONPATH="$root" "$root/.venv/bin/python" -P -m tools.build_software_release \
    --role "$role" --release "$release" --output "$output"
printf 'Bundle ready: %s\n' "$output"
