"""The data boundary: what may and may not be committed.

This is the mechanical enforcement of the whole licensing story. The upstream
wiki text is CC BY-SA (and on the Star Trek side, CC BY-NC), so this repository
publishes the code that fetches and parses it, never the text itself. That rule
is only real if something checks it, and this is the something.

These tests run with no data present and are the reason CI can be trusted.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Anything under these paths is fetched or generated, and must never be tracked.
FORBIDDEN = re.compile(r"^data/(raw|derived)/")
# Bulk formats have no business in the tree at all, wherever they sit.
FORBIDDEN_EXT = re.compile(r"\.(7z|xml|jsonl|sqlite3?|db)$")
# data/curated/ is hand-authored and small; everything else tracked should be too.
MAX_TRACKED_BYTES = 1_000_000


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        return []
    return [line for line in out.stdout.splitlines() if line]


class TestGitBoundary(unittest.TestCase):
    def setUp(self) -> None:
        self.files = tracked()
        if not self.files:
            self.skipTest("not a git repository yet, or nothing committed")

    def test_no_fetched_or_generated_data_is_tracked(self) -> None:
        leaked = [f for f in self.files if FORBIDDEN.match(f)]
        self.assertEqual(leaked, [], f"fetched/generated data is tracked: {leaked}")

    def test_no_bulk_formats_are_tracked(self) -> None:
        leaked = [
            f
            for f in self.files
            if FORBIDDEN_EXT.search(f) and not f.startswith("data/curated/")
        ]
        self.assertEqual(leaked, [], f"bulk data formats are tracked: {leaked}")

    def test_no_large_files_are_tracked(self) -> None:
        big = []
        for name in self.files:
            path = ROOT / name
            if path.is_file() and path.stat().st_size > MAX_TRACKED_BYTES:
                big.append(f"{name} ({path.stat().st_size / 1e6:.1f} MB)")
        self.assertEqual(big, [], f"tracked files over 1 MB: {big}")

    def test_no_env_files_are_tracked(self) -> None:
        env = [
            f
            for f in self.files
            if re.search(r"(^|/)\.env(\..+)?$", f)
            and not re.search(r"\.env\.(template|example)$", f)
        ]
        self.assertEqual(env, [], f"env files are tracked: {env}")


class TestGitignore(unittest.TestCase):
    """The rules must exist and must actually match, not merely be present.

    `.gitignore` not matching is the classic silent failure: an anchored
    pattern that looks right and matches nothing.
    """

    def test_gitignore_exists(self) -> None:
        self.assertTrue((ROOT / ".gitignore").is_file())

    def test_data_dirs_are_actually_ignored(self) -> None:
        if not (ROOT / ".git").exists():
            self.skipTest("not a git repository yet")
        for probe in (
            "data/raw/probe.7z",
            "data/derived/probe.jsonl",
            "data/raw/dialogue/probe.txt",
        ):
            with self.subTest(probe=probe):
                out = subprocess.run(
                    ["git", "check-ignore", "-v", probe],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    out.returncode, 0, f"{probe} is NOT ignored by any rule"
                )

    def test_curated_data_is_not_ignored(self) -> None:
        """The carve-out must stay narrow: data/curated/ is meant to be committed."""
        if not (ROOT / ".git").exists():
            self.skipTest("not a git repository yet")
        out = subprocess.run(
            ["git", "check-ignore", "data/curated/sources.yaml"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(
            out.returncode, 0, "data/curated/ is ignored; it is meant to be tracked"
        )


class TestRequiredFiles(unittest.TestCase):
    """The account-wide baseline from GITHUB_STANDARDS: a public repo has these."""

    def test_baseline_files_exist(self) -> None:
        for name in (
            "README.md",
            "LICENSE",
            "LICENSE-DATA",
            ".gitignore",
            "Makefile",
            "test.sh",
            ".github/workflows/ci.yml",
        ):
            with self.subTest(name=name):
                self.assertTrue((ROOT / name).is_file(), f"{name} is missing")

    def test_licence_is_plain_mit(self) -> None:
        """No preamble: GitHub's licence detector gives up on a file with extra prose."""
        text = (ROOT / "LICENSE").read_text()
        self.assertTrue(
            text.startswith("MIT License"), "LICENSE must begin with the bare MIT text"
        )
        self.assertIn("Copyright (c) 2026 Pieter de Jong", text)

    def test_data_licence_states_the_carve_out(self) -> None:
        text = (ROOT / "LICENSE-DATA").read_text()
        self.assertIn("data/curated/", text)
        for term in ("CC BY-SA", "CC BY 4.0"):
            self.assertIn(term, text, f"LICENSE-DATA should name {term}")


if __name__ == "__main__":
    unittest.main()
