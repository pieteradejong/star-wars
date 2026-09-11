"""Provenance: the manifest is tracked, the bytes are not, so the manifest must be right.

data/MANIFEST.csv is the only record in the repository of what was downloaded
and under what licence. If it drifts from the cache, the repository is making a
claim about data nobody can check. These tests skip when no cache is present.
"""

from __future__ import annotations

import csv
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fetch  # noqa: E402

MANIFEST = ROOT / "data" / "MANIFEST.csv"
RAW = ROOT / "data" / "raw"


class TestManifestFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not MANIFEST.exists():
            raise unittest.SkipTest("data/MANIFEST.csv absent; run `make fetch`")
        with MANIFEST.open(newline="") as fh:
            cls.rows = list(csv.DictReader(fh))

    def test_has_rows(self) -> None:
        self.assertGreater(len(self.rows), 0)

    def test_columns_are_the_agreed_schema(self) -> None:
        self.assertEqual(set(self.rows[0]), set(fetch.FIELDS))

    def test_every_row_names_a_licence(self) -> None:
        """A source whose licence nobody wrote down is a source nobody can use."""
        blank = [r["source"] for r in self.rows if not r["licence"].strip()]
        self.assertEqual(blank, [], f"rows with no licence: {blank}")

    def test_every_row_has_a_url_and_a_date(self) -> None:
        for row in self.rows:
            with self.subTest(source=row["source"]):
                self.assertTrue(row["url"].startswith("http"))
                self.assertRegex(row["retrieved"], r"^\d{4}-\d{2}-\d{2}$")

    def test_successful_rows_carry_a_sha256(self) -> None:
        for row in self.rows:
            if row["http_status"] == "200":
                with self.subTest(source=row["source"]):
                    self.assertRegex(row["sha256"], r"^[0-9a-f]{64}$")
                    self.assertGreater(int(row["bytes"]), 0)

    def test_noncommercial_sources_are_labelled_as_such(self) -> None:
        """Memory Alpha is CC BY-NC. Mislabelling it is the one licensing error
        that would actually matter, so it is asserted rather than assumed."""
        for row in self.rows:
            if "memory-alpha" in row["source"]:
                self.assertIn("NC", row["licence"])


class TestManifestMatchesCache(unittest.TestCase):
    """The bytes on disk must still be the bytes the manifest describes."""

    @classmethod
    def setUpClass(cls) -> None:
        if not MANIFEST.exists() or not RAW.exists():
            raise unittest.SkipTest("no cache present")
        with MANIFEST.open(newline="") as fh:
            cls.rows = list(csv.DictReader(fh))

    def test_cached_files_match_their_recorded_hash(self) -> None:
        checked = 0
        for row in self.rows:
            if row["http_status"] != "200" or not row["sha256"]:
                continue
            # The manifest names sources, which map to paths under data/raw/.
            candidates = [
                RAW / row["source"],
                RAW / f"{row['source']}.json",
                RAW / f"{row['source']}.jsonl",
            ]
            path = next((p for p in candidates if p.is_file()), None)
            if path is None:
                continue  # fetched into a directory, or cleaned since
            with self.subTest(source=row["source"]):
                self.assertEqual(
                    fetch.sha256_of(path),
                    row["sha256"],
                    f"{path.name} has changed since it was recorded",
                )
                self.assertEqual(path.stat().st_size, int(row["bytes"]))
            checked += 1
        if checked == 0:
            self.skipTest("no cached files to verify")


if __name__ == "__main__":
    unittest.main()
