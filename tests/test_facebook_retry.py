import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "recap"))

import facebook_retry


class FacebookRetryTests(unittest.TestCase):
    def test_reuses_source_metadata_and_attaches_custom_thumbnail(self):
        with tempfile.TemporaryDirectory() as folder:
            artifact_dir = Path(folder) / "source"
            artifact_dir.mkdir()
            video_path = artifact_dir / "festival.mp4"
            video_path.write_bytes(b"video")
            thumbnail_path = Path(folder) / "custom-thumbnail.jpg"
            thumbnail_path.write_bytes(b"thumbnail")
            metadata_path = artifact_dir / "festival.json"
            metadata_path.write_text(json.dumps({
                "upload_status": "scheduled_public",
                "youtube_video_id": "cPzhKtL3__o",
                "video": "festival.mp4",
                "title": "अक्षय नवमी और जगद्धात्री पूजा 2026",
                "description": "Original description",
                "publish_at_ist": "2026-11-16 09:00 IST",
                "facebook_status": "not_uploaded_review_required",
            }), encoding="utf-8")
            environment = {
                "FACEBOOK_RETRY_ARTIFACT_DIR": str(artifact_dir),
                "FACEBOOK_RETRY_YOUTUBE_VIDEO_ID": "cPzhKtL3__o",
                "FACEBOOK_RETRY_THUMBNAIL_PATH": str(thumbnail_path),
            }

            with mock.patch.dict(os.environ, environment, clear=True):
                with mock.patch.object(
                    facebook_retry.facebook_upload,
                    "upload_scheduled",
                    return_value={
                        "status": "scheduled_public",
                        "video_id": "facebook-video123",
                        "url": "https://www.facebook.com/page123/videos/facebook-video123",
                        "publish_at_ist": "2026-11-16 09:00 IST",
                    },
                ) as upload:
                    facebook_retry.main()

            upload.assert_called_once_with(
                str(video_path),
                "अक्षय नवमी और जगद्धात्री पूजा 2026",
                "Original description",
                "2026-11-16",
                "09:00",
                thumbnail_path=str(thumbnail_path),
            )
            updated = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["facebook_video_id"], "facebook-video123")
            self.assertEqual(updated["facebook_status"], "scheduled_public")
            self.assertEqual(updated["facebook_thumbnail"], "custom-thumbnail.jpg")

    def test_rejects_an_unexpected_youtube_video_id_before_uploading(self):
        with tempfile.TemporaryDirectory() as folder:
            artifact_dir = Path(folder) / "source"
            artifact_dir.mkdir()
            (artifact_dir / "festival.mp4").write_bytes(b"video")
            (artifact_dir / "festival.json").write_text(json.dumps({
                "youtube_video_id": "different-video",
            }), encoding="utf-8")
            thumbnail_path = Path(folder) / "custom-thumbnail.jpg"
            thumbnail_path.write_bytes(b"thumbnail")
            environment = {
                "FACEBOOK_RETRY_ARTIFACT_DIR": str(artifact_dir),
                "FACEBOOK_RETRY_YOUTUBE_VIDEO_ID": "cPzhKtL3__o",
                "FACEBOOK_RETRY_THUMBNAIL_PATH": str(thumbnail_path),
            }

            with mock.patch.dict(os.environ, environment, clear=True):
                with mock.patch.object(
                    facebook_retry.facebook_upload,
                    "upload_scheduled",
                ) as upload:
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "Expected one metadata file for YouTube video cPzhKtL3__o",
                    ):
                        facebook_retry.main()

            upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
