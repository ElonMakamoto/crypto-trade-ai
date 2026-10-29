"""Settings: environment variables, a local .env, or the desktop app's saved settings."""
import json
import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
# read-only files bundled with the app (fonts, music)
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
# writable files (state, output, settings): %APPDATA%\InstagramAuto for the .exe
if FROZEN:
    DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "InstagramAuto"
else:
    DATA_DIR = Path(__file__).parent

FONTS_DIR = BASE_DIR / "fonts"
OUTPUT_DIR = DATA_DIR / "output"
STATE_FILE = DATA_DIR / "state" / "posted.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
IG_SESSION_FILE = DATA_DIR / "state" / "ig_session.json"

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# Saved by the desktop app; secrets are stored encrypted
SECRET_KEYS = {"GOOGLE_API_KEY", "IG_PASSWORD", "IG_ACCESS_TOKEN"}
DEFAULTS = {
    "GOOGLE_API_KEY": "",
    "GEMINI_MODEL": "gemini-2.5-flash",
    "NEWS_COUNTRY": "US",
    "NEWS_LANGUAGE": "en",
    "POST_LANGUAGE": "English",
    "BRAND_HANDLE": "@yourpage",
    "ACCENT_COLOR": "#FFD400",
    # "instagrapi" = username/password, "graph" = official Graph API (Business/Creator account)
    "IG_BACKEND": "instagrapi",
    "IG_USERNAME": "",
    "IG_PASSWORD": "",
    "IG_ACCESS_TOKEN": "",
    "IG_USER_ID": "",
    "GRAPH_VERSION": "v21.0",
    # Graph API needs a public URL serving output/ images for feed posts (reels upload directly)
    "PUBLIC_MEDIA_BASE_URL": "",
    # "both" (feed post + reel), "post", or "reel"
    "POST_MODE": "both",
    "INTERVAL_HOURS": "5",
    "REEL_SECONDS": "8",
    "MUSIC_DIR": "",
}


def load_settings():
    """Saved app settings (secrets decrypted), or {} if none."""
    if not SETTINGS_FILE.exists():
        return {}
    import secure_store

    data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    for key in SECRET_KEYS & data.keys():
        data[key] = secure_store.decrypt(data[key])
    return data


def save_settings(values):
    import secure_store

    data = {k: str(v).strip() for k, v in values.items()}
    for key in SECRET_KEYS & data.keys():
        data[key] = secure_store.encrypt(data[key])
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    reload()


def current():
    return {k: f"{globals()[k]:g}" if isinstance(globals()[k], float) else str(globals()[k]) for k in DEFAULTS}


def reload():
    """(Re)compute module settings: saved app settings > environment > defaults."""
    saved = load_settings()
    g = globals()
    for key, default in DEFAULTS.items():
        g[key] = (saved.get(key) or os.environ.get(key) or default).strip()
    g["PUBLIC_MEDIA_BASE_URL"] = g["PUBLIC_MEDIA_BASE_URL"].rstrip("/")
    g["INTERVAL_HOURS"] = float(g["INTERVAL_HOURS"] or 5)
    g["REEL_SECONDS"] = int(g["REEL_SECONDS"] or 8)
    g["MUSIC_DIR"] = Path(g["MUSIC_DIR"]) if g["MUSIC_DIR"] else BASE_DIR / "assets" / "music"


reload()
