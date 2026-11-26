"""Map editorial categories to sections using the newspaper's own navigation."""

from datetime import date, datetime, timezone
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from client import MissingPage, ORIGIN


CATEGORY_PATH = re.compile(r"/worker/categories/([\w-]+)/?")
REFRESH_DAYS = 28
# This published section is absent from the archive's navigation menu.
EXTRA_ROOT = {"cpgb-news": "CPGB News"}
# Its sidebar repeats the first menu section. Use the actual child breadcrumbs.
EXTRA_CHILDREN = {"events": "Events", "fighting-fund": "Fighting fund", "reports": "Reports"}


def links(anchors):
    result = {}
    for a in anchors:
        url = urlsplit(urljoin(ORIGIN, a["href"]))
        match = CATEGORY_PATH.fullmatch(url.path)
        name = a.get_text(" ", strip=True)
        if url.hostname in {"weeklyworker.co.uk", "www.weeklyworker.co.uk"} and match and name and not url.query:
            result[match[1]] = name
    return result


def parse_category(html, slug, name, in_menu):
    page = BeautifulSoup(html, "html.parser")
    heading = page.select_one("main > section > h5")
    if not heading:
        raise ValueError(f"Missing category breadcrumb for {slug}")
    parents = links(heading.select("a[href]"))
    label = heading.get_text(" ", strip=True).rsplit(">", 1)[-1].strip()
    if not label or label.casefold() != name.strip().casefold():
        raise ValueError(f"Unexpected category heading for {slug}: {label!r}")
    children = {}
    if in_menu:
        if parents:
            raise ValueError(f"Unexpected parent for menu section {slug}")
        sidebar = page.select_one("main > aside")
        caption = sidebar.select_one("h5") if sidebar else None
        if not caption or caption.get_text(strip=True).casefold() != "in this section":
            raise ValueError(f"Missing category navigation for {slug}")
        children = links(sidebar.select("nav a[href]"))
    return {"name": label, "parents": parents, "children": children}


def refresh_taxonomy(client, archive_html, previous, observed_categories=None):
    """Read the five menu sections and verify additional parents via breadcrumbs."""
    previous = previous or {}
    if archive_html is not None:
        archive = BeautifulSoup(archive_html, "html.parser")
        menu = links(archive.select("header nav a[href]"))
    else:
        menu = previous.get("menu", {})
    if not menu:
        raise ValueError("Archive has no thematic navigation")

    today = datetime.now(timezone.utc).date()
    roots = dict(menu)
    roots.update(EXTRA_ROOT)
    pages = {}

    def read(slug, name, in_menu):
        old = previous.get("pages", {}).get(slug, {})
        if old and old["name"] == name and old["in_menu"] == in_menu:
            age = (today - date.fromisoformat(old["checked"])).days
            if 0 <= age < REFRESH_DAYS:
                pages[slug] = old
                return
        validators = old.get("validators") if old.get("in_menu") == in_menu else None
        try:
            html, fresh = client.get(f"{ORIGIN}/worker/categories/{slug}/", validators)
        except MissingPage:
            if in_menu:
                raise
            record = {"name": name, "parents": {}, "children": {}, "missing": True}
            fresh = {}
        else:
            record = old.copy() if html is None else parse_category(html, slug, name, in_menu)
        record.update(validators=fresh, checked=today.isoformat(), in_menu=in_menu)
        pages[slug] = record

    for slug, name in roots.items():
        read(slug, name, slug in menu)

    known = set(roots)
    for page in pages.values():
        known.update(page["children"])
    additional = dict(EXTRA_CHILDREN)
    # Keep verified side branches when the current batch contains newer categories.
    additional.update({s: p["name"] for s, p in previous.get("pages", {}).items() if not p["in_menu"]})
    additional.update(observed_categories or {})
    pending = dict(sorted(additional.items()))
    while pending:
        slug, name = pending.popitem()
        if slug in known or slug in pages or slug == "letters" or not re.fullmatch(r"[\w-]+", slug):
            continue
        read(slug, name, False)
        pending.update(pages[slug]["parents"])

    roots = {
        slug: page["name"] for slug, page in pages.items()
        if not page["parents"] and not page.get("missing")
    }
    parents = {}
    for slug, page in pages.items():
        if slug in roots:
            for child in page["children"]:
                parents.setdefault(child, {})[slug] = roots[slug]

    def ancestor_roots(slug, visited):
        if slug in visited:
            raise ValueError(f"Cycle in category breadcrumbs at {slug}")
        if slug in roots:
            return {slug: roots[slug]}
        result = dict(parents.get(slug, {}))
        for parent in pages.get(slug, {}).get("parents", {}):
            result.update(ancestor_roots(parent, visited | {slug}))
        return result

    for slug, page in pages.items():
        if page["parents"]:
            parents[slug] = ancestor_roots(slug, set())
    return {"menu": menu, "roots": roots, "parents": parents, "pages": pages}


def apply_taxonomy(articles, taxonomy):
    """Recompute section assignments without changing editorial category labels."""
    roots = taxonomy["roots"]
    parents = taxonomy["parents"]
    for article in articles:
        source = article.setdefault("source_sections", dict(article["sections"]))
        sections = {}
        for category in article["categories"]:
            if category in roots:
                sections[category] = roots[category]
            sections.update(parents.get(category, {}))
        # Hidden sections can highlight the first unrelated menu entry. A
        # category's own breadcrumb or its section index takes precedence.
        article["sections"] = sections or dict(source)
    return dict(roots)
