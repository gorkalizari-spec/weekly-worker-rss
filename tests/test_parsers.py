import unittest

from parsers import BASE, parse_archive, parse_article, parse_issue


class ParserTests(unittest.TestCase):
    issue = BASE + "/worker/1611/"
    summary = {"title": "Letters", "lead": "Thatcher again", "date": "2026-11-26"}

    def test_archive_follows_published_urls(self):
        html = """<main><section><h3><a href="/worker/1681/">Issue 1581</a></h3></section>
        <aside><a href="/worker/year/1994/">1994</a></aside></main>"""
        self.assertEqual(parse_archive(html), ([BASE + "/worker/1681/"], [BASE + "/worker/year/1994/"]))

    def test_issue_includes_image_lead_letters_and_supplement(self):
        html = """<main><section><h5>WW archive &gt; Issue 1611 - 26 November 2026</h5>
        <figure><a href="/worker/1611/lead/"><img></a></figure>
        <h1><a href="/worker/1611/lead/">Lead</a></h1><h2>Words with <em>style</em>.</h2>
        <h3><a href="/worker/1611/letters/">Letters</a></h3><p>Thatcher again</p>
        <h3><a href="/worker/1611a/book_01/">Supplement</a></h3><p></p>
        <h3><a href="/assets/ww/pdf/WW1611-WEB.pdf">PDF format</a></h3></section>
        <aside><a href="/worker/1610/old/">Old</a></aside></main>"""
        rows = parse_issue(html, self.issue)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[self.issue + "letters/"], self.summary)
        self.assertEqual(rows[self.issue + "lead/"]["lead"], "Words with style.")

    def test_pdf_and_template_error_are_distinct(self):
        html = '<main><section><h5>WW archive &gt; Issue 75 - 15 December 1994</h5>%s</section></main>'
        self.assertEqual(parse_issue(html % '<a href="/assets/ww/pdf/paper.pdf">PDF format</a>', self.issue), {})
        with self.assertRaises(ValueError):
            parse_issue(html % '<a href="/assets/">PDF format</a>', self.issue)

    def test_letters_reads_each_signature(self):
        html = """<main><section><h1>Letters</h1><h2>Thatcher again</h2><p>Copy <strong>bold</strong>.</p>
        <p><strong>Ian Spencer</strong><br>Durham</p><h2>N20 fash bash</h2>
        <p>Text.</p><p><strong>Tech Com</strong><br>email</p></section></main>"""
        item = parse_article(html, self.issue + "letters/", self.summary)
        self.assertEqual(item["authors"], ["Ian Spencer", "Tech Com"])
        self.assertEqual(item["date"], "2026-11-26")

    def test_metadata_scoped_to_article_and_its_byline(self):
        html = """<header><nav><a class="current" href="/worker/categories/party-programme/">Party &amp; Programme</a>
        </nav></header><main><article><h5>26.11.2026</h5><aside><h5>Categories:
        <a href="/worker/categories/stalinism/">Stalinism</a>
        <h5>More by: <a href="/worker/authors/mike-macnair/">Mike Macnair</a></h5></aside>
        <h1>Challenging false assumptions</h1><h2></h2><p>Opening words.</p>
        <a href="/worker/authors/other/">A quote</a></article><h4>More on
        <a href="/worker/categories/the-left/">The left</a></h4></main>"""
        item = parse_article(html, self.issue + "lead/", {"lead": ""})
        self.assertEqual(item["authors"], ["Mike Macnair"])
        self.assertEqual(item["sections"], {"party-programme": "Party & Programme"})
        self.assertEqual(item["categories"], {"stalinism": "Stalinism"})
        self.assertEqual((item["lead_source"], item["lead"]), ("excerpt", "Opening words."))

    def test_non_article_fails(self):
        with self.assertRaises(ValueError):
            parse_article("<main><h1>Unavailable</h1></main>", self.issue + "lead/", self.summary)
