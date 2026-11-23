"""Posting to Naver Blog through a real browser (Microsoft Edge or Chrome, already on the PC).

Each account has its own browser profile folder. You log in to Naver once in that browser (with
'로그인 상태 유지' checked); the login stays in the profile, and from then on the app opens the same profile,
fills in Naver's SmartEditor (title, text, images, tags) and publishes, with no password stored in the app.

Naver has no public API for writing blog posts, so this drives the editor like a person would. Every step is
checked (did the text/images really appear?) and falls back to another way of doing it when needed.
"""
import os
import re
import time

import config

LOGIN_URL = "https://nid.naver.com/nidlogin.login?mode=form&url=https%3A%2F%2Fblog.naver.com%2FMyBlog.naver"
MY_BLOG = "https://blog.naver.com/MyBlog.naver"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0")

TITLE = ".se-documentTitle .se-text-paragraph, .se-title-text .se-text-paragraph, .se-title-text"
BODY_PARAGRAPH = ".se-component.se-text .se-text-paragraph"
IMAGE_BUTTON = "button.se-image-toolbar-button, button[data-name='image'], button[data-log='dot.img']"
POPUPS = (".se-popup-button-cancel", ".se-help-panel-close-button", "button.se-popup-close-button")
PUBLISH = "button[class*='publish_btn']"
CONFIRM = "button[class*='confirm_btn'], button[data-testid='seOnePublishBtn']"
TAG_INPUT = "#tag-input, input[class*='tag_input'], input[placeholder*='태그'], div[class*='tag_textarea']"
SAVE = "button[class*='save_btn']"
RESERVED = {"myblog.naver", "postlist.naver", "postview.naver", "prologue", "postwrite",
            "goblogwrite.naver", "blogpost.naver"}


class NeedLogin(Exception):
    pass


class EditorError(Exception):
    pass


def _browser_kwargs(aid, headless):
    common = config.load_common()
    profile = config.profile_dir(aid)
    profile.mkdir(parents=True, exist_ok=True)
    kwargs = {
        "user_data_dir": str(profile), "headless": headless, "locale": "ko-KR", "timezone_id": "Asia/Seoul",
        "args": ["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check",
                 "--window-size=1320,960"],
        "ignore_default_args": ["--enable-automation"],
        "viewport": {"width": 1280, "height": 900} if headless else None,
    }
    if headless:
        kwargs["user_agent"] = UA
    exe = os.environ.get("NAVER_BROWSER_PATH")
    if exe:
        kwargs["executable_path"] = exe
    else:
        kwargs["channel"] = common.get("BROWSER") or "msedge"
    return kwargs


class Session:
    """A browser on the account's own profile. Use as: with Session("a") as s: ..."""

    def __init__(self, aid, headless=None):
        self.aid = aid
        if headless is None:
            headless = config.load_common().get("SHOW_BROWSER", "1") != "1"
        self.headless = headless
        self.pw = self.ctx = self.page = None

    def __enter__(self):
        from playwright.sync_api import Error, sync_playwright

        self.pw = sync_playwright().start()
        kwargs = _browser_kwargs(self.aid, self.headless)
        tried = []
        for channel in ([kwargs.get("channel")] + [c for c in ("msedge", "chrome") if c != kwargs.get("channel")]
                        if "channel" in kwargs else [None]):
            if channel:
                kwargs["channel"] = channel
            try:
                self.ctx = self.pw.chromium.launch_persistent_context(**kwargs)
                break
            except Error as e:
                tried.append(f"{channel}: {str(e).splitlines()[0][:160]}")
                if "user data directory is already in use" in str(e).lower() or "processsingleton" in str(e).lower():
                    self.pw.stop()
                    raise EditorError("이 계정의 브라우저가 이미 열려 있어요. 열린 창을 닫고 다시 해 주세요.")
        if not self.ctx:
            self.pw.stop()
            raise EditorError("브라우저(Edge/Chrome)를 열지 못했어요: " + " / ".join(tried))
        try:
            self.ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin="https://blog.naver.com")
        except Error:
            pass
        self.ctx.set_default_timeout(20000)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self

    def __exit__(self, *exc):
        try:
            if self.ctx:
                self.ctx.close()
        except Exception:
            pass
        try:
            if self.pw:
                self.pw.stop()
        except Exception:
            pass

    def has_login_cookie(self):
        try:
            return any(c["name"] == "NID_AUT" for c in self.ctx.cookies(["https://www.naver.com"]))
        except Exception:
            return False

    def blog_id(self):
        """The logged-in user's blog id (blog.naver.com/<id>); NeedLogin if not logged in."""
        self.page.goto(MY_BLOG, wait_until="domcontentloaded", timeout=45000)
        for _ in range(20):
            url = self.page.url
            if "nid.naver.com" in url:
                raise NeedLogin("네이버 로그인이 필요해요")
            match = re.search(r"blog\.naver\.com/([A-Za-z0-9_-]{3,})(?:[/?#]|$)", url)
            if match and match.group(1).lower() not in RESERVED:
                return match.group(1)
            match = re.search(r"blogId=([A-Za-z0-9_-]{3,})", url)
            if match:
                return match.group(1)
            self.page.wait_for_timeout(500)
        try:
            match = re.search(r"""blogId\s*[=:]\s*['"]([A-Za-z0-9_-]{3,})['"]""", self.page.content())
        except Exception:
            match = None
        if match:
            return match.group(1)
        if not self.has_login_cookie():
            raise NeedLogin("네이버 로그인이 필요해요")
        raise EditorError(f"블로그 주소를 찾지 못했어요 ({self.page.url})")


# ---------------------------------------------------------------- login
def login(aid, timeout=900, cancel=None):
    """Open the account's browser on Naver's login page and wait until the user has logged in.
    Returns the blog id, or None if the window was closed / time ran out."""
    from playwright.sync_api import Error

    print("🔑 브라우저에서 네이버에 로그인하세요. '로그인 상태 유지'를 꼭 체크하세요. 로그인하면 창이 저절로 닫힙니다.")
    try:
        with Session(aid, headless=False) as s:
            s.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
            deadline = time.time() + timeout
            while time.time() < deadline and not (cancel and cancel.is_set()):
                try:
                    if s.page.is_closed():
                        break
                    if s.has_login_cookie() and "nid.naver.com" not in s.page.url:
                        s.page.wait_for_timeout(1500)
                        blog = s.blog_id()
                        print(f"✔ 로그인 완료: blog.naver.com/{blog}")
                        return blog
                    s.page.wait_for_timeout(1000)
                except NeedLogin:
                    s.page.wait_for_timeout(1000)
                except Error:
                    break  # the user closed the browser
    except Error:
        pass
    # the window was closed: check the saved profile once more
    try:
        return check(aid)
    except (NeedLogin, EditorError):
        return None


def check(aid):
    """Is this account still logged in? -> blog id (NeedLogin if not)."""
    with Session(aid, headless=True) as s:
        return s.blog_id()


# ---------------------------------------------------------------- the editor
class Editor:
    def __init__(self, page):
        self.page = page
        self.frame = None

    def wait_ready(self, timeout=60):
        """Find the SmartEditor (top page or an inner frame)."""
        end = time.time() + timeout
        while time.time() < end:
            if "nid.naver.com" in self.page.url:
                raise NeedLogin("네이버 로그인이 풀렸어요")
            for frame in self.page.frames:
                try:
                    if frame.query_selector(".se-documentTitle, .se-title-text"):
                        self.frame = frame
                        self.page.wait_for_timeout(1500)
                        return frame
                except Exception:
                    continue
            self.page.wait_for_timeout(500)
        raise EditorError("글쓰기 화면이 열리지 않았어요")

    def click_if_visible(self, selector):
        loc = self.frame.locator(selector)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=3000)
                self.page.wait_for_timeout(500)
                return True
        except Exception:
            pass
        return False

    def dismiss_popups(self):
        for _ in range(2):
            for sel in POPUPS:  # '작성 중인 글이 있습니다' -> 취소 (start fresh), help panel -> close
                self.click_if_visible(sel)

    def text_of(self, selector):
        try:
            return self.frame.locator(selector).first.inner_text(timeout=3000)
        except Exception:
            return ""

    def body_chars(self):
        return self.frame.evaluate("""() => { let n = 0;
            document.querySelectorAll('.se-component').forEach(c => {
              if (c.classList.contains('se-documentTitle') || c.closest('.se-documentTitle')) return;
              if (c.querySelector('.se-component')) return;
              n += (c.innerText || '').replace(/\\s/g, '').length; });
            return n; }""")

    def image_count(self):
        return self.frame.evaluate("() => document.querySelectorAll('.se-component.se-image').length")

    # ----- title
    def set_title(self, title):
        squash = lambda s: re.sub(r"\s", "", s)
        self.frame.locator(TITLE).first.click()
        self.page.keyboard.insert_text(title)
        self.page.wait_for_timeout(400)
        now = squash(self.text_of(".se-documentTitle, .se-title-text"))
        if squash(title)[:12] in now:
            return
        if now:  # something odd got in: clear the title and type it
            self.page.keyboard.press("Control+A")
            self.page.keyboard.press("Backspace")
        self.page.keyboard.type(title, delay=25)
        if squash(title)[:12] not in squash(self.text_of(".se-documentTitle, .se-title-text")):
            raise EditorError("제목을 넣지 못했어요")

    def start_body(self):
        body = self.frame.locator(BODY_PARAGRAPH)
        if body.count():
            body.first.click()
        else:
            self.page.keyboard.press("Enter")  # from the title down into the body
        self.page.wait_for_timeout(300)

    # ----- text
    def _paste_clipboard(self, html, text):
        self.page.bring_to_front()
        self.frame.evaluate("""async ([h, t]) => { await navigator.clipboard.write([new ClipboardItem({
            'text/html': new Blob([h], {type: 'text/html'}), 'text/plain': new Blob([t], {type: 'text/plain'})})]); }""",
                            [html, text])
        self.page.keyboard.press("Control+V")

    def _paste_event(self, html, text):
        handled = self.frame.evaluate("""([h, t]) => {
            const sel = window.getSelection(); const node = sel && sel.anchorNode;
            const target = node ? (node.nodeType === 1 ? node : node.parentElement) : document.activeElement;
            const dt = new DataTransfer(); dt.setData('text/html', h); dt.setData('text/plain', t);
            const ev = new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true});
            target.dispatchEvent(ev); return ev.defaultPrevented; }""", [html, text])
        if not handled:
            raise EditorError("paste event not handled")

    def _type_lines(self, html, text):
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line.strip():
                self.page.keyboard.insert_text(line)
            if i < len(lines) - 1:
                self.page.keyboard.press("Enter")
        self.page.keyboard.press("Enter")

    def _grew(self, before, expected, wait=4.0):
        end = time.time() + wait
        while True:
            grown = self.body_chars() - before
            if grown >= expected * 0.5 or time.time() > end:
                return grown
            self.page.wait_for_timeout(250)

    def add_text(self, html, text):
        expected = max(1, len(re.sub(r"\s", "", text)))
        for name, method in (("clipboard", self._paste_clipboard), ("paste-event", self._paste_event),
                             ("typing", self._type_lines)):
            before = self.body_chars()
            try:
                method(html, text)
            except Exception:
                continue
            grown = self._grew(before, expected)
            if grown > 0:
                if grown < expected * 0.5:
                    print(f"   ⚠ 본문 일부만 들어갔을 수 있어요 ({grown}/{expected}자)")
                return name
        raise EditorError("본문을 넣지 못했어요")

    # ----- images
    CARET_AFTER_IMAGE = """() => {
        const sel = window.getSelection(); if (!sel || !sel.anchorNode) return false;
        const el = sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement;
        const comp = el && el.closest('.se-component');
        if (!comp || !comp.classList.contains('se-text')) return false;
        const imgs = document.querySelectorAll('.se-component.se-image');
        if (!imgs.length) return true;
        return !!(imgs[imgs.length - 1].compareDocumentPosition(comp) & Node.DOCUMENT_POSITION_FOLLOWING); }"""

    MARK_AFTER_IMAGE = """() => {
        document.querySelectorAll('[data-nba-next]').forEach(e => e.removeAttribute('data-nba-next'));
        const imgs = document.querySelectorAll('.se-component.se-image'); const last = imgs[imgs.length - 1];
        let n = last && last.nextElementSibling;
        while (n && !(n.classList && n.classList.contains('se-component'))) n = n.nextElementSibling;
        const p = n && n.classList.contains('se-text') && n.querySelector('.se-text-paragraph');
        if (p) { p.setAttribute('data-nba-next', '1'); return true; } return false; }"""

    def add_image(self, path):
        from playwright.sync_api import TimeoutError as PWTimeout

        before = self.image_count()
        button = self.frame.locator(IMAGE_BUTTON).first
        try:
            with self.page.expect_file_chooser(timeout=10000) as chooser:
                button.click()
            chooser.value.set_files(str(path))
        except PWTimeout:
            inputs = self.frame.locator("input[type=file]")
            if not inputs.count():
                raise EditorError("사진 올리기 버튼을 찾지 못했어요")
            inputs.first.set_input_files(str(path))
        end = time.time() + 45
        while self.image_count() <= before:
            if time.time() > end:
                raise EditorError("사진이 올라가지 않았어요")
            self.page.wait_for_timeout(500)
        self.page.wait_for_timeout(1200)
        self.caret_below_image()

    def caret_below_image(self):
        """Put the cursor in a text line below the image just added, so the next text goes after it."""
        if self.frame.evaluate(self.CARET_AFTER_IMAGE):
            return
        if self.frame.evaluate(self.MARK_AFTER_IMAGE):
            self.frame.locator("[data-nba-next]").first.click()
            self.page.keyboard.press("End")
            if self.frame.evaluate(self.CARET_AFTER_IMAGE):
                return
        self.page.keyboard.press("ArrowRight")
        self.page.keyboard.press("Enter")
        self.page.wait_for_timeout(300)
        if not self.frame.evaluate(self.CARET_AFTER_IMAGE):
            print("   ⚠ 사진 다음 줄로 커서를 옮기지 못했어요 (글 순서를 확인해 주세요)")

    # ----- finishing
    def publish(self, tags):
        """Click 발행, add tags, confirm. Returns the new post's URL."""
        self.dismiss_popups()
        button = self.frame.locator(PUBLISH)
        if not button.count():
            button = self.frame.get_by_role("button", name="발행", exact=True)
        button.first.click()
        confirm = self.frame.locator(CONFIRM)
        try:
            confirm.first.wait_for(state="visible", timeout=10000)
        except Exception:
            confirm = self.frame.locator("[class*='layer_publish'] button, [class*='publish_layer'] button").filter(
                has_text="발행")
        tag_box = self.frame.locator(TAG_INPUT)
        if tags and tag_box.count():
            try:
                tag_box.first.click(timeout=3000)
                for tag in tags[:10]:
                    self.page.keyboard.insert_text(tag)
                    self.page.keyboard.press("Enter")
                    self.page.wait_for_timeout(250)
            except Exception as e:
                print(f"   ⚠ 태그를 넣지 못했어요 ({str(e).splitlines()[0][:80]})")
        start_url = self.page.url
        confirm.last.click()
        end = time.time() + 60
        while time.time() < end:
            url = self.page.url
            if url != start_url and "postwrite" not in url.lower() and "redirect=write" not in url.lower():
                return url
            self.page.wait_for_timeout(500)
        raise EditorError("발행 후 글 주소로 넘어가지 않았어요 (발행됐는지 블로그에서 확인해 주세요)")

    def save_draft(self):
        button = self.frame.locator(SAVE)
        if not button.count():
            button = self.frame.get_by_role("button", name="저장", exact=True)
        button.first.click()
        self.page.wait_for_timeout(3000)


def log_no(url):
    match = re.search(r"logNo=(\d+)", url or "") or re.search(r"/(\d{9,})", url or "")
    return match.group(1) if match else ""


def fill(editor, title, blocks):
    """Title, then the text and images in order. Returns (text_methods_used, images_added)."""
    editor.dismiss_popups()
    editor.set_title(title)
    editor.start_body()
    methods, n_images = set(), 0
    for i, block in enumerate(blocks, 1):
        if block["type"] == "image":
            try:
                editor.add_image(block["path"])
                n_images += 1
                print(f"   🖼 사진 {n_images}장 올림")
            except Exception as e:
                print(f"   ⚠ 사진을 못 올렸어요: {str(e).splitlines()[0][:100]}")
        else:
            methods.add(editor.add_text(block["html"], block["text"]))
            if block.get("alone"):  # a heading: the following text starts on its own new line
                editor.page.keyboard.press("End")
                editor.page.keyboard.press("Enter")
    return methods, n_images


def post(aid, title, blocks, tags, publish=True, write_url=None, headless=None, shot_dir=None):
    """Write one post with the account's saved login. Returns {"url", "log_no", "draft", "blog_id"}."""
    with Session(aid, headless=headless) as s:
        try:
            blog = "test"
            if not write_url:
                blog = s.blog_id()  # also confirms the login
                if blog != config.load_account(aid).get("BLOG_ID"):
                    config.save_account(aid, {"BLOG_ID": blog})
            url = write_url or f"https://blog.naver.com/{blog}/postwrite"
            print(f"🌐 글쓰기 화면 여는 중: {url}")
            s.page.goto(url, wait_until="domcontentloaded", timeout=60000)
            editor = Editor(s.page)
            editor.wait_ready()
            methods, n_images = fill(editor, title, blocks)
            print(f"   본문 입력 방식: {', '.join(sorted(methods)) or '-'} · 사진 {n_images}장")
            if publish:
                print("📤 발행 중...")
                url = editor.publish(tags)
                return {"url": url, "log_no": log_no(url), "draft": False, "blog_id": blog, "images": n_images}
            editor.save_draft()
            print("💾 임시저장했어요. 네이버 블로그 글쓰기 → 임시저장 글에서 확인 후 발행하세요.")
            return {"url": "", "log_no": "", "draft": True, "blog_id": blog, "images": n_images}
        except Exception:
            if shot_dir:
                try:
                    shot_dir.mkdir(parents=True, exist_ok=True)
                    s.page.screenshot(path=str(shot_dir / "error.png"), full_page=False)
                    print(f"   (오류 화면을 저장했어요: {shot_dir / 'error.png'})")
                except Exception:
                    pass
            raise

