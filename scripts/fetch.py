#!/usr/bin/env python3
"""The shared fetch layer: retrieve a source once, keep it, and record what was kept.

Used by `fetch_sources.py` (dumps, APIs, quotes) and `fetch_dialogue.py`. Nothing
here is specific to either.

Two rules, and they are the whole design:

* **The cache is rebuildable and untracked; the manifest is tracked.** `data/raw/`
  holds the bytes and is gitignored -- the wiki dumps are hundreds of MB and git
  history never shrinks, and the upstream licence (Wookieepedia is CC BY-SA)
  carries a share-alike that travels with anything derived from the text.
  `data/MANIFEST.csv` holds the sha256 and the licence of each file, so drift is
  detectable without carrying the bytes.

* **A failed fetch is a row, not a gap.** A source that refuses automated requests
  is a measured fact; omitting it makes it indistinguishable from work not yet
  done.

Fetching politely: requests are serial, spaced by DELAY, carry a User-Agent that
says who is asking and points at the project, and obey robots.txt. A 403 is not
retried -- it is an answer.
"""

from __future__ import annotations

import csv
import hashlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "data" / "MANIFEST.csv"

FIELDS = [
    "source",
    "kind",
    "url",
    "http_status",
    "content_type",
    "bytes",
    "sha256",
    "licence",
    "retrieved",
]

# Says who is asking and points at the project, so an administrator who sees this
# in a log can find out what it is rather than guess. Fandom and Wikimedia both
# reject a default python-urllib or curl User-Agent with a 403; identifying
# yourself is both the cheapest courtesy and, here, a hard requirement.
PROJECT = "star-wars-corpus"
UA = (
    f"{PROJECT}/0.1 (personal research archive; "
    f"+https://github.com/pieteradejong/{PROJECT.removesuffix('-corpus')}) python-urllib"
)

TIMEOUT = 60
DELAY = 1.0  # seconds between requests, to every host alike

STATUS_ROBOTS = "robots-denied"
STATUS_TIMEOUT = "timeout"
STATUS_ERROR = "error"

_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
_last_request = 0.0


@dataclass(frozen=True)
class Result:
    """What came back. `status` is an HTTP code, or one of the STATUS_* strings."""

    status: str
    content_type: str
    body: bytes

    @property
    def ok(self) -> bool:
        return self.status == "200"


def _throttle() -> None:
    global _last_request
    wait = DELAY - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def _allowed(url: str) -> bool:
    """Does robots.txt permit this? An unreadable robots.txt is not a refusal.

    RobotFileParser.read() swallows the error when robots.txt itself 404s or
    403s and leaves the parser in a state where can_fetch() returns False for
    everything. That is wrong: "no robots.txt" and "robots.txt says no" are
    different answers, and collapsing them silently disables the whole fetcher.
    So an unreadable robots.txt is treated as permissive, which is what the
    standard actually specifies.
    """
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{origin}/robots.txt")
        try:
            _throttle()
            req = urllib.request.Request(rp.url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                rp.parse(r.read().decode("utf-8", "replace").splitlines())
            _robots[origin] = rp
        except Exception:
            _robots[origin] = None
    rp = _robots[origin]
    return True if rp is None else rp.can_fetch(UA, url)


def get(url: str, *, respect_robots: bool = True) -> Result:
    """Fetch one URL. Never raises; every outcome is a Result."""
    if respect_robots and not _allowed(url):
        return Result(STATUS_ROBOTS, "", b"")
    _throttle()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return Result("200", r.headers.get("Content-Type", ""), r.read())
    except urllib.error.HTTPError as e:
        return Result(str(e.code), e.headers.get("Content-Type", ""), b"")
    except TimeoutError:
        return Result(STATUS_TIMEOUT, "", b"")
    except Exception:
        return Result(STATUS_ERROR, "", b"")


def stream_to(url: str, dest: Path, *, respect_robots: bool = True) -> Result:
    """Fetch a large file straight to disk, in chunks, without holding it in RAM.

    The Wookieepedia dump is 262 MB; reading it into a bytes object first is
    avoidable waste. Writes to `<dest>.part` and renames on success, so an
    interrupted download never leaves a truncated file that looks cached.
    """
    if respect_robots and not _allowed(url):
        return Result(STATUS_ROBOTS, "", b"")
    _throttle()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    digest, size = hashlib.sha256(), 0
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r, tmp.open("wb") as fh:
            ctype = r.headers.get("Content-Type", "")
            total = int(r.headers.get("Content-Length") or 0)
            while chunk := r.read(1 << 20):
                fh.write(chunk)
                digest.update(chunk)
                size += len(chunk)
                if total:
                    pct = 100 * size / total
                    print(
                        f"\r    {size / 1e6:7.1f} / {total / 1e6:.1f} MB  {pct:5.1f}%",
                        end="",
                        file=sys.stderr,
                        flush=True,
                    )
        if total:
            print(file=sys.stderr)
        tmp.replace(dest)
    except urllib.error.HTTPError as e:
        tmp.unlink(missing_ok=True)
        return Result(str(e.code), "", b"")
    except Exception:
        tmp.unlink(missing_ok=True)
        return Result(STATUS_ERROR, "", b"")
    # Body is deliberately empty: the point of streaming was not to hold it.
    return Result("200", ctype, b"")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _display(path: Path) -> str:
    """Path relative to the project when it is inside it, absolute otherwise.

    relative_to() raises rather than falling back, and a manifest pointed
    somewhere else (as the tests do) should not crash the writer.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


class Manifest:
    """The tracked record of what was fetched. Rows accumulate, then are written once."""

    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def record(
        self,
        source: str,
        kind: str,
        url: str,
        result: Result,
        licence: str,
        path: Path | None = None,
    ) -> None:
        size = path.stat().st_size if path and path.exists() else len(result.body)
        if path and path.exists():
            digest = sha256_of(path)
        elif result.body:
            digest = hashlib.sha256(result.body).hexdigest()
        else:
            digest = ""
        self.rows.append(
            {
                "source": source,
                "kind": kind,
                "url": url,
                "http_status": result.status,
                "content_type": result.content_type.split(";")[0].strip(),
                "bytes": size,
                "sha256": digest,
                "licence": licence,
                "retrieved": date.today().isoformat(),
            }
        )

    def write(self) -> None:
        """Merge this run's rows into the manifest, replacing only what it touched.

        A partial run -- `--only=wikidata`, say -- must not erase the record of
        every source it did not look at. Rows are keyed by source: the ones
        fetched now win, the rest are carried forward.
        """
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        merged: dict[str, dict[str, object]] = {}
        if MANIFEST.exists():
            try:
                with MANIFEST.open(newline="") as fh:
                    for row in csv.DictReader(fh):
                        merged[row["source"]] = dict(row)
            except (OSError, KeyError):
                pass
        for row in self.rows:
            merged[str(row["source"])] = row
        with MANIFEST.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(
                sorted(
                    merged.values(), key=lambda r: (str(r["kind"]), str(r["source"]))
                )
            )
        failed = [r for r in self.rows if r["http_status"] != "200"]
        print(
            f"\n{_display(MANIFEST)}: {len(self.rows)} rows, " f"{len(failed)} failed"
        )
        for r in failed:
            print(f"  !! {r['source']}: {r['http_status']}")

    def previous_urls(self) -> dict[str, str]:
        """What each cached file was actually downloaded from, if we know.

        A cached file is only usable if it came from the URL we now want.
        Changing a source's URL has to re-download it, or the stale file is
        served silently in whatever format it used to have.
        """
        if not MANIFEST.exists():
            return {}
        try:
            with MANIFEST.open(newline="") as fh:
                return {r["source"]: r["url"] for r in csv.DictReader(fh)}
        except (OSError, KeyError):
            return {}
