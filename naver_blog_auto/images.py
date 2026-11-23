"""4-6 images per post: a title card (the post's thumbnail), one image per chosen section, and a summary card.

Section images come from (in order, by the account's choice): Gemini drawing -> free stock photo (Pixabay/Pexels
key) -> a designed card. Every card gets its own colours and texture, so no two posts share an identical image
(Naver lowers posts that reuse the same images).
"""
import colorsys
import json
import random
import re
from functools import lru_cache
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont

import config
import gemini

SIZE = 1080
STYLES = ("minimal", "pastel", "dark", "memo", "magazine")
NOTO = "NotoSansKR-Variable.ttf"
DISPLAY = "BlackHanSans-Regular.ttf"

AI_LOOK = {
    "minimal": "bright minimal photograph, soft natural light, clean background",
    "pastel": "soft pastel flat illustration, gentle colours",
    "dark": "moody cinematic photograph, dark background, dramatic light",
    "memo": "cute hand-drawn doodle illustration on paper",
    "magazine": "editorial magazine photograph, vivid colours",
}


# ---------------------------------------------------------------- fonts and text
@lru_cache(maxsize=64)
def font(size, weight=700, display=False):
    path = config.FONTS_DIR / (DISPLAY if display else NOTO)
    try:
        f = ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default(size)
    if not display:
        try:
            f.set_variation_by_axes([weight])
        except (OSError, AttributeError, ValueError):
            pass
    return f


def wrap(text, f, max_w):
    """Break Korean/English text into lines that fit max_w (at spaces; long words by letters)."""
    lines = []
    for raw in str(text).split("\n"):
        line = ""
        for word in raw.split(" "):
            trial = f"{line} {word}".strip()
            if f.getlength(trial) <= max_w:
                line = trial
                continue
            if line:
                lines.append(line)
            line = ""
            for ch in word:  # a single word wider than the box
                if f.getlength(line + ch) > max_w and line:
                    lines.append(line)
                    line = ""
                line += ch
        if line:
            lines.append(line)
    return lines


def fit(text, max_w, max_h, start, smallest, weight=800, display=False, spacing=1.25):
    """The biggest font size (start..smallest) at which the wrapped text fits the box -> (font, lines, line_h)."""
    size = start
    while True:
        f = font(size, weight, display)
        lines = wrap(text, f, max_w)
        line_h = int(size * spacing)
        if len(lines) * line_h <= max_h or size <= smallest:
            return f, lines, line_h
        size -= 4


def draw_lines(d, lines, f, x, y, line_h, fill, align="left", width=0):
    for line in lines:
        lx = x + (width - f.getlength(line)) / 2 if align == "center" else x
        d.text((lx, y), line, font=f, fill=fill)
        y += line_h
    return y


# ---------------------------------------------------------------- colours
def hsv(h, s, v):
    return tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h % 1, s, v))


def palette(style, hue):
    """Colours for a style; one hue per post so all its cards match."""
    if style == "pastel":
        return {"bg": hsv(hue, 0.16, 0.98), "panel": (255, 255, 255), "fg": (40, 40, 55),
                "accent": hsv(hue, 0.55, 0.72), "sub": (110, 110, 125)}
    if style == "dark":
        return {"bg": (20, 22, 28), "bg2": (38, 42, 56), "fg": (245, 245, 248), "accent": hsv(hue, 0.65, 1.0),
                "sub": (170, 172, 185)}
    if style == "memo":
        return {"bg": (253, 248, 236), "line": (226, 216, 192), "fg": (52, 46, 40), "accent": hsv(hue, 0.6, 0.78),
                "sub": (120, 110, 95)}
    if style == "magazine":
        return {"bg": (255, 255, 255), "block": hsv(hue, 0.62, 0.72), "fg": (22, 22, 24),
                "accent": hsv(hue, 0.62, 0.72), "sub": (100, 100, 108)}
    return {"bg": (250, 250, 247), "fg": (25, 25, 32), "accent": hsv(hue, 0.75, 0.85), "sub": (110, 110, 120)}


def background(style, pal, rnd):
    img = Image.new("RGB", (SIZE, SIZE), pal["bg"])
    d = ImageDraw.Draw(img)
    if style == "dark":
        for y in range(SIZE):  # vertical gradient
            t = y / SIZE
            d.line([(0, y), (SIZE, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(pal["bg"], pal["bg2"])))
        for _ in range(60):  # faint dots
            x, y = rnd.randrange(SIZE), rnd.randrange(SIZE)
            d.ellipse([x, y, x + 3, y + 3], fill=(60, 64, 80))
    elif style == "memo":
        for y in range(150, SIZE, 64):
            d.line([(0, y), (SIZE, y)], fill=pal["line"], width=2)
        d.line([(110, 0), (110, SIZE)], fill=(240, 180, 170), width=3)
    elif style == "pastel":
        for _ in range(4):  # soft blobs
            r = rnd.randrange(120, 260)
            x, y = rnd.randrange(-100, SIZE), rnd.randrange(-100, SIZE)
            d.ellipse([x, y, x + r, y + r], fill=tuple(min(255, c + 8) for c in pal["bg"]))
    elif style == "minimal":
        r = rnd.randrange(260, 420)
        x, y = SIZE - r // 2 - rnd.randrange(0, 80), -r // 3
        d.ellipse([x, y, x + r, y + r], fill=tuple(int(c * 0.12 + 250 * 0.88) for c in pal["accent"]))
    return img


def grain(img, rnd, amount=6):
    """A light random texture: makes every image unique without being visible."""
    noise = Image.effect_noise((SIZE // 4, SIZE // 4), rnd.uniform(20, 40)).resize(img.size).convert("RGB")
    return Image.blend(img, noise, amount / 255)


def checkmark(d, x, y, r, colour, fg=(255, 255, 255)):
    d.ellipse([x, y, x + 2 * r, y + 2 * r], fill=colour)
    d.line([(x + r * 0.55, y + r * 1.05), (x + r * 0.9, y + r * 1.4), (x + r * 1.5, y + r * 0.65)], fill=fg,
           width=max(3, r // 4))


# ---------------------------------------------------------------- cards
def title_card(title, keyword, style, rnd, dest, brand="", hue=None):
    pal = palette(style, rnd.random() if hue is None else hue)
    img = background(style, pal, rnd)
    d = ImageDraw.Draw(img)
    text = title.replace("/", "\n")
    chip_f = font(40, 700)
    if style == "magazine":
        block_h = int(SIZE * 0.62)
        d.rectangle([0, 0, SIZE, block_h], fill=pal["block"])
        f, lines, lh = fit(text, SIZE - 160, block_h - 220, 120, 60, display=True, spacing=1.18)
        draw_lines(d, lines, f, 80, block_h - 60 - len(lines) * lh, lh, (255, 255, 255))
        d.text((80, 80), f"# {keyword}", font=chip_f, fill=(255, 255, 255))
        d.rectangle([80, block_h + 70, 200, block_h + 82], fill=pal["block"])
        d.text((80, block_h + 110), "핵심만 정리했어요", font=font(54, 800), fill=pal["fg"])
    elif style == "pastel":
        d.rounded_rectangle([90, 170, SIZE - 90, SIZE - 170], radius=48, fill=pal["panel"])
        f, lines, lh = fit(text, SIZE - 300, 480, 104, 56)
        y = (SIZE - len(lines) * lh) // 2 + 20
        draw_lines(d, lines, f, 150, y, lh, pal["fg"], "center", SIZE - 300)
        w = chip_f.getlength(keyword) + 60
        d.rounded_rectangle([(SIZE - w) / 2, 220, (SIZE + w) / 2, 290], radius=35, fill=pal["accent"])
        d.text(((SIZE - chip_f.getlength(keyword)) / 2, 230), keyword, font=chip_f, fill=(255, 255, 255))
    else:
        left = 150 if style == "memo" else 110
        f, lines, lh = fit(text, SIZE - left - 100, 560, 112, 56)
        y = (SIZE - len(lines) * lh) // 2 + 30
        if style == "memo":  # highlighter behind each line
            for i, line in enumerate(lines):
                yy = y + i * lh
                d.rectangle([left - 10, yy + lh * 0.45, left + f.getlength(line) + 10, yy + lh * 0.92],
                            fill=tuple(int(c * 0.55 + 253 * 0.45) for c in pal["accent"]))
            d.rectangle([SIZE // 2 - 110, 40, SIZE // 2 + 110, 100], fill=pal["accent"])  # tape
        if style == "minimal":
            d.rectangle([left - 40, y + 8, left - 26, y + len(lines) * lh - 8], fill=pal["accent"])
        if style == "dark":
            d.rectangle([left, y + len(lines) * lh + 30, left + 160, y + len(lines) * lh + 42], fill=pal["accent"])
        draw_lines(d, lines, f, left, y, lh, pal["fg"])
        chip_y = y - 120
        w = chip_f.getlength(keyword) + 56
        d.rounded_rectangle([left, chip_y, left + w, chip_y + 72], radius=36, fill=pal["accent"])
        d.text((left + 28, chip_y + 10), keyword, font=chip_f,
               fill=(20, 20, 20) if style == "dark" else (255, 255, 255))
    if brand:
        bf = font(34, 500)
        d.text((SIZE - 70 - bf.getlength(brand), SIZE - 90), brand, font=bf, fill=pal["sub"])
    grain(img, rnd).save(dest)
    return dest


def _list_card(pal, style, rnd, dest, label, heading, items, sub=""):
    """Shared layout of section and summary cards: a label (number or 한눈에 정리), a heading, check-marked items,
    all centred vertically."""
    img = background(style, pal, rnd)
    d = ImageDraw.Draw(img)
    left = 150 if style == "memo" else 110
    right = SIZE - 100
    top, bottom = 120, SIZE - 110
    if style == "pastel":
        d.rounded_rectangle([70, 80, SIZE - 70, SIZE - 80], radius=44, fill=pal["panel"])
        left, right = left + 10, right - 20
    on_dark = style == "dark"
    tick_fg = (20, 20, 20) if on_dark else (255, 255, 255)
    item_fg = (228, 229, 235) if on_dark else pal["fg"]
    if style == "magazine":
        d.rectangle([0, 0, SIZE, 290], fill=pal["block"])
        lf = font(130 if len(label) <= 3 else 92, 800, display=True)
        d.text((left, 145 - lf.size * 0.62), label, font=lf, fill=(255, 255, 255))
        top = 340
        label_h = 0
    else:
        lf = font(120 if len(label) <= 3 else 88, 800, display=False)
        label_h = int(lf.size * 1.25) + (70 if sub else 0)
    hf, hlines, hlh = fit(heading, right - left, 250, 78, 46) if heading else (None, [], 0)
    pf = font(50, 600)
    blocks = [wrap(item, pf, right - left - 92)[:2] for item in items]
    gap = 30
    total = label_h + len(hlines) * hlh + (44 if hlines else 0) + sum(len(b) * 68 + gap for b in blocks)
    while total > bottom - top and blocks:  # too much: drop the last item
        total -= len(blocks[-1]) * 68 + gap
        blocks.pop()
    y = top + max(0, (bottom - top - total) // 2)
    if style != "magazine":
        d.text((left, y), label, font=lf, fill=pal["accent"])
        y += int(lf.size * 1.25)
        if sub:
            d.text((left + 4, y + 4), sub, font=font(40, 600), fill=pal["sub"])
            y += 70
    elif sub:
        d.text((left, y), sub, font=font(40, 600), fill=pal["sub"])
        y += 64
    if hlines:
        y = draw_lines(d, hlines, hf, left, y, hlh, pal["fg"]) + 44
    for lines in blocks:
        checkmark(d, left, y + 9, 26, pal["accent"], tick_fg)
        y = draw_lines(d, lines, pf, left + 92, y, 68, item_fg) + gap
    grain(img, rnd).save(dest)
    return dest


def section_card(number, heading, points, style, rnd, dest, hue=None):
    pal = palette(style, rnd.random() if hue is None else hue)
    return _list_card(pal, style, rnd, dest, f"{number:02d}", heading, points[:3])


def summary_card(items, keyword, style, rnd, dest, hue=None):
    pal = palette(style, rnd.random() if hue is None else hue)
    return _list_card(pal, style, rnd, dest, "한눈에 정리", "", items[:5], sub=keyword)


# ---------------------------------------------------------------- photos
def _used_file():
    return config.STATE_DIR / "used_photos.json"


def _used():
    try:
        return set(json.loads(_used_file().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def _remember(url):
    used = _used()
    used.add(url)
    _used_file().parent.mkdir(parents=True, exist_ok=True)
    _used_file().write_text(json.dumps(sorted(used)[-3000:]), encoding="utf-8")


def openverse(query):
    """Photos from the web that anyone may reuse without credit (public domain / CC0), via Openverse — no key."""
    try:
        r = requests.get("https://api.openverse.org/v1/images/", timeout=20, params={
            "q": query[:100], "license": "cc0,pdm", "page_size": 20, "size": "large", "mature": "false"},
            headers={"User-Agent": "NaverBlogAuto/1.0"})
        if not r.ok:
            return []
        return [x["url"] for x in r.json().get("results", []) if x.get("url") and (x.get("width") or 1000) >= 700]
    except (requests.RequestException, ValueError, KeyError):
        return []


def stock_photo(query, dest, rnd):
    """A photo from the web for this topic, not used in an earlier post: Pixabay/Pexels when a key is set,
    otherwise free-to-reuse photos found on the web (no credit needed)."""
    common = config.load_common()
    urls = []
    try:
        if common["PIXABAY_API_KEY"]:
            r = requests.get("https://pixabay.com/api/", timeout=20, params={
                "key": common["PIXABAY_API_KEY"], "q": query[:100], "image_type": "photo", "per_page": 20,
                "safesearch": "true", "orientation": "horizontal"})
            if r.ok:
                urls += [h.get("largeImageURL") or h.get("webformatURL") for h in r.json().get("hits", [])]
        if common["PEXELS_API_KEY"] and len(urls) < 5:
            r = requests.get("https://api.pexels.com/v1/search", timeout=20,
                             headers={"Authorization": common["PEXELS_API_KEY"]},
                             params={"query": query, "per_page": 20})
            if r.ok:
                urls += [p["src"].get("large2x") or p["src"].get("large") for p in r.json().get("photos", [])]
    except (requests.RequestException, ValueError, KeyError):
        return None
    if len(urls) < 3:
        urls += openverse(query)
    used = _used()
    fresh = [u for u in urls if u and u not in used]
    if not fresh:
        return None
    url = rnd.choice(fresh[:8])
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 NaverBlogAuto/1.0"})
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGB")
        if img.width < 500:
            return None
    except (requests.RequestException, OSError):
        return None
    _remember(url)
    return save_photo(img, dest)


def save_photo(img, dest):
    if img.width > SIZE:
        img = img.resize((SIZE, int(img.height * SIZE / img.width)), Image.LANCZOS)
    img.save(dest, quality=90)
    return dest


def ai_image(query, heading, style, dest):
    prompt = (f"{query or heading}. Topic: {heading}. Style: {AI_LOOK.get(style, AI_LOOK['minimal'])}. "
              "Square image, clear subject, no text, no letters, no numbers, no watermark, no logos.")
    raw = dest.with_suffix(".raw")
    if not gemini.draw(prompt, raw):
        return None
    try:
        img = Image.open(raw).convert("RGB")
    except OSError:
        return None
    finally:
        raw.unlink(missing_ok=True)
    return save_photo(img, dest)


# ---------------------------------------------------------------- the set for one post
def slug(text):
    return re.sub(r'[\\/:*?"<>|\s]+', "-", text).strip("-")[:40] or "post"


def pick_sections(n_sections, n_images):
    """Which sections get an image: evenly spread over the post."""
    k = min(n_sections, max(0, n_images - 2))
    if k <= 0:
        return []
    step = n_sections / k
    return sorted({min(n_sections - 1, int(i * step)) for i in range(k)})


def middle_sections(n_sections, k):
    """k section positions spread over the post, the first one in the middle."""
    if k <= 0 or n_sections <= 0:
        return []
    picks = [min(n_sections - 1, int((j + 1) * n_sections / (k + 1))) for j in range(k)]
    return sorted(set(picks))


def photo(query, dest, source, style, heading, rnd):
    """A real photo for the query (web), else an AI drawing; None if neither works."""
    made = None
    if query and source in (config.AUTO, "stock"):
        made = stock_photo(query, dest.with_suffix(".jpg"), rnd)
        if not made and len(query.split()) > 2:  # too specific: try the first words
            made = stock_photo(" ".join(query.split()[:2]), dest.with_suffix(".jpg"), rnd)
    if not made and source in (config.AUTO, "ai"):
        made = ai_image(query, heading, style, dest.with_suffix(".jpg"))
    return made


def make(post, keyword, account, out_dir, seed=""):
    """Images for a post -> [{"path", "caption", "place"}]. A real photo about the post at the very top, photos in
    the middle sections, the summary card, and a real photo at the very end. place: "top", ("section", i),
    "summary", "end"."""
    rnd = random.Random(f"{keyword}|{seed}")
    style = account.get("IMAGE_STYLE", config.AUTO)
    if style not in STYLES:
        style = post.get("image_style") or rnd.choice(STYLES)
    source = account.get("IMAGE_SOURCE", config.AUTO)
    count = account.get("IMAGE_COUNT", config.AUTO)
    sections = post.get("sections", [])
    n_images = int(count) if count in ("4", "5", "6") else max(4, min(6, len(sections) + 1))
    photos = post.get("photos") or {}
    fallback_query = next((s.get("image", {}).get("query_en") for s in sections if s.get("image", {}).get("query_en")),
                          "")
    base = slug(keyword)
    out = []
    hue = rnd.random()
    print(f"🖼 이미지 {n_images}장 만드는 중 (맨 위·중간·맨 끝 관련 사진)")

    def dest():
        return out_dir / f"{base}_{len(out) + 1}"

    top = photo(photos.get("top") or fallback_query, dest(), source, style, post["title"], rnd)
    if not top:  # no photo found: the designed title card
        top = title_card(post.get("thumbnail_title") or post["title"], keyword, style, rnd,
                         dest().with_suffix(".png"), account.get("NICKNAME", ""), hue)
    out.append({"path": top, "caption": "", "place": "top"})
    for number, i in enumerate(middle_sections(len(sections), n_images - 3), 1):
        sec = sections[i]
        image = sec.get("image", {})
        query = (photos.get("middle") if number == 1 else "") or image.get("query_en")
        made = photo(query, dest(), source, style, sec["heading"], rnd)
        if not made:
            points = image.get("points") or [re.sub(r"\*\*", "", p)[:60] for p in sec.get("paragraphs", [])[:2]]
            made = section_card(number, sec["heading"], points, style, rnd, dest().with_suffix(".png"), hue)
        out.append({"path": made, "caption": image.get("caption", ""), "place": ("section", i)})
    summary = post.get("summary") or [s["heading"] for s in sections[:4]]
    out.append({"path": summary_card(summary, keyword, style, rnd, dest().with_suffix(".png"), hue), "caption": "",
                "place": "summary"})
    end = photo(photos.get("end") or photos.get("top") or fallback_query, dest(), source, style, post["title"], rnd)
    if end:
        out.append({"path": end, "caption": "", "place": "end"})
    print(f"   사진 {sum(1 for o in out if str(o['path']).endswith('.jpg'))}장 + 카드 "
          f"{sum(1 for o in out if str(o['path']).endswith('.png'))}장")
    return out
