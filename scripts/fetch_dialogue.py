#!/usr/bin/env python3
"""Cache film script dialogue locally. COPYRIGHTED -- never committed, never published.

This is deliberately a separate script and a separate make target. It is not
part of `make data`, so the default path of this project never touches it.

What this is
------------
The screenplays are Lucasfilm's. IMSDb hosts transcriptions of them without a
licence grant, and nothing here changes that. Fetching a page you could read in
a browser, for your own reading, is ordinary personal use; redistributing the
text is not, and this project does not. Concretely:

  * output goes only to data/raw/dialogue/, which is gitignored
  * the script REFUSES to run if git does not confirm that path is ignored,
    so it cannot write into a tree where the result would be committable
  * nothing derived from this text is written to data/derived/, and the
    corpus the repository describes is built entirely without it

The licensed alternative -- Wikiquote, CC BY-SA, plus the quotes already inside
the Wookieepedia dump -- is fetched by `make data` like any other source and
may be processed and published freely. Prefer it where it suffices.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import fetch
from fetch import RAW

DEST = RAW / "dialogue"

# The eleven theatrical films, by their IMSDb slug. Checked 2026-09-11; IMSDb
# has no robots.txt, so the shared fetcher's permissive handling applies and
# requests stay serial and spaced.
BASE = "https://imsdb.com/scripts"
SCRIPTS = {
    "episode-1-the-phantom-menace": "Star-Wars-The-Phantom-Menace",
    "episode-2-attack-of-the-clones": "Star-Wars-Attack-of-the-Clones",
    "episode-3-revenge-of-the-sith": "Star-Wars-Revenge-of-the-Sith",
    "episode-4-a-new-hope": "Star-Wars-A-New-Hope",
    "episode-5-the-empire-strikes-back": "Star-Wars-The-Empire-Strikes-Back",
    "episode-6-return-of-the-jedi": "Star-Wars-Return-of-the-Jedi",
    "episode-7-the-force-awakens": "Star-Wars-The-Force-Awakens",
}

NOTICE = """\
COPYRIGHTED TEXT -- LOCAL USE ONLY
==================================

The files in this directory are transcriptions of Star Wars screenplays.
The screenplays are Copyright (c) Lucasfilm Ltd. / The Walt Disney Company.
They are NOT covered by this repository's MIT or CC BY 4.0 licences, and no
licence to redistribute them is granted or implied by their presence here.

They were fetched by scripts/fetch_dialogue.py for personal reading. This
directory is gitignored and the fetcher refuses to run if it is not. Do not
commit these files, do not publish them, and do not include them in anything
derived from this project that leaves your machine.

Source: https://imsdb.com/ -- a fan transcription site, not an authorised
publisher. Treat the text as approximate.

For dialogue that CAN be redistributed, use data/raw/quotes/ instead: those
come from Wikiquote and the Wookieepedia dump, both CC BY-SA.
"""

TAG = re.compile(r"<[^>]+>")
PRE = re.compile(r"<pre>(.*?)</pre>", re.S | re.I)


def refuse_if_committable() -> None:
    """Do not write copyrighted text anywhere git would let you commit it."""
    root = Path(__file__).resolve().parent.parent
    if not (root / ".git").exists():
        print(
            "  ~ not a git repository; the gitignore check cannot run.\n"
            "    Refusing anyway: set up the repo first, so the ignore rule "
            "is in place before the text is.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    probe = "data/raw/dialogue/probe.txt"
    result = subprocess.run(
        ["git", "check-ignore", "-q", probe], cwd=root, capture_output=True
    )
    if result.returncode != 0:
        print(
            f"REFUSING: {probe} is not gitignored.\n"
            f"This script writes copyrighted text and will not put it "
            f"anywhere that could be committed. Fix .gitignore first.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def to_text(html: bytes) -> str | None:
    """IMSDb wraps the screenplay in a <pre> block; everything else is chrome."""
    match = PRE.search(html.decode("utf-8", "replace"))
    if not match:
        return None
    import html as html_mod

    text = TAG.sub("", match.group(1))
    return html_mod.unescape(text).strip()


def main(argv: list[str]) -> int:
    refuse_if_committable()
    force = "--force" in argv
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "README.txt").write_text(NOTICE)

    ok = failed = 0
    for name, slug in SCRIPTS.items():
        dest = DEST / f"{name}.txt"
        if dest.exists() and not force:
            print(f"  = {name} ({dest.stat().st_size / 1e3:.0f} KB, cached)")
            ok += 1
            continue
        result = fetch.get(f"{BASE}/{slug}.html")
        if not result.ok:
            print(f"  !! {name}: {result.status}", file=sys.stderr)
            failed += 1
            continue
        text = to_text(result.body)
        if not text or len(text) < 5_000:
            # A 200 that is not a screenplay -- IMSDb serves a search page for
            # a slug it does not have, and that is a failure, not a script.
            print(f"  !! {name}: no <pre> screenplay in the response", file=sys.stderr)
            failed += 1
            continue
        dest.write_text(text)
        print(f"  ↓ {name}  {len(text) / 1e3:.0f} KB, " f"{len(text.split()):,} words")
        ok += 1

    print(f"\n{ok} cached, {failed} failed, in {DEST}")
    print(
        "This text is copyrighted and gitignored. It is not part of the "
        "published corpus."
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
