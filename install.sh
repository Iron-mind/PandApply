#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if command -v python3 >/dev/null 2>&1; then
    exec python3 "$SCRIPT_DIR/install.py" "$@"
fi
printf '%s\n' 'Necesitas Python 3.11 o posterior (con soporte venv).'
exit 1
