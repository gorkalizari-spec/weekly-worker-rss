"""Read the public archive, edition indexes and article templates of Weekly Worker."""

from datetime import datetime
import re
import textwrap
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


BASE = "https://weeklyworker.co.uk"
MONTHS = {name: i for i, name in enumerate(
    "January February March April May June July August September October November December".split(), 1
)}


def _text(tag):
    if tag is None:
        return ""
    return " ".join(tag.get_text().split())


def _path(href):
    url = urlsplit(urljoin(BASE + "/", href))
    if url.scheme not in {"https", "http"} or url.hostname not in {"weeklyworker.co.uk", "www.weeklyworker.co.uk"}:
        return ""
    return "/" + url.path.strip("/")


def parse_archive(html):
    soup = BeautifulSoup(html, "html.parser")
    issues = []
    for a in soup.select("main section a[href]"):
        path = _path(a["href"])
        if re.match(r"^Issue\s", _text(a), re.I):
            if not re.fullmatch(r"/worker/[^/]+", path):
                raise ValueError(f"Unexpected edition link: {a['href']}")
            issues.append(BASE + path + "/")
    years = []
    for a in soup.select("main aside a[href]"):
        path = _path(a["href"])
        if re.fullmatch(r"/worker/year/[0-9]{4}", path):
            years.append(BASE + path + "/")
    if not issues:
        raise ValueError("No editions found in the archive listing")
    return list(dict.fromkeys(issues)), list(dict.fromkeys(years))


def parse_issue(html, issue_url):
    soup = BeautifulSoup(html, "html.parser")
    section = soup.select_one("main section")
    if section is None:
        raise ValueError(f"Missing edition index in {issue_url}")
    heading = _text(section.find("h5"))
    match = re.search(r"\bIssue\s+.+?\s*[-–]\s*(\d{1,2})\s+(\w+)\s+(\d{4})", heading)
    if not match or match[2] not in MONTHS:
        raise ValueError(f"Unrecognised edition date in {issue_url}: {heading}")
    date = datetime(int(match[3]), MONTHS[match[2]], int(match[1])).date().isoformat()
    rows = {}
    pdf = False
    # Include the lead image, text links and letters. The Recent issues sidebar
    # and footer are outside the edition section.
    for a in section.select("a[href]"):
        path = _path(a["href"])
        if path.startswith("/assets/") and path.lower().endswith(".pdf"):
            pdf = True
            continue
        if not re.fullmatch(r"/worker/[^/]+/[^/]+", path):
            if a.find_parent(["h1", "h2", "h3", "h4"]) and _text(a).lower() != "pdf format":
                raise ValueError(f"Unknown entry in {issue_url}: {a['href']}")
            continue
        url = BASE + path + "/"
        row = rows.setdefault(url, {"title": "", "lead": "", "date": date})
        if _text(a):
            row["title"] = _text(a)
            title = a.find_parent(["h1", "h2", "h3", "h4"])
            sibling = title.find_next_sibling() if title else None
            if sibling and sibling.name in {"p", "h2"}:
                row["lead"] = _text(sibling)
    if not rows and not pdf:
        raise ValueError(f"Edition has no recognised articles or PDF: {issue_url}")
    return rows


def _categories(links):
    result = {}
    for a in links:
        path = _path(a["href"])
        if re.fullmatch(r"/worker/categories/[^/]+", path) and _text(a):
            result[path.rsplit("/", 1)[1]] = _text(a)
    return result


def _letters(section, url, summary):
    # One stable URL per edition, with one editorial heading per letter.
    authors = []
    for title in section.find_all("h2", recursive=False):
        last_paragraph = None
        for sibling in title.next_siblings:
            if sibling.name == "h2":
                break
            if sibling.name == "p":
                last_paragraph = sibling
        if last_paragraph:
            author = last_paragraph.find("strong", recursive=False)
            if author and _text(author) and last_paragraph.find() == author:
                authors.append(_text(author))
    lead = summary["lead"] or "; ".join(_text(h) for h in section.find_all("h2", recursive=False))
    return {"url": url, "title": _text(section.h1), "date": summary["date"],
            "lead": lead, "lead_source": "editorial" if lead else "none",
            "authors": list(dict.fromkeys(authors)), "sections": {}, "categories": {"letters": "Letters"}}


def parse_article(html, url, summary):
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("main article")
    if article is None:
        section = soup.select_one("main section")
        if section and _text(section.h1) == "Letters" and _path(url).endswith("/letters"):
            return _letters(section, url, summary)
        raise ValueError(f"Unrecognised article template at {url}")
    title = _text(article.find("h1", recursive=False))
    if not title:
        raise ValueError(f"Missing article title at {url}")
    date_label = _text(article.find("h5", recursive=False))
    date = datetime.strptime(date_label, "%d.%m.%Y").date().isoformat()
    heading = article.find("h2", recursive=False)
    lead = _text(heading) or summary["lead"]
    source = "editorial" if lead else "none"
    if not lead:
        paragraph = article.find("p", recursive=False)
        lead = textwrap.shorten(_text(paragraph), width=280, placeholder="…")
        if lead:
            source = "excerpt"
    authors = []
    for a in article.select("aside a[href]"):
        if re.fullmatch(r"/worker/authors/[^/]+", _path(a["href"])) and _text(a):
            authors.append(_text(a))
    return {
        "url": url, "title": title, "date": date, "lead": lead, "lead_source": source,
        "authors": list(dict.fromkeys(authors)),
        "sections": _categories(soup.select("header nav a.current[href]")),
        "categories": _categories(article.select("aside a[href]")),
    }
