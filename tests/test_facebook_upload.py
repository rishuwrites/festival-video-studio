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
            "META_APP_ID": "app123",
            "META_USER_ACCESS_TOKEN": "user-secret",
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
        start = self.response({"id": "upload:session123"})
        uploaded = self.response({"h": "file-handle"})
        published = self.response({"id": "facebook-video123"})

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "festival.mp4"
            path.write_bytes(b"video-content")
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
                )

        self.assertEqual(result, {
            "video_id": "facebook-video123",
            "url": "https://www.facebook.com/page123/videos/facebook-video123",
            "publish_at_ist": "2027-01-15 18:30 IST",
            "status": "scheduled_public",
        })
        self.assertEqual(post.call_count, 3)
        self.assertEqual(
            post.call_args_list[0].args[0],
            "https://graph.facebook.com/v27.0/app123/uploads",
        )
        self.assertEqual(
            post.call_args_list[0].kwargs["params"]["access_token"],
            "user-secret",
        )
        form = post.call_args_list[2].kwargs["data"]
        self.assertEqual(form["access_token"], "page-secret")
        self.assertEqual(form["fbuploader_video_file_chunk"], "file-handle")
        self.assertEqual(form["published"], "false")
        self.assertEqual(form["scheduled_publish_time"], str(int(publish_at.timestamp())))

    def test_requires_page_and_resumable_upload_credentials(self):
        with mock.patch.dict(os.environ, {"FACEBOOK_PAGE_ID": "page123"}, clear=True):
            with mock.patch.object(facebook_upload.requests, "post") as post:
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / "festival.mp4"
                    path.write_bytes(b"video-content")
                    with self.assertRaisesRegex(
                        facebook_upload.FacebookPublishError,
                        "FACEBOOK_PAGE_ACCESS_TOKEN.*META_APP_ID.*META_USER_ACCESS_TOKEN",
                    ):
                        facebook_upload.upload_scheduled(
                            str(path), "Title", "Description", "2027-01-15", "18:30",
                        )

        post.assert_not_called()

    def test_redacts_tokens_from_meta_error_messages(self):
        error = self.response({
            "error": {"code": 190, "message": "Invalid token user-secret"},
        }, status=400)

        with self.assertRaises(facebook_upload.FacebookPublishError) as raised:
            facebook_upload._response_body(
                error, ("page-secret", "user-secret"), "test operation",
            )

        self.assertNotIn("user-secret", str(raised.exception))
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
