"""Create owner-editable source-data templates and an original topic pool."""

import csv
import json
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START = date(2026, 11, 18)
END = date(2026, 12, 31)
SOURCE_URL = "https://www.drikpanchang.com/"
RASHIS = [
    ("मेष", "Mesh", "Aries", "मेष", "अग्नि", "मंगल", "मंगलवार", "मूंगा", "हनुमान परंपरा", "साहस और पहल"),
    ("वृषभ", "Vrishabh", "Taurus", "वृषभ", "पृथ्वी", "शुक्र", "शुक्रवार", "हीरा", "लक्ष्मी परंपरा", "स्थिरता और धैर्य"),
    ("मिथुन", "Mithun", "Gemini", "मिथुन", "वायु", "बुध", "बुधवार", "पन्ना", "विष्णु परंपरा", "जिज्ञासा और संवाद"),
    ("कर्क", "Kark", "Cancer", "कर्क", "जल", "चंद्र", "सोमवार", "मोती", "शिव परंपरा", "संवेदनशीलता और देखभाल"),
    ("सिंह", "Singh", "Leo", "सिंह", "अग्नि", "सूर्य", "रविवार", "माणिक्य", "सूर्य परंपरा", "आत्मविश्वास और अभिव्यक्ति"),
    ("कन्या", "Kanya", "Virgo", "कन्या", "पृथ्वी", "बुध", "बुधवार", "पन्ना", "विष्णु परंपरा", "विवेक और बारीकी"),
    ("तुला", "Tula", "Libra", "तुला", "वायु", "शुक्र", "शुक्रवार", "हीरा", "लक्ष्मी परंपरा", "संतुलन और सहयोग"),
    ("वृश्चिक", "Vrishchik", "Scorpio", "वृश्चिक", "जल", "मंगल", "मंगलवार", "मूंगा", "शिव परंपरा", "दृढ़ता और आत्ममंथन"),
    ("धनु", "Dhanu", "Sagittarius", "धनु", "अग्नि", "बृहस्पति", "गुरुवार", "पुखराज", "गुरु परंपरा", "सीखना और विस्तार"),
    ("मकर", "Makar", "Capricorn", "मकर", "पृथ्वी", "शनि", "शनिवार", "नीलम", "शनि परंपरा", "अनुशासन और निरंतरता"),
    ("कुंभ", "Kumbh", "Aquarius", "कुंभ", "वायु", "शनि", "शनिवार", "नीलम", "शनि परंपरा", "नवाचार और समुदाय"),
    ("मीन", "Meen", "Pisces", "मीन", "जल", "बृहस्पति", "गुरुवार", "पुखराज", "गुरु परंपरा", "कल्पनाशीलता और करुणा"),
]

FESTIVALS = [
    {
        "name_hi": "तुलसी विवाह",
        "name_en": "Tulsi Vivah",
        "date": "",
        "tithi_note": "Conflicting candidate dates: 2026-11-17 or 2026-11-21; verify on Drik Panchang.",
        "verified": False,
        "source_url": SOURCE_URL,
    },
    {
        "name_hi": "कार्तिक पूर्णिमा / देव दीपावली",
        "name_en": "Kartik Purnima / Dev Diwali",
        "date": "2026-11-24",
        "tithi_note": "Approximate candidate date only; verify tithi and regional observance before use.",
        "verified": False,
        "source_url": SOURCE_URL,
    },
    {
        "name_hi": "कालभैरव जयंती",
        "name_en": "Kalbhairav Jayanti",
        "date": "2026-12-01",
        "tithi_note": "Approximate candidate date only; verify before scheduling.",
        "verified": False,
        "source_url": SOURCE_URL,
    },
    {
        "name_hi": "मार्गशीर्ष अमावस्या",
        "name_en": "Margashirsha Amavasya",
        "date": "",
        "tithi_note": "Check the date; sources conflict.",
        "verified": False,
        "source_url": SOURCE_URL,
    },
    {
        "name_hi": "विवाह पंचमी",
        "name_en": "Vivah Panchami",
        "date": "2026-12-14",
        "tithi_note": "Approximate candidate date only; verify tithi and observance.",
        "verified": False,
        "source_url": SOURCE_URL,
    },
    {
        "name_hi": "धनु संक्रांति",
        "name_en": "Dhanu Sankranti",
        "date": "",
        "tithi_note": "Mid-December candidate; owner must confirm the date and source.",
        "verified": False,
        "source_url": SOURCE_URL,
    },
    {
        "name_hi": "गीता जयंती / मोक्षदा एकादशी",
        "name_en": "Gita Jayanti / Mokshada Ekadashi",
        "date": "",
        "tithi_note": "Conflicting candidate dates: 2026-12-19 or 2026-12-20; verify.",
        "verified": False,
        "source_url": SOURCE_URL,
    },
    {
        "name_hi": "दत्तात्रेय जयंती",
        "name_en": "Dattatreya Jayanti",
        "date": "2026-12-23",
        "tithi_note": "Approximate candidate date only; verify before scheduling.",
        "verified": False,
        "source_url": SOURCE_URL,
    },
]
for name_hi, name_en, occurrences in (
    ("एकादशी", "Ekadashi", 5),
    ("प्रदोष व्रत", "Pradosh", 6),
    ("संकष्टी चतुर्थी", "Sankashti Chaturthi", 2),
    ("पूर्णिमा", "Purnima", 2),
    ("अमावस्या", "Amavasya", 2),
):
    for occurrence in range(1, occurrences + 1):
        FESTIVALS.append({
            "name_hi": name_hi,
            "name_en": name_en,
            "date": "",
            "tithi_note": (
                f"Occurrence {occurrence}: owner must add the date from a trusted panchang."
            ),
            "verified": False,
            "source_url": SOURCE_URL,
        })

STORY_TOPICS = [
    ("दीपदान की परंपरा", "The tradition of offering lamps"),
    ("कलश का सांस्कृतिक अर्थ", "The cultural meaning of the kalash"),
    ("कमल का प्रतीकात्मक स्थान", "The symbolic place of the lotus"),
    ("घंटी और आरती की ध्वनि", "Temple bells and the sound of aarti"),
    ("रंगोली की क्षेत्रीय शैलियाँ", "Regional styles of rangoli"),
    ("प्रसाद बाँटने की परंपरा", "The tradition of sharing prasad"),
    ("पवित्र नदियों के लोकवृत्त", "Folklore around sacred rivers"),
    ("तीर्थयात्रा की लोककथाएँ", "Folk stories of pilgrimage"),
    ("मौखिक परंपरा में पर्व कथाएँ", "Festival stories in oral tradition"),
    ("मंदिर के मेले और स्थानीय समाज", "Temple fairs and local communities"),
    ("घर के आँगन में पूजा की जगह", "The place of worship in the home courtyard"),
    ("दीपक बनाने वाले कारीगर", "Craft traditions of diya makers"),
    ("मौसमी फूल और पूजा सजावट", "Seasonal flowers and devotional decoration"),
    ("भजन की सामुदायिक परंपरा", "Community traditions of devotional song"),
    ("दान और सेवा की सांस्कृतिक भावना", "The cultural idea of giving and service"),
    ("पर्वों में परिवार का मिलन", "Family gatherings during festivals"),
    ("लोकनाट्य और धार्मिक कथाएँ", "Folk theatre and sacred stories"),
    ("पंचांग पढ़ने की परंपरा", "The tradition of reading a panchang"),
    ("चंद्र मास की लोकसमझ", "Popular understanding of lunar months"),
    ("तिथि और पक्ष का सरल परिचय", "A simple guide to tithi and paksha"),
    ("मंदिर स्थापत्य में दीपों का स्थान", "Lamps in temple architecture"),
    ("पूजा थाली की वस्तुओं का अर्थ", "The meaning of items in a puja thali"),
    ("व्रत कथा सुनने की परंपरा", "The tradition of listening to vrat stories"),
    ("घर में सामूहिक पाठ", "Shared scripture reading at home"),
    ("लोकगीतों में ऋतु और पर्व", "Seasons and festivals in folk songs"),
    ("देवालयों के वार्षिक उत्सव", "Annual celebrations at temples"),
    ("कथा वाचन की बदलती शैली", "Changing styles of storytelling"),
    ("भक्ति साहित्य में प्रकृति", "Nature in devotional literature"),
    ("पर्वों में जल का सांस्कृतिक अर्थ", "The cultural meaning of water in festivals"),
    ("परिवारों में पीढ़ियों से चली पूजा", "Worship traditions passed between generations"),
    ("ग्रामीण मेलों की साझा स्मृतियाँ", "Shared memories of village fairs"),
    ("लोककला में शुभ चिह्न", "Auspicious motifs in folk art"),
    ("मंदिर यात्रा की तैयारी", "Preparing for a temple visit"),
    ("आरती के बाद प्रसाद बाँटना", "Sharing prasad after aarti"),
    ("समुदाय की रसोई और सेवा", "Community kitchens and service"),
    ("पर्व कैलेंडर कैसे पढ़ें", "How to read a festival calendar"),
    ("सूर्योदय पूजा का सांस्कृतिक पक्ष", "The cultural side of sunrise worship"),
    ("कथा और इतिहास में अंतर", "The difference between legend and history"),
    ("भक्ति परंपराओं में अतिथि सत्कार", "Hospitality in devotional traditions"),
    ("घर की सजावट में पारंपरिक रंग", "Traditional colors in home decoration"),
    ("शिल्पकारों का पर्व अर्थतंत्र", "Artisans and the festival economy"),
    ("मौसमी अन्न और सामुदायिक भोज", "Seasonal grains and community meals"),
    ("लोकविश्वासों का सम्मानजनक अध्ययन", "Studying folk beliefs respectfully"),
    ("पुरानी पांडुलिपियों की देखभाल", "Caring for historic manuscripts"),
    ("परंपरा को अगली पीढ़ी तक पहुँचाना", "Passing traditions to the next generation"),
]
STORY_ANGLES = [
    ("कथा और लोकस्मृति", "Story and community memory"),
    ("इतिहास की झलक", "A glimpse into history"),
    ("आज के जीवन में अर्थ", "Meaning in contemporary life"),
]
REGIONAL_TOPICS = [
    ("अवध में दीप सजाने की लोकरीति", "Folk lamp decoration in Awadh"),
    ("भोजपुरी अंचल के पर्व गीत", "Festival songs of the Bhojpuri region"),
    ("मिथिला की अरिपन कला", "Aripan art in Mithila"),
    ("पूर्वांचल के मंदिर मेले", "Temple fairs in Purvanchal"),
    ("बिहार के सामुदायिक प्रसाद", "Community prasad traditions in Bihar"),
    ("उत्तर प्रदेश की पूजा थाली सजावट", "Puja-thali decoration in Uttar Pradesh"),
    ("गंगा तट की स्थानीय आरती परंपराएँ", "Local aarti traditions along the Ganga"),
    ("बुंदेलखंड की मौसमी लोककथाएँ", "Seasonal folk stories of Bundelkhand"),
    ("ब्रज क्षेत्र के भक्ति गीत", "Devotional songs of Braj"),
    ("मगध की मंदिर यात्राएँ", "Temple journeys in Magadh"),
    ("छोटे नगरों के वार्षिक धार्मिक मेले", "Annual religious fairs in small towns"),
    ("पूर्वी भारत की अल्पना परंपरा", "Alpana traditions of eastern India"),
    ("राजस्थान की दीप सजावट", "Lamp decoration traditions of Rajasthan"),
    ("दक्षिण भारत के मंदिर उत्सव", "Temple festivals of southern India"),
    ("पश्चिम भारत की सामूहिक आरती", "Community aarti in western India"),
    ("पर्व भोज में क्षेत्रीय अनाज", "Regional grains in festival meals"),
    ("घर-घर की पूजा विधि में विविधता", "Variation in household worship practices"),
    ("बोली और भजन की स्थानीय पहचान", "Local identity in dialect and devotional song"),
    ("क्षेत्रीय मंदिरों के सेवा समूह", "Service groups at regional temples"),
    ("स्थानीय पंचांग से पर्व तिथि देखना", "Checking dates in a local panchang"),
    ("लोक शिल्प में नदी और सूर्य", "Rivers and the sun in folk crafts"),
    ("गाँव के मेले में कारीगरों की भूमिका", "Artisans at village fairs"),
    ("परिवारों में व्रत की अलग-अलग रीति", "Different family customs around fasting"),
    ("क्षेत्रीय परंपराओं को सही नाम देना", "Naming regional traditions accurately"),
    ("शहर और गाँव के पर्व अनुभव", "Festival experiences in towns and villages"),
    ("स्थानीय मंदिरों में भजन संध्या", "Devotional evenings at local temples"),
    ("उत्तर भारतीय घरों की मौसमी सजावट", "Seasonal decoration in North Indian homes"),
    ("भक्ति यात्राओं में स्थानीय भोजन", "Local foods on devotional journeys"),
    ("क्षेत्रीय रीति और सार्वदेशिक तथ्य", "Regional custom versus nationwide fact"),
    ("अलग-अलग समुदायों में प्रसाद की विविधता", "Prasad traditions across communities"),
    ("पर्व आयोजन में महिलाओं की भूमिका", "Women's roles in festival organizing"),
    ("स्थानीय मेलों में लोकनृत्य", "Folk dance at local fairs"),
    ("नदी किनारे होने वाली सामुदायिक सेवा", "Community service beside rivers"),
    ("हस्तशिल्प और धार्मिक अवसर", "Handicrafts and devotional occasions"),
    ("परिवार की मौखिक परंपरा का दस्तावेज़", "Documenting family oral traditions"),
    ("स्थानीय पर्व भोजन में साझा व्यंजन", "Shared dishes in local festival meals"),
    ("क्षेत्रीय देवालयों की वार्षिक यात्रा", "Annual visits to regional temples"),
    ("मंदिर मेले में लोकशिल्प का बाज़ार", "Folk crafts at a temple fair"),
    ("लोककथा और समुदाय की स्मृति", "Folklore and community memory"),
    ("पर्व के समय स्थानीय सेवा परंपरा", "Local service traditions during festivals"),
    ("क्षेत्रीय पूजा सामग्री का परिचय", "An introduction to regional worship items"),
    ("गाँव और शहर के व्रत अनुभव", "Fasting customs in villages and cities"),
    ("स्थानीय भाषा में पर्व कथा", "Festival stories in local languages"),
    ("कला और संगीत से क्षेत्रीय पहचान", "Regional identity through art and music"),
    ("धार्मिक परंपराओं के स्रोत का सम्मान", "Respecting sources for religious customs"),
]
VRAT_TOPICS = [
    ("व्रत से पहले संकल्प कैसे लें", "How to make a vrat intention"),
    ("व्रत में जल और विश्राम की योजना", "Planning hydration and rest during a fast"),
    ("व्रत की तिथि स्थानीय पंचांग से देखना", "Checking vrat dates in a local panchang"),
    ("पारण का समय कैसे सत्यापित करें", "How to verify a parana time"),
    ("परिवार की परंपरा और व्रत नियम", "Family tradition and vrat rules"),
    ("फलाहार की परंपरागत तैयारी", "Traditional preparation of phalahar"),
    ("व्रत कथा सुनने का क्रम", "The sequence for listening to a vrat story"),
    ("पूजा सामग्री की पहले से सूची", "Preparing a puja-supplies checklist"),
    ("एकादशी व्रत के नियम स्रोत से जाँचें", "Verifying Ekadashi rules from a source"),
    ("प्रदोष व्रत की पूजा तैयारी", "Preparing for Pradosh worship"),
    ("संकष्टी चतुर्थी की कथा और परंपरा", "Sankashti Chaturthi story and tradition"),
    ("व्रत में क्षेत्रीय नियमों का अंतर", "Regional differences in fasting customs"),
    ("पारण और स्थानीय सूर्योदय का संबंध", "Parana and local sunrise"),
    ("व्रत के दिन पूजा स्थान तैयार करना", "Preparing a worship space for a fast"),
    ("व्रत नियमों में परिवार से पूछना", "Asking family elders about vrat customs"),
    ("व्रत कथा और स्रोत की पहचान", "Identifying a vrat story and its source"),
    ("निराहार और फलाहार परंपराओं का अंतर", "Nirahar and phalahar traditions"),
    ("व्रत में अहिंसा और सेवा का भाव", "Non-harm and service in fasting traditions"),
    ("व्रत की शुरुआत और समापन विधि", "Beginning and ending a vrat"),
    ("उपवास की परंपरा में संयम का अर्थ", "The meaning of restraint in fasting"),
    ("व्रत तिथि में स्थानानुसार बदलाव", "Location-based variation in vrat dates"),
    ("पर्व के बाद पारण की तैयारी", "Preparing for parana after a festival"),
    ("व्रत के नियमों को सरल भाषा में समझें", "Explaining vrat rules in simple language"),
    ("पूजा में उपयोग होने वाली पारंपरिक वस्तुएँ", "Traditional objects used in worship"),
    ("व्रत और सामुदायिक भोजन की परंपरा", "Fasting and community-meal traditions"),
    ("परिवार में बच्चों को व्रत कथा सुनाना", "Sharing vrat stories with children"),
    ("स्थानीय रीति से पूजा सामग्री चुनना", "Choosing puja items by local custom"),
    ("व्रत के दिन समय-सारणी बनाना", "Making a vrat-day schedule"),
    ("व्रत में परंपरा और व्यक्तिगत सुविधा", "Tradition and personal comfort while fasting"),
    ("व्रत कथा में प्रतीक समझना", "Understanding symbols in vrat stories"),
    ("तिथि बदलने पर व्रत निर्णय कैसे लें", "Making vrat plans when tithis vary"),
    ("पारण के लिए शहर-विशेष पंचांग देखना", "Using a city-specific panchang for parana"),
    ("व्रत परंपराओं का सम्मानजनक परिचय", "A respectful introduction to fasting traditions"),
    ("व्रत और दान की लोकपरंपरा", "Folk traditions of fasting and giving"),
    ("उपवास के दिन शांत दिनचर्या", "A calm routine on a fasting day"),
    ("व्रत के नियम और परंपरा में क्षेत्रीय भेद", "Regional differences in vrat rules"),
    ("व्रत में संकल्प का सरल अर्थ", "The simple meaning of a vrat intention"),
    ("पारण से पहले स्थानीय पंचांग देखना", "Checking the local panchang before parana"),
    ("उपवास में स्वास्थ्य-सुविधा को प्राथमिकता", "Prioritizing personal comfort during a fast"),
    ("व्रत कथा के पात्रों का संदर्भ", "Context for characters in a vrat story"),
    ("परिवार की व्रत परंपरा लिखकर रखना", "Documenting a family's vrat tradition"),
    ("व्रत सामग्री में स्थानीय विकल्प", "Local alternatives for vrat supplies"),
    ("व्रत और विश्राम का संतुलन", "Balancing rest and fasting"),
    ("एकादशी नियमों में स्रोत की तारीख देखना", "Checking the date of an Ekadashi source"),
    ("व्रत के दिन भोजन परंपरा पूछना", "Asking about customary vrat foods"),
]
EVENING_TOPICS = [
    ("आरती के अर्थ को सरल भाषा में समझें", "Aarti meanings in simple language"),
    ("मंत्र जप की परंपरा और उच्चारण", "Mantra recitation traditions and pronunciation"),
    ("पूजा में मौन का सांस्कृतिक अर्थ", "The cultural meaning of silence in worship"),
    ("भक्ति प्रश्नोत्तर: दीप क्यों जलाते हैं", "Devotional Q&A: why light a lamp"),
    ("भक्ति प्रश्नोत्तर: प्रसाद क्या दर्शाता है", "Devotional Q&A: what prasad represents"),
    ("शाम की आरती में परिवार की भागीदारी", "Family participation in evening aarti"),
    ("भजन सुनने और गाने की परंपरा", "Traditions of listening to and singing bhajans"),
    ("मंत्र के अर्थ को समझकर जप", "Reciting a mantra with understanding"),
    ("घर की पूजा में दीप की देखभाल", "Caring for a lamp in household worship"),
    ("पूजा के बाद कृतज्ञता की परंपरा", "Gratitude after worship"),
    ("भक्ति संगीत में ताल और समुदाय", "Rhythm and community in devotional music"),
    ("प्रार्थना और ध्यान की सांस्कृतिक जगह", "Prayer and meditation in cultural life"),
    ("शाम के समय मंदिर की दिनचर्या", "An evening routine at a temple"),
    ("आरती की थाली में वस्तुओं का परिचय", "Objects used in an aarti plate"),
    ("भजन की पंक्ति का भावार्थ कैसे समझें", "How to understand a bhajan's meaning"),
    ("मंत्रों के स्रोत और परंपरा पूछना", "Asking about mantra sources and traditions"),
    ("सांस्कृतिक Q&A: पूजा में घंटी", "Cultural Q&A: bells in worship"),
    ("सांस्कृतिक Q&A: तुलसी की घरेलू परंपरा", "Cultural Q&A: household Tulsi traditions"),
    ("संध्या समय की पारिवारिक प्रार्थना", "Family prayer in the evening"),
    ("लोकभक्ति और शास्त्रीय भक्ति का परिचय", "Folk and classical devotional traditions"),
    ("आरती और सामूहिक गायन", "Aarti and group singing"),
    ("पूजा के समय स्वच्छता की परंपरा", "Cleanliness customs during worship"),
    ("मंदिर में दर्शन की शिष्टाचार परंपरा", "Etiquette traditions during temple visits"),
    ("कथा सुनने के बाद चर्चा", "Discussing a story after listening"),
    ("मंत्र की ध्वनि और ध्यान", "Mantra sound and attention"),
    ("सांस्कृतिक Q&A: तिथि और मुहूर्त", "Cultural Q&A: tithi and muhurta"),
    ("संध्या दीप और घर की सजावट", "Evening lamps and household decoration"),
    ("भक्ति में सेवा का भाव", "The place of service in devotion"),
    ("आरती के बाद प्रसाद बाँटने का भाव", "The meaning of sharing prasad after aarti"),
    ("पारंपरिक प्रार्थना और आधुनिक दिनचर्या", "Traditional prayer and modern routines"),
    ("भक्ति कथाओं को बच्चों तक पहुँचाना", "Sharing devotional stories with children"),
    ("पूजा सामग्री का पर्यावरण-सम्मत उपयोग", "Mindful use of worship materials"),
    ("भजन संध्या की सामुदायिक तैयारी", "Preparing a community bhajan evening"),
    ("प्रार्थना में भाषा और स्थानीय बोली", "Language and dialect in prayer"),
    ("पूजा परंपरा में प्रश्न पूछने की जगह", "Making space for questions about worship"),
    ("स्थानीय आरती की धुनों का परिचय", "An introduction to local aarti melodies"),
    ("भक्ति परंपराओं में मौसमी फूल", "Seasonal flowers in devotional traditions"),
    ("मंदिर के आसपास की स्थानीय कला", "Local art around a temple"),
    ("पूजा के बाद सामुदायिक स्वच्छता", "Community clean-up after worship"),
    ("पर्व की तैयारी में पड़ोस का सहयोग", "Neighbourly help in festival preparations"),
    ("संध्या पूजा में क्षेत्रीय भिन्नताएँ", "Regional variations in evening worship"),
    ("स्थानीय कारीगरों से पारंपरिक सजावट", "Traditional decoration from local artisans"),
    ("व्रत भोजन की पारिवारिक विविधता", "Family variation in vrat foods"),
    ("तीर्थ की लोककथा और स्थानीय संदर्भ", "Pilgrimage folklore and local context"),
    ("क्षेत्रीय परंपरा पर स्रोत कैसे खोजें", "Finding sources for a regional custom"),
]


def _topic(kind, hi, en, evergreen=True, **extra):
    return {
        "type": kind,
        "topic_hi": hi,
        "topic_en": en,
        "evergreen": evergreen,
        "earliest_date": START.isoformat(),
        "latest_date": END.isoformat(),
        **extra,
    }


def build_topics():
    topics = []
    for hi, en in STORY_TOPICS:
        for angle_hi, angle_en in STORY_ANGLES:
            topics.append(_topic(
                "story_history", f"{angle_hi}: {hi}", f"{angle_en}: {en}",
            ))
    for hi, en in REGIONAL_TOPICS:
        topics.append(_topic("regional_customs", hi, en))
        topics.append(_topic(
            "regional_customs",
            f"क्षेत्रीय विविधता: {hi}",
            f"Regional perspective: {en}",
        ))
    for hi, en in VRAT_TOPICS:
        topics.append(_topic("vrat_rules", hi, en))
        topics.append(_topic(
            "vrat_rules",
            f"व्रत परंपरा में क्षेत्रीय दृष्टि: {hi}",
            f"Regional perspective on vrat customs: {en}",
        ))
    for hi, en in EVENING_TOPICS:
        topics.append(_topic("evergreen_culture", hi, en))

    rashi_full_topics = [
        ("पूर्ण परिचय", "Full encyclopedia"),
        ("प्रतीक, तत्व और स्वभाव", "Symbol, element, and nature"),
        ("स्वामी ग्रह और पारंपरिक रत्न", "Ruling planet and traditional gemstone"),
    ]
    rashi_series_topics = [
        ("करियर और कार्यशैली", "Career and working style", "career"),
        ("संबंध और पारंपरिक अनुकूलता", "Relationships and traditional compatibility", "relationships"),
        ("मंत्र, देव परंपरा और उपाय", "Mantra, deity traditions, and remedies", "remedies"),
        ("लोकधारणाएँ और पारंपरिक दावे", "Popular beliefs and traditional claims", "beliefs"),
    ]
    for index, (_, _, name_en, name_hi, *_rest) in enumerate(RASHIS):
        for angle_hi, angle_en in rashi_full_topics:
            topics.append(_topic(
                "rashi_encyclopedia",
                f"{name_hi} राशि: {angle_hi}",
                f"{name_en}: {angle_en}",
                evergreen=False,
                rashi_index=index,
                episode="full" if angle_hi == "पूर्ण परिचय" else "full_extra",
            ))
        for angle_hi, angle_en, episode in rashi_series_topics:
            topics.append(_topic(
                "rashi_encyclopedia",
                f"{name_hi} राशि: {angle_hi}",
                f"{name_en}: {angle_en}",
                evergreen=False,
                rashi_index=index,
                episode=episode,
            ))

    for event in FESTIVALS[:8]:
        name_hi, name_en = event["name_hi"], event["name_en"]
        for variant in range(1, 3):
            for kind, suffix_hi, suffix_en in (
                ("festival_explainer", "तिथि, कथा और परंपराएँ", "date, story, and traditions"),
                ("upcoming_festival", "से पहले जानें: रीति और तैयारी", "customs and preparation to know beforehand"),
                ("story_history", "क्षेत्रीय परंपराएँ और अर्थ", "regional traditions and meaning"),
            ):
                topics.append(_topic(
                    kind,
                    f"{name_hi}: {suffix_hi} भाग {variant}",
                    f"{name_en}: {suffix_en}, part {variant}",
                    evergreen=False,
                    festival_key=name_en,
                ))
    for event in FESTIVALS[8:]:
        name_hi, name_en = event["name_hi"], event["name_en"]
        for index in range(1, 16):
            topics.append(_topic(
                "festival_explainer",
                f"{name_hi}: स्रोत-आधारित परिचय भाग {index:02}",
                f"{name_en}: source-led guide part {index:02}",
                evergreen=False,
                festival_key=name_en,
            ))
            topics.append(_topic(
                "upcoming_festival",
                f"{name_hi}: तैयारी और परंपरा भाग {index:02}",
                f"{name_en}: preparation and traditions part {index:02}",
                evergreen=False,
                festival_key=name_en,
            ))

    seen = set()
    unique = []
    for item in topics:
        key = (item["topic_hi"].casefold(), item["topic_en"].casefold())
        if key not in seen:
            unique.append(item)
            seen.add(key)
    if len(unique) < 300:
        raise RuntimeError(f"Topic seed produced only {len(unique)} unique topics")
    return unique


def build_rashifal_rules():
    moon_focuses = [
        "स्पष्ट संवाद", "धैर्यपूर्वक सुनना", "घर और दिनचर्या", "रचनात्मक अभिव्यक्ति",
        "जिम्मेदारी बाँटना", "सीखने की जिज्ञासा", "सहयोग और संतुलन", "एकाग्रता",
        "लक्ष्य पर विचार", "विश्राम और आत्ममंथन", "समूह में सहभागिता", "भावों को शब्द देना",
    ]
    tips = [
        "एक काम चुनें और उसे छोटे चरणों में पूरा करें",
        "उत्तर देने से पहले पूरी बात सुनें",
        "अपनी दिनचर्या में थोड़ा विराम रखें",
        "किसी विचार को लिखकर फिर उस पर लौटें",
        "ज़रूरत पड़ने पर मदद माँगना भी सहयोग है",
        "समय तय करके पढ़ने या सीखने का अभ्यास करें",
        "मतभेद में भी सम्मानजनक भाषा रखें",
        "किसी निर्णय से पहले उपलब्ध जानकारी जाँचें",
        "लंबी सूची को प्राथमिकता के अनुसार बाँटें",
        "काम और आराम के बीच संतुलन रखें",
        "अपनी बात स्पष्ट और शांत ढंग से रखें",
        "आज की योजना को अपनी वास्तविक सुविधा के अनुसार बदलें",
    ]
    entries = []
    for sign_index, (hi, _, en, name_hi, element, _, _, _, _, traits) in enumerate(RASHIS):
        interpretations = []
        for moon_index, moon_data in enumerate(RASHIS):
            moon_hi = moon_data[3]
            focus = moon_focuses[(moon_index + sign_index) % len(moon_focuses)]
            tip = tips[(sign_index * 5 + moon_index) % len(tips)]
            interpretation = (
                f"परंपरागत ज्योतिष में {name_hi} राशि के लिए {moon_hi} चंद्र स्थिति को "
                f"{focus} पर मनन करने का संकेत माना जाता है; इसे निश्चित घटना की भविष्यवाणी न समझें। "
                f"{name_hi} से जोड़े जाने वाले {traits} गुणों को आज शांत और व्यावहारिक ढंग से अपनाएँ। "
                f"{tip}; किसी परिणाम को पहले से तय मानने के बजाय परिस्थिति और अपनी सुविधा देखकर कदम लें।"
            )
            interpretations.append({
                "moon_rashi": moon_hi,
                "interpretation": interpretation,
                "tip": tip,
            })
        entries.append({
            "rashi": name_hi,
            "rashi_en": en,
            "traditional_traits": traits,
            "tip": tips[sign_index],
            "color": ["लाल", "हरा", "हल्का पीला", "सफेद", "सुनहरा", "हल्का हरा",
                      "गुलाबी", "गहरा लाल", "पीला", "नीला", "आसमानी", "समुद्री हरा"][sign_index],
            "number": (sign_index % 9) + 1,
            "moon_positions": interpretations,
        })
    return {
        "disclaimer": "परंपरागत ज्योतिष पर आधारित, मनोरंजन और जानकारी के लिए",
        "safety": {
            "banned_topics": [
                "मृत्यु", "गंभीर बीमारी", "सटीक धन लाभ", "परीक्षा परिणाम", "गर्भावस्था",
                "death", "serious illness", "exact financial gain", "exam result", "pregnancy",
            ],
            "rule": "Write reflective, non-certain guidance only. Never add medical, financial, or guaranteed predictions.",
        },
        "rashis": entries,
    }


def build_rashi_profiles():
    profiles = []
    symbols = (
        "मेष/मेढ़ा", "वृषभ/बैल", "मिथुन/जुड़वाँ", "कर्क/केकड़ा",
        "सिंह/सिंह", "कन्या/कन्या-रूप", "तुला/तराजू", "वृश्चिक/बिच्छू",
        "धनु/धनुर्धर", "मकर/मकर", "कुंभ/जल-कलश", "मीन/मछलियाँ",
    )
    thumbnail_symbols = ("♈", "♉", "♊", "♋", "♌", "♍", "♎", "♏", "♐", "♑", "♒", "♓")
    for index, (hi, short_en, en, name_hi, element, planet, day, gem, deity, traits) in enumerate(RASHIS):
        profiles.append({
            "name_hi": name_hi,
            "name_en": en,
            "symbol": symbols[index],
            "thumbnail_symbol": thumbnail_symbols[index],
            "element": element,
            "ruling_planet": planet,
            "lucky_day": day,
            "traditional_gemstone": gem,
            "mantra_and_deity": (
                f"{deity}; परंपरागत ग्रह-मंत्र के पाठ और उच्चारण को विश्वसनीय स्रोत से जाँचें"
            ),
            "nature_and_traits": traits,
            "career": "परंपरागत ज्योतिष में बताई गई रुचियों को आत्मचिंतन का संकेत मानें, पेशे का निश्चित निर्णय नहीं।",
            "relationships": "सुनना, संवाद और परस्पर सम्मान किसी भी संबंध में उपयोगी आधार हैं; राशि से अनुकूलता निश्चित नहीं होती।",
            "temples_vrats_festivals": "स्थानीय परंपरा और परिवार की रीति के अनुसार जानकारी लें; सभी समुदायों की पूजा-विधि एक जैसी नहीं होती।",
            "myths_vs_tradition": "ज्योतिषीय विवरण परंपरागत विश्वास हैं, वैज्ञानिक रूप से निश्चित व्यक्तित्व या भविष्यवाणी नहीं।",
            "series_color": ["#D94B45", "#467A54", "#4F7DB8", "#587AA3", "#D18A2B", "#658A5B",
                             "#A45B9A", "#8A3C47", "#8067AE", "#526875", "#3B8A96", "#4F71A7"][len(profiles)],
        })
    return {"disclaimer": "सभी राशि-संबंधी विवरण परंपरागत ज्योतिष के रूप में प्रस्तुत हैं।", "rashis": profiles}


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    write_json(ROOT / "calendar" / "topic_pool.json", {"topics": build_topics()})
    write_json(ROOT / "data" / "festival_dates_2026.json", {"entries": FESTIVALS})
    write_json(ROOT / "data" / "rashifal_rules.json", build_rashifal_rules())
    write_json(ROOT / "data" / "rashi_profiles.json", build_rashi_profiles())

    panchang_path = ROOT / "data" / "panchang_2026_11_18_to_12_31.csv"
    panchang_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "date", "tithi", "paksha", "nakshatra", "moon_rashi",
        "rahu_kaal_start", "rahu_kaal_end", "sunrise", "source_location", "source_url",
    ]
    with panchang_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        current = START
        while current <= END:
            writer.writerow({"date": current.isoformat()})
            current += timedelta(days=1)
    print(
        "Created templates with "
        f"{len(build_topics())} unique topics and "
        f"{sum(len(item['moon_positions']) for item in build_rashifal_rules()['rashis'])} rashifal combinations."
    )


if __name__ == "__main__":
    main()
