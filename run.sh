#!/usr/bin/env bash
# run.sh — the project's entry points. The Makefile is the interface; this wraps it so every
# repo answers to the same three scripts. Run ./init.sh once first.
#
#   ./run.sh                 this message plus `make help` (there is no single default action)
#   ./run.sh <target>        exec make <target>: data fetch refresh inventory plots dialogue
#                            check invariants clean lint format
#   ./run.sh test [args]     ./test.sh (the gate); args pass through, e.g. --fast or lint
set -euo pipefail
cd "$(dirname "$0")"

VENV=.venv
# The dev tools live in the venv; make and test.sh find them on PATH.
[ -d "$VENV/bin" ] && export PATH="$PWD/$VENV/bin:$PATH"

cmd="${1:-help}"
[ $# -gt 0 ] && shift
case "$cmd" in
    help|-h|--help)
        sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
        echo
        make help
        ;;
    test) exec ./test.sh "$@" ;;
    data|fetch|refresh|inventory|plots|dialogue|check|invariants|clean|lint|format)
        exec make "$cmd" "$@" ;;
    *)
        echo "unknown command: $cmd" >&2
        sed -n '5,7p' "$0" | sed 's/^# \{0,1\}//' >&2
        exit 2 ;;
esac
