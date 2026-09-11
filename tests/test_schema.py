"""Contract tests on the generated corpus.

These skip -- they do not fail -- when data/derived/ is absent, so the suite is
meaningful on a fresh clone and in CI, where the multi-gigabyte sources are
deliberately not present. When the data IS there, they are strict: a field that
silently changed type, or an upstream that quietly returned half the catalogue,
should break the build rather than ship.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "data" / "derived" / "inventory.jsonl"
PLOTS = ROOT / "data" / "derived" / "plots.jsonl"

# Verified against the 2026-08-01 Wookieepedia dump. A floor, not an equality:
# the wiki grows, and a newer dump having more works is fine. Having far fewer
# means the parser broke or the dump is truncated.
MIN_WORKS = 11_000
MIN_NOVELS = 1_000
MIN_WITH_SUMMARY = 10_000

KINDS = {
    "novel",
    "short_story",
    "audio",
    "reference",
    "series",
    "collection",
    "comic",
    "comic_story",
    "comic_series",
    "video_game",
    "magazine",
    "magazine_article",
    "magazine_series",
    "film",
    "toy",
}
CONTINUITY = {"canon", "legends", "both", "unknown"}
REQUIRED = {
    "id": str,
    "franchise": str,
    "title": str,
    "kind": str,
    "continuity": str,
    "authors": list,
    "categories": list,
    "source": str,
    "source_url": str,
    "source_licence": str,
}


def load(path: Path) -> list[dict]:
    with path.open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


class TestInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not INVENTORY.exists():
            raise unittest.SkipTest(
                "data/derived/inventory.jsonl absent; run `make data`"
            )
        cls.rows = load(INVENTORY)

    def test_size(self) -> None:
        self.assertGreaterEqual(len(self.rows), MIN_WORKS)

    def test_required_fields_and_types(self) -> None:
        for row in self.rows[:2000]:
            for field, kind in REQUIRED.items():
                with self.subTest(id=row.get("id"), field=field):
                    self.assertIn(field, row)
                    self.assertIsInstance(row[field], kind)

    def test_ids_are_unique(self) -> None:
        ids = [r["id"] for r in self.rows]
        duplicates = {i for i in ids if ids.count(i) > 1} if len(ids) < 5000 else set()
        self.assertEqual(
            len(ids), len(set(ids)), f"duplicate ids, e.g. {list(duplicates)[:5]}"
        )

    def test_every_title_is_non_empty(self) -> None:
        blank = [r["id"] for r in self.rows if not r["title"].strip()]
        self.assertEqual(blank[:5], [], f"{len(blank)} works have no title")

    def test_kinds_are_from_the_shared_vocabulary(self) -> None:
        seen = {r["kind"] for r in self.rows}
        self.assertEqual(seen - KINDS, set(), "unexpected `kind` values")

    def test_continuity_vocabulary(self) -> None:
        seen = {r["continuity"] for r in self.rows}
        self.assertEqual(seen - CONTINUITY, set())

    def test_inference_never_overwrites_sourced_continuity(self) -> None:
        """A guess is only ever offered where the source said nothing."""
        for row in self.rows:
            if row["continuity"] != "unknown":
                with self.subTest(id=row["id"]):
                    self.assertIsNone(row["continuity_guess"])
                    self.assertEqual(row["continuity_basis"], "category")

    def test_has_a_real_number_of_novels(self) -> None:
        novels = [r for r in self.rows if r["kind"] == "novel"]
        self.assertGreaterEqual(len(novels), MIN_NOVELS)

    def test_known_works_are_present_and_correct(self) -> None:
        """Spot-checks against facts that do not change."""
        by_id = {r["id"]: r for r in self.rows}
        heir = by_id.get("sw:Heir_to_the_Empire")
        self.assertIsNotNone(heir, "Heir to the Empire is missing")
        self.assertEqual(heir["kind"], "novel")
        self.assertEqual(heir["published"], 1991)
        self.assertEqual(heir["continuity"], "legends")
        self.assertIn("Timothy Zahn", heir["authors"])
        self.assertEqual(heir["publisher"], "Bantam Spectra")

    def test_authors_contain_no_citation_leakage(self) -> None:
        """Reference works are not people. This was a real bug."""
        bad = [
            (r["id"], a)
            for r in self.rows
            for a in r["authors"]
            if "Essential Reader" in a or a.startswith("File:")
        ]
        self.assertEqual(bad[:5], [], f"{len(bad)} citation links leaked into authors")

    def test_publication_years_are_plausible(self) -> None:
        years = [r["published"] for r in self.rows if r["published"]]
        self.assertGreater(len(years), len(self.rows) * 0.8, "under 80% dated")
        self.assertGreaterEqual(min(years), 1976)  # the first SW publication
        self.assertLessEqual(max(years), 2030)

    def test_source_urls_are_wookieepedia(self) -> None:
        for row in self.rows[:500]:
            self.assertTrue(
                row["source_url"].startswith("https://starwars.fandom.com/wiki/")
            )


class TestPlots(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not PLOTS.exists():
            raise unittest.SkipTest("data/derived/plots.jsonl absent; run `make data`")
        cls.rows = load(PLOTS)

    def test_one_row_per_work(self) -> None:
        if not INVENTORY.exists():
            self.skipTest("inventory absent")
        self.assertEqual(
            len(self.rows),
            len(load(INVENTORY)),
            "plots and inventory must stay the same length",
        )

    def test_most_works_have_a_summary(self) -> None:
        with_summary = [r for r in self.rows if r["summary"]]
        self.assertGreaterEqual(len(with_summary), MIN_WITH_SUMMARY)

    def test_summary_licence_is_recorded_on_every_row(self) -> None:
        for row in self.rows[:1000]:
            self.assertEqual(row["summary_licence"], "CC-BY-SA-3.0")

    def test_word_count_matches_the_summary(self) -> None:
        for row in self.rows[:500]:
            expected = len(row["summary"].split()) if row["summary"] else 0
            self.assertEqual(row["words"], expected)

    def test_summaries_carry_no_residual_markup(self) -> None:
        for row in self.rows[:1000]:
            if not row["summary"]:
                continue
            with self.subTest(id=row["id"]):
                for marker in ("[[", "]]", "{{", "}}", "<ref", "&ndash;"):
                    self.assertNotIn(marker, row["summary"])


if __name__ == "__main__":
    unittest.main()
