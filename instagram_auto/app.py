"""Instagram Auto — Windows desktop app.

Three channels side by side (English, 한국어, 日本語): the same natural disaster news written in each
language and posted to its own Instagram account (same Meta token, a different account ID per channel),
each at its own daily times. Settings live behind the ⚙ 설정 button.
"""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, scrolledtext, simpledialog, ttk

import requests
from PIL import Image, ImageTk

import config
import main as bot
import poster
import timeslots

APP_NAME = "Instagram Auto"
REPO = "ElonMakamoto/crypto-trade-ai"
RELEASE_TAG = "instagram-auto-latest"
DOWNLOAD_URL = f"https://github.com/{REPO}/releases/download/{RELEASE_TAG}/InstagramAuto.exe"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UPDATE_CHECK_MS = 3 * 3600 * 1000  # also check for a new version every 3 hours
TOKEN_HELP_URL = "https://chedlab.org/instagram/#token"

MODES = {"alternate": "하나씩 번갈아 (릴스 → 게시물)", "reel": "릴스만", "post": "게시물만 (3~6장 슬라이드)"}
FOCUSES = {"disasters": "자연재해 뉴스만", "trending": "전체 인기 뉴스"}
COMMON_FIELDS = [
    # key, label, kind
    ("GOOGLE_API_KEY", "Google API 키", "secret"),
    ("IG_ACCESS_TOKEN", "Meta 액세스 토큰 (모든 채널 공통, EAA... 또는 IG...)", "secret"),
    ("NEWS_FOCUS", "뉴스 주제 (모든 채널 공통)", FOCUSES),
    ("ACCENT_COLOR", "강조 색상", "color"),
    ("MUSIC_DIR", "릴스 배경음악 폴더 (선택)", "folder"),
]
CHANNEL_FIELDS = [
    ("ENABLED", "이 채널 사용", "check"),
    ("IG_USER_ID", "인스타 비즈니스 계정 ID", "text"),
    ("CHANNEL_TOKEN", "이 채널 전용 Meta 토큰 (선택 — 비우면 공통 탭의 토큰 사용)", "secret"),
    ("BRAND_HANDLE", "이미지에 넣을 계정명 (예: @chedlab888)", "text"),
    ("POST_TIMES", "자동 업로드 시간 (최대 5개)", "times"),
    ("POST_MODE", "자동 업로드 때 올릴 것", MODES),
]

_local = threading.local()


def app_version():
    try:
        return (config.BASE_DIR / "version.txt").read_text().strip()
    except OSError:
        return "dev"


def open_path(path):
    path = Path(path)
    if not path.suffix:  # a folder: create it so there is something to open
        path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", str(path)])


class LogWriter:
    """print() goes to the log of the channel whose round is running in this thread, else to every log."""

    def __init__(self, app):
        self.app = app

    def write(self, text):
        if not text:
            return
        cid = getattr(_local, "channel", None)
        for panel in self.app.panels.values():
            if cid is None or panel.cid == cid:
                panel.log_q.put(text)

    def flush(self):
        pass


# ---------------------------------------------------------------- settings widgets
def make_field(parent, kind, var, pick_color=None, pick_folder=None):
    """One settings input; returns the widget frame."""
    cell = ttk.Frame(parent)
    if kind == "times":
        boxes = []
        for i in range(timeslots.SLOTS):
            box = ttk.Combobox(cell, state="readonly", values=timeslots.CHOICES, width=10, height=16)
            box.grid(row=0, column=i, padx=(0, 4), sticky="w")
            boxes.append(box)

        def to_var(*_):
            var.set(",".join(b.get() for b in boxes if b.get() and b.get() != timeslots.OFF))

        def to_boxes(*_):
            times = [f"{h:02d}:{m:02d}" for h, m in timeslots.parse(var.get())]
            for i, box in enumerate(boxes):
                box.set(times[i] if i < len(times) else timeslots.OFF)

        for box in boxes:
            box.bind("<<ComboboxSelected>>", to_var)
        var.trace_add("write", to_boxes)
        to_boxes()
    elif isinstance(kind, dict):
        box = ttk.Combobox(cell, state="readonly", values=list(kind.values()), width=40)
        box.bind("<<ComboboxSelected>>", lambda e: var.set(next(k for k, t in kind.items() if t == box.get())))
        var.trace_add("write", lambda *_: box.set(kind.get(var.get(), "")))
        box.set(kind.get(var.get(), ""))
        box.pack(fill="x")
    elif kind == "check":
        ttk.Checkbutton(cell, variable=var, onvalue="1", offvalue="").pack(side="left")
    else:
        entry = ttk.Entry(cell, textvariable=var, width=52, show="•" if kind == "secret" else "")
        entry.pack(side="left", fill="x", expand=True)
        if kind == "secret":
            ttk.Button(cell, text="보기", width=5,
                       command=lambda: entry.config(show="" if entry.cget("show") else "•")).pack(side="left", padx=4)
        elif kind == "color":
            ttk.Button(cell, text="선택", width=5, command=lambda: pick_color(var)).pack(side="left", padx=4)
        elif kind == "folder":
            ttk.Button(cell, text="찾기", width=5, command=lambda: pick_folder(var)).pack(side="left", padx=4)
    return cell


class SettingsWindow:
    """⚙ 설정: common settings + one tab per channel."""

    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title(f"{APP_NAME} · 설정")
        self.win.transient(app.root)
        self.win.resizable(False, False)
        nb = ttk.Notebook(self.win, padding=10)
        nb.pack(fill="both", expand=True)

        saved = config.load_settings()
        self.common = {}
        tab = ttk.Frame(nb, padding=14)
        nb.add(tab, text="  공통  ")
        values = config.current()
        if not saved.get("MUSIC_DIR"):
            values["MUSIC_DIR"] = ""
        for row, (key, label, kind) in enumerate(COMMON_FIELDS):
            ttk.Label(tab, text=label).grid(row=row * 2, column=0, sticky="w", pady=(8 if row else 0, 2))
            var = self.common[key] = tk.StringVar(value=values.get(key, ""))
            make_field(tab, kind, var, self.pick_color, self.pick_folder).grid(row=row * 2 + 1, column=0, sticky="ew")
        row = len(COMMON_FIELDS) * 2
        links = ttk.Frame(tab)
        links.grid(row=row, column=0, sticky="w", pady=(14, 0))
        for text, url in [("Google API 키 발급 →", "https://aistudio.google.com/apikey"),
                          ("Meta 토큰 받는 법 →", TOKEN_HELP_URL)]:
            link = ttk.Label(links, text=text, foreground="#1a73e8", cursor="hand2")
            link.pack(side="left", padx=(0, 16))
            link.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
        self.startup_var = tk.BooleanVar(value=app.startup_enabled())
        ttk.Checkbutton(tab, text="Windows 시작할 때 앱을 켜고, 사용 중인 채널의 자동 업로드 시작",
                        variable=self.startup_var).grid(row=row + 1, column=0, sticky="w", pady=(10, 0))

        self.channels = {}
        for cid, meta in config.CHANNELS.items():
            tab = ttk.Frame(nb, padding=14)
            nb.add(tab, text=f"  {meta['name']}  ")
            ch_values = config.load_channel(cid, saved)
            self.channels[cid] = {}
            for row, (key, label, kind) in enumerate(CHANNEL_FIELDS):
                if key == "POST_TIMES":
                    label = f"{label} — {meta['tz_label']}"
                ttk.Label(tab, text=label).grid(row=row * 2, column=0, sticky="w", pady=(8 if row else 0, 2))
                var = self.channels[cid][key] = tk.StringVar(value=ch_values.get(key, ""))
                make_field(tab, kind, var).grid(row=row * 2 + 1, column=0, sticky="ew")
            written = {"English": "영어", "Korean": "한국어", "Japanese": "일본어"}[meta["language"]]
            note = (f"글은 {written}로 쓰고, 시간은 {meta['tz_label']} 기준입니다. "
                    "전용 토큰을 비우면 공통 탭의 Meta 토큰을 씁니다.")
            ttk.Label(tab, text=note, foreground="#666").grid(row=len(CHANNEL_FIELDS) * 2, column=0, sticky="w",
                                                              pady=(14, 4))
            ttk.Button(tab, text="이 계정 연결 확인", command=lambda c=cid: self.check(c)).grid(
                row=len(CHANNEL_FIELDS) * 2 + 1, column=0, sticky="w")

        buttons = ttk.Frame(self.win, padding=(10, 0, 10, 10))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="닫기", command=self.win.destroy).pack(side="right")
        ttk.Button(buttons, text="저장", style="Accent.TButton", command=self.save).pack(side="right", padx=6)

    def pick_color(self, var):
        color = colorchooser.askcolor(var.get() or "#FFD400", title="강조 색상", parent=self.win)[1]
        if color:
            var.set(color.upper())

    def pick_folder(self, var):
        folder = filedialog.askdirectory(title="mp3 파일이 있는 폴더", parent=self.win)
        if folder:
            var.set(folder)

    def save(self, quiet=False):
        common = {k: v.get().strip() for k, v in self.common.items()}
        color = common["ACCENT_COLOR"]
        if not (color.startswith("#") and len(color) == 7):
            messagebox.showerror(APP_NAME, "강조 색상은 #FFD400 같은 형식이어야 합니다.", parent=self.win)
            return False
        for cid, fields in self.channels.items():
            if fields["ENABLED"].get() and not timeslots.parse(fields["POST_TIMES"].get()):
                messagebox.showerror(APP_NAME, f"{config.CHANNELS[cid]['name']}: 자동 업로드 시간을 하나 이상 골라 주세요.",
                                     parent=self.win)
                return False
        saved = config.load_settings()
        if common.get("IG_ACCESS_TOKEN") != saved.get("IG_ACCESS_TOKEN"):
            saved["TOKEN_REFRESHED_AT"] = ""  # new token: start its refresh clock now
        saved.update(common)
        saved["IG_BACKEND"] = "graph"
        config.save_settings(saved)
        for cid, fields in self.channels.items():
            config.save_channel(cid, {k: v.get() for k, v in fields.items()})
        self.app.set_startup(self.startup_var.get())
        self.app.refresh_panels()
        if not quiet:
            print("✔ 설정을 저장했습니다.\n")
            self.win.destroy()
        return True

    def check(self, cid):
        if not self.save(quiet=True):
            return
        self.app.check_login(cid, parent=self.win)


# ---------------------------------------------------------------- one channel column
class ChannelPanel:
    def __init__(self, app, parent, cid):
        self.app, self.cid, self.meta = app, cid, config.CHANNELS[cid]
        self.log_q = queue.Queue()
        self.stop_event = threading.Event()
        self.auto_thread = None
        self.next_run = None
        self.working = False
        self.preview_imgs = []

        frame = self.frame = ttk.Frame(parent, padding=10, relief="groove")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)
        head = ttk.Frame(frame)
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text=self.meta["name"], style="Channel.TLabel").pack(side="left")
        self.account = tk.StringVar()
        ttk.Label(head, textvariable=self.account, foreground="#666").pack(side="right")

        controls = ttk.Frame(frame)
        controls.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.auto_btn = ttk.Button(controls, text="▶ 자동 시작", style="Accent.TButton", command=self.toggle_auto)
        self.auto_btn.pack(side="left")
        self.buttons = [self.auto_btn]
        for text, kw in [("🎬 릴스", {"only": "reel"}), ("🖼 게시물", {"only": "post"}), ("👁 미리보기", {"dry_run": True})]:
            btn = ttk.Button(controls, text=text, command=lambda kw=kw: self.run_now(**kw))
            btn.pack(side="left", padx=(6, 0))
            self.buttons.append(btn)
        ttk.Button(controls, text="📁", width=3, command=lambda: open_path(config._BASE_OUTPUT_DIR / cid)).pack(
            side="right")

        self.status = tk.StringVar()
        ttk.Label(frame, textvariable=self.status, style="Status.TLabel", wraplength=500).grid(
            row=2, column=0, sticky="w", pady=(8, 6))
        self.preview = ttk.Frame(frame, height=262)
        self.preview.grid(row=3, column=0, sticky="ew")
        self.preview.grid_propagate(False)
        self.log = scrolledtext.ScrolledText(frame, height=12, font=("Consolas", 9), state="disabled", wrap="word")
        self.log.grid(row=4, column=0, sticky="nsew", pady=(6, 0))
        self.show_preview([])
        self.refresh()

    # ----- state
    def settings(self):
        return config.load_channel(self.cid)

    def enabled(self):
        return bool(self.settings()["ENABLED"])

    def auto_on(self):
        return bool(self.auto_thread and self.auto_thread.is_alive() and not self.stop_event.is_set())

    def refresh(self):
        values = self.settings()
        self.account.set(values["BRAND_HANDLE"] if values["ENABLED"] else "사용 안 함")
        state = ["!disabled"] if values["ENABLED"] else ["disabled"]
        for btn in self.buttons:
            btn.state(state)
        if not values["ENABLED"] and self.auto_on():
            self.stop_auto()
        self.update_status()

    def update_status(self, text=None):
        self.status.set(text or self._status_text())

    def _status_text(self):
        if self.working:
            return self.status.get()
        if not self.enabled():
            return "⚪ 꺼짐 · ⚙ 설정에서 '이 채널 사용'을 켜 주세요"
        if self.next_run:
            now = timeslots.now(self.meta["tz"])
            h, m = divmod(max(int((self.next_run - now).total_seconds()), 0) // 60, 60)
            day = "" if self.next_run.date() == now.date() else "내일 "
            return f"🟢 자동 · 다음 {day}{timeslots.describe(self.next_run, self.meta['tz_label'])} · {h}시간 {m}분 후"
        if self.auto_on():
            return "🟢 자동 업로드 켜짐"
        return "⚪ 대기 중"

    def set_status(self, text=None):
        """Thread-safe: None means 'recompute from state'."""
        self.app.root.after(0, lambda: self.update_status(text))

    # ----- running
    def run_now(self, dry_run=False, only=None):
        if not dry_run and not self.app.ready(self.cid):
            return
        threading.Thread(target=self.round, args=(dry_run, only), daemon=True).start()

    def round(self, dry_run=False, only=None):
        _local.channel = self.cid
        what = {"reel": "릴스", "post": "게시물"}.get(only, "")
        self.working = True
        if self.app.round_lock.locked():
            self.set_status("⏳ 다른 채널 작업이 끝나길 기다리는 중...")
        with self.app.round_lock:  # one round at a time across channels (they share the settings module)
            try:
                self.set_status("👁 미리보기 만드는 중..." if dry_run else f"⏫ 뉴스 찾고 {what} 업로드하는 중...")
                print(f"\n=== {datetime.now():%Y-%m-%d %H:%M} {'미리보기' if dry_run else '업로드'} 시작 ===\n")
                config.use_channel(self.cid)
                uploader = None if dry_run else poster.get_poster(self.app.ask_code)
                made = bot.run_once(dry_run=dry_run, poster=uploader, only=only)
                # slide images as they are, videos by their cover frame
                images = [m if m.suffix == ".jpg" else m.with_suffix(".jpg") for m in made]
                images = [m for m in images if m.exists()]
                if images:
                    self.app.root.after(0, self.show_preview, images)
                print("=== 완료 ===\n")
            except Exception as e:
                print(f"❌ 실패: {e}\n")
                traceback.print_exc()
            finally:
                self.working = False
                self.set_status()

    def _auto_loop(self):
        """Upload at the chosen slots in this channel's time zone; checks every 30 s so a sleeping PC or a
        clock change can't skip a slot."""
        _local.channel = self.cid
        tz = self.meta["tz"]
        self.next_run = timeslots.next_slot(timeslots.parse(self.settings()["POST_TIMES"]), tz)
        self.set_status()
        while not self.stop_event.is_set() and self.next_run:
            if timeslots.now(tz) >= self.next_run:
                self.round()
                self.next_run = timeslots.next_slot(timeslots.parse(self.settings()["POST_TIMES"]), tz)
                self.set_status()
            elif self.stop_event.wait(30):
                break
        self.next_run = None
        self.set_status()

    def start_auto(self, quiet=False):
        if self.auto_on() or not self.enabled():
            return
        if not self.app.ready(self.cid, quiet=quiet):
            return
        self.stop_event.clear()
        self.auto_thread = threading.Thread(target=self._auto_loop, daemon=True)
        self.auto_thread.start()
        self.auto_btn.config(text="■ 자동 중지")
        times = ", ".join(f"{h:02d}:{m:02d}" for h, m in timeslots.parse(self.settings()["POST_TIMES"]))
        self.log_q.put(f"▶ 자동 업로드 시작: 매일 {times} ({self.meta['tz_label']}). PC가 켜져 있어야 합니다.\n")

    def stop_auto(self):
        self.stop_event.set()
        self.next_run = None
        self.auto_btn.config(text="▶ 자동 시작")
        self.log_q.put("■ 자동 업로드를 멈췄습니다.\n")
        self.update_status()

    def toggle_auto(self):
        self.stop_auto() if self.auto_on() else self.start_auto()

    # ----- display
    def show_preview(self, paths):
        for child in self.preview.winfo_children():
            child.destroy()
        self.preview_imgs = []
        if not paths:
            ttk.Label(self.preview, text="미리보기가 여기에 나옵니다", foreground="#888").place(relx=0.5, rely=0.5,
                                                                                         anchor="center")
            return
        for i, path in enumerate(paths[:8]):
            img = Image.open(path)
            img.thumbnail((100, 125))
            photo = ImageTk.PhotoImage(img)
            self.preview_imgs.append(photo)  # keep references so Tk doesn't drop the images
            label = ttk.Label(self.preview, image=photo, cursor="hand2")
            label.grid(row=i // 4, column=i % 4, padx=3, pady=3)
            label.bind("<Button-1>", lambda e, p=path: open_path(p))

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
        self._migrate_settings()

        root.title(APP_NAME)
        root.geometry("1680x930")
        root.minsize(1380, 760)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._style()
        self._build()
        sys.stdout = sys.stderr = LogWriter(self)
        self._poll()
        self._tick()
        self._schedule_update_check()
        start = [cid for cid, p in self.panels.items() if p.enabled()] if autostart else list(resume)
        if start:
            root.after(1500, lambda: [self.panels[c].start_auto(quiet=True) for c in start if c in self.panels])
        if autostart:
            root.iconify()

    def _style(self):
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        family = "Malgun Gothic" if sys.platform == "win32" else "TkDefaultFont"
        style.configure(".", font=(family, 10))
        style.configure("Title.TLabel", font=(family, 18, "bold"))
        style.configure("Channel.TLabel", font=(family, 15, "bold"))
        style.configure("Status.TLabel", font=(family, 10, "bold"))
        style.configure("Accent.TButton", font=(family, 10, "bold"), padding=6)

    def _build(self):
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        head = ttk.Frame(outer)
        head.pack(fill="x", pady=(0, 10))
        ttk.Label(head, text="📰 " + APP_NAME, style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="  같은 뉴스를 English · 한국어 · 日本語 로 각 계정에", foreground="#666").pack(side="left")
        ttk.Button(head, text="⚙ 설정", style="Accent.TButton", command=lambda: SettingsWindow(self)).pack(side="right")
        ttk.Label(head, text=f"버전 {app_version()}   ").pack(side="right")
        # fallback when the automatic update can't replace the .exe (e.g. no write permission)
        self.update_btn = ttk.Button(head, text="새 버전 받기", command=lambda: webbrowser.open(DOWNLOAD_URL))
        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        body.rowconfigure(0, weight=1)
        for i, cid in enumerate(config.CHANNELS):
            body.columnconfigure(i, weight=1, uniform="ch")
            panel = self.panels[cid] = ChannelPanel(self, body, cid)
            panel.frame.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0))

    def refresh_panels(self):
        for panel in self.panels.values():
            panel.refresh()

    # ----- settings / checks
    def _migrate_settings(self):
        """Once: users on the old two-per-round default move to one upload per round, alternating."""
        saved = config.load_settings()
        if saved and not saved.get("MODE_MIGRATED"):
            if saved.get("POST_MODE") == "both":
                saved["POST_MODE"] = "alternate"
            saved["MODE_MIGRATED"] = "1"
            config.save_settings(saved)

    def ready(self, cid, quiet=False, parent=None):
        def warn(msg):
            if not quiet:
                messagebox.showwarning(APP_NAME, msg, parent=parent or self.root)
            else:
                self.panels[cid].log_q.put(f"⚠ {msg}\n")
            return False

        # read the saved settings directly: another channel's round may be using the config module
        saved = config.load_settings()
        values, name = config.load_channel(cid, saved), config.CHANNELS[cid]["name"]
        if not values["ENABLED"]:
            return warn(f"{name} 채널이 꺼져 있습니다. ⚙ 설정에서 켜 주세요.")
        if not (values["CHANNEL_TOKEN"] or saved.get("IG_ACCESS_TOKEN") or os.environ.get("IG_ACCESS_TOKEN")):
            return warn("⚙ 설정 → 공통 탭에 Meta 액세스 토큰을 넣어 주세요.")
        if cid != "en" and not values["IG_USER_ID"]:
            return warn(f"⚙ 설정 → {name} 탭에 인스타 비즈니스 계정 ID를 넣어 주세요.")
        if not (saved.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
            if quiet:
                return True
            return messagebox.askyesno(APP_NAME, "Google API 키가 없으면 AI 문구 없이 영어 기사 제목 그대로 올립니다. 계속할까요?",
                                       parent=parent or self.root)
        return True

    def check_login(self, cid, parent=None):
        if not self.ready(cid, parent=parent):
            return

        def check():
            _local.channel = cid
            with self.round_lock:
                try:
                    config.use_channel(cid)
                    name = poster.get_poster(self.ask_code).whoami()["username"]
                    print(f"✔ 인스타 연결 성공: @{name}\n")
                    self.root.after(0, lambda: messagebox.showinfo(APP_NAME, f"{config.CHANNELS[cid]['name']}: "
                                                                             f"연결 성공 @{name}", parent=parent))
                except Exception as e:
                    msg = str(e)
                    print(f"❌ 인스타 연결 실패: {msg}\n")
                    self.root.after(0, lambda: messagebox.showerror(APP_NAME, f"연결 실패\n\n{msg}", parent=parent))

        threading.Thread(target=check, daemon=True).start()

    def ask_code(self, prompt):
        """Called from a worker thread when Instagram wants a security code."""
        answer, done = {}, threading.Event()

        def ask():
            answer["code"] = simpledialog.askstring(APP_NAME, prompt, parent=self.root) or ""
            done.set()

        self.root.after(0, ask)
        done.wait()
        return answer["code"].strip()

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
            if not panel.working:
                panel.update_status()
        self.root.after(30_000, self._tick)

    # ----- self-update
    def check_update(self):
        """Look for a newer release; in the packaged app, install it automatically."""
        current = app_version()
        if current == "dev":
            return
        try:
            r = requests.get(f"https://api.github.com/repos/{REPO}/releases/tags/{RELEASE_TAG}", timeout=15)
            body = r.json().get("body") or "" if r.ok else ""
        except (requests.RequestException, ValueError):
            return
        # release notes start with "build: <sha>"; no release yet means nothing to offer
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
        """Download the new .exe, then swap it in and restart once this process has exited."""
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
        # wait for any running round so an upload is never cut off
        with self.round_lock:
            running = ",".join(cid for cid, p in self.panels.items() if p.auto_on())
            # the onefile bootloader (parent process) holds the .exe open until we exit
            pid = os.getppid()
            bat = exe.with_name("InstagramAuto-update.bat")
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


def selftest(report):
    """Used by the Windows build: check the packaged app can render (all languages), encode and run."""
    import tempfile

    from instagrapi import Client
    import reel
    import render
    import secure_store

    try:
        tmp = Path(tempfile.mkdtemp())
        photo = tmp / "photo.jpg"
        Image.new("RGB", (1200, 900), (40, 90, 160)).save(photo)
        samples = {"English": "SELF TEST HEADLINE WORKS", "Korean": "자체 점검 제목", "Japanese": "セルフテストの見出し"}
        for lang, headline in samples.items():
            config.POST_LANGUAGE = lang
            render.feed_post(photo, headline, [headline.split()[0]], tmp / f"post-{lang}.jpg", swipe=True)
            render.fact_slide(photo, headline + ".", [], 2, 3, tmp / f"slide-{lang}.jpg")
            render.cta_slide(tmp / f"cta-{lang}.jpg", 3, 3)
        card = render.text_card_background("Test", tmp / "card.jpg")
        pick = {"headline": "SELF TEST REEL", "highlight": ["REEL"], "reel_lines": ["one", "two"]}
        video = reel.build_reel([photo, card], pick, tmp, tmp / "reel.mp4")
        reel.extract_cover(video, tmp / "cover.jpg")
        assert secure_store.decrypt(secure_store.encrypt("secret")) == "secret"
        assert Client().user_id is None
        for meta in config.CHANNELS.values():
            assert "/" in str(timeslots.zone(meta["tz"])), f"time zone data missing for {meta['tz']} (tzdata)"
        Path(report).write_text(f"OK {app_version()} {video.stat().st_size} bytes")
        return 0
    except Exception:
        Path(report).write_text(traceback.format_exc())
        return 1


def run():
    if "--selftest" in sys.argv:
        sys.exit(selftest(sys.argv[sys.argv.index("--selftest") + 1]))
    resume = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--resume-auto=")), [])
    if "--resume-auto" in sys.argv:  # older builds restart with a bare flag: resume English
        resume = ["en"]
    root = tk.Tk()
    App(root, autostart="--autostart" in sys.argv, resume=resume)
    root.mainloop()


if __name__ == "__main__":
    run()
