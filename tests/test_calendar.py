import json
import csv
import datetime as dt
import io
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from contextlib import redirect_stdout
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CALENDAR_PATH = ROOT / "data" / "india-festival-video-calendar-2026.json"
sys.path.insert(0, str(ROOT / "calendar"))
import build_calendar
import plan_batch
import seed_templates
import update_calendar


class DailyCalendarBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.slots_path = ROOT / "config" / "slots.json"
        self.pool_path = self.root / "topic_pool.json"
        topics = seed_templates.build_topics()
        topics.extend([
            {
                "type": "festival_explainer",
                "topic_hi": "परीक्षण पर्व: तिथि और कथा",
                "topic_en": "Test Festival: date and story",
                "evergreen": False,
                "earliest_date": "2026-11-18",
                "latest_date": "2026-12-31",
                "festival_key": "Test Festival",
            },
            {
                "type": "upcoming_festival",
                "topic_hi": "परीक्षण पर्व: तैयारी",
                "topic_en": "Test Festival: preparation",
                "evergreen": False,
                "earliest_date": "2026-11-18",
                "latest_date": "2026-12-31",
                "festival_key": "Test Festival",
            },
        ])
        self.pool_path.write_text(
            json.dumps({"topics": topics}, ensure_ascii=False), encoding="utf-8",
        )
        self.festivals_path = self.root / "festivals.json"
        self.legacy_path = self.root / "legacy.json"
        self.legacy_path.write_text(json.dumps({"entries": []}), encoding="utf-8")
        self._write_festivals([{
            "name_hi": "परीक्षण पर्व",
            "name_en": "Test Festival",
            "date": "2026-11-19",
            "tithi_note": "Test owner-verified source",
            "verified": True,
            "source_urls": [
                "https://example.org/festival",
                "https://example.net/festival",
            ],
            "tradition": "Test tradition",
            "notes": "Test source agreement",
        }])
        self.panchang_path = self.root / "panchang.csv"
        self._write_panchang([{
            "date": "2026-11-18",
            "tithi": "द्वादशी",
            "paksha": "शुक्ल",
            "nakshatra": "रोहिणी",
            "moon_rashi": "मेष",
            "rahu_kaal_start": "10:30",
            "rahu_kaal_end": "12:00",
            "sunrise": "06:10",
        }])

    def tearDown(self):
        self.temp.cleanup()

    def _write_festivals(self, entries):
        self.festivals_path.write_text(
            json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8",
        )

    def _write_panchang(self, rows):
        fields = [
            "date", "tithi", "paksha", "nakshatra", "moon_rashi",
            "rahu_kaal_start", "rahu_kaal_end", "sunrise",
        ]
        with self.panchang_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def _build(self, previous_path=None, channel_focus_path=None):
        return build_calendar.build_rows(
            "2026-11-18",
            "2026-11-18",
            slots_path=self.slots_path,
            topic_pool_path=self.pool_path,
            festivals_path=self.festivals_path,
            panchang_path=self.panchang_path,
            previous_path=previous_path or self.root / "missing.json",
            channel_focus_path=channel_focus_path or ROOT / "config" / "channel_focus.json",
            legacy_calendar_path=self.legacy_path,
        )

    def test_builds_ten_unique_topics_and_marks_early_festival_as_late(self):
        result = self._build()
        rows = result["videos"]
        self.assertEqual(len(rows), 10)
        self.assertEqual({row["slot"] for row in rows}, set(range(1, 11)))
        self.assertEqual(len({row["topic_hi"] for row in rows}), 10)
        self.assertFalse(any(
            rows[index]["type"] == rows[index - 1]["type"]
            for index in range(1, len(rows))
        ))
        festival_rows = [row for row in rows if row["festival_date"]]
        self.assertEqual(len(festival_rows), 2)
        self.assertTrue(all(row["notes"] == "late_prepublish" for row in festival_rows))

    def test_does_not_repeat_a_topic_with_a_different_angle_on_the_same_day(self):
        rows = self._build()["videos"]
        identities = [
            build_calendar._topic_identity(row)
            for row in rows
        ]

        self.assertEqual(len(identities), len(set(identities)))

    def test_unverified_festival_slots_use_evergreen_replacements(self):
        entries = json.loads(self.festivals_path.read_text(encoding="utf-8"))["entries"]
        entries[0]["verified"] = False
        self._write_festivals(entries)
        output = io.StringIO()
        with redirect_stdout(output):
            result = self._build()
        replacements = [result["videos"][slot - 1] for slot in (2, 9)]
        self.assertEqual([row["type"] for row in replacements], ["regional_customs", "story_history"])
        self.assertTrue(all(row["status"] == "planned" for row in replacements))
        self.assertTrue(all("unverified festival topic not scheduled" in row["notes"] for row in replacements))
        self.assertIn("Test Festival", output.getvalue())
        self.assertFalse(any(row["festival_date"] for row in replacements))

    def test_calendar_lists_legacy_video_but_keeps_it_out_of_batch_source_rows(self):
        self.legacy_path.write_text(json.dumps({"entries": [{
            "date": "2026-11-20",
            "topic": "Existing legacy daily topic",
            "festival": None,
            "panchang_events": [],
        }]}), encoding="utf-8")

        rows = self._build()["videos"]
        legacy = [row for row in rows if row["source"] == "legacy"]

        self.assertEqual(len(legacy), 1)
        self.assertEqual(legacy[0]["slot"], 3)
        self.assertEqual(legacy[0]["type"], "legacy_daily")
        self.assertEqual(legacy[0]["status"], "legacy_managed")
        self.assertEqual(legacy[0]["topic_hi"], "Existing legacy daily topic")
        self.assertEqual(sum(row["source"] == "batch" for row in rows), 9)

    def test_nearby_legacy_topic_is_not_selected_for_a_batch_slot(self):
        legacy_topic = "Regional perspective: Folk lamp decoration in Awadh"
        self.legacy_path.write_text(json.dumps({"entries": [{
            "date": "2026-11-20",
            "topic": legacy_topic,
            "festival": None,
            "panchang_events": [],
        }]}), encoding="utf-8")

        rows = self._build()["videos"]

        self.assertEqual(
            sum(row["topic_en"] == legacy_topic for row in rows),
            1,
        )
        self.assertFalse(any(
            row["source"] == "batch" and row["topic_en"] == legacy_topic
            for row in rows
        ))

    def test_channel_focus_rejects_below_80_percent_core_topics(self):
        focus = build_calendar._read_channel_focus(ROOT / "config" / "channel_focus.json")
        below_threshold = [
            {
                "status": "planned",
                "source": "batch",
                "type": "festival_explainer" if index < 7 else "rashi_encyclopedia",
            }
            for index in range(10)
        ]
        with self.assertRaisesRegex(build_calendar.CalendarBuildError, "core share"):
            build_calendar._validate_day_focus(below_threshold, focus, "2026-11-18")

        at_threshold = [
            {
                "status": "planned",
                "source": "batch",
                "type": (
                    "festival_explainer" if index < 8
                    else "rashi_encyclopedia" if index == 8
                    else "unclassified"
                ),
            }
            for index in range(10)
        ]
        build_calendar._validate_day_focus(at_threshold, focus, "2026-11-18")

    def test_channel_focus_enforces_daily_astrology_limit(self):
        focus_path = self.root / "focus.json"
        focus_path.write_text(json.dumps({
            "core_categories": ["festival_explainer", "vrat_rules", "story_history",
                               "regional_customs", "evergreen_culture", "upcoming_festival",
                               "tithi_and_dates"],
            "astrology_categories": ["daily_panchang_rashifal", "rashi_encyclopedia"],
            "min_core_share": 0.8,
            "max_astrology_per_day": 0,
            "rashi_encyclopedia_max_per_week": 2,
        }), encoding="utf-8")

        with self.assertRaisesRegex(build_calendar.CalendarBuildError, "astrology videos"):
            self._build(channel_focus_path=focus_path)

    def test_weekly_rashi_limit_is_respected(self):
        rows = []
        for day in ("2026-11-24", "2026-11-25", "2026-11-26", "2026-11-27"):
            rows.append({
                "date": day,
                "tithi": "द्वादशी",
                "paksha": "शुक्ल",
                "nakshatra": "रोहिणी",
                "moon_rashi": "मेष",
                "rahu_kaal_start": "10:30",
                "rahu_kaal_end": "12:00",
                "sunrise": "06:10",
            })
        self._write_panchang(rows)
        focus_path = self.root / "focus.json"
        focus_path.write_text(json.dumps({
            "core_categories": ["festival_explainer", "vrat_rules", "story_history",
                               "regional_customs", "evergreen_culture", "upcoming_festival",
                               "tithi_and_dates"],
            "astrology_categories": ["daily_panchang_rashifal", "rashi_encyclopedia"],
            "min_core_share": 0.8,
            "max_astrology_per_day": 1,
            "rashi_encyclopedia_max_per_week": 1,
        }), encoding="utf-8")

        result = build_calendar.build_rows(
            "2026-11-24",
            "2026-11-27",
            slots_path=self.slots_path,
            topic_pool_path=self.pool_path,
            festivals_path=self.festivals_path,
            panchang_path=self.panchang_path,
            previous_path=self.root / "missing.json",
            channel_focus_path=focus_path,
            legacy_calendar_path=self.legacy_path,
        )

        self.assertLessEqual(
            sum(row["type"] == "rashi_encyclopedia" for row in result["videos"]),
            1,
        )

    def test_missing_panchang_data_stops_calendar_generation(self):
        self._write_panchang([])
        with self.assertRaisesRegex(build_calendar.CalendarBuildError, "missing dates"):
            self._build()

    def test_builder_preserves_completed_status_and_video_id(self):
        first = self._build()
        first["videos"][0].update({
            "status": "uploaded",
            "youtube_video_id": "video-123",
            "drive_link": "https://drive.google.com/file/d/example/view",
            "topic_hi": "मौजूदा अपलोड किया गया विषय",
            "topic_en": "Existing uploaded topic",
        })
        previous = self.root / "previous.json"
        previous.write_text(json.dumps(first), encoding="utf-8")
        rebuilt = self._build(previous)
        self.assertEqual(rebuilt["videos"][0]["status"], "uploaded")
        self.assertEqual(rebuilt["videos"][0]["youtube_video_id"], "video-123")
        self.assertEqual(rebuilt["videos"][0]["drive_link"], "https://drive.google.com/file/d/example/view")
        self.assertEqual(rebuilt["videos"][0]["topic_hi"], "मौजूदा अपलोड किया गया विषय")
        self.assertEqual(rebuilt["videos"][0]["topic_en"], "Existing uploaded topic")

    def test_rebuild_keeps_uploaded_topics_and_avoids_reusing_their_subjects(self):
        first = self._build()
        for slot, hindi_angle, english_angle in (
            (4, "कथा और लोकस्मृति", "Story and community memory"),
            (6, "इतिहास की झलक", "A glimpse into history"),
        ):
            row = first["videos"][slot - 1]
            row.update({
                "status": "scheduled",
                "youtube_video_id": f"video-{slot}",
                "topic_hi": f"{hindi_angle}: घंटी और आरती की ध्वनि",
                "topic_en": f"{english_angle}: Temple bells and aarti",
            })
        previous = self.root / "previous.json"
        previous.write_text(json.dumps(first, ensure_ascii=False), encoding="utf-8")

        rebuilt = self._build(previous)

        rows = rebuilt["videos"]
        completed = [row for row in rows if row["youtube_video_id"]]
        planned = [row for row in rows if row["status"] == "planned"]
        completed_identities = {
            build_calendar._topic_identity(row) for row in completed
        }
        planned_identities = [
            build_calendar._topic_identity(row) for row in planned
        ]
        self.assertEqual([row["youtube_video_id"] for row in completed], ["video-4", "video-6"])
        self.assertEqual(len(planned_identities), len(set(planned_identities)))
        self.assertFalse(completed_identities.intersection(planned_identities))

    def test_pre_publishing_uses_two_to_three_day_window_or_marks_late(self):
        self.assertEqual(
            build_calendar.prepublish_date("2026-11-20", "2026-11-18"),
            ("2026-11-18", False),
        )
        self.assertEqual(
            build_calendar.prepublish_date("2026-11-19", "2026-11-18"),
            ("2026-11-18", True),
        )

    def test_generated_topic_pool_has_at_least_300_distinct_topics(self):
        topics = seed_templates.build_topics()
        self.assertGreaterEqual(len(topics), 300)
        self.assertEqual(len({
            (item["topic_hi"].casefold(), item["topic_en"].casefold())
            for item in topics
        }), len(topics))

    def test_full_window_has_440_unique_long_form_slots_when_sources_are_complete(self):
        start = date(2026, 11, 18)
        end = date(2026, 12, 31)
        topics = seed_templates.build_topics()
        festivals = []
        current = start
        while current <= end:
            event_date = current + timedelta(days=2)
            name_en = f"Test event {current.isoformat()}"
            name_hi = f"परीक्षण पर्व {current.isoformat()}"
            festivals.append({
                "name_hi": name_hi,
                "name_en": name_en,
                "date": event_date.isoformat(),
                "tithi_note": "Synthetic test data",
                "verified": True,
                "source_urls": [
                    "https://example.org/festival",
                    "https://example.net/festival",
                ],
                "tradition": "Synthetic tradition",
                "notes": "Synthetic source agreement",
            })
            for content_type, suffix in (
                ("festival_explainer", "मुख्य परिचय"),
                ("upcoming_festival", "तैयारी"),
            ):
                topics.append({
                    "type": content_type,
                    "topic_hi": f"{name_hi}: {suffix}",
                    "topic_en": f"{name_en}: {suffix}",
                    "evergreen": False,
                    "earliest_date": start.isoformat(),
                    "latest_date": end.isoformat(),
                    "festival_key": name_en,
                })
            current += timedelta(days=1)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            festivals_path = root / "festivals.json"
            festivals_path.write_text(
                json.dumps({"entries": festivals}, ensure_ascii=False), encoding="utf-8",
            )
            pool_path = root / "topics.json"
            pool_path.write_text(
                json.dumps({"topics": topics}, ensure_ascii=False), encoding="utf-8",
            )
            panchang_path = root / "panchang.csv"
            fields = [
                "date", "tithi", "paksha", "nakshatra", "moon_rashi",
                "rahu_kaal_start", "rahu_kaal_end", "sunrise",
            ]
            with panchang_path.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=fields)
                writer.writeheader()
                current = start
                while current <= end:
                    writer.writerow({
                        "date": current.isoformat(),
                        "tithi": "द्वादशी",
                        "paksha": "शुक्ल",
                        "nakshatra": "रोहिणी",
                        "moon_rashi": "मेष",
                        "rahu_kaal_start": "10:30",
                        "rahu_kaal_end": "12:00",
                        "sunrise": "06:10",
                    })
                    current += timedelta(days=1)
            result = build_calendar.build_rows(
                start.isoformat(),
                end.isoformat(),
                slots_path=self.slots_path,
                topic_pool_path=pool_path,
                festivals_path=festivals_path,
                panchang_path=panchang_path,
                previous_path=root / "missing.json",
                legacy_calendar_path=self.legacy_path,
            )
        self.assertEqual(len(result["videos"]), 440)
        self.assertEqual(len({row["topic_hi"] for row in result["videos"]}), 440)
        self.assertTrue(all(row["status"] == "planned" for row in result["videos"]))

    def test_real_window_keeps_ten_planned_videos_without_unverified_festivals(self):
        with redirect_stdout(io.StringIO()):
            result = build_calendar.build_rows(
                "2026-11-18",
                "2026-12-31",
                previous_path=self.root / "missing.json",
            )
        by_date = {}
        for row in result["videos"]:
            by_date.setdefault(row["date"], []).append(row)
        self.assertEqual(len(result["videos"]), 440)
        self.assertTrue(all(
            len(rows) == 10
            and all(row["status"] in {"planned", "legacy_managed"} for row in rows)
            for rows in by_date.values()
        ))
        self.assertTrue(any(
            "unverified festival topic not scheduled" in row["notes"]
            for row in result["videos"]
        ))


class DailyUploadBudgetTests(unittest.TestCase):
    def test_default_budget_attempts_all_ten_planned_videos(self):
        from upload_budget import allocate_uploads
        rows = [
            {"date": "2026-11-18", "slot": slot}
            for slot in range(1, 11)
        ]
        with mock.patch.dict("os.environ", {}, clear=True):
            planned = allocate_uploads(rows)
        self.assertEqual(len(planned), 10)
        self.assertTrue(all(row["upload_allowed"] for row in planned))
        self.assertFalse(any("drive_reason" in row for row in planned))

    def test_batch_planner_selects_only_the_daily_panchang_slot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "content_calendar.json"
            rows = [
                {"date": "2026-11-18", "slot": slot, "status": "planned"}
                for slot in range(1, 11)
            ]
            rows.append({"date": "2026-11-19", "slot": 1, "status": "planned"})
            path.write_text(json.dumps({"videos": rows}), encoding="utf-8")
            with mock.patch.dict("os.environ", {}, clear=True):
                planned = plan_batch.plan_for_date(path, "2026-11-18")
            self.assertEqual([row["slot"] for row in planned], [1])
            self.assertEqual(sum(row["upload_allowed"] for row in planned), 1)

    def test_duplicate_planner_allows_both_platforms_for_an_existing_panchang(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "content_calendar.json"
            rows = [
                {
                    "date": "2026-11-21",
                    "slot": slot,
                    "status": "scheduled" if slot == 1 else "planned",
                    "youtube_video_id": "existing-video" if slot == 1 else "",
                    "facebook_video_id": "existing-facebook" if slot == 1 else "",
                    "publish_time_ist": "06:00",
                }
                for slot in range(1, 11)
            ]
            path.write_text(json.dumps({"videos": rows}), encoding="utf-8")

            planned = plan_batch.plan_for_date(
                path, "2026-11-21", duplicate=True,
            )

        self.assertEqual([row["slot"] for row in planned], [1])
        self.assertTrue(planned[0]["upload_allowed"])
        self.assertTrue(planned[0]["facebook_upload_allowed"])

    def test_duplicate_planner_requires_a_successfully_scheduled_original(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "content_calendar.json"
            rows = [
                {
                    "date": "2026-11-21",
                    "slot": slot,
                    "status": "planned",
                    "youtube_video_id": "",
                }
                for slot in range(1, 11)
            ]
            path.write_text(json.dumps({"videos": rows}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "already-scheduled Panchang"):
                plan_batch.plan_for_date(
                    path, "2026-11-21", duplicate=True,
                )

    def test_batch_planner_excludes_blocked_unverified_slots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "content_calendar.json"
            rows = [
                {
                    "date": "2026-11-18",
                    "slot": slot,
                    "status": "blocked_unverified" if slot in {2, 8} else "planned",
                }
                for slot in range(1, 11)
            ]
            path.write_text(json.dumps({"videos": rows}), encoding="utf-8")
            planned = plan_batch.plan_for_date(path, "2026-11-18")
            self.assertEqual([row["slot"] for row in planned], [1])
            self.assertTrue(all(row["upload_allowed"] for row in planned))

    def test_batch_planner_excludes_legacy_slot_and_reserves_combined_budget(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "content_calendar.json"
            rows = [
                {
                    "date": "2026-11-18",
                    "slot": slot,
                    "type": "legacy_daily" if slot == 3 else "story_history",
                    "source": "legacy" if slot == 3 else "batch",
                    "status": "legacy_managed" if slot == 3 else "planned",
                }
                for slot in range(1, 11)
            ]
            path.write_text(json.dumps({"videos": rows}), encoding="utf-8")

            planned = plan_batch.plan_for_date(path, "2026-11-18")

            self.assertEqual([row["slot"] for row in planned], [1])
            self.assertTrue(all(row["upload_allowed"] for row in planned))

    def test_batch_planner_applies_an_explicit_publish_time_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "content_calendar.json"
            rows = [
                {
                    "date": "2026-11-20",
                    "slot": slot,
                    "status": "planned",
                    "publish_time_ist": "06:00",
                }
                for slot in range(1, 11)
            ]
            path.write_text(json.dumps({"videos": rows}), encoding="utf-8")

            planned = plan_batch.plan_for_date(
                path, "2026-11-20", publish_time="12:00",
            )

        self.assertEqual([row["publish_time_ist"] for row in planned], ["12:00"])

    def test_batch_planner_rejects_malformed_publish_time_overrides(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "content_calendar.json"
            rows = [
                {"date": "2026-11-20", "slot": slot, "status": "planned"}
                for slot in range(1, 11)
            ]
            path.write_text(json.dumps({"videos": rows}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "HH:MM"):
                plan_batch.plan_for_date(
                    path, "2026-11-20", publish_time="9:00",
                )

    def test_batch_planner_ignores_every_slot_outside_the_panchang_plan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "content_calendar.json"
            rows = [
                {
                    "date": "2026-12-30",
                    "slot": slot,
                    "type": "regional_customs",
                    "source": "batch",
                    "status": "planned",
                }
                for slot in range(1, 11)
            ]
            path.write_text(json.dumps({"videos": rows}), encoding="utf-8")

            planned = plan_batch.plan_for_date(path, "2026-12-30")

            self.assertEqual([row["slot"] for row in planned], [1])
            self.assertTrue(all(row["upload_allowed"] for row in planned))

    def test_retry_planner_selects_only_future_slots_without_youtube_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "content_calendar.json"
            rows = [
                {
                    "date": "2026-12-10",
                    "slot": slot,
                    "publish_time_ist": f"{slot:02d}:00",
                    "type": "legacy_daily" if slot == 3 else "story_history",
                    "source": "legacy" if slot == 3 else "batch",
                    "status": "legacy_managed" if slot == 3 else "uploaded",
                    "youtube_video_id": "" if slot == 3 else f"video-{slot}",
                    "facebook_video_id": "",
                }
                for slot in range(1, 11)
            ]
            rows[0]["status"] = "failed_saved_to_drive"
            rows[0]["youtube_video_id"] = ""
            rows[0]["facebook_video_id"] = "facebook-video-1"
            rows[3]["status"] = "skipped"
            rows[3]["youtube_video_id"] = ""
            rows[4]["status"] = "scheduled"
            rows[4]["youtube_video_id"] = ""
            rows[4]["youtube_status"] = "failed"
            rows[5]["youtube_video_id"] = ""
            rows[3]["facebook_video_id"] = "facebook-video-4"
            rows[6]["status"] = "blocked_unverified"
            path.write_text(json.dumps({"videos": rows}), encoding="utf-8")

            planned = plan_batch.plan_for_date(
                path,
                "2026-12-10",
                retry_failed=True,
                now=dt.datetime(2026, 12, 9, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30))),
            )

        self.assertEqual([row["slot"] for row in planned], [1])
        self.assertTrue(all(row["upload_allowed"] for row in planned))
        self.assertFalse(planned[0]["facebook_upload_allowed"])

    def test_retry_planner_omits_slots_inside_youtube_schedule_cutoff(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "content_calendar.json"
            rows = [
                {
                    "date": "2026-12-10",
                    "slot": slot,
                    "publish_time_ist": "06:00",
                    "type": "story_history",
                    "source": "batch",
                    "status": "failed_saved_to_drive",
                    "youtube_video_id": "",
                }
                for slot in range(1, 11)
            ]
            path.write_text(json.dumps({"videos": rows}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "No dispatchable failed videos"):
                plan_batch.plan_for_date(
                    path,
                    "2026-12-10",
                    retry_failed=True,
                    now=dt.datetime(2026, 12, 10, 5, 50, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30))),
                )


class CalendarResultMergeTests(unittest.TestCase):
    def test_merge_records_youtube_failure_even_if_other_platform_succeeded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            calendar_path = root / "content_calendar.json"
            results_path = root / "results"
            results_path.mkdir()
            payload = {
                "start_date": "2026-12-10",
                "end_date": "2026-12-10",
                "videos": [{
                    "date": "2026-12-10",
                    "slot": 1,
                    "publish_time_ist": "06:00",
                    "type": "story_history",
                    "source": "batch",
                    "topic_hi": "परीक्षण कथा",
                    "topic_en": "Test story",
                    "festival_date": "",
                    "festival_tradition": "",
                    "status": "planned",
                    "youtube_status": "not_attempted",
                    "youtube_video_id": "",
                    "drive_link": "",
                    "facebook_video_id": "",
                    "facebook_link": "",
                    "notes": "",
                }],
            }
            calendar_path.write_text(json.dumps(payload), encoding="utf-8")
            (results_path / "RESULT_2026-12-10_1.json").write_text(json.dumps({
                "date": "2026-12-10",
                "slot": 1,
                "status": "scheduled",
                "youtube_status": "failed",
                "youtube_video_id": "",
                "facebook_video_id": "facebook-id",
                "facebook_link": "https://facebook.example/video",
                "publish_time_ist": "12:00",
                "notes": "youtube upload failed: quota exceeded",
            }), encoding="utf-8")

            merged = update_calendar.merge_results(calendar_path, results_path)

        result = merged["videos"][0]
        self.assertEqual(result["youtube_status"], "failed")
        self.assertEqual(result["facebook_video_id"], "facebook-id")
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(result["publish_time_ist"], "12:00")


class FestivalCalendarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calendar = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))

    def test_calendar_has_exactly_one_entry_for_every_date_in_range(self):
        entries = self.calendar["entries"]
        start = date.fromisoformat(self.calendar["start_date"])
        end = date.fromisoformat(self.calendar["end_date"])
        expected = [
            (start + timedelta(days=offset)).isoformat()
            for offset in range((end - start).days + 1)
        ]

        self.assertEqual([entry["date"] for entry in entries], expected)
        self.assertEqual(len({entry["topic"] for entry in entries}), len(entries))

    def test_every_daily_brief_has_notes_and_two_known_sources(self):
        sources = self.calendar["sources"]

        for entry in self.calendar["entries"]:
            with self.subTest(date=entry["date"]):
                self.assertTrue(entry["topic"])
                self.assertTrue(entry["research_notes"])
                self.assertGreaterEqual(len(entry["source_ids"]), 2)
                self.assertTrue(all(source_id in sources for source_id in entry["source_ids"]))
                self.assertTrue(all(
                    sources[source_id]["url"].startswith("https://")
                    for source_id in entry["source_ids"]
                ))

    def test_calendar_marks_evergreen_topics_separately_from_observances(self):
        for entry in self.calendar["entries"]:
            if entry["festival"] is None:
                self.assertIn("evergreen", entry["date_confidence"].lower())

    def test_calendar_includes_monthly_panchang_source_and_event_list(self):
        for entry in self.calendar["entries"]:
            with self.subTest(date=entry["date"]):
                month_source = "drik_november" if entry["date"][5:7] == "11" else "drik_december"
                self.assertIn(month_source, entry["source_ids"])
                self.assertIsInstance(entry["panchang_events"], list)

    def test_key_2026_observance_dates_are_present(self):
        entries = {entry["date"]: entry for entry in self.calendar["entries"]}
        self.assertIn("Chhath Puja", entries["2026-11-15"]["panchang_events"])
        self.assertIn("Karthigai Deepam (Tamil)", entries["2026-11-24"]["panchang_events"])
        self.assertIn("Gita Jayanti", entries["2026-12-20"]["panchang_events"])
        self.assertIn("Arudra Darshan (Tamil)", entries["2026-12-24"]["panchang_events"])


if __name__ == "__main__":
    unittest.main()
