"""Draws the app icon (icon.png + icon.ico): a green rounded square with a white pencil-and-lines mark."""
from PIL import Image, ImageDraw

SIZE = 256


def draw():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=56, fill=(3, 199, 90))
    for i, width in enumerate((150, 120, 90)):  # text lines
        y = 70 + i * 44
        d.rounded_rectangle([52, y, 52 + width, y + 18], radius=9, fill=(255, 255, 255))
    # pencil
    d.polygon([(150, 206), (214, 142), (234, 162), (170, 226)], fill=(255, 255, 255))
    d.polygon([(150, 206), (170, 226), (138, 236)], fill=(255, 226, 140))
    return img


if __name__ == "__main__":
    icon = draw()
    icon.save("icon.png")
    icon.save("icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon.png, icon.ico")
