"""Story mode for the 연애 categories: a news-story post in the reference style.

    title       [person/show] + "direct quote" + concrete number/fact + hook ("~한 이유", "결국 ~")
    opening     image + gray caption "이름 / 출처: 언론사", the quote, a question, then the context
    sections    4-5, each: a quotation-style subtitle, 1-2 images with captions, very short lines
    ending      a reader question, [함께보면 좋은 글] + a link card to my latest post, the image-source footer

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


# ---------------------------------------------------------------- 1. which story
def pick_story(aid, account):
    """The newest love story that several outlets covered, in the chosen 연애 category."""
    import writer

    info = config.LOVE[account["TOPIC"]]
    used = writer.used_keywords(aid)
    history = config.load_history(aid)
    headlines = []
    for seed in info["seeds"]:
        for item in keywords.news(seed, 8, days=3):
            headlines.append(f"{item['title']} ({item['date']})")
    headlines = list(dict.fromkeys(headlines))[:60]
    print(f"💕 '{config.CHOICES['TOPIC'][account['TOPIC']]}' 최근 3일 기사 {len(headlines)}개")
    answer = gemini.generate_json(
        f"카테고리: {config.CHOICES['TOPIC'][account['TOPIC']]} — {info['focus']}\n"
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
덩어리 사이에는 빈 줄이 들어갑니다."""


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
    info = config.LOVE[account["TOPIC"]]
    return (f"[카테고리] {config.CHOICES['TOPIC'][account['TOPIC']]} — {info['focus']}\n"
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

    add(25 <= len(title) <= 42, 10, "제목 25~40자", f"{len(title)}자", "제목을 25~40자로 맞추세요.")
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
    total = sum(c["weight"] for c in checks)
    score = round(100 * sum(c["weight"] for c in checks if c["ok"]) / total)
    return {"score": score, "checks": checks, "issues": [c["fix"] for c in checks if not c["ok"]],
            "stats": {"chars": n_chars, "chars_with_spaces": seo.chars(body, spaces=True),
                      "keyword_count": seo.count(body, keyword), "headings": len(post.get("sections", [])),
                      "missing": []}}


# ---------------------------------------------------------------- the whole thing
def generate(aid, account, keyword=None):
    import writer

    story = ""
    if not keyword:
        keyword = writer.queued_keyword(aid, account)
    if not keyword:
        keyword, story = pick_story(aid, account)
    print("📚 여러 언론 보도 조사 중 (구글 검색 + 뉴스)...")
    notes, sources, outlets = research(keyword, story)
    print(f"   취재 출처: {', '.join(outlets[:8]) or '없음'}")
    print("✍ 글 쓰는 중 (연애 이슈 형식)...")
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
    info = config.LOVE[account["TOPIC"]]
    post["tags"] = list(dict.fromkeys(post["tags"] + info["tags"]))[:10]
    return {"keyword": post.get("keyword") or keyword, "related": {"naver": [], "google": [], "ranked": []},
            "must": [], "notes": notes, "post": post, "seo": result, "sources": sources, "outlets": outlets}
