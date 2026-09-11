#!/usr/bin/env python3
"""The README must describe the tree that exists.

A doc claiming a path or a command that is not there is exactly the mismatch
that hides a missing file, and it is the cheapest class of bug to catch. This
checks three things: every repo-relative path the README names exists, every
`make` target it mentions is in the Makefile, and the licensing section still
says what the LICENSE files say.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
MAKEFILE = ROOT / "Makefile"

# `path/like/this` or `path/like/this.py` in backticks, repo-relative.
PATH_RE = re.compile(r"`((?:scripts|tests|data|\.github)/[A-Za-z0-9_./-]+)`")
MAKE_RE = re.compile(r"`make ([a-z-]+)`")
# Directories that are gitignored: named in the README on purpose, absent on a
# fresh clone, and not a documentation error.
GITIGNORED = ("data/raw", "data/derived")


def main() -> int:
    if not README.exists():
        print("README.md is missing", file=sys.stderr)
        return 1
    text = README.read_text()
    problems = []

    for path in sorted(set(PATH_RE.findall(text))):
        if path.startswith(GITIGNORED):
            continue
        if not (ROOT / path).exists():
            problems.append(f"README names `{path}`, which does not exist")

    if MAKEFILE.exists():
        targets = set(re.findall(r"^([a-z][a-z-]*):", MAKEFILE.read_text(), re.M))
        for target in sorted(set(MAKE_RE.findall(text))):
            if target not in targets:
                problems.append(
                    f"README says `make {target}`, "
                    f"which the Makefile does not define"
                )

    if "## Licensing" not in text:
        problems.append("README has no `## Licensing` section")
    for claim in ("MIT", "CC BY-SA"):
        if claim not in text:
            problems.append(f"README does not mention {claim}")

    for problem in problems:
        print(f"  FAIL {problem}", file=sys.stderr)
    if problems:
        return 1
    print("  README paths, make targets and licence claims all check out")
    return 0


if __name__ == "__main__":
    sys.exit(main())
