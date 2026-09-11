"""Unit tests for the shared fetch layer. No network: every HTTP call is stubbed.

The behaviours worth pinning down are the ones that are wrong by default:
robots.txt handling, the manifest recording failures, and cache invalidation
when a source URL changes.
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from typing import ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch


class TestResult(unittest.TestCase):
    def test_ok_is_only_200(self) -> None:
        self.assertTrue(fetch.Result("200", "", b"").ok)
        for status in ("404", "403", fetch.STATUS_TIMEOUT, fetch.STATUS_ERROR):
            self.assertFalse(fetch.Result(status, "", b"").ok)


class TestRobots(unittest.TestCase):
    def setUp(self) -> None:
        fetch._robots.clear()
        fetch._last_request = 0.0

    def tearDown(self) -> None:
        fetch._robots.clear()

    def test_unreadable_robots_is_permissive(self) -> None:
        """The bug this guards against.

        RobotFileParser.read() swallows a 404/403 and then answers False for
        every path. "No robots.txt" and "robots.txt forbids it" are different
        answers; collapsing them silently disables the whole fetcher.
        """
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError("u", 403, "Forbidden", {}, None),
        ):  # type: ignore[arg-type]
            self.assertTrue(fetch._allowed("https://example.test/a"))

    def test_disallow_is_honoured(self) -> None:
        body = b"User-agent: *\nDisallow: /private\n"
        with mock.patch("urllib.request.urlopen", _fake_response(body)):
            self.assertFalse(fetch._allowed("https://example.test/private/x"))
            self.assertTrue(fetch._allowed("https://example.test/public/x"))

    def test_robots_is_fetched_once_per_origin(self) -> None:
        body = b"User-agent: *\nAllow: /\n"
        with mock.patch("urllib.request.urlopen", _fake_response(body)) as m:
            fetch._allowed("https://example.test/a")
            fetch._allowed("https://example.test/b")
            self.assertEqual(m.call_count, 1)


class TestGet(unittest.TestCase):
    def setUp(self) -> None:
        fetch._robots.clear()
        fetch._last_request = 0.0

    def test_http_error_becomes_a_result_not_an_exception(self) -> None:
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError("u", 404, "Not Found", {}, None),
        ):  # type: ignore[arg-type]
            result = fetch.get("https://example.test/x", respect_robots=False)
        self.assertEqual(result.status, "404")
        self.assertFalse(result.ok)

    def test_connection_error_becomes_a_result(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=OSError("reset")):
            result = fetch.get("https://example.test/x", respect_robots=False)
        self.assertEqual(result.status, fetch.STATUS_ERROR)

    def test_robots_denied_short_circuits(self) -> None:
        body = b"User-agent: *\nDisallow: /\n"
        with mock.patch("urllib.request.urlopen", _fake_response(body)):
            result = fetch.get("https://example.test/x")
        self.assertEqual(result.status, fetch.STATUS_ROBOTS)


class TestManifest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.manifest = self.root / "MANIFEST.csv"
        self.patch = mock.patch.object(fetch, "MANIFEST", self.manifest)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def test_a_failed_fetch_is_a_row_not_a_gap(self) -> None:
        m = fetch.Manifest()
        m.record(
            "good",
            "api",
            "https://a.test",
            fetch.Result("200", "application/json", b"{}"),
            "CC0",
        )
        m.record("bad", "api", "https://b.test", fetch.Result("403", "", b""), "CC0")
        m.write()
        rows = list(csv.DictReader((self.root / "MANIFEST.csv").open()))
        self.assertEqual(len(rows), 2)
        statuses = {r["source"]: r["http_status"] for r in rows}
        self.assertEqual(statuses, {"good": "200", "bad": "403"})

    def test_sha256_and_size_come_from_the_file_when_given(self) -> None:
        path = self.root / "payload.bin"
        path.write_bytes(b"hello")
        m = fetch.Manifest()
        m.record(
            "p",
            "dump",
            "https://a.test",
            fetch.Result("200", "", b""),
            "CC-BY-SA",
            path,
        )
        m.write()
        row = next(iter(csv.DictReader((self.root / "MANIFEST.csv").open())))
        self.assertEqual(row["bytes"], "5")
        self.assertEqual(
            row["sha256"],
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        )
        self.assertEqual(row["licence"], "CC-BY-SA")

    def test_every_row_records_a_licence(self) -> None:
        m = fetch.Manifest()
        m.record(
            "x", "api", "https://a.test", fetch.Result("200", "", b"{}"), "CC-BY-NC-3.0"
        )
        m.write()
        row = next(iter(csv.DictReader((self.root / "MANIFEST.csv").open())))
        self.assertTrue(row["licence"], "licence must never be blank")

    def test_previous_urls_round_trips(self) -> None:
        """Cache invalidation depends on this: a changed URL must re-download."""
        m = fetch.Manifest()
        m.record(
            "dump", "dump", "https://old.test/f.7z", fetch.Result("200", "", b"x"), "CC"
        )
        m.write()
        self.assertEqual(
            fetch.Manifest().previous_urls(), {"dump": "https://old.test/f.7z"}
        )

    def test_a_partial_run_merges_rather_than_erasing(self) -> None:
        """The regression: `--only=wikidata` used to rewrite the manifest with
        a single row, destroying the record of every source it did not touch."""
        first = fetch.Manifest()
        first.record("a", "api", "https://a.test", fetch.Result("200", "", b"1"), "CC0")
        first.record(
            "b", "dump", "https://b.test", fetch.Result("200", "", b"2"), "CC-BY-SA"
        )
        first.write()

        second = fetch.Manifest()  # a partial run touching only "a"
        second.record(
            "a", "api", "https://a.test/v2", fetch.Result("200", "", b"3"), "CC0"
        )
        second.write()

        rows = {r["source"]: r for r in csv.DictReader(self.manifest.open())}
        self.assertEqual(set(rows), {"a", "b"}, "the untouched row was dropped")
        self.assertEqual(
            rows["a"]["url"], "https://a.test/v2", "the fetched row must win"
        )
        self.assertEqual(rows["b"]["licence"], "CC-BY-SA")

    def test_previous_urls_is_empty_when_absent(self) -> None:
        self.assertEqual(fetch.Manifest().previous_urls(), {})


class TestUserAgent(unittest.TestCase):
    def test_identifies_the_project_and_a_contact_url(self) -> None:
        """Fandom and Wikimedia 403 a default urllib UA; this is a requirement."""
        self.assertIn("github.com/pieteradejong", fetch.UA)
        self.assertNotIn("Python-urllib/", fetch.UA)


def _fake_response(body: bytes):
    class _R:
        headers: ClassVar[dict[str, str]] = {"Content-Type": "text/plain"}

        def read(self, *_a: object) -> bytes:
            return body

        def __enter__(self) -> _R:
            return self

        def __exit__(self, *_a: object) -> bool:
            return False

    return mock.MagicMock(return_value=_R())


if __name__ == "__main__":
    unittest.main()
