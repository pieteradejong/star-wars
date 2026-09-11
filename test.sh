#!/usr/bin/env bash
#
# The gate. Everything that can be checked without the network, plus the
# checks that need the fetched sources when they happen to be present.
#
# Design rules, both deliberate:
#
#   * Checks that need data SKIP, they do not FAIL, when data/raw/ or
#     data/derived/ is absent. Those directories are gitignored and multiple
#     gigabytes; a fresh clone and CI will never have them, and a suite that
#     fails there is a suite nobody runs.
#   * Every section runs even if an earlier one failed, so one invocation
#     reports every problem rather than only the first. The exit code is the
#     OR of all of them.
#
# Usage:
#   ./test.sh              everything available
#   ./test.sh --fast       skip the sections that read the 262 MB dump
#   ./test.sh lint         one section by name (lint|unit|boundary|data|manifest|docs)
set -uo pipefail

cd "$(dirname "$0")" || exit 2
PY=${PY:-python3}

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
[ -t 1 ] || { RED=""; GREEN=""; YELLOW=""; DIM=""; OFF=""; }

FAILED=0; PASSED=0; SKIPPED=0
FAILURES=()

section() { printf '\n%s== %s ==%s\n' "$DIM" "$1" "$OFF"; }
pass()    { PASSED=$((PASSED+1)); printf '  %sok%s   %s\n' "$GREEN" "$OFF" "$1"; }
skip()    { SKIPPED=$((SKIPPED+1)); printf '  %sskip%s %s %s(%s)%s\n' "$YELLOW" "$OFF" "$1" "$DIM" "$2" "$OFF"; }
fail()    { FAILED=$((FAILED+1)); FAILURES+=("$1"); printf '  %sFAIL%s %s\n' "$RED" "$OFF" "$1"; }

# run <name> <command...> -- fails the suite if the command exits non-zero.
run() {
  local name="$1"; shift
  local out
  if out=$("$@" 2>&1); then
    pass "$name"
  else
    fail "$name"
    printf '%s\n' "$out" | sed 's/^/       /' | tail -25
  fi
}

# run_if <name> <path> <command...> -- skips when <path> is absent.
run_if() {
  local name="$1" path="$2"; shift 2
  if [ ! -e "$path" ]; then skip "$name" "$path absent"; return; fi
  run "$name" "$@"
}

# Installed is not the same as working: a tool whose shebang points at a
# Python that has since been removed is on PATH and fails on every invocation.
# That is an environment problem, not a code problem, and reporting it as a
# test failure buries the real signal -- so it is a skip that names the cause.
have() { command -v "$1" >/dev/null 2>&1; }
usable() {
  command -v "$1" >/dev/null 2>&1 || return 1
  "$1" --version >/dev/null 2>&1
}
tool() {
  local name="$1"; shift
  if ! have "$name"; then skip "$name" "not installed"; return; fi
  if ! usable "$name"; then skip "$name" "installed but not runnable -- broken install"; return; fi
  run "$@"
}

FAST=0
WANT="all"
for arg in "$@"; do
  case "$arg" in
    --fast) FAST=1 ;;
    lint|unit|boundary|data|manifest|docs) WANT="$arg" ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done
want() { [ "$WANT" = "all" ] || [ "$WANT" = "$1" ]; }

# --------------------------------------------------------------- lint
if want lint; then
  section "lint and types"
  tool ruff      "ruff"         ruff check scripts tests
  tool black     "black --check" black --check --quiet scripts tests
  tool mypy      "mypy"         mypy --ignore-missing-imports scripts
  # Every script must at least import cleanly; a syntax error in a builder
  # that only runs after a 4-minute dump pass is an expensive way to find out.
  for f in scripts/*.py; do
    run "compile $(basename "$f")" "$PY" -m py_compile "$f"
  done
  run "test.sh is executable" test -x test.sh
  tool shellcheck "shellcheck" shellcheck test.sh
fi

# --------------------------------------------------------------- unit
if want unit; then
  section "unit tests (offline, no data required)"
  run "wikitext parser" "$PY" -m unittest tests.test_wikitext -v
  run "fetch layer" "$PY" -m unittest tests.test_fetch -v
fi

# --------------------------------------------------------------- boundary
if want boundary; then
  section "data boundary and repo baseline"
  run "boundary + required files" "$PY" -m unittest tests.test_boundary -v
  # Belt and braces: assert it directly here too, so a broken test module
  # cannot silently take the guard with it.
  if [ -d .git ]; then
    leaked=$(git ls-files | grep -E '^data/(raw|derived)/' || true)
    if [ -z "$leaked" ]; then pass "no fetched data tracked by git"
    else fail "fetched data tracked by git: $leaked"; fi
    # `if`, not a trailing `&&` chain: the chain ends false whenever the last
    # tracked file is under the limit, which makes the assignment exit 1. This
    # script does not `set -e`, but the CI workflow's shell does, and the same
    # snippet failed there with no message at all.
    big=$(git ls-files | while read -r f; do
            if [ -f "$f" ] && [ "$(wc -c <"$f")" -gt 1000000 ]; then
              echo "$f"
            fi
          done)
    if [ -z "$big" ]; then pass "no tracked file over 1 MB"
    else fail "tracked files over 1 MB: $big"; fi
  else
    skip "git boundary" "not a git repository yet"
  fi
fi

# --------------------------------------------------------------- data
if want data; then
  section "corpus contracts"
  run_if "inventory + plots schema" data/derived/inventory.jsonl \
    "$PY" -m unittest tests.test_schema -v
  if [ "$FAST" = 1 ]; then
    skip "dump stream" "--fast"
  else
    run_if "dump streams and stays small" data/raw/wookieepedia.xml.7z \
      "$PY" tests/check_dump.py
  fi
  run_if "invariants" data/derived/inventory.jsonl "$PY" scripts/check_invariants.py
fi

# --------------------------------------------------------------- manifest
if want manifest; then
  section "provenance"
  run_if "manifest matches the cache" data/MANIFEST.csv \
    "$PY" -m unittest tests.test_manifest -v
fi

# --------------------------------------------------------------- docs
if want docs; then
  section "documentation"
  run "README claims match the tree" "$PY" tests/check_docs.py
fi

# --------------------------------------------------------------- summary
printf '\n%s%d passed%s, %s%d failed%s, %s%d skipped%s\n' \
  "$GREEN" "$PASSED" "$OFF" "$RED" "$FAILED" "$OFF" "$YELLOW" "$SKIPPED" "$OFF"
if [ "$FAILED" -gt 0 ]; then
  printf '\nfailed:\n'
  printf '  - %s\n' "${FAILURES[@]}"
  exit 1
fi
exit 0
