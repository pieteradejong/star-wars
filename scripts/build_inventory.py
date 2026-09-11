#!/usr/bin/env python3
"""Derive the published-works inventory from the Wookieepedia dump.

One pass over the dump. A page is a published work if it carries one of the
infobox templates in BOXES; everything else -- characters, planets, in-universe
events, the 220,000 other articles -- is skipped.

Output is data/derived/inventory.jsonl, one JSON object per work, in the schema
shared with the sister star-trek project so the two can be compared.

Two things that had to be measured rather than assumed:

* **Which template marks a work.** `{{Film}}` appears 20,073 times and is a
  citation template; `{{Movie}}` appears 91 times and is the infobox. Counting
  first, then choosing, is the only way to tell those apart.
* **How continuity is marked.** Not by the `{{Top}}` era flags -- those are the
  in-universe setting (`old` = Old Republic era), not the canon/Legends split,
  and `Heir to the Empire` carries `rwm|new` despite being Legends. It is the
  categories that say it: "Legends novels", "Canon adult novels".
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import dump
import wikitext as wt

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "data" / "raw" / "wookieepedia.xml.7z"
OUT = ROOT / "data" / "derived" / "inventory.jsonl"

# infobox template -> the `kind` recorded in the shared schema.
BOXES = {
    "book": "novel",
    "shortstory": "short_story",
    "audiobook": "audio",
    "referencebook": "reference",
    "bookseries": "series",
    "bookcollection": "collection",
    "comicbook": "comic",
    "comicstory": "comic_story",
    "comiccollection": "collection",
    "comicseries": "comic_series",
    "comicmagazine": "comic",
    "comicstrip": "comic",
    "comicarc": "comic_series",
    "videogame": "video_game",
    "magazineissue": "magazine",
    "magazinearticle": "magazine_article",
    "magazineseries": "magazine_series",
    "movie": "film",
    "toyline": "toy",
}

# Infobox field names differ per template; these are tried in order.
AUTHOR_FIELDS = ("author", "writer", "writers", "developer", "director", "creator")
PUBLISHER_FIELDS = ("publisher", "publishers", "studio", "distributor")
DATE_FIELDS = ("release date", "released", "publication date", "airdate", "first aired")
PAGES_FIELDS = ("pages", "page count", "length")

ISBN_RE = re.compile(r"[\dX\-]{10,17}")


def continuity(categories: list[str]) -> str:
    """canon | legends | unknown, from the category prefixes that actually carry it."""
    canon = legends = False
    for c in categories:
        if c.startswith("Legends"):
            legends = True
        elif c.startswith("Canon"):
            canon = True
    if legends and not canon:
        return "legends"
    if canon and not legends:
        return "canon"
    # Both, or neither. Both happens on works reissued across the 2014 reboot;
    # recording it as ambiguous is more honest than picking one.
    return "both" if canon and legends else "unknown"


# Lucasfilm rebranded the existing expanded universe as "Legends" on
# 2014-04-25; works published after that under the Story Group are canon. The
# wiki does not categorise its tie-in and children's titles by continuity at
# all, which leaves ~84% of them unclassified from categories alone.
#
# That date is a sound rule of thumb but it is inference, not what the source
# says, so it NEVER overwrites `continuity`. It is reported separately, with
# the basis recorded, and anything ambiguous stays ambiguous.
REBOOT_YEAR = 2014


def inferred_continuity(sourced: str, year: int | None) -> tuple[str | None, str]:
    if sourced != "unknown":
        return None, "category"
    if year is None:
        return None, "none"
    if year < REBOOT_YEAR:
        return "legends", "published-before-2014-reboot"
    if year > REBOOT_YEAR:
        return "canon", "published-after-2014-reboot"
    # 2014 itself straddles the announcement; guessing here would be noise.
    return None, "none"


def first(params: dict[str, str], fields: tuple[str, ...]) -> str:
    for f in fields:
        if params.get(f):
            return params[f]
    return ""


def to_record(page: dump.Page, box: str, params: dict[str, str]) -> dict:
    title = wt.flatten(params.get("title", "")) or page.title
    date_field = first(params, DATE_FIELDS)
    pages_raw = wt.flatten(first(params, PAGES_FIELDS))
    pages_match = re.search(r"\d+", pages_raw)
    isbn = wt.flatten(params.get("isbn", ""))
    isbn_match = ISBN_RE.search(isbn.replace(" ", ""))
    year = wt.year_of(date_field)
    sourced_continuity = continuity(page.categories)
    guess, basis = inferred_continuity(sourced_continuity, year)
    return {
        "id": f"sw:{page.title.replace(' ', '_')}",
        "franchise": "star-wars",
        "title": title.replace("\n", " ").strip(),
        "page_title": page.title,
        "kind": BOXES[box],
        "infobox": box,
        "series": wt.flatten(params.get("series", "")).replace("\n", " ").strip()
        or None,
        "authors": wt.links(first(params, AUTHOR_FIELDS)),
        "publisher": (
            wt.links(first(params, PUBLISHER_FIELDS))
            or [wt.flatten(first(params, PUBLISHER_FIELDS))]
        )[0]
        or None,
        "published": year,
        "published_raw": wt.flatten(date_field).replace("\n", "; ").strip() or None,
        "isbn": isbn_match.group(0) if isbn_match else None,
        "page_count": int(pages_match.group(0)) if pages_match else None,
        "continuity": sourced_continuity,
        "continuity_guess": guess,
        "continuity_basis": basis,
        "setting": wt.flatten(params.get("timeline", "")).replace("\n", "; ").strip()
        or None,
        "media_type": wt.flatten(params.get("media type", ""))
        .replace("\n", "; ")
        .strip()
        or None,
        "categories": page.categories,
        "source": "wookieepedia",
        "source_url": "https://starwars.fandom.com/wiki/"
        + page.title.replace(" ", "_"),
        "source_licence": "CC-BY-SA-3.0",
    }


def main(argv: list[str]) -> int:
    dump.check_7z()
    limit = next(
        (int(a.split("=", 1)[1]) for a in argv if a.startswith("--limit=")), None
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    n = 0
    with OUT.open("w") as fh:
        for page in dump.stream(ARCHIVE, namespaces={0}, skip_redirects=True):
            box = wt.find_infobox(page.text, set(BOXES))
            if box is None:
                continue
            record = to_record(page, box[0], box[1])
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            counts[record["kind"]] = counts.get(record["kind"], 0) + 1
            n += 1
            if n % 500 == 0:
                print(f"\r  {n} works", end="", flush=True)
            if limit and n >= limit:
                break
    print(f"\r{OUT.relative_to(ROOT)}: {n} works")
    for kind, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {count:6d}  {kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
