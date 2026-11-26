from datetime import timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import xml.etree.ElementTree as ET

from render import DC, SITE, render


class RenderTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.output = Path(temp.name)
        self.sections = {"society-culture": "Society & Culture", "other": "Other"}
        self.article = {
            "title": "Research & debate", "url": SITE + "/worker/1611/research/",
            "date": "2026-11-26", "lead": "With <angles> & commas.",
            "authors": ["Alice", "Bob", "Alice"],
            "sections": {"society-culture": "Society & Culture"},
            "categories": {"child": "Books"},
        }

    def items(self, name):
        return ET.parse(self.output / f"{name}.xml").findall("./channel/item")

    def test_all_items_and_matching_subsets(self):
        anonymous = dict(self.article, url=SITE + "/worker/1600/letters/", date="2026-10-01",
                         title="Letters", authors=[], sections={}, categories={}, lead="")
        render([anonymous, self.article, self.article], self.sections, self.output)
        first, second = self.items("general")
        self.assertEqual(first.findtext("guid"), self.article["url"])
        self.assertEqual(first.find("guid").attrib["isPermaLink"], "true")
        self.assertEqual(first.findtext("link"), first.findtext("guid"))
        self.assertEqual(first.findtext("title"), self.article["title"])
        self.assertEqual(unescape(first.findtext("description")), self.article["lead"])
        instant = parsedate_to_datetime(first.findtext("pubDate"))
        self.assertEqual(instant.date().isoformat(), self.article["date"])
        self.assertEqual(instant.utcoffset(), timedelta(0))
        self.assertEqual([a.text for a in first.findall(f"{{{DC}}}creator")], ["Alice", "Bob"])
        self.assertEqual([c.text for c in first.findall("category")], ["Books", "Society & Culture"])
        self.assertIsNone(second.find("description"))
        self.assertEqual(second.findall(f"{{{DC}}}creator"), [])
        self.assertEqual(len(self.items("society-culture")), 1)
        self.assertEqual(self.items("other"), [])

    def test_order_independent_and_stable(self):
        same_day = dict(self.article, url=SITE + "/worker/1611/another/")
        render([self.article, same_day], self.sections, self.output)
        expected = (self.output / "general.xml").read_bytes()
        render([same_day, self.article], self.sections, self.output)
        self.assertEqual((self.output / "general.xml").read_bytes(), expected)

    def test_bad_input_preserves_previous_feeds(self):
        render([self.article], self.sections, self.output)
        expected = (self.output / "general.xml").read_bytes()
        for articles, sections in [
            ([], {}),
            ([self.article, dict(self.article, title="Changed")], self.sections),
            ([self.article], {"../outside": "Outside"}),
            ([dict(self.article, date="unknown")], self.sections),
            ([dict(self.article, url="https://other.example/x")], self.sections),
        ]:
            with self.subTest(articles=articles, sections=sections):
                with self.assertRaises(ValueError):
                    render(articles, sections, self.output)
                self.assertEqual((self.output / "general.xml").read_bytes(), expected)
