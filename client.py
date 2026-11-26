"""Read only public Weekly Worker pages, checking access rules on every run."""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import time
from urllib.parse import urljoin, urlsplit

from protego import Protego
import requests


ORIGIN = "https://weeklyworker.co.uk"
BOT = "WeeklyWorkerRSS"
MIN_INTERVAL = 2.0


class MissingPage(RuntimeError):
    """A confirmed HTTP 404 or 410."""


class AccessDenied(RuntimeError):
    """A robots rule, denied request, or unsafe redirect stopped this request."""


class RetryLater(RuntimeError):
    def __init__(self, message, retry_at):
        super().__init__(message)
        self.retry_at = retry_at


def _retry_at(value, default_seconds):
    now = time.time()
    value = (value or "").strip()
    if value.isascii() and value.isdecimal():
        return now + int(value)
    if value:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(now, date.timestamp())
        except (OverflowError, ValueError, TypeError):
            pass
    return now + default_seconds


def _same_origin(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc.lower() not in (
        "weeklyworker.co.uk", "weeklyworker.co.uk:443"
    ):
        raise AccessDenied(f"Outside the source website: {url}")


class Client:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": f"{BOT}/1.0 (unofficial RSS reader)"})
        self.rules = None
        self.interval = MIN_INTERVAL
        self.last_request = None
        self.request_count = 0
        self.backoff = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.session.close()

    def _permit(self, url):
        if not self.rules.can_fetch(url, BOT):
            raise AccessDenied(f"robots.txt disallows {url}")
        visit = self.rules.visit_time(BOT)
        if visit and visit.start_time != visit.end_time:
            now = datetime.now(timezone.utc)
            clock = now.time()
            if visit.start_time < visit.end_time:
                allowed = visit.start_time <= clock < visit.end_time
            else:
                allowed = clock >= visit.start_time or clock < visit.end_time
            if not allowed:
                start = datetime.combine(now.date(), visit.start_time, timezone.utc)
                if start <= now:
                    start += timedelta(days=1)
                raise RetryLater("Outside the robots.txt Visit-time window", start.timestamp())

    def _request(self, url, headers, robots=False):
        for _ in range(6):
            _same_origin(url)
            if self.backoff and self.backoff.retry_at > time.time():
                raise self.backoff
            if self.last_request is not None:
                remaining = self.last_request + self.interval - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
            if not robots:
                self._permit(url)
            self.last_request = time.monotonic()
            self.request_count += 1
            response = self.session.get(url, headers=headers, timeout=(10, 30), allow_redirects=False)
            code = response.status_code
            if code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise RuntimeError(f"Redirect without a location at {url}")
                url = urljoin(url, location)
                headers = {}
                continue
            if code == 429 or 500 <= code <= 599:
                until = _retry_at(response.headers.get("Retry-After"), 21600 if code == 429 else 900)
                self.backoff = RetryLater(f"HTTP {code} at {url}", until)
                raise self.backoff
            if code in (401, 403):
                raise AccessDenied(f"HTTP {code} at {url}")
            if code in (404, 410):
                raise MissingPage(f"HTTP {code} at {url}")
            if code not in (200, 304):
                raise RuntimeError(f"Unexpected HTTP {code} at {url}")
            if code == 304 and not headers:
                raise RuntimeError(f"Unsolicited HTTP 304 at {url}")
            return response
        raise AccessDenied(f"Too many redirects at {url}")

    def _load_rules(self):
        try:
            response = self._request(f"{ORIGIN}/robots.txt", {}, robots=True)
        except MissingPage:
            content = ""
        else:
            content = response.content.decode("utf-8-sig", errors="replace")
            if content.lstrip().startswith("<"):
                raise AccessDenied("robots.txt returned markup instead of access rules")
        self.rules = Protego.parse(content)
        self.interval = max(self.interval, self.rules.crawl_delay(BOT) or 0)
        rate = self.rules.request_rate(BOT)
        if rate:
            self.interval = max(self.interval, rate.seconds / rate.requests)

    def get(self, url, validators=None):
        """Return (decoded document or None on 304, validators for the next request)."""
        _same_origin(url)
        if self.rules is None:
            self._load_rules()
        allowed = {"If-None-Match", "If-Modified-Since"}
        headers = {k: v for k, v in (validators or {}).items() if k in allowed and v}
        response = self._request(url, headers)
        fresh = dict(headers) if response.status_code == 304 else {}
        for response_header, request_header in (
            ("ETag", "If-None-Match"), ("Last-Modified", "If-Modified-Since")
        ):
            if value := response.headers.get(response_header):
                fresh[request_header] = value
        if response.status_code == 304:
            return None, fresh
        content_type = response.headers.get("Content-Type", "").lower()
        expected = {"text/html", "application/xhtml+xml"}
        if urlsplit(url).path == "/worker/rss/":
            expected = {"application/rss+xml", "application/xml", "text/xml"}
        if content_type.split(";")[0].strip() not in expected:
            raise RuntimeError(f"Unexpected content type at {url}: {content_type!r}")
        if "charset=" not in content_type:
            response.encoding = "utf-8"
        return response.text, fresh
