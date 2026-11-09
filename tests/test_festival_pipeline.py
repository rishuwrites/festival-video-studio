import os
import sys
import json
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "recap"))

import festival_main
import gemini
import festival_sources


DEFAULT_SCOPE = "India (nationwide, with focus on Uttar Pradesh and Bihar)"


def festival_research(scene_count=6):
    scenes = [
        {
            "title": f"दृश्य {index}",
            "narration": f"इस पर्व से जुड़ी जानकारी {index}। " + "महत्वपूर्ण जानकारी और परंपराओं के बारे में सरल व्याख्या। " * 20,
            "emotion": "happy",
            "visual_prompt": "A respectful Indian festival scene with lamps",
        }
        for index in range(scene_count)
    ]
    video_sources = [
        {
            "title": f"Video {index}",
            "url": f"https://www.youtube.com/watch?v=video{index}",
            "channel_id": f"channel{index}",
            "kind": "video_transcript",
        }
        for index in range(5)
    ]
    web_sources = [
        {"title": f"Web source {index}", "url": f"https://example.org/source{index}", "kind": "grounded_web"}
        for index in range(2)
    ]
    return {
        "research": {
            "headline": "पर्व की पूरी जानकारी",
            "thumbnail_text": "पर्व कब है",
            "hook": "यह पर्व कब मनाया जाता है?",
            "research_summary": "तिथि पंचांग और स्थान के अनुसार बदल सकती है।",
            "key_facts": [{"claim": "तिथि स्थान के अनुसार बदल सकती है।", "source_titles": ["Video 0"]}],
            "keywords": ["पर्व की तिथि", "festival date"],
            "scenes": scenes,
        },
        "sources": video_sources + web_sources,
        "search_queries": ["festival date"],
    }


def video_source_inputs():
    return [
        {
            "video_id": f"video{index}",
            "title": f"Title {index}",
            "channel": f"Channel {index}",
            "channel_id": f"channel{index}",
            "url": f"https://www.youtube.com/watch?v=video{index}",
            "language": "Hindi",
            "transcript_word_count": 5,
            "transcript": f"Transcript text {index}",
        }
        for index in range(5)
    ]


class GroundedFestivalResearchTests(unittest.TestCase):
    def test_lists_stable_flash_models_before_lite_and_excludes_omni_and_preview(self):
        response = mock.Mock()
        response.json.return_value = {
            "models": [
                {"name": "models/gemini-3.1-flash-lite", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3.5-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-omni-1.1-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-4-flash-preview", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3-flash-exp", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-2.5-flash-image", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3.5-flash", "supportedGenerationMethods": ["embedContent"]},
            ],
        }
        response.raise_for_status.return_value = None

        with mock.patch.object(gemini, "MODEL", "gemini-3.8-flash"), \
                mock.patch.object(gemini.requests, "get", return_value=response):
            models = gemini.list_models("test-key")

        self.assertEqual(models, [
            "gemini-3.8-flash",
            "gemini-flash-latest",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-4-flash-preview",
        ])
        self.assertNotIn("gemini-2.5-flash", models)

    def test_extracts_unique_https_sources_and_search_queries(self):
        response = {
            "candidates": [{
                "content": {"parts": [{"text": '{"headline":"उत्सव"}'}]},
                "groundingMetadata": {
                    "webSearchQueries": ["festival date 2026"],
                    "groundingChunks": [
                        {"web": {"title": "Panchang", "uri": "https://example.org/date"}},
                        {"web": {"title": "Duplicate", "uri": "https://example.org/date"}},
                        {"web": {"title": "Unsafe", "uri": "http://example.org/unsafe"}},
                    ],
                },
            }],
        }

        result = gemini.extract_grounded_research(response)

        self.assertEqual(result["research"]["headline"], "उत्सव")
        self.assertEqual(result["sources"], [
            {"title": "Panchang", "url": "https://example.org/date"},
        ])
        self.assertEqual(result["search_queries"], ["festival date 2026"])

    def test_festival_research_enables_google_search_grounding(self):
        payload = {
            "candidates": [{
                "content": {"parts": [{"text": '{"headline":"उत्सव"}'}]},
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"title": "Source 1", "uri": "https://example.org/1"}},
                        {"web": {"title": "Source 2", "uri": "https://example.org/2"}},
                    ],
                },
            }],
        }
        response = mock.Mock(status_code=200)
        response.json.return_value = payload
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                mock.patch.object(gemini, "list_models", return_value=["gemini-test"]), \
                mock.patch.object(gemini.requests, "post", return_value=response) as post:
            result = gemini.research_festival(
                "दिवाली", "2026", DEFAULT_SCOPE, video_sources=video_source_inputs(),
            )

        self.assertEqual(len(result["sources"]), 7)
        self.assertEqual(result["research_method"], "gemini_google_search_grounded")
        self.assertEqual(len([s for s in result["sources"] if s["kind"] == "video_transcript"]), 5)
        request = post.call_args.kwargs["json"]
        self.assertEqual(request["tools"], [{"googleSearch": {}}])
        prompt = request["contents"][0]["parts"][0]["text"]
        self.assertIn("Uttar Pradesh and Bihar", prompt)
        self.assertIn("nationwide", prompt)
        self.assertIn("one city's exact muhurta as applying nationwide", prompt)
        self.assertIn("Transcript text 4", prompt)
        self.assertIn("do not reproduce", prompt)

    def test_pre_researched_web_context_uses_plain_gemini_generation(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {
            "candidates": [{
                "content": {"parts": [{
                    "text": '{"headline":"धनतेरस","thumbnail_text":"धनतेरस कब और कैसे मनाएं आज"}',
                }]},
            }],
        }
        sources = [
            {"title": "Drik Panchang 2026 Dhanteras timings", "url": "https://example.org/panchang"},
            {"title": "Dhanteras customs", "url": "https://example.org/customs"},
        ]
        context = json.dumps({
            "notes": ["New Delhi observes Dhanteras on November 6, 2026."],
            "sources": sources,
            "search_queries": ["Dhanteras 2026 date"],
        })
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                mock.patch.object(gemini, "list_models", return_value=["gemini-test"]), \
                mock.patch.object(gemini.requests, "post", return_value=response) as post:
            result = gemini.research_festival(
                "धनतेरस", "2026", DEFAULT_SCOPE, video_sources=[], web_research=context,
            )

        request = post.call_args.kwargs["json"]
        prompt = request["contents"][0]["parts"][0]["text"]
        self.assertNotIn("tools", request)
        self.assertEqual(request["generationConfig"]["responseMimeType"], "application/json")
        self.assertIn("New Delhi observes Dhanteras on November 6, 2026.", prompt)
        self.assertEqual(result["research"]["headline"], "धनतेरस")
        self.assertEqual(result["research"]["thumbnail_text"], "धनतेरस कब और कैसे मनाएं")
        self.assertEqual(result["research_method"], "provided_web_research")
        self.assertEqual(result["search_queries"], ["Dhanteras 2026 date"])
        self.assertTrue(all(source["kind"] == "web_research" for source in result["sources"]))

    def test_pre_researched_web_context_requires_two_https_sources(self):
        context = json.dumps({
            "notes": "Festival notes",
            "sources": [{"title": "Only source", "url": "https://example.org/source"}],
        })
        with self.assertRaisesRegex(ValueError, "at least two sources"):
            gemini._parse_web_research(context)

    def test_festival_research_supports_web_only_mode_without_claiming_transcripts(self):
        payload = {
            "candidates": [{
                "content": {"parts": [{"text": '{"headline":"उत्सव"}'}]},
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"title": "Source 1", "uri": "https://example.org/1"}},
                        {"web": {"title": "Source 2", "uri": "https://example.org/2"}},
                    ],
                },
            }],
        }
        response = mock.Mock(status_code=200)
        response.json.return_value = payload
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                mock.patch.object(gemini, "list_models", return_value=["gemini-test"]), \
                mock.patch.object(gemini.requests, "post", return_value=response) as post:
            result = gemini.research_festival("छठ पूजा", "2026", DEFAULT_SCOPE, video_sources=[])

        request = post.call_args.kwargs["json"]
        prompt = request["contents"][0]["parts"][0]["text"]
        self.assertEqual(request["tools"], [{"googleSearch": {}}])
        self.assertIn("one Gemini API request", prompt)
        self.assertIn("do not search or fetch pages with a separate browser", prompt)
        self.assertIn("If no transcripts are supplied, do not claim or imply that video transcripts were analyzed", prompt)
        self.assertNotIn("Transcript text", prompt)
        self.assertEqual(len(result["sources"]), 2)
        self.assertTrue(all(source["kind"] == "grounded_web" for source in result["sources"]))

    def test_rejects_research_without_two_grounded_sources(self):
        payload = {
            "candidates": [{
                "content": {"parts": [{"text": '{"headline":"उत्सव"}'}]},
                "groundingMetadata": {"groundingChunks": []},
            }],
        }
        response = mock.Mock(status_code=200)
        response.json.return_value = payload
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                mock.patch.object(gemini, "list_models", return_value=["gemini-test"]), \
                mock.patch.object(gemini.requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "fewer than two usable Google Search citations"):
                gemini.research_festival(
                    "दिवाली", "2026", "India", video_sources=video_source_inputs(),
                )

    def test_reports_gemini_quota_exhaustion_reason(self):
        response = mock.Mock(status_code=429)
        response.json.return_value = {
            "error": {
                "status": "RESOURCE_EXHAUSTED",
                "message": "You exceeded your current quota.",
            },
        }
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                mock.patch.object(gemini, "list_models", return_value=["gemini-test"]), \
                mock.patch.object(gemini.time, "sleep"), \
                mock.patch.object(gemini.requests, "post", return_value=response):
            with self.assertRaisesRegex(
                RuntimeError, "RESOURCE_EXHAUSTED: You exceeded your current quota",
            ):
                gemini.research_festival("दिवाली", "2026", "India", video_sources=[])

    def test_retries_with_backup_key_after_primary_quota_exhaustion(self):
        quota_response = mock.Mock(status_code=429)
        quota_response.json.return_value = {
            "error": {"status": "RESOURCE_EXHAUSTED", "message": "quota exceeded"},
        }
        success_response = mock.Mock(status_code=200)
        success_response.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": '{"headline":"छठ पूजा"}'}]},
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"title": "Source 1", "uri": "https://example.org/1"}},
                        {"web": {"title": "Source 2", "uri": "https://example.org/2"}},
                    ],
                },
            }],
        }
        with mock.patch.dict(os.environ, {
            "GEMINI_API_KEY": "primary-key",
            "GEMINI_API_KEY1": "backup-key",
        }, clear=True), \
                mock.patch.object(gemini, "list_models", return_value=["gemini-test"]), \
                mock.patch.object(
                    gemini.requests, "post",
                    side_effect=[quota_response, success_response],
                ) as post:
            result = gemini.research_festival("छठ पूजा", "2026", "India", video_sources=[])

        self.assertEqual([call.kwargs["params"]["key"] for call in post.call_args_list], [
            "primary-key", "backup-key",
        ])
        self.assertEqual(len(result["sources"]), 2)

    def test_retries_transient_gemini_errors_after_backoff(self):
        quota_response = mock.Mock(status_code=503)
        success_response = mock.Mock(status_code=200)
        success_response.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": '{"headline":"छठ पूजा"}'}]},
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"title": "Source 1", "uri": "https://example.org/1"}},
                        {"web": {"title": "Source 2", "uri": "https://example.org/2"}},
                    ],
                },
            }],
        }
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=True), \
                mock.patch.object(gemini, "list_models", return_value=["gemini-test"]), \
                mock.patch.object(
                    gemini.requests, "post",
                    side_effect=[quota_response, success_response],
                ) as post, \
                mock.patch.object(gemini.time, "sleep") as sleep:
            result = gemini.research_festival("छठ पूजा", "2026", "India", video_sources=[])

        self.assertEqual(len(result["sources"]), 2)
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(30)

    def test_requires_five_distinct_transcribed_channels(self):
        sources = video_source_inputs()
        sources[-1]["channel_id"] = sources[0]["channel_id"]
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            with self.assertRaisesRegex(RuntimeError, "five distinct channels"):
                gemini.research_festival("दिवाली", video_sources=sources)


class RelatedVideoTranscriptTests(unittest.TestCase):
    class FakeTranscript:
        language = "Hindi"

        def __init__(self, text):
            self.snippets = [type("Snippet", (), {"text": text})()]

    class FakeTranscriptApi:
        def __init__(self, failures=()):
            self.failures = set(failures)
            self.requested = []

        def fetch(self, video_id, languages):
            self.requested.append((video_id, languages))
            if video_id in self.failures:
                raise RuntimeError("captions unavailable")
            return RelatedVideoTranscriptTests.FakeTranscript(f"Useful transcript for {video_id}.")

    @staticmethod
    def results(channel_numbers):
        return [
            {
                "id": {"videoId": f"video{index}"},
                "snippet": {
                    "channelId": f"channel{index}",
                    "channelTitle": f"Channel {index}",
                    "title": f"Festival video {index}",
                },
            }
            for index in channel_numbers
        ]

    def test_collects_five_captioned_videos_from_distinct_channels(self):
        client = self.FakeTranscriptApi()
        with mock.patch.dict(os.environ, {"YT_API_KEY": "test-api-key"}), \
                mock.patch.object(festival_sources, "_transcript_client", return_value=client), \
                mock.patch.object(festival_sources, "_search_results", return_value=self.results(range(6))):
            sources = festival_sources.find_transcribed_videos("दीवाली", "2026", DEFAULT_SCOPE)

        self.assertEqual(len(sources), 5)
        self.assertEqual(len({source["channel_id"] for source in sources}), 5)
        self.assertEqual(sources[0]["transcript"], "Useful transcript for video0.")
        self.assertEqual(client.requested[0][1], ["hi", "en"])

    def test_skips_videos_without_captions_and_searches_again(self):
        client = self.FakeTranscriptApi(failures={"video0", "video1"})
        responses = [self.results(range(4)), self.results(range(4, 9))]
        with mock.patch.dict(os.environ, {"YT_API_KEY": "test-api-key"}), \
                mock.patch.object(festival_sources, "_transcript_client", return_value=client), \
                mock.patch.object(festival_sources, "_search_results", side_effect=responses):
            sources = festival_sources.find_transcribed_videos("दीवाली", "2026", "India")

        self.assertEqual(len(sources), 5)
        self.assertNotIn("video0", {source["video_id"] for source in sources})

    def test_second_search_explicitly_covers_up_bihar_and_eastern_regions(self):
        client = self.FakeTranscriptApi()
        search_responses = [self.results(range(2)), self.results(range(2, 5))]
        with mock.patch.dict(os.environ, {"YT_API_KEY": "test-api-key"}), \
                mock.patch.object(festival_sources, "_transcript_client", return_value=client), \
                mock.patch.object(festival_sources, "_search_results", side_effect=search_responses) as search:
            sources = festival_sources.find_transcribed_videos("दीवाली", "2026")

        self.assertEqual(len(sources), 5)
        self.assertIn("India festival date", search.call_args_list[0].args[1])
        regional_query = search.call_args_list[1].args[1]
        self.assertIn("Uttar Pradesh Bihar", regional_query)
        self.assertIn("Bhojpuri Maithili", regional_query)

    def test_fails_when_fewer_than_five_channels_have_captions(self):
        client = self.FakeTranscriptApi(failures={"video0", "video1", "video2"})
        with mock.patch.dict(os.environ, {"YT_API_KEY": "test-api-key"}), \
                mock.patch.object(festival_sources, "_transcript_client", return_value=client), \
                mock.patch.object(festival_sources, "_search_results", return_value=self.results(range(4))):
            with self.assertRaisesRegex(RuntimeError, "found 1"):
                festival_sources.find_transcribed_videos("दीवाली", "2026", "India")

    def test_pipeline_research_uses_gemini_without_external_context_or_transcripts(self):
        expected = {"research": {}, "sources": [], "search_queries": []}
        with mock.patch.object(
            festival_main.gemini, "research_festival", return_value=expected,
        ) as research:
            result = festival_main._research_with_gemini("छठ पूजा", "2026", DEFAULT_SCOPE)

        self.assertIs(result, expected)
        research.assert_called_once_with("छठ पूजा", "2026", DEFAULT_SCOPE, video_sources=[])

    def test_existing_oauth_secrets_authorize_youtube_search(self):
        oauth_response = mock.Mock(status_code=200)
        oauth_response.json.return_value = {"access_token": "temporary-access-token"}
        transcript_client = self.FakeTranscriptApi()
        with mock.patch.dict(os.environ, {
            "YT_CLIENT_ID": "existing-client-id",
            "YT_CLIENT_SECRET": "existing-client-secret",
            "YT_REFRESH_TOKEN": "existing-refresh-token",
        }, clear=True), \
                mock.patch.object(festival_sources.requests, "post", return_value=oauth_response) as post, \
                mock.patch.object(festival_sources, "_transcript_client", return_value=transcript_client), \
                mock.patch.object(
                    festival_sources, "_search_results", return_value=self.results(range(5)),
                ) as search:
            sources = festival_sources.find_transcribed_videos("दीवाली", "2026")

        self.assertEqual(len(sources), 5)
        self.assertEqual(post.call_args.args[0], festival_sources.GOOGLE_TOKEN_URL)
        self.assertEqual(post.call_args.kwargs["data"], {
            "client_id": "existing-client-id",
            "client_secret": "existing-client-secret",
            "refresh_token": "existing-refresh-token",
            "grant_type": "refresh_token",
        })
        self.assertEqual(search.call_args.kwargs["access_token"], "temporary-access-token")
        self.assertIsNone(search.call_args.args[0])

    def test_oauth_search_reports_readonly_scope_requirement(self):
        oauth_response = mock.Mock(status_code=200)
        oauth_response.json.return_value = {"access_token": "temporary-access-token"}
        failed_search = mock.Mock(status_code=403)
        failed_search.raise_for_status.side_effect = festival_sources.requests.HTTPError("forbidden")
        failed_search.json.return_value = {
            "error": {"errors": [{"reason": "insufficientPermissions"}]},
        }
        with mock.patch.object(festival_sources.requests, "get", return_value=failed_search):
            with self.assertRaisesRegex(RuntimeError, "insufficientPermissions.*youtube.readonly"):
                festival_sources._search_results(None, "festival", access_token="temporary-access-token")

    def test_oauth_refresh_failure_does_not_disclose_credentials(self):
        failed_response = mock.Mock(status_code=400)
        with mock.patch.dict(os.environ, {
            "YT_CLIENT_ID": "client-id",
            "YT_CLIENT_SECRET": "do-not-log-this-secret",
            "YT_REFRESH_TOKEN": "do-not-log-this-refresh-token",
        }, clear=True), \
                mock.patch.object(festival_sources.requests, "post", return_value=failed_response):
            with self.assertRaisesRegex(RuntimeError, "HTTP 400") as error:
                festival_sources._oauth_access_token()

        self.assertNotIn("do-not-log-this-secret", str(error.exception))
        self.assertNotIn("do-not-log-this-refresh-token", str(error.exception))


class FestivalValidationTests(unittest.TestCase):
    def test_scene_image_count_keeps_shots_within_five_seconds(self):
        self.assertEqual(festival_main._scene_image_count(1), 1)
        self.assertEqual(festival_main._scene_image_count(5), 1)
        self.assertEqual(festival_main._scene_image_count(5.1), 2)
        self.assertEqual(festival_main._scene_image_count(15), 3)

    def test_shot_prompts_request_distinct_compositions_for_same_scene(self):
        scene = {"visual_prompt": "A family lighting diyas"}

        first = festival_main._shot_prompt(scene, 0, 3)
        second = festival_main._shot_prompt(scene, 1, 3)

        self.assertIn("wide establishing composition", first)
        self.assertIn("medium composition", second)
        self.assertIn("Keep the same scene", first)

    def test_default_scope_covers_india_and_highlights_up_bihar(self):
        self.assertEqual(festival_main.S.DEFAULT_SCOPE, DEFAULT_SCOPE)
        self.assertEqual(festival_main.generate_video.__defaults__[1], DEFAULT_SCOPE)

    def test_accepts_complete_source_grounded_script(self):
        research = festival_main.validate_research(festival_research(scene_count=9))

        self.assertEqual(len(research["scenes"]), 9)

    def test_accepts_web_grounded_script_without_video_transcripts(self):
        result = festival_research(scene_count=9)
        result["sources"] = [source for source in result["sources"] if source["kind"] == "grounded_web"]
        result["research"]["key_facts"][0]["source_titles"] = ["Web source 0"]

        research = festival_main.validate_research(result)

        self.assertEqual(len(research["scenes"]), 9)

    def test_rejects_insufficient_scenes_or_sources(self):
        with self.assertRaisesRegex(ValueError, "9-12 scenes"):
            festival_main.validate_research(festival_research(scene_count=5))

        result = festival_research(scene_count=9)
        result["sources"] = []
        with self.assertRaisesRegex(ValueError, "two web research source citations"):
            festival_main.validate_research(result)

        result = festival_research(scene_count=9)
        result["sources"] = [s for s in result["sources"] if s["kind"] == "grounded_web"]
        result["research"]["key_facts"][0]["source_titles"] = ["Web source 0"]
        result["sources"] = [
            source for source in result["sources"]
        ] + [
            source for source in festival_research(scene_count=9)["sources"]
            if source["kind"] == "video_transcript"
        ][:4]
        with self.assertRaisesRegex(ValueError, "five distinct channels"):
            festival_main.validate_research(result)

    def test_rejects_invalid_emotion(self):
        result = festival_research(scene_count=9)
        result["research"]["scenes"][0]["emotion"] = "fear"

        with self.assertRaisesRegex(ValueError, "unsupported emotion"):
            festival_main.validate_research(result)

    def test_rejects_sources_without_secure_urls_and_long_thumbnail_copy(self):
        result = festival_research(scene_count=9)
        result["sources"][0]["url"] = "http://example.org/video"
        with self.assertRaisesRegex(ValueError, "HTTPS URL"):
            festival_main.validate_research(result)

        result = festival_research(scene_count=9)
        result["research"]["thumbnail_text"] = "यह एक बहुत लंबा थंबनेल शीर्षक है"
        with self.assertRaisesRegex(ValueError, "5 words"):
            festival_main.validate_research(result)

    def test_rejects_script_that_is_too_short_for_six_minutes(self):
        result = festival_research(scene_count=9)
        for scene in result["research"]["scenes"]:
            scene["narration"] = "छोटा पाठ।"

        with self.assertRaisesRegex(ValueError, "at least 800 words"):
            festival_main.validate_research(result)

    def test_requires_actual_synthesized_audio_of_at_least_six_minutes(self):
        with self.assertRaisesRegex(ValueError, "at least 360 seconds"):
            festival_main.validate_narration_duration(359.99)
        festival_main.validate_narration_duration(360)

    def test_hindi_topics_get_deterministic_distinct_output_slugs(self):
        first = festival_main._safe_slug("दीपावली")
        second = festival_main._safe_slug("धनतेरस")

        self.assertNotEqual(first, second)
        self.assertTrue(first.startswith("festival-"))


if __name__ == "__main__":
    unittest.main()
