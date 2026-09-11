#!/usr/bin/env python3
"""Stream pages out of a MediaWiki XML dump without ever unpacking it.

The Wookieepedia dump is 275 MB of 7z that expands to several GB of XML. There
is no reason for those GB to exist: `7z x -so` writes the archive to stdout,
iterparse consumes it as it arrives, and each element is cleared once read. Peak
memory stays flat and the only bytes on disk are the ones already downloaded.

The one trap in iterparse over MediaWiki XML is that clearing an element is not
enough -- the root keeps a reference to every child it has seen, so the tree
still grows. Deleting the preceding siblings from the root is what actually
bounds memory.
"""

from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

SEVEN_ZIP = "7z"


@dataclass(frozen=True)
class Page:
    title: str
    ns: int
    text: str

    @property
    def categories(self) -> list[str]:
        return [m.group(1).strip() for m in CATEGORY_RE.finditer(self.text)]

    @property
    def is_redirect(self) -> bool:
        return self.text.lstrip()[:9].upper().startswith("#REDIRECT")


CATEGORY_RE = re.compile(r"\[\[Category:([^\]|]+)", re.IGNORECASE)
# {{Template name | ...  -- captures only the name, which is all the filter needs.
TEMPLATE_RE = re.compile(r"\{\{\s*([A-Za-z0-9 _'\-]+?)\s*[\|\}]")


def templates(text: str) -> set[str]:
    """Every template invoked on the page, normalised to lowercase."""
    return {m.group(1).strip().lower() for m in TEMPLATE_RE.finditer(text)}


def stream(
    archive: Path, *, namespaces: set[int] | None = None, skip_redirects: bool = True
) -> Iterator[Page]:
    """Yield every page in the dump. `namespaces=None` means all of them."""
    if not archive.exists():
        raise FileNotFoundError(
            f"{archive} is missing -- run `make fetch` first (it is gitignored)"
        )
    proc = subprocess.Popen(
        [SEVEN_ZIP, "x", "-so", str(archive)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert proc.stdout is not None
    try:
        # The dump declares a namespace on <mediawiki>, so every tag arrives as
        # "{http://...}page". Matching on the local name keeps this independent
        # of which schema version the dump was written with.
        root = None
        for event, elem in ET.iterparse(proc.stdout, events=("start", "end")):
            if event == "start":
                if root is None:
                    root = elem
                continue
            if local(elem.tag) != "page":
                continue
            page = _to_page(elem)
            if page is not None and (namespaces is None or page.ns in namespaces):
                if not (skip_redirects and page.is_redirect):
                    yield page
            elem.clear()
            # Clearing the element is not enough: the root still holds it.
            if root is not None:
                del root[:]
    finally:
        proc.stdout.close()
        proc.terminate()
        proc.wait(timeout=30)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _to_page(elem: ET.Element) -> Page | None:
    title = ns = text = None
    for child in elem:
        name = local(child.tag)
        if name == "title":
            title = child.text or ""
        elif name == "ns":
            ns = int(child.text or 0)
        elif name == "revision":
            for sub in child:
                if local(sub.tag) == "text":
                    text = sub.text or ""
    if title is None:
        return None
    return Page(title=title, ns=ns or 0, text=text or "")


def check_7z() -> None:
    try:
        subprocess.run([SEVEN_ZIP, "--help"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        # `from None`: the traceback of the failed --help probe tells the reader
        # nothing useful; the message does.
        raise SystemExit(
            f"{SEVEN_ZIP} is not on PATH. The Fandom dumps are .7z; "
            f"install it with `brew install p7zip`."
        ) from None
