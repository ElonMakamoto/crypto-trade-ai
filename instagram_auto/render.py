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
