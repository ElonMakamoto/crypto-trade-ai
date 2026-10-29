"""Settings loaded from environment variables (or a local .env file)."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
FONTS_DIR = BASE_DIR / "fonts"
MUSIC_DIR = BASE_DIR / "assets" / "music"
STATE_FILE = BASE_DIR / "state" / "posted.json"


def _env(name, default=""):
    return os.environ.get(name, default).strip()


# Google AI (Gemini) — writes the viral headline, caption and hashtags
GOOGLE_API_KEY = _env("GOOGLE_API_KEY")
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-2.5-flash")

# News source: Google News RSS (no key needed)
NEWS_COUNTRY = _env("NEWS_COUNTRY", "US")
NEWS_LANGUAGE = _env("NEWS_LANGUAGE", "en")
# Language the headline/caption are written in (Pubity style = English)
POST_LANGUAGE = _env("POST_LANGUAGE", "English")

# Branding
BRAND_HANDLE = _env("BRAND_HANDLE", "@yourpage")
ACCENT_COLOR = _env("ACCENT_COLOR", "#FFD400")

# Instagram
# "instagrapi" = username/password (simple, unofficial)
# "graph"      = official Instagram Graph API (Business/Creator account)
IG_BACKEND = _env("IG_BACKEND", "instagrapi")
IG_USERNAME = _env("IG_USERNAME")
IG_PASSWORD = _env("IG_PASSWORD")
IG_SESSION_FILE = BASE_DIR / "state" / "ig_session.json"
IG_ACCESS_TOKEN = _env("IG_ACCESS_TOKEN")
IG_USER_ID = _env("IG_USER_ID")
GRAPH_VERSION = _env("GRAPH_VERSION", "v21.0")
# Graph API needs a public URL for feed images (reels upload directly)
PUBLIC_MEDIA_BASE_URL = _env("PUBLIC_MEDIA_BASE_URL").rstrip("/")
# Shell command run after public/instagram is updated, before uploading (e.g. git push)
SITE_PUBLISH_HOOK = _env("SITE_PUBLISH_HOOK")

# What each run posts: "both" (feed post + reel), "post", or "reel"
POST_MODE = _env("POST_MODE", "both")
INTERVAL_HOURS = float(_env("INTERVAL_HOURS", "5"))
REEL_SECONDS = int(_env("REEL_SECONDS", "8"))
