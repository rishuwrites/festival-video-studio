import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "recap"))

import facebook_upload


IST = ZoneInfo("Asia/Kolkata")


class FacebookScheduledUploadTests(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {
            "FACEBOOK_PAGE_ID": "page123",
            "FACEBOOK_PAGE_ACCESS_TOKEN": "page-secret",
            "META_GRAPH_API_VERSION": "v27.0",
        }, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    @staticmethod
    def response(payload, status=200):
        response = mock.Mock(status_code=status)
        response.json.return_value = payload
        response.text = ""
        return response

    def test_uploads_resumably_and_schedules_page_video_at_requested_ist_time(self):
        publish_at = datetime(2027, 1, 15, 18, 30, tzinfo=IST)
        video = b"video-content"
        start = self.response({
            "upload_session_id": "session123",
            "video_id": "facebook-video123",
            "start_offset": "0",
            "end_offset": str(len(video)),
        })
        uploaded = self.response({
            "start_offset": str(len(video)),
            "end_offset": str(len(video)),
        })
        published = self.response({"success": True})

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "festival.mp4"
            thumbnail_path = Path(folder) / "facebook-thumbnail.jpg"
            path.write_bytes(video)
            thumbnail_path.write_bytes(b"jpeg-thumbnail")
            with mock.patch.object(
                facebook_upload.requests, "post",
                side_effect=[start, uploaded, published],
            ) as post:
                result = facebook_upload.upload_scheduled(
                    str(path),
                    "छठ पूजा 2027",
                    "स्रोत-आधारित वीडियो विवरण",
                    "2027-01-15",
                    "18:30",
                    now=datetime(2027, 1, 15, 10, 0, tzinfo=IST),
                    thumbnail_path=str(thumbnail_path),
                )

        self.assertEqual(result, {
            "video_id": "facebook-video123",
            "url": "https://www.facebook.com/page123/videos/facebook-video123",
            "publish_at_ist": "2027-01-15 18:30 IST",
            "status": "scheduled_public",
        })
        self.assertEqual(post.call_count, 3)
        endpoint = "https://graph-video.facebook.com/v27.0/page123/videos"
        self.assertEqual(
            post.call_args_list[0].args[0],
            endpoint,
        )
        self.assertEqual(
            post.call_args_list[1].args[0],
            endpoint,
        )
        self.assertEqual(
            post.call_args_list[0].kwargs["data"],
            {
                "upload_phase": "start",
                "file_size": str(len(video)),
                "access_token": "page-secret",
            },
        )
        transfer = post.call_args_list[1].kwargs
        self.assertEqual(transfer["data"]["upload_phase"], "transfer")
        self.assertEqual(transfer["data"]["upload_session_id"], "session123")
        self.assertEqual(transfer["data"]["start_offset"], "0")
        self.assertEqual(
            transfer["files"]["video_file_chunk"][1],
            video,
        )
        finish_call = post.call_args_list[2]
        self.assertEqual(finish_call.args[0], endpoint)
        finish = finish_call.kwargs
        self.assertEqual(finish["data"]["upload_phase"], "finish")
        self.assertEqual(finish["data"]["upload_session_id"], "session123")
        self.assertEqual(finish["data"]["access_token"], "page-secret")
        self.assertEqual(finish["data"]["published"], "false")
        self.assertEqual(
            finish["data"]["scheduled_publish_time"],
            str(int(publish_at.timestamp())),
        )
        self.assertEqual(
            finish["files"]["thumb"][0],
            "facebook-thumbnail.jpg",
        )
        self.assertEqual(finish["files"]["thumb"][2], "image/jpeg")

    def test_page_token_is_the_only_facebook_upload_credential_required(self):
        responses = [
            self.response({
                "upload_session_id": "session123",
                "video_id": "facebook-video123",
            }),
            self.response({}),
            self.response({"success": True}),
        ]
        with mock.patch.dict(os.environ, {
            "FACEBOOK_PAGE_ID": "page123",
            "FACEBOOK_PAGE_ACCESS_TOKEN": "page-secret",
        }, clear=True):
            with mock.patch.object(
                facebook_upload.requests,
                "post",
                side_effect=responses,
            ) as post:
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / "festival.mp4"
                    path.write_bytes(b"video-content")
                    facebook_upload.upload_scheduled(
                        str(path),
                        "Title",
                        "Description",
                        "2027-01-15",
                        "18:30",
                        now=datetime(2027, 1, 15, 10, 0, tzinfo=IST),
                    )

        self.assertEqual(post.call_count, 3)

    def test_transfers_multiple_chunks_using_server_offsets(self):
        video = b"0123456789"
        responses = [
            self.response({
                "upload_session_id": "session123",
                "video_id": "facebook-video123",
                "start_offset": "0",
                "end_offset": "4",
            }),
            self.response({"start_offset": "4", "end_offset": "7"}),
            self.response({"start_offset": "7", "end_offset": "10"}),
            self.response({"start_offset": "10", "end_offset": "10"}),
            self.response({"success": True}),
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "festival.mp4"
            path.write_bytes(video)
            with mock.patch.object(
                facebook_upload.requests,
                "post",
                side_effect=responses,
            ) as post:
                facebook_upload.upload_scheduled(
                    str(path),
                    "Title",
                    "Description",
                    "2027-01-15",
                    "18:30",
                    now=datetime(2027, 1, 15, 10, 0, tzinfo=IST),
                )

        self.assertEqual(
            [call.kwargs["files"]["video_file_chunk"][1] for call in post.call_args_list[1:4]],
            [b"0123", b"456", b"789"],
        )
        self.assertEqual(
            [call.kwargs["data"]["start_offset"] for call in post.call_args_list[1:4]],
            ["0", "4", "7"],
        )

    def test_rejects_a_chunk_response_that_does_not_advance(self):
        video = b"video-content"
        responses = [
            self.response({
                "upload_session_id": "session123",
                "video_id": "facebook-video123",
                "start_offset": "0",
                "end_offset": str(len(video)),
            }),
            self.response({
                "start_offset": "0",
                "end_offset": str(len(video)),
            }),
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "festival.mp4"
            path.write_bytes(video)
            with mock.patch.object(
                facebook_upload.requests,
                "post",
                side_effect=responses,
            ) as post:
                with self.assertRaisesRegex(
                    facebook_upload.FacebookPublishError,
                    "chunk transfer returned invalid file offsets",
                ):
                    facebook_upload.upload_scheduled(
                        str(path),
                        "Title",
                        "Description",
                        "2027-01-15",
                        "18:30",
                        now=datetime(2027, 1, 15, 10, 0, tzinfo=IST),
                    )

        self.assertEqual(post.call_count, 2)

    def test_redacts_tokens_from_meta_error_messages(self):
        error = self.response({
            "error": {"code": 190, "message": "Invalid token page-secret"},
        }, status=400)

        with self.assertRaises(facebook_upload.FacebookPublishError) as raised:
            facebook_upload._response_body(
                error, ("page-secret",), "test operation",
            )

        self.assertNotIn("page-secret", str(raised.exception))
        self.assertIn("[REDACTED]", str(raised.exception))

    def test_invalid_api_version_is_rejected(self):
        with mock.patch.dict(os.environ, {"META_GRAPH_API_VERSION": "v27"}, clear=False):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "festival.mp4"
                path.write_bytes(b"video-content")
                with self.assertRaisesRegex(ValueError, "version such as v27.0"):
                    facebook_upload.upload_scheduled(
                        str(path), "Title", "Description", "2027-01-15", "18:30",
                    )


if __name__ == "__main__":
    unittest.main()
