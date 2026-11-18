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

    def test_planned_day_runs_without_uploads_and_uses_drive_fallback(self):
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
                    "status": "blocked_unverified" if slot in {2, 8} else "planned",
                }
                for slot in range(1, 11)
            ]
            calendar_path.write_text(json.dumps({"videos": rows}), encoding="utf-8")
            batch = plan_batch.plan_for_date(
                calendar_path, "2026-12-10", upload_limit=0,
            )
            self.assertEqual(len(batch), 8)

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
                return {name: str(path) for name, path in files.items()}

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
                        root / f"slot_{row['slot']}", results_dir, upload_allowed="false",
                    )
                    env.update({
                        "TOPIC": row["topic_hi"],
                        "SLOT": str(row["slot"]),
                        "PUBLISH_TIME": row["publish_time_ist"],
                    })
                    results.append(run_one.run_one(env))

            self.assertEqual(len(generate_mock.call_args_list), 8)
            self.assertEqual(save_mock.call_count, 8)
            self.assertTrue(all(result["status"] == "failed_saved_to_drive" for result in results))
            self.assertTrue(all(not call.kwargs["upload"] for call in generate_mock.call_args_list))

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
            self.assertEqual(result["youtube_video_id"], "")
            self.assertEqual(result["facebook_video_id"], "facebook-id")
            self.assertEqual(result["drive_link"], "https://drive.google.com/file/d/fallback/view")
            self.assertIn("youtube upload failed: quota exceeded", result["notes"])
            self.assertTrue(generate.call_args.kwargs["facebook_upload_enabled"])
            self.assertEqual(save.call_args.args[4], "partial_upload_failure")
