#!/usr/bin/env python3
"""Assert the headline figures the README quotes.

The point is not to test the code -- the unit tests do that -- but to notice
when the UPSTREAM changes shape. A dump that silently halves, an infobox
renamed on the wiki, a parser that stops matching: each of those produces a
smaller corpus that looks perfectly valid. Without a floor to check it against,
the site just quietly gets thinner.

So every number here is one the README states, and a build that cannot meet
them should fail rather than ship.

Run by `make invariants`, by ./test.sh, and in CI when a corpus is present.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "data" / "derived" / "inventory.jsonl"
PLOTS = ROOT / "data" / "derived" / "plots.jsonl"

# Measured against the 2026-08-01 Wookieepedia dump (228,668 articles).
# Floors, not equalities: the wiki grows.
EXPECTED = {
    "works": 11_000,
    "novels": 1_000,
    "comics": 2_500,
    "short_stories": 800,
    "video_games": 350,
    "reference": 800,
    "films": 80,
    "with_summary": 10_000,
    "with_author": 7_500,
    "with_year": 9_500,
    "distinct_authors": 1_500,
}


def main() -> int:
    if not INVENTORY.exists():
        print("no corpus built; nothing to check " "(run `make data`)", file=sys.stderr)
        return 0

    with INVENTORY.open() as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    kinds = collections.Counter(r["kind"] for r in rows)

    actual = {
        "works": len(rows),
        "novels": kinds["novel"],
        "comics": kinds["comic"] + kinds["comic_story"] + kinds["comic_series"],
        "short_stories": kinds["short_story"],
        "video_games": kinds["video_game"],
        "reference": kinds["reference"],
        "films": kinds["film"],
        "with_author": sum(1 for r in rows if r["authors"]),
        "with_year": sum(1 for r in rows if r["published"]),
        "distinct_authors": len({a for r in rows for a in r["authors"]}),
    }

    if PLOTS.exists():
        with PLOTS.open() as fh:
            plots = [json.loads(line) for line in fh if line.strip()]
        actual["with_summary"] = sum(1 for p in plots if p["summary"])
        if len(plots) != len(rows):
            print(
                f"!! plots has {len(plots)} rows, inventory has {len(rows)}; "
                f"they must match",
                file=sys.stderr,
            )
            return 1

    failures = []
    for name, floor in EXPECTED.items():
        if name not in actual:
            continue
        got = actual[name]
        ok = got >= floor
        print(f"  {'ok  ' if ok else 'FAIL'}  {name:18s} {got:7,d}  (>= {floor:,})")
        if not ok:
            failures.append(f"{name}: {got:,} < {floor:,}")

    if failures:
        print(
            "\nThe corpus is thinner than the README claims. Either the "
            "upstream changed shape or a parser stopped matching:",
            file=sys.stderr,
        )
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    checked = sum(1 for n in EXPECTED if n in actual)
    print(f"\nall {checked} invariants hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
