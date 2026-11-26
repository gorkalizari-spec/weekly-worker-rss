import unittest
from unittest.mock import patch

from requests import Response

from client import AccessDenied, Client, MissingPage, ORIGIN, RetryLater


PAGE = ORIGIN + "/worker/100/example/"


def reply(status=200, content="", headers=None):
    response = Response()
    response.status_code = status
    response._content = content.encode()
    response.headers.update(headers or {"Content-Type": "text/html"})
    return response


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.addCleanup(self.client.session.close)
        self.get = self.enterContext(patch.object(self.client.session, "get"))
        self.sleep = self.enterContext(patch("client.time.sleep"))
        self.enterContext(patch("client.time.monotonic", return_value=1000))

    def test_conditional_validators_and_empty_robots(self):
        self.get.side_effect = [
            reply(content=""), reply(content="Café", headers={"Content-Type": "text/html", "ETag": '"abc"'}),
            reply(304, headers={"ETag": '"def"'}),
        ]
        html, validators = self.client.get(PAGE)
        self.assertEqual(html, "Café")
        self.assertEqual(self.client.get(PAGE, validators), (None, {"If-None-Match": '"def"'}))
        self.assertEqual(self.get.call_args.kwargs["headers"], {"If-None-Match": '"abc"'})
        self.assertFalse(self.get.call_args.kwargs["allow_redirects"])
        self.assertEqual(self.get.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_specific_allow_and_delay(self):
        self.get.side_effect = [
            reply(content="User-agent: *\nDisallow: /worker/*\nAllow: /worker/100/example/$\nCrawl-delay: 5\nRequest-rate: 2/20"),
            reply(),
        ]
        self.client.get(PAGE)
        self.sleep.assert_called_with(10)
        with self.assertRaises(AccessDenied):
            self.client.get(ORIGIN + "/worker/private/")
        self.assertEqual(self.get.call_count, 2)

    def test_redirect_rechecks_rules(self):
        self.get.side_effect = [
            reply(content="User-agent: *\nDisallow: /hidden"), reply(302, headers={"Location": "/hidden"}),
        ]
        with self.assertRaises(AccessDenied):
            self.client.get(PAGE)
        self.assertEqual(self.get.call_count, 2)

    def test_unsafe_redirect_rejected(self):
        self.get.side_effect = [reply(404), reply(301, headers={"Location": "https://example.net/feed/"})]
        with self.assertRaises(AccessDenied):
            self.client.get(PAGE)
        self.assertEqual(self.get.call_count, 2)

    def test_publisher_feed_accepts_rss_and_xml(self):
        types = ["application/rss+xml", "application/xml", "text/xml"]
        self.get.side_effect = [reply()] + [
            reply(content="<rss/>", headers={"Content-Type": mime}) for mime in types
        ]
        for mime in types:
            with self.subTest(mime=mime):
                self.assertEqual(self.client.get(ORIGIN + "/worker/rss/")[0], "<rss/>")

    def test_missing_article(self):
        self.get.side_effect = [reply(404), reply(410)]
        with self.assertRaises(MissingPage):
            self.client.get(PAGE)

    def test_unavailable_robots(self):
        self.get.side_effect = [reply(403)]
        with self.assertRaises(AccessDenied):
            self.client.get(PAGE)
        self.assertEqual(self.get.call_count, 1)

    def test_rate_limit_blocks_further_requests(self):
        self.enterContext(patch("client.time.time", return_value=100))
        self.get.side_effect = [reply(), reply(429, headers={"Retry-After": "3600"})]
        with self.assertRaises(RetryLater) as error:
            self.client.get(PAGE)
        self.assertEqual(error.exception.retry_at, 3700)
        with self.assertRaises(RetryLater):
            self.client.get(PAGE)
        self.assertEqual(self.get.call_count, 2)
