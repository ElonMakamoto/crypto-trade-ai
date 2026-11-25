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
        url = editor.publish(SAMPLE["tags"], lambda names: "재테크 정보" if "재테크 정보" in names else None)
        category = s.page.inner_text(".selectbox_button__mock")
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
    assert category == "재테크 정보", category
    return f"browser ok ({', '.join(sorted(methods))}; {n_images} images in order)"


STORY_RAW = {
    "keyword": "연애전쟁", "title": "이효리 \"제발 헤어져라\" 연애전쟁, 19커플 중 5커플 결국 이별한 이유",
    "opening_image": {"who": "이효리", "query": "연애전쟁"},
    "opening": [["\"제발 헤어져라\"", "<b>이효리</b>의 한마디였습니다."], ["그 커플은 어떤 선택을 했을까요."]],
    "sections": [{"heading": f"소제목 {i}", "images": [{"who": "서장훈", "query": "연애전쟁"}],
                  "chunks": [["짧은 줄 하나", "짧은 줄 둘"], ["다만 시즌2는 아직 공식 발표되지 않았습니다."]]}
                 for i in range(1, 5)],
    "question": "어떤 커플이 가장 기억에 남나요?", "tags": ["연애전쟁", "이효리", "서장훈", "JTBC", "연애예능"],
}


def story_browser_test(tmp):
    """The 연애 story layout in the stand-in editor: quotation subtitles, captions, footer, no related-post link."""
    import config
    import naver
    import render
    import story

    post = story.normalize(STORY_RAW, "연애전쟁")
    pics = []
    for i, place in enumerate(["top"] + [("section", k) for k in range(4)]):
        path = tmp / f"story{i}.jpg"
        __import__("PIL.Image", fromlist=["Image"]).new("RGB", (800, 500), (180, 190, 200)).save(path)
        pics.append({"path": path, "caption": "이효리 / 출처: 톱스타뉴스", "place": place})
    blocks = render.story_blocks(post, pics, {"url": "https://blog.naver.com/me/223000000001", "title": "지난 글"},
                                 ["톱스타뉴스"])
    with naver.Session("selftest", headless=True) as s:
        s.page.goto((config.BASE_DIR / "tests" / "mock_editor.html").resolve().as_uri())
        editor = naver.Editor(s.page)
        editor.wait_ready(timeout=20)
        methods, n_images = naver.fill(editor, post["title"], blocks)
        found = s.page.evaluate("""() => ({
            quotes: [...document.querySelectorAll('.se-quotation')].map(q => q.innerText.trim()),
            cards: document.querySelectorAll('.se-oglink').length,
            text: document.querySelector('.se-content').innerText})""")
        found_center = s.page.evaluate("""() => [...document.querySelectorAll('.se-content .se-text .se-text-paragraph')]
            .filter(p => p.innerText.trim()).every(p => getComputedStyle(p).textAlign === 'center')""")
    assert len(found["quotes"]) == 4 and "소제목 1" in found["quotes"][0], found["quotes"]
    assert found["cards"] == 0 and "함께보면" not in found["text"], "no related-post link at the end"
    assert "<b>" not in found["text"] and "</b>" not in found["text"], "no raw HTML tags in the post"
    for must in ("이효리 / 출처: 톱스타뉴스", "무단 전재, 재배포 및 AI학습 이용 금지"):
        assert must in found["text"], must
    assert n_images == 5
    centered = found_center
    assert centered, "body text should be centered"
    result = story.check(post, "연애전쟁")
    assert result["checks"], result
    return f"story ok ({', '.join(sorted(methods))}; 4 quote subtitles, no link card, {n_images} images)"


def image_fallback_test(tmp):
    """Photos still go up when the photo button and file input don't work (paste, then drop)."""
    import config
    import naver

    photo = tmp / "fallback.jpg"
    __import__("PIL.Image", fromlist=["Image"]).new("RGB", (800, 500), (120, 140, 160)).save(photo)
    results = []
    with naver.Session("selftest", headless=True) as s:
        for broken in (["_upload_chooser"], ["_upload_chooser", "_upload_input"],
                       ["_upload_chooser", "_upload_input", "paste"]):
            s.page.goto((config.BASE_DIR / "tests" / "mock_editor.html").resolve().as_uri())
            editor = naver.Editor(s.page)
            editor.wait_ready(timeout=20)
            editor.dismiss_popups()
            editor.start_body()

            def fail(*a, **k):
                raise naver.EditorError("disabled for the test")

            for name in broken:
                if name == "paste":
                    real = editor._file_js
                    editor._file_js = lambda p, ev, real=real: fail() if ev == "paste" else real(p, ev)
                else:
                    setattr(editor, name, fail)
            results.append(editor.add_image(photo))
            assert editor.image_count() == 1
    assert results == ["파일 입력칸", "붙여넣기", "끌어놓기"], results
    return "image fallbacks ok (" + ", ".join(results) + ")"


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
        assert len(pics) == 5 and pics[0]["place"] == "top" and pics[-1]["place"] == "summary", pics  # cards only: no end photo
        result = seo.analyze(SAMPLE, "청년도약계좌 조건", ["청년도약계좌 신청", "청년도약계좌 금리"], "short", len(pics))
        assert 0 <= result["score"] <= 100 and result["checks"], result
        lines.append(f"seo ok (score {result['score']})")
        blocks = render.blocks(SAMPLE, pics)
        render.preview(SAMPLE, pics, result, "청년도약계좌 조건", ["청년도약계좌 신청"], tmp / "preview.html")
        assert sum(1 for b in blocks if b["type"] == "image") == 5
        assert images.middle_sections(5, 1) == [2] and images.middle_sections(4, 3) == [1, 2, 3]
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
        links = keywords.NAVER_ARTICLE.findall('<a href="https://n.news.naver.com/mnews/article/123/0000001">'
                                               '<a href="https://m.entertain.naver.com/article/111/0000002">')
        assert links == ["https://n.news.naver.com/mnews/article/123/0000001",
                         "https://m.entertain.naver.com/article/111/0000002"], links
        page = ('<meta content="https://img/a.jpg" property="og:image"><meta property="og:article:author" '
                'content="톱스타뉴스">')
        assert images._meta(page, "og:image") == "https://img/a.jpg"
        assert images._meta(page, "og:article:author") == "톱스타뉴스"
        assert seo.clean("<b>희망등록 신청서</b> 접수<br>") == "희망등록 신청서 접수"
        import gemini

        fixed = gemini._parse_json('{"t": "질병관리청 "다발-계통 위축" 등", "x": [1, 2,]}')
        assert fixed == {"t": '질병관리청 "다발-계통 위축" 등', "x": [1, 2]}, fixed
        real_json = gemini.generate_json
        gemini.generate_json = lambda *a, **k: [{"자리": 0, "번호": 0, "인물명": "질병관리청"}]  # a bare list answer
        plan = images.assign_story_photos({"keyword": "k", "opening_image": {"who": "x"}, "sections": []},
                                          [{"title": "t", "outlet": "o", "path": "p"}])
        gemini.generate_json = real_json
        assert plan["opening"] == (0, "질병관리청"), plan
        assert render.inline("<strong>꼭</strong>") == "<b>꼭</b>"
        import story as story_mod

        sb = render.story_blocks(story_mod.normalize(STORY_RAW, "x"), [], None, ["톱스타뉴스"])
        q = next(i for i, b in enumerate(sb) if b["type"] == "quote")
        assert sb[q - 1]["html"].endswith("<p><br></p><p><br></p>"), "2 empty lines before a subtitle"
        assert sb[q + 1]["html"].startswith("<p><br></p><p><br></p>"), "2 empty lines after a subtitle"
        real_get = keywords._get

        class Page:
            ok = True

            def __init__(self, text):
                self.text = text

        pages = {"bing.com": Page('<rss><item><link>http://www.bing.com/news/apiclick.aspx?ref=x&amp;url=https%3a%2f%2fwww.yna.co.kr%2fview%2fAKR1&amp;c=1</link></item></rss>'),
                 "daum.net": Page('<a href="https://v.daum.net/v/20261125123045678">x</a>'),
                 "naver.com": Page("")}
        keywords._get = lambda url, **k: next(v for key, v in pages.items() if key in url)
        try:
            links = keywords.news_article_links("질병청", 5)
        finally:
            keywords._get = real_get
        assert links == ["https://v.daum.net/v/20261125123045678", "https://www.yna.co.kr/view/AKR1"], links
        assert secure_store.decrypt(secure_store.encrypt("secret")) == "secret"
        assert timeslots.next_slot(timeslots.parse("09:30,19:30"), seed="a") is not None
        assert "Asia/Seoul" in str(timeslots.KST) or str(timeslots.KST) == "KST"
        lines.append("parsers ok")

        if browser:
            lines.append(browser_test(blocks, tmp))
            lines.append(story_browser_test(tmp))
            lines.append(image_fallback_test(tmp))
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
