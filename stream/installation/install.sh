#!/bin/sh
set -eu

root=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
case "${1:-}" in
    --local)
        shift
        if [ "${1:-}" = '--help' ] || [ "${1:-}" = '-h' ]; then
            printf 'Install the local Stream environment using PINRIG_PYTHON and PINRIG_VENV.\n'
            exit 0
        fi
        if [ "$#" -ne 0 ]; then
            printf 'Usage: %s --local\n' "$0" >&2
            exit 2
        fi
        ;;
    -h|--help)
        PYTHONPATH="$root" exec python3 -P -m tools.installation stream install "$@"
        ;;
    *)
        if [ "$(uname -s)" != Darwin ]; then
            PYTHONPATH="$root" exec python3 -P -m tools.installation stream install "$@"
        fi
        printf 'Preparing the local macOS stream environment from this checkout.\n'
        printf 'Release bundles and systemd installation are for Linux hosts.\n'
        ;;
esac

python=${PINRIG_PYTHON:-python3}
venv=${PINRIG_VENV:-"$root/.venv"}
if [ ! -x "$venv/bin/python" ]; then
    "$python" -m venv "$venv"
fi

version=$("$venv/bin/python" -c 'import sys; print(sys.version_info >= (3, 11))')
if [ "$version" != True ]; then
    printf 'PinRig stream requires Python 3.11 or newer.\n' >&2
    exit 1
fi

if ! "$venv/bin/python" -c 'import websocket' >/dev/null 2>&1; then
    "$venv/bin/python" -m pip install 'websocket-client>=1.6,<2'
fi

PYTHONPATH="$root" "$venv/bin/python" -c 'import stream.overview, shared.http'
printf 'Stream software installed in %s\n' "$venv"
printf 'Next: cd %s && ./run.sh\n' "$root/stream"
