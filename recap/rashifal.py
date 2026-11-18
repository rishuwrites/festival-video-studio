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


def build_panchang_content(
    target_date,
    include_rashifal=False,
    panchang_path=PANCHANG_PATH,
    rules_path=RULES_PATH,
    festivals_path=ROOT / "data" / "festival_dates_2026.json",
):
    row = _read_panchang(panchang_path, target_date)
    date_text = dt.date.fromisoformat(target_date).strftime("%d-%m-%Y")
    observances = json.loads(Path(festivals_path).read_text(encoding="utf-8")).get(
        "entries", [],
    )
    verified_observances = [
        item["name_hi"]
        for item in observances
        if item.get("verified") is True and item.get("date") == target_date
    ]
    vrat_text = (
        "स्रोत से सत्यापित आज के पर्व या व्रत: " + " और ".join(verified_observances) + "।"
        if verified_observances else
        "इस कैलेंडर में आज के लिए कोई स्रोत-सत्यापित व्रत दर्ज नहीं है; "
        "अपने शहर के विश्वसनीय पंचांग और पारिवारिक परंपरा से पुष्टि करें।"
    )
    hook = (
        f"आज {date_text} का पंचांग {row['source_location']} के लिए प्रस्तुत है। "
        f"स्रोत में तिथि {row['tithi']}, {row['paksha']} पक्ष, नक्षत्र "
        f"{row['nakshatra']} और चंद्र राशि {row['moon_rashi']} दी गई है। "
        f"सूर्योदय {row['sunrise']} बजे तथा राहु काल {row['rahu_kaal_start']} "
        f"से {row['rahu_kaal_end']} तक है। {vrat_text} ये समय और observance "
        "स्थान तथा परंपरा के अनुसार बदल सकते हैं।"
    )
    scenes = [
        {
            "title": "तिथि और पक्ष",
            "narration": (
                f"आज की तिथि {row['tithi']} और पक्ष {row['paksha']} है। तिथि को "
                "चंद्रमा और सूर्य के बीच कोणीय अंतर से जुड़े चंद्र दिवस के रूप में "
                "समझा जाता है। यह अंग्रेज़ी कैलेंडर की तारीख जैसी स्थिर आधी रात से "
                "आधी रात की अवधि नहीं होती; तिथि दिन के बीच में बदल सकती है। इसीलिए "
                "एक ही तारीख पर अलग शहरों या अलग व्रत-नियमों में अलग पालन दिख सकता है। "
                "आज के लिए हम वही नाम बता रहे हैं जो दिए गए शहर-विशेष स्रोत में दर्ज है। "
                "व्रत का निर्णय लेते समय केवल सामान्य इंटरनेट सूची नहीं, बल्कि अपने "
                "स्थान का पंचांग और उस व्रत की परंपरा देखें।"
            ),
            "visual_prompt": "A calm illustrated Indian panchang page with moon phases, no text",
            "emotion": "happy",
        },
        {
            "title": "नक्षत्र",
            "narration": (
                f"आज के पंचांग में नक्षत्र {row['nakshatra']} लिखा है। नक्षत्र चंद्रमा "
                "की आकाश में स्थिति को बताने वाली पारंपरिक भारतीय गणना का हिस्सा है। "
                "यहाँ इसका उल्लेख पंचांग की जानकारी के रूप में है, किसी व्यक्ति के "
                "स्वभाव या भविष्य की निश्चित भविष्यवाणी के रूप में नहीं। नक्षत्र का "
                "समय भी दिन के दौरान बदल सकता है; सुबह का नाम और पूरे दिन का नाम हमेशा "
                "एक जैसा हो, यह आवश्यक नहीं। इस वीडियो में हम स्रोत के दिए हुए मान को "
                "स्पष्ट कर रहे हैं, और समय-संबंधी निर्णय के लिए स्थानीय पंचांग देखने "
                "की सलाह देते हैं।"
            ),
            "visual_prompt": "A star map over a traditional observatory, respectful and factual, no text",
            "emotion": "happy",
        },
        {
            "title": "चंद्र राशि",
            "narration": (
                f"स्रोत में आज की चंद्र राशि {row['moon_rashi']} दी गई है। पंचांग में "
                "यह चंद्रमा की गणितीय स्थिति को संक्षेप में बताने वाला संकेत है। इसे "
                "सूर्य राशि या किसी व्यक्ति की पूरी जन्मकुंडली से न मिलाएँ; ये अलग "
                "संदर्भ हैं। हमारा उद्देश्य आज के पंचांग के शब्दों को समझाना है, "
                "व्यक्तिगत सलाह देना नहीं। यदि अलग ऐप या पंचांग में अलग राशि दिखे तो "
                "पहले दोनों के शहर, समय और गणना-पद्धति की जाँच करें। स्थान या समय क्षेत्र "
                "बदलने पर कुछ सीमांत समयों की प्रस्तुति भी बदल सकती है।"
            ),
            "visual_prompt": "The Moon moving along a circular star chart, educational illustration, no text",
            "emotion": "happy",
        },
        {
            "title": "सूर्योदय",
            "narration": (
                f"आज {row['source_location']} के लिए दिया गया सूर्योदय "
                f"{row['sunrise']} बजे है। सूर्योदय का समय अक्षांश, देशांतर, ऊँचाई "
                "और तारीख के अनुसार बदलता है; इसलिए एक शहर का समय पूरे भारत पर लागू "
                "नहीं होता। बहुत-से पंचांग-आधारित व्रत-नियमों में सूर्योदय के समय की "
                "तिथि महत्त्वपूर्ण हो सकती है। किसी व्रत की शुरुआत या पारण तय करने से "
                "पहले अपने क्षेत्र के विश्वसनीय स्रोत में स्थान का नाम और समय दोनों "
                "मिलाएँ। हम यहाँ उपलब्ध स्रोत का समय पढ़ रहे हैं, नया मुहूर्त नहीं "
                "बना रहे।"
            ),
            "visual_prompt": "Sunrise over Lucknow rooftops and a temple courtyard, no text",
            "emotion": "happy",
        },
        {
            "title": "राहु काल",
            "narration": (
                f"दिए गए स्रोत के अनुसार राहु काल {row['rahu_kaal_start']} से "
                f"{row['rahu_kaal_end']} तक है। यह पारंपरिक पंचांग में दिन के एक "
                "खंड का नाम है। अलग स्थानों पर सूर्योदय और सूर्यास्त बदलने के कारण "
                "इस अवधि की घड़ी भी बदल सकती है। इसे स्वास्थ्य, सुरक्षा या किसी "
                "अनिवार्य दैनिक काम के बारे में वैज्ञानिक निष्कर्ष न समझें। जो लोग "
                "इस परंपरा का पालन करते हैं, वे अपनी स्थानीय रीति के अनुसार इसे देखते "
                "हैं; अन्य लोग अपनी परिस्थिति और आवश्यकताओं को प्राथमिकता देते हैं। "
                "यहाँ समय केवल स्रोत-सूचना के रूप में साझा किया जा रहा है।"
            ),
            "visual_prompt": "A daylight timeline with a highlighted traditional time segment, no words",
            "emotion": "happy",
        },
        {
            "title": "आज का सत्यापित व्रत",
            "narration": (
                f"{vrat_text} यदि आपके परिवार या क्षेत्र में कोई अन्य व्रत माना जाता "
                "है, तो उसके नाम, तिथि और विधि को स्थानीय परंपरा से जाँचें। चंद्र "
                "तिथि के आरंभ और समाप्ति के समय तथा सूर्योदय या प्रदोष जैसे नियमों "
                "के कारण पालन-दिन अलग हो सकता है। हम किसी अप्रमाणित तिथि को पर्व "
                "सूची में नहीं जोड़ते और न ही हर क्षेत्र की एक ही विधि बताते हैं। "
                "व्रत स्वास्थ्य की स्थिति, आयु और व्यक्तिगत जरूरतों के अनुसार अलग "
                "हो सकता है; कठिन उपवास के बारे में योग्य चिकित्सक की सलाह लें।"
            ),
            "visual_prompt": "A family consulting a regional calendar together, inclusive, no text",
            "emotion": "happy",
        },
        {
            "title": "स्रोत और स्थान",
            "narration": (
                f"यह जानकारी {row['source_location']} के लिए दिए गए पंचांग स्रोत "
                "से ली गई है। किसी दूसरे शहर में सूर्योदय, राहु काल या तिथि-सीमा "
                "अलग दिख सकती है। तारीखों की जाँच में स्रोत का पूरा नाम, शहर, समय "
                "क्षेत्र और अद्यतन वर्ष देखना उपयोगी है। यदि दो स्रोतों में अंतर "
                "हो, तो एक को चुपचाप सही मानने के बजाय उनके स्थान और पालन-परंपरा "
                "की तुलना करें। इस वीडियो की विवरण-पंक्ति में मूल स्रोत का लिंक "
                "दिया गया है ताकि दर्शक स्वयं जाँच सकें।"
            ),
            "visual_prompt": "A reader comparing two city-specific almanacs at a desk, no text",
            "emotion": "happy",
        },
        {
            "title": "पंचांग को कैसे पढ़ें",
            "narration": (
                "पंचांग के अलग-अलग अंग अलग सवालों का जवाब देते हैं। तिथि चंद्र दिवस "
                "बताती है, पक्ष चंद्र मास के बढ़ने या घटने वाले हिस्से को, नक्षत्र "
                "चंद्रमा की स्थिति को, और सूर्योदय तथा राहु काल दिन के समय-संदर्भ "
                "को। किसी त्योहार की तारीख तय करने में केवल एक अंग पर्याप्त नहीं "
                "होता; स्थान, परंपरा और उस observance का विशेष नियम भी देखा जाता है। "
                "इसलिए छोटे कैलेंडर कार्ड को पूरी पूजा-विधि न मानें। समय संवेदनशील "
                "निर्णय से पहले भरोसेमंद स्थानीय पंचांग या परंपरा के जानकार से पुष्टि "
                "करना बेहतर है।"
            ),
            "visual_prompt": "A clear illustrated almanac with icons for moon, stars, sunrise, no text",
            "emotion": "happy",
        },
        {
            "title": "दिन का सार",
            "narration": (
                f"आज के सार में फिर याद रखें: तिथि {row['tithi']} ({row['paksha']} "
                f"पक्ष), नक्षत्र {row['nakshatra']}, चंद्र राशि {row['moon_rashi']}, "
                f"{row['source_location']} का सूर्योदय {row['sunrise']} बजे, और "
                f"राहु काल {row['rahu_kaal_start']} से {row['rahu_kaal_end']} तक "
                "दिया गया है। " + vrat_text + " इन विवरणों को अपने शहर और "
                "परंपरा के अनुसार जाँचें। पंचांग को सांस्कृतिक समय-सूचक की तरह "
                "समझें; इसे निश्चित फलादेश, चिकित्सकीय सलाह या जरूरी निर्णयों का "
                "विकल्प न बनाएँ।"
            ),
            "visual_prompt": "A peaceful closing view of a panchang beside a sunrise window, no text",
            "emotion": "happy",
        },
    ]

    if include_rashifal:
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
            raise RashifalDataError(
                f"Unknown Moon rashi for {target_date}: {row['moon_rashi']}"
            )
        moon_rashi = selected_rashi["rashi"]
        interpretation = next(
            item["interpretation"] for item in selected_rashi["moon_positions"]
            if item["moon_rashi"] == row["moon_rashi"]
        )
        scenes.append({
            "title": "संक्षिप्त पारंपरिक राशिफल",
            "narration": (
                f"{moon_rashi} राशि के लिए आज का संक्षिप्त पारंपरिक चिंतन है: "
                f"{interpretation}। इसे केवल सांस्कृतिक विचार के रूप में लें, "
                "निश्चित भविष्यवाणी या व्यक्तिगत सलाह के रूप में नहीं।"
            ),
            "visual_prompt": "A calm devotional illustration with a subtle zodiac motif, no text",
            "emotion": "happy",
        })

    source = {
        "title": f"Owner-supplied panchang for {target_date}",
        "url": row["source_url"],
        "kind": "owner_supplied_panchang",
    }
    research = {
        "headline": f"{date_text} का आज का पंचांग",
        "thumbnail_text": "आज का पंचांग",
        "hook": hook,
        "research_summary": (
            f"तिथि: {row['tithi']} ({row['paksha']} पक्ष); नक्षत्र: {row['nakshatra']}; "
            f"चंद्र राशि: {row['moon_rashi']}; स्थान: {row['source_location']}; "
            f"राहु काल: {row['rahu_kaal_start']}–{row['rahu_kaal_end']}; "
            f"सूर्योदय: {row['sunrise']}; सत्यापित व्रत: "
            f"{', '.join(verified_observances) if verified_observances else 'कोई दर्ज नहीं'}। "
            f"स्रोत: {row['source_url']}"
        ),
        "key_facts": [{
            "claim": research_fact,
            "source_titles": [source["title"]],
        } for research_fact in (
            f"तिथि {row['tithi']} ({row['paksha']} पक्ष)",
            f"नक्षत्र {row['nakshatra']} और चंद्र राशि {row['moon_rashi']}",
            f"सूर्योदय {row['sunrise']} और राहु काल {row['rahu_kaal_start']}–{row['rahu_kaal_end']}",
            vrat_text,
        )],
        "keywords": ["आज का पंचांग", "तिथि", "नक्षत्र", "राहु काल"],
        "scenes": scenes,
    }
    narration = " ".join(
        [hook, *(scene["narration"] for scene in scenes)]
    )
    word_count = len(narration.split())
    if word_count < 800:
        raise RashifalDataError(
            f"Daily panchang narration has {word_count} words; at least 800 are required"
        )
    return {
        "research": research,
        "sources": [source],
        "research_method": "owner_supplied_panchang_and_fixed_template",
        "fixed_template": True,
        "word_count": word_count,
    }
