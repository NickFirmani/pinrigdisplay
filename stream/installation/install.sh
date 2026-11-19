#!/bin/sh
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
if [ "$(uname -s)" = Darwin ]; then
    printf 'Preparing the local macOS stream environment from this checkout.\n'
    printf 'Release bundles and systemd installation are for Linux hosts.\n'
    exec "$root/stream/install.sh"
fi
PYTHONPATH="$root" exec python3 -P -m tools.installation stream install "$@"
