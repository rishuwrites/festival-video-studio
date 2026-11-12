import os
import re

import requests

from festival_sources import oauth_access_token


YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
DEFAULT_DESCRIPTION = (
    "भारत के त्योहारों, व्रतों और सांस्कृतिक परंपराओं को सरल हिंदी में जानिए। "
    "यहाँ आपको प्रमुख पर्वों की तिथि, इतिहास, महत्व, रीति-रिवाज और भारत के अलग-अलग "
    "क्षेत्रों की परंपराओं पर स्रोत-आधारित वीडियो मिलेंगे। पंचांग की तिथियाँ और "
    "मुहूर्त स्थान के अनुसार बदल सकते हैं; अपने शहर के विश्वसनीय पंचांग से पुष्टि करें।"
)
DEFAULT_KEYWORDS = (
    "भारतीय त्योहार, हिंदी त्योहार, भारत की संस्कृति, हिंदू त्योहार, पूजा परंपरा, "
    "व्रत त्योहार, छठ पूजा, दिवाली, होली, त्योहार की तिथि, festival India, "
    "Indian festivals, Hindu festivals, Hindi festival videos, Indian culture"
)


def _keywords(value):
    phrases = []
    seen = set()
    for phrase in re.split(r"[,\n]", value):
        phrase = " ".join(phrase.split()).strip()
        key = phrase.casefold()
        if phrase and key not in seen:
            phrases.append(phrase)
            seen.add(key)
    keywords = " ".join(phrases)
    if not keywords:
        raise ValueError("At least one channel keyword is required")
    if len(keywords) > 500:
        raise ValueError("YouTube channel keywords must be 500 characters or fewer")
    return keywords


def _check_response(response, operation):
    if response.status_code in (200, 201):
        return
    try:
        error = response.json().get("error", {})
        detail = error.get("message") or error.get("errors", [{}])[0].get("reason", "")
    except (ValueError, AttributeError, IndexError, TypeError):
        detail = ""
    if response.status_code in (401, 403):
        raise RuntimeError(
            f"YouTube channel {operation} failed (HTTP {response.status_code}"
            f"{', ' + detail if detail else ''}). The refresh token must include the "
            "https://www.googleapis.com/auth/youtube.force-ssl scope, and YouTube "
            "Data API v3 must be enabled."
        )
    raise RuntimeError(
        f"YouTube channel {operation} failed (HTTP {response.status_code}"
        f"{', ' + detail if detail else ''})"
    )


def update_channel_branding(description=None, keywords=None, confirm=False):
    if not confirm:
        raise ValueError(
            "Channel branding was not changed. Set CONFIRM_CHANNEL_BRANDING=true to proceed."
        )
    description = (description or DEFAULT_DESCRIPTION).strip()
    if not description:
        raise ValueError("Channel description must not be empty")
    if len(description) > 1000:
        raise ValueError("YouTube channel description must be 1,000 characters or fewer")
    keyword_string = _keywords(keywords or DEFAULT_KEYWORDS)
    access_token = oauth_access_token()
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(
            f"{YOUTUBE_API}/channels",
            headers=headers,
            params={"part": "brandingSettings,snippet", "mine": "true"},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"YouTube channel lookup failed: {type(exc).__name__}") from exc
    _check_response(response, "lookup")
    channels = response.json().get("items", [])
    if not channels or not channels[0].get("id"):
        raise RuntimeError("YouTube OAuth account has no accessible channel")

    channel = channels[0]
    channel_settings = dict((channel.get("brandingSettings") or {}).get("channel") or {})
    channel_settings["description"] = description
    channel_settings["keywords"] = keyword_string
    payload = {"id": channel["id"], "brandingSettings": {"channel": channel_settings}}
    try:
        response = requests.put(
            f"{YOUTUBE_API}/channels",
            headers={**headers, "Content-Type": "application/json"},
            params={"part": "brandingSettings"},
            json=payload,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"YouTube channel update failed: {type(exc).__name__}") from exc
    _check_response(response, "update")
    print("Updated the authenticated YouTube channel description and keywords.")


if __name__ == "__main__":
    update_channel_branding(
        description=os.getenv("CHANNEL_DESCRIPTION"),
        keywords=os.getenv("CHANNEL_KEYWORDS"),
        confirm=os.getenv("CONFIRM_CHANNEL_BRANDING", "").strip().lower() == "true",
    )
