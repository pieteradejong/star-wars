.PHONY: help all data fetch inventory plots dialogue refresh check invariants test lint format clean

PY ?= python3

## help: list the targets
help:
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/## /  /'

all: data

## data: fetch every source and rebuild the corpus
data: fetch inventory plots invariants

## fetch: download the dump and the APIs into data/raw/ (gitignored, ~275 MB)
fetch:
	$(PY) scripts/fetch_sources.py

## refresh: re-download even if cached, then rebuild
refresh:
	$(PY) scripts/fetch_sources.py --force
	$(MAKE) inventory plots invariants

## inventory: derive data/derived/inventory.jsonl from the dump
inventory:
	$(PY) scripts/build_inventory.py

## plots: derive data/derived/plots.jsonl from the dump
plots:
	$(PY) scripts/build_plots.py

## dialogue: cache film scripts locally. COPYRIGHTED -- never committed, never published.
dialogue:
	$(PY) scripts/fetch_dialogue.py

## check: rebuild from the cache without re-downloading anything
check: inventory plots invariants

## invariants: assert the figures the README quotes
invariants:
	$(PY) scripts/check_invariants.py

## test: the full gate -- lint, unit tests, boundary, contracts, provenance
test:
	./test.sh

## lint: ruff + black + mypy
lint:
	ruff check scripts tests
	black --check scripts tests
	mypy --ignore-missing-imports scripts

## format: apply black and ruff --fix
format:
	black scripts tests
	ruff check --fix scripts tests

## clean: remove the derived corpus. KEEPS data/raw/, so no re-download.
clean:
	rm -rf data/derived
