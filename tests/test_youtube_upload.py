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

    def test_schedules_public_release_at_selected_ist_publish_time(self):
        publish_date, publish_time = future_schedule()
        initiated = mock.Mock(status_code=200)
        initiated.headers = {"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=test"}
        uploaded = mock.Mock(status_code=201)
        uploaded.json.return_value = {"id": "video123"}

        with tempfile.TemporaryDirectory() as folder:
            video_path, metadata_path = self.make_inputs(folder)
            thumbnail_path = str(Path(folder) / "thumbnail.jpg")
            Path(thumbnail_path).write_bytes(b"jpeg")
            with mock.patch.object(youtube_upload, "oauth_access_token", return_value="token"), \
                    mock.patch.object(youtube_upload, "_existing_upload", return_value=None), \
                    mock.patch.object(youtube_upload.requests, "post", return_value=initiated) as post, \
                    mock.patch.object(youtube_upload.requests, "put", return_value=uploaded) as put, \
                    mock.patch.object(youtube_upload, "_set_video_thumbnail") as set_thumbnail:
                result = youtube_upload.upload_scheduled(
                    video_path, metadata_path, publish_date, publish_time,
                    thumbnail_path=thumbnail_path,
                )

        self.assertEqual(result["video_id"], "video123")
        self.assertEqual(result["status"], "scheduled_public")
        self.assertEqual(result["publish_at_ist"].endswith("IST"), True)
        payload = post.call_args.kwargs["json"]
        # YouTube requires privacyStatus=private while a future publishAt is set.
        self.assertEqual(payload["status"]["privacyStatus"], "private")
        self.assertTrue(payload["status"]["publishAt"].endswith("+05:30"))
        self.assertEqual(put.call_args.kwargs["headers"]["Content-Range"], "bytes 0-18/19")
        self.assertEqual(put.call_args.args[0], initiated.headers["Location"])
        set_thumbnail.assert_called_once_with("token", "video123", thumbnail_path)

    def test_sets_existing_video_thumbnail_with_oauth(self):
        response = mock.Mock(status_code=200)
        with tempfile.TemporaryDirectory() as folder:
            thumbnail_path = str(Path(folder) / "thumbnail.jpg")
            Path(thumbnail_path).write_bytes(b"jpeg")
            with mock.patch.object(youtube_upload, "oauth_access_token", return_value="token"), \
                    mock.patch.object(youtube_upload.requests, "post", return_value=response) as post:
                youtube_upload.set_video_thumbnail("video123", thumbnail_path)

        self.assertEqual(post.call_args.args[0], youtube_upload.THUMBNAIL_UPLOAD_URL)
        self.assertEqual(post.call_args.kwargs["params"], {"videoId": "video123"})
        self.assertEqual(post.call_args.kwargs["headers"]["Content-Type"], "image/jpeg")

    def test_rejects_missing_thumbnail_before_uploading_video(self):
        publish_date, publish_time = future_schedule()
        with tempfile.TemporaryDirectory() as folder:
            video_path, metadata_path = self.make_inputs(folder)
            with mock.patch.object(youtube_upload, "oauth_access_token") as oauth:
                with self.assertRaisesRegex(FileNotFoundError, "Thumbnail file"):
                    youtube_upload.upload_scheduled(
                        video_path, metadata_path, publish_date, publish_time,
                        thumbnail_path=str(Path(folder) / "missing.jpg"),
                    )

        oauth.assert_not_called()

    def test_normalizes_tags_before_sending_youtube_metadata(self):
        publish_date, publish_time = future_schedule()
        initiated = mock.Mock(status_code=200)
        initiated.headers = {"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=test"}
        uploaded = mock.Mock(status_code=201)
        uploaded.json.return_value = {"id": "video123"}

        with tempfile.TemporaryDirectory() as folder:
            video_path, metadata_path = self.make_inputs(folder)
            metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
            metadata["tags"] = [
                "Chhath Puja Usha Arghya: the morning offering and conclusion",
                "a tag, with commas",
                "a tag, with commas",
            ]
            Path(metadata_path).write_text(json.dumps(metadata), encoding="utf-8")
            with mock.patch.object(youtube_upload, "oauth_access_token", return_value="token"), \
                    mock.patch.object(youtube_upload, "_existing_upload", return_value=None), \
                    mock.patch.object(youtube_upload.requests, "post", return_value=initiated) as post, \
                    mock.patch.object(youtube_upload.requests, "put", return_value=uploaded):
                youtube_upload.upload_scheduled(
                    video_path, metadata_path, publish_date, publish_time,
                )

        tags = post.call_args.kwargs["json"]["snippet"]["tags"]
        self.assertEqual(tags, ["Chhath Puja Usha Arghya", "a tag with commas"])
        self.assertTrue(all(len(tag) <= 30 and "," not in tag for tag in tags))

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
        with mock.patch.object(festival_main, "_research_with_gemini") as research:
            with self.assertRaisesRegex(ValueError, "15 minutes"):
                festival_main.generate_video(
                    "Festival", publish_date="2020-01-01", publish_time="00:00", upload=True,
                )

        research.assert_not_called()

    def test_invalid_facebook_schedule_is_rejected_before_research_or_rendering(self):
        with mock.patch.object(festival_main, "_research_with_gemini") as research:
            with self.assertRaisesRegex(ValueError, "15 minutes"):
                festival_main.generate_video(
                    "Festival",
                    publish_date="2020-01-01",
                    publish_time="00:00",
                    facebook_upload_enabled=True,
                )

        research.assert_not_called()

    def test_reports_oauth_scope_issue_without_disclosing_token(self):
        response = mock.Mock(status_code=403)
        response.json.return_value = {"error": {"errors": [{"reason": "insufficientPermissions"}]}}

        with self.assertRaisesRegex(RuntimeError, "youtube.upload and youtube.readonly"):
            youtube_upload._check_response(response, "video upload")


if __name__ == "__main__":
    unittest.main()
