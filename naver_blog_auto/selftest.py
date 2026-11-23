"""Self-test used by the Windows build (and by developers): everything except the real Naver/Google calls.

It draws every image style, runs the SEO gate on a sample post, builds the editor blocks and preview, checks
the search-result parsers, and drives a stand-in SmartEditor (tests/mock_editor.html) in the real browser:
title, text, 4+ photos in the right order, tags and the publish button.
"""
import random
import sys
import tempfile
import traceback
from pathlib import Path

SAMPLE = {
    "title": "청년도약계좌 조건 2026 신청 방법과 금리 한 번에 정리",
    "intro": ["**청년도약계좌 조건**은 나이 19~34세, 개인소득과 가구소득 기준을 함께 봐요. 청년도약계좌 신청은 "
              "은행 앱에서 매달 열리는 신청 기간에 할 수 있어요.",
              "아래에서 조건, 신청 방법, 금리, 중도해지까지 순서대로 정리했어요."],
    "sections": [
        {"heading": "청년도약계좌 조건은?", "paragraphs": ["나이와 소득 기준을 모두 맞춰야 해요. 병역 기간은 나이에서 빼 줘요.",
                                                    "청년도약계좌 조건 중 소득은 직전 과세기간 기준이에요."],
         "bullets": ["나이 19~34세", "개인소득 기준 충족", "가구소득 중위 250% 이하"],
         "image": {"query_en": "young korean saving money", "points": ["나이 19~34세", "소득 기준 확인"], "caption": "청년도약계좌 조건 요약"}},
        {"heading": "청년도약계좌 신청 방법", "paragraphs": ["은행 앱에서 가입 신청 후 심사를 기다리면 돼요.", "심사는 보통 2~3주 걸려요."],
         "bullets": [], "image": {"query_en": "bank app smartphone", "points": ["앱에서 신청", "심사 2~3주"], "caption": ""}},
        {"heading": "청년도약계좌 금리와 정부기여금", "paragraphs": ["기본금리에 우대금리가 더해져요.", "정부기여금은 소득 구간별로 달라요."],
         "bullets": [], "image": {"query_en": "interest rate chart", "points": [], "caption": ""}},
        {"heading": "청년도약계좌 중도해지 시 주의할 점", "paragraphs": ["특별중도해지 사유에 해당하면 혜택이 유지돼요."],
         "bullets": [], "image": {"query_en": "warning sign", "points": ["특별중도해지 확인"], "caption": ""}},
    ],
    "summary": ["나이 19~34세", "은행 앱에서 신청", "심사 2~3주", "중도해지 사유 확인"],
    "outro": ["청년도약계좌 조건을 먼저 확인하고 신청 기간에 맞춰 준비하세요."],
    "tags": ["청년도약계좌", "청년도약계좌조건", "청년도약계좌신청", "청년도약계좌금리", "청년적금", "정부지원금", "청년혜택",
             "적금추천", "재테크", "사회초년생"],
    "thumbnail_title": "청년도약계좌 조건/한 번에 정리",
}


def browser_test(blocks, tmp):
    """Drive the stand-in editor with the same code that drives Naver's editor."""
    import config
    import naver

    mock = config.BASE_DIR / "tests" / "mock_editor.html"
    profile_aid = "selftest"
    with naver.Session(profile_aid, headless=True) as s:
        s.page.goto(mock.resolve().as_uri())
        editor = naver.Editor(s.page)
        editor.wait_ready(timeout=20)
        methods, n_images = naver.fill(editor, SAMPLE["title"], blocks)
        order = s.page.evaluate("""() => [...document.querySelectorAll('.se-content > .se-component')]
            .map(c => c.classList.contains('se-image') ? 'IMG' : c.innerText.trim().replace(/\\s+/g, ' '))
            .filter(Boolean)""")
        title = s.page.inner_text(".se-documentTitle")
        url = editor.publish(SAMPLE["tags"])
        tags = s.page.evaluate("() => [...document.querySelectorAll('.tag')].map(t => t.textContent)")
    assert SAMPLE["title"][:10] in title, f"title missing: {title!r}"
    expected_images = sum(1 for b in blocks if b["type"] == "image")
    assert n_images == expected_images, f"images {n_images}/{expected_images}"
    assert order[0] == "IMG", f"the title card should come first: {order[:3]}"
    body = " ".join(order)
    for sec in SAMPLE["sections"]:
        assert sec["heading"][:8] in body, f"heading missing: {sec['heading']}"
    assert naver.log_no(url) == "223456789012", url
    assert len(tags) == 10, tags
    return f"browser ok ({', '.join(sorted(methods))}; {n_images} images in order)"


def run(report=None, browser=True):
    lines = []
    try:
        import config
        import images
        import keywords
        import render
        import secure_store
        import seo
        import timeslots

        tmp = Path(tempfile.mkdtemp())
        rnd = random.Random(1)
        for style in images.STYLES:
            images.title_card(SAMPLE["thumbnail_title"], "청년도약계좌", style, rnd, tmp / f"t-{style}.png", "내 블로그")
            images.section_card(1, SAMPLE["sections"][0]["heading"], ["나이 19~34세", "소득 기준"], style, rnd,
                                tmp / f"s-{style}.png")
            images.summary_card(SAMPLE["summary"], "청년도약계좌", style, rnd, tmp / f"m-{style}.png")
        lines.append(f"images ok ({len(list(tmp.glob('*.png')))} cards)")

        account = dict(config.ACCOUNT_DEFAULTS, IMAGE_SOURCE="card", IMAGE_COUNT="6", IMAGE_STYLE="auto")
        pics = images.make(SAMPLE, "청년도약계좌 조건", account, tmp, seed="selftest")
        assert len(pics) == 6, len(pics)
        result = seo.analyze(SAMPLE, "청년도약계좌 조건", ["청년도약계좌 신청", "청년도약계좌 금리"], "short", len(pics))
        assert 0 <= result["score"] <= 100 and result["checks"], result
        lines.append(f"seo ok (score {result['score']})")
        blocks = render.blocks(SAMPLE, pics)
        render.preview(SAMPLE, pics, result, "청년도약계좌 조건", ["청년도약계좌 신청"], tmp / "preview.html")
        assert sum(1 for b in blocks if b["type"] == "image") == 6
        assert seo.similarity("가나다라마바사아자차", "가나다라마바사아자차") == 1.0

        ac = keywords.parse_naver_autocomplete({"items": [[["청년도약계좌 조건"], ["청년도약계좌 금리"]]]})
        assert ac == ["청년도약계좌 조건", "청년도약계좌 금리"], ac
        rel = keywords.parse_naver_related('<div class="related_srch"><a class="keyword"><div class="tit">청년적금</div></a></div>')
        assert rel == ["청년적금"], rel
        ranks = keywords.parse_blog_results('<a href="https://blog.naver.com/abc/223000000001">'
                                            '<a href="https://blog.naver.com/me/223000000002">')
        assert ranks == [("abc", "223000000001"), ("me", "223000000002")], ranks
        merged = keywords.merge("청년도약계좌", ["청년도약계좌 조건"], ["청년적금"], ["청년도약계좌 조건", "청년도약계좌 해지"])
        assert merged["ranked"][0] == "청년도약계좌 조건", merged
        assert secure_store.decrypt(secure_store.encrypt("secret")) == "secret"
        assert timeslots.next_slot(timeslots.parse("09:30,19:30"), seed="a") is not None
        assert "Asia/Seoul" in str(timeslots.KST) or str(timeslots.KST) == "KST"
        lines.append("parsers ok")

        if browser:
            lines.append(browser_test(blocks, tmp))
        text = "OK\n" + "\n".join(lines)
        code = 0
    except Exception:
        text = "FAIL\n" + "\n".join(lines) + "\n" + traceback.format_exc()
        code = 1
    if report:
        Path(report).write_text(text, encoding="utf-8")
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else None, browser="--no-browser" not in sys.argv))
