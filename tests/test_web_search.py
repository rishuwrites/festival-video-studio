import base64
import os
import sys
import unittest
from urllib.parse import quote
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "recap"))

import festival_main
import gemini
import web_search

LONG = "धनतेरस कार्तिक कृष्ण त्रयोदशी को मनाया जाता है। " * 20


class WebSearchTests(unittest.TestCase):
    def test_extract_text_skips_scripts_and_keeps_title(self):
        title, body = web_search.extract_text(
            "<html><title>Dhanteras</title><script>var x=1;</script><p>" + LONG + "</p></html>"
        )
        self.assertEqual(title, "Dhanteras")
        self.assertNotIn("var x", body)
        self.assertIn("धनतेरस", body)

    def test_blocked_and_non_https_urls_are_rejected(self):
        self.assertFalse(web_search._usable("https://www.youtube.com/watch?v=1"))
        self.assertFalse(web_search._usable("http://drikpanchang.com/x"))
        self.assertFalse(web_search._usable("https://www.bing.com/search?q=festival"))
        self.assertTrue(web_search._usable("https://www.drikpanchang.com/x"))

    def test_bing_search_extracts_and_decodes_result_links(self):
        destination = "https://example.org/chhath"
        encoded = "a1" + base64.urlsafe_b64encode(destination.encode()).decode().rstrip("=")
        markup = (
            '<ol><li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u='
            + quote(encoded)
            + '">Chhath &amp; tradition</a></h2></li></ol>'
        )
        response = mock.Mock(status_code=200, text=markup)
        with mock.patch.object(web_search.requests, "get", return_value=response):
            self.assertEqual(
                web_search._bing_search("Chhath"),
                [{"title": "Chhath & tradition", "url": destination}],
            )

    def test_search_uses_bing_when_other_providers_return_no_results(self):
        results = [{"title": "Chhath", "url": "https://example.org/chhath"}]
        with mock.patch.object(web_search, "_brave_search", return_value=[]), \
                mock.patch.object(web_search, "_ddg_search", return_value=[]), \
                mock.patch.object(web_search, "_bing_search", return_value=results):
            self.assertEqual(web_search.search("Chhath"), results)

    def test_collect_pages_opens_one_page_per_domain_across_site_types(self):
        results = [
            {"title": "A", "url": "https://www.drikpanchang.com/a"},
            {"title": "A2", "url": "https://www.drikpanchang.com/b"},
            {"title": "W", "url": "https://en.wikipedia.org/wiki/Dhanteras"},
        ]
        with mock.patch.object(web_search, "search", return_value=results), \
                mock.patch.object(web_search, "fetch_page", return_value=("Title", LONG)):
            collected = web_search.collect_pages("Dhanteras", "2026")
        domains = [web_search._domain(page["url"]) for page in collected["pages"]]
        self.assertEqual(len(domains), len(set(domains)))
        self.assertGreaterEqual(len(collected["pages"]), 2)
        self.assertEqual(len(collected["search_queries"]), len(web_search.SITE_TYPES))

    def test_research_notes_requires_two_sites(self):
        with self.assertRaises(RuntimeError):
            gemini.research_notes("x", "", "India", {"pages": [{"title": "t", "url": "https://a.in", "type": "p", "text": LONG}]})

    def test_research_notes_falls_back_to_excerpts_without_gemini(self):
        pages = [
            {"title": "A", "url": "https://a.in/x", "type": "panchang", "text": LONG},
            {"title": "B", "url": "https://b.in/x", "type": "reference", "text": LONG},
        ]
        with mock.patch.dict(os.environ, {}, clear=True):
            result = gemini.research_notes("x", "", "India", {"pages": pages, "search_queries": ["q"]})
        self.assertEqual([s["title"] for s in result["sources"]], ["A", "B"])
        parsed = gemini._parse_web_research(result)
        self.assertEqual(len(parsed["sources"]), 2)

    def test_overlay_cleaning_and_source_domain(self):
        self.assertIsNone(festival_main._clean_overlay({"text": ""}))
        overlay = festival_main._clean_overlay({"label": "a b c d", "text": " ".join(["शब्द"] * 30), "source_title": "A"})
        self.assertEqual(len(overlay["label"].split()), 3)
        self.assertEqual(len(overlay["text"].split()), 16)
        scene = {"overlay": overlay}
        out = festival_main._overlay_for_scene(scene, [{"title": "A", "url": "https://www.drikpanchang.com/a"}])
        self.assertEqual(out["source"], "drikpanchang.com")


if __name__ == "__main__":
    unittest.main()
