import json
import csv
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
        })
        previous = self.root / "previous.json"
        previous.write_text(json.dumps(first), encoding="utf-8")
        rebuilt = self._build(previous)
        self.assertEqual(rebuilt["videos"][0]["status"], "uploaded")
        self.assertEqual(rebuilt["videos"][0]["youtube_video_id"], "video-123")
        self.assertEqual(rebuilt["videos"][0]["drive_link"], "https://drive.google.com/file/d/example/view")

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

    def test_batch_planner_selects_exactly_one_day_and_validates_all_slots(self):
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
            self.assertEqual([row["slot"] for row in planned], list(range(1, 11)))
            self.assertEqual(sum(row["upload_allowed"] for row in planned), 10)

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
            self.assertEqual([row["slot"] for row in planned], [1, 3, 4, 5, 6, 7, 9, 10])
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

            self.assertEqual([row["slot"] for row in planned], [1, 2, 4, 5, 6, 7, 8, 9, 10])
            self.assertTrue(all(row["upload_allowed"] for row in planned))

    def test_batch_planner_allows_ten_batch_slots_without_legacy_entry(self):
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

            self.assertEqual(len(planned), 10)
            self.assertTrue(all(row["upload_allowed"] for row in planned))


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
