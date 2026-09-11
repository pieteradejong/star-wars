# CLAUDE.md

Guidance for AI coding assistants working in this repository. Symlinked as `AGENTS.md`.

## Overview

A provenance-tracked inventory of the Star Wars extended universe: 11,597
published works with a plot summary each, derived in two passes over the
Wookieepedia XML dump. The repository holds the code that builds the corpus,
never the corpus itself — the upstream text is CC BY-SA, and `data/raw/` and
`data/derived/` are gitignored and rebuilt by `make data`. Its sister project is
`../star-trek`, which emits the same schema from STAPI.

## Commands

```sh
make data        # fetch (~275 MB) then build inventory + plots + invariants
make fetch       # download only, into the gitignored data/raw/
make inventory   # one dump pass -> data/derived/inventory.jsonl
make plots       # a second dump pass -> data/derived/plots.jsonl
make invariants  # assert the figures the README quotes
make dialogue    # COPYRIGHTED film scripts, local-only -- not part of `make data`
make clean       # remove data/derived/. KEEPS data/raw/, so no re-download.

./test.sh              # the full gate: lint, unit, boundary, data, manifest, docs
./test.sh --fast       # skip the sections that read the 275 MB dump
./test.sh boundary     # one section by name
make lint / make format
```

Requires `7z` (`brew install p7zip`). No runtime Python dependencies by design —
the fetchers and parsers are standard library only.

## Architecture

```
scripts/fetch.py            shared fetch layer: robots, throttle, manifest
scripts/fetch_sources.py    the declarative SOURCES; writes data/MANIFEST.csv
scripts/fetch_dialogue.py   separate on purpose; copyrighted, local-only
scripts/dump.py             streams pages out of the .7z, never extracts it
scripts/wikitext.py         infobox parsing, markup flattening, section finding
scripts/build_inventory.py  dump -> inventory.jsonl
scripts/build_plots.py      dump -> plots.jsonl, keyed by inventory page titles
data/curated/sources.yaml   hand-authored source register (committed, CC BY 4.0)
data/MANIFEST.csv           tracked record of every fetch: sha256, licence, date
```

The data boundary is the organising constraint. `data/raw/` and `data/derived/`
are gitignored; `data/curated/` and `data/MANIFEST.csv` are tracked. CI fails
the build if anything under the first two is ever committed, and
`tests/test_boundary.py` asserts the same locally.

## Gotchas

- **`{{Film}}` is not the film infobox.** It appears 20,073 times and is a
  citation template; `{{Movie}}` appears 91 times and is the infobox. Before
  adding a work type to `BOXES`, count it across the dump rather than guessing
  from the name.
- **Continuity is not in the `{{Top}}` era flags.** Those are the in-universe
  setting — `Heir to the Empire` carries `rwm|new` (New Republic era) despite
  being Legends. The canon/Legends split is in the categories. Where they are
  silent, the 2014 reboot date gives an inference, which goes in
  `continuity_guess` with `continuity_basis` recording how it was reached.
  **Inference never overwrites `continuity`.** Keep it that way.
- **`wikitext.year_of()` searches raw markup, not flattened text**, because
  `flatten()` strips templates and dates are sometimes inside one. It strips
  `<ref>` first so a citation's year cannot win.
- **Never extract the dump.** `dump.stream()` pipes `7z x -so` into `iterparse`
  and detaches each element from the root; clearing alone is not enough.
  `tests/check_dump.py` fails the build if peak RSS stops being flat.
- **mypy cannot run on this machine** — its shebang points at a removed Python
  3.11. `test.sh` reports it as a skip naming the cause. CI is the only thing
  that actually type-checks, so expect type errors to surface there.
- **The CI workflow's shell is `bash -e`.** A trailing `&&` chain inside a
  command substitution ends false and fails the step with no message. Use `if`.
