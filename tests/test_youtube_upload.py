import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "recap"))

import youtube_upload
import festival_main


IST = ZoneInfo("Asia/Kolkata")


def future_schedule():
    future = datetime.now(IST).replace(second=0, microsecond=0)
    if future.minute < 30:
        minute = 30
    else:
        future = future.replace(hour=(future.hour + 1) % 24)
        minute = 30
    future = future.replace(minute=minute)
    if future <= datetime.now(IST).replace(second=0, microsecond=0) + youtube_upload.dt.timedelta(minutes=15):
        future += youtube_upload.dt.timedelta(hours=1)
    return future.strftime("%Y-%m-%d"), future.strftime("%H:%M")


class ScheduledDateTests(unittest.TestCase):
    def test_scheduled_time_is_interpreted_as_india_standard_time(self):
        scheduled = youtube_upload.scheduled_datetime(
            "2027-01-15", "18:30",
            now=datetime(2027, 1, 15, 10, 0, tzinfo=IST),
        )

        self.assertEqual(scheduled.strftime("%Y-%m-%d %H:%M %Z"), "2027-01-15 18:30 IST")

    def test_rejects_bad_date_time_and_schedule_too_near_now(self):
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            youtube_upload.scheduled_datetime("15-01-2027", "18:30")
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            youtube_upload.scheduled_datetime("2027-1-5", "18:30")
        with self.assertRaisesRegex(ValueError, "HH:MM"):
            youtube_upload.scheduled_datetime("2027-01-15", "8:30")
        with self.assertRaisesRegex(ValueError, "15 minutes"):
            youtube_upload.scheduled_datetime(
                "2027-01-15", "10:10",
                now=datetime(2027, 1, 15, 10, 0, tzinfo=IST),
            )


class ScheduledUploadTests(unittest.TestCase):
    def make_inputs(self, folder):
        video_path = Path(folder) / "festival.mp4"
        video_path.write_bytes(b"small-video-content")
        metadata_path = Path(folder) / "festival.json"
        metadata_path.write_text(json.dumps({
            "title": "त्योहार की जानकारी",
            "description": "मूल हिंदी जानकारी।",
            "tags": ["त्योहार", "भारत"],
        }), encoding="utf-8")
        return str(video_path), str(metadata_path)

    def test_uploads_resumably_as_private_with_selected_ist_publish_time(self):
        publish_date, publish_time = future_schedule()
        initiated = mock.Mock(status_code=200)
        initiated.headers = {"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=test"}
        uploaded = mock.Mock(status_code=201)
        uploaded.json.return_value = {"id": "video123"}

        with tempfile.TemporaryDirectory() as folder:
            video_path, metadata_path = self.make_inputs(folder)
            with mock.patch.object(youtube_upload, "oauth_access_token", return_value="token"), \
                    mock.patch.object(youtube_upload, "_existing_upload", return_value=None), \
                    mock.patch.object(youtube_upload.requests, "post", return_value=initiated) as post, \
                    mock.patch.object(youtube_upload.requests, "put", return_value=uploaded) as put:
                result = youtube_upload.upload_scheduled(
                    video_path, metadata_path, publish_date, publish_time,
                )

        self.assertEqual(result["video_id"], "video123")
        self.assertEqual(result["status"], "scheduled_private")
        self.assertEqual(result["publish_at_ist"].endswith("IST"), True)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["status"]["privacyStatus"], "private")
        self.assertTrue(payload["status"]["publishAt"].endswith("+05:30"))
        self.assertEqual(put.call_args.kwargs["headers"]["Content-Range"], "bytes 0-18/19")
        self.assertEqual(put.call_args.args[0], initiated.headers["Location"])

    def test_prevents_upload_when_same_title_already_exists(self):
        publish_date, publish_time = future_schedule()
        with tempfile.TemporaryDirectory() as folder:
            video_path, metadata_path = self.make_inputs(folder)
            with mock.patch.object(youtube_upload, "oauth_access_token", return_value="token"), \
                    mock.patch.object(youtube_upload, "_existing_upload", return_value="existing123"), \
                    mock.patch.object(youtube_upload.requests, "post") as post:
                with self.assertRaisesRegex(RuntimeError, "Not uploading a duplicate"):
                    youtube_upload.upload_scheduled(
                        video_path, metadata_path, publish_date, publish_time,
                    )

        post.assert_not_called()

    def test_never_uploads_if_publish_time_expired_during_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            video_path, metadata_path = self.make_inputs(folder)
            with mock.patch.object(youtube_upload, "oauth_access_token") as oauth:
                with self.assertRaisesRegex(ValueError, "15 minutes"):
                    youtube_upload.upload_scheduled(
                        video_path, metadata_path,
                        "2027-01-15", "10:10",
                        now=datetime(2027, 1, 15, 10, 0, tzinfo=IST),
                    )

        oauth.assert_not_called()

    def test_invalid_schedule_is_rejected_before_research_or_rendering(self):
        with mock.patch.object(festival_main, "find_transcribed_videos") as find_videos:
            with self.assertRaisesRegex(ValueError, "15 minutes"):
                festival_main.generate_video(
                    "Festival", publish_date="2020-01-01", publish_time="00:00", upload=True,
                )

        find_videos.assert_not_called()

    def test_reports_oauth_scope_issue_without_disclosing_token(self):
        response = mock.Mock(status_code=403)
        response.json.return_value = {"error": {"errors": [{"reason": "insufficientPermissions"}]}}

        with self.assertRaisesRegex(RuntimeError, "youtube.upload and youtube.readonly"):
            youtube_upload._check_response(response, "video upload")


if __name__ == "__main__":
    unittest.main()
