#!/bin/sh
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
exec "$root/tools/build-linux-bundle.sh" rig "$@"
