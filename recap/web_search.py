"""Web search step: find several *types* of websites, open them, and extract readable text.

The output feeds Gemini research (see gemini.research_notes), so the video script is
built from pages that were actually retrieved instead of from model memory.

Search providers (first one that works wins):
  1. Brave Search API   - when BRAVE_API_KEY is set
  2. DuckDuckGo HTML    - no key needed
  3. Bing HTML          - no key needed
"""
import base64
import binascii
import os
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import requests

import config as S

USER_AGENT = "Mozilla/5.0 (compatible; FestivalVideoStudio/1.0; +https://github.com/rishuwrites/festival-video-studio)"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
DDG_URL = "https://html.duckduckgo.com/html/"
BING_URL = "https://www.bing.com/search"
MAX_SITES = 7
MAX_PER_DOMAIN = 1
MAX_PAGE_CHARS = 3500
MIN_PAGE_CHARS = 300
MAX_PAGE_BYTES = 1_500_000
FETCH_TIMEOUT = 20

BLOCKED_DOMAINS = (
    "youtube.com", "youtu.be", "facebook.com", "instagram.com", "pinterest.",
    "twitter.com", "x.com", "reddit.com", "quora.com", "tiktok.com", "linkedin.com",
)

# Each website "type" gets its own query so the sources are diverse, not 7 copies of one blog.
SITE_TYPES = (
    ("panchang", "{topic} {date} date tithi puja muhurat drikpanchang"),
    ("reference", "{topic} significance history origin"),
    ("government_or_temple", "{topic} {date} official government OR temple tradition"),
    ("regional_customs", "{topic} Uttar Pradesh Bihar regional customs rituals"),
    ("hindi_news", "{topic} {date} पूजा विधि तिथि महत्व"),
)

# Domains that are usually reliable for festival facts; they are tried first.
PREFERRED_HINTS = (
    "drikpanchang.com", ".gov.in", "nic.in", "wikipedia.org", "britannica.com",
    "hindustantimes.com", "indiatoday.in", "timesofindia", "jagran.com",
    "amarujala.com", "bhaskar.com", "livehindustan.com", "thehindu.com",
)


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside", "iframe"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._skip_depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag in self.SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            text = data.strip()
            if len(text) > 2:
                self.parts.append(text)


class _BingResultParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self._in_result = False
        self._in_heading = False
        self._anchor = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "li" and "b_algo" in attrs.get("class", "").split():
            self._in_result = True
        elif self._in_result and tag == "h2":
            self._in_heading = True
        elif self._in_result and self._in_heading and tag == "a":
            self._anchor = {"url": attrs.get("href", ""), "title": []}

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor:
            title = re.sub(r"\s+", " ", "".join(self._anchor["title"])).strip()
            url = _bing_destination(self._anchor["url"])
            if title and _usable(url):
                self.results.append({"title": title, "url": url})
            self._anchor = None
        elif tag == "h2":
            self._in_heading = False
        elif tag == "li" and self._in_result:
            self._in_result = False

    def handle_data(self, data):
        if self._anchor:
            self._anchor["title"].append(data)


def extract_text(html_text):
    parser = _TextExtractor()
    try:
        parser.feed(html_text)
    except Exception:
        pass
    body = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return re.sub(r"\s+", " ", parser.title).strip(), body


def _domain(url):
    return urlparse(url).netloc.lower().removeprefix("www.")


def _usable(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    domain = _domain(url)
    return not any(blocked in domain for blocked in (*BLOCKED_DOMAINS, "bing.com", "duckduckgo.com"))


def _brave_search(query):
    key = os.getenv("BRAVE_API_KEY", "").strip()
    if not key:
        return []
    response = requests.get(
        BRAVE_URL,
        params={"q": query, "count": 10, "country": "IN", "safesearch": "moderate"},
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    items = (response.json().get("web") or {}).get("results", [])
    return [{"title": str(i.get("title") or ""), "url": str(i.get("url") or "")} for i in items]


def _ddg_search(query):
    response = requests.post(
        DDG_URL, data={"q": query, "kl": "in-en"}, headers={"User-Agent": USER_AGENT}, timeout=30,
    )
    response.raise_for_status()
    results = []
    for match in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', response.text, re.S
    ):
        href, title = match.group(1), re.sub(r"<[^>]+>", "", match.group(2))
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href if href.startswith("http") else "https:" + href).query).get("uddg", [""])[0])
        results.append({"title": re.sub(r"\s+", " ", title).strip(), "url": href})
    return results


def _bing_destination(url):
    parsed = urlparse(url)
    encoded = parse_qs(parsed.query).get("u", [""])[0] if parsed.hostname == "www.bing.com" else ""
    if not encoded.startswith("a1"):
        return url
    try:
        value = encoded[2:]
        value += "=" * (-len(value) % 4)
        return base64.b64decode(value, altchars=b"-_", validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return ""


def _bing_search(query):
    response = requests.get(
        BING_URL,
        params={"q": query, "setlang": "en", "cc": "IN"},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    parser = _BingResultParser()
    parser.feed(response.text)
    return parser.results


def search(query):
    """Return [{'title', 'url'}] from the first provider that answers."""
    for provider in (_brave_search, _ddg_search, _bing_search):
        try:
            results = provider(query)
        except requests.RequestException as exc:
            print(f"  web search via {provider.__name__.strip('_')} failed: {type(exc).__name__}")
            continue
        results = [r for r in results if _usable(r["url"])]
        if results:
            return results
    return []


def fetch_page(url):
    """Open one website and return (title, text) or None if it is unusable."""
    try:
        response = requests.get(
            url, headers={"User-Agent": USER_AGENT, "Accept-Language": "hi-IN,hi;q=0.9,en;q=0.8"},
            timeout=FETCH_TIMEOUT, stream=True,
        )
        response.raise_for_status()
        if "html" not in response.headers.get("Content-Type", "").lower():
            return None
        raw = response.raw.read(MAX_PAGE_BYTES, decode_content=True)
    except requests.RequestException:
        return None
    encoding = response.encoding or "utf-8"
    title, body = extract_text(raw.decode(encoding, errors="replace"))
    if len(body) < MIN_PAGE_CHARS:
        return None
    return title, body[:MAX_PAGE_CHARS]


def _rank(result):
    domain = _domain(result["url"])
    return 0 if any(hint in domain or domain.endswith(hint) for hint in PREFERRED_HINTS) else 1


def collect_pages(topic, date="", scope=S.DEFAULT_SCOPE):
    """Search each website type, open the best hits, and return page excerpts.

    Returns {"pages": [{"type", "title", "url", "text"}], "search_queries": [...]}.
    """
    queries, pages, seen_urls, domain_count = [], [], set(), {}
    for site_type, template in SITE_TYPES:
        query = re.sub(r"\s+", " ", template.format(topic=topic, date=date)).strip()
        queries.append(query)
        results = sorted(search(query), key=_rank)
        taken = 0
        for result in results[:8]:
            url, domain = result["url"], _domain(result["url"])
            if url in seen_urls or domain_count.get(domain, 0) >= MAX_PER_DOMAIN:
                continue
            seen_urls.add(url)
            page = fetch_page(url)
            if not page:
                continue
            title, text = page
            domain_count[domain] = domain_count.get(domain, 0) + 1
            pages.append({
                "type": site_type,
                "title": (title or result["title"] or domain)[:150],
                "url": url,
                "text": text,
            })
            print(f"  opened [{site_type}] {domain} | {(title or '')[:70]}")
            taken += 1
            if taken >= 2 or len(pages) >= MAX_SITES:
                break
        if len(pages) >= MAX_SITES:
            break
    return {"pages": pages, "search_queries": queries}
