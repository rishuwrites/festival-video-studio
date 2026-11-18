"""Build deterministic, source-driven daily panchang and rashifal scripts."""

import csv
import datetime as dt
import json
import re
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
PANCHANG_PATH = ROOT / "data" / "panchang_2026_11_18_to_12_31.csv"
RULES_PATH = ROOT / "data" / "rashifal_rules.json"
DISCLAIMER = "परंपरागत ज्योतिष पर आधारित, मनोरंजन और जानकारी के लिए"
REQUIRED_FIELDS = (
    "tithi", "paksha", "nakshatra", "moon_rashi",
    "rahu_kaal_start", "rahu_kaal_end", "sunrise", "source_location",
)
FORBIDDEN = re.compile(
    r"मृत्यु|गंभीर बीमारी|सटीक धन लाभ|परीक्षा परिणाम|गर्भावस्था|"
    r"\bdeath\b|\bserious illness\b|\bexact financial gain\b|\bexam result\b|\bpregnancy\b",
    re.IGNORECASE,
)


class RashifalDataError(ValueError):
    pass


def _read_panchang(path, target_date):
    target = dt.date.fromisoformat(target_date).isoformat()
    with Path(path).open(encoding="utf-8-sig", newline="") as file:
        rows = [row for row in csv.DictReader(file) if (row.get("date") or "").strip() == target]
    if len(rows) != 1:
        raise RashifalDataError(f"Expected exactly one sourced panchang row for {target}")
    row = {key: (value or "").strip() for key, value in rows[0].items()}
    missing = [field for field in REQUIRED_FIELDS if not row.get(field)]
    if missing:
        raise RashifalDataError(f"Panchang row for {target} is missing: {', '.join(missing)}")
    source_url = row.get("source_url", "")
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RashifalDataError(f"Panchang row for {target} needs an HTTPS source_url")
    return row


def _read_rules(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rashis = payload.get("rashis")
    if not isinstance(rashis, list) or len(rashis) != 12:
        raise RashifalDataError("rashifal_rules.json must contain exactly 12 rashis")
    names = {item.get("rashi") for item in rashis}
    if len(names) != 12 or not all(names):
        raise RashifalDataError("Every rashi must have a unique Hindi name")
    for rashi in rashis:
        positions = rashi.get("moon_positions")
        if not isinstance(positions, list) or len(positions) != 12:
            raise RashifalDataError(f"Rashi {rashi['rashi']} must define all 12 Moon positions")
        if len({item.get("moon_rashi") for item in positions}) != 12:
            raise RashifalDataError(f"Rashi {rashi['rashi']} has duplicate Moon positions")
        for item in positions:
            text = item.get("interpretation", "")
            if not text or FORBIDDEN.search(text):
                raise RashifalDataError(f"Unsafe or empty interpretation for {rashi['rashi']}")
    return payload


def build_daily_content(target_date, panchang_path=PANCHANG_PATH, rules_path=RULES_PATH):
    row = _read_panchang(panchang_path, target_date)
    rules = _read_rules(rules_path)
    selected_rashi = next(
        (
            item for item in rules["rashis"]
            if row["moon_rashi"].casefold() in {
                item["rashi"].casefold(), item["rashi_en"].casefold(),
            }
        ),
        None,
    )
    if not selected_rashi:
        raise RashifalDataError(f"Unknown Moon rashi for {target_date}: {row['moon_rashi']}")
    moon_rashi = selected_rashi["rashi"]

    date_text = dt.date.fromisoformat(target_date).strftime("%d-%m-%Y")
    hook = (
        f"आज {date_text} का पंचांग स्रोत में दी गई तिथि और समय के अनुसार प्रस्तुत है। "
        f"तिथि {row['tithi']}, {row['paksha']} पक्ष, नक्षत्र {row['nakshatra']} और "
        f"चंद्र राशि {moon_rashi} है। {row['source_location']} के लिए सूर्योदय "
        f"{row['sunrise']} बजे है। "
        f"राहु काल {row['rahu_kaal_start']} से {row['rahu_kaal_end']} तक दिया गया है। "
        "पंचांग के समय स्थान के अनुसार बदलते हैं; अपने शहर के स्रोत से पुष्टि करें। "
        f"आगे की बारह राशियों की चर्चा {DISCLAIMER} के रूप में है, निश्चित भविष्यवाणी नहीं।"
    )
    scenes = []
    for rashi in rules["rashis"]:
        interpretation = next(
            item["interpretation"] for item in rashi["moon_positions"]
            if item["moon_rashi"] == moon_rashi
        )
        tip = rashi["tip"]
        color = rashi["color"]
        number = rashi["number"]
        narration = (
            f"{rashi['rashi']} राशि के लिए आज का पारंपरिक चिंतन {interpretation} "
            f"आज का छोटा, व्यावहारिक सुझाव है: {tip}। परंपरागत रूप से इस राशि से "
            f"जुड़ा रंग {color} और अंक {number} बताया जाता है; इन्हें शुभता की सांस्कृतिक "
            "मान्यता समझें, किसी घटना या परिणाम की गारंटी नहीं। अपने निर्णय उपलब्ध जानकारी, "
            "अनुभव और वास्तविक परिस्थितियों के आधार पर लें। यह सामान्य सांस्कृतिक सामग्री है, "
            "व्यक्तिगत सलाह या निश्चित फलादेश नहीं।"
        )
        if FORBIDDEN.search(narration):
            raise RashifalDataError(f"Unsafe wording in generated {rashi['rashi']} narration")
        scenes.append({
            "title": f"{rashi['rashi']} राशि",
            "narration": narration,
            "visual_prompt": f"Original calm devotional illustration with a {color} accent, no text",
            "emotion": "happy",
        })

    source = {
        "title": f"Owner-supplied panchang for {target_date}",
        "url": row["source_url"],
        "kind": "owner_supplied_panchang",
    }
    research = {
        "headline": f"{date_text} का पंचांग और बारह राशियाँ",
        "thumbnail_text": "आज का पंचांग",
        "hook": hook,
        "research_summary": (
            f"तिथि: {row['tithi']} ({row['paksha']} पक्ष); नक्षत्र: {row['nakshatra']}; "
            f"चंद्र राशि: {moon_rashi}; स्थान: {row['source_location']}; "
            f"राहु काल: {row['rahu_kaal_start']}–"
            f"{row['rahu_kaal_end']}; सूर्योदय: {row['sunrise']}। स्रोत: {row['source_url']}"
        ),
        "key_facts": [{
            "claim": research_fact,
            "source_titles": [source["title"]],
        } for research_fact in (
            f"तिथि {row['tithi']} ({row['paksha']} पक्ष)",
            f"नक्षत्र {row['nakshatra']} और चंद्र राशि {moon_rashi}",
            f"राहु काल {row['rahu_kaal_start']} से {row['rahu_kaal_end']}",
        )],
        "keywords": ["आज का पंचांग", "बारह राशियाँ", "daily panchang", "rashifal"],
        "scenes": scenes,
    }
    word_count = len(" ".join([hook, *(scene["narration"] for scene in scenes)]).split())
    if word_count < 800:
        raise RashifalDataError(
            f"Daily panchang/rashifal narration has {word_count} words; at least 800 are required"
        )
    return {
        "research": research,
        "sources": [source],
        "research_method": "owner_supplied_panchang_and_fixed_rules",
        "fixed_template": True,
        "word_count": word_count,
    }
