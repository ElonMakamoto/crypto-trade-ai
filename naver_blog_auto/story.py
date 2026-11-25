"""Story mode for the 연애 categories: a news-story post in the reference style.

    title       [person/show] + "direct quote" + concrete number/fact + hook ("~한 이유", "결국 ~")
    opening     image + gray caption "이름 / 출처: 언론사", the quote, a question, then the context
    sections    4-5, each: a quotation-style subtitle, 1-2 images with captions, very short lines
    ending      a reader question, then the image-source footer

Facts and quotes come only from what several news outlets reported (Gemini with Google Search + Google News);
the post is written in new sentences, never copied from one article.
"""
import json
import re
from urllib.parse import urlparse

import config
import gemini
import keywords
import seo

STORY_SKILL = config.BASE_DIR / "skills" / "naver-love-story" / "SKILL.md"
MAX_REVISIONS = 2
GOOD_SCORE = 85

OUTLETS = {
    "topstarnews.net": "톱스타뉴스", "mhnse.com": "MHN스포츠", "wikitree.co.kr": "위키트리", "tenasia.co.kr": "텐아시아",
    "newsen.com": "뉴스엔", "isplus.com": "일간스포츠", "osen.co.kr": "OSEN", "xportsnews.com": "엑스포츠뉴스",
    "starnewskorea.com": "스타뉴스", "mt.co.kr": "머니투데이", "sports.donga.com": "스포츠동아", "donga.com": "동아일보",
    "sportschosun.com": "스포츠조선", "chosun.com": "조선일보", "news1.kr": "뉴스1", "newsis.com": "뉴시스",
    "yna.co.kr": "연합뉴스", "joongang.co.kr": "중앙일보", "jtbc.co.kr": "JTBC", "mbn.co.kr": "MBN", "sbs.co.kr": "SBS",
    "imbc.com": "MBC", "kbs.co.kr": "KBS", "tvchosun.com": "TV조선", "ichannela.com": "채널A", "mydaily.co.kr": "마이데일리",
    "dispatch.co.kr": "디스패치", "sportsseoul.com": "스포츠서울", "heraldcorp.com": "헤럴드경제", "hankyung.com": "한국경제",
    "mk.co.kr": "매일경제", "edaily.co.kr": "이데일리", "asiae.co.kr": "아시아경제", "nate.com": "네이트",
    "tvreport.co.kr": "TV리포트", "ilgan.co.kr": "일간스포츠", "insight.co.kr": "인사이트", "kukinews.com": "쿠키뉴스",
    "sportsworldi.com": "스포츠월드", "segye.com": "세계일보", "hankookilbo.com": "한국일보", "khan.co.kr": "경향신문",
}


def outlet(url_or_title):
    """'https://www.mhnse.com/...' or 'mhnse.com' -> 'MHN스포츠' (unknown sites: the bare domain)."""
    text = url_or_title or ""
    host = urlparse(text).netloc if "://" in text else text
    host = host.lower().split(":")[0]
    host = re.sub(r"^(www|m|news|n|star|entertain|enter)\.", "", host)
    for domain, name in OUTLETS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host or text


def system_prompt():
    try:
        return re.sub(r"^---.*?---\s*", "", STORY_SKILL.read_text(encoding="utf-8"), flags=re.S)
    except OSError:
        return ""


def topic_info(aid, account):
    """Search seeds, writing focus, tags and label of the account's category (any category, not only 연애)."""
    topic = account.get("TOPIC", config.AUTO)
    if topic in config.LOVE:
        return dict(config.LOVE[topic], label=config.CHOICES["TOPIC"][topic])
    if topic in config.STORY_TOPICS:
        info = dict(config.STORY_TOPICS[topic], label=config.CHOICES["TOPIC"][topic])
        if account.get("TOPIC_DETAIL"):
            info["seeds"] = [account["TOPIC_DETAIL"]] + info["seeds"]
        return info
    if topic == "hot":
        return {"seeds": keywords.trending()[:6] or ["화제"], "focus": "지금 한국에서 가장 화제인 소식",
                "tags": ["이슈", "화제"], "label": config.CHOICES["TOPIC"]["hot"]}
    import writer

    name = writer.topic_text(account) or writer.ensure_topic(aid, account)
    name = re.sub(r"[^\w\s·]", "", name).strip()
    return {"seeds": [w for w in re.split(r"[·,/\s]+", name) if len(w) >= 2][:5] or [name],
            "focus": f"{name} 분야의 최신 소식과 정보", "tags": [name.replace(" ", "")[:15]], "label": name}


def is_health(account):
    return account.get("TOPIC") == "health"


# ---------------------------------------------------------------- 1. which story
def pick_story(aid, account):
    """The newest story that several outlets covered, in the account's category."""
    import writer

    info = topic_info(aid, account)
    used = writer.used_keywords(aid)
    history = config.load_history(aid)
    headlines = []
    for seed in info["seeds"]:
        for item in keywords.news(seed, 8, days=3):
            headlines.append(f"{item['title']} ({item['date']})")
    headlines = list(dict.fromkeys(headlines))[:60]
    print(f"📰 '{info['label']}' 최근 3일 기사 {len(headlines)}개")
    answer = gemini.generate_json(
        f"카테고리: {info['label']} — {info['focus']}\n"
        f"최근 3일 뉴스 제목 (제목 - 언론사 (날짜)):\n" + "\n".join(f"- {h}" for h in headlines) + "\n"
        f"이미 쓴 키워드(같은 이야기는 다시 쓰지 않음): {', '.join(h['keyword'] for h in history[-40:]) or '없음'}\n"
        "네이버 블로그에 쓸 이야기 하나를 고르세요. 기준: 가장 최근이고, 여러 언론사가 함께 다뤄 사실을 교차 확인할 수 "
        "있고, 직접 인용과 숫자가 있는 이야기. 위 목록이 비어 있으면 이 카테고리에서 지금 화제인 이야기를 고르세요.\n"
        'JSON으로만: {"keyword": "검색 키워드 2~4단어 (예: 연애전쟁 술꾼 커플)", "story": "어떤 이야기인지 한 줄", '
        '"reason": "한 줄"}', temperature=0.6)
    keyword = str(answer.get("keyword", "")).strip()
    if not keyword:
        raise gemini.GeminiError("AI가 이야기를 고르지 못했어요.")
    if keywords.squash(keyword) in used:
        print(f"   (이미 쓴 키워드라 이야기를 바꿔 다시 고릅니다: {keyword})")
    print(f"🎯 이야기: {keyword} — {answer.get('story', '')}")
    return keyword, str(answer.get("story", "")).strip()


# ---------------------------------------------------------------- 2. research from several outlets
def research(keyword, story):
    notes, sources = gemini.research_with_sources(
        f"네이버 블로그 글을 쓰려고 합니다. 이야기: {story or keyword} (키워드: {keyword})\n"
        "구글 검색으로 이 이야기를 다룬 여러 언론사 기사(최소 3곳)를 비교해서 한국어 메모로 정리해 주세요. 각 사실 옆에 "
        "(언론사 이름)을 붙이세요.\n"
        "- 언제, 어느 프로그램 몇 회(방송사, 방송일), 프로그램 소개, MC\n"
        "- 등장인물: 이름, 나이, 관계, 교제·결혼 기간 등 기사에 나온 숫자\n"
        "- 직접 인용: 누가 한 말인지와 말 그대로 (\"...\"라고 했다)\n"
        "- 흐름: 상황 → 문제 → 전문가·MC 반응 → 당사자의 선택 → 결과·이후 소식\n"
        "- 아직 공식 발표되지 않았거나 확인되지 않은 것\n"
        "기사마다 다르게 적힌 숫자는 다르다고 적으세요. 기사에 없는 것은 쓰지 마세요.")
    # the articles themselves (Naver News): real facts and quotes even when Google-search research isn't available
    import naver

    articles = 0
    for url in naver.find_articles(keyword, 10):
        title, text = keywords.article_text(url)
        if len(text) < 200:
            continue
        name = outlet(url) if "naver.com" not in url and "daum.net" not in url else ""
        notes += f"\n\n[기사 {articles + 1}] {title} {('— ' + name) if name else ''}\n{text}"
        articles += 1
        if articles >= 4:
            break
    print(f"   기사 본문 {articles}개를 읽었어요")
    headlines = keywords.news(keyword, 10, days=14)
    if headlines:
        notes += "\n\n[관련 기사 제목 — 제목 - 언론사 (날짜)]\n" + "\n".join(
            f"- {h['title']} ({h['date']})" for h in headlines)
    names = [outlet(s["title"] or s["uri"]) for s in sources]
    names += [h["title"].rsplit(" - ", 1)[1].strip() for h in headlines if " - " in h["title"]]
    return notes.strip(), sources, list(dict.fromkeys(n for n in names if n))


# ---------------------------------------------------------------- 3. writing
FORMAT = """JSON으로만 답하세요. 형식:
{
 "keyword": "메인 키워드 (프로그램명이나 인물명이 들어간 2~4단어)",
 "title": "제목",
 "opening_image": {"who": "사진에 들어갈 인물·프로그램 이름", "query": "사진 찾을 검색어 (한국어)"},
 "opening": [["한 줄", "한 줄"], ["한 줄"]],
 "sections": [
   {"heading": "짧은 소제목 (15자 이내, 따옴표 없이)",
    "images": [{"who": "인물·프로그램 이름", "query": "사진 검색어"}],
    "chunks": [["한 줄", "한 줄"], ["한 줄"]]}
 ],
 "question": "독자에게 묻는 질문 한 문장 (?로 끝남)",
 "tags": ["태그 5~10개, 띄어쓰기·# 없이"],
 "sources_used": ["실제로 사실을 가져온 언론사 이름"]
}
opening과 chunks는 "덩어리" 목록입니다. 덩어리 하나 = 1~2줄, 줄 하나 = 짧은 문장 하나(또는 문장의 앞/뒤 절반).
덩어리 사이에는 빈 줄이 들어갑니다.
글 안의 인용은 반드시 둥근 따옴표 “ ” 와 ‘ ’ 로 쓰세요. 곧은 큰따옴표(")는 JSON 문법에만 씁니다. HTML 태그는 쓰지 마세요."""


def _lines(value):
    """[["a", "b"], "c"] -> ["a\nb", "c"]: each chunk becomes one paragraph whose lines are split by \n."""
    out = []
    for chunk in value or []:
        lines = chunk if isinstance(chunk, list) else str(chunk).split("\n")
        lines = [re.sub(r"\s+", " ", str(x)).strip() for x in lines if str(x).strip()]
        if lines:
            out.append("\n".join(lines))
    return out


def normalize(raw, keyword):
    post = {"mode": "story", "keyword": str(raw.get("keyword") or keyword).strip(),
            "title": re.sub(r"\s+", " ", str(raw.get("title", ""))).strip()}
    image = raw.get("opening_image") if isinstance(raw.get("opening_image"), dict) else {}
    post["opening_image"] = {"who": str(image.get("who", "")).strip(), "query": str(image.get("query", "")).strip()}
    post["intro"] = _lines(raw.get("opening"))
    post["sections"] = []
    for s in raw.get("sections") or []:
        if not isinstance(s, dict) or not str(s.get("heading", "")).strip():
            continue
        imgs = [{"who": str(i.get("who", "")).strip(), "query": str(i.get("query", "")).strip()}
                for i in s.get("images") or [] if isinstance(i, dict)][:2]
        heading = str(s["heading"]).strip().strip("“”\"' ")
        post["sections"].append({"heading": heading, "paragraphs": _lines(s.get("chunks")), "bullets": [],
                                 "images": imgs or [{"who": post["keyword"], "query": post["keyword"]}],
                                 "image": {}})
    post["question"] = str(raw.get("question", "")).strip()
    post["outro"] = [post["question"]] if post["question"] else []
    post["summary"], post["faq"] = [], []
    tags = [re.sub(r"[\s#]", "", str(t)) for t in raw.get("tags") or []]
    post["tags"] = list(dict.fromkeys(t for t in tags if t))[:10]
    post["sources_used"] = [str(x).strip() for x in raw.get("sources_used") or [] if str(x).strip()]
    return post


def _context(account, notes, sources_text):
    info = account.get("_topic_info") or {"label": "", "focus": "", "tags": []}
    health = ("[건강·의학 글] 진단·처방처럼 쓰지 말고 기사·공식 기관이 말한 내용만 전달. 치료·약 효과를 단정하지 않기. "
              "마지막 섹션에 '증상이 있으면 전문의와 상담하세요' 한 줄.\n" if is_health(account) else "")
    return (f"[카테고리] {info['label']} — {info['focus']}\n{health}"
            f"[기본 태그 후보] {', '.join(info['tags'])}\n"
            f"[취재한 언론사] {sources_text or '조사 메모 참고'}\n"
            f"[조사 메모 — 사실·숫자·인용은 여기서만, 문장은 새로 쓰기]\n{notes or '없음'}\n")


def write(keyword, story, notes, outlets, account):
    prompt = (f"[이야기] {story or keyword}\n[키워드] {keyword}\n" + _context(account, notes, ", ".join(outlets)) +
              "\n스킬의 형식을 정확히 지켜 글을 쓰세요. 인용과 숫자는 조사 메모에 있는 것만, 문장은 한 기사에서 "
              f"베끼지 말고 여러 기사를 합쳐 새로 쓰세요.\n{FORMAT}")
    return normalize(gemini.generate_json(prompt, system=system_prompt(), temperature=0.7), keyword)


def revise(post, keyword, notes, outlets, account, issues):
    prompt = (f"아래 네이버 블로그 글(JSON)을 고쳐 주세요. 키워드: {keyword}\n" +
              _context(account, notes, ", ".join(outlets)) +
              "[고칠 점 — 모두 해결]\n" + "\n".join(f"- {i}" for i in issues) +
              f"\n\n[지금 글]\n{json.dumps(post, ensure_ascii=False)}\n\n같은 형식의 전체 글로 다시 주세요.\n{FORMAT}")
    return normalize(gemini.generate_json(prompt, system=system_prompt(), temperature=0.5), keyword)


# ---------------------------------------------------------------- 4. format check
QUOTE_RE = re.compile(r"[\"“”‘’']")
HOOK_RE = re.compile(r"(이유|결국|결말|선택|근황|까닭|사연|진짜|속사정|한 말)")
HYPE = [r"충격", r"경악", r"역대급", r"미쳤", r"소름", r"대박", r"헐", r"최악의", r"막장"]
# words that get posts flagged as spam/ads or as illegal medical advertising
RISKY = [r"카지노", r"토토", r"도박", r"바카라", r"대출", r"급전", r"성인", r"19금", r"비아그라", r"최저가", r"무료\s?증정",
         r"할인\s?코드", r"구매\s?링크", r"클릭", r"카톡\s?문의", r"오픈\s?채팅", r"완치", r"100%\s?효과", r"부작용\s?없",
         r"특효", r"기적의", r"즉효"]


def body_lines(post):
    lines = []
    for p in post.get("intro", []) + [x for s in post.get("sections", []) for x in s.get("paragraphs", [])]:
        lines += [x for x in p.split("\n") if x.strip()]
    return lines


def check(post, keyword):
    """-> same shape as seo.analyze(): score, checks, issues, stats."""
    title = post.get("title", "")
    body = seo.body_text(post)
    n_chars = seo.chars(body)
    lines = body_lines(post)
    long_lines = [x for x in lines if len(x) > 45]
    heavy_chunks = [p for p in post.get("intro", []) + [x for s in post.get("sections", [])
                                                       for x in s.get("paragraphs", [])] if p.count("\n") >= 2]
    quotes = len(re.findall(r"[\"“][^\"”]{4,}[\"”]", body))
    numbers = len(re.findall(r"\d", body))
    last = " ".join(post["sections"][-1]["paragraphs"]) if post.get("sections") else ""
    intro = " ".join(post.get("intro", []))
    hype = sorted({m.group(0) for p in HYPE + seo.BANNED for m in re.finditer(p, title + "\n" + body)})
    checks = []

    def add(ok, weight, name, detail, fix):
        checks.append({"ok": bool(ok), "weight": weight, "name": name, "detail": detail, "fix": fix})

    add(25 <= len(title) <= 42, 10, "제목 25~40자", f"{len(title)}자",
        f"제목이 {len(title)}자예요. 40자 이하로 줄이세요 (인용은 짧게, 설명 부분을 빼고 숫자와 '~한 이유'는 남기기)."
        if len(title) > 42 else "제목을 25~40자로 늘리세요.")
    add(QUOTE_RE.search(title) and HOOK_RE.search(title[-14:]), 10, "제목: 직접 인용 + 궁금증 끝맺음", title,
        "제목을 [인물/프로그램] + \"직접 인용\" + 구체적인 숫자·사실 + '~한 이유'/'결국 ~' 끝맺음으로 바꾸세요.")
    add(re.search(r"\d", title), 5, "제목에 숫자·사실", title, "제목에 기사에 나온 숫자(인원, 나이, 기간 등)를 넣으세요.")
    add(len(post.get("intro", [])) >= 4 and ("?" in intro or "까요" in intro), 10, "도입: 인용 → 질문 → 배경",
        f"덩어리 {len(post.get('intro', []))}개",
        "도입부를 인용으로 시작해 질문 한 줄('~했을까요.')을 넣고, 언제·어느 프로그램·MC·최근 회차 내용을 이어 쓰세요.")
    add(4 <= len(post.get("sections", [])) <= 5, 10, "소제목 4~5개", f"{len(post.get('sections', []))}개",
        "소제목(섹션)을 4~5개로 맞추세요: 상황 → 문제 → MC·전문가 반응 → 당사자의 선택 → 결과·이후.")
    with_spaces = seo.chars(body, spaces=True)
    add(1500 <= with_spaces <= 2600, 15, "본문 1,500~2,500자 (공백 포함)", f"공백 포함 {with_spaces:,}자",
        f"본문을 공백 포함 1,500~2,500자로 맞추세요 (지금 {with_spaces}자). 조사 메모의 사실·인용을 더 넣으세요."
        if with_spaces < 1500 else f"본문을 2,500자 안으로 줄이세요 (지금 {with_spaces}자).")
    add(len(long_lines) <= max(2, len(lines) // 10) and not heavy_chunks, 10, "짧은 줄 (덩어리당 1~2줄)",
        f"45자 넘는 줄 {len(long_lines)}개, 3줄 이상 덩어리 {len(heavy_chunks)}개",
        "줄 하나를 짧게(문장 하나 또는 문장 절반) 끊고, 덩어리 하나에 1~2줄만 넣으세요.")
    add(quotes >= 4, 10, "직접 인용 4개 이상", f"{quotes}개",
        "조사 메모에 있는 직접 인용을 더 넣으세요 (\"...\"라고 했습니다 / ~라며 일침을 가했습니다).")
    add(numbers >= 3, 5, "구체적인 숫자", f"숫자 {numbers}개", "조사 메모의 숫자(나이, 기간, 인원, 회차)를 넣으세요.")
    add("아직" in last and re.search(r"발표|확정|공개|확인", last), 5, "마지막: 아직 확정 안 된 것",
        last[-60:], "마지막 섹션에 이후 소식과 함께 '다만 ~는 아직 공식 발표되지 않았습니다' 같은 문장을 넣으세요.")
    add(post.get("question", "").endswith("?"), 5, "독자 질문으로 마무리", post.get("question", ""),
        "마지막에 독자에게 묻는 질문 한 문장(?로 끝남)을 넣으세요.")
    add(5 <= len(post.get("tags", [])) <= 10, 5, "태그 5~10개", f"{len(post.get('tags', []))}개",
        "인물·프로그램·주제 태그를 5~10개로 맞추세요.")
    add(not hype, 5, "과장·자극 표현 없음", ", ".join(hype) or "없음", f"다음 표현을 빼세요: {', '.join(hype)}")
    risky = sorted({m.group(0) for p in RISKY for m in re.finditer(p, title + "\n" + body)})
    add(not risky, 10, "저품질 위험 단어 없음 (광고·도박·의료 과장)", ", ".join(risky) or "없음",
        f"다음 단어는 네이버 저품질·광고 판정 위험이 있어요. 빼거나 다른 말로 바꾸세요: {', '.join(risky)}")
    total = sum(c["weight"] for c in checks)
    score = round(100 * sum(c["weight"] for c in checks if c["ok"]) / total)
    return {"score": score, "checks": checks, "issues": [c["fix"] for c in checks if not c["ok"]],
            "stats": {"chars": n_chars, "chars_with_spaces": seo.chars(body, spaces=True),
                      "keyword_count": seo.count(body, keyword), "headings": len(post.get("sections", [])),
                      "missing": []}}


def shorten_title(title, limit=40):
    """A title the AI kept too long: ask once for a shorter one, else drop words before the hook ending."""
    try:
        answer = gemini.generate_json(
            f"이 네이버 블로그 제목을 {limit}자 이하로 줄여 주세요. 인물·직접 인용·숫자·'~한 이유' 같은 끝맺음은 "
            f"살리고 나머지 설명을 빼세요.\n제목: {title}\n" + 'JSON으로만: {"title": "..."}', temperature=0.3)
        short = re.sub(r"\s+", " ", str(answer.get("title", ""))).strip() if isinstance(answer, dict) else ""
        if 15 <= len(short) <= limit + 2:
            return short
    except gemini.GeminiError:
        pass
    head, sep, tail = title.rpartition(", ")
    if sep:  # drop words from the start of the part after the comma: the ending stays a natural phrase
        words = tail.split(" ")
        while len(head + sep + " ".join(words)) > limit and len(words) > 2:
            words.pop(0)
        title = head + sep + " ".join(words)
    words = title.split(" ")
    while len(" ".join(words)) > limit and len(words) > 5:
        del words[-5]  # keep the last 4 words (the hook phrase: "결국 결별한 진짜 이유")
    while len(" ".join(words)) > limit and len(words) > 3:
        del words[-2]
    return " ".join(words)


# ---------------------------------------------------------------- the whole thing
def generate(aid, account, keyword=None):
    import writer

    story = ""
    account = dict(account, _topic_info=topic_info(aid, account))
    if not keyword:
        keyword = writer.queued_keyword(aid, account)
    if not keyword:
        keyword, story = pick_story(aid, account)
    print("📚 여러 언론 보도 조사 중 (구글 검색 + 뉴스)...")
    notes, sources, outlets = research(keyword, story)
    print(f"   취재 출처: {', '.join(outlets[:8]) or '없음'}")
    print("✍ 글 쓰는 중 (기사형)...")
    post = write(keyword, story, notes, outlets, account)
    result = check(post, keyword)
    print(seo.report(result))
    best = (result["score"], post, result)
    earlier = writer.earlier_texts(aid)
    for attempt in range(MAX_REVISIONS):
        copy = max((seo.similarity(seo.body_text(post), t) for t in earlier), default=0)
        issues = list(result["issues"])
        if copy > writer.COPY_LIMIT:
            issues.append(f"예전 글과 {copy:.0%} 겹칩니다. 문장을 완전히 새로 쓰세요.")
        if result["score"] >= GOOD_SCORE and copy <= writer.COPY_LIMIT:
            break
        print(f"🔧 형식 보완 ({attempt + 1}/{MAX_REVISIONS}): " + " / ".join(i[:40] for i in issues))
        post = revise(post, keyword, notes, outlets, account, issues)
        result = check(post, keyword)
        print(seo.report(result))
        if result["score"] >= best[0]:
            best = (result["score"], post, result)
    _, post, result = best
    if len(post.get("title", "")) > 42:
        post["title"] = shorten_title(post["title"])
        result = check(post, keyword)
    post["tags"] = list(dict.fromkeys(post["tags"] + account["_topic_info"]["tags"]))[:10]
    return {"keyword": post.get("keyword") or keyword, "related": {"naver": [], "google": [], "ranked": []},
            "must": [], "notes": notes, "post": post, "seo": result, "sources": sources, "outlets": outlets}
