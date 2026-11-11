import json
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CALENDAR_PATH = ROOT / "data" / "india-festival-video-calendar-2026.json"


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
