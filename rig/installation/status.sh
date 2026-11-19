#!/bin/sh
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
PYTHONPATH="$root" exec python3 -P -m tools.installation rig status "$@"
