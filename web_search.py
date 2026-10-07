"""Check text against the web.

Picks a few distinctive sentences from the text, searches for them with a web
search API, downloads the result pages and scores each one with the same
shingle comparison used for the local database.

Supported search providers. Supply your own key for one of them, either in a
.env file (see .env.example), as environment variables, or in the web page:
  - Google Programmable Search:  GOOGLE_API_KEY and GOOGLE_CSE_ID (used first)
  - Brave Search API:            BRAVE_API_KEY
"""

import json
import os
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from plagiarism_checker import Match, Report, shingles, tokenize

USER_AGENT = "Mozilla/5.0 (compatible; PlagiarismChecker/1.0)"
TIMEOUT = 10
MAX_PAGE_BYTES = 2_000_000
MAX_QUERY_WORDS = 30  # search engines ignore words beyond ~32


class SearchError(Exception):
    pass


def _get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read(MAX_PAGE_BYTES), resp.headers.get_content_charset() or "utf-8"


def brave_search(query, api_key, count=5):
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
        {"q": query, "count": count}
    )
    body, _ = _get(url, {"Accept": "application/json", "X-Subscription-Token": api_key})
    results = json.loads(body).get("web", {}).get("results", [])
    return [(r["title"], r["url"]) for r in results]


def google_search(query, api_key, cse_id, count=5):
    url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(
        {"key": api_key, "cx": cse_id, "q": query, "num": count}
    )
    body, _ = _get(url)
    return [(r["title"], r["link"]) for r in json.loads(body).get("items", [])]


def load_env_file(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")):
    """Load KEY=value lines from a .env file into the environment.

    Existing environment variables win. The .env file is git-ignored, so keys
    put there are never committed.
    """
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def make_search(google_api_key=None, google_cse_id=None, brave_api_key=None):
    """Return a search(query) function using the given keys.

    Keys not given are taken from the environment (or a .env file).
    Google is used when both of its keys are available, otherwise Brave.
    """
    google_api_key = google_api_key or os.environ.get("GOOGLE_API_KEY")
    google_cse_id = google_cse_id or os.environ.get("GOOGLE_CSE_ID")
    brave_api_key = brave_api_key or os.environ.get("BRAVE_API_KEY")
    if google_api_key and google_cse_id:
        return lambda q: google_search(q, google_api_key, google_cse_id)
    if brave_api_key:
        return lambda q: brave_search(q, brave_api_key)
    raise SearchError(
        "No web search API key set. Add your Google API key and Search engine ID "
        "(or a Brave key) in the page's API keys section or in a .env file. See README."
    )


def search_from_env():
    return make_search()


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "head", "nav", "footer", "svg"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html):
    parser = _TextExtractor()
    parser.feed(html)
    return parser.title.strip(), " ".join(parser.parts)


def fetch_page(url):
    """Download a page and return (title, text)."""
    body, charset = _get(url)
    return html_to_text(body.decode(charset, errors="replace"))


def pick_queries(text, max_queries=3):
    """Choose the longest sentences as search queries, as exact phrases."""
    sentences = [s.split() for s in re.split(r"(?<=[.!?])\s+|\n+", text)]
    sentences = [s for s in sentences if len(s) >= 6] or [text.split()]
    sentences.sort(key=len, reverse=True)
    queries = []
    for words in sentences[:max_queries]:
        phrase = " ".join(words[:MAX_QUERY_WORDS]).replace('"', "")
        queries.append(f'"{phrase}"')
    return queries


def score(query_words, page_words):
    """Percent of the checked text found in the page."""
    query = shingles(query_words)
    if not query:
        phrase = " " + " ".join(query_words) + " "
        return 100.0 if phrase in " " + " ".join(page_words) + " " else 0.0
    return 100.0 * len(query & shingles(page_words)) / len(query)


def check_web(text, threshold=30.0, search=None, fetch=fetch_page, max_queries=3, on_page=None):
    """Search the web for the text and return a Report of matching pages.

    on_page(title, url, page_text) is called for every page that matches,
    e.g. to save it into the local database.
    """
    words = tokenize(text)
    if not words:
        return Report(False, [], "on the web")
    search = search or search_from_env()

    candidates = {}
    for q in pick_queries(text, max_queries):
        for title, url in search(q):
            candidates.setdefault(url, title)

    matches = []
    for url, title in candidates.items():
        try:
            page_title, page_text = fetch(url)
        except Exception:
            continue  # unreachable page, timeout, blocked, ...
        s = score(words, tokenize(page_text))
        if s >= threshold:
            matches.append(Match(title or page_title or url, url, round(s, 1)))
            if on_page:
                on_page(title or page_title or url, url, page_text)
    matches.sort(key=lambda m: m.score, reverse=True)
    return Report(bool(matches), matches, "on the web")
