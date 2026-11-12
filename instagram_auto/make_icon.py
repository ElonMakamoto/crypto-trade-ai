"""Draws the app icon (a camera on a warm gradient tile) as icon.ico and icon.png for the build."""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

HERE = Path(__file__).parent
SIZE = 1024


def _gradient():
    """Purple top right through pink to orange and yellow at the bottom left."""
    stops = [(0.0, (254, 218, 117)), (0.3, (250, 126, 30)), (0.55, (214, 41, 118)), (0.8, (150, 47, 191)),
             (1.0, (79, 91, 213))]
    small = Image.new("RGB", (256, 256))
    px = small.load()
    for y in range(256):
        for x in range(256):
            t = min(1.0, max(0.0, (x + (255 - y)) / 510))
            for (a, ca), (b, cb) in zip(stops, stops[1:]):
                if t <= b:
                    f = (t - a) / (b - a)
                    px[x, y] = tuple(round(ca[i] + (cb[i] - ca[i]) * f) for i in range(3))
                    break
    return small.resize((SIZE, SIZE), Image.BICUBIC)


def draw():
    tile = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(tile).rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=230, fill=255)
    glyph = Image.new("L", (SIZE, SIZE), 0)
    g = ImageDraw.Draw(glyph)
    w = 78  # white line width of the camera outline
    g.rounded_rectangle((200, 200, 824, 824), radius=170, outline=255, width=w)
    g.ellipse((362, 362, 662, 662), outline=255, width=w)
    g.ellipse((660, 300, 740, 380), fill=255)
    img = _gradient().convert("RGBA")
    img.putalpha(tile)
    white = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 255))
    white.putalpha(ImageChops.multiply(glyph, tile))
    return Image.alpha_composite(img, white)


if __name__ == "__main__":
    icon = draw()
    icon.resize((256, 256), Image.LANCZOS).save(HERE / "icon.png")
    icon.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote icon.ico and icon.png")
