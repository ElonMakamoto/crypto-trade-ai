"""Instagram Auto — Windows desktop app.

Enter the Google API key and Instagram login once, press Start, and the app posts a
Pubity-style news post + reel every few hours while the PC is on.
"""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, scrolledtext, simpledialog, ttk

import requests
from PIL import Image, ImageTk

import config
import main as bot
import poster

APP_NAME = "Instagram Auto"
REPO = "ElonMakamoto/crypto-trade-ai"
RELEASE_TAG = "instagram-auto-latest"
DOWNLOAD_URL = f"https://github.com/{REPO}/releases/download/{RELEASE_TAG}/InstagramAuto.exe"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UPDATE_CHECK_MS = 3 * 3600 * 1000  # also check for a new version every 3 hours

FIELDS = [
    # key, label, kind
    ("GOOGLE_API_KEY", "Google API 키", "secret"),
    ("IG_BACKEND", "인스타 연결 방식", "backend"),
    ("IG_ACCESS_TOKEN", "인스타 액세스 토큰 (IG... 또는 EAA... 토큰)", "secret"),
    ("IG_USER_ID", "인스타 비즈니스 계정 ID (선택, EAA 토큰용)", "text"),
    ("IG_USERNAME", "인스타 아이디", "text"),
    ("IG_PASSWORD", "인스타 비밀번호", "secret"),
    ("BRAND_HANDLE", "이미지에 넣을 계정명", "text"),
    ("ACCENT_COLOR", "강조 색상", "color"),
    ("INTERVAL_HOURS", "업로드 간격 (시간)", "text"),
    ("POST_MODE", "올릴 것", "mode"),
    ("MUSIC_DIR", "릴스 배경음악 폴더 (선택)", "folder"),
]
MODES = {"both": "게시물 + 릴스", "post": "게시물만", "reel": "릴스만"}
BACKENDS = {"graph": "공식 API (추천)", "instagrapi": "아이디 / 비밀번호 (비공식)"}
CHOICES = {"mode": MODES, "backend": BACKENDS}
# which fields each login method needs
BACKEND_FIELDS = {"graph": {"IG_ACCESS_TOKEN", "IG_USER_ID"}, "instagrapi": {"IG_USERNAME", "IG_PASSWORD"}}
TOKEN_HELP_URL = "https://chedlab.org/instagram/#token"


def app_version():
    try:
        return (config.BASE_DIR / "version.txt").read_text().strip()
    except OSError:
        return "dev"


class LogWriter:
    """Sends print() output to the log box (the windowed .exe has no console)."""

    def __init__(self, q):
        self.q = q

    def write(self, text):
        if text:
            self.q.put(text)

    def flush(self):
        pass


class App:
    def __init__(self, root, autostart=False, resume=False):
        self.root = root
        self.log_q = queue.Queue()
        sys.stdout = sys.stderr = LogWriter(self.log_q)
        self.busy = threading.Lock()
        self.stop_event = threading.Event()
        self.auto_thread = None
        self.next_run = None
        self.preview_img = None

        root.title(APP_NAME)
        root.geometry("980x720")
        root.minsize(860, 660)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._style()
        self._build()
        self._load_values()
        self._poll_log()
        self._tick()
        self._schedule_update_check()
        if autostart or resume:
            root.after(1500, self.start_auto)
        if autostart:
            root.iconify()

    # ---------- UI ----------
    def _style(self):
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        family = "Malgun Gothic" if sys.platform == "win32" else "TkDefaultFont"
        self.font = (family, 10)
        style.configure(".", font=self.font)
        style.configure("Title.TLabel", font=(family, 18, "bold"))
        style.configure("Status.TLabel", font=(family, 11, "bold"))
        style.configure("Accent.TButton", font=(family, 11, "bold"), padding=8)

    def _build(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(1, weight=1)

        head = ttk.Frame(outer)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Label(head, text="📰 " + APP_NAME, style="Title.TLabel").pack(side="left")
        # fallback when the automatic update can't replace the .exe (e.g. no write permission)
        self.update_btn = ttk.Button(head, text="새 버전 받기", command=lambda: webbrowser.open(DOWNLOAD_URL))
        ttk.Label(head, text=f"버전 {app_version()}").pack(side="right")

        # settings
        form = ttk.LabelFrame(outer, text=" 설정 ", padding=12)
        form.grid(row=1, column=0, sticky="nsw", padx=(0, 12))
        self.vars, self.rows = {}, {}
        for row, (key, label, kind) in enumerate(FIELDS):
            lbl = ttk.Label(form, text=label)
            lbl.grid(row=row * 2, column=0, sticky="w", pady=(6 if row else 0, 2))
            var = tk.StringVar()
            self.vars[key] = var
            cell = ttk.Frame(form)
            cell.grid(row=row * 2 + 1, column=0, sticky="ew")
            self.rows[key] = (lbl, cell)
            if kind in CHOICES:
                options = CHOICES[kind]
                box = ttk.Combobox(cell, state="readonly", values=list(options.values()), width=34)
                box.bind("<<ComboboxSelected>>", lambda e, b=box, v=var, o=options: v.set(
                    next(k for k, t in o.items() if t == b.get())))
                var.trace_add("write", lambda *_, b=box, v=var, o=options: b.set(o.get(v.get(), "")))
                box.pack(fill="x")
                continue
            entry = ttk.Entry(cell, textvariable=var, width=30, show="•" if kind == "secret" else "")
            entry.pack(side="left", fill="x", expand=True)
            if kind == "secret":
                ttk.Button(cell, text="보기", width=4,
                           command=lambda e=entry: e.config(show="" if e.cget("show") else "•")).pack(side="left", padx=(4, 0))
            elif kind == "color":
                ttk.Button(cell, text="선택", width=4, command=lambda v=var: self.pick_color(v)).pack(side="left", padx=(4, 0))
            elif kind == "folder":
                ttk.Button(cell, text="찾기", width=4, command=lambda v=var: self.pick_folder(v)).pack(side="left", padx=(4, 0))

        links = ttk.Frame(form)
        links.grid(row=len(FIELDS) * 2, column=0, sticky="w", pady=(10, 0))
        for text, url in [("Google API 키 발급 →", "https://aistudio.google.com/apikey"),
                          ("인스타 토큰 받는 법 →", TOKEN_HELP_URL)]:
            link = ttk.Label(links, text=text, foreground="#1a73e8", cursor="hand2")
            link.pack(side="left", padx=(0, 12))
            link.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
        self.startup_var = tk.BooleanVar(value=self.startup_enabled())
        ttk.Checkbutton(form, text="Windows 시작할 때 자동 실행", variable=self.startup_var,
                        command=self.toggle_startup).grid(row=len(FIELDS) * 2 + 1, column=0, sticky="w", pady=(8, 0))
        buttons = ttk.Frame(form)
        buttons.grid(row=len(FIELDS) * 2 + 2, column=0, sticky="ew", pady=(12, 0))
        buttons.columnconfigure((0, 1), weight=1)
        ttk.Button(buttons, text="설정 저장", command=self.save).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(buttons, text="인스타 연결 확인", command=self.check_login).grid(row=0, column=1, sticky="ew")
        self.vars["IG_BACKEND"].trace_add("write", lambda *_: self._show_login_fields())

        # right side: controls, preview, log
        right = ttk.Frame(outer)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        controls = ttk.Frame(right)
        controls.grid(row=0, column=0, sticky="ew")
        self.auto_btn = ttk.Button(controls, text="▶ 자동 업로드 시작", style="Accent.TButton", command=self.toggle_auto)
        self.auto_btn.pack(side="left")
        ttk.Button(controls, text="지금 바로 올리기", command=lambda: self.run_now(dry_run=False)).pack(side="left", padx=6)
        ttk.Button(controls, text="미리보기만 만들기", command=lambda: self.run_now(dry_run=True)).pack(side="left")
        ttk.Button(controls, text="결과 폴더", command=self.open_output).pack(side="left", padx=6)

        self.status = tk.StringVar(value="대기 중")
        ttk.Label(right, textvariable=self.status, style="Status.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 6))

        body = ttk.Frame(right)
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self.preview = ttk.Label(body, text="미리보기\n(아직 없음)", anchor="center", width=28, relief="groove")
        self.preview.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        self.log = scrolledtext.ScrolledText(body, height=20, font=("Consolas", 9), state="disabled", wrap="word")
        self.log.grid(row=0, column=1, sticky="nsew")

    # ---------- settings ----------
    def _show_login_fields(self):
        needed = BACKEND_FIELDS.get(self.vars["IG_BACKEND"].get(), set())
        for key in set().union(*BACKEND_FIELDS.values()):
            for widget in self.rows[key]:
                widget.grid() if key in needed else widget.grid_remove()

    def _load_values(self):
        values = config.current()
        if not config.load_settings().get("MUSIC_DIR"):
            values["MUSIC_DIR"] = ""
        for key, var in self.vars.items():
            var.set(values.get(key, ""))

    def collect(self):
        values = {k: v.get().strip() for k, v in self.vars.items()}
        try:
            hours = float(values["INTERVAL_HOURS"])
            assert hours >= 1
        except (ValueError, AssertionError):
            raise ValueError("업로드 간격은 1 이상의 숫자로 넣어 주세요.")
        if not values["ACCENT_COLOR"].startswith("#") or len(values["ACCENT_COLOR"]) != 7:
            raise ValueError("강조 색상은 #FFD400 같은 형식이어야 합니다.")
        return values

    def save(self, quiet=False):
        try:
            values = self.collect()
        except ValueError as e:
            messagebox.showerror(APP_NAME, str(e))
            return False
        saved = config.load_settings()
        if values.get("IG_ACCESS_TOKEN") != saved.get("IG_ACCESS_TOKEN"):
            saved["TOKEN_REFRESHED_AT"] = ""  # new token: start its refresh clock now
        saved.update(values)
        config.save_settings(saved)
        if not quiet:
            print("✔ 설정을 저장했습니다.\n")
        return True

    def pick_color(self, var):
        color = colorchooser.askcolor(var.get() or "#FFD400", title="강조 색상")[1]
        if color:
            var.set(color.upper())

    def pick_folder(self, var):
        folder = filedialog.askdirectory(title="mp3 파일이 있는 폴더")
        if folder:
            var.set(folder)

    def open_output(self):
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(config.OUTPUT_DIR)
        else:
            subprocess.Popen(["xdg-open", str(config.OUTPUT_DIR)])

    # ---------- Windows startup ----------
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

    def toggle_startup(self):
        if sys.platform != "win32" or not config.FROZEN:
            messagebox.showinfo(APP_NAME, "이 기능은 Windows용 .exe에서만 동작합니다.")
            self.startup_var.set(False)
            return
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if self.startup_var.get():
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{sys.executable}" --autostart')
                print("✔ Windows 시작 시 자동으로 켜지고 자동 업로드를 시작합니다.\n")
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except OSError:
                    pass
                print("✔ 자동 실행을 껐습니다.\n")

    # ---------- running ----------
    def ask_code(self, prompt):
        """Called from the worker thread when Instagram wants a security code."""
        answer, done = {}, threading.Event()

        def ask():
            answer["code"] = simpledialog.askstring(APP_NAME, prompt, parent=self.root) or ""
            done.set()

        self.root.after(0, ask)
        done.wait()
        return answer["code"].strip()

    def _round(self, dry_run):
        if not self.busy.acquire(blocking=False):
            print("이미 실행 중입니다. 끝날 때까지 기다려 주세요.\n")
            return
        try:
            self._set_status("미리보기 만드는 중..." if dry_run else "뉴스 찾고 업로드하는 중...")
            print(f"\n=== {datetime.now():%Y-%m-%d %H:%M} {'미리보기' if dry_run else '업로드'} 시작 ===\n")
            uploader = None if dry_run else poster.get_poster(self.ask_code)
            made = bot.run_once(dry_run=dry_run, poster=uploader)
            images = [m for m in made if m.suffix == ".jpg"] or [m.with_suffix(".jpg") for m in made]
            if images and images[0].exists():
                self.root.after(0, self.show_preview, images[0])
            print("=== 완료 ===\n")
        except Exception as e:
            print(f"❌ 실패: {e}\n")
            traceback.print_exc()
        finally:
            self.busy.release()
            self._set_status(None)

    def run_now(self, dry_run):
        if not self.save(quiet=True):
            return
        if not dry_run and not self._ready():
            return
        threading.Thread(target=self._round, args=(dry_run,), daemon=True).start()

    def _ready(self):
        if config.IG_BACKEND == "graph" and not config.IG_ACCESS_TOKEN:
            messagebox.showwarning(APP_NAME, "인스타 액세스 토큰(IG... 또는 EAA...)을 넣어 주세요.\n('인스타 토큰 받는 법'을 참고하세요)")
            return False
        if config.IG_BACKEND == "instagrapi" and not (config.IG_USERNAME and config.IG_PASSWORD):
            messagebox.showwarning(APP_NAME, "인스타 아이디와 비밀번호를 넣어 주세요.")
            return False
        if not config.GOOGLE_API_KEY:
            return messagebox.askyesno(APP_NAME, "Google API 키가 없으면 AI 문구 없이 뉴스 제목 그대로 올립니다. 계속할까요?")
        return True

    def check_login(self):
        if not self.save(quiet=True) or not self._ready():
            return

        def check():
            try:
                uploader = poster.get_poster(self.ask_code)
                name = uploader.whoami()["username"] if hasattr(uploader, "whoami") else config.IG_USERNAME
                if config.IG_USER_ID:  # show an auto-detected business account id in its field
                    self.root.after(0, lambda: self.vars["IG_USER_ID"].set(config.IG_USER_ID))
                print(f"✔ 인스타 연결 성공: @{name}\n")
                self.root.after(0, lambda: messagebox.showinfo(APP_NAME, f"연결 성공: @{name}"))
            except Exception as e:
                msg = str(e)
                print(f"❌ 인스타 연결 실패: {msg}\n")
                self.root.after(0, lambda: messagebox.showerror(APP_NAME, f"연결 실패\n\n{msg}"))

        threading.Thread(target=check, daemon=True).start()

    def _auto_loop(self):
        while not self.stop_event.is_set():
            self._round(dry_run=False)
            self.next_run = datetime.now() + timedelta(hours=config.INTERVAL_HOURS)
            self._set_status(None)
            if self.stop_event.wait(config.INTERVAL_HOURS * 3600):
                break
        self.next_run = None

    def start_auto(self):
        if self.auto_thread and self.auto_thread.is_alive():
            return
        if not self.save(quiet=True) or not self._ready():
            return
        self.stop_event.clear()
        self.auto_thread = threading.Thread(target=self._auto_loop, daemon=True)
        self.auto_thread.start()
        self.auto_btn.config(text="■ 자동 업로드 중지")
        print(f"▶ 자동 업로드 시작: {config.INTERVAL_HOURS:g}시간마다 올립니다. (PC가 켜져 있어야 합니다)\n")

    def stop_auto(self):
        self.stop_event.set()
        self.next_run = None
        self.auto_btn.config(text="▶ 자동 업로드 시작")
        print("■ 자동 업로드를 멈췄습니다.\n")

    def toggle_auto(self):
        if self.auto_thread and self.auto_thread.is_alive() and not self.stop_event.is_set():
            self.stop_auto()
        else:
            self.start_auto()

    def _set_status(self, text):
        """Thread-safe: None means 'recompute from state'."""
        self.root.after(0, lambda: self.status.set(text or self._status_text()))

    def _status_text(self):
        if self.busy.locked():
            return self.status.get()
        if self.next_run:
            left = self.next_run - datetime.now()
            h, m = divmod(max(int(left.total_seconds()), 0) // 60, 60)
            return f"🟢 자동 업로드 켜짐 · 다음 업로드 {self.next_run:%H:%M} ({h}시간 {m}분 후)"
        if self.auto_thread and self.auto_thread.is_alive() and not self.stop_event.is_set():
            return "🟢 자동 업로드 켜짐"
        return "⚪ 대기 중 · '자동 업로드 시작'을 누르세요"

    def show_preview(self, path):
        img = Image.open(path)
        img.thumbnail((230, 300))
        self.preview_img = ImageTk.PhotoImage(img)
        self.preview.config(image=self.preview_img, text="")

    def _poll_log(self):
        chunks = []
        while not self.log_q.empty():
            chunks.append(self.log_q.get_nowait())
        if chunks:
            self.log.config(state="normal")
            self.log.insert("end", "".join(chunks))
            self.log.see("end")
            self.log.config(state="disabled")
        self.root.after(200, self._poll_log)

    def _tick(self):
        if not self.busy.locked():
            self.status.set(self._status_text())
        self.root.after(30_000, self._tick)

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
        with self.busy:
            resume = bool(self.auto_thread and self.auto_thread.is_alive() and not self.stop_event.is_set())
            # the onefile bootloader (parent process) holds the .exe open until we exit
            pid = os.getppid()
            bat = exe.with_name("InstagramAuto-update.bat")
            bat.write_text(
                "@echo off\r\n"
                ":wait\r\n"
                f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto wait)\r\n'
                f'move /Y "{new}" "{exe}" >nul\r\n'
                f'start "" "{exe}" {"--resume-auto" if resume else ""}\r\n'
                'del "%~f0"\r\n',
                encoding="mbcs",
            )
            subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(exe.parent),
                             creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
            print("⬆ 새 버전으로 다시 시작합니다...\n")
            self.stop_event.set()
            self.root.after(500, self.root.destroy)

    def _schedule_update_check(self):
        threading.Thread(target=self.check_update, daemon=True).start()
        self.root.after(UPDATE_CHECK_MS, self._schedule_update_check)

    def on_close(self):
        if self.auto_thread and self.auto_thread.is_alive() and not self.stop_event.is_set():
            if not messagebox.askyesno(APP_NAME, "창을 닫으면 자동 업로드가 멈춥니다. 닫을까요?\n(최소화하면 계속 동작합니다)"):
                return
        self.stop_event.set()
        self.root.destroy()


def selftest(report):
    """Used by the Windows build: check the packaged app can render, encode and log in-ready."""
    import tempfile
    from pathlib import Path

    from instagrapi import Client
    import reel
    import render
    import secure_store

    try:
        tmp = Path(tempfile.mkdtemp())
        photo = tmp / "photo.jpg"
        Image.new("RGB", (1200, 900), (40, 90, 160)).save(photo)
        render.feed_post(photo, "SELF TEST HEADLINE WORKS", ["SELF", "TEST"], tmp / "post.jpg")
        pick = {"headline": "SELF TEST REEL", "highlight": ["REEL"], "reel_lines": ["one", "two"]}
        video = reel.build_reel(photo, pick, tmp, tmp / "reel.mp4")
        reel.extract_cover(video, tmp / "cover.jpg")
        assert secure_store.decrypt(secure_store.encrypt("secret")) == "secret"
        assert Client().user_id is None
        Path(report).write_text(f"OK {app_version()} {video.stat().st_size} bytes")
        return 0
    except Exception:
        Path(report).write_text(traceback.format_exc())
        return 1


def run():
    if "--selftest" in sys.argv:
        sys.exit(selftest(sys.argv[sys.argv.index("--selftest") + 1]))
    root = tk.Tk()
    App(root, autostart="--autostart" in sys.argv, resume="--resume-auto" in sys.argv)
    root.mainloop()


if __name__ == "__main__":
    run()
