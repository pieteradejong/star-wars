# star-wars

A complete, provenance-tracked inventory of the Star Wars extended universe —
every novel, comic, short story, video game, reference book, magazine and film
Wookieepedia records — with a plot summary for each, derived from the wiki's own
XML dump. **11,597 works and 1.48 million words of summary**, built from source
in about ten minutes.

The code is here. The corpus is not: it is rebuilt locally by `make data` and
never committed, because the upstream text is CC BY-SA and this repository does
not redistribute it. See [Licensing](#licensing).

Its sister project, [star-trek](https://github.com/pieteradejong/star-trek),
does the same for the other franchise, into the same schema.

## Quick start

```sh
make data     # fetch (~275 MB) and build everything -- about 10 minutes
make test     # the full gate; also runs as ./test.sh
```

`make help` lists every target. `7z` is required for the dump
(`brew install p7zip`); everything else is the Python standard library.

## What you get

`data/derived/inventory.jsonl` — one JSON object per work:

```json
{
  "id": "sw:Heir_to_the_Empire",
  "title": "Heir to the Empire",
  "kind": "novel",
  "series": "Star Wars: The Thrawn Trilogy",
  "authors": ["Timothy Zahn"],
  "publisher": "Bantam Spectra",
  "published": 1991,
  "isbn": "9780553073270",
  "page_count": 368,
  "continuity": "legends",
  "continuity_basis": "category",
  "setting": "9 ABY",
  "source_url": "https://starwars.fandom.com/wiki/Heir_to_the_Empire"
}
```

`data/derived/plots.jsonl` — one summary per work, same `id`, same length.

| kind | works |
|---|---:|
| comic (issues, stories, series) | 4,063 |
| magazine articles and issues | 2,751 |
| novel | 1,144 |
| short_story | 885 |
| reference | 862 |
| collection | 727 |
| audio | 516 |
| video_game | 380 |
| film | 91 |
| other (series, toy) | 178 |
| **total** | **11,597** |

Field coverage: 93% have a publication year, 91% a publisher, 73% an author,
51% a page count, 27% an ISBN. 1,547 distinct authors.

## Data sources

| Source | What it gives | Licence | Size |
|---|---|---|---|
| [Wookieepedia XML dump](https://s3.amazonaws.com/wikia_xml_dumps/s/st/starwars_pages_current.xml.7z) | the spine: every work, its infobox and its plot | **CC BY-SA 3.0** | 275 MB `.7z`, 228,668 articles, dumped 2026-08-01 |
| [SWAPI](https://swapi.tech) | films and in-universe entities | free API | small |
| [Wikidata](https://query.wikidata.org/) | publication dates and authorship, as a cross-check | CC0 1.0 | 4,678 rows |

Every fetch is recorded in `data/MANIFEST.csv` — url, http status, bytes,
sha256, licence, date — which **is** tracked, so the cache can be verified
without the repository carrying it. A failed fetch is a row, not a gap.

### Sources evaluated and not used

Recorded so the next person need not redo the search.

- **SWAPI for the inventory.** It models only films, people, planets, species,
  starships and vehicles, for the six original films. It knows nothing of the
  Legends novels, the comics or the games. There is no structured catalogue of
  the Star Wars EU; that is why this project parses a wiki dump, and why the
  Star Trek side — which has [STAPI](https://stapi.co) — does not.
- **Wikidata as the spine.** `P8345 (media franchise) = Q462` returns 4,678
  rows but only 314 authors and 4 ISBNs across the whole franchise. Two other
  anchors were worse: `P1080 = Q19786052` gives 1,841 rows that are all
  in-universe entities with no authors at all, and `P179 = Q462` gives 16.
- **Full text of the novels.** There is no legitimate bulk source, and there is
  not going to be: they are in-copyright commercial fiction. This project
  catalogues and summarises the EU; it does not reproduce it.

## How it works

```
scripts/fetch_sources.py    download into data/raw/, write data/MANIFEST.csv
scripts/dump.py             stream pages out of the .7z without unpacking it
scripts/wikitext.py         infobox, plot section and markup handling
scripts/build_inventory.py  one pass over the dump -> inventory.jsonl
scripts/build_plots.py      a second pass -> plots.jsonl
scripts/check_invariants.py assert the figures this README quotes
```

The dump is never extracted. `7z x -so` writes it to stdout and
`ElementTree.iterparse` consumes it as it arrives, clearing each element and
detaching it from the root — which is the part that actually bounds memory.
30,000 pages stream in 4 seconds at **25 MB** peak RSS, and
`tests/check_dump.py` fails the build if that ever stops being true.

### Two things that had to be measured

- **`{{Film}}` is not the film infobox.** It appears 20,073 times and is a
  citation template; `{{Movie}}` appears 91 times and is the infobox. The
  nineteen real work infoboxes were found by counting every template in the
  dump first, then choosing — not by guessing names.
- **Continuity is not in the `{{Top}}` era flags.** Those are the in-universe
  setting: `Heir to the Empire` carries `rwm|new` meaning the New Republic era,
  despite being Legends. The canon/Legends split lives in the categories
  ("Legends novels", "Canon adult novels"), which cover 1,854 works. For the
  rest, the 2014 reboot date gives a sound inference — but it is inference, so
  it goes in `continuity_guess` with `continuity_basis` saying how it was
  reached, and it **never** overwrites what the source said.

## Dialogue

`make dialogue` caches film screenplays into `data/raw/dialogue/`. That text is
Lucasfilm copyright, is not covered by this repository's licences, and is not
part of the corpus. The fetcher refuses to run unless git confirms the target
directory is ignored, so it cannot write where the result could be committed.

Dialogue that *can* be redistributed — Wikiquote and the quotes already inside
the dump, both CC BY-SA — is fetched by `make data` like any other source.

## Tests

`./test.sh` runs six sections and reports all failures, not just the first:

| section | what it checks |
|---|---|
| `lint` | ruff, black, mypy, every script compiles, shellcheck |
| `unit` | the wikitext parser and the fetch layer, offline, no data needed |
| `boundary` | nothing fetched or generated is tracked; the baseline files exist |
| `data` | corpus contracts, the dump still streams in bounded memory, invariants |
| `manifest` | every row has a licence; cached bytes still match their sha256 |
| `docs` | every path and `make` target this README names actually exists |

`./test.sh --fast` skips the sections that read the dump; `./test.sh lint` runs
one section. Checks that need data **skip** rather than fail when `data/raw/` is
absent, so the suite is meaningful on a fresh clone and in CI.

## Licensing

Three-way split, and the distinction is the point:

- **Code** — `scripts/`, `tests/`, the build — is MIT. See `LICENSE`.
- **`data/curated/`** — the hand-authored source register and corrections — is
  CC BY 4.0. See `LICENSE-DATA`.
- **Everything fetched or derived from Wookieepedia** is CC BY-SA 3.0 and stays
  under Fandom's terms. It is not in this repository at all: `data/raw/` and
  `data/derived/` are gitignored, and CI fails the build if anything under
  them is ever committed. Rebuild it yourself with `make data`.

Star Wars, its titles, characters and settings are trademarks and copyrights of
Lucasfilm Ltd. This is an unofficial catalogue, not endorsed by or affiliated
with them.
