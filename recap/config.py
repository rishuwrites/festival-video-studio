import os


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SCOPE = "India (nationwide, with focus on Uttar Pradesh and Bihar)"
W, H, FPS = 1920, 1080, 24
CUT_SECONDS = 5.0
MUSIC_VOLUME = 0.15
VOICE = os.getenv("FESTIVAL_VOICE") or "hi-IN-SwaraNeural"
EMOTION_COLORS = {
    "tense": (200, 90, 0),
    "sad": (40, 90, 170),
    "happy": (30, 150, 70),
    "angry": (190, 20, 30),
    "romantic": (190, 40, 120),
    "shock": (120, 40, 170),
}
STYLE = (
    "original Indian festival editorial illustration, cinematic lighting, "
    "rich but natural colors, respectful culturally specific details, "
    "family friendly, no text, no letters, no logos, no watermark"
)
