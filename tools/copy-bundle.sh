#!/bin/sh
set -eu

usage() {
    printf 'Usage: %s BUILDER_HOST TARGET_HOST {rig|stream} RELEASE\n' "${0##*/}"
}

if [ "${1-}" = --help ]; then
    usage
    exit 0
fi
if [ "$#" -ne 4 ]; then
    usage >&2
    exit 2
fi
case "$3" in
    rig|stream) ;;
    *) usage >&2; exit 2 ;;
esac
case "$4" in
    ''|*[!A-Za-z0-9_.-]*) printf 'Invalid release name.\n' >&2; exit 2 ;;
esac

exec scp -3 -r -- "$1:$3-$4" "$2:"
