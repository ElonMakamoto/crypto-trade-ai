"""The app's look: three background themes (black, green, white) and flat, rounded-feeling buttons.

Everything is drawn with ttk's "clam" theme so colours apply the same way on every Windows version.
"""
import sys
from tkinter import ttk

GREEN = "#03c75a"  # Naver green

THEMES = {
    "black": {"label": "⚫ 블랙", "bg": "#111315", "panel": "#1b1e22", "card": "#23272d", "fg": "#eceef1",
              "sub": "#9aa1ab", "line": "#2f343b", "field": "#262a30", "accent": GREEN, "accent_fg": "#ffffff",
              "accent_hover": "#05b052", "button": "#2b3037", "button_hover": "#353b43", "good": "#3ddc84",
              "warn": "#ffb74d", "bad": "#ff6b6b", "select": "#0f5132"},
    "green": {"label": "🟢 그린", "bg": "#e6f5ec", "panel": "#f4fbf7", "card": "#ffffff", "fg": "#14281d",
              "sub": "#5a7366", "line": "#c9e6d4", "field": "#ffffff", "accent": "#02a84b", "accent_fg": "#ffffff",
              "accent_hover": "#029141", "button": "#d4efdf", "button_hover": "#c2e8d2", "good": "#047a39",
              "warn": "#b26a00", "bad": "#c62828", "select": "#b9e7cb"},
    "white": {"label": "⚪ 화이트", "bg": "#f3f4f6", "panel": "#ffffff", "card": "#ffffff", "fg": "#1f2328",
              "sub": "#6b7280", "line": "#e3e6ea", "field": "#ffffff", "accent": GREEN, "accent_fg": "#ffffff",
              "accent_hover": "#02b351", "button": "#eef0f3", "button_hover": "#e2e5e9", "good": "#0a7d33",
              "warn": "#c06000", "bad": "#c00000", "select": "#cdeedb"},
}
# old hard-coded status colours -> theme keys
STATUS = {"#0a7d33": "good", "#666": "sub", "#c06000": "warn", "#c00000": "bad"}


KOREAN_FONTS = ("Malgun Gothic", "Noto Sans KR", "Noto Sans CJK KR", "NanumGothic", "NanumBarunGothic",
                "Nanum Gothic", "UnDotum", "Baekmuk Gulim", "Apple SD Gothic Neo")
_family = None


def font_family():
    """A font that shows Korean on this system (Malgun Gothic on Windows, Noto/Nanum on Linux)."""
    global _family
    if _family is None:
        if sys.platform == "win32":
            _family = "Malgun Gothic"
        else:
            try:
                from tkinter import font as tkfont

                have = set(tkfont.families())
                _family = next((f for f in KOREAN_FONTS if f in have), "TkDefaultFont")
            except Exception:  # no Tk root yet
                return "TkDefaultFont"
    return _family


def mono_family():
    return "Consolas" if sys.platform == "win32" else font_family()


def palette(name):
    return THEMES.get(name) or THEMES["white"]


def colour(name, status_colour):
    """An old status colour (#0a7d33…) in the current theme."""
    return palette(name).get(STATUS.get(status_colour, ""), status_colour)


def apply(root, name):
    """Style every ttk widget for the theme; returns the palette."""
    p = palette(name)
    f = font_family()
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(bg=p["bg"])
    root.option_add("*Toplevel.background", p["bg"])
    for opt, value in (("background", p["field"]), ("foreground", p["fg"]), ("selectBackground", p["accent"]),
                       ("selectForeground", p["accent_fg"])):
        root.option_add(f"*TCombobox*Listbox.{opt}", value)
    root.option_add("*TCombobox*Listbox.font", (f, 10))

    style.configure(".", background=p["panel"], foreground=p["fg"], font=(f, 10), bordercolor=p["line"],
                    lightcolor=p["panel"], darkcolor=p["panel"], troughcolor=p["bg"], focuscolor=p["accent"],
                    fieldbackground=p["field"], selectbackground=p["accent"], selectforeground=p["accent_fg"],
                    insertcolor=p["fg"])
    style.configure("TFrame", background=p["panel"])
    style.configure("App.TFrame", background=p["bg"])
    style.configure("Card.TFrame", background=p["card"])
    style.configure("TLabel", background=p["panel"], foreground=p["fg"])
    style.configure("App.TLabel", background=p["bg"], foreground=p["fg"])
    style.configure("Title.TLabel", background=p["bg"], foreground=p["fg"], font=(f, 18, "bold"))
    style.configure("AppSub.TLabel", background=p["bg"], foreground=p["sub"])
    style.configure("Account.TLabel", font=(f, 15, "bold"))
    style.configure("Status.TLabel", font=(f, 10, "bold"))
    style.configure("Sub.TLabel", foreground=p["sub"])
    style.configure("Good.TLabel", foreground=p["good"], font=(f, 10, "bold"))

    # buttons: flat, roomy, clear hover/pressed colours
    common = {"borderwidth": 0, "focusthickness": 0, "relief": "flat", "padding": (14, 7)}
    style.configure("TButton", background=p["button"], foreground=p["fg"], font=(f, 10), **common)
    style.map("TButton", background=[("disabled", p["panel"]), ("pressed", p["line"]), ("active", p["button_hover"])],
              foreground=[("disabled", p["sub"])])
    style.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"], font=(f, 10, "bold"),
                    **common)
    style.map("Accent.TButton", background=[("disabled", p["line"]), ("pressed", p["accent_hover"]),
                                            ("active", p["accent_hover"])],
              foreground=[("disabled", p["sub"])])
    style.configure("Head.TButton", background=p["panel"], foreground=p["fg"], font=(f, 10), **common)
    style.map("Head.TButton", background=[("pressed", p["line"]), ("active", p["button_hover"])])
    style.configure("Swatch.TButton", background=p["bg"], foreground=p["sub"], font=(f, 9), borderwidth=0,
                    relief="flat", padding=(8, 5))
    style.map("Swatch.TButton", background=[("active", p["button_hover"])], foreground=[("active", p["fg"])])
    style.configure("SwatchOn.TButton", background=p["accent"], foreground=p["accent_fg"], font=(f, 9, "bold"),
                    borderwidth=0, relief="flat", padding=(8, 5))
    style.map("SwatchOn.TButton", background=[("active", p["accent_hover"])])

    style.configure("TEntry", fieldbackground=p["field"], foreground=p["fg"], bordercolor=p["line"],
                    lightcolor=p["line"], darkcolor=p["line"], padding=5)
    style.map("TEntry", bordercolor=[("focus", p["accent"])], lightcolor=[("focus", p["accent"])],
              fieldbackground=[("readonly", p["panel"])])
    style.configure("TCombobox", fieldbackground=p["field"], background=p["button"], foreground=p["fg"],
                    arrowcolor=p["fg"], bordercolor=p["line"], lightcolor=p["line"], darkcolor=p["line"], padding=4)
    style.map("TCombobox", fieldbackground=[("readonly", p["field"])], foreground=[("readonly", p["fg"])],
              selectbackground=[("readonly", p["field"])], selectforeground=[("readonly", p["fg"])],
              bordercolor=[("focus", p["accent"])], background=[("active", p["button_hover"])])
    style.configure("TCheckbutton", background=p["panel"], foreground=p["fg"], indicatorbackground=p["field"],
                    indicatorforeground=p["accent_fg"], upperbordercolor=p["sub"], lowerbordercolor=p["sub"],
                    indicatormargin=(0, 0, 6, 0))
    style.map("TCheckbutton", indicatorbackground=[("selected", p["accent"])],
              upperbordercolor=[("selected", p["accent"])], lowerbordercolor=[("selected", p["accent"])],
              background=[("active", p["panel"])])

    # tabs: accounts on top, settings/log inside each account
    style.configure("TNotebook", background=p["panel"], borderwidth=0, tabmargins=(0, 4, 0, 0))
    style.configure("TNotebook.Tab", background=p["button"], foreground=p["sub"], padding=(14, 6), borderwidth=0,
                    font=(f, 10))
    style.map("TNotebook.Tab", background=[("selected", p["card"]), ("active", p["button_hover"])],
              foreground=[("selected", p["fg"])])
    style.configure("Accounts.TNotebook", background=p["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure("Accounts.TNotebook.Tab", background=p["bg"], foreground=p["sub"], padding=(18, 9),
                    font=(f, 11, "bold"), borderwidth=0)
    style.map("Accounts.TNotebook.Tab", background=[("selected", p["panel"]), ("active", p["button_hover"])],
              foreground=[("selected", p["accent"])])

    style.configure("Treeview", background=p["card"], fieldbackground=p["card"], foreground=p["fg"], rowheight=26,
                    bordercolor=p["line"])
    style.map("Treeview", background=[("selected", p["select"])], foreground=[("selected", p["fg"])])
    style.configure("Treeview.Heading", background=p["button"], foreground=p["fg"], relief="flat",
                    font=(f, 10, "bold"))
    style.configure("Vertical.TScrollbar", background=p["button"], troughcolor=p["panel"], arrowcolor=p["sub"],
                    bordercolor=p["panel"])
    return p


def text_colours(widget, p, mono=False):
    """Colours for plain tk Text widgets (log, keyword list, memo)."""
    widget.configure(bg=p["card"], fg=p["fg"], insertbackground=p["fg"], selectbackground=p["select"],
                     selectforeground=p["fg"], relief="flat", highlightthickness=1, highlightbackground=p["line"],
                     highlightcolor=p["accent"], borderwidth=8 if not mono else 6)
