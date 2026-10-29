"""Pubity-style graphics: photo on top, black panel with bold caps headline, accent-coloured keywords."""
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

import config

HEADLINE_FONT = config.FONTS_DIR / "Anton-Regular.ttf"
BRAND_FONT = config.FONTS_DIR / "Montserrat-Variable.ttf"


def _font(path, size, weight=None):
    font = ImageFont.truetype(str(path), size)
    if weight:
        try:
            font.set_variation_by_name(weight)
        except (OSError, ValueError):
            pass
    return font


def _hex(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _wrap(draw, words, font, max_width):
    lines, line = [], []
    for word in words:
        trial = " ".join(line + [word])
        if line and draw.textlength(trial, font=font) > max_width:
            lines.append(line)
            line = [word]
        else:
            line.append(word)
    if line:
        lines.append(line)
    return lines


def _fit_headline(draw, text, max_width, max_height, start=120, min_size=48):
    words = text.split()
    for size in range(start, min_size - 1, -4):
        font = _font(HEADLINE_FONT, size)
        lines = _wrap(draw, words, font, max_width)
        line_h = int(size * 1.12)
        if line_h * len(lines) <= max_height:
            return font, lines, line_h
    font = _font(HEADLINE_FONT, min_size)
    return font, _wrap(draw, words, font, max_width), int(min_size * 1.12)


def _highlight_words(highlight):
    if isinstance(highlight, str):
        highlight = [highlight]
    return {w.strip(".,!?:;'\"").upper() for phrase in highlight or [] for w in phrase.split()}


def draw_headline(img, box, headline, highlight, align="center"):
    """Draw the headline inside box=(x0, y0, x1, y1), vertically centred."""
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    font, lines, line_h = _fit_headline(draw, headline.upper(), x1 - x0, y1 - y0)
    accent, hot = _hex(config.ACCENT_COLOR), _highlight_words(highlight)
    space = draw.textlength(" ", font=font)
    y = y0 + ((y1 - y0) - line_h * len(lines)) // 2
    for line in lines:
        width = draw.textlength(" ".join(line), font=font)
        x = x0 + ((x1 - x0) - width) / 2 if align == "center" else x0
        for word in line:
            color = accent if word.strip(".,!?:;'\"") in hot else (255, 255, 255)
            draw.text((x, y), word, font=font, fill=color, stroke_width=2, stroke_fill=(0, 0, 0))
            x += draw.textlength(word, font=font) + space
        y += line_h


def draw_brand(img, xy, anchor="mm", size=34):
    draw = ImageDraw.Draw(img)
    draw.text(xy, config.BRAND_HANDLE, font=_font(BRAND_FONT, size, "Bold"),
              fill=(255, 255, 255), anchor=anchor, stroke_width=1, stroke_fill=(0, 0, 0))


def load_photo(path, size):
    photo = Image.open(path)
    photo = ImageOps.exif_transpose(photo).convert("RGB")
    return ImageOps.fit(photo, size, Image.LANCZOS, centering=(0.5, 0.35))


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
        font = _font(HEADLINE_FONT, 150)
        draw.text((W // 2, H // 2), label.upper()[:24], font=font, fill=tuple(min(255, int(c * 0.55)) for c in accent),
                  anchor="mm")
    img.save(out_path, "JPEG", quality=92)
    return out_path


def feed_post(photo_path, headline, highlight, out_path):
    """1080x1350 (4:5) feed image."""
    W, H, photo_h = 1080, 1350, 820
    img = Image.new("RGB", (W, H), (0, 0, 0))
    img.paste(load_photo(photo_path, (W, photo_h)), (0, 0))
    # soft fade from photo into the black text panel
    fade = Image.linear_gradient("L").resize((W, 160))
    img.paste((0, 0, 0), (0, photo_h - 160, W, photo_h), fade)
    draw_headline(img, (60, photo_h - 40, W - 60, H - 90), headline, highlight)
    draw_brand(img, (W // 2, H - 45))
    img.save(out_path, "JPEG", quality=92)
    return out_path


def reel_background(photo_path, out_path, size=(1296, 2304)):
    """Blurred full-bleed backdrop with the sharp photo in the middle (oversized for the zoom)."""
    W, H = size
    bg = load_photo(photo_path, (W, H)).filter(ImageFilter.GaussianBlur(40))
    bg = Image.eval(bg, lambda v: int(v * 0.45))
    fg = load_photo(photo_path, (W, int(W * 0.9)))
    bg.paste(fg, (0, int(H * 0.30)))
    bg.save(out_path, "JPEG", quality=92)
    return out_path


def reel_overlay(headline, highlight, sub_line, out_path, size=(1080, 1920)):
    """Transparent PNG with headline (top), story line (bottom) and handle."""
    W, H = size
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shade = Image.new("RGBA", (W, 620), (0, 0, 0, 200))
    img.alpha_composite(shade, (0, 0))
    draw_headline(img, (60, 170, W - 60, 600), headline, highlight)
    if sub_line:
        band = Image.new("RGBA", (W, 300), (0, 0, 0, 170))
        img.alpha_composite(band, (0, H - 520))
        draw = ImageDraw.Draw(img)
        font = _font(BRAND_FONT, 50, "ExtraBold")
        lines = _wrap(draw, sub_line.split(), font, W - 140)[:3]
        y = H - 520 + (300 - 64 * len(lines)) // 2
        for line in lines:
            draw.text((W // 2, y), " ".join(line), font=font, fill=(255, 255, 255), anchor="mt")
            y += 64
    draw_brand(img, (W // 2, H - 150), size=40)
    img.save(out_path, "PNG")
    return out_path
