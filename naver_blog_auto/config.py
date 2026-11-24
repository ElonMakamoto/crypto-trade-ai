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
        "travel": "여행·나들이", "food": "맛집·요리·레시피", "health": "건강·의학 상식", "parenting": "육아·교육",
        "beauty": "뷰티·패션", "self": "자기계발·공부", "pet": "반려동물", "home": "살림·인테리어",
        "car": "자동차", "realestate": "부동산", "culture": "영화·드라마·책",
        "love_show": "💕 연애예능 이슈 (연애전쟁·나는솔로·환승연애)", "love_star": "💕 스타 연애·결혼·결별 소식",
        "love_psych": "💕 연애 고민·심리", "love_conflict": "💕 커플 갈등·이별", "love_some": "💕 썸·고백",
        "love_marriage": "💕 결혼·돌싱 이야기",
        "custom": "직접 입력 (아래 세부 주제)",
    },
    "STYLE": {
        "honest_review": "솔직 리뷰형 (기본)", AUTO: "🤖 자동 (검색 의도에 맞게)", "guide": "정보형 가이드", "howto": "방법·단계형 (How-to)",
        "list": "리스트형 (TOP N·추천)", "compare": "비교·장단점형", "qa": "Q&A형", "news": "이슈·뉴스 해설형",
        "review": "리뷰형 (내 메모의 실제 경험만 사용)",
    },
    "TONE": {
        "mom40": "40대 여성 블로거, 친근한 수다체 (기본)", AUTO: "🤖 자동", "friendly": "친근한 해요체", "expert": "전문가 느낌 합니다체", "plain": "담백한 설명체",
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
    "FORMAT": {"story": "기사형 — 짧은 줄·인용구 소제목·사진 많이 (기본)", "seo": "SEO 정보형 (예전 방식)"},
}

COMMON_DEFAULTS = {
    "GOOGLE_API_KEY": "",
    "GEMINI_MODEL": "gemini-2.5-flash",
    "PIXABAY_API_KEY": "",
    "PEXELS_API_KEY": "",
    "BROWSER": "msedge",  # msedge (built into Windows) or chrome
    "SHOW_BROWSER": "1",  # show the browser window while posting (recommended)
    # {app category: Naver blog category name} as JSON; empty entries fall back to LOVE[...]["naver"] / the AI
    "CATEGORY_MAP": "",
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
    "STYLE": "honest_review",
    "TONE": "mom40",
    "CATEGORY": "",  # blog category to post in; empty = the AI picks the best fitting one
    "FORMAT": "story",  # "story" = the tidy news-story layout for every category, "seo" = the older SEO layout
    "PRESET": "",  # set once a known blog's preset was applied
    "V2": "",  # set once the account moved to the review style defaults
    "LENGTH": AUTO,
    "IMAGE_STYLE": AUTO,
    "IMAGE_SOURCE": AUTO,
    "IMAGE_COUNT": AUTO,
    "PUBLISH": "publish",
    "KEYWORDS": "",  # one keyword per line; empty = the AI picks
    "AUTO_KEYWORDS": "1",
    "POST_TIMES": "",
}
# 연애 categories: written as news-story posts in the reference style (story mode). Each has its own news search
# seeds, writing focus, default tags and default Naver blog category name.
LOVE = {
    "love_show": {"seeds": ["연애전쟁", "나는솔로", "환승연애", "솔로지옥", "돌싱글즈", "연애 예능"],
                  "focus": "연애 리얼리티 예능의 최신 회차 이슈 (출연자 사연, MC 반응, 출연자의 선택과 결과)",
                  "tags": ["연애예능", "연애리얼리티"], "naver": "연애예능 이슈"},
    "love_star": {"seeds": ["열애 인정", "결혼 발표", "결별", "열애설", "스타 결혼"],
                  "focus": "스타의 연애·결혼·결별 소식 (공식 입장, 소속사 발표, 지금까지의 경과)",
                  "tags": ["스타열애", "연예계소식"], "naver": "스타 연애·결혼"},
    "love_psych": {"seeds": ["연애 심리", "연애 고민", "연애 상담", "애착 유형"],
                   "focus": "방송·기사로 화제가 된 연애 고민과 심리 (전문가 설명, 사례)",
                   "tags": ["연애고민", "연애심리"], "naver": "연애 고민·심리"},
    "love_conflict": {"seeds": ["커플 갈등", "이별 사연", "부부 갈등", "연애 갈등 방송"],
                      "focus": "화제가 된 커플 갈등·이별 사연 (무슨 일이 있었고, 어떤 선택을 했는지)",
                      "tags": ["커플갈등", "이별"], "naver": "커플 갈등·이별"},
    "love_some": {"seeds": ["썸", "고백", "짝사랑", "썸 타는"],
                  "focus": "화제가 된 썸·고백 이야기 (방송·스타·설문 결과)",
                  "tags": ["썸", "고백"], "naver": "썸·고백"},
    "love_marriage": {"seeds": ["결혼 발표", "돌싱", "재혼", "이혼 숙려", "돌싱글즈"],
                      "focus": "결혼·돌싱·재혼 이야기 (방송·스타 소식, 공식 발표)",
                      "tags": ["결혼", "돌싱"], "naver": "결혼·돌싱 이야기"},
}


# news-story seeds for the other categories (연애 ones are in LOVE)
STORY_TOPICS = {
    "health": {"seeds": ["건강", "질병", "건강검진", "의학 연구", "영양제", "식약처"],
               "focus": "건강·의학 최신 소식 (연구 결과, 질병 정보, 건강 관리 — 기사와 공식 기관 발표 기준)",
               "tags": ["건강정보", "의학상식"]},
    "money": {"seeds": ["재테크", "금리", "적금", "주식", "연말정산"], "focus": "재테크·경제 최신 소식",
              "tags": ["재테크", "경제소식"]},
    "policy": {"seeds": ["지원금", "정부 지원", "신청 방법", "제도 변경"], "focus": "정부 지원금·제도 최신 소식",
               "tags": ["지원금", "정부정책"]},
    "life": {"seeds": ["생활 정보", "꿀팁", "생활비"], "focus": "생활 정보 최신 소식", "tags": ["생활정보", "꿀팁"]},
    "it": {"seeds": ["스마트폰", "AI", "신제품 출시", "앱"], "focus": "IT·테크 최신 소식", "tags": ["IT소식", "테크"]},
    "food": {"seeds": ["맛집", "레시피", "신메뉴"], "focus": "맛집·요리 최신 소식", "tags": ["맛집", "요리"]},
    "travel": {"seeds": ["여행", "축제", "가볼만한곳"], "focus": "여행·나들이 최신 소식", "tags": ["여행", "나들이"]},
    "parenting": {"seeds": ["육아", "교육", "어린이집", "입시"], "focus": "육아·교육 최신 소식", "tags": ["육아", "교육"]},
    "beauty": {"seeds": ["뷰티", "화장품", "패션"], "focus": "뷰티·패션 최신 소식", "tags": ["뷰티", "패션"]},
}

# known blogs: settings applied once after the Naver login finds the blog (the user can still change them)
BLOG_PRESETS = {
    "chedamso": {"TOPIC": "health", "CATEGORY": "나와의관계", "FORMAT": "story"},
}


def is_love(topic):
    return topic in LOVE


def category_map():
    """{app category: Naver blog category name}, the saved names over the defaults."""
    try:
        saved = json.loads(load_common().get("CATEGORY_MAP") or "{}")
    except ValueError:
        saved = {}
    out = {k: v["naver"] for k, v in LOVE.items()}
    out.update({k: str(v).strip() for k, v in saved.items() if str(v).strip()})
    return out


def save_category_map(mapping):
    save_common({"CATEGORY_MAP": json.dumps({k: v.strip() for k, v in mapping.items() if v.strip()},
                                            ensure_ascii=False)})


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
    if saved and not values["V2"]:
        # once: friendly 40s-woman review voice for accounts that were on "auto"
        if values["TONE"] == AUTO:
            values["TONE"] = "mom40"
        if values["STYLE"] == AUTO:
            values["STYLE"] = "honest_review"
        values["V2"] = "1"
        save_account(aid, {"TONE": values["TONE"], "STYLE": values["STYLE"], "V2": "1"})
    preset = BLOG_PRESETS.get(values.get("BLOG_ID", "").lower())
    if preset and values.get("PRESET") != values["BLOG_ID"].lower():
        values.update(preset, PRESET=values["BLOG_ID"].lower())
        save_account(aid, dict(preset, PRESET=values["PRESET"]))
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
