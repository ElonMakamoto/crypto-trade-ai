"""Settings for Naver Blog Auto: common settings + two Naver accounts, saved in %APPDATA%\\NaverBlogAuto.

Every choice (topic, style, tone, length, images...) has an "auto" option: the AI then decides by itself.
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
# read-only files bundled with the app (fonts, the writing skill)
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
# writable files: %APPDATA%\NaverBlogAuto for the .exe, ./data when run from source
if FROZEN:
    DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "NaverBlogAuto"
else:
    DATA_DIR = Path(os.environ.get("NAVER_BLOG_AUTO_HOME") or Path(__file__).parent / "data")

FONTS_DIR = BASE_DIR / "fonts"
SKILL_FILE = BASE_DIR / "skills" / "naver-seo-writer" / "SKILL.md"
SETTINGS_FILE = DATA_DIR / "settings.json"
OUTPUT_DIR = DATA_DIR / "output"
PROFILES_DIR = DATA_DIR / "profiles"  # one browser profile per account: the Naver login stays here
STATE_DIR = DATA_DIR / "state"

AUTO = "auto"
ACCOUNTS = {"a": "계정 1", "b": "계정 2"}

# ---------------------------------------------------------------- choices (value -> label shown in the app)
CHOICES = {
    "TOPIC": {
        AUTO: "🤖 자동 (AI가 잘 될 주제를 골라 고정)", "hot": "🔥 실시간 인기 이슈 (분야 상관없이 지금 뜨는 것)",
        "it": "IT·테크·앱", "life": "생활 정보·꿀팁", "money": "재테크·경제·절약", "policy": "정부 지원금·제도",
        "travel": "여행·나들이", "food": "맛집·요리·레시피", "health": "건강·운동 상식", "parenting": "육아·교육",
        "beauty": "뷰티·패션", "self": "자기계발·공부", "pet": "반려동물", "home": "살림·인테리어",
        "car": "자동차", "realestate": "부동산", "culture": "영화·드라마·책", "custom": "직접 입력 (아래 세부 주제)",
    },
    "STYLE": {
        AUTO: "🤖 자동 (검색 의도에 맞게)", "guide": "정보형 가이드", "howto": "방법·단계형 (How-to)",
        "list": "리스트형 (TOP N·추천)", "compare": "비교·장단점형", "qa": "Q&A형", "news": "이슈·뉴스 해설형",
        "review": "리뷰형 (내 메모의 실제 경험만 사용)",
    },
    "TONE": {
        AUTO: "🤖 자동", "friendly": "친근한 해요체", "expert": "전문가 느낌 합니다체", "plain": "담백한 설명체",
        "fun": "유쾌한 구어체",
    },
    "LENGTH": {
        AUTO: "🤖 자동 (키워드에 맞게)", "short": "짧게 (1,500자+)", "normal": "보통 (2,500자+)", "long": "길게 (3,500자+)",
    },
    "IMAGE_STYLE": {
        AUTO: "🤖 자동 (글마다 어울리게)", "minimal": "깔끔한 미니멀", "pastel": "파스텔", "dark": "다크 모던",
        "memo": "메모지·노트", "magazine": "매거진",
    },
    "IMAGE_SOURCE": {
        AUTO: "🤖 자동 (인터넷 사진 → AI 그림 → 카드)", "stock": "인터넷 사진 (알아서 찾아옴)", "ai": "AI 그림 (Gemini)",
        "card": "디자인 카드만",
    },
    "IMAGE_COUNT": {AUTO: "🤖 자동 (4~6장)", "4": "4장", "5": "5장", "6": "6장"},
    "PUBLISH": {"publish": "바로 발행", "draft": "임시저장만 (확인 후 직접 발행)"},
}

COMMON_DEFAULTS = {
    "GOOGLE_API_KEY": "",
    "GEMINI_MODEL": "gemini-2.5-flash",
    "PIXABAY_API_KEY": "",
    "PEXELS_API_KEY": "",
    "BROWSER": "msedge",  # msedge (built into Windows) or chrome
    "SHOW_BROWSER": "1",  # show the browser window while posting (recommended)
}
SECRET_KEYS = {"GOOGLE_API_KEY", "PIXABAY_API_KEY", "PEXELS_API_KEY"}

ACCOUNT_DEFAULTS = {
    "ENABLED": "1",
    "NICKNAME": "",
    "BLOG_ID": "",  # found automatically after the Naver login
    "TOPIC": AUTO,
    "TOPIC_DETAIL": "",  # e.g. "30대 직장인 재테크", or the topic the AI picked
    "PERSONA": "",  # who is writing: "10년차 직장인, 두 아이 아빠" (optional)
    "MEMO": "",  # real experiences / facts the writer may use (optional)
    "STYLE": AUTO,
    "TONE": AUTO,
    "LENGTH": AUTO,
    "IMAGE_STYLE": AUTO,
    "IMAGE_SOURCE": AUTO,
    "IMAGE_COUNT": AUTO,
    "PUBLISH": "publish",
    "KEYWORDS": "",  # one keyword per line; empty = the AI picks
    "AUTO_KEYWORDS": "1",
    "POST_TIMES": "",
}
# the two accounts post at different times by default
DEFAULT_TIMES = {"a": "09:30,19:30", "b": "11:00,21:00"}

_lock = threading.RLock()


def _read():
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(data):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, SETTINGS_FILE)


def load_common():
    import secure_store

    with _lock:
        saved = _read().get("common", {})
    values = dict(COMMON_DEFAULTS)
    for key in COMMON_DEFAULTS:
        value = saved.get(key)
        if key in SECRET_KEYS:
            value = secure_store.decrypt(value)
        values[key] = (value or os.environ.get(key) or COMMON_DEFAULTS[key]).strip()
    return values


def save_common(values):
    import secure_store

    with _lock:
        data = _read()
        common = data.get("common", {})
        for key in COMMON_DEFAULTS:
            if key in values:
                value = str(values[key]).strip()
                common[key] = secure_store.encrypt(value) if key in SECRET_KEYS else value
        data["common"] = common
        _write(data)


def load_account(aid):
    with _lock:
        saved = _read().get("accounts", {}).get(aid, {})
    values = dict(ACCOUNT_DEFAULTS, POST_TIMES=DEFAULT_TIMES.get(aid, "10:00"))
    values.update({k: str(v) for k, v in saved.items() if k in ACCOUNT_DEFAULTS})
    return values


def save_account(aid, values):
    with _lock:
        data = _read()
        accounts = data.get("accounts", {})
        current = accounts.get(aid, {})
        current.update({k: str(v) for k, v in values.items() if k in ACCOUNT_DEFAULTS})
        accounts[aid] = current
        data["accounts"] = accounts
        _write(data)


def account_label(aid, values=None):
    values = values or load_account(aid)
    name = values.get("NICKNAME") or values.get("BLOG_ID")
    return f"{ACCOUNTS[aid]} ({name})" if name else ACCOUNTS[aid]


def profile_dir(aid):
    return PROFILES_DIR / aid


def output_dir(aid):
    return OUTPUT_DIR / aid


# ---------------------------------------------------------------- history (what each account posted)
def history_file(aid):
    return STATE_DIR / f"history_{aid}.json"


def load_history(aid):
    with _lock:
        try:
            return json.loads(history_file(aid).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []


def save_history(aid, items):
    with _lock:
        path = history_file(aid)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)


def add_history(aid, item):
    with _lock:
        items = load_history(aid)
        items.append(dict(item, time=item.get("time") or time.strftime("%Y-%m-%d %H:%M")))
        save_history(aid, items[-500:])


def other_accounts(aid):
    return [a for a in ACCOUNTS if a != aid]
