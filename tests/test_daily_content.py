import csv
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "recap"))

import festival_main
import rashi_encyclopedia
import rashifal


class RashifalRulesTests(unittest.TestCase):
    def test_all_144_rashi_and_moon_rashi_combinations_are_present(self):
        rules = json.loads((ROOT / "data" / "rashifal_rules.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rules["rashis"]), 12)
        combinations = [
            (rashi["rashi"], item["moon_rashi"])
            for rashi in rules["rashis"]
            for item in rashi["moon_positions"]
        ]
        self.assertEqual(len(combinations), 144)
        self.assertEqual(len(set(combinations)), 144)

    def test_interpretations_exclude_prohibited_prediction_topics(self):
        rules = json.loads((ROOT / "data" / "rashifal_rules.json").read_text(encoding="utf-8"))
        banned = re.compile(
            r"मृत्यु|गंभीर बीमारी|सटीक धन लाभ|परीक्षा परिणाम|गर्भावस्था|"
            r"\bdeath\b|\bserious illness\b|\bexact financial gain\b|\bexam result\b|\bpregnancy\b",
            re.IGNORECASE,
        )
        for rashi in rules["rashis"]:
            for item in rashi["moon_positions"]:
                with self.subTest(rashi=rashi["rashi"], moon=item["moon_rashi"]):
                    self.assertIsNone(banned.search(item["interpretation"]))

    def test_daily_script_uses_the_supplied_panchang_and_safe_rules(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "panchang.csv"
            fields = [
                "date", "tithi", "paksha", "nakshatra", "moon_rashi",
                "rahu_kaal_start", "rahu_kaal_end", "sunrise",
                "source_location", "source_url",
            ]
            with path.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "date": "2026-11-18",
                    "tithi": "द्वादशी",
                    "paksha": "शुक्ल",
                    "nakshatra": "रोहिणी",
                    "moon_rashi": "मेष",
                    "rahu_kaal_start": "10:30",
                    "rahu_kaal_end": "12:00",
                    "sunrise": "06:10",
                    "source_location": "Varanasi",
                    "source_url": "https://example.org/panchang",
                })
            content = rashifal.build_daily_content("2026-11-18", panchang_path=path)

        research = content["research"]
        self.assertIn("द्वादशी", research["hook"])
        self.assertIn("रोहिणी", research["hook"])
        self.assertIn("मेष", research["hook"])
        self.assertIn("Varanasi", research["hook"])
        self.assertEqual(len(research["scenes"]), 12)
        self.assertGreaterEqual(content["word_count"], 800)
        self.assertEqual(content["sources"][0]["url"], "https://example.org/panchang")
        self.assertEqual(rashifal.DISCLAIMER, "परंपरागत ज्योतिष पर आधारित, मनोरंजन और जानकारी के लिए")

    def test_daily_script_refuses_missing_or_unsourced_panchang(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "panchang.csv"
            path.write_text(
                "date,tithi,paksha,nakshatra,moon_rashi,rahu_kaal_start,rahu_kaal_end,sunrise,source_url\n"
                "2026-11-18,,,,,,,,\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(rashifal.RashifalDataError, "missing"):
                rashifal.build_daily_content("2026-11-18", panchang_path=path)


class RashiEncyclopediaTests(unittest.TestCase):
    def test_all_rashis_use_the_same_chapter_template_and_long_form_script(self):
        first = rashi_encyclopedia.build_rashi_content("मेष")
        last = rashi_encyclopedia.build_rashi_content("मीन")
        first_research = first["research"]
        last_research = last["research"]
        self.assertEqual(
            [scene["title"] for scene in first_research["scenes"]],
            [scene["title"] for scene in last_research["scenes"]],
        )
        self.assertEqual(len(first_research["scenes"]), 12)
        self.assertGreaterEqual(
            len(" ".join([first_research["hook"]] + [
                scene["narration"] for scene in first_research["scenes"]
            ]).split()),
            800,
        )
        festival_main._validate_prepared_bundle(first)

    def test_daily_title_stays_under_70_chars_and_is_slot_unique(self):
        title_a = festival_main._video_title(
            "स्रोत-आधारित सांस्कृतिक परिचय", "2026-11-18",
            "भारतीय परंपरा का विस्तृत परिचय", max_length=69,
            unique_suffix="2026-11-18 Slot 3",
        )
        title_b = festival_main._video_title(
            "स्रोत-आधारित सांस्कृतिक परिचय", "2026-11-18",
            "भारतीय परंपरा का विस्तृत परिचय", max_length=69,
            unique_suffix="2026-11-18 Slot 4",
        )
        self.assertLess(len(title_a), 70)
        self.assertNotEqual(title_a, title_b)
