#!/usr/bin/env python3
"""Extract plot summaries for every work in the inventory.

A second pass over the dump, keyed by the page titles build_inventory.py kept.
Wookieepedia puts the story under a handful of different headings depending on
what kind of work it is, and some articles have none at all -- a stub, or a
comic issue whose plot lives on its story arc's page. A work with no summary is
recorded with `summary: null` rather than dropped, so the inventory and the
plots stay the same length and a gap is visible as a gap.

Output is data/derived/plots.jsonl.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import dump
import wikitext as wt

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "data" / "raw" / "wookieepedia.xml.7z"
INVENTORY = ROOT / "data" / "derived" / "inventory.jsonl"
OUT = ROOT / "data" / "derived" / "plots.jsonl"

# In rough order of preference: the real plot first, then the marketing copy,
# then the lead paragraph as a last resort.
PLOT_HEADINGS = [
    {"plot summary", "plot", "synopsis", "story", "story summary", "summary"},
    {
        "publisher's summary",
        "publisher summary",
        "back cover summary",
        "from the publisher",
        "official description",
        "description",
    },
    {"gameplay", "premise", "overview"},
]

MIN_CHARS = 40  # shorter than this is a heading artefact, not a summary


def main(argv: list[str]) -> int:
    dump.check_7z()
    if not INVENTORY.exists():
        raise SystemExit(
            "data/derived/inventory.jsonl is missing -- "
            "run scripts/build_inventory.py first"
        )
    wanted = {}
    with INVENTORY.open() as fh:
        for line in fh:
            record = json.loads(line)
            wanted[record["page_title"]] = record
    print(f"looking for plot summaries for {len(wanted)} works")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    found = 0
    seen: set[str] = set()
    with OUT.open("w") as out:
        for page in dump.stream(ARCHIVE, namespaces={0}, skip_redirects=True):
            record = wanted.get(page.title)
            if record is None:
                continue
            seen.add(page.title)
            summary = source = None
            for i, headings in enumerate(PLOT_HEADINGS):
                body = wt.section(page.text, headings)
                if body and len(body) >= MIN_CHARS:
                    summary = body
                    source = ("plot", "publisher", "overview")[i]
                    break
            if summary is None:
                body = wt.lead(page.text)
                if body and len(body) >= MIN_CHARS:
                    summary, source = body, "lead"
            if summary:
                found += 1
            out.write(
                json.dumps(
                    {
                        "id": record["id"],
                        "title": record["title"],
                        "kind": record["kind"],
                        "summary": summary,
                        "summary_source": source,
                        "words": len(summary.split()) if summary else 0,
                        "source_url": record["source_url"],
                        "summary_licence": "CC-BY-SA-3.0",
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            if len(seen) % 500 == 0:
                print(
                    f"\r  {len(seen)}/{len(wanted)} pages, {found} with a summary",
                    end="",
                    flush=True,
                )

    missing = set(wanted) - seen
    print(f"\r{OUT.relative_to(ROOT)}: {len(seen)} works, {found} with a summary")
    if missing:
        # Should be empty: every title came from a pass over this same dump.
        print(
            f"  !! {len(missing)} inventory pages were not found in the dump",
            file=sys.stderr,
        )
        for title in sorted(missing)[:5]:
            print(f"     {title}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
