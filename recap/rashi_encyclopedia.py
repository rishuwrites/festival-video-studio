"""Build original, consistently structured traditional-rashi encyclopedia episodes."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILES_PATH = ROOT / "data" / "rashi_profiles.json"
DISCLAIMER = "सभी विवरण परंपरागत ज्योतिष के रूप में हैं, निश्चित वैज्ञानिक दावे नहीं।"

CHAPTERS = (
    "परंपरागत राशि-चिह्न",
    "तत्व और उसका सांस्कृतिक अर्थ",
    "स्वामी ग्रह की परंपरा",
    "पारंपरिक शुभ दिन",
    "स्वभाव और गुण",
    "पारंपरिक रत्न",
    "मंत्र और देव परंपरा",
    "करियर संबंधी पारंपरिक दृष्टि",
    "संबंधों में संवाद",
    "अनुकूलता के पारंपरिक दावे",
    "मंदिर, व्रत और पर्व",
    "लोकधारणा और तथ्य",
)


def build_rashi_content(rashi_name, profiles_path=PROFILES_PATH):
    payload = json.loads(Path(profiles_path).read_text(encoding="utf-8"))
    profiles = payload.get("rashis")
    if not isinstance(profiles, list) or len(profiles) != 12:
        raise ValueError("rashi_profiles.json must contain exactly 12 rashi profiles")
    profile = next(
        (item for item in profiles if item.get("name_hi") == rashi_name
         or item.get("name_en", "").casefold() == rashi_name.casefold()),
        None,
    )
    if not profile:
        raise ValueError(f"Unknown rashi profile: {rashi_name}")

    sections = (
        f"परंपरागत राशि-चिह्न {profile['symbol']}",
        f"इस राशि का पारंपरिक तत्व {profile['element']} बताया जाता है।",
        f"परंपरा में {profile['ruling_planet']} को इसका स्वामी ग्रह कहा जाता है।",
        f"इस राशि के साथ {profile['lucky_day']} को पारंपरिक शुभ दिन के रूप में जोड़ा जाता है।",
        f"स्वभाव के वर्णन में {profile['nature_and_traits']} जैसे गुण बताए जाते हैं।",
        f"परंपरागत रत्न के रूप में {profile['traditional_gemstone']} का उल्लेख मिलता है; रत्न पहनना आवश्यक या परिणाम की गारंटी नहीं।",
        f"देवता और मंत्र की परंपरा के विषय में {profile['mantra_and_deity']} का संदर्भ मिलता है। अलग-अलग परिवारों और क्षेत्रों में पूजा-पद्धतियाँ बदल सकती हैं।",
        profile["career"],
        profile["relationships"],
        "अनुकूलता के पारंपरिक दावे किसी रिश्ते का निश्चित परिणाम नहीं बताते। आपसी संवाद, सीमाओं का सम्मान, साझा अपेक्षाएँ और भरोसा संबंधों के व्यावहारिक आधार हैं।",
        profile["temples_vrats_festivals"],
        profile["myths_vs_tradition"],
    )
    scenes = []
    for chapter, detail in zip(CHAPTERS, sections):
        narration = (
            f"{profile['name_hi']} राशि के {chapter} को समझते समय इसे परंपरागत ज्योतिष की "
            f"भाषा में देखना उपयोगी है। {detail} यह जानकारी सांस्कृतिक परिचय देती है, किसी "
            "व्यक्ति का स्वभाव, करियर, संबंध या भविष्य केवल राशि से तय नहीं करती। अलग-अलग "
            "ज्योतिष-ग्रंथों, क्षेत्रों और परिवारों में विवरण के रूप बदल सकते हैं। इसलिए किसी "
            "परंपरा का उल्लेख करते समय उसके संदर्भ को स्पष्ट रखें और इसे सभी लोगों पर लागू "
            "न करें।"
        )
        scenes.append({
            "title": chapter,
            "narration": narration,
            "visual_prompt": (
                f"Original educational illustration for {profile['name_hi']} rashi, "
                f"consistent {profile['series_color']} accent, respectful and without text"
            ),
            "emotion": "happy",
        })

    hook = (
        f"आज के इस विशेष परिचय में हम {profile['name_hi']} राशि को परंपरागत ज्योतिष की "
        "दृष्टि से समझेंगे। राशि-चिह्न और उससे जुड़ी धारणाएँ सांस्कृतिक परंपरा का हिस्सा हैं; "
        "इन्हें वैज्ञानिक रूप से निश्चित व्यक्तित्व-विवरण या भविष्यवाणी नहीं मानना चाहिए। "
        "हम समान अध्यायों में प्रतीक, तत्व, ग्रह, परंपरागत मान्यताएँ और उनके जिम्मेदार अर्थ "
        "देखेंगे।"
    )
    return {
        "research": {
            "headline": f"{profile['name_hi']} राशि का पूरा परिचय",
            "thumbnail_text": f"{profile['name_hi']} राशि",
            "hook": hook,
            "research_summary": DISCLAIMER,
            "key_facts": [],
            "keywords": [profile["name_hi"], profile["name_en"], "राशि परिचय", "traditional astrology"],
            "scenes": scenes,
        },
        "sources": [],
        "research_method": "original_traditional_astrology_guide",
        "fixed_template": True,
        "description_disclaimer": DISCLAIMER,
        "thumbnail_color": profile["series_color"],
        "thumbnail_symbol": profile["thumbnail_symbol"],
    }
