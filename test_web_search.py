import os
import unittest
from unittest import mock

import tempfile

from web_search import (SearchError, check_web, html_to_text, load_env_file, make_search,
                        pick_queries, search_from_env)

PAGE_TEXT = (
    "Plagiarism is the representation of another person's language, thoughts, "
    "ideas, or expressions as one's own original work."
)
PAGES = {
    "https://example.com/copy": ("Copy", PAGE_TEXT),
    "https://example.com/other": ("Other", "Recipes for banana bread and other baked goods."),
}


def fake_search(query):
    return [("Copy", "https://example.com/copy"), ("Other", "https://example.com/other"),
            ("Broken", "https://example.com/broken")]


def fake_fetch(url):
    if url not in PAGES:
        raise OSError("unreachable")
    return PAGES[url]


class WebSearchTest(unittest.TestCase):
    def test_copied_text_found_on_web_with_link(self):
        saved = []
        report = check_web("He said that " + PAGE_TEXT, search=fake_search, fetch=fake_fetch,
                           on_page=lambda *a: saved.append(a[1]))
        self.assertTrue(report.found)
        self.assertEqual([m.url for m in report.matches], ["https://example.com/copy"])
        self.assertEqual(saved, ["https://example.com/copy"])

    def test_original_text_not_found(self):
        report = check_web("My own words about a trip to the mountains last summer with friends.",
                           search=fake_search, fetch=fake_fetch)
        self.assertFalse(report.found)

    def test_pick_queries_uses_longest_sentences_as_phrases(self):
        queries = pick_queries("Short one. This sentence is clearly the longest one in the text here. Tiny.")
        self.assertEqual(queries, ['"This sentence is clearly the longest one in the text here."'])

    def test_html_to_text_skips_scripts(self):
        title, text = html_to_text("<html><head><title>T</title><script>x=1</script></head>"
                                   "<body><p>Hello <b>world</b></p><script>bad()</script></body></html>")
        self.assertEqual(title, "T")
        self.assertEqual(text.split(), ["Hello", "world"])

    def test_google_preferred_and_missing_keys_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SearchError):
                search_from_env()
        env = {"GOOGLE_API_KEY": "g", "GOOGLE_CSE_ID": "c", "BRAVE_API_KEY": "b"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("web_search.google_search", return_value=[("t", "u")]) as g:
            self.assertEqual(search_from_env()("q"), [("t", "u")])
            g.assert_called_once_with("q", "g", "c")

    def test_make_search_prefers_passed_keys_over_env(self):
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "env", "GOOGLE_CSE_ID": "envcx"}, clear=True), \
                mock.patch("web_search.google_search", return_value=[]) as g:
            make_search("mine", "mycx")("q")
            g.assert_called_once_with("q", "mine", "mycx")

    def test_load_env_file_does_not_override_existing(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write('# comment\nGOOGLE_API_KEY="from-file"\nBRAVE_API_KEY=brave\n')
        try:
            with mock.patch.dict(os.environ, {"BRAVE_API_KEY": "already"}, clear=True):
                load_env_file(f.name)
                self.assertEqual(os.environ["GOOGLE_API_KEY"], "from-file")
                self.assertEqual(os.environ["BRAVE_API_KEY"], "already")
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
