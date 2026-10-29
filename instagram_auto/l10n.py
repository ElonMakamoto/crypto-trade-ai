"""Text drawn on the images and added to captions, per post language (config.POST_LANGUAGE)."""
import config

TEXT = {
    "swipe": {"English": "SWIPE >>", "Korean": "넘겨보기 >>", "Japanese": "スワイプ >>"},
    "follow": {"English": "FOLLOW", "Korean": "팔로우", "Japanese": "フォロー"},
    "cta_disasters": {"English": "FOR LIVE NATURAL DISASTER UPDATES", "Korean": "실시간 자연재해 소식을 받아보세요",
                      "Japanese": "最新の自然災害情報をお届けします"},
    "cta_trending": {"English": "FOR DAILY NEWS YOU CAN'T MISS", "Korean": "놓치면 안 될 뉴스를 매일 전해요",
                     "Japanese": "毎日の注目ニュースをお届けします"},
    "actions": {"English": "LIKE  ·  SHARE  ·  SAVE", "Korean": "좋아요  ·  공유  ·  저장",
                "Japanese": "いいね  ·  シェア  ·  保存"},
    # (small line, big line, sub line) of the comment slide
    "question_disasters": {"English": ("PLEASE", "STAY SAFE", "SHARE TO KEEP OTHERS INFORMED"),
                           "Korean": ("모두", "안전하세요", "공유해서 주변에 알려주세요"),
                           "Japanese": ("どうか", "ご無事で", "シェアして周りに知らせてください")},
    "question_trending": {"English": ("WHAT DO YOU", "THINK?", "TELL US IN THE COMMENTS"),
                          "Korean": ("여러분의", "생각은?", "댓글로 알려주세요"),
                          "Japanese": ("あなたは", "どう思う？", "コメントで教えてください")},
    "ending_disasters": {"English": "Stay safe 🙏 Share to keep others informed.",
                         "Korean": "모두 안전하세요 🙏 공유해서 주변에 알려주세요.",
                         "Japanese": "どうかご無事で 🙏 シェアして周りに知らせてください。"},
    "ending_trending": {"English": "What do you think? 👇", "Korean": "여러분의 생각은? 👇",
                        "Japanese": "皆さんはどう思いますか？👇"},
    "follow_line_disasters": {"English": "👉 Follow {handle} for natural disaster updates",
                              "Korean": "👉 실시간 자연재해 소식은 {handle} 팔로우",
                              "Japanese": "👉 最新の自然災害情報は {handle} をフォロー"},
    "follow_line_trending": {"English": "👉 Follow {handle} for daily news", "Korean": "👉 매일 뉴스는 {handle} 팔로우",
                             "Japanese": "👉 毎日のニュースは {handle} をフォロー"},
    "source": {"English": "📰 Source: {source}", "Korean": "📰 출처: {source}", "Japanese": "📰 出典: {source}"},
}

# (headline font, body font) per language; Anton/Montserrat have no Hangul or Kana/Kanji
FONTS = {
    "English": ("Anton-Regular.ttf", "Montserrat-Variable.ttf"),
    "Korean": ("BlackHanSans-Regular.ttf", "NotoSansKR-Variable.ttf"),
    "Japanese": ("DelaGothicOne-Regular.ttf", "NotoSansJP-Variable.ttf"),
}


def lang():
    return config.POST_LANGUAGE if config.POST_LANGUAGE in FONTS else "English"


def t(key, **fmt):
    """Localized text; keys ending in '_' get the news focus appended (e.g. 'cta_' -> 'cta_disasters')."""
    if key.endswith("_"):
        key += "disasters" if config.NEWS_FOCUS == "disasters" else "trending"
    value = TEXT[key].get(lang(), TEXT[key]["English"])
    return value.format(**fmt) if fmt and isinstance(value, str) else value


def fonts():
    headline, body = FONTS[lang()]
    return config.FONTS_DIR / headline, config.FONTS_DIR / body
