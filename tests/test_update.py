"""Exercise consecutive update runs against a small journal with a real issue layout."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from requests.exceptions import ConnectionError

from client import MissingPage
from update import ARCHIVE, RSS, run


CURRENT = ARCHIVE + "1611/"
EARLIER = ARCHIVE + "1610/"
YEAR = ARCHIVE + "year/2026/"
NEWS = CURRENT + "news/"
LETTERS = CURRENT + "letters/"
OLD_NEWS = EARLIER + "old-article/"
SECTION = "society-culture"
CATEGORY = ARCHIVE + f"categories/{SECTION}/"
HEADER = f'<header><nav><a href="{CATEGORY}" class="current">Society &amp; Culture</a></nav></header>'
START = 1_800_000_000
SIX_HOURS = 6 * 3600


def archive(issues):
    rows = "".join(f'<h3><a href="{u}">Issue {u.split("/")[-2]}</a></h3>' for u in issues)
    return f'{HEADER}<main><section>{rows}</section><aside><a href="{YEAR}">2026</a></aside></main>'


def issue(number, day, urls):
    rows = "".join(f'<h3><a href="{u}">{title}</a></h3><p>{title} summary</p>' for u, title in urls)
    return f'<main><section><h5>WW archive &gt; Issue {number} - {day} November 2026</h5>{rows}</section></main>'


def article(title, day):
    return f'''{HEADER}<main><article><h5>{day}.11.2026</h5>
        <aside><a href="{CATEGORY}">Society &amp; Culture</a>
        <a href="/worker/authors/author/">Story author</a></aside>
        <h1>{title}</h1><h2>{title} summary</h2></article></main>'''


class Journal:
    def __init__(self):
        self.calls = []
        self.data = {
            RSS: f'<rss><channel><item><link>{NEWS}</link><title>News</title></item></channel></rss>',
            ARCHIVE: archive([CURRENT]), YEAR: archive([CURRENT, EARLIER]),
            CURRENT: issue(1611, 26, [(NEWS, "News"), (LETTERS, "Letters")]),
            EARLIER: issue(1610, 19, [(OLD_NEWS, "Old article")]),
            NEWS: article("News", 26), OLD_NEWS: article("Old article", 19),
            LETTERS: '<main><section><h1>Letters</h1><h2>Comment</h2><p>A letter.</p>'
                     '<p><strong>Correspondent</strong><br>London</p></section></main>',
            CATEGORY: '<main><section><h5>Society &amp; Culture</h5></section>'
                      '<aside><h5>In this section</h5><nav></nav></aside></main>',
        }

    @property
    def request_count(self):
        return len(self.calls)

    def get(self, url, validators=None):
        self.calls.append(url)
        if url not in self.data:
            raise MissingPage(f"404 {url}")
        result = self.data[url]
        if isinstance(result, Exception):
            raise result
        return result, {}  # The production site frequently sends no cache validators.


class UpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.journal = Journal()

    def update(self, now=START, budget=0):
        self.journal.calls.clear()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return run(self.journal, self.directory, now, budget)

    def urls(self, name="general"):
        doc = ET.parse(self.directory / "feeds" / (name + ".xml"))
        return [e.text for e in doc.findall("./channel/item/guid")]

    def state(self):
        return json.loads((self.directory / "state" / "catalogue.json").read_bytes())

    def test_letters_complement_official_rss_and_rechecks_do_not_refetch_details(self):
        self.assertFalse(self.update())
        self.assertCountEqual(self.urls(), [NEWS, LETTERS])
        self.assertEqual(self.urls(SECTION), [NEWS])
        before = (self.directory / "feeds" / "general.xml").read_bytes()
        self.assertFalse(self.update(START + SIX_HOURS))
        self.assertIn(CURRENT, self.journal.calls)
        self.assertNotIn(NEWS, self.journal.calls)
        self.assertNotIn(LETTERS, self.journal.calls)
        self.assertEqual((self.directory / "feeds" / "general.xml").read_bytes(), before)

    def test_backfill_resumes_from_an_annual_index_with_no_duplicate_urls(self):
        self.assertFalse(self.update())
        self.assertNotIn(OLD_NEWS, self.journal.calls)
        self.assertIn(EARLIER, self.state()["known"])
        self.assertFalse(self.update(START + SIX_HOURS, budget=1))
        self.assertEqual(self.journal.calls.count(OLD_NEWS), 1)
        self.assertCountEqual(self.urls(), [NEWS, LETTERS, OLD_NEWS])
        self.assertFalse(self.update(START + 2 * SIX_HOURS, budget=1))
        self.assertNotIn(OLD_NEWS, self.journal.calls)
        self.assertTrue(self.state()["issues"][EARLIER]["complete"])

    def test_partial_issue_is_saved_and_missing_article_is_retried(self):
        saved = self.journal.data.pop(LETTERS)
        self.assertTrue(self.update())
        self.assertEqual(self.urls(), [NEWS])
        self.assertFalse(self.state()["issues"][CURRENT]["complete"])
        self.journal.data[LETTERS] = saved
        self.assertFalse(self.update(START + SIX_HOURS))
        self.assertEqual(self.journal.calls.count(LETTERS), 1)
        self.assertNotIn(NEWS, self.journal.calls)
        self.assertTrue(self.state()["issues"][CURRENT]["complete"])
        self.assertCountEqual(self.urls(), [NEWS, LETTERS])

    def test_network_interruption_keeps_last_successful_files_and_resumes(self):
        self.assertFalse(self.update())
        original = {p: p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        saved = self.journal.data[OLD_NEWS]
        self.journal.data[OLD_NEWS] = ConnectionError("disconnected")
        with self.assertRaises(ConnectionError):
            self.update(START + SIX_HOURS, budget=1)
        for path, contents in original.items():
            self.assertEqual(path.read_bytes(), contents)
        self.journal.data[OLD_NEWS] = saved
        self.assertFalse(self.update(START + 2 * SIX_HOURS, budget=1))
        self.assertCountEqual(self.urls(), [NEWS, LETTERS, OLD_NEWS])
