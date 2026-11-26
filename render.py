"""Generate deterministic RSS 2.0 documents from the collected article metadata."""

from collections import defaultdict
from datetime import date, datetime, time, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


SITE = "https://weeklyworker.co.uk"
DC = "http://purl.org/dc/elements/1.1/"
ET.register_namespace("dc", DC)
# XML 1.0 permits tab, newline, carriage return and the printable Unicode ranges.
INVALID_XML = re.compile(r"[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def _text(parent, tag, value):
    ET.SubElement(parent, tag).text = INVALID_XML.sub("", value)


def _document(articles, section_name, link):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    name = f"Weekly Worker — {section_name}" if section_name else "Weekly Worker"
    _text(channel, "title", f"{name} (unofficial)")
    _text(channel, "link", link)
    _text(channel, "description", f"Unofficial RSS feed of articles published by {name}.")
    _text(channel, "language", "en")
    _text(channel, "ttl", "360")

    for article in articles:
        item = ET.SubElement(channel, "item")
        _text(item, "title", article["title"])
        _text(item, "link", article["url"])
        ET.SubElement(item, "guid", isPermaLink="true").text = article["url"]
        # The paper gives a calendar date. RSS requires a time as well.
        published = datetime.combine(date.fromisoformat(article["date"]), time.min, timezone.utc)
        _text(item, "pubDate", format_datetime(published, usegmt=True))
        if article["lead"]:
            # RSS descriptions contain encoded HTML, including when displaying plain text.
            _text(item, "description", escape(article["lead"], quote=False))
        for author in dict.fromkeys(article["authors"]):
            _text(item, f"{{{DC}}}creator", author)
        names = set(article["sections"].values()) | set(article["categories"].values())
        for category in sorted(names):
            _text(item, "category", category)

    ET.indent(rss)
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True) + b"\n"


def render(articles, sections, output):
    """Write general.xml and a feed per top-level section under output."""
    by_url = {}
    section_names = dict(sections)
    for article in articles:
        url = article["url"]
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.netloc != "weeklyworker.co.uk"
                or not parts.path.startswith("/worker/") or parts.query or parts.fragment
                or INVALID_XML.search(url)):
            raise ValueError(f"Unexpected article permalink: {url!r}")
        if not article["title"].strip():
            raise ValueError(f"Empty title: {url}")
        if url in by_url and by_url[url] != article:
            raise ValueError(f"Conflicting metadata for {url}")
        by_url[url] = article
        for slug, name in article["sections"].items():
            section_names.setdefault(slug, name)

    if not by_url:
        raise ValueError("No articles to publish")
    for slug in section_names:
        if slug == "general" or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise ValueError(f"Invalid section slug: {slug!r}")

    # A permanent secondary sort key keeps ties stable between data imports.
    ordered = sorted(by_url.values(), key=lambda a: (-date.fromisoformat(a["date"]).toordinal(), a["url"]))
    groups = defaultdict(list)
    for article in ordered:
        for slug in article["sections"]:
            groups[slug].append(article)

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output) as temporary:
        staging = Path(temporary)
        (staging / "general.xml").write_bytes(_document(ordered, None, SITE + "/"))
        for slug, name in sorted(section_names.items()):
            link = f"{SITE}/worker/categories/{slug}/"
            (staging / f"{slug}.xml").write_bytes(_document(groups[slug], name, link))
        for path in sorted(staging.iterdir()):
            path.replace(output / path.name)
