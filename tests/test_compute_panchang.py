import datetime as dt
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "tools"))
import compute_panchang


LOCATION = {
    "name": "Lucknow, Uttar Pradesh",
    "latitude": 26.8467,
    "longitude": 80.9462,
    "elevation_m": 126,
    "timezone": "Asia/Kolkata",
    "drik_geoname_id": "1264733",
}
DRIK_BASE = "https://www.drikpanchang.com/panchang/day-panchang.html?date="
PUBLISHED_EXPECTATIONS = {
    "2026-11-18": {
        "tithi": "नवमी",
        "paksha": "शुक्ल",
        "nakshatra": "शतभिषा",
        "source_url": f"{DRIK_BASE}18/11/2026&geoname-id=1264733",
    },
    "2026-11-21": {
        "tithi": "एकादशी",
        "paksha": "शुक्ल",
        "nakshatra": "उत्तराभाद्रपदा",
        "source_url": f"{DRIK_BASE}21/11/2026&geoname-id=1264733",
    },
    "2026-12-20": {
        "tithi": "एकादशी",
        "paksha": "शुक्ल",
        "nakshatra": "अश्विनी",
        "source_url": f"{DRIK_BASE}20/12/2026&geoname-id=1264733",
    },
}


@unittest.skipUnless(
    importlib.util.find_spec("swisseph"),
    "pyswisseph wheel is unavailable for this interpreter",
)
class PublishedPanchangCalculationTests(unittest.TestCase):
    def test_three_fixed_sunrise_values_match_cited_drik_pages(self):
        for date_text, expected in PUBLISHED_EXPECTATIONS.items():
            with self.subTest(date=date_text, source=expected["source_url"]):
                row = compute_panchang.compute_day(
                    dt.date.fromisoformat(date_text),
                    LOCATION,
                    source_url=expected["source_url"],
                )
                for field in ("tithi", "paksha", "nakshatra"):
                    self.assertEqual(row[field], expected[field])


class PanchangHelperTests(unittest.TestCase):
    def test_drik_url_is_date_and_location_specific(self):
        self.assertEqual(
            compute_panchang.drik_day_url(
                dt.date(2026, 11, 18),
                "1264733",
            ),
            f"{DRIK_BASE}18/11/2026&geoname-id=1264733",
        )

    def test_rejects_invalid_location_coordinates(self):
        with self.assertRaisesRegex(ValueError, "out of range"):
            compute_panchang.compute_day(
                "2026-11-18",
                {**LOCATION, "latitude": 100},
                swe_module=object(),
            )

    def test_drik_parser_uses_value_at_sunrise(self):
        html = """
        <title>November 21, 2026 Panchang for Lucknow, Uttar Pradesh</title>
        <div class="dpTableKey">Sunrise</div>
        <div class="dpTableValue">06:30 AM</div>
        <div class="dpTableKey">Tithi</div>
        <div class="dpTableValue">
          <a>Ekadashi</a> upto 06:31 AM
          <img alt="Shukla Ekadashi">
          <a>Dwadashi</a> upto 04:56 AM, Nov 22
          <img alt="Shukla Dwadashi">
        </div>
        <div class="dpTableKey">Nakshatra</div>
        <div class="dpTableValue">
          <a>Uttara Bhadrapada</a> upto 06:50 AM
          <img alt="Uttara Bhadrapada">
          <a>Revati</a> upto 05:54 AM, Nov 22
          <img alt="Revati">
        </div>
        """
        self.assertEqual(
            compute_panchang.parse_drik_panchang(
                html,
                "2026-11-21",
                LOCATION,
            ),
            {
                "source_tithi": "शुक्ल एकादशी",
                "source_nakshatra": "उत्तराभाद्रपदा",
            },
        )

    def test_drik_parser_selects_second_tithi_when_first_ends_before_sunrise(self):
        html = """
        <title>November 18, 2026 Panchang for Lucknow, Uttar Pradesh</title>
        <div class="dpTableKey">Sunrise</div>
        <div class="dpTableValue">06:28 AM</div>
        <div class="dpTableKey">Tithi</div>
        <div class="dpTableValue">
          <a>Ashtami</a> upto 06:04 AM, Nov 18
          <img alt="Shukla Ashtami">
          <a>Navami</a> upto Full Night
          <img alt="Shukla Navami">
        </div>
        <div class="dpTableKey">Nakshatra</div>
        <div class="dpTableValue">
          <a>Dhanishtha</a> upto 04:34 AM, Nov 18
          <img alt="Dhanishtha">
          <a>Shatabhisha</a>
          <img alt="Shatabhisha">
        </div>
        """
        self.assertEqual(
            compute_panchang.parse_drik_panchang(html, "2026-11-18", LOCATION),
            {
                "source_tithi": "शुक्ल नवमी",
                "source_nakshatra": "शतभिषा",
            },
        )


if __name__ == "__main__":
    unittest.main()
