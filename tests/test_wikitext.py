"""Unit tests for the wikitext parser.

Every fixture here is real wikitext, copied from the article named in the
docstring. Synthetic markup would not exercise the cases that actually break a
parser -- nested templates inside a `<ref>` inside an infobox parameter, say.
These run offline and need no dump.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import wikitext as wt

# From "Heir to the Empire". Trimmed, but every structure kept: a piped link,
# a bulleted multi-value field, a <br/>, a {{C|...}} qualifier, and a <ref>
# containing a template that itself contains pipes and an = sign.
HEIR = """{{Top|rwm|new|italics=1}}
{{Book
|image=[[File:HeirtotheEmpire.jpg]]
|title=''Heir to the Empire''
|author=[[Timothy Zahn]]
|cover artist=*[[Tom Jung]]<br/>{{C|Original cover}}
*[[Tracie Ching]]<ref name="Essential">{{Twitter|DelReyStarWars|status/1377|[[Del Rey]]|quote=We love looking at cover art, here's Heir to the Empire}}</ref> {{C|''[[The Essential Legends Collection]]'' cover}}
|publisher=[[Bantam Spectra]]
|release date=[[May 1]], [[1991]]<ref name="YBY">''[[Star Wars Year By Year]]''</ref>
|pages=368
|isbn=9780553073270
|series=''[[Star Wars: The Thrawn Trilogy]]''
|timeline=9 [[Anno Battle of Yavin|ABY]]
}}
'''''Heir to the Empire''''' is a novel by [[Timothy Zahn]].

==Plot summary==
Five years after the [[Battle of Endor]], a new threat emerges.
The [[Grand Admiral]] gathers his forces &ndash; and strikes.

==Appearances==
*[[Luke Skywalker]]

[[Category:Legends novels]]
"""


class TestInfobox(unittest.TestCase):
    def setUp(self) -> None:
        found = wt.find_infobox(HEIR, {"book", "movie"})
        assert found is not None
        self.name, self.params = found

    def test_finds_the_infobox_not_the_banner(self) -> None:
        # {{Top|...}} comes first in the text and must not be mistaken for it.
        self.assertEqual(self.name, "book")

    def test_simple_fields(self) -> None:
        self.assertEqual(wt.flatten(self.params["title"]), "Heir to the Empire")
        self.assertEqual(self.params["pages"], "368")
        self.assertEqual(self.params["isbn"], "9780553073270")

    def test_pipes_inside_a_ref_do_not_split_the_field(self) -> None:
        """The regression this parser exists for.

        `cover artist` holds a <ref> wrapping {{Twitter|a|b|c|quote=...}}. A
        naive split on "|" turns that into six bogus parameters and loses
        every field after it.
        """
        self.assertIn("cover artist", self.params)
        self.assertIn("publisher", self.params)
        self.assertEqual(wt.flatten(self.params["publisher"]), "Bantam Spectra")
        self.assertEqual(wt.flatten(self.params["release date"]), "May 1, 1991")

    def test_links_extracts_people_and_skips_citations(self) -> None:
        artists = wt.links(self.params["cover artist"])
        self.assertIn("Tom Jung", artists)
        self.assertIn("Tracie Ching", artists)
        # Inside the <ref>: a publisher and a reference work, neither an artist.
        self.assertNotIn("Del Rey", artists)
        self.assertNotIn("The Essential Legends Collection", artists)

    def test_links_skips_file_and_category_targets(self) -> None:
        self.assertEqual(wt.links(self.params["image"]), [])

    def test_year_of(self) -> None:
        self.assertEqual(wt.year_of(self.params["release date"]), 1991)
        self.assertIsNone(wt.year_of("no date here"))

    def test_year_survives_a_template_wrapped_date(self) -> None:
        """Memory Beta writes {{srcdate|2008|February}}; flattening first
        strips the template and loses the year entirely."""
        self.assertEqual(wt.year_of("{{srcdate|2008|February}}"), 2008)

    def test_year_ignores_a_citation_year(self) -> None:
        """A <ref> naming a differently-dated source sits in the same field."""
        self.assertEqual(
            wt.year_of("<ref name='YBY'>Year By Year, 2012</ref>[[May 1]], [[1991]]"),
            1991,
        )


class TestFlatten(unittest.TestCase):
    def test_strips_markup(self) -> None:
        self.assertEqual(wt.flatten("'''''Bold italic'''''"), "Bold italic")
        self.assertEqual(wt.flatten("[[Luke Skywalker]]"), "Luke Skywalker")
        self.assertEqual(wt.flatten("[[Anno Battle of Yavin|ABY]]"), "ABY")
        self.assertEqual(wt.flatten("text<!-- hidden -->more"), "textmore")

    def test_br_becomes_a_space(self) -> None:
        """Dropping <br/> outright welds words together."""
        self.assertEqual(
            wt.flatten("Darth Bane:<br />Path of Destruction"),
            "Darth Bane: Path of Destruction",
        )

    def test_html_entities_are_decoded(self) -> None:
        # The EN DASH here is deliberate: it is what &ndash; must decode to.
        self.assertEqual(
            wt.flatten("1006 BBY&ndash;1000 BBY"), "1006 BBY\u20131000 BBY"
        )
        self.assertEqual(wt.flatten("Tom &amp; Jerry"), "Tom & Jerry")

    def test_image_embeds_are_dropped_caption_and_all(self) -> None:
        """A picture is not prose, and its caption carries layout junk."""
        self.assertEqual(
            wt.flatten("[[File:X.jpg|thumb|left|180px|A caption]]Real prose."),
            "Real prose.",
        )
        self.assertEqual(wt.flatten("[[Image:a.png|thumb|c]]Text."), "Text.")

    def test_links_nested_inside_an_image_caption_leave_no_markup(self) -> None:
        """The regression: a non-greedy match stops at the INNER ']]' and
        strands the outer one in the output as literal markup."""
        out = wt.flatten(
            "[[File:X.jpg|thumb|[[Aurra Sing/Legends|Aurra Sing.]]]]Prose."
        )
        self.assertEqual(out, "Prose.")
        for marker in ("[[", "]]", "thumb"):
            self.assertNotIn(marker, out)

    def test_malformed_source_markup_leaves_nothing_behind(self) -> None:
        """The wikis contain genuinely broken links -- a doubled "]]", an
        unclosed "[[". No correct parse resolves those, because the source is
        wrong; once the well-formed links are gone, the remains are swept."""
        for broken in (
            "the [[Interdiction field|interdiction field]]]] barricading it",
            "an [[unclosed link that never closes",
            "a stray ]] bracket",
        ):
            with self.subTest(broken=broken):
                out = wt.flatten(broken)
                self.assertNotIn("[[", out)
                self.assertNotIn("]]", out)

    def test_refs_are_removed_including_self_closing(self) -> None:
        self.assertEqual(wt.flatten("Text<ref name='a'>Note</ref> more"), "Text more")
        self.assertEqual(wt.flatten("Text<ref name='a' /> more"), "Text more")


class TestSections(unittest.TestCase):
    def test_finds_named_section(self) -> None:
        plot = wt.section(HEIR, {"plot summary"})
        assert plot is not None
        self.assertTrue(plot.startswith("Five years after the Battle of Endor"))
        # Must stop at the next heading, not run to the end of the article.
        self.assertNotIn("Luke Skywalker", plot)

    def test_missing_section_is_none(self) -> None:
        self.assertIsNone(wt.section(HEIR, {"gameplay"}))

    def test_lead_excludes_infobox_and_banners(self) -> None:
        lead = wt.lead(HEIR)
        self.assertIn("is a novel by Timothy Zahn", lead)
        self.assertNotIn("Bantam Spectra", lead)  # infobox content
        self.assertNotIn("9780553073270", lead)


class TestBalance(unittest.TestCase):
    def test_nested_templates_are_balanced(self) -> None:
        found = wt.find_infobox("{{Book|a={{X|{{Y|z}}}}|b=2}}", {"book"})
        assert found is not None
        self.assertEqual(found[1]["b"], "2")

    def test_unclosed_template_is_not_a_crash(self) -> None:
        self.assertIsNone(wt.find_infobox("{{Book|a=1", {"book"}))

    def test_absent_infobox_returns_none(self) -> None:
        self.assertIsNone(wt.find_infobox("plain text", {"book"}))


if __name__ == "__main__":
    unittest.main()
