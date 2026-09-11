#!/usr/bin/env python3
"""Download every third-party source into data/raw/ (gitignored).

Nothing here is committed: the dump is 262 MB, it carries its own licence, and
it changes upstream. Run `make data` to fetch and then rebuild the corpus under
data/derived/.

Sources and licences are catalogued in README.md -> "Data sources", and every
fetch is recorded in data/MANIFEST.csv, which IS tracked.

Why the dump and not an API
---------------------------
There is no structured catalogue of the Star Wars extended universe. SWAPI --
the obvious candidate -- models only films, people, planets, species, starships
and vehicles, for the six original films. It knows nothing of the ~400 Legends
novels, the comics, or the games. So the inventory is derived by parsing
Wookieepedia offline. Its sister project (star-trek) has STAPI and does not
need this.

Deliberately NOT here: scripts/fetch_dialogue.py. Verbatim film scripts are
Lucasfilm copyright and are cached local-only; keeping it out of `make data`
means the default path never touches it.
"""

from __future__ import annotations

import json
import sys
import time

import fetch
from fetch import RAW, Manifest

# Db name came from starwars.fandom.com/api.php?action=query&meta=siteinfo
# (wikiid "starwars"); the licence from the same endpoint's rightsinfo.
# 228,668 articles / 730,534 pages as of the 2026-08-01 dump.
DUMPS = {
    "wookieepedia.xml.7z": {
        "url": "https://s3.amazonaws.com/wikia_xml_dumps/s/st/starwars_pages_current.xml.7z",
        "licence": "CC-BY-SA-3.0 (Wookieepedia)",
        "note": "228,668 articles: canon + Legends, the whole EU",
    },
}

# Enrichment only -- neither of these drives the inventory.
SWAPI = "https://swapi.tech/api"
SWAPI_ENTITIES = ["films", "people", "planets", "species", "starships", "vehicles"]
SWAPI_LICENCE = "SWAPI (swapi.tech), free API -- data about copyrighted works"

# A CC0 cross-check on publication dates and authorship, nothing more.
#
# Anchor choice, measured rather than assumed. Three candidates were tried:
#   P1080 (narrative universe) = Q19786052 -> 1,841 rows, ALL in-universe
#     entities (planets, characters, locations) and zero authors. Useless here.
#   P179  (part of the series) = Q462       -> 16 rows. Far too narrow.
#   P8345 (media franchise)    = Q462       -> 4,678 rows, including 286
#     literary works, 188 video games and 84 films, with 314 authors.
# So P8345 it is. Note how thin that still is: 314 authors and 4 ISBNs across
# the whole franchise. Wikidata cannot carry this project's inventory -- which
# is precisely why the Wookieepedia dump is the spine and this is enrichment.
WIKIDATA = "https://query.wikidata.org/sparql"
WIKIDATA_LICENCE = "CC0-1.0 (Wikidata)"
# Deliberately unfiltered by type: the in-universe rows are dropped when the
# inventory is built, and keeping them here costs one query instead of six.
WIKIDATA_QUERY = """
SELECT ?work ?workLabel ?typeLabel ?pubdate ?isbn
       (GROUP_CONCAT(DISTINCT ?authorName; separator="|") AS ?authors)
WHERE {
  ?work wdt:P8345 wd:Q462 .
  OPTIONAL { ?work wdt:P31  ?type }
  OPTIONAL { ?work wdt:P577 ?pubdate }
  OPTIONAL { ?work wdt:P212 ?isbn }
  OPTIONAL { ?work wdt:P50  ?author .
             ?author rdfs:label ?authorName . FILTER(LANG(?authorName)="en") }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
}
GROUP BY ?work ?workLabel ?typeLabel ?pubdate ?isbn
"""


def fetch_dumps(manifest: Manifest, force: bool) -> None:
    known = manifest.previous_urls()
    for name, spec in DUMPS.items():
        dest = RAW / name
        stale = known.get(name) not in (None, spec["url"])
        if stale and dest.exists():
            print(f"  ~ {name} was fetched from a different URL; re-downloading")
        if dest.exists() and not force and not stale:
            print(f"  = {name} ({dest.stat().st_size / 1e6:.1f} MB, cached)")
            manifest.record(
                name,
                "dump",
                spec["url"],
                fetch.Result("200", "application/x-7z-compressed", b""),
                spec["licence"],
                dest,
            )
            continue
        print(f"  ↓ {name}  [{spec['note']}]")
        # S3 serves no robots.txt for these paths and the dumps are published
        # for exactly this use; the wiki host itself is still checked.
        res = fetch.stream_to(spec["url"], dest, respect_robots=False)
        if res.ok:
            print(
                f"    {dest.stat().st_size / 1e6:.1f} MB  "
                f"sha256={fetch.sha256_of(dest)[:16]}"
            )
        else:
            print(f"    !! {res.status}", file=sys.stderr)
        manifest.record(name, "dump", spec["url"], res, spec["licence"], dest)


def fetch_swapi(manifest: Manifest, force: bool) -> None:
    """Pull the six SWAPI collections. Small, and complete in a handful of pages."""
    for entity in SWAPI_ENTITIES:
        dest = RAW / "swapi" / f"{entity}.json"
        if dest.exists() and not force:
            print(f"  = swapi/{entity}.json (cached)")
            manifest.record(
                f"swapi/{entity}",
                "api",
                f"{SWAPI}/{entity}",
                fetch.Result("200", "application/json", b""),
                SWAPI_LICENCE,
                dest,
            )
            continue
        records: list[dict] = []
        url, status = f"{SWAPI}/{entity}?page=1&limit=100", "200"
        while url:
            res = fetch.get(url, respect_robots=False)
            if not res.ok:
                status = res.status
                print(f"    !! {entity}: {res.status}", file=sys.stderr)
                break
            payload = json.loads(res.body)
            # swapi.tech returns {"results": [...], "next": url} for the paged
            # collections but {"result": [...]} for /films, which is not paged.
            records.extend(payload.get("results") or payload.get("result") or [])
            url = payload.get("next")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(records, indent=1) + "\n")
        print(f"  ↓ swapi/{entity}.json  {len(records)} records")
        manifest.record(
            f"swapi/{entity}",
            "api",
            f"{SWAPI}/{entity}",
            fetch.Result(status, "application/json", b""),
            SWAPI_LICENCE,
            dest,
        )


def fetch_wikidata(manifest: Manifest, force: bool) -> None:
    dest = RAW / "wikidata" / "works.json"
    if dest.exists() and not force:
        print("  = wikidata/works.json (cached)")
        manifest.record(
            "wikidata/works",
            "api",
            WIKIDATA,
            fetch.Result("200", "application/json", b""),
            WIKIDATA_LICENCE,
            dest,
        )
        return
    import urllib.parse

    url = f"{WIKIDATA}?format=json&query={urllib.parse.quote(WIKIDATA_QUERY)}"
    # WDQS takes ~30s to plan and stream this one; the shared 60s timeout is
    # cutting it close, so this call alone gets longer.
    previous, fetch.TIMEOUT = fetch.TIMEOUT, 180
    try:
        res = fetch.get(url, respect_robots=False)
    finally:
        fetch.TIMEOUT = previous
    dest.parent.mkdir(parents=True, exist_ok=True)
    if res.ok:
        rows = json.loads(res.body)["results"]["bindings"]
        dest.write_text(json.dumps(rows, indent=1) + "\n")
        print(f"  ↓ wikidata/works.json  {len(rows)} rows")
    else:
        print(f"    !! wikidata: {res.status}", file=sys.stderr)
    manifest.record(
        "wikidata/works",
        "api",
        WIKIDATA,
        res,
        WIKIDATA_LICENCE,
        dest if dest.exists() else None,
    )


def main(argv: list[str]) -> int:
    force = "--force" in argv
    only = next((a.split("=", 1)[1] for a in argv if a.startswith("--only=")), None)
    RAW.mkdir(parents=True, exist_ok=True)
    manifest = Manifest()
    started = time.monotonic()

    if only in (None, "swapi"):
        print("SWAPI (films and in-universe entities; no EU coverage)")
        fetch_swapi(manifest, force)
    if only in (None, "wikidata"):
        print("\nWikidata (publication dates, ISBNs, series -- a CC0 cross-check)")
        fetch_wikidata(manifest, force)
    if only in (None, "dumps"):
        print("\nWookieepedia dump (the spine: every EU work and its plot)")
        fetch_dumps(manifest, force)

    manifest.write()
    print(f"done in {time.monotonic() - started:.0f}s")
    return 0 if all(r["http_status"] == "200" for r in manifest.rows) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
