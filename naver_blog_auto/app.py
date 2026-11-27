"""Naver Blog Auto — Windows desktop app.

Two Naver accounts side by side. Log in to Naver once per account (🔑 button); after that the app writes
Korean SEO posts with Gemini (free Google AI Studio key) and publishes them at the chosen times by itself.
"""
import os
import queue
import re
import subprocess
import sys
import threading
import time
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
import theme
import timeslots

APP_NAME = "Naver Blog Auto"
REPO = "ElonMakamoto/crypto-trade-ai"
RELEASE_TAG = "naver-blog-auto-latest"
EXE_NAME = "NaverBlogAuto.exe" if sys.platform == "win32" else "NaverBlogAuto-linux"
DOWNLOAD_URL = f"https://github.com/{REPO}/releases/download/{RELEASE_TAG}/{EXE_NAME}"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UPDATE_CHECK_MS = 1 * 3600 * 1000  # check GitHub for a new build every hour
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
        browsers = {"msedge": "Microsoft Edge (Windows 기본)", "chrome": "Google Chrome",
                    "chromium": "Chromium (없으면 앱이 자동으로 받음)"}
        self.browser_box = ttk.Combobox(f, values=list(browsers.values()), state="readonly", width=44)
        self.browser_box.set(browsers.get(values["BROWSER"], browsers["chrome"]))
        self.browsers = browsers
        line("브라우저", self.browser_box)
        ttk.Checkbutton(f, text="글 올릴 때 브라우저 창 보이기 (권장)", variable=self.show).grid(
            row=row, column=1, sticky="w", pady=4)
        row += 1
        ttk.Checkbutton(f, text="컴퓨터 시작할 때 자동 실행 + 자동 업로드 시작", variable=self.startup).grid(
            row=row, column=1, sticky="w", pady=4)
        row += 1
        ttk.Label(f, text="무료 Google 키로 글을 씁니다. 사진은 AI 그림이 안 되는 키면 무료 사진(Pixabay/Pexels 키) 또는\n"
                          "디자인 카드로 자동으로 바뀝니다.", style="Sub.TLabel").grid(row=row, column=0, columnspan=3,
                                                                          sticky="w", pady=(10, 0))
        row += 1
        buttons = ttk.Frame(f)
        buttons.grid(row=row, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="📁 카테고리 연결", command=lambda: CategoryMapWindow(app, top)).pack(side="left", padx=4)
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


class CategoryMapWindow:
    """Which Naver blog category each app category posts into."""

    def __init__(self, app, parent):
        top = self.top = tk.Toplevel(parent)
        top.title("카테고리 연결 — 앱 카테고리 → 네이버 블로그 카테고리")
        top.transient(parent)
        f = ttk.Frame(top, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="네이버 블로그에 만들어 둔 카테고리 이름을 그대로 적으세요. 비우면 AI가 블로그 카테고리 중에서 골라요.",
                  style="Sub.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        current = config.category_map()
        self.vars = {}
        row = 1
        for key, label in config.CHOICES["TOPIC"].items():
            if key in (config.AUTO, "custom"):
                continue
            ttk.Label(f, text=label).grid(row=row, column=0, sticky="w", pady=2, padx=(0, 10))
            var = self.vars[key] = tk.StringVar(value=current.get(key, ""))
            ttk.Entry(f, textvariable=var, width=28).grid(row=row, column=1, sticky="w", pady=2)
            row += 1
        bar = ttk.Frame(f)
        bar.grid(row=row, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bar, text="저장", style="Accent.TButton", command=self.save).pack(side="left", padx=4)
        ttk.Button(bar, text="닫기", command=top.destroy).pack(side="left")

    def save(self):
        config.save_category_map({k: v.get() for k, v in self.vars.items()})
        self.top.destroy()


class UpdateDialog:
    """Small window for the ⬆ 업데이트 button: what's happening, a progress bar, and 다시 설치 / 닫기."""

    def __init__(self, app):
        self.app = app
        top = self.top = tk.Toplevel(app.root)
        top.title("업데이트")
        top.transient(app.root)
        top.resizable(False, False)
        f = ttk.Frame(top, padding=20)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="⬆ 업데이트", style="Account.TLabel").pack(anchor="w")
        self.text = ttk.Label(f, text="새 버전이 있는지 확인하는 중...", wraplength=380)
        self.text.pack(anchor="w", pady=(10, 8))
        self.bar = ttk.Progressbar(f, length=380, mode="indeterminate")
        self.bar.pack(fill="x")
        self.bar.start(12)
        self.buttons = ttk.Frame(f)
        self.buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(self.buttons, text="닫기", command=top.destroy).pack(side="right")
        self.reinstall = ttk.Button(self.buttons, text="다시 설치", command=self.force)

    def alive(self):
        try:
            return bool(self.top.winfo_exists())
        except tk.TclError:
            return False

    def _ui(self, fn):
        if self.alive():
            self.app.root.after(0, fn)

    def say(self, text, done=False, reinstall=False):
        def apply():
            self.text.config(text=text)
            if done:
                self.bar.stop()
                self.bar.config(mode="determinate", value=100 if "✅" in text else 0)
            if reinstall:
                self.reinstall.pack(side="right", padx=6)
        self._ui(apply)

    def progress(self, done, total):
        def apply():
            if str(self.bar.cget("mode")) != "determinate":
                self.bar.stop()
                self.bar.config(mode="determinate", maximum=100)
            self.bar.config(value=100 * done / total)
            self.text.config(text=f"⬇ 받는 중... {done / 1e6:.0f} / {total / 1e6:.0f} MB")
        self._ui(apply)

    def force(self):
        self.reinstall.pack_forget()
        self.say("⬇ 다시 받는 중...")
        self.bar.config(mode="indeterminate")
        self.bar.start(12)
        threading.Thread(target=self.app.check_update, kwargs={"manual": True, "force": True}, daemon=True).start()


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
                  style="Sub.TLabel").pack(side="left")
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

        frame = self.frame = ttk.Frame(parent, padding=14)
        head = ttk.Frame(frame)
        head.pack(fill="x")
        self.title_label = ttk.Label(head, text=config.account_label(aid, values), style="Account.TLabel")
        self.title_label.pack(side="left")
        if aid != "a":
            ttk.Button(head, text="🗑 계정 빼기", command=lambda: self.app.remove_account(self.aid)).pack(side="right",
                                                                                                padx=(6, 0))
        ttk.Button(head, text="로그인 확인", command=self.check_login).pack(side="right")
        ttk.Button(head, text="🔑 네이버 로그인", style="Accent.TButton", command=self.login).pack(side="right", padx=6)
        self.login_label = ttk.Label(frame, text="", style="Status.TLabel")
        self.login_label.pack(fill="x", pady=(4, 6))

        pick_row = ttk.Frame(frame)
        pick_row.pack(fill="x", pady=(0, 6))
        ttk.Label(pick_row, text="이번 글 카테고리", style="Status.TLabel").pack(side="left")
        self.topic_box = choice_box(pick_row, "TOPIC", self.vars["TOPIC"], width=44)
        self.topic_box.pack(side="left", padx=6)
        self.topic_box.bind("<<ComboboxSelected>>", lambda e: self.save(quiet=True), add="+")
        ttk.Label(pick_row, text="기사형: 짧은 줄·인용구 소제목·사진",
                  style="Sub.TLabel").pack(side="left")
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
        self.status_label = ttk.Label(more, text="", style="Good.TLabel")
        self.status_label.pack(side="left", padx=8)

        self.tabs = ttk.Notebook(frame)
        self.tabs.pack(fill="both", expand=True)
        self._build_settings(self.tabs, values)
        self._build_keywords(self.tabs, values)
        log_tab = ttk.Frame(self.tabs, padding=4)
        self.log = scrolledtext.ScrolledText(log_tab, height=16, state="disabled", font=(theme.mono_family(), 9), wrap="word")
        self.log.pack(fill="both", expand=True)
        self.app.register_text(self.log, mono=True)
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
        pair("글 형식", choice_box(tab, "FORMAT", self.vars["FORMAT"]))
        safe = ttk.Frame(tab)
        ttk.Checkbutton(safe, text="🛡 저품질 예방", variable=self.vars["SAFE_MODE"], onvalue="1", offvalue="").pack(side="left")
        ttk.Label(safe, text="  하루 최대").pack(side="left")
        daily = ttk.Combobox(safe, values=["1", "2", "3"], state="readonly", width=3, textvariable=self.vars["DAILY_MAX"])
        daily.pack(side="left", padx=4)
        ttk.Label(safe, text="개").pack(side="left")
        ttk.Label(tab, text="").grid(row=r, column=2)
        safe.grid(row=r, column=2, columnspan=2, sticky="w", padx=10)
        r += 1
        cats = [c for c in config.load_account(self.aid).get("BLOG_CATEGORIES", "").split("|") if c]
        self.category_box = ttk.Combobox(tab, textvariable=self.vars["CATEGORY"], values=[""] + cats)
        pair("카테고리", self.category_box)
        ttk.Label(tab, text="내 블로그 카테고리 목록에서 고르세요 (한 번 글을 올리면 목록이 채워져요). 비우면 AI가 골라 고정",
                  style="Sub.TLabel", wraplength=330).grid(
            row=r, column=2, columnspan=2, sticky="w", padx=10)
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
        ttk.Label(times, text="한국시간 · 매일 ±40분 랜덤", style="Sub.TLabel").pack(side="left")
        r += 1
        bottom = ttk.Frame(tab)
        bottom.grid(row=r, column=0, columnspan=4, sticky="we", pady=(8, 0))
        ttk.Button(bottom, text="💾 저장", style="Accent.TButton", command=self.save).pack(side="left")
        ttk.Button(bottom, text="🤖 전부 자동으로", command=self.all_auto).pack(side="left", padx=6)
        ttk.Label(bottom, text="'자동'은 AI가 키워드마다 알아서 정해요. 한 계정은 한 주제로 꾸준히 쓰는 게 검색에 유리해요.",
                  style="Sub.TLabel", wraplength=420).pack(side="left", padx=6)

    def _build_keywords(self, tabs, values):
        tab = ttk.Frame(tabs, padding=8)
        tabs.add(tab, text="🔑 키워드·메모")
        ttk.Label(tab, text="키워드 목록 — 한 줄에 하나, 위에서부터 씁니다 (이미 쓴 키워드는 건너뜀)").pack(anchor="w")
        self.kw_text = tk.Text(tab, height=7, wrap="none", font=(theme.font_family(), 10))
        self.kw_text.insert("1.0", values["KEYWORDS"])
        self.app.register_text(self.kw_text)
        self.kw_text.pack(fill="x", pady=(2, 4))
        ttk.Checkbutton(tab, text="키워드가 없으면 AI가 알아서 고르기 (네이버·구글 자동완성의 실제 검색어 중 롱테일)",
                        variable=self.auto_kw).pack(anchor="w")
        ttk.Label(tab, text="내 메모 — 실제 경험·가게 정보·내가 아는 사실 (AI는 경험담을 이 메모에서만 씁니다)").pack(
            anchor="w", pady=(8, 0))
        self.memo_text = tk.Text(tab, height=4, wrap="word", font=(theme.font_family(), 10))
        self.memo_text.insert("1.0", values["MEMO"])
        self.app.register_text(self.memo_text)
        self.memo_text.pack(fill="x", pady=(2, 4))
        ttk.Button(tab, text="💾 저장", style="Accent.TButton", command=self.save).pack(anchor="w")

    def all_auto(self):
        for kind in ("TOPIC", "LENGTH", "IMAGE_STYLE", "IMAGE_SOURCE", "IMAGE_COUNT"):
            self.vars[kind].set(config.AUTO)
        self.vars["STYLE"].set("honest_review")
        self.vars["TONE"].set("mom40")
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
        self.app.update_tab(self.aid)
        self.update_status()
        if not quiet:
            self.log_q.put("💾 설정을 저장했어요.\n")

    def reload_fields(self):
        """Pick up values the app changed by itself (blog id, the topic the AI chose)."""
        values = config.load_account(self.aid)
        if hasattr(self, "category_box"):
            self.category_box.config(values=[""] + [c for c in values.get("BLOG_CATEGORIES", "").split("|") if c])
        for key in ("BLOG_ID", "TOPIC_DETAIL", "CATEGORY"):
            if self.vars[key].get() != values[key]:
                self.vars[key].set(values[key])
        self.title_label.config(text=config.account_label(self.aid, values))
        self.app.update_tab(self.aid)
        self.refresh_login()

    def refresh_login(self, text=None, colour=None):
        blog = config.load_account(self.aid).get("BLOG_ID")
        if text is None:
            text, colour = ((f"🟢 로그인됨 · blog.naver.com/{blog}", "#0a7d33") if blog else
                            ("⚪ 아직 로그인 전 — 🔑 네이버 로그인을 눌러 한 번만 로그인하세요", "#666"))
        self.login_label.config(text=text, foreground=theme.colour(self.app.theme_name, colour))

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
                    wait = "" if dry_run else bot.pace_check(self.aid, config.load_account(self.aid))
                    if wait:
                        print(f"🛡 저품질 예방: 이번에는 쉬어요 — {wait}. (끄려면 ⚙ 글 설정 → 저품질 예방 해제)\n")
                        return True
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
            if not isinstance(e, (gemini.GeminiError, naver.EditorError, ValueError, requests.RequestException)):
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
        self.update_lock = threading.Lock()
        self.update_dialog = None
        self.panels = {}
        self.text_widgets = []
        self.theme_name = config.load_common().get("THEME", "white")
        root.title(APP_NAME)
        root.geometry("1480x900")
        root.minsize(1200, 700)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._style()
        self._build()
        sys.stdout = sys.stderr = LogWriter(self)
        self._poll()
        self._tick()
        self.report_update()
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
        self.pal = theme.apply(self.root, self.theme_name)

    def register_text(self, widget, mono=False):
        self.text_widgets.append((widget, mono))
        theme.text_colours(widget, self.pal, mono)

    def set_theme(self, name):
        self.theme_name = name
        config.save_common({"THEME": name})
        self._style()
        for widget, mono in self.text_widgets:
            try:
                theme.text_colours(widget, self.pal, mono)
            except tk.TclError:
                pass
        for key, button in self.swatches.items():
            button.configure(style="SwatchOn.TButton" if key == name else "Swatch.TButton")
        for panel in self.panels.values():
            panel.refresh_login()

    def _build(self):
        outer = ttk.Frame(self.root, padding=(16, 12), style="App.TFrame")
        outer.pack(fill="both", expand=True)
        head = ttk.Frame(outer, style="App.TFrame")
        head.pack(fill="x", pady=(0, 10))
        ttk.Label(head, text="📝 " + APP_NAME, style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="   네이버 블로그 여러 계정 · 기사형 글 + 사진 자동 발행", style="AppSub.TLabel").pack(side="left")
        ttk.Button(head, text="⚙ 공통 설정", style="Head.TButton", command=lambda: CommonSettings(self)).pack(side="right")
        ttk.Button(head, text="➕ 계정 추가", style="Head.TButton", command=self.add_account).pack(side="right", padx=6)
        self.update_now_btn = ttk.Button(head, text=f"⬆ 업데이트  ·  {app_version()}", style="Accent.TButton",
                                         command=self.manual_update)
        self.update_now_btn.pack(side="right", padx=6)
        swatch_box = ttk.Frame(head, style="App.TFrame")
        swatch_box.pack(side="right", padx=10)
        self.swatches = {}
        for key, pal in theme.THEMES.items():
            b = ttk.Button(swatch_box, text=pal["label"], command=lambda k=key: self.set_theme(k),
                           style="SwatchOn.TButton" if key == self.theme_name else "Swatch.TButton")
            b.pack(side="left", padx=1)
            self.swatches[key] = b
        self.update_btn = ttk.Button(head, text="새 버전 직접 받기", command=lambda: webbrowser.open(DOWNLOAD_URL))
        self.account_tabs = ttk.Notebook(outer, style="Accounts.TNotebook")
        self.account_tabs.pack(fill="both", expand=True)
        for aid in config.ACCOUNTS:
            self._add_panel(aid)

    def _add_panel(self, aid):
        panel = self.panels[aid] = AccountPanel(self, self.account_tabs, aid)
        self.account_tabs.add(panel.frame, text=self._tab_text(aid))
        return panel

    def _tab_text(self, aid):
        return f"  {config.account_label(aid)}  "

    def update_tab(self, aid):
        panel = self.panels.get(aid)
        if panel and hasattr(self, "account_tabs"):
            try:
                self.account_tabs.tab(panel.frame, text=self._tab_text(aid))
            except tk.TclError:
                pass

    def add_account(self):
        aid = config.add_account()
        if not aid:
            return messagebox.showinfo(APP_NAME, "계정은 6개까지 넣을 수 있어요.")
        panel = self._add_panel(aid)
        self.account_tabs.select(panel.frame)
        panel.log_q.put(f"➕ {config.ACCOUNTS[aid]}를 추가했어요. 🔑 네이버 로그인을 눌러 블로그에 로그인하세요.\n")

    def remove_account(self, aid):
        panel = self.panels.get(aid)
        if not panel:
            return
        if not messagebox.askyesno(APP_NAME, f"{config.account_label(aid)}을(를) 목록에서 뺄까요?\n"
                                             "(로그인·설정·기록은 지워지지 않아서 다시 추가하면 그대로 돌아와요)"):
            return
        panel.stop_event.set()
        self.account_tabs.forget(panel.frame)
        panel.frame.destroy()
        del self.panels[aid]
        config.remove_account(aid)

    # ----- Windows startup
    AUTOSTART = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / \
        "naver-blog-auto.desktop"

    def startup_enabled(self):
        if sys.platform != "win32":
            return self.AUTOSTART.exists()
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
        if not config.FROZEN:
            if enabled:
                print("컴퓨터 시작 시 자동 실행은 내려받은 프로그램에서만 동작합니다.\n")
            return
        if sys.platform != "win32":  # Linux desktops: an autostart entry
            if enabled:
                self.AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
                self.AUTOSTART.write_text("[Desktop Entry]\nType=Application\nName=Naver Blog Auto\n"
                                          f'Exec="{sys.executable}" --autostart\nX-GNOME-Autostart-enabled=true\n',
                                          encoding="utf-8")
            else:
                self.AUTOSTART.unlink(missing_ok=True)
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
    def manual_update(self):
        if self.update_dialog and self.update_dialog.alive():
            self.update_dialog.top.lift()
            return
        self.update_dialog = UpdateDialog(self)
        threading.Thread(target=self.check_update, kwargs={"manual": True}, daemon=True).start()

    def latest_version(self):
        """The newest build's version: the release's version.txt (no API limits), else the release notes.
        Returns (version or None, error message or "")."""
        try:
            r = requests.get(f"https://github.com/{REPO}/releases/download/{RELEASE_TAG}/version.txt", timeout=20,
                             headers={"Cache-Control": "no-cache"})
            if r.ok and 4 <= len(r.text.strip()) <= 40:
                return r.text.strip(), ""
            r = requests.get(f"https://api.github.com/repos/{REPO}/releases/tags/{RELEASE_TAG}", timeout=20)
            if not r.ok:
                return None, f"GitHub 응답 {r.status_code}"
            body = r.json().get("body") or ""
            m = re.match(r"build:\s*([0-9a-f]{7})", body)
            return (m.group(1), "") if m else (None, "버전 정보를 찾지 못했어요")
        except (requests.RequestException, ValueError) as e:
            return None, f"연결 실패 ({type(e).__name__})"

    def check_update(self, manual=False, force=False):
        """Look for a newer build on GitHub; the packaged app installs it by itself and restarts.
        manual: show progress in the update window; force: install even if the version is the same."""
        dialog = self.update_dialog if manual else None

        def tell(msg, reinstall=False):
            if dialog:
                dialog.say(msg, done=True, reinstall=reinstall)

        if not self.update_lock.acquire(blocking=False):
            return tell("업데이트를 이미 받고 있어요. 잠시만 기다려 주세요.")
        try:
            current = app_version()
            if current == "dev":
                return tell("개발 버전(소스 실행)이라 자동 업데이트는 내려받은 프로그램에서만 동작해요. "
                            "소스는 git pull 로 업데이트하세요.")
            latest, error = self.latest_version()
            if not latest:
                print(f"(업데이트 확인 실패: {error})\n")
                return tell(f"업데이트를 확인하지 못했어요: {error}\n잠시 뒤 다시 눌러 주세요.")
            if dialog:
                dialog.say(f"최신 버전: {latest}  ·  지금: {current}")
            if latest == current and not force:
                return tell(f"✅ 최신 버전이에요 (버전 {current}).", reinstall=config.FROZEN)
            print(f"⬆ 새 버전 {latest}을(를) 받아요 (지금 {current}). 올리는 중인 글이 있으면 끝난 뒤에 바꿉니다.\n")
            if config.FROZEN:
                try:
                    self.install_update(latest, dialog)
                    return
                except Exception as e:
                    print(f"❌ 자동 업데이트 실패: {e}\n")
                    tell(f"자동 업데이트에 실패했어요: {e}\n오른쪽 위 '새 버전 받기'로 직접 받아 주세요.")
            self.root.after(0, lambda: self.update_btn.pack(side="right", padx=8))
        finally:
            self.update_lock.release()

    def download_new(self, new, dialog=None):
        """Download the new .exe completely (3 tries); checks the size against what the server said."""
        last = None
        for attempt in range(3):
            try:
                with requests.get(DOWNLOAD_URL, stream=True, timeout=120, headers={"Cache-Control": "no-cache"}) as r:
                    r.raise_for_status()
                    expected = int(r.headers.get("Content-Length") or 0)
                    done = 0
                    with open(new, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                            done += len(chunk)
                            if dialog and expected:
                                dialog.progress(done, expected)
                size = new.stat().st_size
                if size >= 5_000_000 and (not expected or size == expected):
                    return
                last = f"받은 파일 크기가 맞지 않아요 ({size:,} / {expected:,} bytes)"
            except (requests.RequestException, OSError) as e:
                last = str(e)
            print(f"   다시 받는 중... ({attempt + 1}/3)\n")
            time.sleep(5)
        new.unlink(missing_ok=True)
        raise RuntimeError(last or "다운로드 실패")

    def install_update(self, version, dialog=None):
        exe = Path(sys.executable)
        new = exe.with_name(exe.name + ".new")
        if dialog:
            dialog.say(f"⬇ 새 버전 {version} 받는 중...")
        self.download_new(new, dialog)
        if dialog:
            dialog.say("✅ 다 받았어요. 앱을 새 버전으로 바꾸고 다시 켭니다..." if not self.round_lock.locked() else
                       "글을 올리는 중이라, 끝나는 대로 새 버전으로 바꾸고 다시 켭니다.")
        log = config.DATA_DIR / "update.log"
        if sys.platform != "win32":
            # Linux: a running program file can be replaced directly, then the app restarts itself
            with self.round_lock:
                running = ",".join(a for a, p in self.panels.items() if p.auto_on())
                os.chmod(new, 0o755)
                os.replace(new, exe)
                log.write_text(f"ok {version}", encoding="utf-8")
                print("⬆ 새 버전으로 다시 시작합니다...\n")
                for panel in self.panels.values():
                    panel.stop_event.set()
                args = [str(exe)] + (["--resume-auto=" + running] if running else [])
                self.root.after(500, lambda: os.execv(str(exe), args))
            return
        with self.round_lock:  # never cut off a post halfway
            running = ",".join(a for a, p in self.panels.items() if p.auto_on())
            pid = os.getppid()  # the onefile bootloader holds the .exe open until we exit
            bat = exe.with_name("NaverBlogAuto-update.bat")
            args = "--resume-auto=" + running if running else ""
            # wait for the old app to exit, then retry the swap for up to 2 minutes (antivirus scans and
            # slow exits keep the .exe locked for a while); always restart, and write down what happened
            bat.write_text(
                "@echo off\r\n"
                ":wait\r\n"
                f'tasklist /FI "PID eq {pid}" | find " {pid} " >nul && (timeout /t 1 /nobreak >nul & goto wait)\r\n'
                f'tasklist /FI "PID eq {os.getpid()}" | find " {os.getpid()} " >nul && (timeout /t 1 /nobreak >nul & goto wait)\r\n'
                "set tries=0\r\n"
                ":swap\r\n"
                f'move /Y "{new}" "{exe}" >nul 2>&1 && goto ok\r\n'
                "set /a tries+=1\r\n"
                "if %tries% geq 120 goto fail\r\n"
                "timeout /t 1 /nobreak >nul\r\n"
                "goto swap\r\n"
                ":ok\r\n"
                f'echo ok {version}> "{log}"\r\n'
                f'start "" "{exe}" {args}\r\n'
                "goto end\r\n"
                ":fail\r\n"
                f'echo fail {version}> "{log}"\r\n'
                f'start "" "{exe}" {args}\r\n'
                ":end\r\n"
                'del "%~f0"\r\n',
                encoding="mbcs",
            )
            subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(exe.parent),
                             creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
            print("⬆ 새 버전으로 다시 시작합니다...\n")
            for panel in self.panels.values():
                panel.stop_event.set()
            self.root.after(500, self.root.destroy)

    def report_update(self):
        """After a restart: say whether the last update worked."""
        log = config.DATA_DIR / "update.log"
        try:
            status, version = log.read_text(encoding="mbcs" if sys.platform == "win32" else "utf-8").split()[:2]
        except (OSError, ValueError):
            return
        log.unlink(missing_ok=True)
        if status == "ok" and app_version() == version:
            print(f"✅ 업데이트 완료: 버전 {version}\n")
        else:
            print("❌ 지난 업데이트에서 파일을 바꾸지 못했어요 (백신 프로그램이 막았을 수 있어요). "
                  "오른쪽 위 '새 버전 받기'로 직접 받아 주세요.\n")
            self.root.after(0, lambda: self.update_btn.pack(side="right", padx=8))

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


def ensure_korean_font():
    """Linux: if the system has no Korean font, install the bundled Noto Sans KR for this user (Tk shows boxes
    instead of Korean otherwise)."""
    try:
        out = subprocess.run(["fc-list", ":lang=ko", "family"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return
    if out.strip():
        return
    target = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "fonts"
    source = config.FONTS_DIR / "NotoSansKR-Variable.ttf"
    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / source.name).write_bytes(source.read_bytes())
        subprocess.run(["fc-cache", "-f", str(target)], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass


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
    if sys.platform != "win32":
        ensure_korean_font()
    try:
        root = tk.Tk()
    except tk.TclError as e:
        sys.exit(f"화면(데스크톱)이 없어서 창을 열 수 없어요: {e}\n"
                 "데스크톱에서 실행하거나, 서버에서는 python main.py --account a 처럼 명령줄로 쓰세요.")
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
