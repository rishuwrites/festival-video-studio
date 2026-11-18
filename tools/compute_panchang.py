"""Compute Lucknow sunrise panchang and cross-check it against Drik Panchang."""

import argparse
import csv
import datetime as dt
from html.parser import HTMLParser
import json
import re
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "panchang.json"
OUTPUT_PATH = ROOT / "data" / "panchang_2026_11_18_to_12_31.csv"
REPORT_PATH = ROOT / "data" / "panchang_crosscheck_report.csv"
DRIK_DAY_URL = "https://www.drikpanchang.com/panchang/day-panchang.html"
CSV_FIELDS = [
    "date", "tithi", "paksha", "nakshatra", "moon_rashi",
    "rahu_kaal_start", "rahu_kaal_end", "sunrise", "source_location", "source_url",
]
REPORT_FIELDS = [
    "date", "computed_tithi", "source_tithi", "computed_nakshatra",
    "source_nakshatra", "match", "source_url",
]

TITHIS = (
    "प्रतिपदा", "द्वितीया", "तृतीया", "चतुर्थी", "पंचमी",
    "षष्ठी", "सप्तमी", "अष्टमी", "नवमी", "दशमी",
    "एकादशी", "द्वादशी", "त्रयोदशी", "चतुर्दशी",
)
TITHI_EN_HI = {
    "Pratipada": TITHIS[0], "Prathama": TITHIS[0],
    "Dwitiya": TITHIS[1], "Tritiya": TITHIS[2],
    "Chaturthi": TITHIS[3], "Panchami": TITHIS[4],
    "Shashthi": TITHIS[5], "Shashti": TITHIS[5],
    "Saptami": TITHIS[6], "Ashtami": TITHIS[7], "Navami": TITHIS[8],
    "Dashami": TITHIS[9], "Ekadashi": TITHIS[10],
    "Dwadashi": TITHIS[11], "Trayodashi": TITHIS[12],
    "Chaturdashi": TITHIS[13], "Purnima": "पूर्णिमा", "Amavasya": "अमावस्या",
}
NAKSHATRAS_EN_HI = {
    "Ashwini": "अश्विनी", "Bharani": "भरणी", "Krittika": "कृत्तिका",
    "Rohini": "रोहिणी", "Mrigashira": "मृगशीर्ष", "Ardra": "आर्द्रा",
    "Punarvasu": "पुनर्वसु", "Pushya": "पुष्य", "Ashlesha": "आश्लेषा",
    "Magha": "मघा", "Purva Phalguni": "पूर्वा फाल्गुनी",
    "Uttara Phalguni": "उत्तरा फाल्गुनी", "Hasta": "हस्त",
    "Chitra": "चित्रा", "Swati": "स्वाती", "Vishakha": "विशाखा",
    "Anuradha": "अनुराधा", "Jyeshtha": "ज्येष्ठा", "Mula": "मूल",
    "Purva Ashadha": "पूर्वाषाढ़ा", "Uttara Ashadha": "उत्तराषाढ़ा",
    "Shravana": "श्रवण", "Dhanishtha": "धनिष्ठा",
    "Shatabhisha": "शतभिषा", "Purva Bhadrapada": "पूर्वाभाद्रपदा",
    "Uttara Bhadrapada": "उत्तराभाद्रपदा", "Revati": "रेवती",
}
RASHIS = (
    "मेष", "वृषभ", "मिथुन", "कर्क", "सिंह", "कन्या",
    "तुला", "वृश्चिक", "धनु", "मकर", "कुंभ", "मीन",
)
RAHU_SEGMENT_BY_WEEKDAY = {
    0: 2,  # Monday
    1: 7,  # Tuesday
    2: 5,  # Wednesday
    3: 6,  # Thursday
    4: 4,  # Friday
    5: 3,  # Saturday
    6: 8,  # Sunday
}


def _load_swe():
    try:
        import swisseph
    except ImportError as exc:
        raise RuntimeError(
            "pyswisseph is required; install the requirements for a supported Python runtime"
        ) from exc
    return swisseph


def _validate_location(location):
    required = ("name", "latitude", "longitude", "timezone")
    missing = [key for key in required if key not in location]
    if missing:
        raise ValueError(f"PANCHANG_LOCATION is missing: {', '.join(missing)}")
    latitude = float(location["latitude"])
    longitude = float(location["longitude"])
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("PANCHANG_LOCATION latitude/longitude are out of range")
    ZoneInfo(str(location["timezone"]))
    return latitude, longitude


def _local_time_from_jd(julian_day, timezone):
    utc = dt.datetime.fromtimestamp(
        (julian_day - 2440587.5) * 86400,
        tz=dt.timezone.utc,
    )
    return utc.astimezone(timezone)


def _sun_event(swe, date, location, event_flag):
    utc_midnight = swe.julday(date.year, date.month, date.day, 0.0)
    geopos = (
        float(location["longitude"]),
        float(location["latitude"]),
        float(location.get("elevation_m", 0)),
    )
    result, times = swe.rise_trans(
        utc_midnight,
        swe.SUN,
        event_flag,
        geopos,
        0,
        0,
        swe.FLG_SWIEPH,
    )
    if result != 0:
        raise RuntimeError(f"Swiss Ephemeris could not calculate the Sun event for {date}")
    return times[0]


def _tithi_and_paksha(sun_longitude, moon_longitude):
    elongation = (moon_longitude - sun_longitude) % 360
    number = int(elongation // 12) + 1
    paksha = "शुक्ल" if number <= 15 else "कृष्ण"
    paksha_tithi = (number - 1) % 15 + 1
    if paksha_tithi == 15:
        name = "पूर्णिमा" if paksha == "शुक्ल" else "अमावस्या"
    else:
        name = TITHIS[paksha_tithi - 1]
    return name, paksha


def _rahu_kaal(date, sunrise, sunset):
    daylight = sunset - sunrise
    eighth = daylight / 8
    segment = RAHU_SEGMENT_BY_WEEKDAY[date.weekday()]
    start = sunrise + eighth * (segment - 1)
    end = start + eighth
    return start.strftime("%H:%M"), end.strftime("%H:%M")


def drik_day_url(date, geoname_id):
    if not geoname_id:
        raise ValueError("PANCHANG_LOCATION must define drik_geoname_id for cross-checks")
    return (
        f"{DRIK_DAY_URL}?date={date.strftime('%d/%m/%Y')}"
        f"&geoname-id={geoname_id}"
    )


def compute_day(date, location, swe_module=None, source_url=""):
    """Compute tithi, nakshatra, moon rashi, sunrise, and Rahu Kaal at sunrise."""
    if isinstance(date, str):
        date = dt.date.fromisoformat(date)
    _validate_location(location)
    swe = swe_module or _load_swe()
    timezone = ZoneInfo(str(location["timezone"]))
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    sunrise_jd = _sun_event(swe, date, location, swe.CALC_RISE)
    sunset_jd = _sun_event(swe, date, location, swe.CALC_SET)
    sunrise = _local_time_from_jd(sunrise_jd, timezone)
    sunset = _local_time_from_jd(sunset_jd, timezone)
    flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL
    sun_longitude = swe.calc_ut(sunrise_jd, swe.SUN, flags)[0][0]
    moon_longitude = swe.calc_ut(sunrise_jd, swe.MOON, flags)[0][0]
    tithi, paksha = _tithi_and_paksha(sun_longitude, moon_longitude)
    nakshatra_index = int(moon_longitude * 27 / 360) % 27
    rashi_index = int(moon_longitude // 30) % 12
    rahu_start, rahu_end = _rahu_kaal(date, sunrise, sunset)
    return {
        "date": date.isoformat(),
        "tithi": tithi,
        "paksha": paksha,
        "nakshatra": tuple(NAKSHATRAS_EN_HI.values())[nakshatra_index],
        "moon_rashi": RASHIS[rashi_index],
        "rahu_kaal_start": rahu_start,
        "rahu_kaal_end": rahu_end,
        "sunrise": sunrise.strftime("%H:%M"),
        "source_location": str(location["name"]),
        "source_url": source_url,
    }


class _DrikTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = []
        self.cells = {}
        self.mode = ""
        self.depth = 0
        self.text = []
        self.images = []
        self.pending_key = ""

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "title":
            self.mode = "title"
            self.depth = 0
        elif tag == "div":
            classes = set(attributes.get("class", "").split())
            if not self.mode and "dpTableKey" in classes:
                self.mode = "key"
                self.depth = 1
                self.text = []
                self.images = []
            elif not self.mode and "dpTableValue" in classes:
                self.mode = "value"
                self.depth = 1
                self.text = []
                self.images = []
            elif self.mode in ("key", "value"):
                self.depth += 1
        if self.mode == "value" and tag == "img" and attributes.get("alt"):
            self.images.append(attributes["alt"].strip())

    def handle_endtag(self, tag):
        if tag == "title" and self.mode == "title":
            self.mode = ""
        elif tag == "div" and self.mode in ("key", "value"):
            self.depth -= 1
            if self.depth == 0:
                value = " ".join(" ".join(self.text).split())
                if self.mode == "key":
                    self.pending_key = value
                elif self.pending_key:
                    self.cells[self.pending_key] = {
                        "text": value,
                        "images": list(self.images),
                    }
                    self.pending_key = ""
                self.mode = ""
        elif self.mode == "title" and tag == "title":
            self.mode = ""

    def handle_data(self, data):
        if self.mode == "title":
            self.title.append(data)
        elif self.mode in ("key", "value"):
            self.text.append(data)


def _tithi_candidates(cell):
    result = []
    for alt in cell["images"]:
        parts = alt.split()
        if len(parts) >= 2 and parts[0] in ("Shukla", "Krishna"):
            english_name = " ".join(parts[1:])
            if english_name in TITHI_EN_HI:
                result.append((parts[0], TITHI_EN_HI[english_name]))
    return result


def _nakshatra_candidates(cell):
    return [
        NAKSHATRAS_EN_HI[alt]
        for alt in cell["images"]
        if alt in NAKSHATRAS_EN_HI
    ]


def _first_end_time(text, date):
    match = re.search(
        r"\bupto\s+(\d{1,2}:\d{2})\s*(AM|PM)"
        r"(?:,\s*([A-Za-z]+\s+\d{1,2}))?",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    time_value = dt.datetime.strptime(
        f"{match.group(1)} {match.group(2).upper()}",
        "%I:%M %p",
    ).time()
    end_date = date
    if match.group(3):
        end_date = dt.datetime.strptime(
            f"{match.group(3)} {date.year}",
            "%b %d %Y",
        ).date()
    return dt.datetime.combine(end_date, time_value)


def _at_sunrise(candidates, cell, date, sunrise):
    if not candidates:
        return ""
    end_time = _first_end_time(cell["text"], date)
    if end_time and end_time <= dt.datetime.combine(date, sunrise) and len(candidates) > 1:
        return candidates[1]
    return candidates[0]


def parse_drik_panchang(html, date, location):
    """Extract sunrise tithi and nakshatra from a Drik daily Panchang page."""
    if isinstance(date, str):
        date = dt.date.fromisoformat(date)
    parser = _DrikTableParser()
    parser.feed(html)
    title = " ".join(parser.title).strip()
    if str(location["name"]).split(",")[0].casefold() not in title.casefold():
        raise ValueError(f"Drik source page is not for {location['name']}: {title!r}")
    required = ("Sunrise", "Tithi", "Nakshatra")
    missing = [key for key in required if key not in parser.cells]
    if missing:
        raise ValueError(f"Drik source page is missing: {', '.join(missing)}")

    sunrise_match = re.search(
        r"(\d{1,2}:\d{2})\s*(AM|PM)",
        parser.cells["Sunrise"]["text"],
        re.IGNORECASE,
    )
    if not sunrise_match:
        raise ValueError("Drik source page has no parseable sunrise time")
    sunrise = dt.datetime.strptime(
        f"{sunrise_match.group(1)} {sunrise_match.group(2).upper()}",
        "%I:%M %p",
    ).time()
    tithi = _at_sunrise(
        _tithi_candidates(parser.cells["Tithi"]),
        parser.cells["Tithi"],
        date,
        sunrise,
    )
    nakshatra = _at_sunrise(
        _nakshatra_candidates(parser.cells["Nakshatra"]),
        parser.cells["Nakshatra"],
        date,
        sunrise,
    )
    if not tithi or not nakshatra:
        raise ValueError("Drik source page has no parseable tithi or nakshatra")
    return {
        "source_tithi": f"{'शुक्ल' if tithi[0] == 'Shukla' else 'कृष्ण'} {tithi[1]}",
        "source_nakshatra": nakshatra,
    }


def fetch_drik_panchang(date, location):
    url = drik_day_url(date, location.get("drik_geoname_id"))
    request = Request(url, headers={"User-Agent": "PanchangCalendar/1.0"})
    with urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", "replace")
    return parse_drik_panchang(html, date, location), url


def _date_range(start, end):
    if start > end:
        raise ValueError("Start date must not be after end date")
    current = start
    while current <= end:
        yield current
        current += dt.timedelta(days=1)


def write_rows(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def compute_range(start, end, location):
    rows = []
    for date in _date_range(start, end):
        source_url = drik_day_url(date, location["drik_geoname_id"])
        rows.append(compute_day(date, location, source_url=source_url))
    return rows


def crosscheck_rows(rows, location, delay_seconds=0.25):
    reports = []
    for index, row in enumerate(rows):
        date = dt.date.fromisoformat(row["date"])
        url = drik_day_url(date, location["drik_geoname_id"])
        source_tithi = ""
        source_nakshatra = ""
        try:
            source, _ = fetch_drik_panchang(date, location)
            source_tithi = source["source_tithi"]
            source_nakshatra = source["source_nakshatra"]
        except (URLError, TimeoutError, UnicodeError, ValueError) as exc:
            print(
                f"Cross-check requires review for {date}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        computed_tithi = f"{row['paksha']} {row['tithi']}"
        matched = (
            computed_tithi == source_tithi
            and row["nakshatra"] == source_nakshatra
        )
        reports.append({
            "date": row["date"],
            "computed_tithi": computed_tithi,
            "source_tithi": source_tithi,
            "computed_nakshatra": row["nakshatra"],
            "source_nakshatra": source_nakshatra,
            "match": "match" if matched else "needs_review",
            "source_url": url,
        })
        if index + 1 < len(rows):
            time.sleep(delay_seconds)
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start_date", default="2026-11-18")
    parser.add_argument("--to", dest="end_date", default="2026-12-31")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--no-crosscheck", action="store_true")
    args = parser.parse_args()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    location = config.get("PANCHANG_LOCATION")
    if not isinstance(location, dict):
        raise SystemExit("config/panchang.json needs a PANCHANG_LOCATION object")
    try:
        rows = compute_range(
            dt.date.fromisoformat(args.start_date),
            dt.date.fromisoformat(args.end_date),
            location,
        )
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(f"Panchang computation failed: {exc}") from exc
    write_rows(args.output, rows, CSV_FIELDS)
    print(f"Wrote {len(rows)} computed panchang rows to {args.output}")
    if not args.no_crosscheck:
        reports = crosscheck_rows(rows, location)
        write_rows(args.report, reports, REPORT_FIELDS)
        matches = sum(report["match"] == "match" for report in reports)
        print(
            f"Wrote {len(reports)} source comparisons to {args.report}; "
            f"{matches} match and {len(reports) - matches} need review"
        )


if __name__ == "__main__":
    main()
