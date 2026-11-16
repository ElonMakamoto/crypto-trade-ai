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
    # (small line, big line, sub line) of the last slide of a learning post
    "learn_follow": {"English": ("DON'T LOSE THIS PAGE", "FOLLOW NOW OR YOU'LL NEVER SEE THIS AGAIN",
                                 "New lessons every week — only followers see them"),
                     "Korean": ("이 계정, 놓치지 마세요", "지금 팔로우 안 하면 다시는 못 봐요",
                                "새로운 배움은 팔로워에게만 보여요"),
                     "Japanese": ("このアカウント、見失わないで", "今フォローしないと二度と見られません",
                                  "新しい学びはフォロワーだけに届きます")},
    "learn_follow_line": {"English": "👉 Follow {handle} now — or you'll never find these lessons again",
                          "Korean": "👉 지금 {handle} 팔로우 안 하면 이런 글, 다시는 못 봐요",
                          "Japanese": "👉 今 {handle} をフォローしないと、この学びは二度と見られません"},
    "save_line": {"English": "📌 Save this post to read it again", "Korean": "📌 저장해두고 다시 읽어보세요",
                  "Japanese": "📌 保存してまた読み返してください"},
    "source": {"English": "📰 Source: {source}", "Korean": "📰 출처: {source}", "Japanese": "📰 出典: {source}"},
}

# (headline, body, typewriter story-text) fonts per language; Anton/Montserrat have no Hangul or Kana/Kanji
FONTS = {
    "English": ("Anton-Regular.ttf", "Montserrat-Variable.ttf", "CourierPrime-Bold.ttf"),
    "Korean": ("BlackHanSans-Regular.ttf", "NotoSansKR-Variable.ttf", "NanumGothicCoding-Bold.ttf"),
    "Japanese": ("DelaGothicOne-Regular.ttf", "NotoSansJP-Variable.ttf", "MPLUS1Code-Variable.ttf"),
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
    """(headline, body, typewriter) font files for the post language."""
    return tuple(config.FONTS_DIR / name for name in FONTS[lang()])
