"""Pubity-style graphics: photo on top, black panel with bold caps headline, accent-coloured keywords."""
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

import config
import l10n

# Japanese has no spaces: break between characters, keeping Latin words/numbers whole and
# closing punctuation on the line before it
CJK_TOKEN = re.compile(r"[A-Za-z0-9.,%'’+\-/:&#@]+\s*|\S\s*")
CLOSERS = set("、。，．・！？!?」』）)]】〉》ー〜…%")


def _font(path, size, weight=None):
    font = ImageFont.truetype(str(path), size)
    if weight:
        try:
            font.set_variation_by_name(weight)
        except (OSError, ValueError):
            pass
    return font


def _hfont(size):
    """Headline font for the post language."""
    return _font(l10n.fonts()[0], size)


def _bfont(size, weight="ExtraBold"):
    """Body font for the post language."""
    return _font(l10n.fonts()[1], size, weight)


def _tfont(size):
    """Typewriter font for the story text on fact slides."""
    return _font(l10n.fonts()[2], size, "Bold")


def _hex(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _tokens(text):
    """[(token, offset)], each token keeping its trailing space so lines can be joined back exactly."""
    # line breaks from the AI become spaces (same length, so highlight offsets still match)
    text = re.sub(r"[\r\n\t\v\f]", " ", text)
    if l10n.lang() != "Japanese" and " " in text.strip():
        return [(m.group(0), m.start()) for m in re.finditer(r"\S+\s*", text)]
    tokens = []
    for m in CJK_TOKEN.finditer(text):
        tok = m.group(0)
        if tokens and tok.strip() and tok.strip()[0] in CLOSERS:
            prev, start = tokens.pop()
            tokens.append((prev.rstrip() + tok, start))
        else:
            tokens.append((tok, m.start()))
    return tokens


def _width(draw, line, font):
    return draw.textlength("".join(tok for tok, _ in line).rstrip(), font=font)


def _wrap(draw, tokens, font, max_width):
    lines, line = [], []
    for token in tokens:
        if line and _width(draw, line + [token], font) > max_width:
            lines.append(line)
            line = [token]
        else:
            line.append(token)
    if line:
        lines.append(line)
    return lines


def _hot(text, highlight):
    """Character offsets of the highlighted phrases (case-insensitive)."""
    if isinstance(highlight, str):
        highlight = [highlight]
    folded, hot = text.casefold(), set()
    for phrase in highlight or []:
        phrase = str(phrase).strip(" .,!?:;'\"").casefold()
        start = folded.find(phrase) if phrase else -1
        while start >= 0:
            hot.update(range(start, start + len(phrase)))
            start = folded.find(phrase, start + 1)
    return hot


def _draw_lines(draw, lines, font, x0, x1, y, line_h, hot=(), **style):
    accent = _hex(config.ACCENT_COLOR)
    for line in lines:
        x = x0 + ((x1 - x0) - _width(draw, line, font)) / 2
        for tok, start in line:
            word = tok.rstrip()
            color = accent if any(i in hot for i in range(start, start + len(word))) else (255, 255, 255)
            draw.text((x, y), word, font=font, fill=color, **style)
            x += draw.textlength(tok, font=font)
        y += line_h


def _fit_line(draw, text, make_font, size, max_width, min_size=20):
    """The largest font (from `size` down) that keeps a single line within max_width."""
    while size > min_size and draw.textlength(text, font=make_font(size)) > max_width:
        size -= 4
    return make_font(size)


# empty space left and right of the text on every slide
SIDE = 110


def draw_headline(img, box, headline, highlight, align="center"):
    """Draw the headline inside box=(x0, y0, x1, y1), vertically centred."""
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    text = headline.upper()
    tokens = _tokens(text)
    for size in range(104, 39, -4):
        font = _hfont(size)
        lines = _wrap(draw, tokens, font, x1 - x0)
        line_h = int(size * 1.15)
        if line_h * len(lines) <= y1 - y0:
            break
    y = y0 + ((y1 - y0) - line_h * len(lines)) // 2
    _draw_lines(draw, lines, font, x0, x1, y, line_h, _hot(text, highlight), stroke_width=2, stroke_fill=(0, 0, 0))


def draw_brand(img, xy, anchor="mm", size=34):
    draw = ImageDraw.Draw(img)
    draw.text(xy, config.BRAND_HANDLE, font=_font(config.FONTS_DIR / "Montserrat-Variable.ttf", size, "Bold"),
              fill=(255, 255, 255), anchor=anchor, stroke_width=1, stroke_fill=(0, 0, 0))


def load_photo(path, size):
    photo = Image.open(path)
    photo = ImageOps.exif_transpose(photo).convert("RGB")
    fitted = ImageOps.fit(photo, size, Image.LANCZOS, centering=(0.5, 0.35))
    if min(photo.width / size[0], photo.height / size[1]) < 1:
        # a small photo blown up: sharpen it back a little
        fitted = fitted.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
    return fitted


def photo_width(path):
    """Width in pixels of a photo (as it is shown, after EXIF rotation); raises if it isn't a readable image."""
    with Image.open(path) as photo:
        return ImageOps.exif_transpose(photo).width


def save_jpeg(img, out_path):
    """Highest-quality JPEG (no colour subsampling, so text edges stay crisp)."""
    img.save(out_path, "JPEG", quality=97, subsampling=0, optimize=True)
    return out_path


def text_card_background(label, out_path, size=(1600, 1200)):
    """A dark accent-gradient backdrop (used when a story has no usable photo)."""
    W, H = size
    accent = _hex(config.ACCENT_COLOR)
    img = Image.new("RGB", (W, H), (12, 12, 12))
    glow = Image.new("RGB", (W, H), tuple(int(c * 0.35) for c in accent))
    mask = Image.radial_gradient("L").resize((W, H)).point(lambda v: 255 - v)
    img.paste(glow, (0, 0), mask)
    draw = ImageDraw.Draw(img)
    for x in range(-H, W, 60):  # subtle diagonal stripes
        draw.line([(x, 0), (x + H, H)], fill=(24, 24, 24), width=3)
    if label:
        font = _font(config.FONTS_DIR / "Anton-Regular.ttf", 150)
        draw.text((W // 2, H // 2), label.upper()[:24], font=font, fill=tuple(min(255, int(c * 0.55)) for c in accent),
                  anchor="mm")
    return save_jpeg(img, out_path)


def feed_post(photo_path, headline, highlight, out_path, swipe=False):
    """1080x1350 (4:5) feed image (the cover slide of a carousel when swipe=True)."""
    W, H, photo_h = 1080, 1350, 820
    img = Image.new("RGB", (W, H), (0, 0, 0))
    img.paste(load_photo(photo_path, (W, photo_h)), (0, 0))
    # soft fade from photo into the black text panel
    fade = Image.linear_gradient("L").resize((W, 160))
    img.paste((0, 0, 0), (0, photo_h - 160, W, photo_h), fade)
    draw_headline(img, (SIDE, photo_h - 40, W - SIDE, H - 90), headline, highlight)
    draw_brand(img, (W // 2, H - 45))
    if swipe:
        ImageDraw.Draw(img).text((W - 40, H - 45), l10n.t("swipe"), font=_bfont(28),
                                 fill=_hex(config.ACCENT_COLOR), anchor="rm")
    return save_jpeg(img, out_path)


def _counter(img, index, total):
    draw = ImageDraw.Draw(img)
    font = _font(config.FONTS_DIR / "Montserrat-Variable.ttf", 28, "Bold")
    text = f"{index}/{total}"
    w = draw.textlength(text, font=font)
    x1, y0 = img.width - 36, 36
    draw.rounded_rectangle((x1 - w - 36, y0, x1, y0 + 52), radius=26, fill=(0, 0, 0))
    draw.text((x1 - 18 - w / 2, y0 + 26), text, font=font, fill=(255, 255, 255), anchor="mm")


def fact_slide(photo_path, text, highlight, index, total, out_path):
    """Carousel slide: full photo, story sentence on a dark panel, slide counter."""
    W, H, photo_h = 1080, 1350, 900
    img = Image.new("RGB", (W, H), (0, 0, 0))
    img.paste(load_photo(photo_path, (W, photo_h)), (0, 0))
    fade = Image.linear_gradient("L").resize((W, 200))
    img.paste((0, 0, 0), (0, photo_h - 200, W, photo_h), fade)
    draw = ImageDraw.Draw(img)
    box_top, box_bottom = photo_h - 60, H - 100
    tokens = _tokens(text)
    for size in range(54, 27, -4):
        font = _tfont(size)
        lines = _wrap(draw, tokens, font, W - 2 * SIDE)
        line_h = int(size * 1.35)
        if line_h * len(lines) <= box_bottom - box_top:
            break
    y = box_top + ((box_bottom - box_top) - line_h * len(lines)) // 2
    _draw_lines(draw, lines, font, SIDE, W - SIDE, y, line_h, _hot(text, highlight))
    _counter(img, index, total)
    draw_brand(img, (W // 2, H - 45))
    return save_jpeg(img, out_path)


def reel_panel(text, highlight, out_path, cover=False, index=None, total=None, size=(1080, 1920)):
    """Transparent 9:16 overlay for a reel scene over stock video: the text on a black panel at the bottom,
    like the post's cover (headline for the cover, the story sentence for the others)."""
    W, H = size
    top = 1120  # the video shows above this
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fade = Image.linear_gradient("L").resize((W, 220))
    img.paste((0, 0, 0, 255), (0, top - 220, W, top), fade)
    img.paste((0, 0, 0, 255), (0, top, W, H))
    box = (SIDE, top - 30, W - SIDE, 1620)  # Instagram's own caption covers the bottom of a reel
    if cover:
        draw_headline(img, box, text, highlight)
    else:
        draw = ImageDraw.Draw(img)
        tokens = _tokens(text)
        for fsize in range(58, 27, -4):
            font = _tfont(fsize)
            lines = _wrap(draw, tokens, font, box[2] - box[0])
            line_h = int(fsize * 1.35)
            if line_h * len(lines) <= box[3] - box[1]:
                break
        y = box[1] + ((box[3] - box[1]) - line_h * len(lines)) // 2
        _draw_lines(draw, lines, font, box[0], box[2], y, line_h, _hot(text, highlight))
        if index and total:
            _counter(img, index, total)
    draw_brand(img, (W // 2, 1670))
    img.save(out_path, "PNG")
    return out_path


def question_slide(photo_path, out_path, index, total):
    """Engagement slide used when a story has nothing more to tell: keeps carousels at 3+ slides."""
    W, H = 1080, 1350
    img = Image.new("RGB", (W, H), (0, 0, 0))
    photo = load_photo(photo_path, (W, H)).filter(ImageFilter.GaussianBlur(12))
    img.paste(Image.eval(photo, lambda v: int(v * 0.35)), (0, 0))
    draw = ImageDraw.Draw(img)
    top, big, sub = l10n.t("question_")
    draw.text((W // 2, H // 2 - 90), top, font=_fit_line(draw, top, _hfont, 140, W - 2 * SIDE), fill=(255, 255, 255),
              anchor="mm")
    draw.text((W // 2, H // 2 + 60), big, font=_fit_line(draw, big, _hfont, 170, W - 2 * SIDE),
              fill=_hex(config.ACCENT_COLOR), anchor="mm")
    draw.text((W // 2, H // 2 + 220), sub, font=_fit_line(draw, sub, _bfont, 42, W - 2 * SIDE), fill=(255, 255, 255),
              anchor="mm")
    _counter(img, index, total)
    draw_brand(img, (W // 2, H - 45))
    return save_jpeg(img, out_path)


def cta_slide(out_path, index, total):
    """Last carousel slide: follow call-to-action."""
    W, H = 1080, 1350
    img = Image.open(text_card_background("", out_path, size=(W, H))).convert("RGB")
    draw = ImageDraw.Draw(img)
    accent = _hex(config.ACCENT_COLOR)
    anton = lambda size: _font(config.FONTS_DIR / "Anton-Regular.ttf", size)  # noqa: E731 (handle is Latin)
    follow, subtitle, actions = l10n.t("follow"), l10n.t("cta_"), l10n.t("actions")
    draw.text((W // 2, H // 2 - 170), follow, font=_fit_line(draw, follow, _hfont, 150, W - 2 * SIDE),
              fill=(255, 255, 255), anchor="mm")
    handle = config.BRAND_HANDLE.upper()
    draw.text((W // 2, H // 2), handle, font=_fit_line(draw, handle, anton, 110, W - 2 * SIDE), fill=accent,
              anchor="mm")
    draw.text((W // 2, H // 2 + 150), subtitle, font=_fit_line(draw, subtitle, _bfont, 40, W - 2 * SIDE),
              fill=(255, 255, 255), anchor="mm")
    draw.text((W // 2, H // 2 + 230), actions, font=_bfont(34, "Bold"), fill=(170, 170, 170), anchor="mm")
    _counter(img, index, total)
    return save_jpeg(img, out_path)


def reel_frame(slide_path, out_path, size=(1080, 1920)):
    """A 4:5 post slide on a 9:16 frame: the slide at full width in the middle over a dark, blurred copy of itself."""
    W, H = size
    slide = Image.open(slide_path).convert("RGB")
    bg = load_photo(slide_path, (W, H)).filter(ImageFilter.GaussianBlur(40))
    bg = Image.eval(bg, lambda v: int(v * 0.4))
    if slide.width != W:
        slide = slide.resize((W, round(slide.height * W / slide.width)), Image.LANCZOS)
    bg.paste(slide, (0, (H - slide.height) // 2))
    return save_jpeg(bg, out_path)


# ---------------------------------------------------------------- learning posts: paper slides with a doodle
PAPER, INK, SOFT = (247, 242, 232), (28, 26, 24), (150, 142, 128)
MARK = (255, 214, 64)  # marker colour behind the key words and inside the doodles
# each channel's own background (paper) and marker colour, so the three accounts look different at a glance
PALETTES = {
    "en": ((255, 226, 112), (255, 255, 255), (120, 98, 30)),   # yellow paper, white marker
    "ko": ((206, 229, 250), (255, 226, 112), (82, 104, 128)),  # pastel blue paper, yellow marker
    "ja": ((252, 218, 230), (255, 255, 255), (138, 92, 108)),  # pastel pink paper, white marker
}


def use_palette(channel=None):
    """Switch the learning-post colours to this channel's palette."""
    global PAPER, MARK, SOFT
    PAPER, MARK, SOFT = PALETTES.get(channel or getattr(config, "CHANNEL", ""), PALETTES["en"])


def _icon(name, size=600):
    """A built-in line doodle (drawn 3x and scaled down so the marker lines are smooth)."""
    import math

    S = size * 3
    img = Image.new("RGB", (S, S), PAPER)
    d = ImageDraw.Draw(img)
    w = S // 34  # marker width
    c = S // 2

    def line(points, fill=INK, width=w):
        pts = [(int(x * S), int(y * S)) for x, y in points]
        d.line(pts, fill=fill, width=width, joint="curve")
        for x, y in (pts[0], pts[-1]):
            d.ellipse((x - width // 2, y - width // 2, x + width // 2, y + width // 2), fill=fill)

    def circle(x, y, r, fill=None, outline=INK):
        box = (int((x - r) * S), int((y - r) * S), int((x + r) * S), int((y + r) * S))
        d.ellipse(box, fill=fill, outline=outline, width=w)

    def person(x, y, s=1.0, arms="down"):
        circle(x, y, 0.07 * s, fill=PAPER)
        line([(x, y + 0.07 * s), (x, y + 0.30 * s)])
        line([(x, y + 0.30 * s), (x - 0.09 * s, y + 0.47 * s)])
        line([(x, y + 0.30 * s), (x + 0.09 * s, y + 0.47 * s)])
        dy = -0.10 * s if arms == "up" else 0.10 * s
        line([(x, y + 0.13 * s), (x - 0.12 * s, y + 0.13 * s + dy)])
        line([(x, y + 0.13 * s), (x + 0.12 * s, y + 0.13 * s + dy)])

    if name == "bulb":
        circle(0.5, 0.40, 0.21, fill=MARK)
        d.rounded_rectangle((int(.41 * S), int(.60 * S), int(.59 * S), int(.74 * S)), radius=w, outline=INK, width=w,
                            fill=PAPER)
        line([(.43, .67), (.57, .67)])
        for a in range(-150, -29, 30):
            r0, r1 = 0.27, 0.34
            line([(0.5 + r0 * math.cos(math.radians(a)), 0.40 + r0 * math.sin(math.radians(a))),
                  (0.5 + r1 * math.cos(math.radians(a)), 0.40 + r1 * math.sin(math.radians(a)))])
    elif name == "brain":
        for x, y, r in ((.40, .40, .13), (.58, .38, .14), (.36, .55, .12), (.62, .55, .13), (.50, .62, .12)):
            circle(x, y, r, fill=MARK)
        for x, y, r in ((.40, .40, .13), (.58, .38, .14), (.36, .55, .12), (.62, .55, .13), (.50, .62, .12)):
            circle(x, y, r - 0.012, fill=MARK, outline=MARK)
        line([(.50, .28), (.48, .42), (.53, .52), (.49, .70)])
    elif name == "heart":
        pts = []
        for i in range(0, 361, 6):
            t = math.radians(i)
            pts.append((0.5 + 0.016 * 16 * math.sin(t) ** 3,
                        0.47 - 0.016 * (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))))
        d.polygon([(int(x * S), int(y * S)) for x, y in pts], fill=MARK)
        line(pts)
    elif name == "coin":
        circle(0.56, 0.56, 0.20, fill=PAPER)
        circle(0.44, 0.44, 0.20, fill=MARK)
        line([(.44, .33), (.44, .55)])
        line([(.50, .39), (.40, .39), (.38, .44), (.50, .45), (.50, .50), (.38, .50)])
    elif name == "clock":
        circle(0.5, 0.5, 0.26, fill=MARK)
        line([(.5, .5), (.5, .32)])
        line([(.5, .5), (.62, .56)])
    elif name == "book":
        d.polygon([(int(x * S), int(y * S)) for x, y in ((.20, .34), (.50, .40), (.50, .72), (.20, .66))], fill=MARK)
        line([(.20, .34), (.50, .40), (.80, .34), (.80, .66), (.50, .72), (.20, .66), (.20, .34)])
        line([(.50, .40), (.50, .72)])
        line([(.58, .46), (.73, .43)])
        line([(.58, .54), (.73, .51)])
    elif name == "people":
        person(0.36, 0.26, 1.0)
        person(0.64, 0.26, 1.0)
        line([(.48, .41), (.52, .41)], fill=MARK, width=w * 2)
    elif name == "star":
        pts = []
        for i in range(11):
            r = 0.27 if i % 2 == 0 else 0.11
            a = math.radians(-90 + i * 36)
            pts.append((0.5 + r * math.cos(a), 0.5 + r * math.sin(a)))
        d.polygon([(int(x * S), int(y * S)) for x, y in pts], fill=MARK)
        line(pts)
    elif name == "mountain":
        line([(.14, .74), (.42, .30), (.56, .52), (.66, .40), (.86, .74), (.14, .74)])
        line([(.42, .30), (.42, .16)])
        d.polygon([(int(x * S), int(y * S)) for x, y in ((.42, .16), (.55, .20), (.42, .25))], fill=MARK)
    elif name == "target":
        for r, f in ((.27, PAPER), (.18, MARK), (.08, PAPER)):
            circle(0.48, 0.52, r, fill=f)
        line([(.48, .52), (.78, .22)])
        line([(.70, .22), (.78, .22), (.78, .30)])
    elif name == "plant":
        line([(.5, .74), (.5, .36)])
        for sx in (-1, 1):
            pts = [(.5, .50), (.5 + sx * .10, .40), (.5 + sx * .22, .40), (.5 + sx * .12, .52), (.5, .50)]
            d.polygon([(int(x * S), int(y * S)) for x, y in pts], fill=MARK)
            line(pts)
        line([(.34, .74), (.66, .74)])
        line([(.38, .74), (.42, .86), (.58, .86), (.62, .74)])
    else:  # thinker: a person with an idea
        person(0.42, 0.34, 1.0, arms="up")
        circle(0.68, 0.24, 0.09, fill=MARK)
        circle(0.57, 0.36, 0.022, fill=INK)
    return img.resize((size, size), Image.LANCZOS)


def _doodle_image(path, icon, size=600):
    """The AI drawing on paper (its white turned into the paper colour), or the built-in icon."""
    from PIL import ImageChops, ImageOps

    if path:
        try:
            art = ImageOps.fit(Image.open(path).convert("RGB"), (size, size), Image.LANCZOS)
            # the drawing's white background becomes the slide's paper; its own colours stay true
            r, g, b = art.split()
            whiteness = ImageChops.darker(ImageChops.darker(r, g), b)
            alpha = whiteness.point(lambda v: max(0, min(255, (255 - v) * 5)))
            paper = Image.new("RGB", (size, size), PAPER)
            paper.paste(art, (0, 0), alpha)
            return paper
        except OSError:
            pass
    return _icon(icon, size)


def _paper_lines(draw, lines, font, x0, x1, y, line_h, hot=()):
    """Centred dark text; key words sit on a marker-yellow stroke."""
    for line in lines:
        x = x0 + ((x1 - x0) - _width(draw, line, font)) / 2
        for tok, start in line:
            word = tok.rstrip()
            if any(i in hot for i in range(start, start + len(word))):
                w = draw.textlength(word, font=font)
                draw.rounded_rectangle((x - 8, y + line_h * 0.12, x + w + 8, y + line_h * 0.92), radius=10, fill=MARK)
            draw.text((x, y), word, font=font, fill=INK)
            x += draw.textlength(tok, font=font)
        y += line_h


def _paper_text(img, text, highlight, box, make_font, sizes, spacing=1.35):
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    tokens = _tokens(text)
    for size in sizes:
        font = make_font(size)
        lines = _wrap(draw, tokens, font, x1 - x0)
        line_h = int(size * spacing)
        if line_h * len(lines) <= y1 - y0:
            break
    y = y0 + ((y1 - y0) - line_h * len(lines)) // 2
    _paper_lines(draw, lines, font, x0, x1, y, line_h, _hot(text, highlight))


def _paper_frame(index, total):
    """Blank paper slide with the account name and the slide counter."""
    W, H = 1080, 1350
    img = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(img)
    small = _font(config.FONTS_DIR / "Montserrat-Variable.ttf", 30, "Bold")
    draw.text((70, 70), config.BRAND_HANDLE, font=small, fill=SOFT, anchor="lm")
    draw.text((W - 70, 70), f"{index}/{total}", font=small, fill=SOFT, anchor="rm")
    return img


def lesson_cover(headline, highlight, art, icon, total, out_path):
    """First slide: the doodle and the big title, with a swipe hint."""
    img = _paper_frame(1, total)
    img.paste(_doodle_image(art, icon, 560), (260, 120))
    _paper_text(img, headline, highlight, (80, 700, 1000, 1180), _hfont, range(96, 43, -4), spacing=1.22)
    draw = ImageDraw.Draw(img)
    draw.text((540, 1262), l10n.t("swipe"), font=_bfont(36, "Bold"), fill=SOFT, anchor="mm")
    return save_jpeg(img, out_path)


def lesson_slide(number, text, highlight, art, icon, index, total, out_path):
    """A lesson slide: its number, the doodle, and one short point."""
    img = _paper_frame(index, total)
    draw = ImageDraw.Draw(img)
    draw.ellipse((480, 120, 600, 240), fill=MARK)
    draw.text((540, 180), str(number), font=_font(config.FONTS_DIR / "Anton-Regular.ttf", 72), fill=INK, anchor="mm")
    img.paste(_doodle_image(art, icon, 520), (280, 260))
    _paper_text(img, text, highlight, (90, 810, 990, 1260), _bfont, range(60, 31, -4))
    return save_jpeg(img, out_path)


def lesson_follow(index, total, out_path):
    """Last slide: follow now, or you won't find this again."""
    W = 1080
    img = _paper_frame(index, total)
    draw = ImageDraw.Draw(img)
    small, big, sub = l10n.t("learn_follow")
    img.paste(_icon("star", 300), (390, 130))
    draw.text((W // 2, 520), small, font=_fit_line(draw, small, _bfont, 50, W - 160), fill=INK, anchor="mm")
    _paper_text(img, big, big, (90, 580, 990, 860), _hfont, range(104, 47, -4), spacing=1.25)
    handle = config.BRAND_HANDLE
    font = _fit_line(draw, handle, lambda s: _font(config.FONTS_DIR / "Anton-Regular.ttf", s), 96, W - 240)
    hw = draw.textlength(handle, font=font)
    draw.rounded_rectangle((W / 2 - hw / 2 - 40, 900, W / 2 + hw / 2 + 40, 1040), radius=30, fill=INK)
    draw.text((W // 2, 970), handle, font=font, fill=MARK, anchor="mm")
    draw.text((W // 2, 1120), sub, font=_fit_line(draw, sub, _bfont, 40, W - 160), fill=INK, anchor="mm")
    draw.text((W // 2, 1220), l10n.t("actions"), font=_bfont(34, "Bold"), fill=SOFT, anchor="mm")
    return save_jpeg(img, out_path)
