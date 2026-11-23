"""Naver Blog Auto — Windows desktop app.

Two Naver accounts side by side. Log in to Naver once per account (🔑 button); after that the app writes
Korean SEO posts with Gemini (free Google AI Studio key) and publishes them at the chosen times by itself.
"""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
import webbrowser
from datetime import timedelta
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

import requests

import config
import gemini
import main as bot
import naver
import timeslots

APP_NAME = "Naver Blog Auto"
REPO = "ElonMakamoto/crypto-trade-ai"
RELEASE_TAG = "naver-blog-auto-latest"
EXE_NAME = "NaverBlogAuto.exe"
DOWNLOAD_URL = f"https://github.com/{REPO}/releases/download/{RELEASE_TAG}/{EXE_NAME}"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UPDATE_CHECK_MS = 3 * 3600 * 1000
RANK_CHECK_MS = 6 * 3600 * 1000
RETRY_MINUTES = 20

_local = threading.local()


def app_version():
    try:
        return (config.BASE_DIR / "version.txt").read_text().strip() or "dev"
    except OSError:
        return "dev"


def open_path(path):
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - opens a folder or file the app made
    elif path.startswith("http"):
        webbrowser.open(path)
    else:
        subprocess.Popen(["xdg-open", path])


class LogWriter:
    """print() from any thread goes to that account's log (or every log if no account)."""

    def __init__(self, app):
        self.app = app

    def write(self, text):
        aid = getattr(_local, "aid", None)
        targets = [self.app.panels[aid]] if aid in self.app.panels else list(self.app.panels.values())
        for panel in targets:
            panel.log_q.put(text)

    def flush(self):
        pass


def choice_box(parent, kind, var, width=26):
    labels = list(config.CHOICES[kind].values())
    box = ttk.Combobox(parent, values=labels, state="readonly", width=width)

    def to_var(*_):
        var.set(next((k for k, v in config.CHOICES[kind].items() if v == box.get()), config.AUTO))

    def to_box(*_):
        box.set(config.CHOICES[kind].get(var.get(), labels[0]))

    box.bind("<<ComboboxSelected>>", to_var)
    var.trace_add("write", to_box)
    to_box()
    return box


# ---------------------------------------------------------------- common settings
class CommonSettings:
    def __init__(self, app):
        self.app = app
        top = self.top = tk.Toplevel(app.root)
        top.title("공통 설정")
        top.transient(app.root)
        top.resizable(False, False)
        values = config.load_common()
        self.vars = {k: tk.StringVar(value=values[k]) for k in config.COMMON_DEFAULTS}
        self.show = tk.BooleanVar(value=values["SHOW_BROWSER"] == "1")
        self.startup = tk.BooleanVar(value=app.startup_enabled())
        f = ttk.Frame(top, padding=16)
        f.pack(fill="both", expand=True)
        row = 0

        def line(label, widget, extra=None):
            nonlocal row
            ttk.Label(f, text=label).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 10))
            widget.grid(row=row, column=1, sticky="we", pady=5)
            if extra:
                extra.grid(row=row, column=2, sticky="w", padx=(8, 0))
            row += 1

        line("Google API 키 (무료)", ttk.Entry(f, textvariable=self.vars["GOOGLE_API_KEY"], show="•", width=46),
             ttk.Button(f, text="무료 발급", command=lambda: webbrowser.open(gemini.KEY_URL)))
        line("Gemini 모델", ttk.Entry(f, textvariable=self.vars["GEMINI_MODEL"], width=46),
             ttk.Button(f, text="키 확인", command=self.check_key))
        line("Pixabay API 키 (선택)", ttk.Entry(f, textvariable=self.vars["PIXABAY_API_KEY"], show="•", width=46),
             ttk.Button(f, text="발급", command=lambda: webbrowser.open("https://pixabay.com/api/docs/")))
        line("Pexels API 키 (선택)", ttk.Entry(f, textvariable=self.vars["PEXELS_API_KEY"], show="•", width=46),
             ttk.Button(f, text="발급", command=lambda: webbrowser.open("https://www.pexels.com/api/")))
        browsers = {"msedge": "Microsoft Edge (Windows 기본)", "chrome": "Google Chrome"}
        self.browser_box = ttk.Combobox(f, values=list(browsers.values()), state="readonly", width=44)
        self.browser_box.set(browsers.get(values["BROWSER"], browsers["msedge"]))
        self.browsers = browsers
        line("브라우저", self.browser_box)
        ttk.Checkbutton(f, text="글 올릴 때 브라우저 창 보이기 (권장)", variable=self.show).grid(
            row=row, column=1, sticky="w", pady=4)
        row += 1
        ttk.Checkbutton(f, text="Windows 시작할 때 자동 실행 + 자동 업로드 시작", variable=self.startup).grid(
            row=row, column=1, sticky="w", pady=4)
        row += 1
        ttk.Label(f, text="무료 Google 키로 글을 씁니다. 사진은 AI 그림이 안 되는 키면 무료 사진(Pixabay/Pexels 키) 또는\n"
                          "디자인 카드로 자동으로 바뀝니다.", foreground="#666").grid(row=row, column=0, columnspan=3,
                                                                          sticky="w", pady=(10, 0))
        row += 1
        buttons = ttk.Frame(f)
        buttons.grid(row=row, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="저장", style="Accent.TButton", command=self.save).pack(side="left", padx=4)
        ttk.Button(buttons, text="닫기", command=top.destroy).pack(side="left")

    def save(self, close=True):
        values = {k: v.get() for k, v in self.vars.items()}
        values["SHOW_BROWSER"] = "1" if self.show.get() else ""
        values["BROWSER"] = next(k for k, v in self.browsers.items() if v == self.browser_box.get())
        config.save_common(values)
        gemini._models = None
        self.app.set_startup(self.startup.get())
        if close:
            self.top.destroy()

    def check_key(self):
        self.save(close=False)

        def check():
            try:
                model = gemini.check_key()
                self.app.root.after(0, lambda: (self.vars["GEMINI_MODEL"].set(model), messagebox.showinfo(
                    APP_NAME, f"Google API 키가 동작해요.\n사용 모델: {model}", parent=self.top)))
            except Exception as e:
                msg = str(e)
                self.app.root.after(0, lambda: messagebox.showerror(APP_NAME, f"키 확인 실패\n\n{msg}",
                                                                    parent=self.top))

        threading.Thread(target=check, daemon=True).start()


# ---------------------------------------------------------------- history / search ranks
class HistoryWindow:
    COLUMNS = (("time", "날짜", 120), ("keyword", "키워드", 170), ("title", "제목", 330), ("score", "SEO", 50),
               ("images", "사진", 45), ("rank", "블로그탭", 90), ("main", "통합검색", 70), ("url", "주소", 230))

    def __init__(self, panel):
        self.panel = panel
        top = self.top = tk.Toplevel(panel.app.root)
        top.title(f"{config.account_label(panel.aid)} — 올린 글과 검색 노출")
        top.geometry("1180x520")
        bar = ttk.Frame(top, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="📈 지금 순위 확인", command=self.check).pack(side="left")
        ttk.Button(bar, text="🔗 글 열기", command=self.open_post).pack(side="left", padx=6)
        ttk.Button(bar, text="👁 미리보기 열기", command=self.open_preview).pack(side="left")
        ttk.Label(bar, text="  네이버 블로그탭 순위(1페이지 안)와 통합검색 노출을 6시간마다 자동으로 확인해요.",
                  foreground="#666").pack(side="left")
        self.tree = ttk.Treeview(top, columns=[c[0] for c in self.COLUMNS], show="headings")
        for key, label, width in self.COLUMNS:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.tree.bind("<Double-1>", lambda e: self.open_post())
        self.load()

    def load(self):
        self.tree.delete(*self.tree.get_children())
        self.items = list(reversed(config.load_history(self.panel.aid)))
        for i, h in enumerate(self.items):
            rank = h.get("blog_rank")
            rank_text = "-" if rank is None else (f"{rank}위" if rank else "1페이지 밖")
            main_text = "-" if h.get("main_page") is None else ("노출" if h["main_page"] else "-")
            if h.get("draft"):
                rank_text = main_text = "임시저장"
            self.tree.insert("", "end", iid=str(i), values=(h.get("time", ""), h.get("keyword", ""), h.get("title", ""),
                                                            h.get("score", ""), h.get("images", ""), rank_text, main_text,
                                                            h.get("url", "")))

    def selected(self):
        sel = self.tree.selection()
        return self.items[int(sel[0])] if sel else None

    def open_post(self):
        item = self.selected()
        if item and item.get("url"):
            webbrowser.open(item["url"])

    def open_preview(self):
        item = self.selected()
        if item and item.get("json"):
            page = Path(item["json"]).with_name("미리보기.html")
            if page.exists():
                open_path(page)

    def check(self):
        def run():
            _local.aid = self.panel.aid
            bot.check_ranks(self.panel.aid, force=True)
            self.panel.app.root.after(0, self.load)

        threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------- one account
class AccountPanel:
    def __init__(self, app, parent, aid):
        self.app, self.aid = app, aid
        self.log_q = queue.Queue()
        self.stop_event = threading.Event()
        self.cancel_event = threading.Event()
        self.browser_lock = threading.Lock()  # one browser per account profile at a time
        self.auto_thread = None
        self.working = False
        self.next_slot = None
        self.last_job = None
        values = config.load_account(aid)
        self.vars = {k: tk.StringVar(value=values[k]) for k in config.ACCOUNT_DEFAULTS
                     if k not in ("KEYWORDS", "MEMO", "POST_TIMES")}
        self.auto_kw = tk.BooleanVar(value=values["AUTO_KEYWORDS"] == "1")

        frame = self.frame = ttk.Frame(parent, padding=10, relief="groove")
        head = ttk.Frame(frame)
        head.pack(fill="x")
        self.title_label = ttk.Label(head, text=config.account_label(aid, values), style="Account.TLabel")
        self.title_label.pack(side="left")
        ttk.Button(head, text="로그인 확인", command=self.check_login).pack(side="right")
        ttk.Button(head, text="🔑 네이버 로그인", style="Accent.TButton", command=self.login).pack(side="right", padx=6)
        self.login_label = ttk.Label(frame, text="", style="Status.TLabel")
        self.login_label.pack(fill="x", pady=(4, 6))

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(0, 4))
        self.auto_btn = ttk.Button(actions, text="▶ 자동 시작", style="Accent.TButton", command=self.toggle_auto)
        self.auto_btn.pack(side="left")
        self.post_btn = ttk.Button(actions, text="🚀 지금 올리기", command=lambda: self.run_now(False))
        self.post_btn.pack(side="left", padx=4)
        self.preview_btn = ttk.Button(actions, text="👁 미리보기 (올리지 않음)", command=lambda: self.run_now(True))
        self.preview_btn.pack(side="left")
        self.publish_last_btn = ttk.Button(actions, text="📤 미리본 글 올리기", command=self.publish_last,
                                           state="disabled")
        self.publish_last_btn.pack(side="left", padx=4)
        self.cancel_btn = ttk.Button(actions, text="⏹ 취소", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left")
        more = ttk.Frame(frame)
        more.pack(fill="x", pady=(0, 6))
        ttk.Button(more, text="📈 올린 글·검색 노출", command=lambda: HistoryWindow(self)).pack(side="left")
        ttk.Button(more, text="📂 결과 폴더", command=self.open_output).pack(side="left", padx=4)
        self.status_label = ttk.Label(more, text="", foreground="#0a7d33")
        self.status_label.pack(side="left", padx=8)

        self.tabs = ttk.Notebook(frame)
        self.tabs.pack(fill="both", expand=True)
        self._build_settings(self.tabs, values)
        self._build_keywords(self.tabs, values)
        log_tab = ttk.Frame(self.tabs, padding=4)
        self.log = scrolledtext.ScrolledText(log_tab, height=16, state="disabled", font=("Consolas", 9), wrap="word")
        self.log.pack(fill="both", expand=True)
        self.tabs.add(log_tab, text="📜 진행 기록")
        self.refresh_login()
        self.update_status()

    # ----- UI
    def _build_settings(self, tabs, values):
        tab = ttk.Frame(tabs, padding=8)
        tabs.add(tab, text="⚙ 글 설정")
        tab.columnconfigure(1, weight=1)
        tab.columnconfigure(3, weight=1)
        r = 0

        def pair(label, widget, col=0):
            ttk.Label(tab, text=label).grid(row=r, column=col, sticky="w", pady=3, padx=(0 if col == 0 else 10, 6))
            widget.grid(row=r, column=col + 1, sticky="we", pady=3)

        pair("별명", ttk.Entry(tab, textvariable=self.vars["NICKNAME"]))
        pair("블로그 주소", ttk.Entry(tab, textvariable=self.vars["BLOG_ID"], state="readonly"), 2)
        r += 1
        pair("블로그 주제", choice_box(tab, "TOPIC", self.vars["TOPIC"]))
        pair("세부 주제", ttk.Entry(tab, textvariable=self.vars["TOPIC_DETAIL"]), 2)
        r += 1
        pair("글 스타일", choice_box(tab, "STYLE", self.vars["STYLE"]))
        pair("말투", choice_box(tab, "TONE", self.vars["TONE"]), 2)
        r += 1
        pair("글 길이", choice_box(tab, "LENGTH", self.vars["LENGTH"]))
        pair("올리는 방식", choice_box(tab, "PUBLISH", self.vars["PUBLISH"]), 2)
        r += 1
        pair("사진 종류", choice_box(tab, "IMAGE_SOURCE", self.vars["IMAGE_SOURCE"]))
        pair("사진 스타일", choice_box(tab, "IMAGE_STYLE", self.vars["IMAGE_STYLE"]), 2)
        r += 1
        pair("사진 장수", choice_box(tab, "IMAGE_COUNT", self.vars["IMAGE_COUNT"]))
        pair("글쓴이 소개", ttk.Entry(tab, textvariable=self.vars["PERSONA"]), 2)
        r += 1
        ttk.Label(tab, text="업로드 시간").grid(row=r, column=0, sticky="w", pady=3)
        times = ttk.Frame(tab)
        times.grid(row=r, column=1, columnspan=3, sticky="w", pady=3)
        saved = [f"{h:02d}:{m:02d}" for h, m in timeslots.parse(values["POST_TIMES"])]
        self.time_boxes = []
        for i in range(timeslots.SLOTS):
            box = ttk.Combobox(times, values=timeslots.CHOICES, state="readonly", width=9)
            box.set(saved[i] if i < len(saved) else timeslots.OFF)
            box.pack(side="left", padx=(0, 6))
            self.time_boxes.append(box)
        ttk.Label(times, text="한국시간 · 매일 ±40분 랜덤", foreground="#666").pack(side="left")
        r += 1
        bottom = ttk.Frame(tab)
        bottom.grid(row=r, column=0, columnspan=4, sticky="we", pady=(8, 0))
        ttk.Button(bottom, text="💾 저장", style="Accent.TButton", command=self.save).pack(side="left")
        ttk.Button(bottom, text="🤖 전부 자동으로", command=self.all_auto).pack(side="left", padx=6)
        ttk.Label(bottom, text="'자동'은 AI가 키워드마다 알아서 정해요. 한 계정은 한 주제로 꾸준히 쓰는 게 검색에 유리해요.",
                  foreground="#666", wraplength=420).pack(side="left", padx=6)

    def _build_keywords(self, tabs, values):
        tab = ttk.Frame(tabs, padding=8)
        tabs.add(tab, text="🔑 키워드·메모")
        ttk.Label(tab, text="키워드 목록 — 한 줄에 하나, 위에서부터 씁니다 (이미 쓴 키워드는 건너뜀)").pack(anchor="w")
        self.kw_text = tk.Text(tab, height=7, wrap="none", font=("Malgun Gothic", 10))
        self.kw_text.insert("1.0", values["KEYWORDS"])
        self.kw_text.pack(fill="x", pady=(2, 4))
        ttk.Checkbutton(tab, text="키워드가 없으면 AI가 알아서 고르기 (네이버·구글 자동완성의 실제 검색어 중 롱테일)",
                        variable=self.auto_kw).pack(anchor="w")
        ttk.Label(tab, text="내 메모 — 실제 경험·가게 정보·내가 아는 사실 (AI는 경험담을 이 메모에서만 씁니다)").pack(
            anchor="w", pady=(8, 0))
        self.memo_text = tk.Text(tab, height=4, wrap="word", font=("Malgun Gothic", 10))
        self.memo_text.insert("1.0", values["MEMO"])
        self.memo_text.pack(fill="x", pady=(2, 4))
        ttk.Button(tab, text="💾 저장", style="Accent.TButton", command=self.save).pack(anchor="w")

    def all_auto(self):
        for kind in ("TOPIC", "STYLE", "TONE", "LENGTH", "IMAGE_STYLE", "IMAGE_SOURCE", "IMAGE_COUNT"):
            self.vars[kind].set(config.AUTO)
        self.auto_kw.set(True)
        self.save()

    def values(self):
        # the blog address is found by the app itself (login), never typed: don't overwrite it from the form
        values = {k: v.get() for k, v in self.vars.items() if k != "BLOG_ID"}
        values["KEYWORDS"] = self.kw_text.get("1.0", "end").strip()
        values["MEMO"] = self.memo_text.get("1.0", "end").strip()
        values["AUTO_KEYWORDS"] = "1" if self.auto_kw.get() else ""
        values["POST_TIMES"] = ",".join(b.get() for b in self.time_boxes if b.get() != timeslots.OFF)
        return values

    def save(self, quiet=False):
        config.save_account(self.aid, self.values())
        self.title_label.config(text=config.account_label(self.aid))
        self.update_status()
        if not quiet:
            self.log_q.put("💾 설정을 저장했어요.\n")

    def reload_fields(self):
        """Pick up values the app changed by itself (blog id, the topic the AI chose)."""
        values = config.load_account(self.aid)
        for key in ("BLOG_ID", "TOPIC_DETAIL"):
            if self.vars[key].get() != values[key]:
                self.vars[key].set(values[key])
        self.title_label.config(text=config.account_label(self.aid, values))
        self.refresh_login()

    def refresh_login(self, text=None, colour=None):
        blog = config.load_account(self.aid).get("BLOG_ID")
        if text is None:
            text, colour = ((f"🟢 로그인됨 · blog.naver.com/{blog}", "#0a7d33") if blog else
                            ("⚪ 아직 로그인 전 — 🔑 네이버 로그인을 눌러 한 번만 로그인하세요", "#666"))
        self.login_label.config(text=text, foreground=colour)

    def open_output(self):
        path = config.output_dir(self.aid)
        path.mkdir(parents=True, exist_ok=True)
        open_path(path)

    # ----- status
    def auto_on(self):
        return bool(self.auto_thread and self.auto_thread.is_alive())

    def update_status(self, text=None):
        if text is None:
            if self.working:
                return
            if self.auto_on() and self.next_slot:
                text = f"⏰ 다음 업로드: {timeslots.describe(self.next_slot)}"
            elif self.auto_on():
                text = "⏰ 업로드 시간이 없어요 (⚙ 글 설정에서 고르세요)"
            else:
                times = timeslots.parse(",".join(b.get() for b in self.time_boxes if b.get() != timeslots.OFF))
                text = f"자동 업로드 꺼짐 · 시간 {', '.join(f'{h:02d}:{m:02d}' for h, m in times) or '없음'}"
        self.status_label.config(text=text)

    def set_working(self, on, text=""):
        def apply():
            self.working = on
            state = "disabled" if on else "normal"
            for b in (self.post_btn, self.preview_btn):
                b.config(state=state)
            self.publish_last_btn.config(state="disabled" if on or not self.last_job else "normal")
            self.cancel_btn.config(state="normal" if on else "disabled")
            self.update_status(text if on else None)
            if on:
                self.tabs.select(2)

        self.app.root.after(0, apply)

    # ----- actions
    def ready(self, quiet=False):
        def warn(msg):
            if quiet:
                self.log_q.put(f"⚠ {msg}\n")
            else:
                messagebox.showwarning(APP_NAME, msg)
            return False

        if not config.load_common()["GOOGLE_API_KEY"]:
            return warn("상단 ⚙ 공통 설정에 Google API 키를 넣어 주세요 (aistudio.google.com/apikey 에서 무료 발급).")
        return True

    def login(self):
        if self.working:
            return

        def run():
            _local.aid = self.aid
            if not self.browser_lock.acquire(blocking=False):
                print("⚠ 이 계정 브라우저가 이미 사용 중이에요.\n")
                return
            try:
                self.app.root.after(0, lambda: self.refresh_login("🔑 열린 브라우저에서 로그인하세요 ('로그인 상태 유지' 체크)",
                                                                  "#c06000"))
                blog = naver.login(self.aid)
                if blog:
                    config.save_account(self.aid, {"BLOG_ID": blog})
                    print(f"✔ 로그인 저장 완료: blog.naver.com/{blog}\n")
                else:
                    print("❌ 로그인하지 않고 창이 닫혔어요.\n")
            except Exception as e:
                print(f"❌ 로그인 실패: {e}\n")
            finally:
                self.browser_lock.release()
                self.app.root.after(0, self.reload_fields)

        threading.Thread(target=run, daemon=True).start()

    def check_login(self):
        def run():
            _local.aid = self.aid
            if not self.browser_lock.acquire(blocking=False):
                return
            try:
                blog = naver.check(self.aid)
                config.save_account(self.aid, {"BLOG_ID": blog})
                print(f"✔ 로그인 유지 중: blog.naver.com/{blog}\n")
                self.app.root.after(0, self.reload_fields)
            except naver.NeedLogin:
                print("❌ 로그인이 필요해요. 🔑 네이버 로그인을 눌러 주세요.\n")
                self.app.root.after(0, lambda: self.refresh_login("🔴 로그인이 필요해요 — 🔑 네이버 로그인", "#c00000"))
            except Exception as e:
                print(f"❌ 확인 실패: {e}\n")
            finally:
                self.browser_lock.release()

        threading.Thread(target=run, daemon=True).start()

    def run_now(self, dry_run):
        if self.working or not self.ready():
            return
        self.save(quiet=True)
        threading.Thread(target=self.round, kwargs={"dry_run": dry_run}, daemon=True).start()

    def publish_last(self):
        if self.working or not self.last_job:
            return
        threading.Thread(target=self.round, kwargs={"job": self.last_job}, daemon=True).start()

    def cancel(self):
        self.cancel_event.set()
        self.log_q.put("⏹ 취소합니다 — 지금 단계가 끝나면 멈추고 올리지 않아요.\n")

    def round(self, dry_run=False, job=None):
        """Write (and post) one article. Returns True when it worked."""
        _local.aid = self.aid
        self.cancel_event.clear()
        self.set_working(True, "✍ 작업 중..." if not job else "📤 올리는 중...")
        ok = False
        try:
            with self.app.round_lock:  # one account at a time
                if not job:
                    print(f"\n===== {config.account_label(self.aid)} · {timeslots.now():%m/%d %H:%M} =====\n")
                    job = bot.make_post(self.aid)
                    self.app.root.after(0, self.reload_fields)
                    if dry_run:
                        self.last_job = job
                        open_path(job["preview"])
                        print("👁 미리보기를 브라우저로 열었어요. 마음에 들면 📤 미리본 글 올리기를 누르세요.\n")
                        return True
                if self.cancel_event.is_set():
                    print("⏹ 취소했어요 (올리지 않음).\n")
                    return False
                with self.browser_lock:
                    bot.publish_job(job)
                if job is self.last_job:
                    self.last_job = None
                ok = True
        except naver.NeedLogin:
            print("❌ 네이버 로그인이 풀렸어요. 🔑 네이버 로그인을 다시 눌러 주세요.\n")
            self.app.root.after(0, lambda: self.refresh_login("🔴 로그인이 풀렸어요 — 🔑 네이버 로그인을 다시 해 주세요",
                                                              "#c00000"))
        except Exception as e:
            print(f"❌ 실패: {e}\n")
            if not isinstance(e, (gemini.GeminiError, naver.EditorError, ValueError)):
                print(traceback.format_exc() + "\n")
        finally:
            self.set_working(False)
        return ok

    # ----- automatic posting
    def _auto_loop(self):
        _local.aid = self.aid
        retry_at = None
        while not self.stop_event.is_set():
            account = config.load_account(self.aid)
            slot = timeslots.next_slot(timeslots.parse(account["POST_TIMES"]), seed=self.aid + account["BLOG_ID"])
            if retry_at and (not slot or retry_at < slot):
                slot = retry_at
            self.next_slot = slot
            self.app.root.after(0, self.update_status)
            if not slot:
                self.stop_event.wait(60)
                continue
            while timeslots.now() < slot and not self.stop_event.is_set():
                self.stop_event.wait(min(20, max(1, (slot - timeslots.now()).total_seconds())))
            if self.stop_event.is_set():
                break
            if not self.ready(quiet=True):
                retry_at = None
                continue
            ok = self.round()
            if ok or retry_at:
                retry_at = None
            else:  # failed: try once more a little later
                retry_at = timeslots.now() + timedelta(minutes=RETRY_MINUTES)
                print(f"↻ {RETRY_MINUTES}분 뒤에 한 번 더 시도해요.\n")
        self.next_slot = None
        self.app.root.after(0, self.update_status)

    def start_auto(self, quiet=False):
        if self.auto_on() or not self.ready(quiet):
            return
        self.save(quiet=True)
        self.stop_event.clear()
        self.auto_thread = threading.Thread(target=self._auto_loop, daemon=True)
        self.auto_thread.start()
        self.auto_btn.config(text="■ 자동 중지")
        self.log_q.put("▶ 자동 업로드를 시작했어요. PC가 켜져 있는 동안 정해진 시간에 올립니다.\n")

    def stop_auto(self):
        self.stop_event.set()
        self.auto_btn.config(text="▶ 자동 시작")
        self.log_q.put("■ 자동 업로드를 멈췄어요.\n")
        self.update_status("자동 업로드 꺼짐")

    def toggle_auto(self):
        self.stop_auto() if self.auto_on() else self.start_auto()

    def poll_log(self):
        chunks = []
        while not self.log_q.empty():
            chunks.append(self.log_q.get_nowait())
        if chunks:
            self.log.config(state="normal")
            self.log.insert("end", "".join(chunks))
            self.log.see("end")
            self.log.config(state="disabled")


# ---------------------------------------------------------------- main window
class App:
    def __init__(self, root, autostart=False, resume=()):
        self.root = root
        self.round_lock = threading.Lock()
        self.panels = {}
        root.title(APP_NAME)
        root.geometry("1480x900")
        root.minsize(1200, 700)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._style()
        self._build()
        sys.stdout = sys.stderr = LogWriter(self)
        self._poll()
        self._tick()
        self._schedule_update_check()
        root.after(60_000, self._schedule_rank_check)
        start = [a for a, p in self.panels.items() if config.load_account(a).get("BLOG_ID")] if autostart else resume
        if start:
            root.after(1500, lambda: [self.panels[a].start_auto(quiet=True) for a in start if a in self.panels])
        if autostart:
            root.iconify()
        if not config.load_common()["GOOGLE_API_KEY"]:
            root.after(800, lambda: messagebox.showinfo(
                APP_NAME, "처음 오셨네요!\n\n1. ⚙ 공통 설정에 무료 Google API 키를 넣으세요.\n"
                          "2. 계정마다 🔑 네이버 로그인을 눌러 한 번 로그인하세요 ('로그인 상태 유지' 체크).\n"
                          "3. 👁 미리보기로 글을 확인하고 ▶ 자동 시작을 누르면 끝!"))

    def _style(self):
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        family = "Malgun Gothic" if sys.platform == "win32" else "TkDefaultFont"
        style.configure(".", font=(family, 10))
        style.configure("Title.TLabel", font=(family, 18, "bold"))
        style.configure("Account.TLabel", font=(family, 15, "bold"))
        style.configure("Status.TLabel", font=(family, 10, "bold"))
        style.configure("Accent.TButton", font=(family, 10, "bold"), padding=5)

    def _build(self):
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        head = ttk.Frame(outer)
        head.pack(fill="x", pady=(0, 10))
        ttk.Label(head, text="📝 " + APP_NAME, style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="  네이버 블로그 2계정 · 한국어 SEO 글 + 사진 4~6장 자동 발행", foreground="#666").pack(side="left")
        ttk.Button(head, text="⚙ 공통 설정", style="Accent.TButton", command=lambda: CommonSettings(self)).pack(side="right")
        ttk.Label(head, text=f"버전 {app_version()}   ").pack(side="right")
        self.update_btn = ttk.Button(head, text="새 버전 받기", command=lambda: webbrowser.open(DOWNLOAD_URL))
        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        body.rowconfigure(0, weight=1)
        for i, aid in enumerate(config.ACCOUNTS):
            body.columnconfigure(i, weight=1, uniform="acc")
            panel = self.panels[aid] = AccountPanel(self, body, aid)
            panel.frame.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))

    # ----- Windows startup
    def startup_enabled(self):
        if sys.platform != "win32":
            return False
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, APP_NAME)
                return True
        except OSError:
            return False

    def set_startup(self, enabled):
        if enabled == self.startup_enabled():
            return
        if sys.platform != "win32" or not config.FROZEN:
            if enabled:
                print("Windows 시작 시 자동 실행은 Windows용 .exe에서만 동작합니다.\n")
            return
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{sys.executable}" --autostart')
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except OSError:
                    pass

    # ----- loops
    def _poll(self):
        for panel in self.panels.values():
            panel.poll_log()
        self.root.after(200, self._poll)

    def _tick(self):
        for panel in self.panels.values():
            panel.update_status()
        self.root.after(30_000, self._tick)

    def _schedule_rank_check(self):
        def run():
            for aid in self.panels:
                if config.load_history(aid):
                    _local.aid = aid
                    try:
                        bot.check_ranks(aid)
                    except Exception as e:
                        print(f"(순위 확인 실패: {e})\n")
            _local.aid = None

        threading.Thread(target=run, daemon=True).start()
        self.root.after(RANK_CHECK_MS, self._schedule_rank_check)

    # ----- self-update (same as the Instagram app)
    def check_update(self):
        current = app_version()
        if current == "dev":
            return
        try:
            r = requests.get(f"https://api.github.com/repos/{REPO}/releases/tags/{RELEASE_TAG}", timeout=15)
            body = (r.json().get("body") or "") if r.ok else ""
        except (requests.RequestException, ValueError):
            return
        if not body.startswith("build:") or current in body:
            return
        if config.FROZEN and sys.platform == "win32":
            try:
                self.install_update()
                return
            except Exception as e:
                print(f"자동 업데이트 실패: {e}\n")
        self.root.after(0, lambda: self.update_btn.pack(side="right", padx=8))
        print("⬆ 새 버전이 있습니다. 오른쪽 위 '새 버전 받기'를 누르세요.\n")

    def install_update(self):
        exe = Path(sys.executable)
        new = exe.with_name(exe.name + ".new")
        print("⬆ 새 버전을 받는 중...\n")
        with requests.get(DOWNLOAD_URL, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(new, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        if new.stat().st_size < 5_000_000:
            new.unlink()
            raise RuntimeError("받은 파일이 올바르지 않습니다")
        with self.round_lock:  # never cut off a post halfway
            running = ",".join(a for a, p in self.panels.items() if p.auto_on())
            pid = os.getppid()  # the onefile bootloader holds the .exe open until we exit
            bat = exe.with_name("NaverBlogAuto-update.bat")
            bat.write_text(
                "@echo off\r\n"
                ":wait\r\n"
                f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto wait)\r\n'
                f'move /Y "{new}" "{exe}" >nul\r\n'
                f'start "" "{exe}" {"--resume-auto=" + running if running else ""}\r\n'
                'del "%~f0"\r\n',
                encoding="mbcs",
            )
            subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(exe.parent),
                             creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
            print("⬆ 새 버전으로 다시 시작합니다...\n")
            for panel in self.panels.values():
                panel.stop_event.set()
            self.root.after(500, self.root.destroy)

    def _schedule_update_check(self):
        threading.Thread(target=self.check_update, daemon=True).start()
        self.root.after(UPDATE_CHECK_MS, self._schedule_update_check)

    def on_close(self):
        if any(p.auto_on() for p in self.panels.values()):
            if not messagebox.askyesno(APP_NAME, "창을 닫으면 자동 업로드가 멈춥니다. 닫을까요?\n(최소화하면 계속 동작합니다)"):
                return
        for panel in self.panels.values():
            panel.stop_event.set()
        self.root.destroy()


def run():
    if "--selftest" in sys.argv:
        import selftest

        sys.exit(selftest.run(sys.argv[sys.argv.index("--selftest") + 1]))
    resume = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--resume-auto=")), [])
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NaverBlogAuto.App")
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    try:
        if sys.platform == "win32" and (config.BASE_DIR / "icon.ico").exists():
            root.iconbitmap(default=str(config.BASE_DIR / "icon.ico"))
        root.iconphoto(True, tk.PhotoImage(file=str(config.BASE_DIR / "icon.png")))
    except tk.TclError:
        pass
    App(root, autostart="--autostart" in sys.argv, resume=resume)
    root.mainloop()


if __name__ == "__main__":
    run()
