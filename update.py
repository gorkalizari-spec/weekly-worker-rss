"""Update public RSS feeds from Weekly Worker's feed and the printed issue indexes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from time import time
import xml.etree.ElementTree as ET

from client import Client, MissingPage, ORIGIN, RetryLater
from parsers import parse_archive, parse_issue, parse_article
from render import render
from taxonomy import refresh_taxonomy, apply_taxonomy

ARCHIVE = ORIGIN + "/worker/"
RSS = ARCHIVE + "rss/"
DAY = 86400


def official_items(xml):
    root = ET.fromstring(xml)
    entries = {}
    for item in root.findall("./channel/item"):
        link = (item.findtext("link") or "").strip()
        if not re.fullmatch(re.escape(ARCHIVE) + r"[^/?#]+/[^/?#]+/", link):
            raise ValueError(f"Unexpected article link in official RSS: {link}")
        entries[link] = {"title": item.findtext("title") or "", "lead": ""}
    if not entries:
        raise ValueError("Official RSS contains no entries")
    return entries


def persisted(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def as_list(*groups):
    return list(dict.fromkeys(item for group in groups for item in group))


def discover(client, state, now, errors, year_limit):
    try:
        xml, validators = client.get(RSS, state.get("rss_validators"))
        if xml is not None:
            state["official"] = official_items(xml)
        state["rss_validators"] = validators
    except (MissingPage, ET.ParseError, ValueError) as error:
        errors.append(f"{RSS}: {error}")
        state.setdefault("official", {})
    archive, _ = client.get(ARCHIVE)
    recent, year_urls = parse_archive(archive)
    if not recent or not year_urls:
        raise ValueError("Archive lacks issue links or annual indexes")
    years = state.setdefault("years", {})
    # One annual index per run covers both interruptions and retrospective digitisation.
    ordered_years = sorted(year_urls, key=lambda url: years.get(url, {}).get("checked", 0))
    for year in ordered_years[:year_limit]:
        previous = years.get(year, {})
        if now - previous.get("checked", 0) < 30 * DAY:
            break
        try:
            html, validators = client.get(year, previous.get("validators"))
            links = previous["links"] if html is None else parse_archive(html)[0]
            years[year] = {"checked": now, "validators": validators, "links": links}
        except (MissingPage, ValueError) as error:
            errors.append(f"{year}: {error}")
            years[year] = {**previous, "checked": now, "links": previous.get("links", []),
                           "error": str(error)}
    official_issues = [url.rsplit("/", 2)[0] + "/" for url in state["official"]]
    history = [url for year in year_urls for url in years.get(year, {}).get("links", [])]
    state["known"] = as_list(recent, official_issues, history, state.get("known", []))
    return archive, as_list(recent[:1], official_issues)


def worklist(state, current, now, budget):
    issues = state["issues"]
    current = [url for url in current if issues.get(url, {}).get("retry", 0) <= now]
    backlog = [url for url in state["known"] if url not in current
               and not issues.get(url, {}).get("complete")
               and issues.get(url, {}).get("retry", 0) <= now]
    # Re-read a recently superseded issue daily and rotate through older issues.
    recent = [url for url in state["known"][:5] if url not in current
              and issues.get(url, {}).get("complete")
              and issues[url]["checked"] <= now - DAY]
    stale = [url for url, page in issues.items() if page.get("complete")
             and page["checked"] <= now - 90 * DAY]
    stale.sort(key=lambda url: issues[url]["checked"])
    untouched = [url for url in backlog if url not in issues]
    retries = sorted((url for url in backlog if url in issues), key=lambda u: issues[u].get("retry", 0))
    batch = as_list(untouched[:1], retries[:1], untouched, retries)[:budget]
    return as_list(current, batch, recent[:1], stale[:1])


def update_issue(client, state, issue, now, errors):
    page = state["issues"].get(issue, {})
    articles = state["articles"]
    # Refresh individual metadata periodically even when its listing has not changed.
    refresh_details = now - page.get("details_checked", 0) >= 90 * DAY
    extras = {u: s for u, s in state["official"].items() if u.rsplit("/", 2)[0] + "/" == issue}
    conditional = page.get("complete") and not refresh_details and extras.keys() <= page.get("items", {}).keys()
    html, validators = client.get(issue, page.get("validators") if conditional else None)
    if html is None:
        page.update(checked=now, validators=validators)
        return
    listings = parse_issue(html, issue)
    listings = {**extras, **listings}
    previous = page.get("items", {})
    completed = {}
    for url, summary in listings.items():
        fingerprint = hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest()[:24]
        old = previous.get(url, {})
        if refresh_details or url not in articles or old.get("signature") != fingerprint:
            try:
                # A changed index can carry a corrected standfirst even if article HTML is unchanged.
                cache = old.get("validators") if old.get("signature") == fingerprint and url in articles else None
                body, check = client.get(url, cache)
                if body is not None:
                    articles[url] = parse_article(body, url, summary)
                old = {"signature": fingerprint, "validators": check}
            except (MissingPage, ValueError) as error:
                errors.append(f"{url}: {error}")
                continue
        completed[url] = old
    complete = len(completed) == len(listings)
    state["issues"][issue] = {
        "checked": now, "details_checked": now if refresh_details else page["details_checked"],
        "complete": complete, "validators": validators, "items": completed,
        "retry": 0 if complete else now + (5 * 3600 if issue in state["known"][:2] else DAY)
    }


def run(client, directory, now, budget, year_limit=1):
    folder = directory / "state"
    path = folder / "catalogue.json"
    state = persisted(path, {"version": 1, "issues": {}, "articles": {}})
    if state.get("version") != 1:
        raise ValueError("Unsupported catalogue format")
    cooldown = folder / "retry.json"
    if persisted(cooldown, {}).get("after", 0) > now:
        print("Waiting until the source's Retry-After has elapsed.")
        return
    errors = []
    try:
        archive, current = discover(client, state, now, errors, year_limit)
        for issue in worklist(state, current, now, budget):
            try:
                update_issue(client, state, issue, now, errors)
            except (MissingPage, ValueError) as error:
                errors.append(f"{issue}: {error}")
                state["issues"].setdefault(issue, {}).update(complete=False, retry=now + DAY)
        categories = {k: v for a in state["articles"].values() for k, v in a["categories"].items()}
        taxonomy = refresh_taxonomy(client, archive, state.get("taxonomy", {}), categories)
    except RetryLater as error:
        save(cooldown, {"after": error.retry_at})
        raise
    state["taxonomy"] = taxonomy
    articles = [dict(item) for item in state["articles"].values()]
    sections = apply_taxonomy(articles, taxonomy)
    render(articles, sections, directory / "feeds")
    save(path, state)
    save(folder / "coverage.json", {
        "articles": len(articles), "sections": sections, "discovered_issues": len(state["known"]),
        "complete_issues": sum(bool(v.get("complete")) for v in state["issues"].values()),
        "annual_indexes_checked": sum("error" not in y for y in state["years"].values()),
        "pending_issues": [url for url in state["known"] if not state["issues"].get(url, {}).get("complete")],
        "errors_this_run": errors,
    })
    cooldown.unlink(missing_ok=True)
    print(f"{len(articles)} articles, {len(sections)} sections, {client.request_count} HTTP requests.")
    for error in errors:
        print(f"::warning::{error}", file=sys.stderr)
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill", type=int, default=2, choices=range(0, 11), metavar="0..10",
                        help="Number of additional unprocessed issues per run (default: 2)")
    parser.add_argument("--annual-indexes", type=int, default=1, choices=range(1, 51), metavar="1..50",
                        help="Annual indexes to check, spaced by the same rate limiter")
    args = parser.parse_args()
    with Client() as client:
        errors = run(client, Path(__file__).resolve().parent, int(time()), args.backfill, args.annual_indexes)
    sys.exit(2 if errors else 0)
