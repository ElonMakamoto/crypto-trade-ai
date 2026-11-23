"""The writer: picks a keyword, researches it, and writes a Naver-SEO blog post with Gemini.

The writing rules are the naver-seo-writer skill (skills/naver-seo-writer/SKILL.md), a Korean Naver version of
the content-engine skill. It is sent to Gemini as the system instruction, so editing that file changes how
every post is written. A copy at %APPDATA%\\NaverBlogAuto\\skill.md overrides the bundled one.
"""
import json
import re

import config
import gemini
import keywords
import seo

MAX_REVISIONS = 2
GOOD_SCORE = 85
COPY_LIMIT = 0.30  # similarity to an earlier post above this = rewrite


def system_prompt():
    custom = config.DATA_DIR / "skill.md"
    path = custom if custom.exists() else config.SKILL_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return re.sub(r"^---.*?---\s*", "", text, flags=re.S)  # drop the skill's front matter


def label(kind, value):
    return config.CHOICES[kind].get(value, value)


def is_auto(value):
    return not value or value == config.AUTO


# ---------------------------------------------------------------- topic
def topic_text(account):
    detail = account.get("TOPIC_DETAIL", "").strip()
    topic = account.get("TOPIC", config.AUTO)
    if topic in ("custom",) or (is_auto(topic) and detail):
        return detail
    base = label("TOPIC", topic) if not is_auto(topic) else ""
    return f"{base} — {detail}" if base and detail else base or detail


def ensure_topic(aid, account):
    """'Auto' topic: the AI picks one niche once and the account keeps it (Naver's C-Rank rewards blogs that stay
    on one topic). The two accounts get different niches."""
    if topic_text(account):
        return topic_text(account)
    others = [topic_text(config.load_account(o)) for o in config.other_accounts(aid)]
    trend = keywords.trending()[:15]
    answer = gemini.generate_json(
        "새 네이버 블로그의 주제(니치)를 하나 정해 주세요.\n"
        "조건: 검색 수요가 꾸준하고, 정보성 글을 매일 1~2개 쓸 수 있고, 애드포스트·체험단 등 수익화가 쉬운 주제. "
        "너무 넓지 않게 (예: '재테크' 대신 '사회초년생 재테크·절약').\n"
        f"다른 계정이 이미 쓰는 주제(겹치지 않게): {others or '없음'}\n"
        f"요즘 한국 인기 검색어(참고만): {', '.join(trend) or '알 수 없음'}\n"
        f"글쓴이 소개: {account.get('PERSONA') or '없음'}\n"
        'JSON으로만 답하세요: {"topic": "주제 (20자 이내)", "reason": "고른 이유 한 줄"}',
        temperature=0.9)
    topic = str(answer.get("topic", "")).strip()[:40] or "생활 정보·꿀팁"
    print(f"🧭 AI가 고른 블로그 주제: {topic} — {answer.get('reason', '')}")
    account["TOPIC_DETAIL"] = topic
    config.save_account(aid, {"TOPIC_DETAIL": topic})
    return topic


# ---------------------------------------------------------------- keyword
def used_keywords(aid, days_other=30):
    """Keywords this account already posted, plus the other account's recent ones (no duplicate posts)."""
    import time

    used = {keywords.squash(h.get("keyword")) for h in config.load_history(aid)}
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days_other * 86400))
    for other in config.other_accounts(aid):
        used |= {keywords.squash(h.get("keyword")) for h in config.load_history(other) if h.get("time", "") >= cutoff}
    return used


def queued_keyword(aid, account):
    used = used_keywords(aid)
    for line in account.get("KEYWORDS", "").splitlines():
        kw = line.strip().lstrip("-•*").strip()
        if kw and not kw.startswith("#") and keywords.squash(kw) not in used:
            return kw
    return None


def auto_keyword(aid, account):
    """The AI picks the next keyword: real searches (Naver/Google autocomplete) around the blog's topic, long-tail,
    not posted before, leaning toward what already ranked well for this blog."""
    topic = ensure_topic(aid, account)
    history = config.load_history(aid)
    used = used_keywords(aid)
    good = [h["keyword"] for h in history if h.get("blog_rank") and 0 < h["blog_rank"] <= 10][-10:]
    weak = [h["keyword"] for h in history if h.get("blog_rank") == 0][-10:]
    trend = keywords.trending()[:20]
    seeds = gemini.generate_json(
        f"네이버 블로그 주제: {topic}\n"
        f"이미 쓴 키워드(다시 쓰지 않음): {', '.join(h['keyword'] for h in history[-40:]) or '없음'}\n"
        f"검색 상위에 오른 키워드(이런 방향을 더): {', '.join(good) or '아직 없음'}\n"
        f"노출이 안 된 키워드(경쟁이 센 방향은 피함): {', '.join(weak) or '아직 없음'}\n"
        f"요즘 한국 인기 검색어(주제와 맞을 때만 참고): {', '.join(trend) or '알 수 없음'}\n"
        "이 블로그가 다음에 쓸 글의 '검색 씨앗어' 8개를 만들어 주세요. 사람들이 네이버에 실제로 치는 짧은 검색어 "
        "(2~3단어). 꾸준히 검색되는 것 6개 + 요즘 뜨는 것 2개.\n"
        'JSON으로만: {"seeds": ["...", "..."]}', temperature=0.9).get("seeds", [])
    candidates = []
    for seed in [s for s in seeds if isinstance(s, str)][:8]:
        for phrase in keywords.naver_autocomplete(seed)[:8] + keywords.google_suggest(seed)[:5]:
            if keywords.squash(phrase) not in used and 4 <= len(phrase) <= 25:
                candidates.append(phrase)
    candidates = list(dict.fromkeys(candidates))[:60]
    print(f"🔎 실제 검색어 후보 {len(candidates)}개 (네이버·구글 자동완성)")
    answer = gemini.generate_json(
        f"네이버 블로그 주제: {topic}\n"
        f"실제 검색어 후보 (네이버·구글 자동완성에서 모음):\n{json.dumps(candidates, ensure_ascii=False)}\n"
        f"이미 쓴 키워드: {', '.join(h['keyword'] for h in history[-40:]) or '없음'}\n"
        f"상위 노출된 키워드: {', '.join(good) or '없음'} / 노출 안 된 키워드: {', '.join(weak) or '없음'}\n"
        "다음 글의 메인 키워드 하나를 고르세요. 기준: 주제에 맞음, 검색 의도가 분명함, 2~4단어 롱테일(새 블로그도 "
        "상위 노출 가능), 정보성 글로 확실한 답을 줄 수 있음, 이미 쓴 것과 겹치지 않음. 후보가 비어 있으면 같은 기준으로 "
        "직접 만드세요.\n"
        'JSON으로만: {"keyword": "...", "reason": "한 줄"}', temperature=0.7)
    keyword = str(answer.get("keyword", "")).strip()
    if not keyword:
        raise gemini.GeminiError("AI가 키워드를 고르지 못했어요.")
    print(f"🎯 AI가 고른 키워드: {keyword} — {answer.get('reason', '')}")
    return keyword


def next_keyword(aid, account):
    keyword = queued_keyword(aid, account)
    if keyword:
        print(f"🎯 키워드 목록에서: {keyword}")
        return keyword
    if account.get("AUTO_KEYWORDS", "1") == "1":
        return auto_keyword(aid, account)
    raise ValueError("키워드 목록에 남은 키워드가 없습니다. 키워드를 더 넣거나 'AI가 알아서 고르기'를 켜 주세요.")


# ---------------------------------------------------------------- research
def research(keyword, related):
    """Fresh facts for the post: Gemini with Google Search, plus recent news headlines."""
    notes = gemini.research(
        f"네이버 블로그에 '{keyword}' 글을 쓰려고 합니다. 구글 검색으로 최신 정보를 조사해서 한국어 메모로 정리해 주세요.\n"
        f"함께 다룰 연관검색어: {', '.join(related[:10]) or '없음'}\n"
        "- 검색한 사람이 가장 알고 싶은 답\n- 핵심 사실, 숫자, 금액, 날짜, 조건, 절차 (출처 기관·매체 이름과 함께)\n"
        "- 자주 묻는 질문과 답\n- 헷갈리기 쉬운 점, 주의할 점\n"
        "확인되지 않은 내용은 쓰지 말고, 날짜가 중요한 정보는 기준 날짜를 적어 주세요. 1,500자 안팎.")
    headlines = keywords.news(keyword, 8)
    if headlines:
        notes += "\n\n[최근 뉴스 제목]\n" + "\n".join(f"- {h['title']} ({h['date']})" for h in headlines)
    return notes.strip()


# ---------------------------------------------------------------- writing
FORMAT = """JSON으로만 답하세요. 형식:
{
 "search_intent": "정보형|방법형|비교형|구매형|이슈형 중 하나",
 "angle": "이 글이 주는 핵심 답 한 문장",
 "style": "실제로 쓴 글 스타일", "tone": "실제로 쓴 말투",
 "title": "제목",
 "intro": ["첫 문단 (메인 키워드 + 핵심 답)", "둘째 문단"],
 "sections": [
   {"heading": "소제목", "paragraphs": ["문단", "문단"], "bullets": ["목록 항목 (없으면 빈 배열)"],
    "image": {"query_en": "photo search words in English", "points": ["카드 문구 1", "카드 문구 2"],
              "caption": "사진 아래 설명 한 문장 (키워드 자연스럽게)"}}
 ],
 "summary": ["한눈에 정리 1", "2", "3"],
 "faq": [{"q": "질문", "a": "답"}],
 "outro": ["마무리 문단"],
 "tags": ["태그 10개, 띄어쓰기·# 없이"],
 "related_used": ["본문에 실제로 넣은 연관검색어들"],
 "thumbnail_title": "대표 이미지에 크게 넣을 제목 (16자 이내, 줄바꿈할 곳에 /)",
 "image_style": "minimal|pastel|dark|memo|magazine 중 글에 어울리는 것"
}
문단 안에서 강조할 단어는 **굵게** 표시하세요 (문단당 1번 이하)."""


def _settings_text(account, n_images):
    length = account.get("LENGTH", config.AUTO)
    min_chars = seo.MIN_CHARS.get(length, seo.MIN_CHARS["auto"])
    pick = "자동 — 검색 의도에 맞게 직접 고르세요"
    return (
        f"[블로그 주제] {topic_text(account) or '자유'}\n"
        f"[글 스타일] {pick if is_auto(account.get('STYLE')) else label('STYLE', account['STYLE'])}\n"
        f"[말투] {pick if is_auto(account.get('TONE')) else label('TONE', account['TONE'])}\n"
        f"[분량] 공백 제외 {min_chars:,}자 이상 (공백 포함 약 {int(min_chars * 1.25):,}자 이상)"
        f"{' — 키워드에 맞게 더 길게 써도 됨' if is_auto(length) else ''}\n"
        f"[글쓴이] {account.get('PERSONA') or '정보를 꼼꼼히 정리해 주는 블로거 (경험담 없음)'}\n"
        f"[내 메모 — 실제 경험·사실, 이것만 경험으로 쓸 수 있음]\n{account.get('MEMO') or '없음'}\n"
        f"[이미지] 대표 이미지 + 소제목 이미지 {max(1, n_images - 2)}장 + 한눈에 정리 카드 → 소제목은 "
        f"최소 {max(4, n_images - 2)}개\n"
        f"[이미지 스타일] {'자동 — 글에 어울리게' if is_auto(account.get('IMAGE_STYLE')) else account['IMAGE_STYLE']}"
    )


def _normalize(post, keyword):
    def strings(value):
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        return [str(v).strip() for v in value or [] if str(v).strip()]

    out = {k: post.get(k) for k in ("search_intent", "angle", "style", "tone", "image_style")}
    out["title"] = re.sub(r"\s+", " ", str(post.get("title", ""))).strip()
    out["intro"] = strings(post.get("intro"))
    out["sections"] = []
    for s in post.get("sections") or []:
        if not isinstance(s, dict) or not str(s.get("heading", "")).strip():
            continue
        image = s.get("image") if isinstance(s.get("image"), dict) else {}
        out["sections"].append({
            "heading": str(s["heading"]).strip(), "paragraphs": strings(s.get("paragraphs")),
            "bullets": strings(s.get("bullets")),
            "image": {"query_en": str(image.get("query_en", "")).strip(), "points": strings(image.get("points"))[:3],
                      "caption": str(image.get("caption", "")).strip()}})
    out["summary"] = strings(post.get("summary"))[:5]
    out["faq"] = [{"q": str(f.get("q", "")).strip(), "a": str(f.get("a", "")).strip()}
                  for f in post.get("faq") or [] if isinstance(f, dict) and f.get("q") and f.get("a")][:5]
    out["outro"] = strings(post.get("outro"))
    tags = [re.sub(r"[\s#]", "", t) for t in strings(post.get("tags"))]
    main = keywords.squash(keyword)
    tags = list(dict.fromkeys([main] + [t for t in tags if t]))[:12]
    out["tags"] = tags
    out["related_used"] = strings(post.get("related_used"))
    out["thumbnail_title"] = str(post.get("thumbnail_title") or out["title"]).strip()
    if out["image_style"] not in ("minimal", "pastel", "dark", "memo", "magazine"):
        out["image_style"] = None
    return out


def write(keyword, must, extra, notes, account, n_images):
    prompt = (
        f"[메인 키워드] {keyword}\n"
        f"[반드시 넣을 연관검색어 — 네이버·구글에서 실제로 검색되는 말, 원래 형태 그대로 모두 넣기]\n"
        f"{', '.join(must) if must else '(수집 실패 — 사람들이 실제로 검색할 연관검색어 6개를 직접 정해서 넣고 related_used에 적기)'}\n"
        f"[추가 연관검색어 — FAQ와 본문에 자연스럽게]\n{', '.join(extra) or '없음'}\n"
        f"{_settings_text(account, n_images)}\n\n"
        f"[조사 메모 — 사실은 여기서만]\n{notes or '조사 메모 없음: 확실히 아는 일반 상식만 쓰고, 날짜·금액처럼 바뀌는 정보는 확인 방법을 안내'}\n\n"
        f"스킬의 작성 순서와 품질 검사를 지켜 네이버 블로그 글을 쓰세요.\n{FORMAT}")
    return _normalize(gemini.generate_json(prompt, system=system_prompt(), temperature=0.8), keyword)


def revise(post, keyword, must, notes, account, n_images, issues):
    prompt = (
        f"아래 네이버 블로그 글(JSON)을 고쳐 주세요. 메인 키워드: {keyword}\n"
        f"반드시 넣을 연관검색어: {', '.join(must) or '없음'}\n"
        f"{_settings_text(account, n_images)}\n\n"
        "[고칠 점 — 모두 해결]\n" + "\n".join(f"- {i}" for i in issues) +
        f"\n\n[조사 메모 — 새 사실은 여기서만]\n{notes or '없음'}\n\n"
        f"[지금 글]\n{json.dumps(post, ensure_ascii=False)}\n\n"
        f"좋은 부분은 살리고 고칠 점만 해결한 전체 글을 같은 형식으로 다시 주세요.\n{FORMAT}")
    return _normalize(gemini.generate_json(prompt, system=system_prompt(), temperature=0.5), keyword)


def earlier_texts(aid, limit=40):
    """Body texts of recent posts from both accounts (to avoid near-copies)."""
    texts = []
    for a in config.ACCOUNTS:
        for h in config.load_history(a)[-limit:]:
            path = h.get("json")
            try:
                texts.append(seo.body_text(json.loads(open(path, encoding="utf-8").read())["post"]))
            except (OSError, ValueError, KeyError, TypeError):
                continue
    return texts


def image_count(account):
    value = account.get("IMAGE_COUNT", config.AUTO)
    return int(value) if value in ("4", "5", "6") else None


def generate(aid, account, keyword=None):
    """Keyword -> related searches -> research -> post -> SEO gate (rewrite until it passes).
    Returns {"keyword", "related", "notes", "post", "seo"}."""
    keyword = keyword or next_keyword(aid, account)
    rel = keywords.related(keyword)
    ranked = rel["ranked"]
    print(f"🔎 연관검색어 — 네이버 {len(rel['naver'])}개, 구글 {len(rel['google'])}개")
    if ranked:
        print("   " + ", ".join(ranked[:12]))
    else:
        print("   (네이버·구글에 연결하지 못해 AI가 연관검색어를 직접 정합니다)")
    must, extra = ranked[:6], ranked[6:14]
    print("📚 최신 정보 조사 중 (구글 검색 + 뉴스)...")
    notes = research(keyword, ranked)
    n_images = image_count(account) or 5
    print("✍ 글 쓰는 중...")
    post = write(keyword, must, extra, notes, account, n_images)
    must = must or post["related_used"][:6]
    length = account.get("LENGTH", config.AUTO)
    result = seo.analyze(post, keyword, must, length)
    print(seo.report(result))
    earlier = earlier_texts(aid)
    best = (result["score"], post, result)
    for attempt in range(MAX_REVISIONS):
        copy = max((seo.similarity(seo.body_text(post), t) for t in earlier), default=0)
        issues = list(result["issues"])
        if copy > COPY_LIMIT:
            issues.append(f"예전 글과 {copy:.0%} 겹칩니다. 같은 사실이라도 각도, 소제목, 문장을 완전히 새로 쓰세요.")
        if result["score"] >= GOOD_SCORE and copy <= COPY_LIMIT:
            break
        print(f"🔧 SEO 보완 ({attempt + 1}/{MAX_REVISIONS}): " + " / ".join(i[:40] for i in issues))
        post = revise(post, keyword, must, notes, account, n_images, issues)
        result = seo.analyze(post, keyword, must, length)
        print(seo.report(result))
        if result["score"] >= best[0]:
            best = (result["score"], post, result)
    _, post, result = best
    return {"keyword": keyword, "related": rel, "must": must, "notes": notes, "post": post, "seo": result}
