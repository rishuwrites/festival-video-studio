import re

# Noto Sans Devanagari has no Latin glyphs: any Latin letters in captions or thumbnails would show as empty boxes (□□□).
_WORDS = {
    "tv": "टीवी", "ep": "एपिसोड", "episode": "एपिसोड", "full": "पूरा", "serial": "सीरियल",
    " promo": " प्रोमो", "update": "अपडेट", "story": "कहानी", "twist": "ट्विस्ट", "new": "नया",
    "ok": "ओके", "okay": "ओके", "sorry": "सॉरी", "thank": "थैंक", "thanks": "थैंक्स",
    "please": "प्लीज़", "yes": "हाँ", "no": "नहीं", "hello": "हेलो", "hi": "हाय", "bye": "बाय",
    "doctor": "डॉक्टर", "dr": "डॉ.", "police": "पुलिस", "inspector": "इंस्पेक्टर",
    "hospital": "अस्पताल", "icu": "आईसीयू", "dna": "डीएनए", "fir": "एफआईआर", "ips": "आईपीएस",
    "ias": "आईएएस", "vip": "वीआईपी", "ceo": "सीईओ", "bjp": "बीजेपी", "otp": "ओटीपी",
    "cctv": "सीसीटीवी", "sim": "सिम", "id": "आईडी", "proof": "प्रूफ़", "plan": "प्लान",
    "party": "पार्टी", "truth": "सच", "secret": "राज़", "promise": "वादा", "love": "प्यार",
    "marriage": "शादी", "wedding": "शादी", "divorce": "तलाक", "jail": "जेल", "court": "कोर्ट",
    "judge": "जज", "lawyer": "वकील", "case": "केस", "phone": "फ़ोन", "call": "कॉल",
    "video": "वीडियो", "photo": "फ़ोटो", "message": "मैसेज", "msg": "मैसेज", "live": "लाइव",
    "room": "कमरा", "house": "घर", "home": "घर", "office": "ऑफ़िस", "car": "कार",
    "money": "पैसे", "property": "प्रॉपर्टी", "papers": "काग़ज़ात", "sign": "साइन",
    "sir": "सर", "madam": "मैडम", "mam": "मैम", "boss": "बॉस", "hero": "हीरो",
    "villain": "विलेन", "family": "परिवार", "friend": "दोस्त", "baby": "बच्चा",
    "child": "बच्चा", "son": "बेटा", "daughter": "बेटी", "mother": "माँ", "mom": "मम्मी",
    "father": "पिता", "dad": "पापा", "papa": "पापा", "brother": "भाई", "sister": "बहन",
    "wife": "पत्नी", "husband": "पति", "bhabhi": "भाभी", "didi": "दीदी", "bhaiya": "भैया",
    "ji": "जी", "shock": "झटका", "drama": "ड्रामा", "scene": "दृश्य", "part": "भाग",
    " vs ": " बनाम ", "and": "और", "or": "या", "in": "में", "on": "पर", "to": "को",
    "of": "का", "for": "के लिए", "with": "के साथ", "from": "से", "by": "द्वारा",
    "the": "", "a": "एक", "is": "है", "are": "हैं", "was": "था", "were": "थे",
}

_LETTERS = dict(zip(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    ["ए", "बी", "सी", "डी", "ई", "एफ", "जी", "एच", "आई", "जे", "के", "एल", "एम",
     "एन", "ओ", "पी", "क्यू", "आर", "एस", "टी", "यू", "वी", "डब्ल्यू", "एक्स", "वाई", "ज़ेड"]
))

# Phonetic fallback for any remaining lowercase Latin words so no Latin characters ever survive
_PHONETIC = [
    ("sh", "श"), ("ch", "च"), ("th", "थ"), ("dh", "ध"), ("ph", "फ़"), ("bh", "भ"),
    ("kh", "ख"), ("gh", "घ"), ("jh", "झ"), ("aa", "आ"), ("ee", "ई"), ("oo", "ऊ"),
    ("ai", "ऐ"), ("au", "औ"), ("a", "अ"), ("b", "ब"), ("c", "क"), ("d", "द"),
    ("e", "ए"), ("f", "फ़"), ("g", "ग"), ("h", "ह"), ("i", "इ"), ("j", "ज"),
    ("k", "क"), ("l", "ल"), ("m", "म"), ("n", "न"), ("o", "ओ"), ("p", "प"),
    ("q", "क"), ("r", "र"), ("s", "स"), ("t", "ट"), ("u", "उ"), ("v", "व"),
    ("w", "व"), ("x", "क्स"), ("y", "य"), ("z", "ज़"),
]

def _translit_word(w):
    low = w.lower()
    if low in _WORDS:
        return _WORDS[low]
    # All-caps acronym (e.g. BJP, DNA, TV) -> letter-by-letter Devanagari
    if w.isupper() and len(w) <= 7:
        return "".join(_LETTERS.get(c, "") for c in w)
    # Mixed or lowercase unknown word -> phonetic approximation
    res, i = [], 0
    while i < len(low):
        matched = False
        for pat, rep in _PHONETIC:
            if low.startswith(pat, i):
                res.append(rep)
                i += len(pat)
                matched = True
                break
        if not matched:
            c = low[i].upper()
            res.append(_LETTERS.get(c, ""))
            i += 1
    return "".join(res)

def deva(text):
    """Convert any Latin acronyms or English words into Devanagari so captions/thumbnails never render empty boxes."""
    if not text:
        return ""
    out = re.sub(r"[A-Za-z]+", lambda m: _translit_word(m.group(0)), str(text))
    return re.sub(r"\s+", " ", out).strip()
