"""Naver SEO quality gate: scores a written post (0-100) and lists what to fix.

The checks follow what Naver search rewards (C-Rank / D.I.A.+): the keyword at the front of the title and in the
first paragraph, enough real content, related searches covered, sub-headings, short mobile-friendly paragraphs,
no keyword stuffing, no AI filler phrases, and no copy of an earlier post.
"""
import re

import keywords

# minimum body length in characters without spaces (about 1,500 / 2,500 / 3,500 with spaces)
MIN_CHARS = {"short": 1200, "normal": 2000, "long": 2900, "auto": 1800}

BANNED = [
    r"알아보(?:겠습니다|도록 하겠습니다|ㄹ까요|아요)", r"알아볼까요", r"이번 포스팅에서는", r"오늘은 .{0,30}에 대해",
    r"많은 분들이 궁금해", r"분들 많으시죠", r"도움이 되셨(?:길|으면)", r"공감.{0,6}댓글", r"이웃\s?추가",
    r"획기적인", r"혁신적인", r"필수적인", r"완벽한", r"게임\s?체인저", r"중요한 역할을 합니다",
    r"라고 할 수 있습니다", r"무조건", r"100%", r"마무리하며", r"결론적으로",
    r"살펴보(?:겠습니다|도록 하겠습니다)", r"정리해 보겠습니다", r"에 대해 자세히", r"는 점을 기억", r"꼭 참고하시",
]
BANNED_RE = [re.compile(p) for p in BANNED]


def clean(text):
    return re.sub(r"\*\*(.+?)\*\*", r"\1", str(text or "")).strip()


def paragraphs(post):
    """Every body paragraph (headings excluded) in reading order."""
    out = [clean(p) for p in post.get("intro", [])]
    for section in post.get("sections", []):
        out += [clean(p) for p in section.get("paragraphs", [])]
        out += [clean(b) for b in section.get("bullets", [])]
    out += [clean(s) for s in post.get("summary", [])]
    for qa in post.get("faq", []):
        out += [clean(qa.get("q")), clean(qa.get("a"))]
    out += [clean(p) for p in post.get("outro", [])]
    return [p for p in out if p]


def headings(post):
    return [clean(s.get("heading")) for s in post.get("sections", []) if clean(s.get("heading"))]


def body_text(post):
    parts = [clean(p) for p in post.get("intro", [])]
    for section in post.get("sections", []):
        parts.append(clean(section.get("heading")))
        parts += [clean(p) for p in section.get("paragraphs", [])]
        parts += [clean(b) for b in section.get("bullets", [])]
    parts += [clean(s) for s in post.get("summary", [])]
    for qa in post.get("faq", []):
        parts += [clean(qa.get("q")), clean(qa.get("a"))]
    parts += [clean(p) for p in post.get("outro", [])]
    return "\n".join(p for p in parts if p)


def count(text, phrase):
    """How often a phrase appears, with or without its spaces ("강아지 사료" also finds "강아지사료")."""
    phrase = keywords.squash(phrase)
    return keywords.squash(text).count(phrase) if phrase else 0


def chars(text, spaces=False):
    return len(text) if spaces else len(re.sub(r"\s", "", text))


def keyword_range(n_chars):
    """How many times the main keyword should appear for a body of n_chars (no spaces)."""
    return max(3, n_chars // 700), max(7, n_chars // 300)


def analyze(post, keyword, must=(), length="auto", n_images=None):
    """-> {"score": 0-100, "checks": [...], "issues": [...], "stats": {...}}"""
    title = clean(post.get("title"))
    body = body_text(post)
    n_chars, n_spaces = chars(body), chars(body, spaces=True)
    paras = paragraphs(post)
    heads = headings(post)
    intro = " ".join(clean(p) for p in post.get("intro", []))[:200]
    kw_count = count(body, keyword)
    lo, hi = keyword_range(n_chars)
    min_chars = MIN_CHARS.get(length, MIN_CHARS["auto"])
    title_pos = keywords.squash(title).find(keywords.squash(keyword))
    missing = [m for m in must if count(title + "\n" + body, m) == 0]
    covered = 1 - len(missing) / len(must) if must else 1.0
    heads_with_kw = sum(1 for h in heads if count(h, keyword) or any(count(h, m) for m in must))
    banned = sorted({m.group(0) for r in BANNED_RE for m in r.finditer(title + "\n" + body)})
    long_paras = [p for p in paras if len(p) > 230]
    sentences = [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n", body) if len(s.strip()) > 15]
    repeated = len(sentences) - len(set(sentences))
    tags = [t for t in post.get("tags", []) if t]
    tag_ok = 8 <= len(tags) <= 15 and any(keywords.squash(keyword) == keywords.squash(t) for t in tags)

    checks = []

    def check(ok, weight, name, detail, fix):
        checks.append({"ok": bool(ok), "weight": weight, "name": name, "detail": detail, "fix": fix})

    check(0 <= title_pos <= 12, 15, "제목 앞쪽에 메인 키워드",
          f"'{title}'", f"제목을 메인 키워드 '{keyword}'로 시작하게 바꾸세요.")
    check(22 <= len(title) <= 42, 5, "제목 길이 22~42자", f"{len(title)}자",
          f"제목을 25~40자로 맞추세요 (지금 {len(title)}자).")
    check(n_chars >= min_chars, 15, f"본문 분량 (공백 제외 {min_chars:,}자 이상)",
          f"공백 제외 {n_chars:,}자 / 포함 {n_spaces:,}자",
          f"본문이 짧습니다 (공백 제외 {n_chars}자). 각 소제목에 구체적인 정보 문단을 더해 {min_chars + 300}자 이상으로 늘리세요.")
    check(lo <= kw_count <= hi, 15, f"메인 키워드 반복 {lo}~{hi}회", f"{kw_count}회",
          (f"메인 키워드 '{keyword}'를 본문에 {lo}~{hi}회가 되도록 자연스럽게 더 넣으세요 (지금 {kw_count}회)."
           if kw_count < lo else
           f"메인 키워드 '{keyword}'가 너무 많습니다 ({kw_count}회). {hi}회 이하로 줄이고 대명사나 연관어로 바꾸세요."))
    check(count(intro, keyword) > 0, 10, "도입부 첫 문단에 키워드", intro[:60] + "…",
          f"도입부 첫 문단(앞 200자 안)에 '{keyword}'와 핵심 답을 넣으세요.")
    check(4 <= len(heads) <= 7 and heads_with_kw >= 2, 10, "소제목 4~7개, 키워드·연관어 포함 2개 이상",
          f"소제목 {len(heads)}개, 키워드 포함 {heads_with_kw}개",
          "소제목을 4~6개로 하고, 그 중 2개 이상에 메인 키워드나 연관검색어를 넣으세요.")
    check(covered >= 0.8, 15, "연관검색어 포함 (80% 이상)",
          f"{len(must) - len(missing)}/{len(must)}" + (f" — 빠짐: {', '.join(missing)}" if missing else ""),
          f"다음 연관검색어를 원래 형태 그대로 본문이나 소제목에 넣으세요: {', '.join(missing)}")
    check(not banned, 5, "금지 표현 없음", ", ".join(banned) or "없음",
          f"다음 표현을 지우고 구체적인 문장으로 바꾸세요: {', '.join(banned)}")
    check(len(long_paras) <= 1 and repeated == 0, 5, "짧은 문단·반복 문장 없음",
          f"긴 문단 {len(long_paras)}개, 반복 문장 {repeated}개",
          "230자가 넘는 문단은 2~3문장씩 나누고, 같은 문장을 반복하지 마세요.")
    check(tag_ok, 5, "태그 8~15개 (메인 키워드 포함)", f"{len(tags)}개",
          f"태그를 10개로 맞추고 '{keywords.squash(keyword)}'를 넣으세요.")
    if n_images is not None:
        checks.append({"ok": 4 <= n_images <= 6, "weight": 0, "name": "이미지 4~6장", "detail": f"{n_images}장",
                       "fix": ""})

    total = sum(c["weight"] for c in checks)
    score = round(100 * sum(c["weight"] for c in checks if c["ok"]) / total) if total else 0
    return {
        "score": score,
        "checks": checks,
        "issues": [c["fix"] for c in checks if not c["ok"] and c["fix"]],
        "stats": {"chars": n_chars, "chars_with_spaces": n_spaces, "keyword_count": kw_count,
                  "headings": len(heads), "missing": missing},
    }


def shingles(text, n=5):
    s = keywords.squash(text)
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def similarity(a, b):
    """0..1 overlap of two texts (Jaccard of 5-letter pieces); above ~0.3 Naver may treat them as copies."""
    sa, sb = shingles(a), shingles(b)
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def report(result):
    """Readable checklist for the log and the preview."""
    lines = [f"SEO 점수 {result['score']}/100"]
    for c in result["checks"]:
        lines.append(f"  {'✅' if c['ok'] else '⚠️'} {c['name']}: {c['detail']}")
    return "\n".join(lines)
