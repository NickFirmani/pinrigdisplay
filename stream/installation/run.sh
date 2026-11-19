#!/bin/sh
set -eu

root=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
venv=${PINRIG_VENV:-"$root/.venv"}
python=${PINRIG_PYTHON:-"$venv/bin/python"}
config=${1:-"$HOME/stream-config.json"}
state="${XDG_STATE_HOME:-"$HOME/.local/state"}/pinrig-stream"
if [ "$#" -gt 0 ]; then
    shift
fi

if [ ! -x "$python" ]; then
    printf 'Python environment not found at %s. Run ./install.sh first.\n' "$python" >&2
    exit 1
fi

if [ ! -f "$config" ]; then
    mkdir -p "$(dirname -- "$config")"
    printf 'No stream config at %s. Let’s configure OBS and the rig(s).\n' "$config"
    PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}" "$python" -c \
        'from pathlib import Path; from tools.configure_installation import generate_config; import sys; generate_config("stream", Path(sys.argv[1]))' \
        "$config"
fi

exec env PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}" "$python" -m stream.overview \
    --config "$config" --bind 127.0.0.1 --state "$state" --releases "$state/releases" "$@"
