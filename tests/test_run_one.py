import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "recap"))
sys.path.insert(0, str(ROOT / "calendar"))

import run_one
import plan_batch


class RunOneFallbackTests(unittest.TestCase):
    def _environment(self, output_dir, result_dir, upload_allowed="true"):
        return {
            "TOPIC": "A source-grounded cultural story",
            "FEST_DATE": "",
            "FESTIVAL_TRADITION": "A test tradition",
            "CALENDAR_DATE": "2026-12-10",
            "PUBLISH_DATE": "2026-12-10",
            "PUBLISH_TIME": "22:30",
            "CONTENT_TYPE": "story_history",
            "SLOT": "10",
            "UPLOAD_ALLOWED": upload_allowed,
            "EXTRA_ARGS": "[]",
            "OUTPUT_DIR": str(output_dir),
            "RESULTS_DIR": str(result_dir),
        }

    def test_quota_failure_skips_retry_and_saves_generated_files_to_drive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "output"
            results_dir = root / "results"
            output_dir.mkdir()
            video = output_dir / "video.mp4"
            thumbnail = output_dir / "video.jpg"
            metadata = output_dir / "video.json"
            video.write_bytes(b"mp4")
            thumbnail.write_bytes(b"jpg")
            metadata.write_text(json.dumps({"title": "test"}), encoding="utf-8")
            drive_response = {
                "drive_link": "https://drive.google.com/file/d/test/view",
                "reason": "youtube_quota",
            }
            with mock.patch.object(
                run_one.festival_main, "generate_video",
                side_effect=RuntimeError("YouTube upload failed (HTTP 403, quotaExceeded)"),
            ) as generate, mock.patch.object(
                run_one, "save_to_drive", return_value=drive_response,
            ) as save, mock.patch.object(run_one.time, "sleep") as sleep:
                result = run_one.run_one(self._environment(output_dir, results_dir))

            self.assertEqual(result["status"], "failed_saved_to_drive")
            self.assertEqual(result["drive_link"], drive_response["drive_link"])
            generate.assert_called_once()
            self.assertEqual(generate.call_args.kwargs["date"], "")
            self.assertEqual(generate.call_args.kwargs["festival_tradition"], "A test tradition")
            sleep.assert_not_called()
            self.assertEqual(save.call_args.args[3:5], (10, "youtube_quota"))
            saved = json.loads((results_dir / "RESULT_2026-12-10_10.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, result)

    def test_quota_reserved_video_goes_directly_to_drive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "output"
            results_dir = root / "results"
            output_dir.mkdir()
            generated = {
                "video": str(output_dir / "video.mp4"),
                "thumbnail": str(output_dir / "video.jpg"),
                "metadata": str(output_dir / "video.json"),
            }
            for path in generated.values():
                Path(path).write_bytes(b"generated")
            Path(generated["metadata"]).write_text(json.dumps({"title": "test"}), encoding="utf-8")
            with mock.patch.object(
                run_one.festival_main, "generate_video", return_value=generated,
            ) as generate, mock.patch.object(
                run_one, "save_to_drive",
                return_value={"drive_link": "https://drive.google.com/file/d/reserved/view"},
            ) as save:
                result = run_one.run_one(
                    self._environment(output_dir, results_dir, upload_allowed="false"),
                )

            self.assertEqual(result["status"], "failed_saved_to_drive")
            self.assertIn("quota_reserved", result["notes"])
            generate.assert_called_once()
            self.assertFalse(generate.call_args.kwargs["upload"])
            self.assertEqual(save.call_args.args[3:5], (10, "quota_reserved"))

    def test_festival_slot_does_not_load_prepared_editorial_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "output"
            results_dir = root / "results"
            prepared_root = root / "prepared"
            prepared_path = prepared_root / "2026-12-10" / "slot_2.json"
            prepared_path.parent.mkdir(parents=True)
            bundle = {
                "research": {"headline": "तैयार पाठ"},
                "sources": [{"title": "Source A", "url": "https://example.org/a"}],
            }
            prepared_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
            files = {
                "video": output_dir / "video.mp4",
                "thumbnail": output_dir / "video.jpg",
                "metadata": output_dir / "video.json",
                "youtube": "https://www.youtube.com/watch?v=video-123",
            }
            output_dir.mkdir()
            files["video"].write_bytes(b"mp4")
            files["thumbnail"].write_bytes(b"jpg")
            files["metadata"].write_text(json.dumps({
                "title": "तैयार पाठ",
                "youtube_video_id": "video-123",
            }), encoding="utf-8")
            env = self._environment(output_dir, results_dir)
            env["PREPARED_CONTENT_DIR"] = str(prepared_root)
            env["CONTENT_TYPE"] = "festival_explainer"
            env["SLOT"] = "2"

            with mock.patch.object(
                run_one.festival_main, "generate_video", return_value=files,
            ) as generate:
                result = run_one.run_one(env)

        self.assertEqual(result["youtube_status"], "scheduled")
        self.assertIsNone(generate.call_args.kwargs["prepared_bundle"])

    def test_planned_day_attempts_only_the_panchang_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            calendar_path = root / "content_calendar.json"
            results_dir = root / "results"
            rows = [
                {
                    "date": "2026-12-10",
                    "slot": slot,
                    "publish_time_ist": f"{slot:02d}:00",
                    "type": "story_history",
                    "topic_hi": f"परीक्षण विषय {slot}",
                    "festival_date": "",
                    "festival_tradition": "",
                    "status": "planned",
                }
                for slot in range(1, 11)
            ]
            calendar_path.write_text(json.dumps({"videos": rows}), encoding="utf-8")
            with mock.patch.dict("os.environ", {}, clear=True):
                batch = plan_batch.plan_for_date(calendar_path, "2026-12-10")
            self.assertEqual([row["slot"] for row in batch], [1])
            self.assertTrue(all(row["upload_allowed"] for row in batch))

            def generate(**kwargs):
                output_dir = Path(kwargs["output_dir"])
                output_dir.mkdir(parents=True, exist_ok=True)
                files = {
                    "video": output_dir / "video.mp4",
                    "thumbnail": output_dir / "video.jpg",
                    "metadata": output_dir / "video.json",
                }
                files["video"].write_bytes(b"mock video")
                files["thumbnail"].write_bytes(b"mock thumbnail")
                files["metadata"].write_text(
                    json.dumps({"title": kwargs["topic"]}), encoding="utf-8",
                )
                raise RuntimeError("YouTube upload failed (HTTP 403, quotaExceeded)")

            with mock.patch.object(
                run_one.festival_main, "generate_video", side_effect=generate,
            ) as generate_mock, mock.patch.object(
                run_one, "save_to_drive",
                return_value={"drive_link": "https://drive.google.com/file/d/mock/view"},
            ) as save_mock, mock.patch.object(
                run_one, "_prepared_content", return_value=None,
            ):
                results = []
                for row in batch:
                    env = self._environment(
                        root / f"slot_{row['slot']}", results_dir,
                        upload_allowed=str(row["upload_allowed"]).lower(),
                    )
                    env.update({
                        "TOPIC": row["topic_hi"],
                        "SLOT": str(row["slot"]),
                        "PUBLISH_TIME": row["publish_time_ist"],
                    })
                    results.append(run_one.run_one(env))

            self.assertEqual(len(generate_mock.call_args_list), 1)
            self.assertEqual(save_mock.call_count, 1)
            self.assertTrue(all(result["status"] == "failed_saved_to_drive" for result in results))
            self.assertTrue(all(call.kwargs["upload"] for call in generate_mock.call_args_list))
            self.assertTrue(all("youtube_quota" in result["notes"] for result in results))

    def test_batch_runner_rejects_legacy_slot_before_rendering(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = self._environment(root / "output", root / "results")
            env["CONTENT_TYPE"] = "legacy_daily"
            with mock.patch.object(run_one.festival_main, "generate_video") as generate:
                with self.assertRaisesRegex(ValueError, "managed by Apps Script"):
                    run_one.run_one(env)
            generate.assert_not_called()

    def test_facebook_success_is_recorded_when_youtube_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "output"
            results_dir = root / "results"
            output_dir.mkdir()
            generated = {
                "video": str(output_dir / "video.mp4"),
                "thumbnail": str(output_dir / "video.jpg"),
                "metadata": str(output_dir / "video.json"),
                "youtube": "",
                "facebook": "https://www.facebook.com/page/videos/facebook-id",
                "upload_errors": {"youtube": "quota exceeded"},
            }
            Path(generated["video"]).write_bytes(b"video")
            Path(generated["thumbnail"]).write_bytes(b"thumbnail")
            Path(generated["metadata"]).write_text(json.dumps({
                "facebook_video_id": "facebook-id",
                "facebook_url": generated["facebook"],
            }), encoding="utf-8")
            env = self._environment(output_dir, results_dir)
            env["FACEBOOK_UPLOAD"] = "true"

            with mock.patch.object(
                run_one.festival_main, "generate_video", return_value=generated,
            ) as generate, mock.patch.object(
                run_one, "save_to_drive",
                return_value={"drive_link": "https://drive.google.com/file/d/fallback/view"},
            ) as save:
                result = run_one.run_one(env)

            self.assertEqual(result["status"], "scheduled")
            self.assertEqual(result["youtube_status"], "failed")
            self.assertEqual(result["youtube_video_id"], "")
            self.assertEqual(result["facebook_video_id"], "facebook-id")
            self.assertEqual(result["drive_link"], "https://drive.google.com/file/d/fallback/view")
            self.assertIn("youtube upload failed: quota exceeded", result["notes"])
            self.assertTrue(generate.call_args.kwargs["facebook_upload_enabled"])
            self.assertEqual(save.call_args.args[4], "partial_upload_failure")

    def test_runner_fails_when_youtube_fails_even_if_facebook_succeeds(self):
        with mock.patch.object(
            run_one, "run_one",
            return_value={
                "status": "scheduled",
                "youtube_status": "failed",
                "youtube_video_id": "",
            },
        ):
            with self.assertRaises(SystemExit) as raised:
                run_one.main()

        self.assertEqual(raised.exception.code, 1)

    def test_legacy_upload_failure_saves_rendered_assets_to_drive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            generated = {
                "video": str(root / "video.mp4"),
                "thumbnail": str(root / "video.jpg"),
                "metadata": str(root / "video.json"),
                "upload_errors": {"youtube": "quota exceeded"},
            }
            Path(generated["metadata"]).write_text(json.dumps({}), encoding="utf-8")
            environment = {
                "FESTIVAL_TOPIC": "A sourced legacy festival topic",
                "FESTIVAL_PUBLISH_DATE": "2026-12-10",
                "FESTIVAL_PUBLISH_TIME": "09:00",
                "YOUTUBE_UPLOAD": "true",
                "FACEBOOK_UPLOAD": "true",
            }
            with mock.patch.dict("os.environ", environment, clear=True), mock.patch.object(
                run_one.sys, "argv", ["festival_main.py"],
            ), mock.patch.object(
                run_one.festival_main, "generate_video", return_value=generated,
            ) as generate, mock.patch.object(
                run_one.festival_main, "save_to_drive",
                return_value={"drive_link": "https://drive.google.com/file/d/legacy/view"},
            ) as save:
                with self.assertRaisesRegex(SystemExit, "YouTube upload failed"):
                    run_one.festival_main.main()

            self.assertTrue(generate.call_args.kwargs["continue_on_upload_errors"])
            self.assertEqual(save.call_args.args[3:5], (3, "partial_upload_failure"))
            self.assertEqual(save.call_args.kwargs["publish_date"], "2026-12-10")
            self.assertEqual(save.call_args.kwargs["publish_time"], "09:00")
            self.assertEqual(save.call_args.kwargs["calendar_date"], "2026-12-10")

    def test_legacy_upload_success_does_not_save_a_drive_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            metadata_path = Path(temp_dir) / "video.json"
            metadata_path.write_text(json.dumps({
                "youtube_video_id": "video-id",
            }), encoding="utf-8")
            environment = {
                "FESTIVAL_TOPIC": "A sourced legacy festival topic",
                "FESTIVAL_PUBLISH_DATE": "2026-12-10",
                "FESTIVAL_PUBLISH_TIME": "09:00",
                "YOUTUBE_UPLOAD": "true",
            }
            generated = {
                "video": str(Path(temp_dir) / "video.mp4"),
                "thumbnail": str(Path(temp_dir) / "video.jpg"),
                "metadata": str(metadata_path),
                "youtube": "https://www.youtube.com/watch?v=video-id",
                "upload_errors": {},
            }
            with mock.patch.dict("os.environ", environment, clear=True), mock.patch.object(
                run_one.sys, "argv", ["festival_main.py"],
            ), mock.patch.object(
                run_one.festival_main, "generate_video", return_value=generated,
            ), mock.patch.object(
                run_one.festival_main, "save_to_drive",
            ) as save:
                run_one.festival_main.main()
        save.assert_not_called()
