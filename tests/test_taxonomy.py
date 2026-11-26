import unittest
from unittest.mock import Mock

from taxonomy import apply_taxonomy, parse_category, refresh_taxonomy


def link(slug, name):
    return f'<a href="/worker/categories/{slug}/">{name}</a>'


def page(breadcrumb, sidebar):
    return (f'<main><section><h5>{breadcrumb}</h5></section><aside>'
            f'<h5>In this section</h5><nav>{sidebar}</nav></aside></main>')


class TaxonomyTests(unittest.TestCase):
    def setUp(self):
        menu = link("democracy-state", "Democracy &amp; State")
        self.archive = f"<header><nav>{menu}</nav></header>"
        self.html = {
            "democracy-state": page("Democracy &amp; State", link("stalinism", "Stalinism")),
            "cpgb-news": page("CPGB News", link("the-left", "The left")),
        }
        for slug, name in (("events", "Events"), ("reports", "Reports"), ("fighting-fund", "Fighting fund")):
            self.html[slug] = page(link("cpgb-news", "CPGB News") + " &gt; " + name, "")
        self.client = Mock()
        self.client.get.side_effect = lambda url, _: (self.html[url.split("/")[-2]], {"If-None-Match": '"v1"'})

    def test_breadcrumbs_and_actual_sections(self):
        mapping = refresh_taxonomy(self.client, self.archive, {})
        self.assertNotIn("the-left", mapping["parents"])
        articles = [
            {"sections": {"party-programme": "Party & Programme"}, "categories": {"events": "Events"}},
            {"sections": {}, "categories": {"cpgb-news": "CPGB News", "stalinism": "Stalinism"}},
            {"sections": {}, "categories": {"letters": "Letters"}},
            {"sections": {"society-culture": "Society & Culture"}, "categories": {}},
        ]
        sections = apply_taxonomy(articles, mapping)
        self.assertEqual(set(sections), {"cpgb-news", "democracy-state"})
        self.assertEqual(set(articles[0]["sections"]), {"cpgb-news"})
        self.assertEqual(set(articles[1]["sections"]), set(sections))
        self.assertFalse(articles[2]["sections"])
        self.assertEqual(set(articles[3]["sections"]), {"society-culture"})

    def test_cache_and_newly_observed_category(self):
        first = refresh_taxonomy(self.client, self.archive, {})
        self.assertEqual(self.client.get.call_count, 5)
        self.client.get.reset_mock()
        self.assertEqual(first, refresh_taxonomy(self.client, None, first))
        self.client.get.assert_not_called()
        self.html["new"] = page(link("cpgb-news", "CPGB News") + " &gt; New", "")
        refreshed = refresh_taxonomy(self.client, self.archive, first, {"new": "New"})
        self.assertEqual(self.client.get.call_count, 1)
        self.assertEqual(refreshed["parents"]["new"], {"cpgb-news": "CPGB News"})

    def test_follows_breadcrumb_to_previously_unlisted_section(self):
        self.html.update({
            "topic": page(link("branch", "Branch") + " &gt; Topic", ""),
            "branch": page(link("new-root", "New root") + " &gt; Branch", ""),
            "new-root": page("New root", link("spurious", "Spurious")),
        })
        data = refresh_taxonomy(self.client, self.archive, {}, {"topic": "Topic"})
        self.assertEqual(data["parents"]["topic"], {"new-root": "New root"})
        self.assertEqual(data["roots"]["new-root"], "New root")
        self.assertNotIn("spurious", data["parents"])

    def test_revalidates_only_expired_pages(self):
        first = refresh_taxonomy(self.client, self.archive, {})
        first["pages"]["cpgb-news"]["checked"] = "2020-01-01"
        self.client.get.reset_mock()
        self.client.get.side_effect = lambda url, validators: (None, validators)
        updated = refresh_taxonomy(self.client, self.archive, first)
        self.assertEqual(updated["parents"], first["parents"])
        self.client.get.assert_called_once_with(
            "https://weeklyworker.co.uk/worker/categories/cpgb-news/", {"If-None-Match": '"v1"'})

    def test_parse_rejects_wrong_page(self):
        with self.assertRaises(ValueError):
            parse_category(page("Another section", ""), "democracy-state", "Democracy & State", True)
        with self.assertRaises(ValueError):
            parse_category("<main/>", "events", "Events", False)
