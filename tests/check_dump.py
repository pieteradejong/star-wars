#!/usr/bin/env python3
"""Assert the dump reader streams: bounded memory, no multi-GB temp file.

The whole reason scripts/dump.py pipes `7z x -so` into iterparse is that the
262 MB archive expands to several GB of XML. If a future change ever buffers
the archive, extracts it to a temp file, or forgets to clear the iterparse
root, this is what notices -- and it notices in seconds, on the first 30,000
pages, rather than after the machine fills its disk.
"""

from __future__ import annotations

import resource
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import dump  # noqa: E402

ARCHIVE = ROOT / "data" / "raw" / "wookieepedia.xml.7z"
PAGES = 30_000
# Generous: the observed figure is ~26 MB. This catches "the tree is growing",
# not a few MB of ordinary variation.
MAX_RSS_MB = 250


def main() -> int:
    if not ARCHIVE.exists():
        print(f"skip: {ARCHIVE.name} absent")
        return 0
    dump.check_7z()
    before = disk_used(ROOT / "data" / "raw")
    started = time.monotonic()
    seen = titles = 0
    for page in dump.stream(ARCHIVE, namespaces={0}, skip_redirects=True):
        seen += 1
        titles += bool(page.title)
        if seen >= PAGES:
            break
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
    after = disk_used(ROOT / "data" / "raw")
    elapsed = time.monotonic() - started

    print(f"  {seen:,} pages in {elapsed:.1f}s, peak RSS {rss:.0f} MB")
    ok = True
    if seen < PAGES:
        print(f"  FAIL only {seen} pages read, expected {PAGES}", file=sys.stderr)
        ok = False
    if titles != seen:
        print(f"  FAIL {seen - titles} pages had no title", file=sys.stderr)
        ok = False
    if rss > MAX_RSS_MB:
        print(
            f"  FAIL peak RSS {rss:.0f} MB > {MAX_RSS_MB} MB -- the parser is "
            f"accumulating instead of streaming",
            file=sys.stderr,
        )
        ok = False
    if after > before + 50_000_000:
        print(
            f"  FAIL data/raw/ grew by {(after - before) / 1e6:.0f} MB -- "
            f"something extracted the archive to disk",
            file=sys.stderr,
        )
        ok = False
    return 0 if ok else 1


def disk_used(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


if __name__ == "__main__":
    sys.exit(main())
