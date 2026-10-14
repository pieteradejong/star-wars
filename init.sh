#!/usr/bin/env bash
# init.sh — everything needed to work on the Star Wars corpus. Idempotent; exit 0 = ready.
# The corpus builders are standard-library Python, so the venv holds only the dev tools
# (ruff, black, mypy) that `make lint` and `./test.sh` use.
#
#   ./init.sh            create .venv/ if missing, install the dev tools, check 7z
#   ./init.sh --clean    remove .venv/ first and rebuild it
#   ./init.sh --help     this message
set -euo pipefail
cd "$(dirname "$0")"

case "${1:-}" in
    -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --clean) rm -rf .venv ;;
    '') ;;
    *) echo "unknown option: $1 (see ./init.sh --help)" >&2; exit 2 ;;
esac

VENV=.venv
PY=${PY:-python3}

command -v "$PY" >/dev/null 2>&1 || { echo "python3 not found" >&2; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || { echo "python >= 3.11 required, found $("$PY" --version)" >&2; exit 1; }
echo "== $("$PY" --version)"

if [ -x "$VENV/bin/python" ]; then
    echo "== reusing $VENV/"
else
    echo "== creating $VENV/"
    "$PY" -m venv "$VENV"
fi
# Dev tools only: pyproject's [project.optional-dependencies].dev, same set CI installs.
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check ruff black mypy

if command -v 7z >/dev/null 2>&1; then
    echo "== 7z found (needed by make fetch / make plots)"
else
    echo "== 7z not found: install with brew install p7zip before make data" >&2
fi

echo "ready."
echo "  ./test.sh --fast     the gate without the dump-reading sections"
echo "  ./run.sh help        make targets (data, fetch, inventory, plots, lint, format)"
